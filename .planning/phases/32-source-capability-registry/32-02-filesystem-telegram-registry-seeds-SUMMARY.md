---
phase: 32-source-capability-registry
plan: 02
subsystem: source-registry
tags: [filesystem, telegram, descriptors, source-registry]
requires:
  - phase: 32-source-capability-registry
    provides: typed source descriptor contract
provides:
  - filesystem source descriptor seed
  - Telegram source descriptor seed
  - default source registry factory
affects: [filesystem-source, telegram-source, phase-33-lifecycle]
tech-stack:
  added: []
  patterns:
    - declarative source descriptor builders
    - default registry factory with filesystem and Telegram seeds
key-files:
  created:
    - backend/src/dotmd/ingestion/source_registry.py
  modified:
    - backend/tests/ingestion/test_source_registry.py
key-decisions:
  - "Filesystem is registered as a first-class source while local paths remain internal holder mechanics."
  - "Telegram auth is delegated to mcp-telegram and dotMD does not become a direct Telegram API client."
  - "Filesystem and Telegram seed descriptors expose exact Phase 32 capability sets."
patterns-established:
  - "Seed descriptors live in ingestion/source_registry.py and remain declarative."
  - "Default registry creation registers filesystem and Telegram descriptors only for Phase 32."
requirements-completed: ["SRC-02", "SRC-03"]
duration: 2min
completed: 2026-05-08
---

# Phase 32 Plan 02: Filesystem And Telegram Registry Seeds Summary

**Default source registry with detailed filesystem and Telegram descriptor seeds**

## Performance

- **Duration:** 2 min
- **Started:** 2026-05-08T13:35:20Z
- **Completed:** 2026-05-08T13:37:14Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added tests requiring the Phase 32 default registry to expose exactly `filesystem` and `telegram`.
- Added a filesystem descriptor with `paths` and `exclude` config schema fields, no auth, fingerprint cursor semantics, and local/materialization/browse capabilities.
- Added a Telegram descriptor with delegated `mcp-telegram` auth, optional `socket_path`, provider checkpoint cursors, and local/read-window/incremental/federated-search capabilities.
- Verified existing filesystem and Telegram provider tests still pass.

## Task Commits

1. **Task 1: Add default registry seed tests** - `9059cf7` (test)
2. **Task 2: Implement default source registry seeds** - `797aeea` (feat)

## Files Created/Modified

- `backend/src/dotmd/ingestion/source_registry.py` - Descriptor builders and `default_source_registry()`.
- `backend/tests/ingestion/test_source_registry.py` - Default registry, filesystem descriptor, and Telegram descriptor assertions.

## Decisions Made

- The filesystem descriptor uses `source_kind="local_filesystem"` and keeps Markdown parser details in `metadata_json`.
- The Telegram descriptor uses `auth_kind="delegated"` with `delegated_to="mcp-telegram"` and does not import Telegram runtime libraries.
- Telegram includes `federated_search` as a marker capability for later unified search work, without implementing that runtime path in Phase 32.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py -q` - passed.
- `cd backend && uv run pyright src/dotmd/ingestion/source_registry.py tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py` - passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Filesystem and Telegram now have declarative registry entries for the compatibility bridge in Plan 32-03 and the Airweave mapping docs in Plan 32-04.

---
*Phase: 32-source-capability-registry*
*Completed: 2026-05-08*
