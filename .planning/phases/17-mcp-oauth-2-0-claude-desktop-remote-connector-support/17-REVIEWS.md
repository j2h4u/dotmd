---
phase: 17
reviewers: [opencode]
reviewed_at: 2026-04-29T00:00:00Z
plans_reviewed: [17-01-PLAN.md, 17-02-PLAN.md, 17-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 17

## OpenCode Review

# Cross-AI Plan Review: Phase 17 — MCP OAuth 2.0

## Plan 17-01: Verify Tailscale path-stripping + base_url config

### Summary

Plan 01 is a well-scoped 3-task plan that resolves the critical A1 assumption (Tailscale path handling) and adds the `base_url` field to `Settings`. The human-verify checkpoint for Task 1 is the right call — confirmed via live curl that Tailscale **does strip** `/dotmd` (root `/health` returns `{"status":"ok"}`, `/dotmd/health` returns `Not Found`). This means `mount_path` is NOT needed, confirming the plan's default assumption.

### Strengths

- **A1 resolution is a blocking checkpoint** — the single highest-risk assumption is resolved before any code is written
- **`base_url` field placement** is clean: optional with `None` default, HTTPS validator, trailing-slash stripping — follows existing `field_validator` patterns exactly
- **Test coverage is specific**: 5 behavior-pinning tests cover None, valid HTTPS, invalid HTTP, localhost exception, and trailing slash
- **No regressions**: acceptance criteria explicitly verify `Settings()` still constructs without error

### Concerns

- **MEDIUM** — If the container is not running when Task 1 executes, the curl verification blocks with no fallback path documented.
- **LOW** — The `validate_base_url` validator allows `http://localhost` but not `http://127.0.0.1` or `http://0.0.0.0`. Local dev with non-localhost loopback addresses would fail.
- **LOW** — Plan reads `feedback.py` in context but never uses it — stale reference from pattern mapper template.

### Suggestions

- Add `http://127.0.0.1` and `http://0.0.0.0` to the localhost exception in the validator for local-dev flexibility
- Consider whether Task 1 should document a fallback if the container is down

### Risk Assessment: **LOW**

Well-scoped, verifiable, reversible.

---

## Plan 17-02: Implement DotMDOAuthProvider

### Summary

Plan 02 implements the core OAuth provider — a JSON-backed storage backend for all 9 `OAuthAuthorizationServerProvider` methods. The design correctly treats the provider as pure storage (the SDK handles all protocol logic). However, there is a **missing `resource` field** on `AccessToken` that could cause issues with strict OAuth clients.

### Strengths

- **Correct PKCE boundary**: Provider only stores/returns `code_challenge` — SDK verifies `sha256(verifier) == challenge` before calling `exchange_authorization_code()`.
- **Atomic persistence**: `tmp + os.replace()` pattern is correct for crash safety
- **asyncio.Lock()**: Right choice for serializing mutations in the async handler context
- **load_access_token() expiry check**: Correctly called out that SDK does NOT enforce this
- **Test 10 (persistence across instances)**: Excellent — verifies JSON round-trip by creating a second provider instance from the same file
- **10 behavior tests covering all 9 methods + persistence**: Thorough coverage

### Concerns

- **HIGH** — `AccessToken` model also has a `resource: str | None` field (RFC 8707) that the plan's skeleton does NOT set when creating access tokens in `exchange_authorization_code()`. The resource is present on `AuthorizationCode` (via `params.resource`) but is not propagated to the issued `AccessToken`. This means resource binding is lost between the auth code and the token — a correctness gap for strict OAuth clients.

- **MEDIUM** — `AuthorizationCode.redirect_uri` is typed as `AnyUrl` (not `AnyUrl | None`) in the actual SDK source. The interfaces documentation in RESEARCH.md shows `AnyUrl | None` — misleading for the executor, though the actual construction code is correct.

- **MEDIUM** — The plan says "Write tests in `backend/tests/test_auth.py`" but doesn't specify whether to place it under `tests/` root or a subdirectory. Minor but worth clarifying.

- **LOW** — `revoke_token()` uses `hasattr(token, "token")` unnecessarily — both `AccessToken` and `RefreshToken` are guaranteed to have `.token`. Harmless but noisy.

- **LOW** — No cleanup of expired auth codes. Codes accumulate in JSON (expire in 5 minutes, deleted on exchange). Fine for single-user but undocumented.

### Suggestions

- **Set `resource` on `AccessToken`** from the auth code's `resource` field: `resource=authorization_code.resource`
- Fix RESEARCH.md interfaces section to show `redirect_uri: AnyUrl` (not optional) for `AuthorizationCode`
- Add a note that expired unclaimed auth codes accumulate in JSON (minor)

### Risk Assessment: **MEDIUM**

Core logic is sound and well-tested, but the `resource` field omission could cause issues with strict OAuth clients.

---

## Plan 17-03: Wire auth into mcp_server.py + E2E verification

### Summary

Plan 03 connects the provider into the `FastMCP` constructor and verifies the complete OAuth PKCE flow via curl. The wiring is clean (~15 lines changed), conditional on `DOTMD_BASE_URL`, and preserves backward compatibility.

### Strengths

- **Conditional wiring**: When `DOTMD_BASE_URL` is unset, auth is completely disabled — no regression for stdio or internal Docker paths
- **`create_app()` requires no changes**: `routes=mcp_starlette.routes` already copies all routes including auth routes
- **6-step E2E verification** covers: metadata → register → PKCE authorize → token exchange → authenticated MCP call → unauthenticated 401
- **Correct Tailscale stripping assumption** with documented fallback for the "preserves" case
- **Honest threat model**: auto-approve appropriate for single-user trusted Tailnet

### Concerns

- **HIGH** — Task 1 verification (`docker exec dotmd python -c "from dotmd.mcp_server import mcp; print('auth_provider:', mcp.auth_server_provider)"`) will print `auth_provider: None` even after the code change because `DOTMD_BASE_URL` is not set in the container env at this point (it's in `.env`, loaded on restart). This could confuse the executor into thinking auth isn't wired. The acceptance criteria should clarify this is expected before the Task 2 restart.

- **MEDIUM** — E2E Step 3 uses `curl -v` on the `/authorize` endpoint. The `-v` (not `-L`) is intentional to see the 302 redirect, but this nuance should be documented to prevent confusion.

- **MEDIUM** — Step 2 (register) uses `redirect_uris: ["http://localhost:8888/callback"]`. If the SDK's registration handler rejects localhost URIs, the E2E test fails immediately. This is the standard Claude Desktop pattern and should work, but worth noting.

- **LOW** — `mount_path` acceptance criterion (`grep -c "mount_path" ... returns 0`) is hardcoded for the "strips" case. If "preserves" was returned from Plan 01, this check would need to return 1. The conditional branch in the plan text isn't reflected in the acceptance criteria.

- **LOW** — Behavior when `DOTMD_BASE_URL` is set but stdio transport is used is not documented. Auth middleware won't apply to stdio (correct), but worth a comment.

### Suggestions

- Add clarification to Task 1 acceptance criteria: "`mcp.auth_server_provider` will be `None` without `DOTMD_BASE_URL` in container env — expected; real verification is the E2E flow in Task 3 after Task 2 restart"
- Add a comment to E2E Step 3 noting `-v` (not `-L`) is intentional to observe the 302 redirect
- Consider a negative test: call `/mcp` with an **expired** token to verify `load_access_token()` returns `None`

### Risk Assessment: **MEDIUM**

Wiring is straightforward but E2E verification is fragile — multiple moving parts (Tailscale, container restart, PKCE flow). The `auth_provider: None` verification before restart could confuse the executor.

---

## Consensus Summary

### Overall Phase Risk: **MEDIUM**

### Agreed Strengths

- Wave ordering correct — A1 resolved in Plan 01 before any code written in Plans 02/03
- Backward compatibility preserved — auth completely opt-in via `DOTMD_BASE_URL`
- PKCE boundary is correct — SDK handles protocol, provider handles storage only
- Atomic JSON persistence with `asyncio.Lock()` is the right concurrency approach
- No new dependencies — everything in mcp 1.26.0 already installed
- Auto-approve pattern appropriate for single-user trusted Tailnet

### Agreed Concerns

1. **`resource` field not propagated to `AccessToken`** (HIGH, Plan 17-02) — RFC 8707 resource binding lost between auth code and token. Fix: add `resource=authorization_code.resource` in `exchange_authorization_code()`.

2. **Task 1 verification in Plan 17-03 prints `None` before container restart** (HIGH, Plan 17-03) — acceptance criteria will show `auth_provider: None` even when code is correct. Needs a clarifying note.

3. **No automated integration test for the OAuth flow** — E2E is entirely manual. A future smoke test covering auth would prevent regressions.

### Divergent Views

- Plan 17-01 Task 1 fallback: reviewer flagged that no fallback exists if container is down during verification. Not a blocker — container must be running to test OAuth anyway.

### Actionable Before Execution

1. **Fix Plan 17-02**: Add `resource=authorization_code.resource` to `AccessToken` construction in `exchange_authorization_code()`
2. **Fix Plan 17-03 Task 1**: Add acceptance criteria note that `auth_provider: None` before Task 2 restart is expected

To incorporate these fixes:
```
/gsd-plan-phase 17 --reviews
```
