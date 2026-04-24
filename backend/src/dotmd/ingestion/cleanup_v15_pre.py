"""Pre-migration cleanup for Phase 15 (content-addressed chunk_ids).

Removes two classes of orphan rows accumulated over prior migrations:

  1. Chunks for files that no longer have a fingerprint row (file deleted
     from disk, cleanup never ran).
  2. Legacy 32-char MD5 chunk rows that have no corresponding vec_meta
     entry for any active embedding model — ghosts left by a buggy
     ``_purge_file()`` during the 2026-04-03 MD5->BLAKE2b migration.

After this cleanup completes successfully, the remaining chunk_ids in
``chunks_*`` tables all have a consistent set of companion rows
(vec_meta, chunks_fts, chunk_fingerprints) and ``migration_v15`` can
safely remap them to 64-char blake3 without collisions.

Run standalone against a stopped container's volume:

    python -m dotmd.ingestion.cleanup_v15_pre /path/to/index.db [--apply]

Without ``--apply`` the script is dry-run: it reports what WOULD be
removed and exits without mutating the database.
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _discover_strategies(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'chunks_%' AND name NOT LIKE 'chunks_fts_%'"
    ).fetchall()
    return [r[0].removeprefix("chunks_") for r in rows]


def _vec_meta_tables(conn: sqlite3.Connection, strategy: str) -> list[str]:
    return [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
            (f"vec_meta_{strategy}_%",),
        ).fetchall()
    ]


def _vec0_table_for_meta(meta_table: str) -> str:
    # vec_meta_heading_512_50_e5  ->  vec_chunks_heading_512_50_e5
    return "vec_chunks_" + meta_table.removeprefix("vec_meta_")


def _delete_chunks(
    conn: sqlite3.Connection,
    strategy: str,
    chunk_ids: list[str],
) -> dict[str, int]:
    """Cascade-delete a batch of chunk_ids across all related tables.

    Deletes vec0 rowids, vec_meta rows, chunks_fts rows, chunks rows.
    Does NOT commit — caller wraps the whole cleanup in one transaction.
    Returns per-table deletion counts for reporting.
    """
    if not chunk_ids:
        return {}
    counts: dict[str, int] = {}

    chunks_table = f"chunks_{strategy}"
    fts_table = f"chunks_fts_{strategy}"

    # Batch to stay under SQLite's parameter limit (~32k).
    BATCH = 500

    for meta_table in _vec_meta_tables(conn, strategy):
        vec0_table = _vec0_table_for_meta(meta_table)
        meta_deleted = 0
        vec0_deleted = 0
        for i in range(0, len(chunk_ids), BATCH):
            batch = chunk_ids[i:i + BATCH]
            placeholders = ",".join("?" * len(batch))
            rowids = [
                r[0] for r in conn.execute(
                    f"SELECT rowid FROM {meta_table} WHERE chunk_id IN ({placeholders})",
                    batch,
                ).fetchall()
            ]
            if rowids:
                rid_ph = ",".join("?" * len(rowids))
                conn.execute(
                    f"DELETE FROM {vec0_table} WHERE rowid IN ({rid_ph})",
                    rowids,
                )
                vec0_deleted += len(rowids)
            cur = conn.execute(
                f"DELETE FROM {meta_table} WHERE chunk_id IN ({placeholders})",
                batch,
            )
            meta_deleted += cur.rowcount
        counts[meta_table] = meta_deleted
        counts[vec0_table] = vec0_deleted

    fts_deleted = 0
    chunks_deleted = 0
    for i in range(0, len(chunk_ids), BATCH):
        batch = chunk_ids[i:i + BATCH]
        placeholders = ",".join("?" * len(batch))
        fts_cur = conn.execute(
            f"DELETE FROM {fts_table} WHERE chunk_id IN ({placeholders})",
            batch,
        )
        fts_deleted += fts_cur.rowcount
        chunk_cur = conn.execute(
            f"DELETE FROM {chunks_table} WHERE chunk_id IN ({placeholders})",
            batch,
        )
        chunks_deleted += chunk_cur.rowcount
    counts[fts_table] = fts_deleted
    counts[chunks_table] = chunks_deleted

    return counts


def _delete_fingerprints_for_files(
    conn: sqlite3.Connection,
    strategy: str,
    file_paths: list[str],
) -> dict[str, int]:
    """Delete chunk/embed fingerprint rows for given file paths."""
    if not file_paths:
        return {}
    counts: dict[str, int] = {}
    BATCH = 500

    fp_tables = [
        r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND (name LIKE ? OR name LIKE ?)",
            (f"chunk_fingerprints_{strategy}", f"embed_fingerprints_{strategy}_%"),
        ).fetchall()
    ]

    for fp_table in fp_tables:
        deleted = 0
        for i in range(0, len(file_paths), BATCH):
            batch = file_paths[i:i + BATCH]
            placeholders = ",".join("?" * len(batch))
            cur = conn.execute(
                f"DELETE FROM {fp_table} WHERE file_path IN ({placeholders})",
                batch,
            )
            deleted += cur.rowcount
        if deleted:
            counts[fp_table] = deleted
    return counts


def plan_cleanup(conn: sqlite3.Connection) -> dict:
    """Compute cleanup plan without mutating anything.

    Returns a dict {strategy: {step1_ids, step2_ids, step1_files}} where
    step1_ids = orphan chunks for deleted files (no fingerprint row),
    step2_ids = legacy chunks with no vec_meta entry for any active model.
    """
    plan: dict[str, dict] = {}
    for strategy in _discover_strategies(conn):
        chunks_table = f"chunks_{strategy}"
        fp_table = f"chunk_fingerprints_{strategy}"

        # Step 1: chunks with file_path not present in chunk_fingerprints
        step1_ids = [
            r[0] for r in conn.execute(
                f"SELECT c.chunk_id FROM {chunks_table} c "
                f"LEFT JOIN {fp_table} fp ON fp.file_path = c.file_path "
                f"WHERE fp.file_path IS NULL"
            ).fetchall()
        ]
        step1_files = sorted({
            r[0] for r in conn.execute(
                f"SELECT DISTINCT c.file_path FROM {chunks_table} c "
                f"LEFT JOIN {fp_table} fp ON fp.file_path = c.file_path "
                f"WHERE fp.file_path IS NULL"
            ).fetchall()
        })

        # Step 2: non-64-char chunks that have no vec_meta row for any model.
        # These are ghost rows left by the 2026-04-03 hash swap — they are
        # invisible to semantic search (no vector) and at most a FTS remnant.
        vec_meta_tables = _vec_meta_tables(conn, strategy)
        if vec_meta_tables:
            not_exists = " AND ".join(
                f"NOT EXISTS(SELECT 1 FROM {vm} v WHERE v.chunk_id = c.chunk_id)"
                for vm in vec_meta_tables
            )
            step2_sql = (
                f"SELECT c.chunk_id FROM {chunks_table} c "
                f"WHERE length(c.chunk_id) != 64 AND {not_exists}"
            )
            # Exclude step1 ids — they are already covered.
            step1_set = set(step1_ids)
            step2_ids = [
                r[0] for r in conn.execute(step2_sql).fetchall()
                if r[0] not in step1_set
            ]
        else:
            step2_ids = []

        plan[strategy] = {
            "step1_ids": step1_ids,
            "step1_files": step1_files,
            "step2_ids": step2_ids,
        }
    return plan


def run_cleanup(index_db_path: Path, apply: bool) -> int:
    """Main entrypoint. Returns exit code."""
    if not index_db_path.exists():
        print(f"ERROR: {index_db_path} not found", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(index_db_path))
    try:
        plan = plan_cleanup(conn)

        total_step1 = sum(len(p["step1_ids"]) for p in plan.values())
        total_step2 = sum(len(p["step2_ids"]) for p in plan.values())

        print()
        print("=" * 70)
        print("PRE-MIGRATION CLEANUP PLAN")
        print("=" * 70)
        for strategy, p in plan.items():
            print(f"\n[{strategy}]")
            print(f"  Step 1 (orphan files, chunks without fingerprints):")
            print(f"      {len(p['step1_ids'])} chunks across "
                  f"{len(p['step1_files'])} files")
            if p["step1_files"][:3]:
                print(f"      e.g. {p['step1_files'][0]}")
            print(f"  Step 2 (legacy non-64-char chunks without vec_meta):")
            print(f"      {len(p['step2_ids'])} chunks")

        print()
        print(f"TOTAL: {total_step1} orphan chunks + {total_step2} ghost chunks "
              f"= {total_step1 + total_step2} rows")

        if not apply:
            print()
            print("DRY-RUN — no changes made. Re-run with --apply to execute.")
            return 0

        print()
        print("Applying cleanup...")
        print()

        conn.execute("BEGIN")
        try:
            for strategy, p in plan.items():
                if p["step1_ids"]:
                    counts = _delete_chunks(conn, strategy, p["step1_ids"])
                    print(f"[{strategy}] Step 1 deletions: {counts}")
                    fp_counts = _delete_fingerprints_for_files(
                        conn, strategy, p["step1_files"],
                    )
                    if fp_counts:
                        print(f"[{strategy}] Step 1 fingerprint deletions: {fp_counts}")
                if p["step2_ids"]:
                    counts = _delete_chunks(conn, strategy, p["step2_ids"])
                    print(f"[{strategy}] Step 2 deletions: {counts}")
            conn.execute("COMMIT")
        except Exception:
            conn.execute("ROLLBACK")
            raise

        # Post-cleanup verification
        print()
        print("Post-cleanup state:")
        for strategy in _discover_strategies(conn):
            chunks_table = f"chunks_{strategy}"
            total = conn.execute(f"SELECT COUNT(*) FROM {chunks_table}").fetchone()[0]
            dist = dict(conn.execute(
                f"SELECT length(chunk_id), COUNT(*) FROM {chunks_table} "
                f"GROUP BY length(chunk_id)"
            ).fetchall())
            print(f"  {chunks_table}: total={total}, id-length distribution={dist}")

        return 0
    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_db_path", type=Path)
    parser.add_argument("--apply", action="store_true",
                        help="Apply cleanup (default: dry-run only)")
    args = parser.parse_args()
    return run_cleanup(args.index_db_path, args.apply)


if __name__ == "__main__":
    sys.exit(main())
