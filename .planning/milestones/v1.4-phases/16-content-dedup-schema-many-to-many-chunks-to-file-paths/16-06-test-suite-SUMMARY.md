---
phase: 16-content-dedup-schema
plan: 06
subsystem: tests
tags: [tdd, fixtures, red-phase, wave-1, migration-v16, m2m, dedup]
dependency_graph:
  requires: []
  provides: [test-suite-RED-baseline, pre-v16-schema-fixtures, ALL_TEST_NAMES-manifest]
  affects: [16-01, 16-02, 16-03, 16-04, 16-05]
tech_stack:
  added: []
  patterns: [deferred-import RED tests, set-equivalence schema fidelity, conftest fixture hierarchy]
key_files:
  created:
    - backend/tests/fixtures/schema_pre_v16.sql
    - backend/tests/fixtures/schema_pre_v16.sqlite.dump
    - backend/tests/conftest.py
    - backend/tests/test_fixture_fidelity.py
    - backend/tests/ingestion/test_migration_v16.py
    - backend/tests/ingestion/test_migration_v16_invariants.py
    - backend/tests/ingestion/test_migration_v15_superseded.py
    - backend/tests/ingestion/test_trickle_lock.py
    - backend/tests/ingestion/test_pipeline_m2m_insert.py
    - backend/tests/ingestion/test_migration_v16_ops.py
    - backend/tests/ingestion/test_migration_v16_progress.py
    - backend/tests/ingestion/test_pipeline_purge.py
    - backend/tests/ingestion/test_pipeline_orphan_sweep.py
    - backend/tests/ingestion/test_chunker.py
    - backend/tests/storage/test_metadata_m2m.py
    - backend/tests/api/test_search_result_shape.py
    - backend/tests/api/test_service_search.py
    - backend/tests/api/test_search_parity.py
    - backend/tests/cli/test_migrate_cli.py
    - backend/tests/cli/test_search_output.py
    - backend/tests/cli/test_status_output.py
    - backend/tests/mcp/test_search_tool.py
  modified:
    - backend/tests/conftest.py (full rewrite — replaces old minimal fixture set)
    - backend/pyproject.toml (added testpaths + addopts to [tool.pytest.ini_options])
decisions:
  - "schema_pre_v16.sql mirrors live production DB verbatim (no migration_v15_state — Phase 15 never ran)"
  - "sqlite_sequence excluded from fidelity set-equivalence (SQLite internal, no CREATE statement)"
  - "Deferred-import pattern used for RED tests: production imports inside test methods, not at module level, so --collect-only works before P1-P5 ship"
  - "blake3 installed in test venv (was missing, pre-existing gap blocking collect-only)"
  - "Reference dump covers only non-virtual tables (vec0 requires sqlite_vec extension at connect time — excluded from fixture schema)"
metrics:
  duration: "21m 5s"
  completed: "2026-04-25"
  tasks: 3
  files_created: 22
  tests_collected: 157
  new_test_functions: 84
---

# Phase 16 Plan 06: Test Suite (Wave 1 RED Phase) Summary

Wave 1 RED phase delivering the full Decision #7 test matrix. Every downstream plan (P1–P5) now has failing test targets it must turn GREEN. Suite is intentionally RED — this is the wave-1 baseline.

## Fixture Architecture

### Schema Fidelity (Three-Layer)

**Layer 1 — DDL signature presence** (`test_schema_pre_v16_sql_contains_required_ddl_signatures`):
Checks that every expected table name appears in `schema_pre_v16.sql`. Retained for human readability.

**Layer 2 — Set-equivalence vs committed reference** (`test_fixture_schema_byte_matches_reference_dump`):
Builds a temp DB from `schema_pre_v16.sql` via `executescript()`, extracts its CREATE statements from `sqlite_master`, normalises whitespace, and compares as an equal set against the committed `schema_pre_v16.sqlite.dump`. Catches column ordering drift, missing indexes, auxiliary table omissions. Excludes `sqlite_sequence` (SQLite internal, no user-visible CREATE statement).

**Layer 3 — Non-empty dump sanity floor** (`test_reference_dump_is_committed_and_non_empty`):
Verifies the reference dump file exists and has ≥ 10 CREATE TABLE statements.

