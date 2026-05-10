---
phase: 36-telegram-unified-sync-and-federated-search
plan: "02"
subsystem: ingestion
tags: [asyncio, telegram, polling, lifespan, mcp_server, config, tdd]

# Dependency graph
requires:
  - phase: 36-01
    provides: rebound_units in ApplicationSourceIngestResult, TG-03/TG-04 anchors
  - phase: 33
    provides: SourceRuntimeFactory with build_if_configured("telegram")
  - phase: 28
    provides: ingest_application_source_runtime pipeline method

provides:
  - telegram_sync_interval_seconds Settings field with DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS env var
  - _run_telegram_poller async coroutine in mcp_server.py (D-LOCAL-SERIALIZED via run_in_executor)
  - Telegram polling task wired into _server_lifespan (conditional on build_if_configured)
  - Clean 30s shutdown with cancel+suppress on timeout

affects:
  - mcp_server.py _server_lifespan (Telegram task lifecycle alongside trickle indexer)
  - config.py Settings (new telegram_sync_interval_seconds field)

# Tech tracking
tech-stack:
  added: []
  patterns:
    - Background polling coroutine using asyncio.wait_for(shutdown_event.wait(), timeout=interval) for interruptible sleep
    - D-LOCAL-SERIALIZED: pipeline write path dispatched via loop.run_in_executor(_local_executor) not asyncio.to_thread
    - Conditional task creation: telegram_task only starts when build_if_configured returns non-None
    - 30s Telegram shutdown timeout (vs 120s for trickle indexer — poller exits at next interval boundary)

key-files:
  created:
    - backend/tests/test_telegram_sync.py
    - .planning/phases/36-telegram-unified-sync-and-federated-search/deferred-items.md
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/mcp_server.py
    - backend/tests/api/test_phase34_gaps.py
    - backend/tests/api/test_telegram_federated_read.py

key-decisions:
  - "D-LOCAL-SERIALIZED honored: _run_telegram_poller uses loop.run_in_executor(_local_executor) not asyncio.to_thread for pipeline write path"
  - "Telegram task shutdown timeout is 30s (not 120s like trickle) — poller exits at next sleep boundary, much faster"
  - "telegram_bundle built once at startup via build_if_configured; not rebuilt per-poll (lifecycle factory contract)"
  - "PYTHONPATH override required to run tests against worktree source (venv editable install points to main repo)"

patterns-established:
  - "Interruptible async sleep: await asyncio.wait_for(shutdown_event.wait(), timeout=interval) with TimeoutError suppressed"
  - "Conditional background task: create only when source bundle is configured, guard shutdown with is not None check"

requirements-completed:
  - TG-01
  - TG-02

# Metrics
duration: 8min
completed: 2026-05-10
---

# Phase 36 Plan 02: Telegram Auto-Sync Polling Task Summary

**`_run_telegram_poller` coroutine wired into `_server_lifespan` — Telegram ingestion now runs automatically every 300s via `loop.run_in_executor(_local_executor)` with clean shutdown**

## Performance

- **Duration:** ~8 min
- **Started:** 2026-05-10T18:09:31Z
- **Completed:** 2026-05-10T18:17:52Z
- **Tasks:** 4 (RED, CONFIG, GREEN, VERIFY)
- **Files modified:** 6

## Accomplishments

- `telegram_sync_interval_seconds: float = 300.0` added to `Settings` with `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS` env override
- `_run_telegram_poller` async coroutine calls `ingest_application_source_runtime` via `loop.run_in_executor(_local_executor)` — respects D-LOCAL-SERIALIZED, no asyncio.to_thread in write path
- Polling task created at server startup only when `build_if_configured("telegram")` returns a bundle; skipped otherwise
- Shutdown: `await asyncio.wait_for(telegram_task, timeout=30)` with cancel+suppress on timeout, before trickle indexer wait
- 2 pre-existing test bugs fixed (Rule 1): `hits` key alignment from 36-01 and wrong exception type expectation

## Task Commits

Each task committed atomically:

1. **Task RED: Failing tests for config field and poller interface** - `8304715` (test)
2. **Task CONFIG: Add telegram_sync_interval_seconds + fix 2 pre-existing test bugs** - `f636a7f` (feat)
3. **Task GREEN: _run_telegram_poller + lifespan wiring + expanded behavioral test** - `79ed82f` (feat)
4. **Task VERIFY: Wiring/executor/shutdown verification + deferred-items.md** - `662f11f` (test)

## Files Created/Modified

