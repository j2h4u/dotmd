"""RED test skeletons for migration_v15 stub (Decision #9 — P1 Task 3).

After Phase 16 P1 ships, migration_v15.py becomes a no-op stub with a
deprecation banner. These tests verify the stub contract without touching
the filesystem.

Assertion style: assert on module.__doc__ and function return values,
not on log-string substrings (Review-LOW-10).

These tests will FAIL once P1 ships the stub because the current
migration_v15 is a full implementation (not a stub), so:
  - needs_migration_v15 still returns True on old data
  - run_migration_v15 still tries to mutate the DB
  - the module docstring does not say "Superseded"
"""

from __future__ import annotations

from pathlib import Path

import pytest

import dotmd.ingestion.migration_v15 as _v15


class TestV15IsNoOp:
    """After P1 stubs migration_v15, both entry points must be safe no-ops."""

    def test_needs_migration_v15_returns_false(self, tmp_index_db: Path) -> None:
        """needs_migration_v15 always returns False (stub superseded by migration_v16)."""
        result = _v15.needs_migration_v15(tmp_index_db)
        assert result is False, (
            f"needs_migration_v15 should return False (stub), got {result!r}"
        )

    def test_run_migration_v15_is_noop(self, tmp_index_db: Path) -> None:
        """run_migration_v15 returns None without touching the filesystem."""
        import hashlib
        before = hashlib.md5(tmp_index_db.read_bytes()).hexdigest()
        result = _v15.run_migration_v15(tmp_index_db)
        after = hashlib.md5(tmp_index_db.read_bytes()).hexdigest()
        assert result is None, f"run_migration_v15 should return None (stub), got {result!r}"
        assert before == after, "run_migration_v15 (stub) modified the database"


class TestV15DeprecationBanner:
    """The module docstring must contain the word 'Superseded' (Decision #9)."""

    def test_v15_module_has_deprecation_banner(self) -> None:
        """migration_v15 module docstring contains 'Superseded' (Review-LOW-10: assert on __doc__)."""
        doc = _v15.__doc__
        assert doc is not None, "migration_v15 module has no docstring"
        assert "Superseded" in doc, (
            "migration_v15.__doc__ does not contain 'Superseded'.\n"
            f"Current docstring:\n{doc!r}"
        )
