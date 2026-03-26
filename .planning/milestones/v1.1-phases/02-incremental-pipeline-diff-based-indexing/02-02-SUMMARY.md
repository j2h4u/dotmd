---
phase: 02-incremental-pipeline-diff-based-indexing
plan: 02
subsystem: api
tags: [cli, service-facade, force-reindex, click]

# Dependency graph
requires:
  - phase: 02-incremental-pipeline-diff-based-indexing
    plan: 01
    provides: IndexingPipeline.index(force=True) for full re-index bypass
provides:
  - DotMDService.index(force=True) threading to pipeline
  - CLI --force / -f flag for dotmd index command
  - Mode label output (incremental vs full re-index)
affects: [phase-03-cli-api-polish]

# Tech tracking
tech-stack:
  added: []
  patterns: [parameter-threading-cli-service-pipeline]

key-files:
  created:
    - backend/tests/test_service_force.py
  modified:
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/cli.py

key-decisions:
  - "Used post-init mock replacement instead of __init__ patching for simpler test setup"

patterns-established:
  - "CLI -> Service -> Pipeline parameter threading: force kwarg flows through all layers as keyword-only argument"

requirements-completed: [IP-05]

# Metrics
duration: 3min
completed: 2026-03-23
---

# Phase 02 Plan 02: Force Parameter Threading Summary

**--force CLI flag threaded through DotMDService to IndexingPipeline, enabling user-triggered full re-index bypass of incremental change detection**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-23T11:48:07Z
- **Completed:** 2026-03-23T11:50:55Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- DotMDService.index() accepts force keyword parameter and passes it to pipeline.index()
- CLI `dotmd index --force` / `-f` triggers full re-index via service
- CLI output shows mode label: "incremental" or "full re-index"
- 3 new tests verify force parameter threading (45 total pass)

## Task Commits

Each task was committed atomically (TDD for Task 1):

1. **Task 1: Thread force parameter through DotMDService**
   - `efcf160` (test) - RED: 3 failing tests for force parameter threading
   - `ce908ef` (feat) - GREEN: force parameter added to DotMDService.index()
2. **Task 2: Add --force flag to CLI index command**
   - `346720d` (feat) - --force/-f flag with mode label output

## Files Created/Modified
- `backend/tests/test_service_force.py` - 3 tests verifying force parameter threading (default, True, False)
- `backend/src/dotmd/api/service.py` - DotMDService.index() gains `force: bool = False` keyword arg
- `backend/src/dotmd/cli.py` - `--force` / `-f` Click option, mode label in echo output

## Decisions Made
- Used post-init mock replacement (`service._pipeline.index = MagicMock()`) instead of patching `__init__` -- simpler setup since DotMDService.__init__ has complex side effects (creates stores, search engines, extractors)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## Known Stubs
None -- force parameter is fully wired end-to-end from CLI through service to pipeline.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Phase 02 complete: incremental pipeline with force override fully wired
- Full parameter chain verified: CLI --force -> service.index(force=True) -> pipeline.index(force=True)
- Ready for Phase 03 (CLI & API Polish)

## Self-Check: PASSED

All 3 files verified present. All 3 commit hashes verified in git log.

---
*Phase: 02-incremental-pipeline-diff-based-indexing*
*Completed: 2026-03-23*
