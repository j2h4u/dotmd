---
phase: 10-background-trickle-indexer
plan: 04
subsystem: api, cli
tags: [status-endpoint, trickle-progress, cli, fastapi, pydantic]

# Dependency graph
requires:
  - phase: 10-03
    provides: "TrickleIndexer with .state property returning TrickleState dataclass"
provides:
  - "IndexStats extended with trickle progress fields (status, indexed, total, rate, ETA)"
  - "GET /status returns trickle indexer progress in JSON response"
  - "CLI `dotmd status` displays background indexing progress with rate and ETA"
affects: []

# Tech tracking
tech-stack:
  added: []
  patterns: [status-enrichment-from-background-task-state]

key-files:
  created: []
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/cli.py
    - backend/src/dotmd/api/server.py

key-decisions:
  - "Service.status() always returns IndexStats (never None) so trickle progress is available pre-index"
  - "Trickle fields use Optional[T] = None defaults -- absent when indexer not running, populated when active"

patterns-established:
  - "Status enrichment: service reads background task state and merges into response model"

requirements-completed: [BGIDX-02]

# Metrics
duration: 2min
completed: 2026-03-28
---

# Phase 10 Plan 04: Status Endpoint & CLI Progress Summary

**IndexStats extended with trickle progress fields, CLI shows backlog count/rate/ETA, API /status returns enriched JSON with background indexer state**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T19:44:30Z
- **Completed:** 2026-03-27T19:46:39Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- IndexStats model extended with 6 trickle progress fields (status, indexed, total, current_file, files_per_hour, eta_minutes)
- Service.status() reads live TrickleIndexer state and enriches response; always returns IndexStats (never None)
- CLI status command displays formatted background progress: "indexing (N/M files) @ X files/hr, ETA ~Ymin"
- API /status endpoint returns IndexStats with trickle fields in JSON (response_model updated from Optional)

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend IndexStats with trickle progress fields** - `2168af7` (feat)
2. **Task 2: Update CLI status command and API response model** - `89557fe` (feat)

## Files Created/Modified
- `backend/src/dotmd/core/models.py` - Added 6 trickle_* fields to IndexStats (status, indexed, total, current_file, files_per_hour, eta_minutes)
- `backend/src/dotmd/api/service.py` - status() enriches stats with TrickleIndexer.state; returns IndexStats always (not None)
- `backend/src/dotmd/cli.py` - status command displays background progress (backlog count, rate, ETA, watching, stopping)
- `backend/src/dotmd/api/server.py` - /status endpoint response_model changed from IndexStats | None to IndexStats

## Decisions Made
- Service.status() returns IndexStats always (not None) so trickle progress is available even before any explicit `dotmd index` has run -- the trickle indexer may already be processing files
- Trickle fields default to None rather than 0 to distinguish "not running" from "running with zero progress"

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree was behind feat/sqlite-vec-backend; fast-forward merged to get Plans 01-03 changes before starting
- Python venv only exists in main repo; used PYTHONPATH override to point to worktree source for verification

## Known Stubs

None - all functionality fully wired.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Plan 04 is the final plan in Phase 10 -- background trickle indexer feature complete
- All BGIDX requirements addressed: BGIDX-01 (trickle core), BGIDX-02 (progress reporting), BGIDX-03 (watchdog)

## Self-Check: PASSED

All 4 modified files exist on disk. Both task commits (2168af7, 89557fe) verified in git log. SUMMARY.md created.

---
*Phase: 10-background-trickle-indexer*
*Completed: 2026-03-28*
