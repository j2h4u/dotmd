---
phase: "28-application-source-provider-contract"
plan: "01"
subsystem: ingestion
tags: [source-provider, pydantic, protocol, source-unit]
requires: []
provides:
  - generic application source payload models
  - application source provider protocol
  - required SourceUnit updated_at field
affects: [phase-29-telegram-source-adapter]
tech-stack:
  added: []
  patterns: [pydantic-payload-models, protocol-first-provider-contract]
key-files:
  created:
    - backend/src/dotmd/ingestion/source_provider.py
    - backend/tests/ingestion/test_application_source_provider.py
  modified:
    - backend/src/dotmd/core/models.py
key-decisions:
  - "Application sources expose describe_source, export_changes, and read_unit_window only."
  - "SourceUnit.updated_at is required and source-unit windows are modeled explicitly."
requirements-completed: ["R3", "R4", "R8"]
duration: 12 min
completed: 2026-05-07
---

# Phase 28 Plan 01: Provider Models and Protocol Summary

**Generic application-source payload models and protocol for document/unit exports and neighboring source-unit reads**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-07T17:26:00Z
- **Completed:** 2026-05-07T17:38:00Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `ApplicationSourceDescription`, `ApplicationSourceChange`, `ApplicationSourceChangeBatch`, and `SourceUnitWindow`.
- Made `SourceUnit.updated_at` required while preserving `unit_type` and `chunking_hints`.
- Added `ApplicationSourceProviderProtocol` with the exact generic method set.

## Task Commits

1. **Provider models and protocol** - `3552523` (`feat(28-01)`)

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - Provider payload models and source-unit window model.
- `backend/src/dotmd/ingestion/source_provider.py` - Protocol-only provider contract.
- `backend/tests/ingestion/test_application_source_provider.py` - Telegram-like contract tests.

## Decisions Made

Used source-neutral model names and kept Telegram only in tests/examples. No `export_documents`, `export_units`, Telegram provider class, or direct Telegram import was added to production code.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `rg -n "SourceUnit\\(" backend/src backend/tests` found only the class definition and new tests.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q` passed: 62 passed, 45 warnings.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 02 could add durable checkpoint and fingerprint state against the new `SourceUnit` model.

---
*Phase: 28-application-source-provider-contract*
*Completed: 2026-05-07*
