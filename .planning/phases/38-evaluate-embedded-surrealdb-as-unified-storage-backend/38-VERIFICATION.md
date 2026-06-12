---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
verified: 2026-06-12T16:58:05Z
status: passed
score: 30/30 must-haves verified
overrides_applied: 0
---

# Phase 38: Embedded SurrealDB storage spike Verification Report

**Phase Goal:** Decide whether dotMD should replace separate SQLite/sqlite-vec/FTS5 and FalkorDB storage with one embedded SurrealDB-backed storage layer while maximizing migration of existing data and avoiding default rechunking/reembedding/re-extraction.
**Verified:** 2026-06-12T16:58:05Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | A minimal SurrealDB prototype models documents, source units, chunks, embeddings, entities, relations, feedback, and cursor/checkpoint state. | ✓ VERIFIED | `backend/src/dotmd/storage/surreal.py` defines schema tables for all required domains and adapter stores; `test_define_dotmd_surreal_schema_declares_required_record_shapes_and_thin_scope` and `test_run_surreal_import_apply_preserves_ids_vectors_feedback_and_graph_properties` cover the shape and imported rows. |
| 2 | The prototype proves or rejects dotMD's required retrieval paths: full-text, vector, graph-direct entity retrieval, and hybrid/RRF fusion. | ✓ VERIFIED | `backend/src/dotmd/search/surreal_parity.py` implements per-engine comparators plus a gating report; `38-03-RETRIEVAL-PARITY.md` records PASS/FAIL outcomes, including `recommendation_gate: fail`. |
| 3 | The spike measures migration feasibility from current production data instead of defaulting to CPU-heavy rechunking/reembedding/re-extraction. | ✓ VERIFIED | `backend/src/dotmd/storage/surreal_inventory.py` inventories copied SQLite/Falkor/feedback state; `backend/src/dotmd/ingestion/migrate_surreal.py` loads stored rows directly; `test_run_surreal_import_never_reaches_embedding_or_extraction_recomputation` guards against recomputation. |
| 4 | The result is an explicit migrate/defer/reject recommendation with operational notes for backup/restore, locking/concurrency, and rollback. | ✓ VERIFIED | `backend/src/dotmd/storage/surreal_ops.py` builds the final decision from gates; `38-RECOMMENDATION.md` is explicit `reject`; `38-04-OPERATIONS.md` covers backup/restore, rollback, and writer coordination. |
| 5 | D-01: production `index.db`, `feedback.db`, and FalkorDB are inspected through copied snapshots or read-only exporters. | ✓ VERIFIED | `copy_sqlite_snapshot()` in `backend/src/dotmd/storage/surreal_inventory.py` uses the SQLite backup API; `collect_falkor_inventory()` and `collect_feedback_inventory()` use exporter/provider abstractions; `38-01-INVENTORY.md` records copied snapshot paths and read-only graph/feedback discipline. |
| 6 | Current chunks, provenance, bindings, fingerprints, source state, embeddings, graph data, and feedback are counted before Surreal import work starts. | ✓ VERIFIED | `collect_sqlite_inventory()` reports counts for chunk/vector/fingerprint/source-state surfaces; `38-01-INVENTORY.md` records the copied-snapshot counts and graph/feedback totals before import proof. |
| 7 | The migration map states transform-only handling for each current data category and flags unsafe categories explicitly. | ✓ VERIFIED | `build_surreal_migration_map()` classifies categories as `transformable`, `unsafe`, or `unsupported`; `38-01-MIGRATION-MAP.md` covers every D-01 category plus explicitly flagged non-D-01 surfaces. |
| 8 | SQLite snapshots are consistent when WAL/SHM sidecars exist. | ✓ VERIFIED | `copy_sqlite_snapshot()` uses `sqlite3.Connection.backup()` and records sidecars in the manifest; `test_copy_sqlite_snapshot_handles_wal_state_without_silent_row_loss` proves WAL-contained rows survive the snapshot. |
| 9 | FalkorDB graph inventory preserves relation labels, weights, metadata keys, and edge property value types. | ✓ VERIFIED | `collect_falkor_inventory()` materializes `GraphRelationSummary`; `test_collect_falkor_inventory_preserves_relation_labels_weights_keys_and_types` checks labels, weights, keys, and typed properties; `38-01-INVENTORY.md` records sampled property shapes. |
| 10 | Plan 38-05 embedded atomicity and writer-safety gate passed before Surreal schema/import apply work proceeds toward a migrate-ready result. | ✓ VERIFIED | `run_surreal_import()` blocks apply mode unless `assert_embedded_safety_gate_passed()` accepts the gate report; `test_run_surreal_import_apply_requires_embedded_safety_gate` verifies `gate_blocked` behavior. |
| 11 | Transform import preserves existing chunk IDs, refs, fingerprints, source state, vector values, graph identities, and feedback rows without CPU-heavy recomputation. | ✓ VERIFIED | `load_sqlite_rows_for_surreal()` and `run_surreal_import()` preserve caller-owned IDs and vector payloads; `test_run_surreal_import_apply_preserves_ids_vectors_feedback_and_graph_properties` verifies chunk IDs, refs, vectors, graph properties, feedback IDs, checkpoints, and cursors. |
| 12 | The Surreal storage module is a thin prototype adapter surface only and is not wired into DotMDService, IndexingPipeline, or production startup as the default backend. | ✓ VERIFIED | `backend/src/dotmd/storage/surreal.py` documents the thin-prototype boundary and unsupported production behaviors; grep over `backend/src/dotmd/api`, `backend/src/dotmd/cli.py`, and `backend/src/dotmd/mcp_server.py` found no production wiring to Surreal adapters. |
| 13 | Surreal record identifiers are centrally encoded/decoded so special characters in chunk IDs, entity names, file paths, and refs cannot alter SurrealQL structure. | ✓ VERIFIED | `SurrealRecordIdCodec`, `encode_surreal_record_id()`, and `decode_surreal_record_id()` centralize encoding; `test_surreal_record_id_codec_round_trips_special_characters_without_leaking_raw_values` covers colons, slashes, braces, quotes, spaces, and Unicode. |
| 14 | Surreal FTS, vector, graph-direct, and hybrid/RRF retrieval are compared against current dotMD behavior. | ✓ VERIFIED | `SurrealRetrievalParityHarness` dispatches per-engine comparisons; `tests/search/test_surreal_retrieval_parity.py` covers FTS, vector, graph-direct, and hybrid comparators. |
| 15 | Parity criteria are explicit and failing criteria block a migrate recommendation. | ✓ VERIFIED | `RetrievalParityReport.passed` and `.recommendation_gate` fail on blocking parity or scale failures; `test_fts_weighting_mismatch_is_classified_as_defer_and_blocks_report` and `test_regression_result_causes_failing_report_not_warning` exercise this gate. |
| 16 | Plan 38-05 embedded safety evidence and Plan 38-02 import proof are consumed before parity is treated as migration evidence. | ✓ VERIFIED | The Phase 38 evidence chain is explicit in `38-04-OPERATIONS.md` and `run_surreal_full_pipeline_smoke()` covers `inventory`, `embedded safety gate`, `transform import`, `retrieval parity`, `operations`, and `recommendation`. |
| 17 | Retrieval parity tests use imported or fixture embeddings and graph rows, not recomputed source markdown state. | ✓ VERIFIED | `38-03-RETRIEVAL-PARITY.md` states fixed query embeddings and fixture-backed graph evidence; `test_run_surreal_import_never_reaches_embedding_or_extraction_recomputation` enforces the transform-only boundary. |
| 18 | FTS weighting mismatch has an explicit failure category and stop condition. | ✓ VERIFIED | `classify_fts_parity_failure()` returns `defer: FTS weighting`; the paired test verifies the category and failing recommendation gate. |
| 19 | RRF and hybrid parity are deterministic under ties via a stable tie-breaker. | ✓ VERIFIED | `_stable_sort_pairs()` sorts by `(-score, chunk_id)` and `compare_hybrid_results()` trims through that helper; `test_hybrid_ties_are_stabilized_by_chunk_id_and_repeatable` verifies determinism. |
| 20 | Representative copied-snapshot metrics are recorded before any migrate recommendation can pass. | ✓ VERIFIED | `evaluate_surreal_scale_gate()` requires record counts, HNSW timing where available, SurrealKV file size, latencies, and representative corpus flag; `test_scale_gate_fails_when_required_metrics_are_missing` verifies blocking behavior; `38-03-RETRIEVAL-PARITY.md` records the representative metrics. |
| 21 | Backup, restore, rollback, and partial-import recovery are tested on copied stores and consume the embedded safety evidence before recommendation. | ✓ VERIFIED | `rehearse_surreal_backup_restore()` and `rehearse_current_stack_rollback()` operate on caller-provided copied paths; `run_surreal_import()` clears phase tables on apply failure; `38-04-OPERATIONS.md` documents the consumed inputs and failure semantics. |
| 22 | A migrate recommendation is impossible unless transform coverage, retrieval parity, and operations safety all pass. | ✓ VERIFIED | `build_storage_recommendation()` marks retrieval parity and embedded safety as hard-reject gates and folds all remaining gate failures into the final decision. |
| 23 | A migrate recommendation is impossible without recorded scale metrics. | ✓ VERIFIED | `evaluate_surreal_scale_gate()` fails when counts, HNSW time, file size, or latency evidence is missing; the scale-gate test verifies the failure category. |
| 24 | Recommendation output includes an explicit failure category taxonomy. | ✓ VERIFIED | `SurrealDecisionCategory` enumerates transform, FTS, vector, graph, hybrid/RRF, atomicity, backup, rollback, scale, and writer categories; `38-RECOMMENDATION.md` uses `hybrid/RRF gap`. |
| 25 | Rollback rehearsal proves return to the current SQLite/sqlite-vec/FTS5 plus FalkorDB stack on copied originals. | ✓ VERIFIED | `rehearse_current_stack_rollback()` restores copied SQLite and Falkor exports and smoke-checks both; `test_current_stack_rollback_restores_copied_sqlite_and_falkor_originals` passes. |
| 26 | A same-corpus integration smoke covers inventory, embedded safety gate, transform import, retrieval parity, operations evidence, and recommendation assembly. | ✓ VERIFIED | `run_surreal_full_pipeline_smoke()` enumerates the full six-stage chain; `test_full_pipeline_smoke_requires_all_gates` verifies coverage and migrate-only success semantics. |
| 27 | Surreal schema/import/parity work cannot become migrate-ready until embedded atomicity and single-writer safety are proven or blocking. | ✓ VERIFIED | `probe_embedded_transaction_atomicity()` and `probe_embedded_writer_safety()` produce go/no-go evidence; `write_embedded_safety_gate_report()` blocks downstream work when only control results pass. |
| 28 | The `surrealdb` package checkpoint is completed before the dependency is introduced. | ✓ VERIFIED | `38-05-SURREAL-PACKAGE-VERIFY.md` records the approval checkpoint; commit `6f622b4` adds the verification artifact together with `backend/pyproject.toml` and `backend/uv.lock`, showing the dependency was introduced under the documented checkpoint. |
| 29 | Embedded commit/rollback and writer-guard behavior are tested on copied/local Surreal stores with no live production mutation. | ✓ VERIFIED | `probe_embedded_transaction_atomicity()` targets local `surrealkv://` paths only; `test_probe_embedded_transaction_atomicity_commits_and_rolls_back` and `test_writer_guard_blocks_second_writer_and_exposes_owner_metadata` validate the behavior. |
| 30 | Writer-guard recovery is tested for stale owners through TTL and explicit force-release. | ✓ VERIFIED | `release_stale_surreal_writer_guard()` and `force_release_surreal_writer_guard()` implement the recovery paths; `test_release_stale_writer_guard_requires_ttl_expiry` and `test_force_release_requires_matching_target_path_and_records_previous_owner` pass. |

