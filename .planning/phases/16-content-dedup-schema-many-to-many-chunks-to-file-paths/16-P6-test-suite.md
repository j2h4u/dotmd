---
phase: 16-content-dedup-schema
plan: 6
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/tests/conftest.py
  - backend/tests/ingestion/test_migration_v16.py
  - backend/tests/ingestion/test_migration_v16_ops.py
  - backend/tests/ingestion/test_migration_v16_progress.py
  - backend/tests/ingestion/test_migration_v16_invariants.py
  - backend/tests/ingestion/test_migration_v15_superseded.py
  - backend/tests/ingestion/test_trickle_lock.py
  - backend/tests/ingestion/test_pipeline_m2m_insert.py
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
  - backend/pyproject.toml
autonomous: true
requirements: [DEDUP-10, DEDUP-10b]
must_haves:
  truths:
    - "Every downstream plan (P1–P5) has a failing test file it must turn green — Wave 0 RED phase."
    - "Collision-rich fixture exists: pytest boilerplate + mirrored skills + symlinks + repeated in-file headings."
    - "Empty-strategy + empty-knowledgebase fixtures exist and are no-ops for the migration."
    - "Round-trip top-K parity test proves search results for non-collision chunks unchanged pre- vs post-migration."
    - "Invariant suite: 64-char blake3 ids, no orphans in vec_meta_*/FTS, UNIQUE(file_path, chunk_index) per strategy."
    - "pytest is confirmed as the framework; `backend/pyproject.toml` has [tool.pytest.ini_options] with an `addopts` baseline."
  artifacts:
    - path: backend/tests/conftest.py
      provides: "Shared fixtures: tmp_index_db, collision_rich_db, empty_db, post_v15_pre_v16_db, query_set."
    - path: backend/tests/ingestion/test_migration_v16.py
      provides: "Core migration behaviour — DEDUP-01..04."
    - path: backend/tests/ingestion/test_migration_v16_invariants.py
      provides: "DEDUP-10 invariant battery."
    - path: backend/tests/api/test_search_parity.py
      provides: "DEDUP-10b round-trip top-K parity."
  key_links:
    - from: backend/tests/conftest.py
      to: backend/src/dotmd/ingestion/migration_v15.py
      via: "fixture uses v15-era schema shape to build pre-v16 DB"
      pattern: "CREATE TABLE chunks_.*file_path"
    - from: backend/tests/api/test_search_parity.py
      to: backend/src/dotmd/api/service.py
      via: "DotMDService.search invoked pre/post migration with fixed query set"
      pattern: "top_k_parity"
---

<objective>
Build the test suite + fixtures FIRST so every downstream plan (P1–P5) has a RED target it must turn GREEN. Delivers the full Decision #7 matrix: data correctness + operational + invariants + quality (round-trip parity) + ops-mode tests.

Purpose: Wave 0 gap closure per the Nyquist rule — every `<verify><automated>` command in P1–P5 references a test file; those files must exist before P1–P5 execute. Also verifies pytest configuration (Research Assumption A2).

Output: Test module skeletons + the conftest fixture builder for collision-rich / empty / pre-v16 databases.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@backend/pyproject.toml
@backend/src/dotmd/ingestion/migration_v15.py
@backend/src/dotmd/storage/metadata.py
@backend/CLAUDE.md
</context>

<tasks>

<task type="auto">
  <name>Task 1: Confirm pytest config + shared fixtures in conftest.py</name>
  <files>backend/pyproject.toml, backend/tests/conftest.py</files>
  <action>
    1. Verify `pytest` is in `backend/pyproject.toml` dev extras. If absent, add minimal `[tool.pytest.ini_options]` with `testpaths = ["tests"]` and `addopts = "-x --tb=short"`.

    2. Build these fixtures in `backend/tests/conftest.py`:

       - `tmp_index_db` — creates an empty `index.db` in a tmp dir with the pre-v16 schema (chunks_<strategy> with file_path/chunk_index/char_offset columns, vec_meta_*, vec0_*, chunks_fts_*). Matches what migration_v15.py expects as input.

       - `empty_db(tmp_index_db)` — pre-v16 schema with no data rows; used for empty-strategy / empty-knowledgebase tests.

       - `collision_rich_db(tmp_index_db)` — pre-v16 DB populated with:
         * file `~/.pytest_cache/README.md` + `<project>/.pytest_cache/README.md` (identical body → collision group of size 2)
         * file `~/.agents/foo.md` + `<repos>/foo.md` (mirrored skill → collision group of size 2)
         * file `~/kb/a.md` with two repeated identical headings in same file (PK-with-chunk_index regression case)
         * one non-collision file `~/kb/unique.md`
         Populates chunks_*, vec_meta_* (deterministic stub vectors via seeded RNG), chunks_fts_* consistently.

       - `post_v15_pre_v16_db(collision_rich_db)` — chunk_ids already blake3-remapped (as if v15 completed successfully), but schema still has the v15 shape. This is the realistic starting point for migration_v16.

       - `query_set` — list of ~10 fixed queries covering collision and non-collision chunks; used by the round-trip parity test.

    3. Add a small helper `assert_db_bytes_unchanged(path, before_hash)` for dry-run/verify-only tests.

    Do NOT import `migration_v16` here (it doesn't exist yet — that's P1). Fixtures build raw SQL directly.
  </action>
  <verify>
    <automated>cd backend && pytest --collect-only tests/ 2>&1 | head -60</automated>
  </verify>
  <done>
    - `pytest --collect-only` discovers all test modules listed in `files_modified`.
    - Fixtures defined and usable in downstream tests.
    - pyproject pytest config present.
  </done>
