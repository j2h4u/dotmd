---
phase: "28-application-source-provider-contract"
plan: "03"
subsystem: testing
tags: [fixtures, source-provider, read-unit-window, idempotency]
requires:
  - phase: "28-01"
    provides: provider protocol and payload models
  - phase: "28-02"
    provides: source-unit fingerprint helper
provides:
  - deterministic application source fixture provider
  - read_unit_window fixture coverage
  - replay idempotency test against SQLiteMetadataStore
affects: [phase-29-telegram-source-adapter]
tech-stack:
  added: []
  patterns: [test-only-fixture-provider, opaque-offset-cursors]
key-files:
  created:
    - backend/tests/ingestion/application_source_fixtures.py
  modified:
    - backend/tests/ingestion/test_application_source_provider.py
key-decisions:
  - "Fixture provider stays test-only; production source_provider.py remains protocol-only."
  - "Document-only sources use an implicit root SourceUnit fallback."
requirements-completed: ["R3", "R4", "R8"]
duration: 12 min
completed: 2026-05-07
---

# Phase 28 Plan 03: Fixture Provider Contract Summary

**Deterministic fixture provider proving export cursors, source-unit windows, implicit root fallback, and unchanged replay**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-07T17:52:00Z
- **Completed:** 2026-05-07T18:04:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `FixtureApplicationSourceProvider` with opaque `offset:<n>` cursors.
- Added implicit root unit helper for document-shaped sources.
- Covered neighboring message windows, unknown-unit errors, malformed cursors, invalid limits, and fingerprint replay idempotency.

## Task Commits

1. **Fixture provider tests** - `9639df2` (`test(28-03)`)

## Files Created/Modified

- `backend/tests/ingestion/application_source_fixtures.py` - Test-only provider and implicit-root helper.
- `backend/tests/ingestion/test_application_source_provider.py` - Fixture behavior and storage replay tests.

## Decisions Made

Kept all fixture classes and helpers under `backend/tests`; production code remains the minimal protocol and Pydantic payload boundary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `rg -n "FixtureApplicationSourceProvider|make_implicit_root_unit|telethon|mcp_telegram" backend/src/dotmd/ingestion/source_provider.py backend/tests/ingestion/application_source_fixtures.py` found only the test fixture/helper and no forbidden imports.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q` passed: 35 passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 04 could document the Phase 29 `mcp-telegram` payload boundary using tested provider semantics.

---
*Phase: 28-application-source-provider-contract*
*Completed: 2026-05-07*
