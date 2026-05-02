---
phase: 05-bm25-hybrid-fix
plan: 01
subsystem: search
tags: [bm25, reranker, cross-encoder, rrf, hybrid-search]

# Dependency graph
requires: []
provides:
  - "Score-threshold-free cross-encoder reranker"
  - "Merge-back logic preserving all RRF fusion candidates through reranking"
  - "BM25-only diagnostic logging at DEBUG level"
affects: [06-docker-integration]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "Reranker reorders but never filters -- all candidates survive"
    - "Merge-back pattern: unscored fusion candidates appended with fusion-only weight"

key-files:
  created:
    - backend/tests/test_reranker.py
    - backend/tests/test_hybrid_bm25.py
  modified:
    - backend/src/dotmd/search/reranker.py
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/api/service.py

key-decisions:
  - "D-01: Remove hard score threshold (-8.0) from reranker entirely rather than making it configurable"
  - "D-02: Merge back all fusion candidates not scored by reranker with fusion-only weight (0.4 * norm_f)"
  - "D-03: Keep blend weights unchanged (0.4 fusion + 0.6 reranker)"
  - "D-05: Add DEBUG-level diagnostic logging for BM25-only survival counts"

patterns-established:
  - "Reranker never filters: reorders candidates by cross-encoder score, truncates by top_k only"
  - "Merge-back pattern: after blending reranked pool, append unscored candidates with fusion-only scores"

requirements-completed: [SEARCH-01]

# Metrics
duration: 5min
completed: 2026-03-26
---

# Phase 05 Plan 01: BM25 Hybrid Fix Summary

**Removed cross-encoder score threshold and added merge-back logic so all BM25 fusion candidates survive through reranking**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-26T22:17:40Z
- **Completed:** 2026-03-26T22:22:58Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- Removed the hard score threshold (-8.0) from the reranker that silently dropped BM25-only matches with low cross-encoder scores
- Added merge-back logic so fusion candidates beyond pool_size are preserved with fusion-only scores instead of being permanently lost
- Added diagnostic logging at DEBUG level reporting how many BM25-only matches survived reranking
- 8 new tests (5 reranker unit + 3 hybrid integration) all passing, 65 total tests with no regressions

## Task Commits

Each task was committed atomically:

1. **Task 1: Remove reranker score threshold and clean dead config** - `96f6ef1` (fix)
2. **Task 2: Add merge-back logic and diagnostic logging in service search** - `d09fb08` (fix)

_Both tasks followed TDD: RED (failing tests) -> GREEN (implementation) -> verify_

## Files Created/Modified
- `backend/tests/test_reranker.py` - 5 unit tests verifying reranker returns all candidates without threshold filtering
- `backend/tests/test_hybrid_bm25.py` - 3 integration tests for merge-back, BM25 survival, and diagnostic logging
- `backend/src/dotmd/search/reranker.py` - Removed score_threshold parameter and filter from list comprehension
- `backend/src/dotmd/core/config.py` - Removed rerank_score_threshold setting
- `backend/src/dotmd/api/service.py` - Removed score_threshold kwarg, added merge-back loop and BM25 diagnostic logging

## Decisions Made
- D-01: Removed threshold entirely (not configurable) -- any threshold would silently drop BM25 matches
- D-02: Merge-back uses fusion-only weight `0.4 * norm_f` for unscored candidates (consistent with blend formula)
- D-03: Blend weights 0.4/0.6 unchanged -- no reason to change and keeps behavior predictable
- D-05: Logging at DEBUG level (visible only with `--verbose`) to avoid noise in normal operation

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Issues Encountered
- CrossEncoder mock target needed adjustment: `sentence_transformers.CrossEncoder` instead of `dotmd.search.reranker.CrossEncoder` because the import is lazy inside `_load_model()`, not at module level. Resolved by using `@patch("sentence_transformers.CrossEncoder")` decorator.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- BM25 hybrid search fix is complete and tested
- Ready for Phase 06 (Docker Integration + Migration) which will deploy these changes
- Empirical validation in production will confirm BM25 matches now appear in hybrid results

## Self-Check: PASSED

All 5 files verified present. Both commit hashes (96f6ef1, d09fb08) found in git log.

---
*Phase: 05-bm25-hybrid-fix*
*Completed: 2026-03-26*
