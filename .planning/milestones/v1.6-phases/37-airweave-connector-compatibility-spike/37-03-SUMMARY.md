---
phase: 37-airweave-connector-compatibility-spike
plan: 37-03
subsystem: ingestion
tags: [gmail, source-registry, source-lifecycle, settings, oauth]
requires:
  - phase: 37-01
    provides: Vendored Airweave Gmail slice and token shim
  - phase: 37-02
    provides: GmailApplicationSourceProvider and GmailBridge
provides:
  - Gmail SourceDescriptor registered in default source registry
  - GmailSourceConfig in lifecycle SourceConfig union
  - SourceRuntimeFactory.build("gmail") runtime bundle branch
  - Settings-backed DOTMD_GMAIL_* activation path with partial-config warning
affects: [37-04-airweave-compatibility-report-and-tests]
tech-stack:
  added: []
  patterns: [registry-lifecycle-source-wiring, env-backed-federated-source]
key-files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/source_registry.py
    - backend/src/dotmd/ingestion/source_lifecycle.py
    - backend/src/dotmd/core/config.py
    - backend/tests/test_gmail_bridge.py
key-decisions:
  - "Gmail uses the same SourceRegistry and SourceRuntimeFactory path as filesystem and Telegram."
  - "Gmail build bypasses DefaultSourceCredentialProvider.get_access because auth_kind=oauth_refresh is managed by GmailOAuthTokenProvider."
  - "Refresh tokens live on GmailSourceConfig, not SourceAccess.delegated_to."
patterns-established:
  - "Optional federated sources seed config from Settings only when their required env var set is complete."
  - "Partial source env config logs missing var names and skips registration."
requirements-completed: [AIR-01, AIR-03]
duration: 20min
completed: 2026-05-13
---

# Phase 37 Plan 03 Summary

**Gmail registered through dotMD source registry and lifecycle factory with Settings-backed OAuth config**

## Performance

- **Duration:** 20 min
- **Started:** 2026-05-13T00:45:00Z
- **Completed:** 2026-05-13T01:05:00Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments

- Added `gmail_source_descriptor()` and registered it in `default_source_registry()` with `FEDERATED_SEARCH` and `READ_UNIT_WINDOW` only.
- Added `GmailSourceConfig`, included it in the lifecycle `SourceConfig` union, and implemented `SourceRuntimeFactory.build("gmail")`.
- Added `DOTMD_GMAIL_CLIENT_ID`, `DOTMD_GMAIL_CLIENT_SECRET`, `DOTMD_GMAIL_REFRESH_TOKEN`, and `DOTMD_GMAIL_SEARCH_RESULT_LIMIT` Settings fields.
- Seeded Gmail lifecycle config from complete Settings credentials and logged named warnings for partial Gmail env configuration.
- Removed the Phase 37-02 skip markers by implementing descriptor, lifecycle missing-config, build-if-configured, config validation, union, and credential-provider bypass tests.

## Task Commits

1. **Tasks 1-4: Descriptor, lifecycle config, Settings activation, and tests** - `1ce8bd0` (feat)

## Files Created/Modified

- `backend/src/dotmd/ingestion/source_registry.py` - Gmail descriptor and default registry entry.
- `backend/src/dotmd/ingestion/source_lifecycle.py` - Gmail config model, runtime build branch, config seeding, and partial env warning.
- `backend/src/dotmd/core/config.py` - Gmail Settings env fields.
- `backend/tests/test_gmail_bridge.py` - Registry/lifecycle/config tests replacing 37-02 skip placeholders.

## Decisions Made

- Used `SourceAccess(kind="none")` in the Gmail build branch because the refresh token is already held by `GmailSourceConfig`; there is no delegated credential chain.
- Kept Gmail optional: no env vars means no bundle and no warning; partial env vars produce a named warning and no bundle.
- Used a normal union assignment for `SourceConfig` instead of Python 3.12 `type` alias syntax so `typing.get_args(SourceConfig)` exposes `GmailSourceConfig` to the verification tests.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Made SourceConfig inspectable by verification**
- **Found during:** Task 4 verification
- **Issue:** Python 3.12 `type SourceConfig = ...` creates a `TypeAliasType`; `typing.get_args(SourceConfig)` returned `()`, failing the planned verification.
- **Fix:** Switched to `SourceConfig = FilesystemSourceConfig | TelegramSourceConfig | GmailSourceConfig`, preserving runtime semantics and making the union inspectable.
- **Files modified:** `backend/src/dotmd/ingestion/source_lifecycle.py`
- **Verification:** Direct `typing.get_args(SourceConfig)` check passed.
- **Committed in:** `1ce8bd0`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** Verification-compatible representation only; Gmail remains in the SourceConfig union.

## Issues Encountered

- `uv run python -m pytest tests/ -x -q` again executed 119 passing tests and then exited nonzero because the local dotMD MCP server was not reachable at `http://localhost:8080`.

## User Setup Required

Production Gmail activation expects `DOTMD_GMAIL_CLIENT_ID`, `DOTMD_GMAIL_CLIENT_SECRET`, and `DOTMD_GMAIL_REFRESH_TOKEN` to be loaded into the container environment, normally through `~/.secrets/dotmd-gmail.env` via docker-compose `env_file`.

## Verification

- `uv run python -m pytest tests/test_gmail_bridge.py tests/test_vendor_airweave_import.py -v` — 35 passed.
- `uv run python -m pytest tests/test_gmail_bridge.py tests/ingestion/test_source_lifecycle.py -q` — 40 passed.
- Direct registry check confirmed filesystem, Telegram, and Gmail descriptors are registered.
- Direct SourceConfig union check confirmed `GmailSourceConfig` is included.
- Direct `SourceRuntimeFactory.build("gmail")` check confirmed `access.kind == "none"` and provider construction.
- Broad backend test body: 119 passed, 1 skipped before MCP reachability exit.

## Self-Check: PASSED

## Next Phase Readiness

Plan 37-04 can write the compatibility report from actual implementation evidence and run final phase-level verification.

---
*Phase: 37-airweave-connector-compatibility-spike*
*Completed: 2026-05-13*