- `backend/tests/test_telegram_sync.py` — TDD tests: config field presence + poller behavioral contract
- `backend/src/dotmd/core/config.py` — Added `telegram_sync_interval_seconds: float = 300.0`
- `backend/src/dotmd/mcp_server.py` — Added `_run_telegram_poller` + lifespan wiring
- `backend/tests/api/test_phase34_gaps.py` — Fixed `_FakeClient` to return `hits` key (36-01 changed telegram_provider)
- `backend/tests/api/test_telegram_federated_read.py` — Fixed to expect `RuntimeError` not `ConnectionError` (service wraps)
- `.planning/phases/36-telegram-unified-sync-and-federated-search/deferred-items.md` — Pre-existing failure logged

## Decisions Made

- `loop.run_in_executor(_local_executor)` chosen over `asyncio.to_thread` per D-LOCAL-SERIALIZED constraint — pipeline writes must stay serialized on the dedicated thread pool
- Telegram shutdown timeout 30s (vs trickle's 120s): the poller sleeps `interval_seconds` between runs and exits at the next sleep boundary, so 30s is ample even at the default 300s interval (the `shutdown_event.wait()` wakes immediately)
- `telegram_bundle` is built once at startup by `build_if_configured` — the lifecycle factory owns credential and cursor setup; re-building per poll would bypass the factory contract

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_phase34_gaps.py _FakeClient response key**
- **Found during:** Task CONFIG (full suite run with worktree PYTHONPATH)
- **Issue:** 36-01 changed `telegram_provider.py` to use `hits` key instead of `messages`; `_FakeClient.search_messages()` still returned `messages`, causing `tg_candidates` to be empty
- **Fix:** Updated `_FakeClient` to return `{"hits": [...]}` matching the current provider contract
- **Files modified:** `backend/tests/api/test_phase34_gaps.py`
- **Verification:** Test passes after fix; confirmed same failure in main repo
- **Committed in:** `f636a7f` (Task CONFIG commit)

**2. [Rule 1 - Bug] Fixed test_telegram_federated_read.py exception expectation**
- **Found during:** Task CONFIG (full suite run)
- **Issue:** Test expected `ConnectionError` to propagate from `service.read()`, but `_read_telegram_message` wraps all exceptions in `RuntimeError("Telegram provider error: ...")`; test had been broken at the base commit
- **Fix:** Changed `pytest.raises(ConnectionError)` to `pytest.raises(RuntimeError, match="Telegram provider error")`
- **Files modified:** `backend/tests/api/test_telegram_federated_read.py`
- **Verification:** Test passes after fix
- **Committed in:** `f636a7f` (Task CONFIG commit)

---

**Total deviations:** 2 auto-fixed (both Rule 1 - pre-existing bugs exposed by worktree test run)
**Impact on plan:** Both fixes correct existing test contracts. No scope creep. Plan implementation was clean.

## Issues Encountered

**Worktree PYTHONPATH:** The venv editable install (`_editable_impl_dotmd.pth`) points to the main repo's `backend/src`, not the worktree's. Tests run via the venv without a `PYTHONPATH` override load the unmodified main repo source, making all worktree source changes invisible to the test runner. Fixed by running all tests with `PYTHONPATH=/path/to/worktree/backend/src` prefix.

**Pre-existing test failure:** `tests/cli/test_search_output.py::TestRefRendering::test_renders_ref` fails with `SourceLifecycleConfigError("filesystem.paths is required")` in the CLI test environment. This predates Phase 36 (confirmed failing in main repo at the same base commit). Logged to `deferred-items.md`; excluded from VERIFY suite run with `--ignore`.

## Known Stubs

None — `_run_telegram_poller` is fully wired. The `telegram_task` is only `None` when Telegram is not configured (correct behavior).

## Threat Flags

None — no new network endpoints, auth paths, or trust boundary changes. The poller calls the existing `ingest_application_source_runtime` pipeline method via the existing `_local_executor` thread pool. No new external connectivity introduced.

## TDD Gate Compliance

- RED gate: `8304715` `test(36): RED — telegram sync config and poller interface missing`
- GREEN gate: `79ed82f` `feat(36): implement _run_telegram_poller and wire into _server_lifespan`
- REFACTOR: not required (implementation was clean on first pass)

## Next Phase Readiness

- Telegram auto-sync is operational: starts at server boot if `DOTMD_TELEGRAM_DAEMON_SOCKET` is set, polls every 300s (configurable), shuts down cleanly
- No blockers for Phase 36 completion

---
*Phase: 36-telegram-unified-sync-and-federated-search*
*Completed: 2026-05-10*