</task>

<task type="auto">
  <name>Task 2: Author RED test skeletons for P1 (migration core) + P3 (ingest/trickle)</name>
  <files>backend/tests/ingestion/test_migration_v16.py, backend/tests/ingestion/test_migration_v16_invariants.py, backend/tests/ingestion/test_migration_v15_superseded.py, backend/tests/ingestion/test_trickle_lock.py, backend/tests/ingestion/test_pipeline_m2m_insert.py, backend/tests/ingestion/test_chunker.py, backend/tests/storage/test_metadata_m2m.py</files>
  <action>
    Write failing test bodies (not just `pass`) for every test name referenced in P1 and P3:

    **test_migration_v16.py** (DEDUP-01..04): test_creates_m2m_table_and_index, test_drops_file_path_chunk_index_char_offset, test_collision_canonical_is_min_old_id, test_divergence_warn_emitted_above_threshold, test_divergence_warn_not_emitted_below_threshold, test_resume_after_crash_skips_completed_strategy, test_empty_strategy_no_op, test_dry_run_leaves_db_untouched, test_lock_acquired_and_released, test_rebuild_fallback_when_drop_column_fails.

    **test_migration_v16_invariants.py** (DEDUP-10): test_all_chunk_ids_are_64_hex_blake3, test_no_orphan_vec_meta_rows, test_no_orphan_fts_rows, test_unique_file_path_chunk_index_per_strategy, test_row_count_delta_matches_expected_collapse, test_backup_file_exists.

    **test_migration_v15_superseded.py**: test_needs_migration_v15_returns_false, test_run_migration_v15_is_noop, test_v15_module_has_deprecation_banner.

    **test_trickle_lock.py**: test_refuses_while_locked, test_starts_when_lock_cleared, test_starts_when_lock_table_absent.

    **test_pipeline_m2m_insert.py**: test_insert_or_ignore_on_repeat, test_two_files_identical_content_share_chunk, test_repeated_heading_in_same_file_creates_two_m2m_rows, test_vec_meta_not_rewritten_on_reindex.

    **test_chunker.py**: test_chunker_emits_no_char_offset, test_chunker_emits_file_paths_as_single_element_list.

    **test_metadata_m2m.py**: test_insert_chunk_is_idempotent, test_add_file_path_is_idempotent, test_get_file_paths_sorted_lex, test_delete_m2m_for_file_returns_orphans, test_chunk_model_rejects_char_offset.

    Each test imports the target module symbol and will fail with ImportError/AttributeError until the corresponding plan lands. Use `pytest.importorskip` ONLY where a dependency is genuinely optional — here we want RED on missing modules.

    For divergence tests, seed the stub TEI embedder to produce vectors differing by a known cosine distance so the threshold logic is deterministic.

    For `test_rebuild_fallback_when_drop_column_fails`, use `monkeypatch` on `sqlite3.Connection.execute` to inject an OperationalError on the specific DROP COLUMN call and assert the rebuild path was taken.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16.py tests/ingestion/test_migration_v16_invariants.py tests/ingestion/test_migration_v15_superseded.py tests/ingestion/test_trickle_lock.py tests/ingestion/test_pipeline_m2m_insert.py tests/ingestion/test_chunker.py tests/storage/test_metadata_m2m.py --collect-only 2>&1 | tail -20</automated>
  </verify>
  <done>
    - Every test function named in P1/P3 exists and is collected by pytest.
    - Running these modules produces the expected RED (failures/errors on missing implementations), NOT collection errors from syntax issues in the tests themselves.
  </done>
</task>

