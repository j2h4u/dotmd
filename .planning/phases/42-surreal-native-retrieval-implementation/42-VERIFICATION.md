---
phase: 42-surreal-native-retrieval-implementation
verified: 2026-06-14T08:28:32Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 42: Surreal-native retrieval implementation Verification Report

**Phase Goal:** Implement full-text, vector, graph, and hybrid retrieval on real SurrealDB capabilities instead of Phase 38 proxy logic.
**Verified:** 2026-06-14T08:28:32Z
**Status:** passed
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | `SURR-SEARCH-01`: real Surreal BM25/full-text path with weighted title/tags/text fields exists | ✓ VERIFIED | [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:309) defines analyzer plus separate BM25 indexes for `title`, `tags_text`, and `text`; [backend/src/dotmd/search/surreal_fts.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:53) queries those three fields with weighted `search::score(1..3)` composition; [backend/src/dotmd/ingestion/migrate_surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:455) materializes `title` and `tags_text` into chunk payloads. Embedded BM25 spot-check passed. |
| 2 | `SURR-SEARCH-02`: Surreal HNSW vector path enforces single-model/dimension and bounded `top_k`/`hnsw_ef` preconditions | ✓ VERIFIED | [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:341) validates `top_k`, `hnsw_ef`, single active `embedding_model`, and uniform `embedding_dimension`; [backend/src/dotmd/search/surreal_vector.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:105) applies those bounds before query execution and uses native HNSW lookup at [line 170](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:170). Embedded HNSW spot-check passed. |
| 3 | `SURR-SEARCH-03`: graph/entity retrieval runs through Surreal relation records with `target_id` and `rel_type` filtering, not Python full relation scans | ✓ VERIFIED | [backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:333) includes `relations_target_id_idx`; [backend/src/dotmd/search/surreal_graph.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:51) issues a bounded `FROM relations` query with `target_id IN $entity_names` and `rel_type IN $allowed_rel_types`; no `scan_table("relations")` call exists in the engine. Embedded relation-query spot-check passed. |
| 4 | `SURR-SEARCH-04`: hybrid fusion runs over Surreal result sets through explicit engine overrides and preserves engine attribution | ✓ VERIFIED | [backend/src/dotmd/search/surreal_native.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_native.py:18) builds explicit Surreal `semantic`/`keyword`/`graph_direct` overrides; [backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1339) accepts `engine_overrides`, feeds their result sets into `fuse_results`, and keeps graph enrichment separate; [backend/tests/api/test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:1363) verifies preserved `matched_engines` and `engine_scores`. |
| 5 | Phase 42 did not add production cutover, shadow-run execution, runtime fallback backend, capability-probe startup consumption, or legacy stack deletion | ✓ VERIFIED | [backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:267) still initializes legacy default engines (`SemanticSearchEngine`, pipeline keyword engine, `GraphDirectEngine`) at service startup; [backend/tests/search/test_surreal_native_hybrid.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_native_hybrid.py:75) asserts no `search::rrf`, no built-in hybrid helper use, and no `SurrealRetrievalCapabilityReport` wiring into runtime entrypoints. Global grep found no Phase 42 production cutover/fallback wiring additions. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/src/dotmd/storage/surreal_schema.py` | Retrieval index plan, HNSW contract, relation index, capability probe | ✓ VERIFIED | Substantive implementation at lines 309-338, 341-367, and 881-965; used by tests and by Surreal-native engines. |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | Transform-only lexical field materialization | ✓ VERIFIED | Chunk payload builder at lines 439-480 fills `title` and `tags_text` from copied SQLite `source_documents` rows. |
| `backend/tests/fixtures/surreal_native.py` | Shared isolated embedded-Surreal fixture | ✓ VERIFIED | Exports `isolated_surreal_connection()` and `apply_surreal_native_retrieval_schema()`; imported by embedded FTS/vector/graph tests. |
| `backend/src/dotmd/search/surreal_fts.py` | Weighted Surreal BM25 engine | ✓ VERIFIED | Uses fixed SurrealQL over `title`, `tags_text`, `text`; fail-soft on operational errors. |
| `backend/src/dotmd/search/surreal_vector.py` | HNSW Surreal vector engine | ✓ VERIFIED | Preserves semantic query normalization, checks bounds/preconditions, queries HNSW directly. |
| `backend/src/dotmd/search/surreal_graph.py` | Relation-backed graph direct engine | ✓ VERIFIED | Loads entity catalog once; hot path uses bounded relation query and normalized weighted ranking. |
| `backend/src/dotmd/search/surreal_native.py` | Explicit Surreal override builder | ✓ VERIFIED | Builds `semantic`, `keyword`, and `graph_direct` overrides without changing runtime defaults. |
| `backend/src/dotmd/api/service.py` | Candidate-pool seam for explicit engine overrides | ✓ VERIFIED | `_collect_candidate_pool()` accepts overrides and still uses existing `fuse_results()`/candidate attribution path. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `migrate_surreal.py` | `surreal_schema.py` | lexical chunk payload fields match retrieval schema fields | ✓ WIRED | Manual verification: payload builder writes `title`/`tags_text` at [migrate_surreal.py:463](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migrate_surreal.py:463), and schema declares those fields at [surreal_schema.py:425](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:425). `verify.key-links` false-negative was a multiline regex miss, not missing wiring. |
| `surreal_schema.py` | `surreal_schema.py` | capability probe validates same analyzer/HNSW/relation statements exposed by schema helpers | ✓ WIRED | `probe_surreal_native_retrieval_capabilities()` consumes `build_surreal_native_retrieval_index_plan()` statements directly at lines 888-935. |
| `surreal_fts.py` | `surreal_schema.py` | FTS engine uses the Phase 42 title/tags/text field contract | ✓ WIRED | FTS statement references `title`, `tags_text`, and `text` at [surreal_fts.py:61](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_fts.py:61); schema/index plan defines the same fields and BM25 indexes at [surreal_schema.py:326](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:326). `verify.key-links` false-negative was another multiline regex miss. |
| `surreal_vector.py` | `semantic.py` | preserves TEI/local query encoding behavior before Surreal lookup | ✓ WIRED | `_normalize_query_text()` at [surreal_vector.py:163](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_vector.py:163) matches the existing semantic-engine normalization contract. |
| `surreal_graph.py` | `surreal_schema.py` | graph engine queries relation fields/index path added in 42-01 | ✓ WIRED | Query selects `source_id`, `target_id`, `rel_type`, `weight`, `properties`, `metadata` and filters `target_id IN $entity_names` at [surreal_graph.py:52](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_graph.py:52). |
| `surreal_native.py` | `surreal_fts.py` / `surreal_vector.py` / `surreal_graph.py` | explicit Surreal override builder | ✓ WIRED | Builder instantiates all three engines at lines 27-40. |
| `api/service.py` | `search/fusion.py` | existing Python RRF stays the hybrid fusion implementation | ✓ WIRED | `_collect_candidate_pool()` still calls `fuse_results()` at [service.py:1407](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1407). |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `surreal_fts.py` | `rows -> (chunk_id, score)` | Surreal `chunks` table queried via BM25 predicates on `title`, `tags_text`, `text` | Yes — embedded test inserts real `chunks` rows and search returns hits | ✓ FLOWING |
| `surreal_vector.py` | `rows -> (chunk_id, score)` | Surreal `embeddings` table queried with HNSW operator and cosine projection | Yes — embedded test inserts real embedding rows and returns nearest-neighbor hits | ✓ FLOWING |
| `surreal_graph.py` | `rows -> chunk_scores` | Surreal `relations` table filtered by `target_id`/`rel_type` | Yes — embedded test inserts real `RELATE` rows and returns only allowed matches | ✓ FLOWING |
| `api/service.py` | `engine_results -> fused -> candidate attribution` | Explicit override engine result sets passed into `fuse_results()` and candidate hydration | Yes — service tests prove override outputs become fused candidates with preserved `matched_engines`/`engine_scores` | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Embedded BM25 retrieval returns real Surreal hits | `cd backend && uv run pytest tests/search/test_surreal_native_fts.py -q -k embedded_surreal_fts_returns_weighted_chunk_hits` | `1 passed, 3 deselected in 0.80s` | ✓ PASS |
| Embedded HNSW retrieval returns nearest neighbor without scan fallback | `cd backend && uv run pytest tests/search/test_surreal_native_vector.py -q -k embedded_surreal_hnsw_returns_nearest_neighbor_without_scan_table` | `1 passed, 14 deselected in 0.82s` | ✓ PASS |
| Embedded relation-backed graph retrieval returns only allowed matches | `cd backend && uv run pytest tests/search/test_surreal_native_graph.py -q -k embedded_surreal_graph_returns_only_allowed_relation_matches` | `1 passed, 7 deselected in 0.87s` | ✓ PASS |
| Hybrid override seam and capability-probe non-consumption hold | `cd backend && uv run pytest tests/search/test_surreal_native_hybrid.py tests/api/test_service_search.py -q -k 'phase42_keeps_capability_probe_out_of_runtime_entrypoints or collect_candidate_pool_uses_engine_overrides_and_existing_fusion'` | `2 passed` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| None declared/found | `find scripts -path '*/tests/probe-*.sh' -type f` plus phase grep | No phase-declared or conventional probe scripts found | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `SURR-SEARCH-01` | 42-01, 42-02 | SurrealDB full-text search uses real BM25/full-text indexes with weighted title, tags, and body/text contributions | ✓ SATISFIED | Schema/index plan at `surreal_schema.py:309-338`, lexical materialization at `migrate_surreal.py:455-480`, weighted engine query at `surreal_fts.py:53-77`, embedded BM25 spot-check passed. |
| `SURR-SEARCH-02` | 42-01, 42-02 | SurrealDB vector search uses HNSW/DISKANN strategy with implementation guardrails | ✓ SATISFIED | Phase 42 concretely implements the HNSW path and preconditions at `surreal_schema.py:341-367` and `surreal_vector.py:105-214`; embedded HNSW spot-check passed. Roadmap Phase 43 still owns broader production-derived latency/build-time evidence for the milestone. |
| `SURR-SEARCH-03` | 42-01, 42-03 | Graph/entity retrieval runs through Surreal relation records and preserves relation metadata | ✓ SATISFIED | Relation schema/index path at `surreal_schema.py:333-336`, query/ranking path at `surreal_graph.py:52-145`, embedded relation-query spot-check passed. |
| `SURR-SEARCH-04` | 42-04 | Hybrid fusion runs over Surreal result sets and preserves engine attribution | ✓ SATISFIED | Override builder at `surreal_native.py:18-40`, fusion seam at `service.py:1339-1410`, attribution tests at `test_service_search.py:1363-1409`, hybrid/service spot-check passed. |

No orphaned Phase 42 requirements were found in `.planning/REQUIREMENTS.md`.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| — | — | None in scanned phase-owned source/test files | ℹ️ Info | No `TBD`/`FIXME`/`XXX` debt markers, placeholder text, or console-log-only implementations found. |

### Human Verification Required

None. The phase deliverables are backend retrieval/search seams with code-level and embedded-runtime evidence; no visual or human-only acceptance surface remains for Phase 42 itself.

### Gaps Summary

No blocker gaps found. Phase 42 achieves the implementation-only goal: real Surreal-native BM25, HNSW vector, relation-backed graph retrieval, and explicit hybrid fusion wiring exist in code, are exercised by embedded-runtime tests, and did not spill into Phase 43/44/45 cutover or deletion scope.

---

_Verified: 2026-06-14T08:28:32Z_
_Verifier: the agent (gsd-verifier)_
