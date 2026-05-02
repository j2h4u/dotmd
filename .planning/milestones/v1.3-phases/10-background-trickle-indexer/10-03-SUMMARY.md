---
phase: 10-background-trickle-indexer
plan: 03
subsystem: ingestion, api
tags: [asyncio, watchdog, inotify, background-indexer, trickle, lifespan]

# Dependency graph
requires:
  - phase: 10-01
    provides: "FTS5SearchEngine with incremental add_chunks/remove_chunks"
  - phase: 10-02
    provides: "Settings with indexing_paths, indexing_exclude, trickle_pause_seconds, poll_interval_seconds; discover_files_multi()"
provides:
  - "TrickleIndexer class with background loop and watchdog filesystem watching"
  - "Per-file processing in thread pool (asyncio.to_thread)"
  - "Graceful shutdown via asyncio.Event with 120s timeout"
  - "FastAPI lifespan integration starting TrickleIndexer as asyncio.Task"
  - "DotMDService.trickle_indexer property accessor"
affects: [10-04]

# Tech tracking
tech-stack:
  added: []
  patterns: [asyncio-background-task-in-lifespan, watchdog-to-asyncio-bridge, thread-pool-for-sync-io]

key-files:
  created:
    - backend/src/dotmd/ingestion/trickle.py
  modified:
    - backend/src/dotmd/api/server.py
    - backend/src/dotmd/api/service.py

key-decisions:
  - "Per-file processing runs in thread pool via asyncio.to_thread to avoid blocking the event loop"
  - "Watchdog events bridged to asyncio via loop.call_soon_threadsafe into asyncio.Queue"
  - "2-second debounce on watchdog events to prevent duplicate processing of rapid file saves"
  - "120s graceful shutdown timeout to allow current file to finish before cancellation"

patterns-established:
  - "Watchdog-to-asyncio bridge: _MarkdownEventHandler uses loop.call_soon_threadsafe to enqueue paths"
  - "Background task lifecycle: asyncio.create_task in lifespan, asyncio.Event for shutdown signal"
  - "Thread pool for sync pipeline: asyncio.to_thread wraps synchronous per-file processing"

requirements-completed: [BGIDX-01, BGIDX-03]

# Metrics
duration: 4min
completed: 2026-03-28
---

# Phase 10 Plan 03: Trickle Indexer Core Summary

**Background trickle indexer processes unindexed files one at a time via asyncio.to_thread while FastAPI serves search queries, with watchdog inotify watching and hourly polling fallback**

## Performance

- **Duration:** 4 min
- **Started:** 2026-03-27T19:37:32Z
- **Completed:** 2026-03-27T19:41:24Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- TrickleIndexer class with two-phase lifecycle: backlog processing (newest mtime first) then watch mode
- Per-file processing through full pipeline (chunk, embed, FTS5, extract, graph, fingerprint) in thread pool
- Watchdog filesystem monitoring with debounced event handler bridging to asyncio queue
- Hourly polling fallback re-scans for files inotify may have missed
- FastAPI lifespan starts indexer as asyncio.Task, graceful shutdown with 120s timeout

## Task Commits

Each task was committed atomically:

1. **Task 1: Create TrickleIndexer class** - `a7a7944` (feat)
2. **Task 2: Integrate TrickleIndexer into FastAPI lifespan and service** - `8f3a3b2` (feat)

## Files Created/Modified
- `backend/src/dotmd/ingestion/trickle.py` - New: TrickleIndexer, TrickleState, _MarkdownEventHandler -- background indexer with backlog + watch mode
- `backend/src/dotmd/api/server.py` - Modified: _lifespan starts TrickleIndexer as asyncio.Task with shutdown_event
- `backend/src/dotmd/api/service.py` - Modified: creates TrickleIndexer, exposes via trickle_indexer property

## Decisions Made
- Per-file processing uses asyncio.to_thread to avoid blocking the event loop (per Pitfall 3 from research)
- Watchdog events bridged via loop.call_soon_threadsafe into an asyncio.Queue (thread-safe pattern from research Pattern 3)
- 2-second debounce on watchdog events prevents duplicate processing when editors do rapid save-then-write
- 120-second graceful shutdown timeout allows current file to finish; cancels if still running after timeout

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- Worktree was branched from main (missing Plan 01/02 changes); fast-forward merged feat/sqlite-vec-backend to get FTS5SearchEngine and config changes before starting implementation
- Python venv only exists in main repo; used PYTHONPATH override to point to worktree source for verification

## Known Stubs

None - all functionality fully wired.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- TrickleIndexer is ready for Plan 04 (status endpoint and CLI integration)
- TrickleState exposes indexed_count, total_files, files_per_hour, eta_minutes, current_file, status
- trickle_indexer property on DotMDService provides access from API layer

## Self-Check: PASSED

All 3 created/modified files exist on disk. Both task commits (a7a7944, 8f3a3b2) verified in git log. SUMMARY.md created.

---
*Phase: 10-background-trickle-indexer*
*Completed: 2026-03-28*
