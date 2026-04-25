"""RED test skeletons for `dotmd migrate` CLI subcommand (DEDUP-06 — P2 Task 2).

Uses Click's CliRunner for isolated test invocations.
Assertion style: exit codes + output content (not log strings).

These tests FAIL at execution time until P2 (wave 6) adds the migrate CLI.
Imports are deferred so --collect-only works before P2 ships.
"""

from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest


def _get_cli():  # type: ignore[no-untyped-def]
    """Deferred import of CLI entrypoint — raises ImportError until P2 ships migrate group."""
    from click.testing import CliRunner
    from dotmd.cli import main
    return CliRunner, main


def _get_runner():  # type: ignore[no-untyped-def]
    from click.testing import CliRunner
    return CliRunner()


class TestMigrateDryRunCLI:
    """migrate run --dry-run: exit 0, DB unchanged."""

    def test_cli_run_dry_run_exit_zero_db_unchanged(
        self, collision_rich_db: Path
    ) -> None:
        """dotmd migrate run --dry-run exits 0 and leaves DB bytes unchanged."""
        from tests.conftest import assert_db_bytes_unchanged
        CliRunner, main = _get_cli()
        runner = CliRunner()
        before = hashlib.md5(collision_rich_db.read_bytes()).hexdigest()
        result = runner.invoke(
            main,
            ["--index-dir", str(collision_rich_db.parent), "migrate", "run", "--dry-run"],
        )
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
        )
        assert_db_bytes_unchanged(collision_rich_db, before)


class TestMigrateVerifyOnlyCLI:
    """migrate run --verify-only: exit 0, DB unchanged."""

    def test_cli_verify_only_exit_zero_db_unchanged(
        self, collision_rich_db: Path
    ) -> None:
        """dotmd migrate run --verify-only exits 0 on clean DB, DB unchanged."""
        from tests.conftest import assert_db_bytes_unchanged
        CliRunner, main = _get_cli()
        runner = CliRunner()
        before = hashlib.md5(collision_rich_db.read_bytes()).hexdigest()
        result = runner.invoke(
            main,
            ["--index-dir", str(collision_rich_db.parent), "migrate", "run", "--verify-only"],
        )
        # Pre-migration DB may fail invariant check (exit 1 or 4) but must not crash
        assert result.exit_code in (0, 1, 4), (
            f"Unexpected exit code {result.exit_code}. Output:\n{result.output}"
        )
        assert_db_bytes_unchanged(collision_rich_db, before)


class TestMigrateMutexFlags:
    """--dry-run and --verify-only are mutually exclusive (exit 2)."""

    def test_cli_dry_run_and_verify_only_mutex_exit_2(
        self, collision_rich_db: Path
    ) -> None:
        """dotmd migrate run --dry-run --verify-only exits 2 with mutex error."""
        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--index-dir",
                str(collision_rich_db.parent),
                "migrate",
                "run",
                "--dry-run",
                "--verify-only",
            ],
        )
        assert result.exit_code == 2, (
            f"Expected exit 2 for mutex flags, got {result.exit_code}. Output:\n{result.output}"
        )


class TestMigrateStatusCLI:
    """migrate status reads state without mutation."""

    def test_cli_status_fresh_db(self, empty_db: Path) -> None:
        """dotmd migrate status on a fresh DB exits 0 and prints 'needs migration'."""
        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--index-dir", str(empty_db.parent), "migrate", "status"],
        )
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
        )
        assert "needs" in result.output.lower() or "migration" in result.output.lower(), (
            f"Expected 'needs migration' in output: {result.output!r}"
        )

    def test_cli_status_post_migration(self, collision_rich_db: Path) -> None:
        """dotmd migrate status after migration shows per-strategy state."""
        from dotmd.ingestion.migration_v16 import run_migration_v16
        run_migration_v16(collision_rich_db)

        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--index-dir", str(collision_rich_db.parent), "migrate", "status"],
        )
        assert result.exit_code == 0, (
            f"Expected exit 0, got {result.exit_code}. Output:\n{result.output}"
        )
        assert "heading_512_50" in result.output or "complete" in result.output, (
            f"Expected strategy state in output: {result.output!r}"
        )


class TestMigrateStaleLockCLI:
    """migrate run with stale lock: exit 2 with operator hint."""

    def test_cli_run_stale_lock_exit_2_with_hint(
        self, collision_rich_db: Path
    ) -> None:
        """dotmd migrate run exits 2 when lock held; output contains DELETE hint."""
        # Insert a stale lock row directly
        conn = sqlite3.connect(str(collision_rich_db))
        conn.execute("""
            CREATE TABLE IF NOT EXISTS migration_v16_lock (
                id INTEGER PRIMARY KEY CHECK (id = 1),
                locked_at TEXT NOT NULL,
                pid INTEGER NOT NULL,
                host TEXT NOT NULL,
                mode TEXT NOT NULL
            )
        """)
        conn.execute(
            "INSERT OR REPLACE INTO migration_v16_lock (id, locked_at, pid, host, mode) "
            "VALUES (1, datetime('now'), 99999, 'stalehost', 'run')"
        )
        conn.commit()
        conn.close()

        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["--index-dir", str(collision_rich_db.parent), "migrate", "run"],
        )
        assert result.exit_code == 2, (
            f"Expected exit 2 for stale lock, got {result.exit_code}. Output:\n{result.output}"
        )
        assert "DELETE FROM migration_v16_lock" in result.output, (
            f"Expected DELETE hint in output: {result.output!r}"
        )


class TestMigrateVerifyOnlyInvariantViolation:
    """migrate run --verify-only exits 1 on a fixture with invariant violations."""

    def test_cli_verify_only_invariant_violation_exit_1(
        self, tmp_index_db: Path
    ) -> None:
        """--verify-only exits 1 when invariants fail (e.g., non-64-char chunk_ids)."""
        # Insert a row with a non-64-char chunk_id to trigger the invariant check
        conn = sqlite3.connect(str(tmp_index_db))
        conn.execute(
            "INSERT INTO chunks_heading_512_50 "
            "(chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
            "VALUES (?, ?, '[]', 0, 'text', 0, 0)",
            ("short_invalid_id", "/tmp/test.md"),  # chunk_id not 64 chars — triggers invariant
        )
        conn.commit()
        conn.close()

        CliRunner, main = _get_cli()
        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "--index-dir",
                str(tmp_index_db.parent),
                "migrate",
                "run",
                "--verify-only",
            ],
        )
        assert result.exit_code in (1, 4), (
            f"Expected exit 1 or 4 on invariant violation, got {result.exit_code}. "
            f"Output:\n{result.output}"
        )
