---
phase: "28-application-source-provider-contract"
plan: "04"
subsystem: docs
tags: [mcp-telegram, source-contract, architecture, checkpoint-cursor]
requires:
  - phase: "28-01"
    provides: provider protocol and payload models
  - phase: "28-02"
    provides: checkpoint and fingerprint storage semantics
  - phase: "28-03"
    provides: fixture proof of provider behavior
provides:
  - mcp-telegram source contract note
  - Phase 28 architecture documentation
affects: [phase-29-telegram-source-adapter]
tech-stack:
  added: []
  patterns: [contract-note-before-adapter-implementation]
key-files:
  created:
    - docs/mcp-telegram-source-contract.md
    - .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md
  modified:
    - docs/source-adapter-architecture.md
    - docs/architecture.md
key-decisions:
  - "dotMD consumes structured mcp-telegram provider payloads and does not read private SQLite tables."
  - "Phase 28 explicitly excludes direct Telegram API ownership, attachments/media, lifecycle deletes, and plugin marketplace work."
requirements-completed: ["R3", "R4", "R8"]
duration: 21 min
completed: 2026-05-07
---

# Phase 28 Plan 04: Docs and Telegram Contract Note Summary

**mcp-telegram provider payload contract and architecture updates for Phase 29 planning**

## Performance

- **Duration:** 21 min
- **Started:** 2026-05-07T18:04:00Z
- **Completed:** 2026-05-07T18:25:00Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Created `docs/mcp-telegram-source-contract.md` with strict JSON examples for source description, export changes, and read windows.
- Updated architecture docs with Phase 28 delivered state, minimal provider methods, cursor semantics, source-unit recomputation boundary, and deferred lifecycle scope.
- Documented that Phase 28 requires no `dotmd index --force`, no full reindex, and no rebuild.

## Task Commits

1. **Docs and contract note** - pending docs commit after this summary is staged.

## Files Created/Modified

- `docs/mcp-telegram-source-contract.md` - Concrete Phase 29 contract boundary.
- `docs/source-adapter-architecture.md` - Phase 28 delivered state and updated source-state model.
- `docs/architecture.md` - Future source adapters section updated for Phase 28.
- `.planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` - Verification record.

## Decisions Made

The `mcp-telegram` contract note is an implementation contract for Phase 29 planning, not a Telegram ingestion claim. dotMD must not import Telethon, instantiate a Telegram API client, or read private `mcp-telegram` SQLite tables.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `python` was not available on PATH for JSON validation. Re-ran through `cd backend && uv run python ...`, which validated 3 JSON examples.
- `just lint` initially found import ordering in `tests/ingestion/test_application_source_provider.py`; fixed with `ruff check --fix`.
- `just typecheck` initially reported one new pyright error from an intentional Pydantic missing-field validation call; changed the test to pass a payload dict. Final typecheck passed and improved the ratchet.

## Verification

- `rg "checkpoint_cursor|read_unit_window|SourceDocument|SourceUnit|private .*SQLite|no direct Telegram API client" docs/mcp-telegram-source-contract.md` passed.
- `rg "Phase 28|checkpoint_cursor|read_unit_window|mcp-telegram-source-contract|no dotmd index --force" docs/source-adapter-architecture.md docs/architecture.md .planning/phases/28-application-source-provider-contract/28-04-SUMMARY.md` passed after summary creation.
- JSON examples: `cd backend && uv run python ...` validated 3 JSON examples.
- `just typecheck` passed: pyright ratchet 66 errors, baseline 69, improvements -3 across 2 files.
- `just lint` passed: all checks passed.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q` passed: 94 passed, 45 warnings.

## Self-Check: PASSED

All required grep checks passed, JSON examples are valid, no new type/lint/test failures remain, and no `dotmd index --force` or full rebuild was run.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 29 can plan the actual Telegram source adapter against a tested provider protocol, durable source-state helpers, deterministic fixtures, and a concrete mcp-telegram payload boundary.

---
*Phase: 28-application-source-provider-contract*
*Completed: 2026-05-07*
