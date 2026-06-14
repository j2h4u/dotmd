---
phase: 42-surreal-native-retrieval-implementation
plan: 02
subsystem: search
tags: [surrealdb, python, retrieval, bm25, hnsw]
requires:
  - phase: 39-surrealdb-native-retrieval-contract
    provides: surreal-native retrieval semantics and accepted-difference policy
  - phase: 42-surreal-native-retrieval-implementation
    provides: retrieval schema fields, index-plan helpers, and embedded Surreal fixtures from 42-01
provides:
  - weighted Surreal BM25 search engine over chunk title, tags_text, and text
  - HNSW-backed Surreal vector search engine with semantic-query normalization
  - embedded Surreal regression coverage for native lexical and vector retrieval
affects: [42-03, 42-04, 43]
tech-stack:
  added: []
  patterns: [fixed-field SurrealQL weighting, cached embedding precondition checks, embedded Surreal retrieval assertions]
key-files:
  created:
    - backend/src/dotmd/search/surreal_fts.py
    - backend/src/dotmd/search/surreal_vector.py
    - backend/tests/search/test_surreal_native_fts.py
    - backend/tests/search/test_surreal_native_vector.py
  modified: []
key-decisions:
  - "Surreal full-text scores are negated in the query so the engine keeps dotMD's descending higher-is-better tuple contract."
  - "The HNSW operator uses validated literal top-k/ef values in SurrealQL because the current embedded runtime rejects parameters inside <|k,ef|>."
patterns-established:
  - "Keep user text and query vectors bound as Surreal variables while schema identifiers and HNSW operator bounds stay fixed or validated."
  - "Validate the single-model and uniform-dimension precondition once per engine instance with a lightweight Surreal query instead of scan_table-based hot-path scans."
requirements-completed: [SURR-SEARCH-01, SURR-SEARCH-02]
duration: 4min
completed: 2026-06-14
status: complete
---

# Phase 42 Plan 02: Surreal-native retrieval implementation Summary

**Weighted Surreal BM25 and HNSW search engines with embedded-runtime assertions and no scan_table vector fallback**

## Performance

- **Duration:** 4 min
- **Started:** 2026-06-14T12:45:41+05:00
- **Completed:** 2026-06-14T12:49:30+05:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added RED coverage for weighted BM25 statement composition, HNSW query shape, bounds enforcement, precondition failures, score-floor behavior, and embedded Surreal retrieval.
- Implemented `SurrealFTSSearchEngine` with fixed-field weighted scoring and fail-soft operational error handling.
- Implemented `SurrealVectorSearchEngine` with semantic-style query normalization, cached single-model/dimension validation, and native HNSW lookup over Surreal embeddings.

## TDD Notes

- **RED:** `9ee416d` added failing lexical/vector tests, including the mandatory embedded `surrealkv://` assertions.
- **GREEN:** `ecd9aec` implemented the two engines and tightened the tests against the real embedded runtime behavior.
- **REFACTOR:** None.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED tests for Surreal BM25 and HNSW engines | `9ee416d` | `test` |
| 2 | Implement Surreal full-text and vector search engines | `ecd9aec` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/search/surreal_fts.py` - Weighted full-text engine that binds user query text through Surreal variables and returns `(chunk_id, score)` tuples.
- `backend/src/dotmd/search/surreal_vector.py` - HNSW vector engine that preserves semantic-query encoding behavior and validates model/dimension bounds before lookup.
- `backend/tests/search/test_surreal_native_fts.py` - Covers blank-query short-circuiting, weighted SurrealQL shape, fail-soft FTS errors, and embedded BM25 retrieval.
- `backend/tests/search/test_surreal_native_vector.py` - Covers query normalization, HNSW query shape, bounds and precondition failures, score-floor behavior, and embedded HNSW retrieval.

## Decisions Made

- Preserved the existing semantic-engine query normalization rules exactly: `query_instruction` wins, then `query:` prefix when enabled, then the raw query.
- Used validated literal `top_k` / `hnsw_ef` values inside the HNSW operator while keeping the query vector and embedding model as Surreal variables, matching the current runtime constraints without interpolating user-derived content.

## Verification Output

- `cd backend && uv run pytest tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_vector.py -q` -> PASS (`19 passed`)
- `cd backend && uv run ruff check src/dotmd/search/surreal_fts.py src/dotmd/search/surreal_vector.py tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_vector.py` -> PASS

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The embedded Surreal runtime rejects parameters inside the HNSW operator (`<|$top_k,$hnsw_ef|>`), so the engine uses validated integer literals there and keeps user-derived values in bound variables elsewhere.
- Embedded test records cannot use hyphenated Surreal record ids directly, so the tests use safe Surreal record ids while preserving real chunk ids in stored fields.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 42-03 can reuse the same embedded fixture and fail-soft engine contract style for relation-backed graph retrieval.
- Plan 42-04 can fuse the new weighted BM25 and HNSW tuple outputs through the existing service candidate-pool seam without revisiting engine-level query encoding or bounds rules.

## Self-Check

PASSED

- Found `.planning/phases/42-surreal-native-retrieval-implementation/42-02-SUMMARY.md`
- Found task commits `9ee416d` and `ecd9aec` in git history

---
*Phase: 42-surreal-native-retrieval-implementation*
*Completed: 2026-06-14*
