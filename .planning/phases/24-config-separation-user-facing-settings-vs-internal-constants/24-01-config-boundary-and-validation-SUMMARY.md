---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
plan: 01-config-boundary-and-validation
subsystem: config
tags: [settings, runtime-validation, indexing, mcp, fastapi]

requires:
  - phase: 24-config-separation-user-facing-settings-vs-internal-constants
    provides: Phase context and config-boundary decisions
provides:
  - Settings runtime validation for long-running server startup
  - Internal default constants for tuning and built-in indexing excludes
  - Effective indexing excludes with additive operator extras
  - Regression tests for config separation and runtime validation
affects: [config, indexing, mcp-runtime, fastapi-runtime]

tech-stack:
  added: []
  patterns:
    - Single Settings surface with explicit runtime validation helper
    - Built-in defaults as module constants feeding compatibility fields
    - Effective exclude property for call-site consumption

key-files:
  created:
    - .planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/deferred-items.md
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/ingestion/trickle.py
    - backend/src/dotmd/api/server.py
    - backend/src/dotmd/mcp_server.py
    - backend/tests/core/test_config_separation.py

key-decisions:
  - "Keep Settings as the public config surface and add validate_for_runtime() instead of environment profiles."
  - "Keep indexing_exclude as legacy replace-only config, add indexing_extra_exclude for additive operator patterns, and route call sites through effective_indexing_exclude."
  - "Use load_runtime_settings() only for long-running server startup paths; short-lived CLI commands continue to use load_settings()."

patterns-established:
  - "Runtime validation belongs at server startup boundaries, not normal Settings construction."
  - "Built-in indexing excludes live in DEFAULT_INDEXING_EXCLUDE and are consumed through effective_indexing_exclude."

requirements-completed: []

duration: 8 min
completed: 2026-05-05
---

# Phase 24 Plan 01: Config Boundary and Validation Summary

**Single Settings surface with named internal defaults, runtime startup validation, and effective indexing excludes that preserve built-in ignores.**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-05T15:55:26Z
- **Completed:** 2026-05-05T16:03:25Z
- **Tasks:** 3
- **Files modified:** 7

## Accomplishments

- Added focused RED/GREEN regression coverage for config constants, runtime validation, FalkorDB default safety, optional `base_url=None`, and additive indexing excludes.
- Added `DEFAULT_INDEXING_EXCLUDE`, `DEFAULT_FALKORDB_URL`, tuning default constants, `indexing_extra_exclude`, `effective_indexing_exclude`, `validate_for_runtime()`, and `load_runtime_settings()`.
- Migrated indexing discovery/watch call sites to effective excludes and long-running MCP/FastAPI server startup paths to runtime-validated settings.

## Task Commits

1. **Task 1: Add config separation constants and runtime validation tests** - `1275015` (test)
2. **Task 2: Implement the Settings boundary and effective defaults** - `a95e2aa` (feat)
3. **Task 3: Migrate call sites to effective excludes and runtime settings where appropriate** - `e1bab28` (feat)

**Plan metadata:** pending

## Files Created/Modified

- `backend/src/dotmd/core/config.py` - Added default constants, effective excludes, runtime validation, and runtime settings helper.
- `backend/src/dotmd/api/service.py` - Uses `effective_indexing_exclude` for live status change discovery.
- `backend/src/dotmd/ingestion/trickle.py` - Uses `effective_indexing_exclude` for orphan cleanup, backlog discovery, and watchdog filtering.
- `backend/src/dotmd/api/server.py` - Uses `load_runtime_settings()` for FastAPI lifespan startup.
- `backend/src/dotmd/mcp_server.py` - Uses `load_runtime_settings()` for stdio and streamable-HTTP MCP startup; exposes `init_service()` with `_init_for_stdio` compatibility alias.
- `backend/tests/core/test_config_separation.py` - Covers the config-boundary contract and consumed call boundaries.
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/deferred-items.md` - Records direct-pyright baseline errors outside this plan.

## Decisions Made

- Runtime validation is explicit and opt-in through `load_runtime_settings()`, so local unit construction with `Settings(...)` and `load_settings(...)` stays lightweight.
- `graph_backend="falkordb"` rejects empty `falkordb_url` and the unsafe Python default `redis://localhost:6379`; LadybugDB still accepts an empty/default FalkorDB URL because it does not use it.
- `indexing_exclude` keeps legacy replace-only semantics, while `indexing_extra_exclude` is additive and call sites consume the de-duplicated effective list.

## Deviations from Plan

### Auto-fixed Issues

None - plan implementation followed the planned behavior.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No behavior scope was added beyond applying runtime validation to the long-running FastAPI serving path identified during Task 3 inspection.

## Issues Encountered

- The exact direct command `cd backend && uv run pyright src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` reports 21 pre-existing type errors in `service.py` and `trickle.py`. This is outside the config-boundary change and is recorded in `deferred-items.md`.
- The repository ratchet gate passes unchanged: `just typecheck` reports `pyright ratchet: 76 errors (baseline 76)`.

## Verification

- `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` - passed (`21 passed`).
- `cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q` - passed (`19 passed`).
- `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` - passed.
- `just typecheck` - passed against the checked-in ratchet baseline.
- Direct `uv run pyright ...` - failed on pre-existing baseline errors as noted above.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 24-02 to align startup/docs/templates with the new config boundary and runtime validation behavior.

## Self-Check: PASSED

- Key modified files exist.
- Task commits exist in git history: `1275015`, `a95e2aa`, `e1bab28`.
- Verification commands were run; only the known direct-pyright baseline issue remains deferred.

---
*Phase: 24-config-separation-user-facing-settings-vs-internal-constants*
*Completed: 2026-05-05*
