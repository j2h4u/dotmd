"""RED test skeletons for migration_v16 invariant battery (DEDUP-10).

Each test calls migration_v16.run_invariants(conn) and asserts on the returned
InvariantReport.checks[*].passed — never on log-text strings (Review-LOW-10).

run_invariants is the single source of truth for invariant logic; both
--verify-only CLI mode and these tests import the same helper.

These tests FAIL at execution time (not collection time) until P1 (wave 2)
implements migration_v16.py.  Imports are deferred so --collect-only works.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

STRATEGIES = ["heading_512_50", "contextual_512_50"]
MODEL = "multilingual_e5_large"


def _import():  # type: ignore[no-untyped-def]
    """Deferred import — raises ImportError until P1 ships migration_v16."""
    from dotmd.ingestion.migration_v16 import run_invariants, run_migration_v16
    return run_invariants, run_migration_v16


def _conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


def _find_check(inv_report, name: str):  # type: ignore[no-untyped-def]
    """Return the check dict with the given name from InvariantReport.checks."""
    for check in inv_report.checks:
        if check["name"] == name:
            return check
    return None


class TestAllChunkIdsAre64HexBlake3:
    """Invariant: every chunk_id in chunks_* is 64-char hex after migration."""

    def test_all_chunk_ids_are_64_hex_blake3(self, collision_rich_db: Path) -> None:
        run_invariants, run_migration_v16 = _import()
        run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        inv = run_invariants(conn)
        conn.close()

        check = _find_check(inv, "64char_blake3")
        assert check is not None, "InvariantReport missing '64char_blake3' check"
        assert check["passed"] is True, f"64char_blake3 check failed: {check.get('detail')}"


class TestNoOrphanVecMetaRows:
    """Invariant: no orphan rows in vec_meta_* after migration."""

    def test_no_orphan_vec_meta_rows(self, collision_rich_db: Path) -> None:
        run_invariants, run_migration_v16 = _import()
        run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        inv = run_invariants(conn)
        conn.close()

        check = _find_check(inv, "no_orphan_vec_meta")
        assert check is not None, "InvariantReport missing 'no_orphan_vec_meta' check"
        assert check["passed"] is True, f"no_orphan_vec_meta failed: {check.get('detail')}"


class TestNoOrphanFtsRows:
    """Invariant: no orphan rows in chunks_fts_* after migration."""

    def test_no_orphan_fts_rows(self, collision_rich_db: Path) -> None:
        run_invariants, run_migration_v16 = _import()
        run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        inv = run_invariants(conn)
        conn.close()

        check = _find_check(inv, "no_orphan_fts")
        assert check is not None, "InvariantReport missing 'no_orphan_fts' check"
        assert check["passed"] is True, f"no_orphan_fts failed: {check.get('detail')}"


class TestUniqueFilePathChunkIndexPerStrategy:
    """Invariant: UNIQUE(file_path, chunk_index) holds in chunk_file_paths_* per strategy."""

    def test_unique_file_path_chunk_index_per_strategy(
        self, collision_rich_db: Path
    ) -> None:
        run_invariants, run_migration_v16 = _import()
        run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        inv = run_invariants(conn)
        conn.close()

        check = _find_check(inv, "unique_file_path_chunk_index")
        assert check is not None, "InvariantReport missing 'unique_file_path_chunk_index' check"
        assert check["passed"] is True, (
            f"unique_file_path_chunk_index failed: {check.get('detail')}"
        )


class TestRowCountDeltaMatchesExpectedCollapse:
    """Invariant: row count delta matches expected collision collapse count."""

    def test_row_count_delta_matches_expected_collapse(
        self, collision_rich_db: Path
    ) -> None:
        """After migrating collision_rich_db, chunks_* shrinks by 2 per strategy (2 groups × 2)."""
        run_invariants, run_migration_v16 = _import()

        conn_pre = _conn(collision_rich_db)
        pre_counts = {}
        for s in STRATEGIES:
            pre_counts[s] = conn_pre.execute(
                f"SELECT COUNT(*) FROM chunks_{s}"
            ).fetchone()[0]
        conn_pre.close()

        report = run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        inv = run_invariants(conn)
        conn.close()

        assert report.collisions_collapsed >= len(STRATEGIES) * 2

        check = _find_check(inv, "row_count_delta")
        assert check is not None, "InvariantReport missing 'row_count_delta' check"
        assert check["passed"] is True, f"row_count_delta failed: {check.get('detail')}"


class TestBackupFileExists:
    """Post-flight: backup file created for real runs."""

    def test_backup_file_exists(self, collision_rich_db: Path) -> None:
        """After run_migration_v16, a backup file exists at index.db.v16-backup."""
        _, run_migration_v16 = _import()
        run_migration_v16(collision_rich_db)
        backup_path = collision_rich_db.with_suffix(".db.v16-backup")
        alt_backup = Path(str(collision_rich_db) + ".v16-backup")
        assert backup_path.exists() or alt_backup.exists(), (
            f"Backup file not created: checked {backup_path} and {alt_backup}"
        )