### Schema Source

`schema_pre_v16.sql` and `schema_pre_v16.sqlite.dump` were captured from the live production container (`dotmd-api-1 /dotmd-index/index.db`, 2026-04-25). The production DB is in the pre-v16 state because Phase 15 was blocked by the M2M collision issue this phase resolves.

Note: `migration_v15_state` table is absent from the reference dump — Phase 15 never ran on production. The fixture accurately mirrors production starting state.

Note: `vec_chunks_*` VIRTUAL TABLES (vec0) require the `sqlite_vec` extension loaded at connection time. They are intentionally omitted from the fixture schema. Migration tests that need vector data use `vec_meta_*` plain tables and mock or skip vec0 operations.

### Fixture Hierarchy

```
tmp_index_db     — empty pre-v16 schema DB (base fixture, all tests)
├── empty_db         — alias for tmp_index_db (no data rows; no-op migration tests)
└── collision_rich_db — PRIMARY fixture (production starting state with 4 collision scenarios)
    ├── pre_v15_db      — alias for collision_rich_db (Review-MED clarity)
    └── post_v15_pre_v16_db — SECONDARY fixture (blake3-remapped chunk_ids, pre-v16 schema)
```

`collision_rich_db` is documented as PRIMARY — it represents actual production state:
- Group A: pytest cache duplication (2 files, identical body)
- Group B: mirrored skill copies (2 files, identical body)
- Group C: repeated identical heading in same file (2 M2M rows, different chunk_index → different blake3 IDs)
- Non-collision: unique file

## Test Module Map (Plan → File)

