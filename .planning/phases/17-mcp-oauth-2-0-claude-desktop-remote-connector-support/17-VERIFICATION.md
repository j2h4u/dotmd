---
phase: 17-mcp-oauth-2-0-claude-desktop-remote-connector-support
verified: 2026-05-06T19:56:26+05:00
status: passed
score: 90
---

# Phase 17 Verification: MCP OAuth 2.0 Connector Support

## Goal Achievement

**Goal:** Implement OAuth 2.0 Authorization Server support inside the existing FastMCP server so remote MCP connector flows can use UI-based OAuth, with persistent token storage and `DOTMD_BASE_URL` configuration.

**Result:** PASSED.

Phase 17 delivered public-base-url configuration, a JSON-backed OAuth provider, FastMCP auth wiring, and public OAuth flow verification. Current code still contains the OAuth provider and conditional MCP auth wiring. OAuth remains disabled when `DOTMD_BASE_URL` is unset, which preserves local/internal transport behavior.

## Observable Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| `DOTMD_BASE_URL` is represented in settings | VERIFIED | `backend/src/dotmd/core/config.py:216` defines the OAuth base URL setting and `backend/src/dotmd/core/config.py:229` validates/normalizes it. |
| OAuth provider is implemented | VERIFIED | `backend/src/dotmd/auth.py:114` defines `DotMDOAuthProvider` over the MCP SDK provider protocol. |
| OAuth state is JSON-backed and persisted | VERIFIED | `backend/src/dotmd/mcp_server.py:138` constructs `DotMDOAuthProvider(Path("/dotmd-index/oauth_state.json"))`. |
| FastMCP receives auth provider/settings conditionally | VERIFIED | `backend/src/dotmd/mcp_server.py:133` reads `DOTMD_BASE_URL`; `backend/src/dotmd/mcp_server.py:293` passes `auth_server_provider=_provider`. |
| Authorization redirects use SDK helper | VERIFIED | `backend/src/dotmd/auth.py:325` returns `construct_redirect_uri(...)`. |
| Production preflight can run without auth poisoning local e2e | VERIFIED | `backend/start.sh:49` and `backend/start.sh:79` run preflight with `DOTMD_BASE_URL` unset before final authenticated startup. |

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| Plan 01 summary | VERIFIED | `17-01-SUMMARY.md` records Tailscale path stripping, `Settings.base_url`, and production env setup. |
| Plan 02 summary | VERIFIED | `17-02-SUMMARY.md` records provider implementation and token storage behavior. |
| Plan 03 summary | VERIFIED | `17-03-SUMMARY.md` records FastMCP wiring and public OAuth flow verification. |
| Current implementation | VERIFIED | `auth.py`, `mcp_server.py`, `core/config.py`, and `start.sh` retain the delivered behavior. |

## Key Link Verification

The OAuth path starts at `DOTMD_BASE_URL`: settings validate the public base URL, `mcp_server.py` creates a `DotMDOAuthProvider` only when the base URL is configured, FastMCP receives that provider, and the provider issues authorization redirects and tokens using SDK OAuth types.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| OAUTH-ENV-01 | SATISFIED | `17-01-SUMMARY.md` and settings code cover `DOTMD_BASE_URL`. |
| OAUTH-ENV-02 | SATISFIED | `17-01-SUMMARY.md` records Tailscale path stripping and public base URL behavior. |
| OAUTH-PROVIDER-01 | SATISFIED | `DotMDOAuthProvider` implements the SDK provider surface. |
| OAUTH-PROVIDER-02 | SATISFIED | JSON persistence and token/code storage are implemented in `auth.py`. |
| OAUTH-PROVIDER-03 | SATISFIED | Expiry, rotation, revoke, and one-time authorization behavior are covered by provider tests. |
| OAUTH-WIRE-01 | SATISFIED | `mcp_server.py` wires the provider into FastMCP conditionally. |
| OAUTH-E2E-01 | SATISFIED | `17-03-SUMMARY.md` records successful public OAuth discovery, registration, authorize, token exchange, authenticated MCP, and unauthenticated 401. |

## Anti-Patterns Checked

| Anti-pattern | Result |
|--------------|--------|
| OAuth required for local/internal transports | ABSENT; auth is conditional on `DOTMD_BASE_URL`. |
| Token verification rereads JSON per request | ABSENT according to provider summary; state loads into memory and mutations flush atomically. |
| Public path requires FastMCP mount-path rewrite | ABSENT; Phase 17 verified Tailscale strips `/dotmd`. |
| Preflight accidentally tests auth-enabled runtime with unauthenticated smoke | ABSENT; `start.sh` unsets `DOTMD_BASE_URL` for preflight. |

## Human Verification Required

None for phase closure. Live public OAuth was verified during the phase and recorded in `17-03-SUMMARY.md`.

## Gaps Summary

No blocking gaps remain. Current deployment may choose to leave OAuth disabled by omitting `DOTMD_BASE_URL`; that is a configuration choice, not a missing Phase 17 artifact.

## Verification Metadata

- Verification type: retroactive goal-backward phase verification
- Evidence checked: Phase 17 summaries, settings, OAuth provider, MCP server wiring, startup preflight, current provider tests
- Current checks run:
  - PASS: `cd backend && uv run pytest tests/core/test_config_base_url.py tests/test_auth.py -q` (`28 passed`)

