---
phase: 19-reranker-adapter-layer-and-multi-model-comparison
plan: 02-shared-candidate-pool
subsystem: search
tags: [reranker, candidate-pool, rrf, graph-enrichment, service]

requires:
  - phase: 19-reranker-adapter-layer-and-multi-model-comparison
    provides: RerankerProtocol, built-in registry, and cached RerankerFactory
provides:
  - Explicit RerankCandidatePool for reusable retrieval/fusion output
  - DotMDService runtime reranker selection by stable name
  - Single-reranker normal search path backed by RerankerFactory
  - Regression coverage for graph-enriched fused fallback behavior
affects: [phase-19, search, api-service, reranker-comparison]

tech-stack:
  added: []
  patterns:
    - Typed candidate pool over existing search engines
    - Factory-backed reranker lookup per reranked request
    - Fusion-only merge-back for candidates not scored by reranker

key-files:
  created:
    - .planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-02-shared-candidate-pool-SUMMARY.md
  modified:
    - backend/src/dotmd/api/service.py
    - backend/tests/test_hybrid_bm25.py

key-decisions:
  - "Keep normal search to one factory-resolved reranker per request; rerank=False does not touch the factory."
  - "Treat graph enrichment as part of the shared candidate pool, so comparison work sees the same post-enrichment candidates as normal search."
  - "Merge back candidates not scored by the reranker with their original fusion/enrichment scores."

patterns-established:
  - "_collect_candidate_pool returns post-graph-enrichment fused candidates and engine_results."
  - "DotMDService.search accepts reranker_name for runtime selection while preserving the configured default."
  - "Tests mock reranker factories instead of concrete reranker instances."

requirements-completed:
  - RERANK-ADAPTER-01
  - RERANK-SELECT-04
  - RERANK-COMPARE-01

duration: 8min
completed: 2026-05-01
---

# Phase 19 Plan 02: Shared Candidate Pool and Single-Reranker Search Wiring Summary

**Reusable post-graph-enrichment candidate pool with factory-backed runtime reranker selection and preserved fused fallback scoring**

## Performance

- **Duration:** 8min
- **Started:** 2026-05-01T12:18:00Z
- **Completed:** 2026-05-01T12:26:09Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Extracted `_collect_candidate_pool()` and `RerankCandidatePool` so semantic, keyword, graph-direct, RRF fusion, and graph enrichment can run once and be reused.
- Wired `DotMDService.search(..., reranker_name=...)` through `RerankerFactory` without loading a reranker in `__init__`.
- Preserved fused fallback behavior when reranking is disabled or when a reranker returns no candidates.
- Added regression tests proving graph-enriched candidates appear in `pool["fused"]`, engine calls happen once, factory lookup behavior is correct, and search logging reflects whether reranker scores were actually applied.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: Add reusable candidate pool tests** - `346a895` (test)
2. **Task 1 GREEN: Extract shared candidate pool** - `5021e9c` (feat)
3. **Task 2 RED: Add reranker factory wiring tests** - `e946f25` (test)
4. **Task 2 GREEN: Wire search through reranker factory** - `bb048cb` (feat)
5. **Task 3 RED: Add search contract tests** - `4bf04e1` (test)
6. **Task 3 GREEN: Preserve fusion scores on merge-back** - `a8db1b1` (fix)

## Files Created/Modified

- `backend/src/dotmd/api/service.py` - Added `RerankCandidatePool`, extracted `_collect_candidate_pool()`, routed search reranking through `RerankerFactory`, and preserved fusion-only merge-back scores.
- `backend/tests/test_hybrid_bm25.py` - Added candidate-pool, runtime reranker, `rerank=False`, graph-enrichment, merge-back, and logging regression tests.
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-02-shared-candidate-pool-SUMMARY.md` - Execution summary.

## Decisions Made

- Used `RerankerFactory.get(reranker_name)` inside the rerank branch only, so `rerank=False` never resolves or warms a reranker.
- Kept graph enrichment under the existing `"graph"` engine key because `build_search_results()` already maps that key to `graph_score`.
- Preserved raw fusion/enrichment scores for candidates merged back after reranking instead of normalizing them into the reranker blend scale.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Preserved fusion-only scores for merge-back candidates**
- **Found during:** Task 3 (Preserve search result and logging contracts after refactor)
- **Issue:** Candidates not returned by the reranker, including graph-appended candidates, were being normalized into the reranker blend range. A graph-enriched fallback could receive a negative score instead of its enrichment score.
- **Fix:** Merge back unscored candidates with their original post-enrichment fused score.
- **Files modified:** `backend/src/dotmd/api/service.py`, `backend/tests/test_hybrid_bm25.py`
- **Verification:** `cd backend && uv run pytest tests/test_hybrid_bm25.py -q`
- **Committed in:** `a8db1b1`

---

**Total deviations:** 1 auto-fixed (Rule 1).
**Impact on plan:** The fix tightened the planned result-contract preservation and did not expand scope.

## Issues Encountered

None beyond the merge-back scoring issue documented above.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. Stub-pattern scan only found intentional empty test values for mocked `heading_hierarchy`.

## Verification

- `cd backend && uv run pytest tests/test_hybrid_bm25.py -q` - PASS (`11 passed`, warnings only from existing pydantic-settings TOML warning)
- `cd backend && uv run pytest tests/test_hybrid_bm25.py tests/api/test_service_search.py -q` - PASS (`11 passed`, warnings only)
- `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py -q` - PASS (`35 passed`, warnings only)
- `cd backend && uv run ruff check src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_hybrid_bm25.py tests/api/test_service_search.py` - PASS

## Next Phase Readiness

Ready for Plan 03 to compare multiple reranker adapters using the shared post-graph-enrichment candidate pool without rerunning retrieval for each reranker.

## Self-Check: PASSED

- Confirmed key files exist on disk.
- Confirmed task commits exist: `346a895`, `5021e9c`, `e946f25`, `bb048cb`, `4bf04e1`, `a8db1b1`.
- Confirmed no generated or runtime files were left untracked by this plan.
- Confirmed `.planning/STATE.md` was not committed because it was already modified outside this plan and orchestrator-owned for wave completion.

---
*Phase: 19-reranker-adapter-layer-and-multi-model-comparison*
*Completed: 2026-05-01*
