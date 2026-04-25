"""Shared test fixtures for dotmd Phase 16 test suite.

Provides:
  - tmp_index_db       : empty pre-v16 schema DB in a tmp dir
  - empty_db           : alias for tmp_index_db (no data rows)
  - collision_rich_db  : PRIMARY fixture — pre-v15-format data with collision groups
  - post_v15_pre_v16_db: SECONDARY fixture — blake3-remapped chunk_ids (as if v15 ran)
  - pre_v15_db         : alias for collision_rich_db (Review-MED clarity alias)
  - query_set          : stable list of ~10 queries for round-trip parity tests
  - assert_db_bytes_unchanged : helper for dry-run / verify-only tests
  - ALL_TEST_NAMES     : manifest of all expected test function names in the suite
"""

from __future__ import annotations

import hashlib
import json
import random
import sqlite3
import struct
from pathlib import Path
from typing import Generator

import pytest

# ---------------------------------------------------------------------------
# Schema DDL path
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"
_SCHEMA_SQL = _FIXTURES_DIR / "schema_pre_v16.sql"

# Strategies present in the pre-v16 DB
STRATEGIES = ["heading_512_50", "contextual_512_50"]
# Default model suffix for vec_meta tables
MODEL_SUFFIX = "multilingual_e5_large"


# ---------------------------------------------------------------------------
# Pre-v15 chunk_id format helpers
# (simulate the old 128-char blake2b ids that migration_v16 will rewrite)
# ---------------------------------------------------------------------------

def _make_old_chunk_id(file_path: str, chunk_index: int) -> str:
    """Simulate the pre-v15 128-char blake2b chunk_id format."""
    payload = f"{file_path}:{chunk_index}"
    return hashlib.blake2b(payload.encode()).hexdigest()  # 128 chars


def _make_blake3_chunk_id(text: str, chunk_index: int, strategy: str) -> str:
    """Compute the post-v15/v16 64-char blake3 chunk_id.

    Mirrors chunker._make_chunk_id logic without importing migration_v16.
    Only used by post_v15_pre_v16_db fixture.
    """
    import blake3 as _blake3
    body_checksum = _blake3.blake3(f"text\n{text}".encode()).hexdigest()
    payload = f"{body_checksum}:{chunk_index}:{strategy}"
    return _blake3.blake3(payload.encode()).hexdigest()


def _seeded_vector(seed: int, dim: int = 8) -> bytes:
    """Return a deterministic stub embedding vector as raw float32 bytes.

    Uses a small dimension (8) for test speed; dim matches vec_meta usage.
    """
    rng = random.Random(seed)
    floats = [rng.gauss(0, 1) for _ in range(dim)]
    return struct.pack(f"{dim}f", *floats)


def _insert_chunk_row(
    conn: sqlite3.Connection,
    strategy: str,
    chunk_id: str,
    file_path: str,
    heading_hierarchy: list[str],
    level: int,
    text: str,
    chunk_index: int,
    char_offset: int = 0,
    vec_seed: int | None = None,
) -> None:
    """Insert a single chunk row into pre-v16 schema tables (chunks_* + fts + vec_meta)."""
    table = f"chunks_{strategy}"
    fts_table = f"chunks_fts_{strategy}"
    vm_table = f"vec_meta_{strategy}_{MODEL_SUFFIX}"

    conn.execute(
        f"INSERT OR IGNORE INTO {table} "
        "(chunk_id, file_path, heading_hierarchy, level, text, chunk_index, char_offset) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (chunk_id, file_path, json.dumps(heading_hierarchy), level, text, chunk_index, char_offset),
    )
    conn.execute(
        f"INSERT OR IGNORE INTO {fts_table} (chunk_id, text) VALUES (?, ?)",
        (chunk_id, text),
    )
    seed = vec_seed if vec_seed is not None else abs(hash(chunk_id)) % (2**31)
    conn.execute(
        f"INSERT OR IGNORE INTO {vm_table} (chunk_id, text_hash) VALUES (?, ?)",
        (chunk_id, hashlib.md5(text.encode()).hexdigest()),
    )


