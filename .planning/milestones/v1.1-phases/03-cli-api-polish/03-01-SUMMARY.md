---
phase: 03-cli-api-polish
plan: 01
subsystem: api
tags: [pydantic, sqlite, click, fastapi, diff-reporting, indexstats]

requires:
  - phase: 02-incremental-pipeline
    provides: "FileDiff, FileTracker, incremental/full index paths in IndexingPipeline"
provides:
  - "IndexStats with diff fields (new_files, modified_files, deleted_files, unchanged_files, data_dir)"
  - "CLI diff summary output after indexing"
  - "CLI status command with live change detection"
  - "API force parameter on POST /index"
  - "Metadata store schema migration for diff columns"
affects: [cli-output, api-consumers, status-monitoring]

tech-stack:
  added: []
  patterns:
    - "Idempotent ALTER TABLE migration pattern for SQLite schema evolution"
    - "Fresh diff counts on no-changes short-circuit (Pitfall 3 avoidance)"
    - "Live file diff in status() for change detection"

key-files:
  created:
    - backend/tests/test_diff_reporting.py
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/storage/metadata.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/cli.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/api/server.py

key-decisions:
  - "Idempotent ALTER TABLE with try/except for schema migration instead of version tracking"
  - "Fresh diff counts on no-changes path to avoid stale stored values (Pitfall 3)"
  - "Live file diff in DotMDService.status() using stored data_dir for change detection"

patterns-established:
  - "diff_counts dict threading: pipeline methods pass {new, modified, deleted, unchanged} dicts to _ingest_and_finalize"
  - "data_dir stored in IndexStats for subsequent status queries"

requirements-completed: [CA-01, CA-02, CA-03]

duration: 12min
completed: 2026-03-23
---

# Phase 03 Plan 01: Diff Reporting Summary

**Diff counts threaded from FileDiff through IndexStats to CLI/API output with live change detection in status command**

## Performance

- **Duration:** 12 min
- **Started:** 2026-03-23T12:33:42Z
- **Completed:** 2026-03-23T12:45:43Z
- **Tasks:** 2
- **Files modified:** 7

## Accomplishments
- Extended IndexStats with 5 new fields (new_files, modified_files, deleted_files, unchanged_files, data_dir) and threaded diff counts through all 3 pipeline paths (incremental, full, no-changes)
- CLI now shows diff summary after indexing ("3 new, 1 modified, 0 deleted, 222 unchanged") and status command detects pending changes via live file diff
- API POST /index accepts force parameter and returns enriched IndexStats JSON with diff fields
- 12 new tests covering model fields, metadata round-trip, schema migration, old-schema compat, and all pipeline code paths

## Task Commits

Each task was committed atomically:

1. **Task 1: Extend IndexStats model, metadata schema, and pipeline diff threading** - `21dc104` (test, TDD RED) + `d17fd5b` (feat, TDD GREEN)
2. **Task 2: CLI output formatting, status change detection, and API force parameter** - `9d773ce` (feat)

## Files Created/Modified
- `backend/src/dotmd/core/models.py` - Added new_files, modified_files, deleted_files, unchanged_files, data_dir fields to IndexStats
- `backend/src/dotmd/storage/metadata.py` - Idempotent ALTER TABLE migration, updated _UPSERT_STATS, save_stats, get_stats for new columns
- `backend/src/dotmd/ingestion/pipeline.py` - diff_counts and data_dir threading through index, _full_index, _incremental_index, _ingest_and_finalize
- `backend/src/dotmd/cli.py` - Diff summary line in index command, pending changes in status command, @click.pass_context
- `backend/src/dotmd/api/service.py` - Live file diff in status() using stored data_dir
- `backend/src/dotmd/api/server.py` - force: bool = False on IndexRequest, threaded to service.index()
- `backend/tests/test_diff_reporting.py` - 12 tests for diff reporting through IndexStats, metadata, and pipeline

## Decisions Made
- Used idempotent ALTER TABLE with try/except OperationalError for schema migration -- simpler than version tracking, safe for concurrent opens
- No-changes short-circuit returns fresh diff counts (zeros + unchanged count) rather than stale stored values from previous run (Pitfall 3 from RESEARCH.md)
- Live file diff in DotMDService.status() uses stored data_dir to discover current files and run FileTracker.diff() without re-indexing

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree was based on older commit without Phase 2 changes; resolved with fast-forward merge from feat/sqlite-vec-backend
- No pip/python in system PATH; used main repo's venv with PYTHONPATH override pointing to worktree source

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- All CA-01, CA-02, CA-03 requirements complete
- IndexStats diff fields available for any future consumers (web UI, MCP, monitoring)
- 57 total tests passing (45 existing + 12 new)

## Self-Check: PASSED

All 7 files verified present. All 3 commits (21dc104, d17fd5b, 9d773ce) verified in history.

---
*Phase: 03-cli-api-polish*
*Completed: 2026-03-23*
