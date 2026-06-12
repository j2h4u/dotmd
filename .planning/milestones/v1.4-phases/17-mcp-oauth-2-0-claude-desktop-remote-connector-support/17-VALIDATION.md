---
phase: 17-mcp-oauth-2-0-claude-desktop-remote-connector-support
slug: mcp-oauth-2-0-claude-desktop-remote-connector-support
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06T20:08:34+05:00
validation_state: reconstructed-from-summaries
gaps_found: 0
gaps_resolved: 0
manual_only: 0
---

# Phase 17 — Validation Strategy

> Retroactive Nyquist validation for the completed MCP OAuth connector phase.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/core/test_config_base_url.py tests/test_auth.py tests/test_mcp_access_log.py -q` |
| Full phase command | `cd backend && uv run pytest tests/core/test_config_base_url.py tests/test_auth.py tests/test_mcp_access_log.py -q` |
| Lint command | `cd backend && uv run ruff check src/dotmd/auth.py src/dotmd/mcp_server.py src/dotmd/core/config.py tests/test_auth.py tests/core/test_config_base_url.py tests/test_mcp_access_log.py` |
| Estimated runtime | about 3 seconds |

## Discovery

Phase 17 had no pre-existing `17-VALIDATION.md`, so this file reconstructs the validation contract from:

- `17-01-PLAN.md` and `17-01-SUMMARY.md`
- `17-02-PLAN.md` and `17-02-SUMMARY.md`
- `17-03-PLAN.md` and `17-03-SUMMARY.md`
- `17-VERIFICATION.md`
- Current OAuth settings, provider, MCP route, startup, and access-log tests

## Gap Analysis

No Nyquist validation gaps remain. Phase 17 already has behavior-focused tests for the base URL contract, OAuth provider storage/token lifecycle, metadata routes, pairing flow, and request-body preservation around token handling.

| Requirement | Coverage |
|-------------|----------|
| OAUTH-ENV-01 | `tests/core/test_config_base_url.py` covers `Settings.base_url` default, HTTPS acceptance, localhost exception, trailing slash normalization, and invalid HTTP rejection. |
| OAUTH-ENV-02 | `17-01-SUMMARY.md` records the Tailscale path-stripping check; current tests keep the route layer root-mounted and metadata URL behavior pinned. |
| OAUTH-PROVIDER-01 | `tests/test_auth.py` covers `DotMDOAuthProvider` registration, client lookup, pending-client behavior, authorize, token exchange, refresh, revoke, expiry, and JSON persistence. |
| OAUTH-PROVIDER-02 | `tests/test_auth.py` covers JSON persistence, token storage, pending-client storage, and second-provider state reload. |
| OAUTH-PROVIDER-03 | `tests/test_auth.py` covers expiry, refresh rotation, idempotent revoke, pairing code activation/expiry/rate-limit, redirect allowlist behavior, and public-client ChatGPT connector behavior. |
| OAUTH-WIRE-01 | `tests/test_mcp_access_log.py` covers OAuth metadata, protected-resource metadata, pairing authorize route behavior, and token form preservation through middleware. |
| OAUTH-E2E-01 | `17-03-SUMMARY.md` records the historical public OAuth e2e flow; current local tests cover the protocol pieces that are practical to automate without requiring the production Tailscale endpoint to be auth-enabled during every local validation run. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| 17-01-01 | 01 | 1 | OAUTH-ENV-01 | `DOTMD_BASE_URL` maps to `Settings.base_url`; valid values construct and invalid non-localhost HTTP fails loudly. | unit | `cd backend && uv run pytest tests/core/test_config_base_url.py -q` | yes | green |
| 17-01-02 | 01 | 1 | OAUTH-ENV-02 | Public URL keeps `/dotmd` while container routes stay root-mounted; Tailscale strips `/dotmd`. | recorded live check + route tests | `cd backend && uv run pytest tests/test_mcp_access_log.py -q` | yes | green |
| 17-02-01 | 02 | 2 | OAUTH-PROVIDER-01 | Provider implements registration, pending activation, authorization code, access token, refresh token, and revoke flows. | unit | `cd backend && uv run pytest tests/test_auth.py -q` | yes | green |
| 17-02-02 | 02 | 2 | OAUTH-PROVIDER-02 | Provider persists JSON state atomically enough for a second provider instance to reload issued credentials. | unit | `cd backend && uv run pytest tests/test_auth.py -q` | yes | green |
| 17-02-03 | 02 | 2 | OAUTH-PROVIDER-03 | Expired tokens are rejected, refresh tokens rotate, pairing codes expire/rate-limit, and revocation is idempotent. | unit | `cd backend && uv run pytest tests/test_auth.py -q` | yes | green |
| 17-03-01 | 03 | 3 | OAUTH-WIRE-01 | MCP OAuth metadata and pairing routes expose the expected public issuer/resource behavior. | integration-style unit | `cd backend && uv run pytest tests/test_mcp_access_log.py -q` | yes | green |
| 17-03-02 | 03 | 3 | OAUTH-E2E-01 | Metadata discovery, dynamic registration, PKCE authorize, token exchange, bearer-authenticated MCP, and unauthenticated 401 were verified against the public Tailscale URL during the phase; current automated tests pin provider and route behavior. | recorded live e2e + automated protocol tests | `cd backend && uv run pytest tests/core/test_config_base_url.py tests/test_auth.py tests/test_mcp_access_log.py -q` | yes | green |

## Wave 0 Requirements

Existing pytest infrastructure covers all Phase 17 requirements.

## Manual-Only Verifications

All current Phase 17 closure behavior has automated verification or recorded live evidence from phase execution. No unresolved manual-only verification remains.

## Commands Run

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/core/test_config_base_url.py tests/test_auth.py tests/test_mcp_access_log.py -q` | PASS: 33 passed |
| `cd backend && uv run ruff check src/dotmd/auth.py src/dotmd/mcp_server.py src/dotmd/core/config.py tests/test_auth.py tests/core/test_config_base_url.py tests/test_mcp_access_log.py` | PASS |

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or recorded live e2e evidence
- [x] Sampling continuity restored retroactively
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 10 seconds for the focused phase suite
- [x] `nyquist_compliant: true` set in frontmatter

Approval: approved 2026-05-06