# ---------------------------------------------------------------------------
# Core DB fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_index_db(tmp_path: Path) -> Generator[Path, None, None]:
    """Empty pre-v16 schema DB in a temp dir, built from schema_pre_v16.sql.

    This is the base fixture: schema only, no data rows.

    Also pre-creates the migration_v16 infrastructure tables
    (migration_v16_state + migration_v16_lock) so that dry-run tests can
    verify the lock lifecycle without their byte-equality hash capturing a
    pre-infrastructure state.
    """
    db_path = tmp_path / "index.db"
    ddl = _SCHEMA_SQL.read_text()
    conn = sqlite3.connect(str(db_path))
    conn.executescript(ddl)
    # Pre-create migration_v16 infrastructure tables so dry-run tests that
    # query migration_v16_lock after a dry-run don't get OperationalError.
    # These tables are created by migration_v16.py itself on first run, but
    # the fixture ensures a stable baseline for byte-equality assertions
    # (the tables exist before `before` hash is captured).
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS migration_v16_state (
            strategy                TEXT PRIMARY KEY,
            status                  TEXT NOT NULL DEFAULT 'complete',
            completed_at            TEXT NOT NULL DEFAULT '',
            collisions_collapsed    INTEGER NOT NULL DEFAULT 0,
            divergence_warnings     INTEGER NOT NULL DEFAULT 0,
            payload_mismatch_warnings INTEGER NOT NULL DEFAULT 0,
            allow_payload_divergence  INTEGER NOT NULL DEFAULT 0,
            payload_divergences     TEXT
        );
        CREATE TABLE IF NOT EXISTS migration_v16_lock (
            id        INTEGER PRIMARY KEY CHECK (id = 1),
            locked_at TEXT NOT NULL,
            pid       INTEGER NOT NULL,
            host      TEXT NOT NULL,
            mode      TEXT NOT NULL
        );
    """)
    conn.commit()
    conn.close()
    yield db_path


@pytest.fixture
def empty_db(tmp_index_db: Path) -> Path:
    """Pre-v16 schema with no data rows.

    Used for empty-strategy / empty-knowledgebase migration tests (no-op path).
    """
    return tmp_index_db


# ---------------------------------------------------------------------------
# collision_rich_db — PRIMARY fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def collision_rich_db(tmp_index_db: Path) -> Path:
    """PRIMARY fixture representing actual production starting state (pre-v15 chunk_ids).

    Populated with collision scenarios mirroring real-world knowledgebase duplicates:

    Group A — pytest cache duplication (size-2 collision):
        ~/.pytest_cache/README.md  +  <project>/.pytest_cache/README.md
        Identical body → same blake3 after migration.

    Group B — mirrored skill copies (size-2 collision):
        ~/.agents/foo.md  +  ~/repos/project/skills/foo.md
        Identical body → same blake3 after migration.

    Group C — repeated heading in same file (PK-with-chunk_index regression case):
        ~/kb/a.md: two identical heading+body blocks at different chunk_index values.
        Same body → same blake3, different chunk_index → different final blake3 IDs
        (because _make_chunk_id includes chunk_index in the hash).
        This tests the UNIQUE(file_path, chunk_index) invariant per strategy.

    Non-collision:
        ~/kb/unique.md: one chunk with unique content.

    All chunk_ids are pre-v15 format (128-char blake2b) — what migration_v16 will remap.

    Documented as PRIMARY — production has never run migration_v15, so its chunk_ids
    are the old blake2b format that migration_v16.py's needs_migration_v16() must detect.
    """
    conn = sqlite3.connect(str(tmp_index_db))

    # Shared body for collision groups
    PYTEST_README_BODY = (
        "# pytest cache directory\n\n"
        "This directory contains data from the pytest cache mechanism.\n"
        "Do not commit this to version control.\n"
    )
    SKILL_BODY = (
        "# Skill: foo\n\n"
        "This skill provides foo functionality.\n"
        "Use it when you need to foo.\n"
    )
    REPEATED_HEADING_BODY = (
        "# Introduction\n\n"
        "This is the introduction section content.\n"
    )
    UNIQUE_BODY = (
        "# Unique Content\n\n"
        "This content appears in exactly one file in the knowledgebase.\n"
        "It will not participate in any collision group.\n"
    )

    for strategy in STRATEGIES:
        # --- Group A: pytest cache duplication ---
        path_a1 = "/home/user/.pytest_cache/README.md"
        path_a2 = "/home/user/repos/project/.pytest_cache/README.md"
        cid_a1 = _make_old_chunk_id(path_a1, 0)
        cid_a2 = _make_old_chunk_id(path_a2, 0)
        _insert_chunk_row(conn, strategy, cid_a1, path_a1,
                          ["pytest cache directory"], 1, PYTEST_README_BODY, 0, vec_seed=101)
        _insert_chunk_row(conn, strategy, cid_a2, path_a2,
                          ["pytest cache directory"], 1, PYTEST_README_BODY, 0, vec_seed=101)

        # --- Group B: mirrored skill copies ---
        path_b1 = "/home/user/.agents/foo.md"
        path_b2 = "/home/user/repos/project/skills/foo.md"
        cid_b1 = _make_old_chunk_id(path_b1, 0)
        cid_b2 = _make_old_chunk_id(path_b2, 0)
        _insert_chunk_row(conn, strategy, cid_b1, path_b1,
                          ["Skill: foo"], 1, SKILL_BODY, 0, vec_seed=202)
        _insert_chunk_row(conn, strategy, cid_b2, path_b2,
                          ["Skill: foo"], 1, SKILL_BODY, 0, vec_seed=202)

        # --- Group C: repeated heading in same file (different chunk_index) ---
        # Note: same body + different chunk_index → DIFFERENT blake3 IDs after migration
        # (because chunk_index is in the hash input).  These do NOT form a collision group.
        # They test that UNIQUE(file_path, chunk_index) per strategy is preserved.
        path_c = "/home/user/kb/a.md"
        cid_c0 = _make_old_chunk_id(path_c, 0)
        cid_c1 = _make_old_chunk_id(path_c, 1)
        _insert_chunk_row(conn, strategy, cid_c0, path_c,
                          ["Introduction"], 1, REPEATED_HEADING_BODY, 0, vec_seed=303)
        _insert_chunk_row(conn, strategy, cid_c1, path_c,
                          ["Introduction"], 1, REPEATED_HEADING_BODY, 1, vec_seed=304)

        # --- Non-collision: unique file ---
        path_u = "/home/user/kb/unique.md"
        cid_u = _make_old_chunk_id(path_u, 0)
        _insert_chunk_row(conn, strategy, cid_u, path_u,
                          ["Unique Content"], 1, UNIQUE_BODY, 0, vec_seed=404)

    conn.commit()
    conn.close()
    return tmp_index_db


@pytest.fixture
def pre_v15_db(collision_rich_db: Path) -> Path:
    """Alias for collision_rich_db (Review-MED clarity alias).

    Identical to collision_rich_db; named to clarify that the data represents
    the pre-v15 state (128-char blake2b chunk_ids not yet remapped).
    """
    return collision_rich_db


# ---------------------------------------------------------------------------
# post_v15_pre_v16_db — SECONDARY fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def post_v15_pre_v16_db(collision_rich_db: Path) -> Path:
    """SECONDARY fixture: chunk_ids already blake3-remapped as if v15 completed.

    Documented as 'secondary' — production has pre-v15 chunk_ids (collision_rich_db
    is the actual production starting state). This fixture represents a DB where
    migration_v15 ran successfully, so all chunk_ids are already 64-char blake3.
    The schema still has file_path/chunk_index/char_offset columns (pre-v16 shape).

    Used only for tests that need to distinguish v15-complete vs v16-complete states.
    """
    conn = sqlite3.connect(str(collision_rich_db))

    for strategy in STRATEGIES:
        table = f"chunks_{strategy}"
        fts_table = f"chunks_fts_{strategy}"
        vm_table = f"vec_meta_{strategy}_{MODEL_SUFFIX}"

        # Read current rows and remap their chunk_ids to blake3
        rows = conn.execute(
            f"SELECT chunk_id, file_path, heading_hierarchy, level, text, chunk_index "
            f"FROM {table}"
        ).fetchall()

        id_map: dict[str, str] = {}
        for old_id, fp, hh, lv, text, ci in rows:
            new_id = _make_blake3_chunk_id(text, ci, strategy)
            id_map[old_id] = new_id

        for old_id, new_id in id_map.items():
            try:
                conn.execute(f"UPDATE {table} SET chunk_id=? WHERE chunk_id=?", (new_id, old_id))
                conn.execute(f"UPDATE {fts_table} SET chunk_id=? WHERE chunk_id=?", (new_id, old_id))
                conn.execute(f"UPDATE {vm_table} SET chunk_id=? WHERE chunk_id=?", (new_id, old_id))
            except sqlite3.IntegrityError:
                # Collision group: two rows map to same new_id; skip the duplicate
                conn.execute(f"DELETE FROM {table} WHERE chunk_id=?", (old_id,))
                conn.execute(f"DELETE FROM {fts_table} WHERE chunk_id=?", (old_id,))
                conn.execute(f"DELETE FROM {vm_table} WHERE chunk_id=?", (old_id,))

    conn.commit()
    conn.close()
    return collision_rich_db


# ---------------------------------------------------------------------------
# query_set fixture
# ---------------------------------------------------------------------------

@pytest.fixture
def query_set() -> list[str]:
    """Stable list of ~10 test queries for round-trip top-K parity tests.

    Covers collision-group content (pytest cache, skill files) and
    non-collision content (unique file). Fixed strings so top-K results
    are reproducible across runs when the stub embedder is deterministic.
    """
    return [
        "pytest cache directory",
        "do not commit to version control",
        "skill provides foo functionality",
        "when you need to foo",
        "unique content appears in exactly one file",
        "introduction section content",
        "knowledgebase",
        "heading hierarchy",
        "chunk index strategy",
        "content addressed chunk id",
    ]


# ---------------------------------------------------------------------------
# assert_db_bytes_unchanged helper
# ---------------------------------------------------------------------------

def assert_db_bytes_unchanged(db_path: Path, before_hash: str) -> None:
    """Assert that index.db has not been modified since before_hash was captured.

    Usage:
        before = hashlib.md5(db_path.read_bytes()).hexdigest()
        run_something(db_path)
        assert_db_bytes_unchanged(db_path, before)

    Uses MD5 for speed (not security).  WAL-mode DBs should be checkpointed
    before hashing; the helper also checks that the WAL file is absent/empty.
    """
    after_hash = hashlib.md5(db_path.read_bytes()).hexdigest()
    wal_path = db_path.with_suffix(".db-wal")
    wal_size = wal_path.stat().st_size if wal_path.exists() else 0
    assert after_hash == before_hash and wal_size == 0, (
        f"DB was modified: before={before_hash!r} after={after_hash!r} "
        f"wal_size={wal_size}"
    )


# ---------------------------------------------------------------------------
# ALL_TEST_NAMES manifest
# ---------------------------------------------------------------------------

ALL_TEST_NAMES: list[str] = [
    # test_fixture_fidelity.py
    "test_schema_pre_v16_sql_contains_required_ddl_signatures",
    "test_fixture_schema_byte_matches_reference_dump",
    "test_reference_dump_is_committed_and_non_empty",

    # test_migration_v16.py
    "test_creates_m2m_table_and_index",
    "test_drops_file_path_chunk_index_char_offset",
    "test_shadow_column_flow_no_pk_violation",
    "test_collision_canonical_is_min_old_id_for_payload_but_final_id_is_blake3",
    "test_collision_group_payload_invariant_mismatch_logs_warn",
    "test_uses_chunker_make_chunk_id_helper",
    "test_divergence_warn_emitted_above_threshold",
    "test_divergence_warn_not_emitted_below_threshold",
    "test_resume_after_crash_skips_completed_strategy",
    "test_empty_strategy_no_op",
    "test_dry_run_leaves_db_untouched",
    "test_dry_run_acquires_and_releases_lock",
    "test_lock_acquired_and_released",
    "test_rebuild_fallback_when_drop_column_fails",
    "test_run_invariants_helper_exists_and_callable",
    "test_m2m_remap_covers_non_canonical_old_ids",
    "test_aborts_on_divergence_without_flag",
    "test_proceeds_with_flag_records_to_state",
    "test_verify_only_reports_divergence_count",

    # test_migration_v16_invariants.py
    "test_all_chunk_ids_are_64_hex_blake3",
    "test_no_orphan_vec_meta_rows",
    "test_no_orphan_fts_rows",
    "test_unique_file_path_chunk_index_per_strategy",
    "test_row_count_delta_matches_expected_collapse",
    "test_backup_file_exists",

    # test_migration_v15_superseded.py
    "test_needs_migration_v15_returns_false",
    "test_run_migration_v15_is_noop",
    "test_v15_module_has_deprecation_banner",

    # test_trickle_lock.py
    "test_refuses_while_locked",
    "test_starts_when_lock_cleared",
    "test_starts_when_lock_table_absent",
    "test_refuses_on_dry_run_lock",

    # test_pipeline_m2m_insert.py
    "test_insert_or_ignore_on_repeat",
    "test_two_files_identical_content_share_chunk",
    "test_repeated_heading_in_same_file_creates_two_m2m_rows",
    "test_vec_meta_not_rewritten_on_reindex",
    "test_payload_mismatch_logs_warn_without_overwriting",

    # test_chunker.py
    "test_chunker_emits_no_char_offset",
    "test_chunker_emits_file_paths_as_single_element_list",

    # test_metadata_m2m.py
    "test_insert_chunk_is_idempotent",
    "test_add_file_path_is_idempotent",
    "test_get_file_paths_sorted_lex",
    "test_get_file_paths_for_chunk_ids_single_query",
    "test_delete_m2m_for_file_returns_orphans_uses_caller_conn",
    "test_chunk_model_rejects_char_offset",

    # test_migration_v16_ops.py
    "test_dry_run_writes_nothing",
    "test_verify_only_no_mutation",
    "test_status_reports_no_state_on_fresh_db",
    "test_status_reports_per_strategy_state_after_run",

    # test_migration_v16_progress.py
    "test_progress_line_emits_rows_per_sec_and_eta",
    "test_dry_run_prefix_present",
    "test_verify_only_prefix_present",

    # test_migrate_cli.py
    "test_cli_run_dry_run_exit_zero_db_unchanged",
    "test_cli_verify_only_exit_zero_db_unchanged",
    "test_cli_dry_run_and_verify_only_mutex_exit_2",
    "test_cli_status_fresh_db",
    "test_cli_status_post_migration",
    "test_cli_run_stale_lock_exit_2_with_hint",
    "test_cli_verify_only_invariant_violation_exit_1",

    # test_pipeline_purge.py
    "test_purge_single_holder_cascades_chunk",
    "test_purge_shared_holder_preserves_chunk",
    "test_purge_mixed_orphans_and_shared",
    "test_purge_is_transactional_on_failure",
    "test_purge_runs_across_all_strategies",
    "test_graph_cleanup_failure_does_not_rollback_db",
    "test_graph_holder_aware_path_when_audit_flags_unsafe",

    # test_pipeline_orphan_sweep.py
    "test_orphan_sweep_finds_missing_files",
    "test_orphan_sweep_ignores_present_files",
    "test_orphan_sweep_multi_strategy",

    # test_search_result_shape.py
    "test_file_paths_field_is_list",
    "test_file_paths_sorted_lex",
    "test_single_holder_returns_single_element_list",
    "test_no_file_path_attr",
    "test_graph_direct_hit_also_hydrates",
    "test_batch_hydration_single_query_per_strategy",

    # test_service_search.py
    "test_search_returns_file_paths_list",
    "test_search_respects_top_k",

    # test_search_parity.py
    "test_top_k_parity_for_non_collision_chunks",

    # test_search_output.py
    "test_renders_single_holder_no_more_suffix",
    "test_renders_multi_holder_with_plus_n_suffix",

    # test_status_output.py
    "test_counts_distinct_paths_from_m2m",

    # test_search_tool.py (MCP)
    "test_file_paths_is_json_array",
    "test_docstring_mentions_file_paths",
]
