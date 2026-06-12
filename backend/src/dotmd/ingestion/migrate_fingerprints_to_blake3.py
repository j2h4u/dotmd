"""Recompute chunk_fingerprints.* and embed_fingerprints.* checksums as BLAKE3.

Replaces the previous BLAKE2b checksums in place. The migration reads every
file tracked by any fingerprint row, computes the BLAKE3 equivalent using the
SAME input payload as the live code, and UPDATEs the checksum column.

Why: unify all content hashing under BLAKE3 so the codebase stops carrying
multiple hash algorithms. See ROADMAP.md Phase 999.4 context and the
2026-04-24 discussion in session notes.

Note (Phase 999.12): embed_tracker has been replaced by meta_tracker in the
production pipeline. This migration script handles historical embed_fingerprints.*
tables only. New deployments use meta_fingerprints.* tables with meta_checksum.
The internal ``_compute_embed_checksum_blake3`` function is retained for migration
of existing embed_fingerprints rows and must NOT be removed.

CRITICAL ordering constraint:
    This script MUST run BEFORE the code in ``reader.py`` switches
    ``chunk_checksum`` / ``embed_checksum`` to BLAKE3. If the code were
    switched first, FileTracker would compare BLAKE3(file) against the
    stored BLAKE2b and flag every file as modified -- triggering a full
    re-chunk/re-embed cycle (hours of GLiNER).

Safe to resume: every UPDATE is idempotent; re-running recomputes identical
values for already-migrated rows.

Run standalone on a stopped container's volume:

    python -m dotmd.ingestion.migrate_fingerprints_to_blake3 /path/to/index.db [--apply]
"""

from __future__ import annotations

import argparse
import logging
import re
import sqlite3
import sys
from pathlib import Path

import blake3 as _blake3
import yaml

logger = logging.getLogger(__name__)

_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n(.*)", re.DOTALL)


def _parse_frontmatter(content: str) -> tuple[dict, str]:
    """Mirror reader.parse_frontmatter without importing it (self-contained)."""
    match = _FRONTMATTER_RE.match(content)
    if not match:
        return {}, content
    try:
        fm = yaml.safe_load(match.group(1)) or {}
    except yaml.YAMLError:
        return {}, content
    return fm if isinstance(fm, dict) else {}, match.group(2)


def _compute_chunk_checksum_blake3(path: Path) -> str:
    """BLAKE3 equivalent of reader.chunk_checksum: blake3(kind + "\\n" + body)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _parse_frontmatter(content)
    # "document" matches DocKind.DOCUMENT default -- keep semantics identical.
    kind = frontmatter.get("kind", "document")
    payload = f"{kind}\n{body}"
    return _blake3.blake3(payload.encode()).hexdigest()


def _compute_embed_checksum_blake3(path: Path) -> str:
    """BLAKE3 equivalent of reader.embed_checksum: blake3(kind + title + tags + body)."""
    content = path.read_text(encoding="utf-8", errors="replace")
    frontmatter, body = _parse_frontmatter(content)
    kind = frontmatter.get("kind", "document")
    title = str(frontmatter.get("title", ""))
    tags = frontmatter.get("tags", [])
    tags_str = ",".join(sorted(str(t) for t in tags)) if tags else ""
    payload = f"{kind}\n{title}\n{tags_str}\n{body}"
    return _blake3.blake3(payload.encode()).hexdigest()


def _migrate_table(
    conn: sqlite3.Connection,
    table: str,
    is_embed: bool,
    apply: bool,
) -> tuple[int, int, list[str]]:
    """Returns (updated, missing, errors).

    missing = rows whose file_path no longer exists on disk (orphan fingerprints)
    errors  = human-readable strings listing read/parse failures
    """
    compute = _compute_embed_checksum_blake3 if is_embed else _compute_chunk_checksum_blake3

    rows = conn.execute(f"SELECT file_path, checksum FROM {table}").fetchall()

    updated = 0
    missing: list[str] = []
    errors: list[str] = []

    updates: list[tuple[str, str]] = []
    for file_path, old_checksum in rows:
        path = Path(file_path)
        if not path.exists():
            missing.append(file_path)
            continue
        try:
            new_checksum = compute(path)
        except Exception as exc:
            errors.append(f"{file_path}: {type(exc).__name__}: {exc}")
            continue
        if new_checksum != old_checksum:
            updates.append((new_checksum, file_path))
            updated += 1

    if apply and updates:
        conn.executemany(
            f"UPDATE {table} SET checksum = ? WHERE file_path = ?",
            updates,
        )
    if apply and missing:
        ph = ",".join("?" * len(missing))
        conn.execute(
            f"DELETE FROM {table} WHERE file_path IN ({ph})",
            missing,
        )

    return updated, len(missing), errors


def run_migration(index_db_path: Path, apply: bool) -> int:
    if not index_db_path.exists():
        print(f"ERROR: {index_db_path} not found", file=sys.stderr)
        return 2

    conn = sqlite3.connect(str(index_db_path))
    try:
        fp_tables = [
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' "
                "AND (name LIKE 'chunk_fingerprints_%' OR name LIKE 'embed_fingerprints_%')"
            ).fetchall()
        ]
        if not fp_tables:
            print("No fingerprint tables found -- nothing to migrate.")
            return 0

        print()
        print("=" * 70)
        print("BLAKE2b -> BLAKE3 FINGERPRINT MIGRATION")
        print("=" * 70)
        print(f"{'Table':<60} {'updated':>8} {'missing':>8} {'errors':>8}")
        print("-" * 90)

        total_updated = 0
        total_missing = 0
        all_errors: list[str] = []

        conn.execute("BEGIN")
        try:
            for t in fp_tables:
                is_embed = t.startswith("embed_fingerprints_")
                updated, missing, errors = _migrate_table(conn, t, is_embed, apply)
                total_updated += updated
                total_missing += missing
                all_errors.extend(errors)
                print(f"{t:<60} {updated:>8} {missing:>8} {len(errors):>8}")

            if all_errors:
                print()
                print(f"ERRORS ({len(all_errors)}):")
                for e in all_errors[:20]:
                    print(f"  {e}")
                if len(all_errors) > 20:
                    print(f"  ... and {len(all_errors) - 20} more")
                print()
                print("Aborting -- no changes written. Fix errors and re-run.")
                conn.execute("ROLLBACK")
                return 3

            if apply:
                conn.execute("COMMIT")
                print()
                print(f"APPLIED: {total_updated} rows updated, {total_missing} orphan rows deleted")
            else:
                conn.execute("ROLLBACK")
                print()
                print(
                    f"DRY-RUN: would update {total_updated} rows, "
                    f"delete {total_missing} orphan rows"
                )
                print("Re-run with --apply to execute.")
        except Exception:
            conn.execute("ROLLBACK")
            raise
        return 0
    finally:
        conn.close()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("index_db_path", type=Path)
    parser.add_argument(
        "--apply", action="store_true", help="Apply migration (default: dry-run only)"
    )
    args = parser.parse_args()
    return run_migration(args.index_db_path, args.apply)


if __name__ == "__main__":
    sys.exit(main())
