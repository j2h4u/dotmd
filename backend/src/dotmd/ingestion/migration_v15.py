"""One-time migration to content-addressed chunk_ids (Phase 15).

Replaces path-based blake2b chunk_ids (128-char) with content-addressed
blake3(body_checksum:chunk_index:chunk_strategy) chunk_ids (64-char).

Pre-conditions (MUST be satisfied before running):
  1. Plans 15-01 and 15-02 deployed and at least one full index cycle completed.
  2. dotmd container is STOPPED (docker compose stop in /opt/docker/dotmd).
  3. index.db is at the path given as argument.

Run standalone (outside container):
    python -m dotmd.ingestion.migration_v15 /var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db

FTS5 note: chunk_id is UNINDEXED in chunks_fts_* tables, so plain UPDATE is safe
without DELETE+INSERT. The migration uses plain UPDATE throughout.

The script is safe to resume: a migration_v15_state table tracks which strategies
have completed. Rerunning skips already-completed strategies.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

# Table name for per-strategy migration progress tracking.
# DDL: CREATE TABLE IF NOT EXISTS migration_v15_state (strategy TEXT PRIMARY KEY, ...)
_STATE_TABLE = "migration_v15_state"


def needs_migration_v15(index_db_path: Path) -> bool:
    """True if any chunks table still has old 128-char blake2b chunk_ids.

    blake2b hexdigest = 128 chars (512-bit output).
    blake3 hexdigest  =  64 chars (256-bit output).

    Checks ALL discovered chunks tables (not just one sample) to correctly
    handle partially migrated databases.
    """
    conn = sqlite3.connect(str(index_db_path))
    try:
        table_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name LIKE 'chunks_%' AND name NOT LIKE 'chunks_fts_%'"
        ).fetchall()
        if not table_rows:
            return False
        for (table_name,) in table_rows:
            sample = conn.execute(
                f"SELECT chunk_id FROM {table_name} LIMIT 1"
            ).fetchone()
            if sample and len(sample[0]) == 128:
                return True
        return False
    finally:
        conn.close()


def _verify_v15(conn: sqlite3.Connection, strategies: list[str]) -> None:
    """Expanded verification: orphans, uniqueness, row parity, no remaining 128-char IDs."""
    errors = 0

    for strategy in strategies:
        chunks_table = f"chunks_{strategy}"
        fts_table = f"chunks_fts_{strategy}"

        # 1. Orphan check: every chunk_id in chunks_* must appear in each vec_meta_*
        meta_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"vec_meta_{strategy}_%",),
            ).fetchall()
        ]
        for meta_table in meta_tables:
            orphans = conn.execute(
                f"SELECT COUNT(*) FROM {chunks_table} c "
                f"LEFT JOIN {meta_table} vm ON c.chunk_id = vm.chunk_id "
                f"WHERE vm.chunk_id IS NULL"
            ).fetchone()[0]
            if orphans > 0:
                logger.error("ORPHAN: %d chunk_ids in %s not in %s", orphans, chunks_table, meta_table)
                errors += 1
            else:
                logger.info("ORPHAN OK: %s <-> %s", chunks_table, meta_table)

        # 2. Uniqueness: COUNT(*) == COUNT(DISTINCT chunk_id) in chunks_*
        total, unique = conn.execute(
            f"SELECT COUNT(*), COUNT(DISTINCT chunk_id) FROM {chunks_table}"
        ).fetchone()
        if total != unique:
            logger.error(
                "DUPLICATE IDs: %s has %d rows but only %d distinct chunk_ids",
                chunks_table, total, unique,
            )
            errors += 1
        else:
            logger.info("UNIQUENESS OK: %s -- %d rows, %d distinct", chunks_table, total, unique)

        # 3. Row-count parity: chunks_* and chunks_fts_* must have same count
        fts_count = conn.execute(f"SELECT COUNT(*) FROM {fts_table}").fetchone()[0]
        if total != fts_count:
            logger.error(
                "FTS PARITY: %s has %d rows, %s has %d rows",
                chunks_table, total, fts_table, fts_count,
            )
            errors += 1
        else:
            logger.info("FTS PARITY OK: %s <-> %s (%d rows)", chunks_table, fts_table, total)

        # 4. No remaining 128-char IDs (old blake2b format)
        old_count = conn.execute(
            f"SELECT COUNT(*) FROM {chunks_table} WHERE length(chunk_id) = 128"
        ).fetchone()[0]
        if old_count > 0:
            logger.error("OLD IDs REMAIN: %d 128-char chunk_ids still in %s", old_count, chunks_table)
            errors += 1
        else:
            logger.info("ID FORMAT OK: no 128-char IDs in %s", chunks_table)

    if errors:
        raise RuntimeError(
            f"Migration verification failed: {errors} check(s) failed. See log above."
        )
    logger.info("All verification checks passed.")


def run_migration_v15(index_db_path: Path) -> None:
    """Migrate all chunk_ids in index.db from 128-char blake2b to 64-char blake3.

    Safe to resume: migration_v15_state table tracks per-strategy completion.
    Rerunning skips already-completed strategies.

    Raises RuntimeError if collision detection fails or verification fails.
    """
    # Step 0 — Check if fully migrated
    if not needs_migration_v15(index_db_path):
        logger.info("Already fully migrated or no chunks found -- skipping")
        return

    # Step 1 — Backup (refuse to overwrite existing backup)
    bak = Path(str(index_db_path) + ".bak")
    if bak.exists():
        logger.warning(
            "Backup %s already exists -- will not overwrite. "
            "Remove it manually to create a fresh backup.", bak
        )
    else:
        shutil.copy2(index_db_path, bak)
        logger.info("Backup created: %s", bak)

    # Step 2 — Open connection with WAL mode and blake3 UDF
    conn = sqlite3.connect(str(index_db_path))
    conn.execute("PRAGMA journal_mode=WAL")

    import blake3 as _blake3

    def _blake3_hex(payload: str) -> str:
        return _blake3.blake3(payload.encode()).hexdigest()

    conn.create_function("blake3_hex", 1, _blake3_hex)

    # Step 3 — Create state marker table
    conn.execute(
        f"CREATE TABLE IF NOT EXISTS {_STATE_TABLE} ("
        "strategy TEXT PRIMARY KEY, "
        "status TEXT NOT NULL, "
        "completed_at TEXT"
        ")"
    )
    conn.commit()

    # Step 4 — Discover strategies (ALL chunks_ tables, excluding FTS5)
    strategy_rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name LIKE 'chunks_%' AND name NOT LIKE 'chunks_fts_%'"
    ).fetchall()
    strategies = [r[0].removeprefix("chunks_") for r in strategy_rows]
    logger.info("Strategies found: %s", strategies)

    # Step 5 — Migrate each strategy
    for strategy in strategies:
        # Check state marker — skip if already complete
        state_row = conn.execute(
            f"SELECT status FROM {_STATE_TABLE} WHERE strategy = ?", (strategy,)
        ).fetchone()
        if state_row and state_row[0] == "complete":
            logger.info("Strategy %s already migrated -- skipping", strategy)
            continue

        chunks_table = f"chunks_{strategy}"
        fts_table = f"chunks_fts_{strategy}"
        fp_table = f"chunk_fingerprints_{strategy}"

        # Check fingerprints table exists
        fp_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (fp_table,)
        ).fetchone()
        if not fp_exists:
            logger.warning(
                "No fingerprints table %s -- skipping strategy %s", fp_table, strategy
            )
            continue

        # Build old->new id_map via JOIN with fingerprints
        rows = conn.execute(
            f"SELECT c.chunk_id, fp.checksum, c.chunk_index "
            f"FROM {chunks_table} c "
            f"JOIN {fp_table} fp ON fp.file_path = c.file_path"
        ).fetchall()

        id_map: dict[str, str] = {}
        for old_id, checksum, chunk_index in rows:
            new_id = _blake3_hex(f"{checksum}:{chunk_index}:{strategy}")
            id_map[old_id] = new_id

        logger.info("Strategy %s: %d chunk_ids to migrate", strategy, len(id_map))

        if not id_map:
            logger.info("Strategy %s: no rows -- marking complete", strategy)
            with conn:
                conn.execute(
                    f"INSERT OR REPLACE INTO {_STATE_TABLE} VALUES (?, 'complete', datetime('now'))",
                    (strategy,),
                )
            continue

        # === COLLISION CHECK (before any mutation) ===
        # Two distinct (checksum, chunk_index, strategy) inputs could produce the same
        # blake3 output only if duplicate files (identical body) exist in the knowledgebase.
        new_ids = list(id_map.values())
        if len(new_ids) != len(set(new_ids)):
            duplicates = [nid for nid in new_ids if new_ids.count(nid) > 1]
            raise RuntimeError(
                f"Strategy {strategy}: collision detected -- {len(new_ids)} old IDs map to "
                f"{len(set(new_ids))} distinct new IDs. Duplicate files? "
                f"Colliding new IDs (first 3): {list(set(duplicates))[:3]}"
            )
        logger.info(
            "Strategy %s: collision check passed (%d unique new IDs)", strategy, len(set(new_ids))
        )

        # Mark collision_checked in state
        with conn:
            conn.execute(
                f"INSERT OR REPLACE INTO {_STATE_TABLE} VALUES (?, 'collision_checked', NULL)",
                (strategy,),
            )

        # Discover all vec_meta tables for this strategy
        meta_tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
                (f"vec_meta_{strategy}_%",),
            ).fetchall()
        ]

        # Apply all UPDATEs in a single transaction per strategy.
        # FTS5 note: chunk_id is UNINDEXED in chunks_fts_* -- plain UPDATE is safe.
        with conn:
            for old_id, new_id in id_map.items():
                conn.execute(
                    f"UPDATE {chunks_table} SET chunk_id=? WHERE chunk_id=?",
                    (new_id, old_id),
                )
                conn.execute(
                    f"UPDATE {fts_table} SET chunk_id=? WHERE chunk_id=?",
                    (new_id, old_id),
                )
                for meta_table in meta_tables:
                    conn.execute(
                        f"UPDATE {meta_table} SET chunk_id=? WHERE chunk_id=?",
                        (new_id, old_id),
                    )
            # Mark complete atomically with the data updates
            conn.execute(
                f"INSERT OR REPLACE INTO {_STATE_TABLE} VALUES (?, 'complete', datetime('now'))",
                (strategy,),
            )
        logger.info("Strategy %s: migration committed", strategy)

    # Step 6 — Verify all strategies
    _verify_v15(conn, strategies)
    conn.close()

    print("""