**Score:** 30/30 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/src/dotmd/storage/surreal_inventory.py` | Read-only inventory + migration-map helpers | ✓ VERIFIED | Present, substantive, and covered by storage contract tests. |
| `backend/src/dotmd/storage/surreal.py` | Thin Surreal schema + store adapters | ✓ VERIFIED | Present, substantive, and used by the import proof. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | Transform-only import proof | ✓ VERIFIED | Present, substantive, and wired to Surreal adapters and gate checks. |
| `backend/src/dotmd/search/surreal_parity.py` | Retrieval parity harness | ✓ VERIFIED | Present, substantive, and used by parity tests/reports. |
| `backend/src/dotmd/storage/surreal_ops.py` | Safety, rollback, backup/restore, and recommendation helpers | ✓ VERIFIED | Present, substantive, and covered by operations tests. |
| `backend/tests/storage/test_surreal_storage_contract.py` | Inventory/schema contract coverage | ✓ VERIFIED | Covers snapshots, inventories, migration map, codec, schema, and protocol shape. |
| `backend/tests/ingestion/test_surreal_transform_only_migration.py` | Transform-only import proof coverage | ✓ VERIFIED | Covers dry-run, apply, gate blocking, truncation failure, no recomputation, and rollback on apply error. |
| `backend/tests/search/test_surreal_retrieval_parity.py` | Parity + scale gate coverage | ✓ VERIFIED | Covers pass/fail cases for FTS, vector, graph-direct, hybrid, tie-breaks, and scale gate. |
| `backend/tests/storage/test_surreal_ops_safety.py` | Embedded safety + recommendation coverage | ✓ VERIFIED | Covers atomicity, writer guard, TTL/force-release, backup/restore, rollback, decision building, and full-pipeline smoke. |
| `38-01-INVENTORY.md`, `38-01-MIGRATION-MAP.md`, `38-02-IMPORT-PROOF.md`, `38-03-RETRIEVAL-PARITY.md`, `38-04-OPERATIONS.md`, `38-05-EMBEDDED-SAFETY-GATE.md`, `38-05-SURREAL-PACKAGE-VERIFY.md`, `38-RECOMMENDATION.md` | Evidence chain and final decision | ✓ VERIFIED | All required evidence artifacts exist and are referenced by the code/test chain. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| Plan 38-01 artifacts | Current metadata/sqlite-vec/Falkor surfaces | inventory patterns | ✓ VERIFIED | `gsd-tools verify.key-links` reported 3/3 links verified. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `backend/src/dotmd/storage/surreal.py` | transform importer writes through Surreal stores | ✓ VERIFIED | `gsd-tools verify.key-links` reported 4/4 links verified for Plan 38-02. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `38-05-EMBEDDED-SAFETY-GATE.md` | apply mode requires PASS gate | ✓ VERIFIED | `run_surreal_import()` blocks without a passing gate report. |
| `backend/src/dotmd/search/surreal_parity.py` | current FTS/vector/graph/fusion semantics | comparator baselines | ✓ VERIFIED | `gsd-tools verify.key-links` reported 4/4 links verified for Plan 38-03. |
| `backend/src/dotmd/storage/surreal_ops.py` | import proof, safety gate, parity report | recommendation consumes upstream evidence | ✓ VERIFIED | `gsd-tools verify.key-links` reported 4/4 links verified for Plan 38-04. |
| `backend/src/dotmd/storage/surreal_ops.py` | `backend/pyproject.toml` and `38-05-EMBEDDED-SAFETY-GATE.md` | package gate + explicit safety report | ✓ VERIFIED | `gsd-tools verify.key-links` reported 3/3 links verified for Plan 38-05. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/storage/surreal_inventory.py` | `table_counts`, `relation_summaries`, feedback counts | read-only SQLite queries + exporter/provider surfaces | Yes | ✓ FLOWING |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | `sqlite_rows`, `graph_rows`, `feedback_rows` | copied SQLite snapshot + graph exporter + feedback provider | Yes | ✓ FLOWING |
| `backend/src/dotmd/search/surreal_parity.py` | `RetrievalParityResult` / `RetrievalParityReport` | current-stack and Surreal callables + scale metrics | Yes | ✓ FLOWING |
| `backend/src/dotmd/storage/surreal_ops.py` | `SurrealStorageRecommendation` | safety/parity/scale/rollback gate inputs | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| WAL-safe snapshot keeps uncheckpointed rows and does not silently drop sidecar state | `cd backend && uv run pytest -q tests/storage/test_surreal_storage_contract.py::test_copy_sqlite_snapshot_handles_wal_state_without_silent_row_loss ...` | part of combined targeted run: `6 passed in 0.71s` | ✓ PASS |
| Apply-mode import preserves special IDs, vectors, feedback, graph properties, and chunk/file bindings | `cd backend && uv run pytest -q tests/ingestion/test_surreal_transform_only_migration.py::test_run_surreal_import_apply_preserves_ids_vectors_feedback_and_graph_properties ...` | part of combined targeted run: `6 passed in 0.71s` | ✓ PASS |
| Retrieval parity logic blocks on FTS weighting mismatch and maintains deterministic hybrid attribution when aligned | `cd backend && uv run pytest -q tests/search/test_surreal_retrieval_parity.py::TestParityComparators::test_fts_weighting_mismatch_is_classified_as_defer_and_blocks_report tests/search/test_surreal_retrieval_parity.py::TestParityComparators::test_hybrid_parity_preserves_top_hit_and_engine_attribution ...` | part of combined targeted run: `6 passed in 0.71s` | ✓ PASS |
| Final recommendation rejects parity failure and rollback rehearsal restores copied current-stack originals | `cd backend && uv run pytest -q tests/storage/test_surreal_ops_safety.py::test_recommendation_blocks_migrate_on_parity_and_scale_failures tests/storage/test_surreal_ops_safety.py::test_current_stack_rollback_restores_copied_sqlite_and_falkor_originals ...` | part of combined targeted run: `6 passed in 0.71s` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| none discovered | `find scripts -path '*/tests/probe-*.sh' -type f` and phase grep | no conventional or phase-declared probes found | SKIPPED |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `STOR-01` | `38-01`, `38-02` | Model current persistent data in embedded SurrealDB. | ✓ SATISFIED | Schema tables and adapters cover documents/source units/chunks/embeddings/entities/relations/feedback/cursors/checkpoints; import apply test verifies stored rows. |
| `STOR-02` | `38-03` | Execute required retrieval paths. | ✓ SATISFIED | Parity harness implements FTS, vector, graph-direct, and hybrid/RRF comparison paths and records both passing and failing outcomes. |
| `STOR-03` | `38-01`, `38-02` | Measure migration without CPU-heavy recomputation. | ✓ SATISFIED | Inventory + transform-only import loaders use copied stored data; no recomputation test passes. |
| `STOR-04` | `38-05`, `38-04` | Produce migrate/defer/reject recommendation with operational notes. | ✓ SATISFIED | Safety gate, backup/restore, rollback, writer coordination, and recommendation builder produce an explicit `reject` recommendation with failure category. |

Orphaned requirements: none. All Phase 38 requirement IDs in `REQUIREMENTS.md` are claimed by at least one plan.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | No `TBD`, `FIXME`, `XXX`, unresolved placeholder text, or stub-only phase code paths found in the phase-modified source/test files. | none | No blocker debt markers detected. |

### Human Verification Required

None.

### Gaps Summary

None. The phase goal is achieved because the codebase contains:

- a substantive Surreal prototype schema and adapter surface,
- tested transform-only inventory/import evidence that preserves stored data without default recomputation,
- a retrieval-parity harness that honestly fails the migrate gate for FTS weighting and hybrid/RRF mismatch,
- and a recommendation path that converts those gates into an explicit `reject` decision with operational notes.

---

_Verified: 2026-06-12T16:58:05Z_  
_Verifier: the agent (gsd-verifier)_
