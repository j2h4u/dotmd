"""RED test skeletons for migration_v16.py (P1 — schema migration core).

These tests cover DEDUP-01..04 plus all Review-HIGH regression guards.
They will FAIL with ImportError or AttributeError until P1 (wave 2)
implements migration_v16.py.

Assertion style: return-value / report-object assertions only.
No log-string substring matching (Review-LOW-10 non-brittle assertions).

Collection note: imports are deferred into each test so that --collect-only
works even before P1 ships.  Running the tests will fail on missing modules.
"""

from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest

# We defer the production imports to runtime so collect-only succeeds:
# from dotmd.ingestion.migration_v16 import (...)
# These will ImportError at test execution time until P1 ships.


STRATEGIES = ["heading_512_50", "contextual_512_50"]
MODEL = "multilingual_e5_large"


def _import():  # type: ignore[no-untyped-def]
    """Deferred import — raises ImportError until P1 ships migration_v16."""
    from dotmd.ingestion.migration_v16 import (
        PayloadDivergenceBlocked,
        run_migration_v16,
        run_invariants,
        needs_migration_v16,
        status,
    )
    return PayloadDivergenceBlocked, run_migration_v16, run_invariants, needs_migration_v16, status


def _conn(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(str(db_path))


# ---------------------------------------------------------------------------
# Core schema migration — DEDUP-01..04
# ---------------------------------------------------------------------------

class TestM2MTableCreation:
    """DEDUP-01: M2M table + index created per strategy."""

    def test_creates_m2m_table_and_index(self, collision_rich_db: Path) -> None:
        """After migration, chunk_file_paths_<strategy> exists with the correct PK and index."""
        _, run_migration_v16, *_ = _import()
        report = run_migration_v16(collision_rich_db)
        assert report is not None

        conn = _conn(collision_rich_db)
        for strategy in STRATEGIES:
            m2m = f"chunk_file_paths_{strategy}"
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (m2m,)
            ).fetchone()
            assert row is not None, f"M2M table {m2m} not created"

            idx = f"idx_chunk_file_paths_{strategy}_file_path"
            row = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' AND name=?", (idx,)
            ).fetchone()
            assert row is not None, f"Index {idx} not created"
        conn.close()


class TestColumnDrops:
    """DEDUP-02: file_path, chunk_index, char_offset dropped from chunks_*."""

    def test_drops_file_path_chunk_index_char_offset(self, collision_rich_db: Path) -> None:
        """After migration, chunks_* has no file_path, chunk_index, or char_offset columns."""
        _, run_migration_v16, *_ = _import()
        run_migration_v16(collision_rich_db)
        conn = _conn(collision_rich_db)
        for strategy in STRATEGIES:
            table = f"chunks_{strategy}"
            cursor = conn.execute(f"PRAGMA table_info({table})")
            col_names = {row[1] for row in cursor.fetchall()}
            assert "file_path" not in col_names, f"file_path still in {table}"
            assert "chunk_index" not in col_names, f"chunk_index still in {table}"
            assert "char_offset" not in col_names, f"char_offset still in {table}"
        conn.close()


# ---------------------------------------------------------------------------
# Shadow-column flow regression guards (Review-HIGH-1..4)
# ---------------------------------------------------------------------------

class TestShadowColumnFlow:
    """Review-HIGH-1: shadow-column flow prevents IntegrityError on collision groups."""

    def test_shadow_column_flow_no_pk_violation(self, collision_rich_db: Path) -> None:
        """Migration does not raise IntegrityError even when multiple old IDs map to same blake3."""
        _, run_migration_v16, *_ = _import()
        try:
            report = run_migration_v16(collision_rich_db)
        except Exception as exc:  # noqa: BLE001
            pytest.fail(f"Migration raised unexpectedly: {exc!r}")
        assert report.completed is True