Migration complete. Next steps:
  1. Rebuild Docker image (blake3 is a new compiled dep -- restart alone is NOT enough):
       cd /opt/docker/dotmd && docker compose build

  2. Start container:
       docker compose up -d

  3. Verify extraction_cache is warm (should_invalidate must return False on new instance):
       docker exec dotmd-api-1 python -c "
import os; os.environ.setdefault('DOTMD_EMBEDDING_URL', 'http://embeddings:8088')
from dotmd.core.config import Settings
from dotmd.storage.cache import ExtractionCache
import sqlite3
s = Settings()
conn = sqlite3.connect(str(s.index_db_path))
ec = ExtractionCache(conn, s.ner_model_name, s.ner_entity_types or [], 0.5)
invalidate = ec.should_invalidate()
print(f'should_invalidate={invalidate} (must be False for GLiNER to be skipped)')
assert not invalidate, 'extraction_cache is NOT warm -- run a full index cycle first!'
print('extraction_cache is warm -- reindex_graph will skip GLiNER')
"

  4. Run reindex_graph() to update FalkorDB with new chunk_ids:
       docker exec dotmd-api-1 python -c "
from dotmd.core.config import Settings
from dotmd.ingestion.pipeline import IndexingPipeline
p = IndexingPipeline(Settings())
n = p.reindex_graph()
print(f'reindex_graph: {n} chunks processed')
"

  5. Confirm GLiNER did NOT load during reindex_graph():
       docker logs dotmd-api-1 2>&1 | grep -i 'Loading GLiNER'
       (Expected: no output -- GLiNER must not have been loaded)
""")


# ------------------------------------------------------------------
# Standalone entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    default_path = Path("/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db")
    db_path = Path(sys.argv[1]) if len(sys.argv) > 1 else default_path
    if not db_path.exists():
        print(f"ERROR: index.db not found at {db_path}", file=sys.stderr)
        sys.exit(1)
    run_migration_v15(db_path)
