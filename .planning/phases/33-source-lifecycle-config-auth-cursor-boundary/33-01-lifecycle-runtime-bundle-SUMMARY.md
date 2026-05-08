---
phase: 33-source-lifecycle-config-auth-cursor-boundary
plan: "01"
subsystem: ingestion
tags: [source-lifecycle, source-registry, credentials, cursors, pydantic, sqlite]

requires:
  - phase: 32-source-capability-registry
    provides: declarative filesystem and Telegram source descriptors
provides:
  - Importable source runtime factory and inspectable runtime bundle
  - Typed local source config records with credential references separated from config
  - Delegated credential/access provider boundary for Telegram
  - SQLite cursor-store wrapper preserving caller-owned checkpoint transactions
affects: [source-lifecycle, filesystem-unification, telegram-unification, connector-compatibility]

tech-stack:
  added: []
  patterns:
    - Pydantic strict config models for lifecycle-owned source runtime config
    - Protocol-based config, credential, and cursor store boundaries
    - Runtime bundle factory consuming declarative SourceRegistry descriptors

key-files:
  created:
    - backend/src/dotmd/ingestion/source_lifecycle.py
    - backend/tests/ingestion/test_source_lifecycle.py
  modified: []

key-decisions:
  - "Lifecycle construction returns an inspectable SourceRuntimeBundle rather than a bare provider/source object."
  - "Telegram access remains delegated to mcp-telegram through SourceAccess; dotMD stores typed config and credential references only."
  - "SQLiteSourceCursorStore requires caller-provided conn for checkpoint commits, preserving transaction-owned cursor persistence."

patterns-established:
  - "Airweave-lite construction boundary: descriptor plus typed config plus access plus cursor store plus runtime object."
  - "Optional source startup can use build_if_configured(namespace) while direct build(namespace) fails fast on missing required config."

requirements-completed: ["LIFE-01", "LIFE-02", "LIFE-03"]

duration: 3 min
completed: 2026-05-08
---

# Phase 33 Plan 01: Lifecycle Runtime Bundle Contract Summary

**Typed source lifecycle factory builds inspectable filesystem and Telegram runtime bundles with delegated access and transaction-owned cursor commits.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-08T15:07:38Z
- **Completed:** 2026-05-08T15:11:06Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added lifecycle contract tests first, covering filesystem and Telegram bundle construction, fail-fast config errors, config/credential separation, optional Telegram startup, and cursor rollback behavior.
- Implemented `source_lifecycle.py` with strict typed source configs, `SourceConfigRecord`, credential/access provider protocol, `DefaultSourceCredentialProvider`, `SQLiteSourceCursorStore`, `SourceRuntimeBundle`, and `SourceRuntimeFactory`.
- Preserved Phase 33 boundaries: no call-site migration, no Airweave runtime dependency, no direct Telegram API client, and no raw credential storage.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add lifecycle contract tests first** - `9b443e5` (test)
2. **Task 2: Implement lifecycle factory, config store, credential provider, and cursor store** - `f29ef79` (feat)

**Plan metadata:** committed separately after this summary.

## Files Created/Modified

- `backend/tests/ingestion/test_source_lifecycle.py` - Contract tests for runtime bundles, config failures, credential separation, optional Telegram build, and cursor transaction ownership.
- `backend/src/dotmd/ingestion/source_lifecycle.py` - Source lifecycle factory, config store, delegated access provider, SQLite cursor store wrapper, and runtime bundle types.

## Decisions Made

- Followed the plan's Airweave-lite boundary: lifecycle assembles existing dotMD filesystem and Telegram runtime pieces rather than importing or copying Airweave runtime code.
- Kept config and access inspectable on the runtime bundle so future filesystem and Telegram integration plans can assert the boundary directly.
- Required `conn=` for `SQLiteSourceCursorStore.commit_checkpoint()` so lifecycle-mediated checkpoints cannot commit outside the caller's persistence transaction.

## TDD Gate Compliance

- **RED:** `9b443e5` added lifecycle contract tests; `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q` failed with `ModuleNotFoundError: No module named 'dotmd.ingestion.source_lifecycle'`.
- **GREEN:** `f29ef79` implemented the lifecycle module; focused pytest and pyright checks passed.
- **REFACTOR:** No separate refactor commit was needed.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py -q` -> `31 passed`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py` -> `0 errors, 0 warnings, 0 informations`
- `rg -n "from airweave|import airweave|Telethon|telegram\.client|sqlite.*telegram" backend/src/dotmd/ingestion/source_lifecycle.py backend/tests/ingestion/test_source_lifecycle.py` -> no matches

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for subsequent Phase 33 plans to migrate filesystem and Telegram call sites onto the lifecycle boundary.

## Self-Check: PASSED

- Found `backend/src/dotmd/ingestion/source_lifecycle.py`
- Found `backend/tests/ingestion/test_source_lifecycle.py`
- Found commit `9b443e5`
- Found commit `f29ef79`

---
*Phase: 33-source-lifecycle-config-auth-cursor-boundary*
*Completed: 2026-05-08*
