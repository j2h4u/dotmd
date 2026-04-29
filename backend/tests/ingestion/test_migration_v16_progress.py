"""RED test skeletons for migration_v16 progress reporting (DEDUP-06 — P2 Task 1).

Asserts on ProgressReport objects returned by run_migration_v16, NOT on
caplog.text substring matches (Review-LOW-10 non-brittle assertions).

These tests FAIL at execution time until P2 (wave 6) adds the progress reporter.
Imports are deferred so --collect-only works before P1/P2 ship.
"""

from __future__ import annotations

from pathlib import Path


def _import():  # type: ignore[no-untyped-def]
    from dotmd.ingestion.migration_v16 import run_migration_v16
    return run_migration_v16


class TestProgressLineEmission:
    """Progress reporter emits rows_per_sec and ETA."""

    def test_progress_line_emits_rows_per_sec_and_eta(
        self, collision_rich_db: Path
    ) -> None:
        """MigrationReport carries rows_per_sec > 0 for each completed strategy."""
        run_migration_v16 = _import()
        report = run_migration_v16(collision_rich_db)
        # Report must expose per-strategy progress fields
        assert hasattr(report, "per_strategy_progress"), (
            "MigrationReport missing per_strategy_progress field"
        )
        for strategy, prog in report.per_strategy_progress.items():
            assert prog.get("rows_per_sec", 0) >= 0, (
                f"rows_per_sec missing or negative for strategy {strategy}"
            )
            # ETA may be 0 for small fixtures but field must be present
            assert "eta_seconds" in prog or "rows_done" in prog, (
                f"Progress dict for {strategy} missing expected fields: {prog!r}"
            )


class TestDryRunPrefix:
    """Dry-run mode marks report fields with mode='dry-run'."""

    def test_dry_run_prefix_present(self, collision_rich_db: Path) -> None:
        """Report from --dry-run has mode='dry-run' field."""
        run_migration_v16 = _import()
        report = run_migration_v16(collision_rich_db, dry_run=True)
        assert hasattr(report, "mode"), "MigrationReport missing mode field"
        assert report.mode == "dry-run", (
            f"Expected mode='dry-run', got {report.mode!r}"
        )


class TestVerifyOnlyPrefix:
    """Verify-only mode marks report fields with mode='verify-only'."""

    def test_verify_only_prefix_present(self, collision_rich_db: Path) -> None:
        """Report from --verify-only has mode='verify-only' field."""
        run_migration_v16 = _import()
        report = run_migration_v16(collision_rich_db, verify_only=True)
        assert hasattr(report, "mode"), "MigrationReport missing mode field"
        assert report.mode == "verify-only", (
            f"Expected mode='verify-only', got {report.mode!r}"
        )
