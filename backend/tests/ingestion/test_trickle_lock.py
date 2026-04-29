"""RED test skeletons for TrickleIndexer advisory lock check (P3 — Task 2).

Trickle must refuse to start while migration_v16_lock is held (any mode).
The lock-table name is imported from storage.lock_constants, NOT from
migration_v16 (no runtime dependency on migration module — Review-LOW).

These tests will FAIL until P3 (wave 3) implements the startup lock check.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

# Lock table constant — deferred so collection works before P3 ships.
# If lock_constants does not exist, the tests themselves will fail with ImportError.
LOCK_TABLE = "migration_v16_lock"  # module-level default; overridden by the helper below


def _get_lock_table() -> str:
    """Import LOCK_TABLE from lock_constants (raises ImportError until P3 ships)."""
    from dotmd.storage.lock_constants import LOCK_TABLE as _LT
    return _LT


def _insert_lock_row(db_path: Path, mode: str = "run") -> None:
    """Insert a migration_v16_lock sentinel row into the DB."""
    lt = _get_lock_table()  # Raises ImportError until P3 ships lock_constants.py
    conn = sqlite3.connect(str(db_path))
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {lt} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            locked_at TEXT NOT NULL,
            pid INTEGER NOT NULL,
            host TEXT NOT NULL,
            mode TEXT NOT NULL
        )
    """)
    conn.execute(
        f"INSERT OR REPLACE INTO {lt} (id, locked_at, pid, host, mode) "
        "VALUES (1, datetime('now'), ?, 'testhost', ?)",
        (12345, mode),
    )
    conn.commit()
    conn.close()


def _start_trickle(db_path: Path):  # type: ignore[no-untyped-def]
    """Attempt to start TrickleIndexer against db_path.

    Returns the TrickleIndexer instance on success, or raises SystemExit / an
    exception on refused startup.
    """
    from dotmd.core.config import Settings
    from dotmd.ingestion.trickle import TrickleIndexer

    # Build a minimal settings pointing at tmp DB
    settings = Settings(index_dir=db_path.parent)
    return TrickleIndexer(settings)


class TestTrickleLockRefusal:
    """TrickleIndexer refuses to start while migration_v16_lock is held."""

    def test_refuses_while_locked(self, tmp_index_db: Path) -> None:
        """TrickleIndexer raises or exits non-zero when lock row with mode='run' exists."""
        _insert_lock_row(tmp_index_db, mode="run")
        with pytest.raises((SystemExit, RuntimeError, OSError)):
            _start_trickle(tmp_index_db)

    def test_starts_when_lock_cleared(self, tmp_index_db: Path) -> None:
        """TrickleIndexer starts normally when no lock row is present."""
        # No lock inserted — should not raise
        # We only test the startup check, not the full indexer lifecycle;
        # patch the actual indexing so the test exits quickly.
        with patch(
            "dotmd.ingestion.trickle.TrickleIndexer._run_index_loop",
            side_effect=StopIteration("test stop"),
        ):
            try:
                _start_trickle(tmp_index_db)
            except StopIteration:
                pass  # Expected — means startup check passed and indexer tried to run
            except (SystemExit, RuntimeError) as exc:
                pytest.fail(f"Trickle should not refuse when lock is clear: {exc!r}")

    def test_starts_when_lock_table_absent(self, empty_db: Path) -> None:
        """TrickleIndexer starts when the migration_v16_lock table doesn't exist yet (fresh DB)."""
        # empty_db has pre-v16 schema without migration_v16_lock table
        with patch(
            "dotmd.ingestion.trickle.TrickleIndexer._run_index_loop",
            side_effect=StopIteration("test stop"),
        ):
            try:
                _start_trickle(empty_db)
            except StopIteration:
                pass  # Expected
            except (SystemExit, RuntimeError) as exc:
                pytest.fail(
                    f"Trickle should not refuse when lock table is absent: {exc!r}"
                )

    def test_refuses_on_dry_run_lock(self, tmp_index_db: Path) -> None:
        """TrickleIndexer refuses when lock mode='dry-run' (Review-MED-6: dry-run also holds lock)."""
        _insert_lock_row(tmp_index_db, mode="dry-run")
        with pytest.raises((SystemExit, RuntimeError, OSError)):
            _start_trickle(tmp_index_db)
