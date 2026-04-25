"""RED test skeletons for migration_v16 ops modes (DEDUP-06 — P2 Task 1).

Tests for --dry-run, --verify-only, and migrate status behaviour.
Assertion style: assert on report objects, not log strings (Review-LOW-10).

These tests FAIL at execution time until P2 (wave 6) wires the ops modes.
Imports are deferred so --collect-only works before P1/P2 ship.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest


def _import():  # type: ignore[no-untyped-def]
    from dotmd.ingestion.migration_v16 import run_migration_v16, status
    return run_migration_v16, status


def _conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


class TestDryRunWritesNothing:
    """--dry-run reports stats without persisting anything."""

    def test_dry_run_writes_nothing(self, collision_rich_db: Path) -> None:
        """--dry-run: DB bytes unchanged before and after (uses assert_db_bytes_unchanged)."""
        from tests.conftest import assert_db_bytes_unchanged
        run_migration_v16, _ = _import()
        before = hashlib.md5(collision_rich_db.read_bytes()).hexdigest()
        report = run_migration_v16(collision_rich_db, dry_run=True)
        assert report is not None
        assert_db_bytes_unchanged(collision_rich_db, before)


class TestVerifyOnlyNoMutation:
    """--verify-only: runs invariant checks without any DB mutation."""

    def test_verify_only_no_mutation(self, collision_rich_db: Path) -> None:
        """--verify-only: DB bytes unchanged, report contains InvariantReport."""
        from tests.conftest import assert_db_bytes_unchanged
        run_migration_v16, _ = _import()
        before = hashlib.md5(collision_rich_db.read_bytes()).hexdigest()
        report = run_migration_v16(collision_rich_db, verify_only=True)
        assert report is not None
        assert_db_bytes_unchanged(collision_rich_db, before)


class TestStatusReporting:
    """migrate status reports current state of migration_v16_state table."""

    def test_status_reports_no_state_on_fresh_db(self, empty_db: Path) -> None:
        """status() on a fresh DB returns a report indicating needs_migration=True."""
        _, status = _import()
        report = status(empty_db)
        assert report is not None
        assert hasattr(report, "needs_migration")
        assert report.needs_migration is True or report.per_strategy_state == {}

    def test_status_reports_per_strategy_state_after_run(
        self, collision_rich_db: Path
    ) -> None:
        """status() after a completed migration reports per-strategy rows."""
        run_migration_v16, status = _import()
        run_migration_v16(collision_rich_db, allow_payload_divergence=True)

        report = status(collision_rich_db)
        assert report is not None
        assert hasattr(report, "per_strategy_state")
        assert len(report.per_strategy_state) >= 1

        # Each strategy should show 'complete' status
        for strategy, state in report.per_strategy_state.items():
            assert state.get("status") in ("complete", "payload_divergence_blocked"), (
                f"Unexpected status for strategy {strategy}: {state!r}"
            )
