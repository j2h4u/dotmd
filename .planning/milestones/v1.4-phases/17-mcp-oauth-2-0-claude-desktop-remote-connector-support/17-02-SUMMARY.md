---
phase: 17-mcp-oauth-2-0-claude-desktop-remote-connector-support
plan: "02"
subsystem: oauth-provider
tags: [oauth, mcp, json-storage, tokens]
requirements:
  - OAUTH-PROVIDER-01
  - OAUTH-PROVIDER-02
  - OAUTH-PROVIDER-03
key_files:
  created:
    - backend/src/dotmd/auth.py
    - backend/tests/test_auth.py
  modified: []
metrics:
  completed: "2026-04-30T08:35:57Z"
  tasks_completed: 1
  tests_added: 10
---

# Phase 17 Plan 02: DotMDOAuthProvider

Implemented the JSON-backed OAuth Authorization Server provider used by FastMCP.
The SDK owns protocol mechanics; `DotMDOAuthProvider` handles client/code/token
storage, auto-approval redirect generation, token rotation, expiry checks, and
atomic persistence.

## Tasks Completed

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Implement DotMDOAuthProvider | a3ad039 | Added provider with all 9 SDK methods, atomic JSON writes, in-memory state, async write lock, and behavior tests |

## Behavior Delivered

- `register_client()` persists `OAuthClientInformationFull` to JSON.
- `authorize()` auto-generates an auth code and redirects immediately with `code` and optional `state`.
- `exchange_authorization_code()` deletes the auth code, issues 30-day access token, and issues perpetual refresh token.
- `load_access_token()` rejects expired tokens locally because the SDK verifier trusts provider output.
- `exchange_refresh_token()` rotates refresh and access tokens.
- `revoke_token()` is idempotent and removes matching access/refresh token entries.
- State loads once at provider initialization; hot-path token verification does not read JSON from disk.
- All mutations flush via tmp file plus `os.replace()`.

## Verification

- `UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev pytest tests/test_auth.py -q --tb=short` -> `10 passed`
- `UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev ruff check src/dotmd/auth.py tests/test_auth.py` -> passed
- `UV_CACHE_DIR=/tmp/uv-cache uv run python -c "import dotmd.auth; print('auth import ok')"` -> `auth import ok`
- `docker exec dotmd python -m pytest tests/test_auth.py -q --tb=short` -> `10 passed`
- `docker exec dotmd python -c "import dotmd.auth; print('auth import ok')"` -> `auth import ok`
- Method count check confirmed all 9 `OAuthAuthorizationServerProvider` methods are implemented exactly once.

## Deviations from Plan

**[Rule 2 - Missing handling] SDK key-link checker cannot verify non-file source links**
- Found during: pre-wave and post-implementation key-link checks.
- Issue: `verify.key-links` reports failures for entries where `from` is `DotMDOAuthProvider._flush()` or `authorize()` because those are symbols, not file paths. It also did not match the generic inheritance pattern despite the source containing the inheritance.
- Fix: Verified links manually against `backend/src/dotmd/auth.py`: class inherits `OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]`, `_flush()` uses `os.replace`, and `authorize()` calls `construct_redirect_uri(str(params.redirect_uri), ...)`.
- Files modified: None beyond the planned implementation.
- Verification: Tests, import check, ruff, and direct source inspection passed.

Total deviations: 1 auto-handled. Impact: none; verifier limitation only.

## Known Stubs

None.

## Threat Flags

None. This provider is storage-only and does not expose endpoints by itself.

## Self-Check: PASSED

All Plan 02 must-haves are satisfied:
- All 9 provider methods implemented.
- Auto-approve authorization flow implemented.
- Expired access tokens return `None`.
- Mutations are serialized by `asyncio.Lock`.
- JSON writes are atomic with tmp file plus `os.replace`.
- In-memory state is loaded once at init.
- Access tokens use 30-day expiry; refresh tokens have no expiry.
- Module imports cleanly without `DOTMD_BASE_URL`.
