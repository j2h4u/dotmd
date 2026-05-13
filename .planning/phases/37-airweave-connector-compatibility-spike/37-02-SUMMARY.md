---
phase: 37-airweave-connector-compatibility-spike
plan: 37-02
subsystem: ingestion
tags: [gmail, federated-search, airweave, source-provider, searchcandidate]
requires:
  - phase: 37-01
    provides: Vendored Airweave Gmail slice and OAuth token shim
provides:
  - BaseConnectorBridge ABC for connector-to-dotMD federated providers
  - GmailBridge direct Gmail API search and read_unit_window implementation
  - GmailApplicationSourceProvider protocol wrapper with federated-only stubs
  - Source-neutral federated low-signal filtering in DotMDService
affects: [37-03-gmail-registry-lifecycle-wiring, 37-04-airweave-compatibility-report-and-tests]
tech-stack:
  added: []
  patterns: [connector-bridge-abc, federated-only-provider, quota-merge-source-filter]
key-files:
  created:
    - backend/src/dotmd/ingestion/gmail_provider.py
    - backend/tests/test_gmail_bridge.py
  modified:
    - backend/src/dotmd/api/service.py
key-decisions:
  - "Gmail search uses direct Gmail API calls because Airweave GmailSource.search() is not implemented."
  - "Federated Gmail candidates keep source_native_score=None because they bypass RRF and use quota merge slots."
  - "Telegram low-signal filtering is source-scoped and does not apply to Gmail snippets."
patterns-established:
  - "Connector bridges implement BaseConnectorBridge.search_native/read_unit_window/to_search_candidate."
  - "Federated-only providers satisfy ApplicationSourceProviderProtocol with explicit NotImplementedError stubs for sync methods."
requirements-completed: [AIR-01]
duration: 25min
completed: 2026-05-13
---

# Phase 37 Plan 02 Summary

**Gmail federated bridge with direct Gmail API search, readable message refs, and source-neutral quota filtering**

## Performance

- **Duration:** 25 min
- **Started:** 2026-05-13T00:20:00Z
- **Completed:** 2026-05-13T00:45:00Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `BaseConnectorBridge` and `GmailBridge`, including explicit Gmail API timeouts, direct metadata search, body decoding, and `SourceUnitWindow` read support.
- Added `GmailApplicationSourceProvider` with protocol-conformant `describe_source`, `export_changes`, `search_native`, and `read_unit_window` methods.
- Replaced Telegram-specific federated quota filtering in `DotMDService` with `_is_low_signal_federated_candidate`, preserving Telegram filtering while passing Gmail candidates through.
- Added unit coverage for score-`None` federated candidates, low-signal filtering, Gmail API error boundaries, body decoding, metadata whitelisting, ABC behavior, and protocol stub signatures.

## Task Commits

1. **Tasks 1-3: Source-neutral filtering, Gmail bridge, and tests** - `936fa32` (feat)

## Files Created/Modified

- `backend/src/dotmd/ingestion/gmail_provider.py` - Gmail bridge, provider wrapper, Gmail body decoding, and Gmail-specific errors.
- `backend/src/dotmd/api/service.py` - Source-neutral federated low-signal filter.
- `backend/tests/test_gmail_bridge.py` - Unit tests for bridge behavior and service filter safety.

## Decisions Made

- Defined Gmail auth/temporary errors locally in `gmail_provider.py` because no existing dotMD core exception types for source auth/transient provider failures existed.
- Documented O(n) Gmail metadata round-trips in `search_native`; batch metadata fetch remains a future optimization rather than hidden scope.
- Kept `GMAIL_API_TIMEOUT_SECONDS = 10.0` and per-call `httpx.Timeout(..., connect=5.0)` to prevent federated search hangs.

## Deviations from Plan

None - plan executed exactly as written.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** None.

## Issues Encountered

- `uv run python -m pytest tests/ -x -q` executed 119 passing tests and then exited nonzero because the local dotMD MCP server was not reachable at `http://localhost:8080`. Focused bridge tests passed and no test assertion failed before the environment reachability gate.

## User Setup Required

None - Gmail credentials are wired in the next lifecycle plan.

## Verification

- `uv run python -m pytest tests/test_gmail_bridge.py tests/test_vendor_airweave_import.py -q` — 27 passed, 2 skipped.
- Direct import check for `GmailApplicationSourceProvider`, `GmailBridge`, `BaseConnectorBridge`, and `GMAIL_API_TIMEOUT_SECONDS` passed.
- Broad backend test body: 119 passed, 1 skipped before MCP reachability exit.

## Self-Check: PASSED

## Next Phase Readiness

Plan 37-03 can register Gmail in the source registry and lifecycle factory, using `GmailApplicationSourceProvider` and `GmailOAuthTokenProvider` to build a federated runtime bundle.

---
*Phase: 37-airweave-connector-compatibility-spike*
*Completed: 2026-05-13*
