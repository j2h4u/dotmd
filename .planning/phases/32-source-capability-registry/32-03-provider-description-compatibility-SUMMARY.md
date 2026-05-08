---
phase: 32-source-capability-registry
plan: 03
subsystem: source-provider
tags: [source-descriptors, provider-protocol, telegram, compatibility]
requires:
  - phase: 32-source-capability-registry
    provides: typed source descriptors and seed registry entries
provides:
  - descriptor-to-application-description bridge
  - legacy Telegram capability alias normalization
  - provider protocol compatibility coverage
affects: [telegram-source, application-source-provider, phase-33-lifecycle]
tech-stack:
  added: []
  patterns:
    - raw provider payload compatibility plus canonical normalized comparisons
key-files:
  created: []
  modified:
    - backend/src/dotmd/core/models.py
    - backend/tests/ingestion/test_source_registry.py
    - backend/tests/ingestion/test_application_source_provider.py
    - backend/tests/ingestion/test_telegram_provider.py
key-decisions:
  - "ApplicationSourceDescription keeps raw capability strings for current daemon compatibility."
  - "Capability comparisons should use normalized_capabilities() during the migration window."
  - "Provider protocol remains describe_source() -> ApplicationSourceDescription in Phase 32."
patterns-established:
  - "Descriptor-to-description conversion copies canonical SourceCapability.value strings."
  - "Legacy daemon aliases are centralized in LEGACY_CAPABILITY_ALIASES."
requirements-completed: ["SRC-01", "SRC-02"]
duration: 2min
completed: 2026-05-08
---

# Phase 32 Plan 03: Provider Description Compatibility Summary

**Descriptor-to-provider-description bridge with legacy Telegram capability normalization**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-08T13:37:15Z
- **Completed:** 2026-05-08T13:39:02Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added tests proving `telegram_source_descriptor()` can produce the current `ApplicationSourceDescription` shape.
- Added compatibility tests for current daemon strings `incremental-export` and `unit-window`.
- Added `ApplicationSourceDescription.from_descriptor()` to expose canonical descriptor capabilities as strings.
- Added `LEGACY_CAPABILITY_ALIASES` plus `normalized_capabilities()` so existing daemon payloads remain valid while comparisons use Phase 32 names.
- Preserved `ApplicationSourceProviderProtocol.describe_source() -> ApplicationSourceDescription` and the Telegram provider's current daemon payload construction.

## Task Commits

1. **Task 1: Test descriptor compatibility with existing provider descriptions** - `0fc446b` (test)
2. **Task 2: Add descriptor-to-description bridge without changing runtime protocol** - `d053e97` (feat)

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - Descriptor bridge and legacy capability alias normalization.
- `backend/tests/ingestion/test_source_registry.py` - Descriptor-to-description conversion test.
- `backend/tests/ingestion/test_application_source_provider.py` - Legacy capability validation and normalization tests.
- `backend/tests/ingestion/test_telegram_provider.py` - Telegram daemon capability normalization coverage.

## Decisions Made

- Did not change the raw `capabilities: list[str]` field because daemon compatibility is part of the Phase 32 bridge.
- Did not make providers construct runtimes from registry descriptors; that remains Phase 33 lifecycle scope.
- Did not copy descriptor display metadata into `metadata_json`; `display_name` remains the top-level lightweight description field.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` - passed.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_source_registry.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The provider-description bridge is ready for the Phase 32 Airweave mapping docs and gives Phase 33 a canonical capability comparison path without forcing an immediate daemon contract change.

---
*Phase: 32-source-capability-registry*
*Completed: 2026-05-08*
