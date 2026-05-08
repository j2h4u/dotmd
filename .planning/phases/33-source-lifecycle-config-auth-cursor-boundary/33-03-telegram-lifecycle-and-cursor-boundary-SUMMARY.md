---
phase: 33-source-lifecycle-config-auth-cursor-boundary
plan: "03"
subsystem: ingestion
tags: [source-lifecycle, telegram, cursors, mcp-telegram, tdd]

requires:
  - phase: 33-source-lifecycle-config-auth-cursor-boundary
    provides: lifecycle runtime factory, settings-derived filesystem wiring, and SQLite cursor store
provides:
  - Telegram service and CLI runtime construction through source lifecycle
  - Lifecycle cursor-store checkpoint reads, commits, and error recording for application-source ingest
  - Regression coverage for delegated Telegram auth and rollback-safe cursor commits
  - Phase 33 source lifecycle documentation updates
affects: [telegram-unification, source-lifecycle, connector-compatibility, source-ref-contract]

tech-stack:
  added: []
  patterns:
    - Lifecycle-built Telegram runtime bundles reused by service, CLI, and pipeline ingest
    - Cursor-store protocol used inside application-source transaction boundaries

key-files:
  created:
    - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-03-telegram-lifecycle-and-cursor-boundary-SUMMARY.md
  modified:
    - backend/src/dotmd/ingestion/source_lifecycle.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/cli.py
    - backend/tests/ingestion/test_source_lifecycle.py
    - backend/tests/ingestion/test_telegram_ingestion.py
    - backend/tests/api/test_service_search.py
    - docs/source-adapter-architecture.md
    - docs/source-registry-airweave-mapping.md

key-decisions:
  - "Telegram lifecycle config stores a delegated mcp-telegram credential reference, not raw Telegram secret material."
  - "DotMDService and dotmd telegram ingest obtain Telegram providers from SourceRuntimeFactory instead of direct construction."
  - "Application-source checkpoint reads, commits, and errors now flow through SourceCursorStoreProtocol while preserving caller-owned SQLite transactions."

patterns-established:
  - "Use SourceRuntimeBundle for application-source runtime handoff into pipeline ingest."
  - "Use build_if_configured(\"telegram\") for optional service startup and build(\"telegram\") after CLI socket validation."

requirements-completed: ["LIFE-01", "LIFE-02", "LIFE-03", "LIFE-04"]

duration: 10 min
completed: 2026-05-08
---

# Phase 33 Plan 03: Telegram Lifecycle And Cursor Boundary Summary

**Telegram service, CLI, and application-source checkpoint handling now route through the source lifecycle factory with delegated mcp-telegram access.**

## Performance

- **Duration:** 10 min
- **Started:** 2026-05-08T15:20:00Z
- **Completed:** 2026-05-08T15:30:04Z
- **Tasks:** 3
- **Files modified:** 10

## Accomplishments

- Added RED regression tests for Telegram lifecycle config seeding, raw secret rejection, service provider construction, delegated access, lifecycle cursor calls, and rollback-safe checkpoint behavior.
- Routed `DotMDService._build_telegram_provider()` and `dotmd telegram ingest` through lifecycle-built Telegram runtime bundles.
- Refactored application-source ingest so checkpoint reads, successful commits, and error recording use `SourceCursorStoreProtocol` while commits remain inside the existing SQLite transaction.
- Updated source architecture docs to record Phase 33 runtime bundles, delegated Telegram auth, cursor semantics, and the Airweave-lite runtime boundary.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add Telegram lifecycle and cursor boundary regression tests** - `a3034ee` (test)
2. **Task 2: Route Telegram service, CLI, and checkpoint access through lifecycle** - `437a6dc` (feat)
3. **Task 3: Document Phase 33 lifecycle boundary and run static source-boundary guards** - `0e55d8b` (docs)

**Plan metadata:** committed separately after this summary.

## Files Created/Modified

- `backend/src/dotmd/ingestion/source_lifecycle.py` - Seeds Telegram config with delegated `mcp-telegram` credential reference.
- `backend/src/dotmd/ingestion/pipeline.py` - Adds lifecycle runtime ingest and routes checkpoint access through cursor store protocol methods.
- `backend/src/dotmd/api/service.py` - Builds optional Telegram provider through `build_if_configured("telegram")`.
- `backend/src/dotmd/cli.py` - Builds `telegram ingest` runtime through lifecycle after socket validation.
- `backend/tests/ingestion/test_source_lifecycle.py` - Adds Telegram config, delegated access, and raw-secret rejection coverage.
- `backend/tests/ingestion/test_telegram_ingestion.py` - Adds lifecycle cursor-store usage and rollback regression coverage.
- `backend/tests/api/test_service_search.py` - Adds service lifecycle construction coverage and fixture isolation for required verification.
- `docs/source-adapter-architecture.md` - Records delivered Phase 33 source runtime bundles and cursor/auth boundary.
- `docs/source-registry-airweave-mapping.md` - Records the Airweave-lite runtime bundle/factory adaptation.

