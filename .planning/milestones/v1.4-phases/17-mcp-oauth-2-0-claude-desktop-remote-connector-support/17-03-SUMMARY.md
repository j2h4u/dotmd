---
phase: 17-mcp-oauth-2-0-claude-desktop-remote-connector-support
plan: "03"
subsystem: mcp-oauth-wiring
tags: [oauth, mcp, fastmcp, tailscale]
requirements:
  - OAUTH-WIRE-01
  - OAUTH-E2E-01
key_files:
  created: []
  modified:
    - backend/src/dotmd/mcp_server.py
    - backend/start.sh
    - backend/tests/e2e/conftest.py
metrics:
  completed: "2026-04-30T09:47:30Z"
  tasks_completed: 3
  public_oauth_steps_passed: 6
---

# Phase 17 Plan 03: MCP OAuth Wiring

Wired `DotMDOAuthProvider` into the FastMCP server and verified the full public
OAuth flow through the Tailscale URL:
metadata discovery -> dynamic client registration -> PKCE authorize -> token
exchange -> authenticated MCP `tools/list` -> unauthenticated 401.

## Tasks Completed

| Task | Name | Commit | Key Changes |
|------|------|--------|-------------|
| 1 | Wire FastMCP OAuth | df83a47, 9648785 | Added conditional `DOTMD_BASE_URL` provider wiring and preserved FastMCP auth middleware in the wrapped Starlette app |
| 2 | Restart and preflight | d225ce5, 9ec30be | Rebuilt image for `start.sh`; preflight now runs smoke tests with `DOTMD_BASE_URL` unset, then starts final authenticated server |
| 3 | Public OAuth verification | n/a | Verified all 6 curl-equivalent steps against `https://senbonzakura.tailf87223.ts.net/dotmd` |

## Verification

- OAuth metadata: `GET /dotmd/.well-known/oauth-authorization-server` -> `200`, issuer `https://senbonzakura.tailf87223.ts.net/dotmd`.
- Dynamic registration: `POST /dotmd/register` -> `201`, returned `client_id` and `client_secret`.
- PKCE authorize: `GET /dotmd/authorize?...` -> `302`, redirect to `http://localhost:8888/callback?code=...`.
- Token exchange: `POST /dotmd/token` -> `200`, `token_type=Bearer`, `expires_in=2592000`, refresh token present.
- Authenticated MCP: `POST /dotmd/mcp` with bearer token -> `200`, tools: `search,read,feedback`.
- Unauthenticated MCP: `POST /dotmd/mcp` without bearer token -> `401`, body `{"error": "invalid_token", "error_description": "Authentication required"}`.
- Container preflight after final fix: `30 passed in 129.66s (0:02:09)`, followed by final server startup.
- Health check: `GET http://127.0.0.1:18082/health` -> `200 {"status":"ok"}`.
- OAuth state: `/dotmd-index/oauth_state.json` exists, size `8.3K`, with `6` clients, `5` access tokens, and `5` refresh tokens after verification runs.
- Local lint: `UV_CACHE_DIR=/tmp/uv-cache uv run --extra dev ruff check src/dotmd/mcp_server.py` -> passed.
- Local pyright: only the existing two `Settings()` baseline errors in `mcp_server.py`; pyright ratchet remains at baseline `121 errors (baseline 121)`.

## Deviations from Plan

**[Rule 2 - Missing handling] FastMCP middleware was not preserved by `create_app()`**
- Found during: public OAuth verification; token issuance succeeded but authenticated `/mcp` returned `401`.
- Issue: `create_app()` copied `mcp_starlette.routes` but dropped `mcp_starlette.user_middleware`, so FastMCP's `AuthenticationMiddleware` never parsed bearer tokens into the request scope.
- Fix: Added `middleware=mcp_starlette.user_middleware` to the wrapper `Starlette(...)` constructor.
- Verification: Re-ran preflight and public OAuth flow; bearer `tools/list` returned `200`.

**[Rule 2 - Missing handling] Dev preflight could not run against auth-enabled `/mcp`**
- Found during: first restart with `DOTMD_BASE_URL` set; E2E smoke tests received `401`.
- Issue: the preflight smoke suite validates local unauthenticated transport behavior, but final production HTTP must require OAuth.
- Fix: `start.sh` now starts a temporary server with `DOTMD_BASE_URL` unset for preflight, shuts it down after tests pass, then `exec`s the final server with the real environment.
- Follow-up fix: changed `DOTMD_BASE_URL=` to `env -u DOTMD_BASE_URL` because an empty string is intentionally invalid configuration.
- Verification: Rebuilt image and confirmed preflight passed before final authenticated server startup.

**Tool names differ from the original plan text**
- The plan expected `Search, Drill, GetStatus, SubmitFeedback`.
- The running code exposes `search, read, feedback`, matching pre-existing tool-surface edits in this worktree.
- OAuth verification treats this as a non-auth surface difference; the required bearer-gated `tools/list` behavior passes.

## Known Stubs

None.

## Threat Flags

None added. `/mcp` is bearer-token protected when `DOTMD_BASE_URL` is set, while
stdio/internal paths remain auth-disabled when `DOTMD_BASE_URL` is unset.

## Self-Check: PASSED

All Plan 03 success criteria are satisfied:
- FastMCP receives `auth_server_provider=_provider` and OAuth `AuthSettings` when `DOTMD_BASE_URL` is set.
- Auth routes are externally discoverable at the Tailscale `/dotmd` prefix.
- PKCE authorization and token exchange work.
- Bearer-authenticated MCP calls succeed.
- Unauthenticated MCP calls return `401`.
- OAuth state persists under `/dotmd-index/oauth_state.json`.
