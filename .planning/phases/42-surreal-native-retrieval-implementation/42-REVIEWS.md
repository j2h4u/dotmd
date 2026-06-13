---
phase: 42-surreal-native-retrieval-implementation
cycle: 1
reviewers: [opencode, claude]
reviewed_at: 2026-06-14T01:14:54+05:00
plans_reviewed:
  - 42-01-PLAN.md
  - 42-02-PLAN.md
  - 42-03-PLAN.md
  - 42-04-PLAN.md
supporting_artifacts:
  - 42-RESEARCH.md
  - 42-PATTERNS.md
  - ../39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md
  - ../39-surrealdb-native-retrieval-contract/39-01-SUMMARY.md
  - ../40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md
  - ../41-production-grade-surreal-schema-and-import/41-01-SUMMARY.md
  - ../41-production-grade-surreal-schema-and-import/41-02-SUMMARY.md
  - ../41-production-grade-surreal-schema-and-import/41-03-SUMMARY.md
cycle_summary:
  current_high: 1
  current_actionable: 5
---

# Cross-AI Plan Review - Phase 42 Cycle 1

## Tooling

Requested intent: `$gsd-plan-review-convergence 42 --opencode --claude`, cycle 1.

The `gsd-plan-review-convergence` and `gsd-review` skill instructions were available and read. A packaged slash-command runner was not available in this Codex orchestration context, so I performed the equivalent review workflow directly:

- OpenCode reviewer invoked with `/home/j2h4u/.opencode/bin/opencode run --dangerously-skip-permissions`.
- Claude reviewer invoked with `/home/j2h4u/.local/bin/claude --print --permission-mode bypassPermissions`.
- Both reviewers received the same workspace-local prompt and were instructed to review Phase 42 plans plus research, patterns, and relevant Phase 39-41 summaries.
- The orchestrator is Codex and was not used as a reviewer.

OpenCode first invocation failed because the installed CLI parsed the message after `--file` as another file path. Retried successfully with the message before `--file`.
Claude first invocation failed because this CLI required stdin or prompt input for `--print`. Retried successfully through stdin.

## OpenCode Review

### Summary

OpenCode found the Phase 42 plans well-structured and scope-disciplined. The reviewer agreed that the decomposition into schema/capability foundation, parallel FTS/vector and graph engines, then fusion wiring is correct. OpenCode also confirmed that the plans respect the locally verified SurrealDB 2.0 runtime path: old-style `SEARCH ANALYZER` BM25, HNSW, relation tables, and Python-side fusion. No cutover, shadow-run, fallback, production restart, or legacy deletion leak was found.

### Strengths

- Runtime-version constraints are explicit and repeated across the plans.
- Dependency order is correct: 42-01 before 42-02 and 42-03, then 42-04.
- The plans use existing architecture seams: `SearchEngineProtocol`, `DotMDService._collect_candidate_pool`, `fuse_results`, and `build_candidates`.
- Threat models are specific and useful.
- The capability probe in 42-01 is a good guard against Surreal syntax drift.
- 42-RESEARCH and 42-PATTERNS provide strong code-level grounding.

### Concerns

- `[MEDIUM]` 42-02 / 42-PATTERNS: the FTS5 sanitization analog could be misread as a literal instruction to append FTS5-style `*` wildcards, which Surreal BM25 does not need. OpenCode recommended clarifying that only the helper boundary should be copied, not the FTS5 wildcard transform. Count status: not counted as unresolved PLAN work because 42-02-PLAN.md already says to sanitize "only enough to avoid empty predicates" and pass the actual query as `$query`.
- `[LOW]` 42-04: the Surreal override builder returns `semantic`, `keyword`, and `graph_direct`, while graph enrichment remains on the existing `_graph_engine` unless an explicit `graph` override is supplied. OpenCode recommended clarifying that graph enrichment replacement remains outside Phase 42. Count status: not counted because 42-04-PLAN.md already states that graph enrichment stays on the existing graph engine unless explicitly overridden.
- `[LOW]` `.planning/REQUIREMENTS.md`: Phase 41 requirement traceability appears stale. Count status: not counted because this is not a Phase 42 PLAN.md execution concern.
- `[LOW]` 42-01 / 42-02: `hnsw_ef` is described as bounded but no concrete bounds are assigned. Count status: counted as actionable non-HIGH because the PLAN files should pin the validation contract before implementation.
- `[LOW]` 42-03: relation queries should account for Phase 41 relation rows having `in`/`out` endpoints in addition to flat `source_id` / `target_id` fields. Count status: covered by the current HIGH graph indexing concern below rather than counted separately.