| Plan | Test File | Coverage |
|------|-----------|----------|
| P1 | `test_migration_v16.py` | DEDUP-01..04, Review-HIGH-1..4, cycle-2 NEW-HIGH-1+2, dry-run, lock |
| P1 | `test_migration_v16_invariants.py` | DEDUP-10 via `run_invariants(conn)` |
| P1 | `test_migration_v15_superseded.py` | DEDUP-11 no-op stub + deprecation banner |
| P1 | `test_metadata_m2m.py` | M2M metadata surface, caller-conn contract |
| P1 | `test_chunker.py` | char_offset removal (Decision #8), file_paths list emission |
| P2 | `test_migration_v16_ops.py` | DEDUP-06 dry-run/verify-only/status report fields |
| P2 | `test_migration_v16_progress.py` | ProgressReport mode + rows_per_sec assertions |
| P2 | `test_migrate_cli.py` | CLI migrate subcommand (7 CliRunner tests) |
| P3 | `test_pipeline_m2m_insert.py` | INSERT OR IGNORE idempotency, payload mismatch WARN |
| P3 | `test_trickle_lock.py` | Advisory lock startup check (4 modes) |
| P4 | `test_pipeline_purge.py` | Holder-aware purge + transaction atomicity (7 tests) |
| P4 | `test_pipeline_orphan_sweep.py` | M2M-based orphan sweep (3 tests) |
| P5 | `test_search_result_shape.py` | DEDUP-09 file_paths list shape + batch hydration |
| P5 | `test_service_search.py` | DotMDService.search file_paths contract |
| P5 | `test_search_parity.py` | DEDUP-10b round-trip top-K parity |
| P5 | `test_search_output.py` | CLI renderer single/multi holder format |
| P5 | `test_status_output.py` | Status counts from M2M |
| P5 | `test_search_tool.py` | MCP file_paths JSON array |

## pytest Configuration

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-x --tb=short"
markers = ["smoke: smoke tests requiring a running dotMD stack"]
```

## ALL_TEST_NAMES Manifest

Location: `backend/tests/conftest.py::ALL_TEST_NAMES` — a constant list of all 84 expected test function names in the Phase 16 suite. Downstream plans can reference these names to verify their implementations complete the correct targets.

## RED State Confirmation

The suite is **intentionally RED** at end of Wave 1. Running the Phase 16 test files produces failures on missing modules (`ModuleNotFoundError: migration_v16`) and missing fields (`AttributeError: file_paths`). This is the wave-1 baseline.

`--collect-only` returns 157 tests with zero collection errors. All failures are at test execution time (not collection time), using the deferred-import pattern:

```python
def _import():
    from dotmd.ingestion.migration_v16 import run_migration_v16, ...
    return ...

def test_something(self, fixture):
    run_migration_v16, _ = _import()  # fails here until P1 ships
    ...
```

## Review-Concern Regression Guard Coverage

| Review Concern | Test(s) |
|----------------|---------|
| Review-HIGH-1 (shadow-column flow) | `test_shadow_column_flow_no_pk_violation` |
| Review-HIGH-2 (payload invariant mismatch) | `test_collision_group_payload_invariant_mismatch_logs_warn`, `test_aborts_on_divergence_without_flag`, `test_proceeds_with_flag_records_to_state` |
| Review-HIGH-3 (_make_chunk_id reuse) | `test_uses_chunker_make_chunk_id_helper` |
| Review-HIGH-4 (canonical semantics) | `test_collision_canonical_is_min_old_id_for_payload_but_final_id_is_blake3` |
| Review-MED-6 (dry-run lock) | `test_dry_run_acquires_and_releases_lock`, `test_refuses_on_dry_run_lock` |
| Review-HIGH-P3 (payload mismatch warn) | `test_payload_mismatch_logs_warn_without_overwriting` |
| Review-HIGH-P4 (atomicity) | `test_purge_is_transactional_on_failure` |
| Review-MED-P4 (graph holder-aware) | `test_graph_holder_aware_path_when_audit_flags_unsafe` |
| Review-LOW-10 (non-brittle assertions) | All tests — assert on return values/report objects, not log strings |
| Review-LOW-11 (CLI rendering format) | `test_renders_multi_holder_with_plus_n_suffix` |
| Review-LOW-12 (batch hydration) | `test_get_file_paths_for_chunk_ids_single_query`, `test_batch_hydration_single_query_per_strategy` |
| Cycle-2 NEW-HIGH-1 (M2M remap gap) | `test_m2m_remap_covers_non_canonical_old_ids` |
| Cycle-2 NEW-HIGH-2 (payload divergence) | `test_aborts_on_divergence_without_flag`, `test_proceeds_with_flag_records_to_state`, `test_verify_only_reports_divergence_count` |

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed normalise() function in fidelity test for sqlite_master format**
- **Found during:** Task 1 fidelity test execution
- **Issue:** The `_normalise()` function split on semicolons but sqlite_master output doesn't have semicolons between statements. This caused the set-equivalence comparison to see only 1 statement vs 27.
- **Fix:** Added two-path splitting: semicolon-split for reference dump, `\n(?=CREATE )` lookahead split for sqlite_master row output. Also excluded `sqlite_sequence` (SQLite internal table with no user-visible CREATE DDL).
- **Commit:** d8e8f66

**2. [Rule 2 - Missing Critical Functionality] Installed blake3 in test venv**
- **Found during:** Task 1 collect-only
- **Issue:** `blake3` not installed in `.venv/` despite being in pyproject.toml dependencies. Pre-existing gap; blocked all test collection (`test_diff_reporting.py` failed on import).
- **Fix:** `uv pip install blake3 --python .venv/bin/python3`
- **Commit:** d8e8f66

**3. [Rule 1 - Bug] Removed migration_v15_state from schema_pre_v16.sql**
- **Found during:** Task 1 fidelity test
- **Issue:** Initial fixture SQL included `migration_v15_state` table but it is absent from the real production DB (Phase 15 never ran). Including it caused the set-equivalence comparison to fail.
- **Fix:** Removed from fixture SQL; added comment documenting why it's absent. The DDL signature test was also updated to remove the now-incorrect assertion.
- **Commit:** d8e8f66

## Known Stubs

None. All test files contain real assertions on missing production code (not placeholder `pass` bodies). The RED state is from missing production modules, not stub tests.

## Self-Check: PASSED

- All 22 created files exist on disk: VERIFIED
- All 3 task commits exist in git log: d8e8f66, 494f6e5, 5838070: VERIFIED
- `pytest --collect-only tests/` reports 157 tests, 0 errors: VERIFIED
- Running Phase 16 tests produces RED (failures on missing implementations): VERIFIED
- Fidelity tests (3) pass: VERIFIED