## Decisions Made

- Kept Telegram auth delegated to `mcp-telegram`; lifecycle stores only the credential reference and produces `SourceAccess(kind="delegated")`.
- Preserved `ingest_application_source(provider, ...)` as a compatibility entry point while adding `ingest_application_source_runtime(bundle, ...)` for lifecycle-mediated ingestion.
- Used narrow pyright casts for existing service protocol mismatches instead of changing search/reranker/storage interfaces during this plan.

## TDD Gate Compliance

- **RED:** `a3034ee` added failing tests; the plan pytest command failed because Telegram settings-derived lifecycle config did not seed the delegated `mcp-telegram` credential reference.
- **GREEN:** `437a6dc` implemented Telegram lifecycle integration; focused pytest and pyright passed.
- **REFACTOR:** No separate refactor commit was needed.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` -> `104 passed`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py` -> `0 errors`
- `rg -n "from airweave|import airweave" backend/src backend/tests` -> no matches
- `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests` -> no matches
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` -> no matches
- `rg -n "TelegramApplicationSourceProvider\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` -> no matches

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Aligned a service test fixture with lifecycle-required indexing paths**
- **Found during:** Task 2
- **Issue:** A service integration test constructed `Settings` without `indexing_paths`, which now correctly prevents filesystem lifecycle construction.
- **Fix:** Added `indexing_paths=[str(data_dir)]` to the fixture settings.
- **Files modified:** `backend/tests/api/test_service_search.py`
- **Verification:** Focused pytest command exits 0.
- **Committed in:** `437a6dc`

**2. [Rule 3 - Blocking] Isolated a CLI logging side effect in the service test suite**
- **Found during:** Task 2
- **Issue:** The CLI test configured dotMD logging against a `CliRunner` stream that later closed, causing a required service `caplog` assertion to miss the warning.
- **Fix:** Cleared the dotMD logger handler and restored propagation inside the affected test before setting `caplog`.
- **Files modified:** `backend/tests/api/test_service_search.py`
- **Verification:** Focused pytest command exits 0.
- **Committed in:** `437a6dc`

**3. [Rule 3 - Blocking] Added narrow pyright casts for existing service protocol mismatches**
- **Found during:** Task 2
- **Issue:** The plan-required pyright target included `service.py` and surfaced existing protocol typing mismatches for metadata/vector store access.
- **Fix:** Added local casts at service call sites and adjusted new tests to use pyright-friendly Pydantic validation calls.
- **Files modified:** `backend/src/dotmd/api/service.py`, `backend/tests/api/test_service_search.py`, `backend/tests/ingestion/test_source_lifecycle.py`
- **Verification:** Plan pyright command exits 0.
- **Committed in:** `437a6dc`

---

**Total deviations:** 3 auto-fixed (Rule 3)
**Impact on plan:** All fixes were required to satisfy the plan verification gate. No architecture or public contract scope was expanded.

## Issues Encountered

None beyond the auto-fixed blocking issues documented above.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 33 can close with filesystem and Telegram construction paths routed through lifecycle. The next unified-source phases can build on the bundle boundary for federated candidates, Telegram sync reuse, and connector compatibility without inheriting direct Telegram construction or unsafe cursor commits.

## Self-Check: PASSED

- Found `backend/src/dotmd/ingestion/source_lifecycle.py`
- Found `backend/src/dotmd/ingestion/pipeline.py`
- Found `backend/src/dotmd/api/service.py`
- Found `backend/src/dotmd/cli.py`
- Found `backend/tests/ingestion/test_source_lifecycle.py`
- Found `backend/tests/ingestion/test_telegram_ingestion.py`
- Found `backend/tests/api/test_service_search.py`
- Found `docs/source-adapter-architecture.md`
- Found `docs/source-registry-airweave-mapping.md`
- Found `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-03-telegram-lifecycle-and-cursor-boundary-SUMMARY.md`
- Found commit `a3034ee`
- Found commit `437a6dc`
- Found commit `0e55d8b`

---
*Phase: 33-source-lifecycle-config-auth-cursor-boundary*
*Completed: 2026-05-08*