### Risk Assessment

OpenCode rated the plans LOW risk. The largest OpenCode concern was avoiding accidental FTS5-specific query transforms in the Surreal FTS engine. Other concerns were plan-clarification items.

### Source Grounding Notes

OpenCode verified that existing referenced files are present: `backend/src/dotmd/search/base.py`, `backend/src/dotmd/search/fusion.py`, `backend/src/dotmd/api/service.py`, `backend/src/dotmd/storage/surreal.py`, `backend/src/dotmd/storage/surreal_schema.py`, `backend/src/dotmd/ingestion/migrate_surreal.py`, and existing test files. It also confirmed that Phase 42-created files such as `surreal_fts.py`, `surreal_vector.py`, `surreal_graph.py`, and `surreal_native.py` are correctly absent before execution.

## Claude Review

### Summary

Claude agreed that the Phase 42 plans are a disciplined and well-grounded implementation decomposition. It emphasized that the plans correctly target the local SurrealDB 2.0 feature set rather than newer 3.x documentation, and that default runtime behavior remains unchanged because 42-04 does not wire the override builder into startup, settings, CLI, MCP, or service initialization.

Claude raised one HIGH issue and several actionable non-HIGH issues. The common theme is that the plans should prove true database-backed retrieval, not only fake-connection statement construction.

### Strengths

- Clean wave order and parallelism.
- Correct handling of runtime/docs skew.
- Correct reuse of the service candidate-pool seam.
- Explicit anti-pattern targeting for old `scan_table()` hot paths.
- Transform-only discipline for title and tag materialization from imported metadata.

### Concerns

- `[HIGH]` 42-01 / 42-03: `relations.target_id` has no supporting single-field index, so graph entity lookup can degrade into a database-side scan. Phase 41 relation indexes cover `rel_type` and `(source_id, target_id)`, but entity-to-chunk lookup filters by `target_id` and relation type. Change needed: add `relations_target_id_idx` or equivalent to the 42-01 retrieval index plan and assert it in tests; have 42-03 rely on that indexed lookup.
- `[MEDIUM]` 42-01 / 42-02: the HNSW plan assumes one embedding dimension while the `embeddings` table can store multiple `embedding_model` values. Change needed: state and test a single-active-model/dimension-uniformity precondition, or specify per-model index scoping plus over-fetch before model filtering.
- `[MEDIUM]` 42-01 / 42-02 / 42-03: embedded Surreal smoke tests are optional or "where deterministic", so engine plans could pass fake-only tests without proving real BM25/HNSW/relation SurrealQL. Change needed: make 42-01 create a reusable isolated embedded-Surreal fixture and make at least one real embedded assertion mandatory per engine.
- `[MEDIUM]` 42-01: the exact source metadata key for `tags_text` is not pinned. A wrong key would silently make tag-weighted BM25 empty across the corpus. Change needed: pin the actual metadata key in 42-01 tests with a known tagged document and assert non-empty `tags_text`.
- `[LOW]` 42-01: the capability probe is created and tested but not consumed as a runtime fail-closed gate by 42-02, 42-03, or 42-04. Change needed: either wire it into the first runtime consumer or explicitly defer runtime consumption to Phase 43/44 in 42-01 success criteria.

### Suggestions