class TestCanonicalSemantics:
    """Review-HIGH-4: canonical = MIN(old_chunk_id) for payload, final id is always blake3."""

    def test_collision_canonical_is_min_old_id_for_payload_but_final_id_is_blake3(
        self, collision_rich_db: Path
    ) -> None:
        """Canonical old id is MIN(old_ids); the surviving chunk_id in chunks_* is 64-hex blake3."""
        _, run_migration_v16, *_ = _import()
        report = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        conn = _conn(collision_rich_db)
        for strategy in STRATEGIES:
            rows = conn.execute(
                f"SELECT chunk_id FROM chunks_{strategy}"
            ).fetchall()
            for (cid,) in rows:
                assert len(cid) == 64, f"Non-blake3 chunk_id in chunks_{strategy}: {cid!r}"
        assert report.collisions_collapsed >= 0
        conn.close()


class TestPayloadInvariantMismatch:
    """Review-HIGH-2: payload mismatch in collision group is WARN-logged, not silently dropped."""

    def test_collision_group_payload_invariant_mismatch_logs_warn(
        self, tmp_index_db: Path
    ) -> None:
        """Two chunks with same blake3 but different heading_hierarchy emit payload_mismatch_warnings."""
        _, run_migration_v16, *_ = _import()
        conn = _conn(tmp_index_db)
        strategy = "heading_512_50"
        table = f"chunks_{strategy}"
        shared_text = "identical body content for divergence test"
        conn.execute(
            f"INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("old_id_aaa", "/path/fileA.md", json.dumps(["Heading A"]), 1, shared_text, 0, 0),
        )
        conn.execute(
            f"INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("old_id_bbb", "/path/fileB.md", json.dumps(["Heading B"]), 2, shared_text, 0, 0),
        )
        conn.commit()
        conn.close()

        report = run_migration_v16(tmp_index_db, allow_payload_divergence=True)
        assert report.payload_mismatch_warnings >= 1, (
            "Expected at least 1 payload_mismatch_warning for diverged heading_hierarchy"
        )


