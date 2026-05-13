---
phase: 37-airweave-connector-compatibility-spike
status: clean
reviewed_at: 2026-05-13
reviewer: codex-inline
scope:
  - backend/src/dotmd/vendor/airweave/
  - backend/src/dotmd/ingestion/gmail_provider.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/ingestion/source_registry.py
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/api/service.py
  - backend/tests/
---

# Phase 37 Code Review

## Findings

No open findings.

## Fixed During Review

### Warning: Vendored BaseSource assumed async token providers only

- **File:** `backend/src/dotmd/vendor/airweave/source_base.py`
- **Issue:** `BaseSource.get_access_token()` awaited `self._auth.get_token()` unconditionally, while the Phase 37 `GmailOAuthTokenProvider` is intentionally synchronous for the sync Gmail bridge.
- **Fix:** `BaseSource.get_access_token()` now accepts either a synchronous string token or an awaitable token, matching `GmailSource.validate()`.
- **Commit:** `54f6d99`

## Verification

- `just check` - passed.
- Result: Ruff passed, Pyright ratchet passed, pytest passed with 550 passed, 14 skipped, 36 deselected.