- Consider reusing `SemanticSearchEngine` behind a Surreal `VectorStoreProtocol` instead of duplicating query normalization in a standalone vector engine. If a standalone `SurrealVectorSearchEngine` remains, add a byte-for-byte parity test against `SemanticSearchEngine` query encoding.
- State the Phase 43 handoff explicitly in 42-04 because the override builder is intentionally unwired in Phase 42.
- Consider adding one Phase 40 eval-shaped assertion in 42-02 or 42-03 so Phase 43 does not need to reshape engine outputs later.

### Risk Assessment

Claude rated the plans LOW-MEDIUM risk. The architecture and scope are sound, but graph indexing, multi-model HNSW assumptions, and fake-only testing could let Phase 42 appear green while still missing native retrieval behavior.

### Source Grounding Notes

Claude checked these existing symbols and files:

- `DotMDService._collect_candidate_pool`: present in `backend/src/dotmd/api/service.py`.
- `fuse_results` and `build_candidates`: present in `backend/src/dotmd/search/fusion.py` and used by service code.
- `build_dotmd_surreal_schema_plan`: present in `backend/src/dotmd/storage/surreal_schema.py`.
- `build_surreal_native_retrieval_index_plan`, `SurrealRetrievalCapabilityReport`, and `probe_surreal_native_retrieval_capabilities`: absent and correctly planned as Phase 42 artifacts.
- Current `chunks` table has `text`, `ref`, `document_ref`, and metadata but not `title` / `tags_text`; 42-01 correctly adds them.
- Current `embeddings` table has `embedding_model`, `text_hash`, and `embedding`.
- Current `relations` table has `rel_type`, `weight`, `source_id`, `target_id`, `source_table`, `target_table`, `properties`, and `metadata`, but no single-field `target_id` index.
- `load_sqlite_rows_for_surreal`: present in `backend/src/dotmd/ingestion/migrate_surreal.py`; current chunk payload does not yet include `title` / `tags_text`.
- `SemanticSearchEngine`, `SearchEngineProtocol`, and `GraphDirectEngine` are present.

## Consensus Summary

### Agreed Strengths

- The phase is correctly scoped to native retrieval implementation, not cutover.
- HNSW, old-style BM25, relation tables, and Python fusion are the right feature targets for the currently verified local runtime.
- The wave order is coherent and enables parallel work after 42-01.
- The new engines should fit the existing `SearchEngineProtocol` and service fusion seam.

### Agreed Concerns

- The plans need stronger guarantees that native Surreal retrieval is actually exercised by tests, not only statement strings against fake connections.
- Some validation contracts should be pinned before execution: `hnsw_ef` bounds, model/dimension assumptions, relation lookup indexing, and tag metadata source key.

### Divergent Views

- OpenCode treated the FTS sanitization ambiguity as the main non-HIGH risk. The current 42-02 PLAN text already narrows sanitization to empty-predicate handling, so it is not counted as unresolved PLAN work, but executor attention is warranted.
- Claude treated relation indexing as HIGH because it can satisfy "no Python scan" while still failing the intent of native indexed graph retrieval. This is counted.

## Verification Coverage

Source-grounding pass used `rg` over the current checkout. Verdicts:

| Symbol / File | Verdict | Evidence |
|---|---|---|
| `SearchEngineProtocol.search` | VERIFIED | `backend/src/dotmd/search/base.py:14`, `backend/src/dotmd/search/base.py:21` |
| `FTS5SearchEngine.search` | VERIFIED | `backend/src/dotmd/search/fts5.py:74`, `backend/src/dotmd/search/fts5.py:273` |
| `SemanticSearchEngine.search` | VERIFIED | `backend/src/dotmd/search/semantic.py:26`, `backend/src/dotmd/search/semantic.py:232` |
| `GraphDirectEngine.search` | VERIFIED | `backend/src/dotmd/search/graph_direct.py:20`, `backend/src/dotmd/search/graph_direct.py:52` |
| `fuse_results` | VERIFIED | `backend/src/dotmd/search/fusion.py:189` |
| `build_candidates` | VERIFIED | `backend/src/dotmd/search/fusion.py:275` |
| `DotMDService._collect_candidate_pool` | VERIFIED | `backend/src/dotmd/api/service.py:233`, `backend/src/dotmd/api/service.py:1325` |
| `SurrealConnection` | VERIFIED | `backend/src/dotmd/storage/surreal.py:118` |
| `SurrealConnection.scan_table` | VERIFIED | `backend/src/dotmd/storage/surreal.py:163` |
| Phase 38 vector scan anti-pattern | VERIFIED | `backend/src/dotmd/storage/surreal.py:458` |
| `SurrealRecordIdCodec` | VERIFIED | `backend/src/dotmd/storage/surreal.py:49` |
| `build_dotmd_surreal_schema_plan` | VERIFIED | `backend/src/dotmd/storage/surreal_schema.py:259` |
| `load_sqlite_rows_for_surreal` | VERIFIED | `backend/src/dotmd/ingestion/migrate_surreal.py:275` |
| Relation import with `INSERT RELATION` | VERIFIED | `backend/src/dotmd/storage/surreal.py:765`, `backend/src/dotmd/storage/surreal.py:779` |
| Relation fields `rel_type`, `weight`, `source_id`, `target_id` | VERIFIED | `backend/src/dotmd/storage/surreal_schema.py` and `backend/src/dotmd/storage/surreal.py` matches from source-grounding pass |
| Existing `source_documents` metadata source | VERIFIED | `backend/src/dotmd/ingestion/migrate_surreal.py` matches from source-grounding pass |
| HNSW and Python fusion research grounding | VERIFIED | `42-RESEARCH.md` lines matching HNSW, DISKANN rejection, `search::rrf` rejection, and Python fusion |
| Phase 42 new modules | VERIFIED ABSENT | `backend/src/dotmd/search/surreal_fts.py`, `surreal_vector.py`, `surreal_graph.py`, and `surreal_native.py` are planned artifacts, not existing symbols |
| Function signatures for future SurrealQL helpers | UNCHECKABLE | They are new Phase 42 artifacts and cannot be signature-checked before implementation |

## Current Unresolved Concerns

### HIGH

1. 42-01 / 42-03 must add and test an indexed relation lookup path for entity-to-chunk graph retrieval, especially `target_id` filtering for `MENTIONS` / `HAS_TAG` style queries.

### Actionable Non-HIGH

1. 42-01 / 42-02 must define the HNSW single-model/dimension-uniformity precondition or specify per-model index scoping and over-fetch behavior before model filtering.
2. 42-01 / 42-02 / 42-03 must make real embedded-Surreal retrieval assertions mandatory, with a reusable isolated fixture owned by the plans.
3. 42-01 must pin the exact metadata key used to materialize `tags_text` and test a known tagged document with non-empty output.
4. 42-01 / 42-02 must specify concrete bounds for `hnsw_ef` / top-k validation so tests and implementation share one contract.
5. 42-01 must either wire the capability probe into the first runtime consumer or explicitly defer runtime consumption to Phase 43/44.

## Cycle Summary

CYCLE_SUMMARY: current_high=1 current_actionable=5

## Current HIGH Concerns

- 42-01 / 42-03: add and test an indexed relation lookup path for entity-to-chunk graph retrieval, especially `target_id` filtering for `MENTIONS` / `HAS_TAG` style queries.

## Current Actionable Non-HIGH Concerns

- 42-01 / 42-02: define the HNSW single-model/dimension-uniformity precondition or specify per-model index scoping and over-fetch behavior before model filtering.
- 42-01 / 42-02 / 42-03: make real embedded-Surreal retrieval assertions mandatory, with a reusable isolated fixture owned by the plans.
- 42-01: pin the exact metadata key used to materialize `tags_text` and test a known tagged document with non-empty output.
- 42-01 / 42-02: specify concrete bounds for `hnsw_ef` / top-k validation so tests and implementation share one contract.
- 42-01: either wire the capability probe into the first runtime consumer or explicitly defer runtime consumption to Phase 43/44.