<task type="auto">
  <name>Task 3: Author RED test skeletons for P2 (ops modes), P4 (purge), P5 (API break) + round-trip parity</name>
  <files>backend/tests/ingestion/test_migration_v16_ops.py, backend/tests/ingestion/test_migration_v16_progress.py, backend/tests/cli/test_migrate_cli.py, backend/tests/ingestion/test_pipeline_purge.py, backend/tests/ingestion/test_pipeline_orphan_sweep.py, backend/tests/api/test_search_result_shape.py, backend/tests/api/test_service_search.py, backend/tests/api/test_search_parity.py, backend/tests/cli/test_search_output.py, backend/tests/cli/test_status_output.py, backend/tests/mcp/test_search_tool.py</files>
  <action>
    Author failing test skeletons for every name referenced by P2, P4, P5.

    **test_migration_v16_ops.py** (DEDUP-06): test_dry_run_writes_nothing, test_verify_only_no_mutation, test_status_reports_no_state_on_fresh_db, test_status_reports_per_strategy_state_after_run.

    **test_migration_v16_progress.py**: test_progress_line_emits_rows_per_sec_and_eta, test_dry_run_prefix_present, test_verify_only_prefix_present.

    **test_migrate_cli.py**: test_cli_run_dry_run_exit_zero_db_unchanged, test_cli_verify_only_exit_zero_db_unchanged, test_cli_dry_run_and_verify_only_mutex_exit_2, test_cli_status_fresh_db, test_cli_status_post_migration, test_cli_run_stale_lock_exit_2_with_hint.

    **test_pipeline_purge.py** (DEDUP-08): test_purge_single_holder_cascades_chunk, test_purge_shared_holder_preserves_chunk, test_purge_mixed_orphans_and_shared, test_purge_is_transactional_on_failure, test_purge_runs_across_all_strategies.

    **test_pipeline_orphan_sweep.py**: test_orphan_sweep_finds_missing_files, test_orphan_sweep_ignores_present_files, test_orphan_sweep_multi_strategy.

    **test_search_result_shape.py** (DEDUP-09): test_file_paths_field_is_list, test_file_paths_sorted_lex, test_single_holder_returns_single_element_list, test_no_file_path_attr, test_graph_direct_hit_also_hydrates.

    **test_service_search.py**: test_search_returns_file_paths_list, test_search_respects_top_k.

    **test_search_parity.py** (DEDUP-10b): test_top_k_parity_for_non_collision_chunks — run DotMDService.search on fixture BEFORE migration (pre-v16 pipeline), record top-K chunk_ids per query; run migration; run search AGAIN; assert that for every query in `query_set`, the top-K chunk_ids for non-collision-group queries are unchanged. For collision-group queries, assert that the set of returned file_paths post-migration is the UNION of file_paths returned pre-migration (collapse semantics).

    **test_search_output.py** (CLI rendering): test_renders_single_holder_no_more_suffix, test_renders_multi_holder_with_plus_n_suffix.

    **test_status_output.py**: test_counts_distinct_paths_from_m2m.

    **test_search_tool.py** (MCP): test_file_paths_is_json_array, test_docstring_mentions_file_paths.

    For the parity test, `query_set` fixture from Task 1 supplies the stable queries. Stub the embedder deterministically (seeded RNG) so top-K is reproducible across runs.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ -x --collect-only 2>&1 | tail -30</automated>
  </verify>
  <done>
    - Every test name in P2/P4/P5 is collected.
    - No collection errors (syntax, import-time failures in conftest, etc.).
    - Running the suite produces RED because implementations don't exist yet — that's the wave-0 baseline.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| tests → index.db fixture | all data is synthetic; no production secrets touched |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-17 | Data integrity | a green test suite that misses the real bug | mitigate | fixtures mirror real CONTEXT.md scenarios (pytest cache dupes, mirrored skills, symlinks, repeated in-file headings); divergence test uses deterministic stub embedder |
| T-16-18 | Denial of service | parity test slow due to reindex | accept | fixture is small (~5 files); deterministic stub embedder is instant |
</threat_model>

<verification>
- `pytest --collect-only` reports ≥ all test names enumerated in Tasks 2+3 with zero collection errors.
- Running `pytest tests/` produces RED (expected) — downstream plans P1–P5 turn it GREEN.
- `pyproject.toml` has a `[tool.pytest.ini_options]` section.
</verification>

<success_criteria>
- Every `<verify><automated>` command in P1–P5 references a test module that now exists.
- Fixtures cover collision, empty, and pre-v16 DB shapes.
- Round-trip parity test is wired to the query_set fixture.
- Suite is RED at end of Wave 0 — downstream plans will turn it GREEN in Wave 2+3.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-06-SUMMARY.md` with: final fixture list, test module map (P# → files), pytest config chosen, and an explicit statement that the suite is RED and this is intentional.
</output>
