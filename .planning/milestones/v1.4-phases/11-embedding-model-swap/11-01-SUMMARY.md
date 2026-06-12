---
phase: 11-embedding-model-swap
plan: 01
subsystem: testing
tags: [evaluation, search-quality, httpx, argparse, a-b-testing]

# Dependency graph
requires: []
provides:
  - "Baseline capture script for search quality evaluation"
  - "A/B comparison script with rank/score delta analysis"
affects: [11-02, 11-03]

# Tech tracking
tech-stack:
  added: [httpx]
  patterns: [standalone eval scripts communicating via HTTP only]

key-files:
  created:
    - backend/scripts/eval_baseline.py
    - backend/scripts/eval_compare.py
  modified: []

key-decisions:
  - "Used GET /search with query params (matching actual API) instead of POST as plan suggested"
  - "Scripts detect embedding model via TEI /info and dotMD /status endpoints"
  - "Verdict logic: improved/degraded/unchanged based on top-3 score delta and lost hits"

patterns-established:
  - "Eval scripts are standalone (no dotmd imports), communicate via HTTP only"
  - "Test query set defined as constants in eval_baseline.py, reused by compare via JSON"

requirements-completed: [EVAL-01, EVAL-02]

# Metrics
duration: 2min
completed: 2026-03-30
---

# Phase 11 Plan 01: Evaluation Scripts Summary

**Standalone A/B search quality evaluation tooling -- baseline capture and rank/score comparison via HTTP API**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-30T19:47:11Z
- **Completed:** 2026-03-30T19:49:30Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- Baseline capture script with 5 test queries from SEARCH-BASELINE.md (semantic, keyword, negative, entity, hybrid)
- A/B comparison script with per-query rank changes, score deltas, new/lost hits, top-3 stability
- Summary verdict with improved/degraded/unchanged counts and merge recommendation

## Task Commits

Each task was committed atomically:

1. **Task 1: Create baseline capture script** - `3998fe1` (feat)
2. **Task 2: Create A/B comparison script** - `e043508` (feat)

## Files Created/Modified
- `backend/scripts/eval_baseline.py` - Captures search results from live dotMD instance into JSON baseline
- `backend/scripts/eval_compare.py` - Compares current results against saved baseline with detailed analysis

## Decisions Made
- **GET instead of POST**: Plan specified `POST /search` but the actual API uses `GET /search?q=...`. Used the correct endpoint.
- **Model detection**: Scripts try dotMD `/status` first, then TEI `/info` on common ports (8088, 8080) to identify the embedding model.
- **Verdict thresholds**: Score degradation threshold set at 0.05 (configurable via constant). Top-3 lost hits always count as degradation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected HTTP method for search endpoint**
- **Found during:** Task 1 (baseline capture script)
- **Issue:** Plan specified `POST http://{host}/search` but the actual API endpoint is `GET /search` with query parameters
- **Fix:** Used `httpx.Client.get()` with `params={"q": query, "top_k": top_k}` matching the real API
- **Files modified:** backend/scripts/eval_baseline.py, backend/scripts/eval_compare.py
- **Verification:** Syntax check passes, params match server.py endpoint signature
- **Committed in:** 3998fe1, e043508

---

**Total deviations:** 1 auto-fixed (Rule 1 - bug in plan spec)
**Impact on plan:** Essential for correctness -- POST would return 405 Method Not Allowed.

## Issues Encountered
None

## Known Stubs
None -- both scripts are complete and functional.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Evaluation scripts ready to use against the live dotMD service
- Run `eval_baseline.py` to capture current E5-large results before any model changes
- Plan 11-02 can use these scripts for the pplx-embed swap evaluation

## Self-Check: PASSED

- All 2 created files exist on disk
- All 2 task commits verified in git log (3998fe1, e043508)
- SUMMARY.md created successfully

---
*Phase: 11-embedding-model-swap*
*Completed: 2026-03-30*
