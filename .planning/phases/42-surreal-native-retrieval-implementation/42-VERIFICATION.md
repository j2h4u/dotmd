---
phase: 42-surreal-native-retrieval-implementation
verified: 2026-06-14T09:04:46Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: passed
  previous_score: 5/5
  gaps_closed: []
  gaps_remaining: []
  regressions: []
---

# Phase 42: Surreal-native retrieval implementation Verification Report

**Phase Goal:** Implement full-text, vector, graph, and hybrid retrieval on real SurrealDB capabilities instead of Phase 38 proxy logic.
**Verified:** 2026-06-14T09:04:46Z
**Status:** passed
**Re-verification:** Yes — post-review regression check after [42-REVIEW.md](/home/j2h4u/repos/j2h4u/dotmd/.planning/phases/42-surreal-native-retrieval-implementation/42-REVIEW.md:22) reported `status: clean`

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `SURR-SEARCH-01`: Surreal FTS uses real weighted BM25 fields and is scoped by the configured `chunk_strategy` | ✓ VERIFIED | [surreal_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:55) filters `FROM chunks WHERE chunk_strategy = $chunk_strategy` and weights `title`/`tags_text`/`text`; [test_surreal_native_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_fts.py:86) asserts the configured strategy is passed through. Review summary explicitly calls this fix out at [42-REVIEW.md](/home/j2h4u/repos/j2h4u/dotmd/.planning/phases/42-surreal-native-retrieval-implementation/42-REVIEW.md:34). |
| 2 | `SURR-SEARCH-02`: vector retrieval scopes active chunks by `chunk_strategy`, scopes precondition/search by selected `embedding_model`, and does not fail closed for valid multi-model strategy slices | ✓ VERIFIED | [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:22) derives active chunk IDs from `chunks` with `chunk_strategy = $chunk_strategy`; [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:27) scopes preconditions to `embedding_model = $embedding_model`; [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:204) scopes the HNSW search to the same selected model. [test_surreal_native_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_vector.py:138) verifies strategy scoping, and [test_surreal_native_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_vector.py:201) proves a valid selected-model slice still searches successfully. |
| 3 | `SURR-SEARCH-03`: graph retrieval aggregates by `source_id` before `LIMIT` and uses indexed `target_id`/`rel_type` filtering instead of Python scans | ✓ VERIFIED | [surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:52) issues `SELECT source_id, math::sum(weight) ... GROUP BY source_id ... LIMIT $limit`; [test_surreal_native_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_graph.py:127) asserts the query shape, and [test_surreal_native_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_graph.py:228) proves limit is applied after chunk aggregation, not on raw relation rows. |
| 4 | Capability probing requires explicit mutation opt-in and remains a non-runtime artifact in Phase 42 | ✓ VERIFIED | [surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:881) rejects probe execution unless `allow_target_mutation=True`; [test_surreal_schema_definition.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/storage/test_surreal_schema_definition.py:446) covers the guard directly. [test_surreal_native_hybrid.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_hybrid.py:87) verifies `SurrealRetrievalCapabilityReport` is still absent from runtime entrypoints. |
| 5 | Phase 42 still does not introduce production cutover, shadow-run execution, runtime fallback/backend switching, or legacy deletion | ✓ VERIFIED | [service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:260) still initializes the default runtime engines (`SemanticSearchEngine`, pipeline keyword engine, `GraphDirectEngine`) at service startup; [surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18) only builds explicit opt-in overrides; [test_surreal_native_hybrid.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_hybrid.py:77) checks no built-in hybrid helper or runtime cutover wiring was added. Repo-wide grep found no Phase 42 runtime consumer for the capability report and no new fallback/cutover wiring in the implementation files under review. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/src/dotmd/search/surreal_fts.py` | Weighted Surreal BM25 engine with strategy scoping | ✓ VERIFIED | Substantive query implementation at [surreal_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:55); wired by direct test coverage and hybrid override builder. |
| `backend/src/dotmd/search/surreal_vector.py` | HNSW engine with strategy/model scoping and precondition checks | ✓ VERIFIED | Active chunk discovery, selected-model preconditions, and HNSW query path are implemented at [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:123), [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:138), and [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:204). |
| `backend/src/dotmd/search/surreal_graph.py` | Relation-backed graph direct engine with aggregation before limit | ✓ VERIFIED | Query and normalization logic are substantive at [surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:52) and [surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:122). |
| `backend/src/dotmd/storage/surreal_schema.py` | Capability probe and retrieval contract guardrails | ✓ VERIFIED | Typed capability report plus explicit mutation opt-in guard at [surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:221) and [surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:881). |
| `backend/src/dotmd/search/surreal_native.py` | Explicit Surreal override builder only | ✓ VERIFIED | Override builder exists and stays outside startup/runtime defaults at [surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18). |
| `backend/src/dotmd/api/service.py` | Existing fusion seam accepts optional overrides without changing defaults | ✓ VERIFIED | `_collect_candidate_pool()` accepts overrides while default startup engines remain unchanged at [service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1339). |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `surreal_fts.py` | `chunks` retrieval schema | `chunk_strategy` + weighted `title` / `tags_text` / `text` predicates | ✓ WIRED | Query statement in [surreal_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:55) matches the retrieval-field contract and is asserted in [test_surreal_native_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_fts.py:53). |
| `surreal_vector.py` | `chunks` and `embeddings` retrieval slices | active chunk set comes from strategy-filtered chunks, then precondition/search narrow to selected model | ✓ WIRED | [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:123), [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:138), and [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:204) form the full slice; tests assert the variables at [test_surreal_native_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_vector.py:129). |
| `surreal_graph.py` | `relations` retrieval path | indexed `target_id` / `rel_type` lookup aggregates by `source_id` before limiting | ✓ WIRED | [surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:52) uses `GROUP BY source_id` before `LIMIT`; [test_surreal_native_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_graph.py:151) and [test_surreal_native_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_graph.py:228) cover both query shape and post-aggregation limit behavior. |
| `surreal_schema.py` | capability probe execution | mutation guard sits ahead of any probe statement execution | ✓ WIRED | [surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:888) raises before schema/probe work unless explicitly opted in; [test_surreal_schema_definition.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/storage/test_surreal_schema_definition.py:446) verifies the guard. |
| `surreal_native.py` | `api/service.py` | explicit override builder feeds existing candidate-pool seam only | ✓ WIRED | [surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:27) builds `semantic`/`keyword`/`graph_direct` overrides; [service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1350) consumes them while leaving defaults intact. |
| `api/service.py` | `search/fusion.py` | existing Python RRF remains the hybrid fusion implementation | ✓ WIRED | [service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1398) still funnels engine result sets through `fuse_results()`, and [test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:1363) verifies preserved engine attribution. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `surreal_fts.py` | `rows -> (chunk_id, score)` | `chunks` rows filtered by `chunk_strategy` and BM25 predicates | Yes — embedded/runtime tests and scoped suite passed | ✓ FLOWING |
| `surreal_vector.py` | `active_chunk_ids`, `precondition_rows`, `rows -> (chunk_id, score)` | strategy-filtered `chunks` slice, then selected-model `embeddings` slice | Yes — selected-model slice and embedded HNSW tests passed, including valid multi-model slice coverage | ✓ FLOWING |
| `surreal_graph.py` | `rows -> chunk_scores` | aggregated `relations` rows grouped by `source_id` | Yes — graph tests prove weighted aggregation and limit-after-grouping behavior | ✓ FLOWING |
| `api/service.py` | `engine_results -> fused -> candidate attribution` | explicit override engine results passed into existing Python fusion | Yes — attribution test at [test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:1363) proves overlap metadata survives candidate hydration | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Full backend verification gate | `cd backend && just verify` | `661 passed, 36 deselected, 1 warning` | ✓ PASS |
| Scoped post-review Phase 42 suite | `cd backend && uv run pytest tests/search/test_surreal_native_vector.py tests/storage/test_surreal_schema_definition.py tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_graph.py tests/search/test_surreal_native_hybrid.py -q` | `45 passed in 1.50s` | ✓ PASS |
| Direct review-fix spot-checks | `cd backend && uv run pytest tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_vector.py tests/search/test_surreal_native_graph.py tests/storage/test_surreal_schema_definition.py -q -k 'test_search_filters_to_configured_chunk_strategy or test_search_allows_other_models_in_active_strategy_when_selected_model_is_valid or test_search_limits_after_chunk_aggregation_not_raw_relation_rows or test_probe_surreal_native_retrieval_capabilities_requires_explicit_mutation_opt_in'` | `4 passed, 37 deselected in 0.79s` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| None declared/found | `find scripts -path '*/tests/probe-*.sh' -type f` plus phase grep | No phase-declared or conventional probe scripts found | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `SURR-SEARCH-01` | 42-01, 42-02 | SurrealDB full-text search uses real BM25/full-text indexes with weighted title, tags, and body/text contributions | ✓ SATISFIED | Weighted BM25 query over `title` / `tags_text` / `text` plus `chunk_strategy` filtering at [surreal_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:55); scoped FTS test at [test_surreal_native_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_fts.py:86). |
| `SURR-SEARCH-02` | 42-01, 42-02 | SurrealDB vector search uses HNSW/DISKANN strategy with implementation guardrails | ✓ SATISFIED | Phase 42 implements the HNSW path and scopes retrieval correctly by strategy/model at [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:123), [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:138), and [surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:204); valid multi-model slice behavior is covered at [test_surreal_native_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_vector.py:201). |
| `SURR-SEARCH-03` | 42-01, 42-03 | Graph/entity retrieval runs through Surreal relation records and preserves relation metadata | ✓ SATISFIED | Relation query aggregates by `source_id` before `LIMIT` in [surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:52), with explicit limit-after-aggregation test coverage at [test_surreal_native_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_graph.py:228). |
| `SURR-SEARCH-04` | 42-04 | Hybrid fusion runs over Surreal result sets and preserves engine attribution | ✓ SATISFIED | Override builder at [surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18), fusion seam at [service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1339), and attribution verification at [test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:1363). |

No orphaned Phase 42 requirements were found in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | None in reviewed Phase 42 implementation/test files | ℹ️ Info | No `TBD` / `FIXME` / `XXX` markers, placeholder code, or console-log-only implementations were found. |

### Human Verification Required

None.

### Gaps Summary

No blocker gaps found. The post-review fixes are present in code, covered by focused tests, the latest code review is clean, and fresh execution evidence passed both the scoped Phase 42 suite (`45 passed`) and the full backend verification gate (`661 passed, 36 deselected, 1 warning`). Phase 42 still achieves its implementation-only goal without leaking Phase 43/44/45 runtime cutover scope.

---

_Verified: 2026-06-14T09:04:46Z_
_Verifier: the agent (gsd-verifier)_