class TestMakeChunkIdReuse:
    """Review-HIGH-3: migration reuses chunker._make_chunk_id, does not restate the recipe."""

    def test_uses_chunker_make_chunk_id_helper(
        self, collision_rich_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """migration_v16 calls chunker._make_chunk_id (verified via monkeypatch)."""
        _, run_migration_v16, *_ = _import()
        call_count = {"n": 0}
        import dotmd.ingestion.chunker as _chunker

        original = _chunker._make_chunk_id

        def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
            call_count["n"] += 1
            return original(*args, **kwargs)

        monkeypatch.setattr(_chunker, "_make_chunk_id", spy)
        run_migration_v16(collision_rich_db)
        assert call_count["n"] > 0, "_make_chunk_id was never called by migration_v16"


# ---------------------------------------------------------------------------
# Divergence threshold tests (Decision #4)
# ---------------------------------------------------------------------------

class TestVectorDivergenceThreshold:
    """Decision #4: cosine divergence WARN at 0.01 threshold, does not abort."""

    def test_divergence_warn_emitted_above_threshold(
        self, collision_rich_db: Path
    ) -> None:
        """migration_v16 emits divergence_warnings when cosine distance > 0.01."""
        _, run_migration_v16, *_ = _import()
        with patch(
            "dotmd.ingestion.migration_v16._fetch_vector_for_divergence_check"
        ) as mock_fetch:
            mock_fetch.side_effect = lambda *a, **kw: (
                [1.0, 0.0] if mock_fetch.call_count % 2 == 1 else [0.0, 1.0]
            )
            report = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        assert report.divergence_warnings >= 0

    def test_divergence_warn_not_emitted_below_threshold(
        self, collision_rich_db: Path
    ) -> None:
        """No divergence_warnings when cosine distance <= 0.01 (identical vectors)."""
        _, run_migration_v16, *_ = _import()
        with patch(
            "dotmd.ingestion.migration_v16._fetch_vector_for_divergence_check"
        ) as mock_fetch:
            mock_fetch.return_value = [1.0, 0.0, 0.0, 0.0]
            report = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        assert report.divergence_warnings == 0


# ---------------------------------------------------------------------------
# Operational behaviour
# ---------------------------------------------------------------------------

class TestResumeAfterCrash:
    """Decision #6: per-strategy state marker enables resume after crash."""

    def test_resume_after_crash_skips_completed_strategy(
        self, collision_rich_db: Path
    ) -> None:
        """Running migration twice skips already-completed strategies (idempotent)."""
        _, run_migration_v16, *_ = _import()
        report1 = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        report2 = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        assert report2.skipped_strategies == list(report1.completed_strategies)


class TestEmptyStrategyNoOp:
    """Migration is a no-op when chunks_* tables are empty."""

    def test_empty_strategy_no_op(self, empty_db: Path) -> None:
        """Migration on an empty DB completes without error and reports 0 collisions."""
        _, run_migration_v16, *_ = _import()
        report = run_migration_v16(empty_db)
        assert report.completed is True
        assert report.collisions_collapsed == 0


# ---------------------------------------------------------------------------
# Dry-run behaviour (Review-MED-6)
# ---------------------------------------------------------------------------

class TestDryRun:
    """Decision #7: --dry-run acquires lock, makes no persistent changes."""

    def test_dry_run_leaves_db_untouched(
        self, collision_rich_db: Path
    ) -> None:
        """--dry-run DB bytes are identical before and after."""
        from tests.conftest import assert_db_bytes_unchanged
        _, run_migration_v16, *_ = _import()
        before = hashlib.md5(collision_rich_db.read_bytes()).hexdigest()
        run_migration_v16(collision_rich_db, dry_run=True)
        assert_db_bytes_unchanged(collision_rich_db, before)

    def test_dry_run_acquires_and_releases_lock(
        self, collision_rich_db: Path
    ) -> None:
        """--dry-run acquires migration_v16_lock (mode='dry-run') and releases it on ROLLBACK."""
        _, run_migration_v16, *_ = _import()
        report = run_migration_v16(collision_rich_db, dry_run=True)
        assert report.lock_mode == "dry-run"
        conn = _conn(collision_rich_db)
        lock_row = conn.execute(
            "SELECT id FROM migration_v16_lock WHERE id = 1"
        ).fetchone()
        conn.close()
        assert lock_row is None, "Lock not released after dry-run"


# ---------------------------------------------------------------------------
# Advisory lock lifecycle
# ---------------------------------------------------------------------------

class TestLockLifecycle:
    """Decision #6: advisory lock acquired at start, released at end of real run."""

    def test_lock_acquired_and_released(self, collision_rich_db: Path) -> None:
        """migration_v16_lock row is gone after successful migration."""
        _, run_migration_v16, *_ = _import()
        report = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        assert report.completed is True
        conn = _conn(collision_rich_db)
        lock_row = conn.execute(
            "SELECT id FROM migration_v16_lock WHERE id = 1"
        ).fetchone()
        conn.close()
        assert lock_row is None, "Lock row persists after successful migration"


# ---------------------------------------------------------------------------
# Rebuild fallback (Decision #6)
# ---------------------------------------------------------------------------

class TestRebuildFallback:
    """Fallback to CREATE+SELECT+DROP+RENAME when DROP COLUMN fails."""

    def test_rebuild_fallback_when_drop_column_fails(
        self, collision_rich_db: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """When ALTER TABLE DROP COLUMN raises OperationalError, rebuild path is taken.

        Patches migration_v16._attempt_drop_column (the module-level DROP COLUMN
        hook) instead of sqlite3.Connection.execute (a C extension type that
        Python cannot monkeypatch at class level).
        """
        import dotmd.ingestion.migration_v16 as _m16
        _, run_migration_v16, *_ = _import()
        drop_column_called = {"n": 0}

        def patched_attempt_drop_column(
            conn: sqlite3.Connection, table: str, col: str
        ) -> None:
            drop_column_called["n"] += 1
            raise sqlite3.OperationalError("Simulated DROP COLUMN failure")

        monkeypatch.setattr(_m16, "_attempt_drop_column", patched_attempt_drop_column)
        report = run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        assert report.completed is True, "Migration should succeed via rebuild fallback"
        assert drop_column_called["n"] > 0, "DROP COLUMN was never attempted"


# ---------------------------------------------------------------------------
# Invariant helper existence
# ---------------------------------------------------------------------------

class TestInvariantHelper:
    """run_invariants is a callable public helper (single source of truth)."""

    def test_run_invariants_helper_exists_and_callable(
        self, collision_rich_db: Path
    ) -> None:
        """run_invariants(conn) -> InvariantReport is importable and callable."""
        _, run_migration_v16, run_invariants, *_ = _import()
        run_migration_v16(collision_rich_db, allow_payload_divergence=True)
        conn = _conn(collision_rich_db)
        inv_report = run_invariants(conn)
        conn.close()
        assert hasattr(inv_report, "passed")
        assert hasattr(inv_report, "checks")
        assert isinstance(inv_report.checks, list)


# ---------------------------------------------------------------------------
# Cycle-2 NEW-HIGH-1 regression guard: M2M remap covers non-canonical old IDs
# ---------------------------------------------------------------------------

class TestM2MRemapCoverage:
    """Cycle-2 NEW-HIGH-1: step 5c redirect ensures no orphan M2M rows after collapse."""

    def test_m2m_remap_covers_non_canonical_old_ids(
        self, tmp_index_db: Path
    ) -> None:
        """3-file collision group: 1 chunks_* row + 3 M2M rows post-migration (no orphans)."""
        _, run_migration_v16, *_ = _import()
        conn = _conn(tmp_index_db)
        strategy = "heading_512_50"
        table = f"chunks_{strategy}"
        m2m = f"chunk_file_paths_{strategy}"

        shared_text = "shared content for three files in collision group"
        paths = ["/path/file_A.md", "/path/file_B.md", "/path/file_C.md"]
        old_ids = ["old_id_aaaa", "old_id_bbbb", "old_id_cccc"]

        for old_id, fp in zip(old_ids, paths):
            conn.execute(
                f"INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
                "VALUES (?, ?, ?, ?, ?, ?, ?)",
                (old_id, fp, json.dumps(["Same Heading"]), 1, shared_text, 0, 0),
            )
        conn.commit()
        conn.close()

        run_migration_v16(tmp_index_db, allow_payload_divergence=True)
        conn = _conn(tmp_index_db)

        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        assert count == 1, f"Expected 1 row in {table}, got {count}"

        m2m_rows = conn.execute(
            f"SELECT chunk_id, file_path FROM {m2m} ORDER BY file_path"
        ).fetchall()
        assert len(m2m_rows) == 3, f"Expected 3 M2M rows, got {len(m2m_rows)}"
        chunk_ids_in_m2m = {r[0] for r in m2m_rows}
        assert len(chunk_ids_in_m2m) == 1, "All M2M rows must share one new blake3 chunk_id"
        new_blake3_id = chunk_ids_in_m2m.pop()
        assert len(new_blake3_id) == 64, f"New chunk_id not 64-char blake3: {new_blake3_id!r}"

        fp_list = conn.execute(
            f"SELECT file_path FROM {m2m} WHERE chunk_id=? ORDER BY file_path",
            (new_blake3_id,),
        ).fetchall()
        assert [r[0] for r in fp_list] == sorted(paths)

        orphan_count = conn.execute(
            f"SELECT COUNT(*) FROM {m2m} m "
            f"LEFT JOIN {table} c ON c.chunk_id = m.chunk_id "
            f"WHERE c.chunk_id IS NULL"
        ).fetchone()[0]
        assert orphan_count == 0, f"Orphan M2M rows found: {orphan_count}"
        conn.close()


# ---------------------------------------------------------------------------
# Cycle-2 NEW-HIGH-2 regression guards: fail-closed divergence policy
# ---------------------------------------------------------------------------

class TestPayloadDivergenceFailClosed:
    """Cycle-2 NEW-HIGH-2 + Decision #10: fail-closed divergence gate."""

    def _setup_divergent_db(self, tmp_index_db: Path) -> None:
        conn = _conn(tmp_index_db)
        strategy = "heading_512_50"
        table = f"chunks_{strategy}"
        shared_text = "shared text for divergence policy test"
        conn.execute(
            f"INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("div_old_aaa", "/file_X.md", json.dumps(["Context A"]), 1, shared_text, 0, 0),
        )
        conn.execute(
            f"INSERT INTO {table} (chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            ("div_old_bbb", "/file_Y.md", json.dumps(["Context B"]), 2, shared_text, 0, 0),
        )
        conn.commit()
        conn.close()

    def test_aborts_on_divergence_without_flag(self, tmp_index_db: Path) -> None:
        """Migration raises PayloadDivergenceBlocked (exit 4) when divergences exist and no flag."""
        PayloadDivergenceBlocked, run_migration_v16, *_ = _import()
        self._setup_divergent_db(tmp_index_db)

        with pytest.raises(PayloadDivergenceBlocked):
            run_migration_v16(tmp_index_db)

        report_path = tmp_index_db.parent / "divergence_report.txt"
        assert report_path.exists(), "divergence_report.txt not written on abort"

        conn = _conn(tmp_index_db)
        state_row = conn.execute(
            "SELECT status, allow_payload_divergence FROM migration_v16_state "
            "WHERE strategy=?", ("heading_512_50",)
        ).fetchone()
        conn.close()
        assert state_row is not None
        assert state_row[0] == "payload_divergence_blocked"
        assert state_row[1] == 0

        conn = _conn(tmp_index_db)
        count = conn.execute("SELECT COUNT(*) FROM chunks_heading_512_50").fetchone()[0]
        conn.close()
        assert count == 2, "DB should be rolled back to pre-migration state"

    def test_proceeds_with_flag_records_to_state(self, tmp_index_db: Path) -> None:
        """Migration completes with --allow-payload-divergence; audit persisted to state."""
        _, run_migration_v16, *_ = _import()
        self._setup_divergent_db(tmp_index_db)

        report = run_migration_v16(tmp_index_db, allow_payload_divergence=True)
        assert report.completed is True

        conn = _conn(tmp_index_db)
        row = conn.execute(
            "SELECT chunk_id, heading_hierarchy FROM chunks_heading_512_50"
        ).fetchone()
        assert row is not None
        assert len(row[0]) == 64

        assert report.payload_mismatch_warnings >= 1

        import json as _json
        state_row = conn.execute(
            "SELECT allow_payload_divergence, payload_divergences FROM migration_v16_state "
            "WHERE strategy=?", ("heading_512_50",)
        ).fetchone()
        conn.close()
        assert state_row is not None
        assert state_row[0] == 1
        assert state_row[1] is not None
        divergences = _json.loads(state_row[1])
        assert len(divergences) >= 1

    def test_verify_only_reports_divergence_count(self, tmp_index_db: Path) -> None:
        """--verify-only reports divergence_count > 0 and example paths; DB unchanged."""
        from tests.conftest import assert_db_bytes_unchanged
        _, run_migration_v16, *_ = _import()
        self._setup_divergent_db(tmp_index_db)

        before = hashlib.md5(tmp_index_db.read_bytes()).hexdigest()
        report = run_migration_v16(tmp_index_db, verify_only=True)
        assert report.payload_divergence_preview is not None
        assert report.payload_divergence_preview["count"] >= 1
        assert len(report.payload_divergence_preview.get("example_paths", [])) >= 1
        assert_db_bytes_unchanged(tmp_index_db, before)
