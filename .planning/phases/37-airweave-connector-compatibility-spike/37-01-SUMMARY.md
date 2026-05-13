---
phase: 37-airweave-connector-compatibility-spike
plan: 37-01
subsystem: ingestion
tags: [airweave, gmail, vendoring, oauth, source-provider]
requires: []
provides:
  - Vendored Airweave Gmail entity/source/config slice under dotmd.vendor.airweave
  - DI shims for Gmail logging, HTTP, and OAuth refresh-token access
  - Smoke tests proving vendored imports avoid the full Airweave runtime
affects: [37-02-gmail-bridge-federated-search, 37-03-gmail-registry-lifecycle-wiring]
tech-stack:
  added: []
  patterns: [vendored-platform-slice, structural-di-shims, margin-based-token-cache]
key-files:
  created:
    - backend/src/dotmd/vendor/airweave/entities_base.py
    - backend/src/dotmd/vendor/airweave/entities_gmail.py
    - backend/src/dotmd/vendor/airweave/source_base.py
    - backend/src/dotmd/vendor/airweave/source_gmail.py
    - backend/src/dotmd/vendor/airweave/gmail_config.py
    - backend/src/dotmd/vendor/airweave/decorators.py
    - backend/src/dotmd/vendor/airweave/shims.py
    - backend/tests/test_vendor_airweave_import.py
  modified: []
key-decisions:
  - "Vendored only the Airweave platform slice needed for Gmail compatibility."
  - "Kept OAuth refresh-token material inside GmailOAuthTokenProvider instead of Airweave runtime objects."
patterns-established:
  - "Vendored connector slices live under dotmd.vendor.* and must not import airweave.* runtime modules."
  - "Token refresh uses expires_in - 300 with a threading.Lock and double-check cache path."
requirements-completed: [AIR-01, AIR-02]
duration: 20min
completed: 2026-05-13
---

# Phase 37 Plan 01 Summary

**Vendored Airweave Gmail platform slice with self-contained entities, source/config stubs, and thread-safe OAuth shims**

## Performance

- **Duration:** 20 min
- **Started:** 2026-05-13T00:00:00Z
- **Completed:** 2026-05-13T00:20:00Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Added a self-contained `dotmd.vendor.airweave` package with Gmail entities, source metadata, config, decorator stubs, source base stubs, and vendor traceability files.
- Implemented `GmailLoggerShim`, `GmailHttpClientShim`, and `GmailOAuthTokenProvider`; the token provider uses `threading.Lock`, double-check locking, and `expires_in - 300` cache expiry.
- Added smoke tests covering imports, source construction with shims, token expiry margin, concurrent refresh serialization, and no heavy Airweave runtime imports.

## Task Commits

1. **Tasks 1-3: Vendor package, shims, and smoke tests** - `04db3d6` (feat)

## Files Created/Modified

- `backend/src/dotmd/vendor/airweave/entities_base.py` - Local Airweave base entities and `AirweaveField` metadata wrapper.
- `backend/src/dotmd/vendor/airweave/entities_gmail.py` - Gmail thread/message/attachment/deletion entity schemas.
- `backend/src/dotmd/vendor/airweave/source_base.py` - Minimal source contract plus DI stubs and enums.
- `backend/src/dotmd/vendor/airweave/source_gmail.py` - GmailSource shell with Airweave metadata and explicit `search()` absence note.
- `backend/src/dotmd/vendor/airweave/gmail_config.py` - Extracted Gmail config model.
- `backend/src/dotmd/vendor/airweave/decorators.py` - No-op `@source` decorator preserving class attributes.
- `backend/src/dotmd/vendor/airweave/shims.py` - Logger, HTTP client, and OAuth token-provider shims.
- `backend/src/dotmd/vendor/airweave/VENDOR_VERSION` - Source traceability.
- `backend/src/dotmd/vendor/airweave/VENDOR_NOTES.md` - Per-file modification notes.
- `backend/tests/test_vendor_airweave_import.py` - Vendored slice smoke tests.

## Decisions Made

- Used a local `AirweaveField` wrapper that stores Airweave flags in `json_schema_extra`, avoiding Pydantic v2 deprecated extra-field warnings while keeping flag metadata available.
- Kept `GmailSource` as a platform-compatible shell instead of porting Airweave's full async sync implementation, because Phase 37's live search bridge uses direct Gmail API calls and not Airweave's sync runtime.
- Implemented token refresh as a synchronous shim because the bridge planned in 37-02 uses synchronous federated search calls.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Avoided Pydantic v2 field-metadata warnings**
- **Found during:** Task 3 verification
- **Issue:** Using `AirweaveField = Field` with Airweave-specific keyword args produced Pydantic deprecation warnings.
- **Fix:** Implemented a local `AirweaveField()` wrapper that moves Airweave metadata into `json_schema_extra`.
- **Files modified:** `backend/src/dotmd/vendor/airweave/entities_base.py`
- **Verification:** `uv run python -m pytest tests/test_vendor_airweave_import.py -v` passes with no warnings.
- **Committed in:** `04db3d6`

---

**Total deviations:** 1 auto-fixed (Rule 2).
**Impact on plan:** No scope expansion; the fix keeps the vendored slice compatible with Pydantic v2 behavior.

## Issues Encountered

- The local environment has no bare `python` binary. Verification used `uv run python`, matching the repo-managed Python environment.

## User Setup Required

None - no external service configuration required for the vendored slice.

## Verification

- `uv run python -m pytest tests/test_vendor_airweave_import.py -v` — 8 passed.
- `grep -r "^from airweave\\.\\|^import airweave\\.\\|temporalio" src/dotmd/vendor/ --include='*.py'` — no matches.
- Direct import checks for `entities_base`, `entities_gmail`, `source_gmail`, and `gmail_config` passed.

## Self-Check: PASSED

## Next Phase Readiness

Plan 37-02 can import `dotmd.vendor.airweave` and use `GmailOAuthTokenProvider` as its runtime token provider. `GmailSource.search()` remains intentionally absent; the bridge must call the Gmail API directly.

---
*Phase: 37-airweave-connector-compatibility-spike*
*Completed: 2026-05-13*
