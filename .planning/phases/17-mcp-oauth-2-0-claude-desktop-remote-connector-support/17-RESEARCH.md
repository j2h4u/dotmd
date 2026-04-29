# Phase 17: MCP OAuth 2.0 — Research

**Researched:** 2026-04-29
**Domain:** MCP SDK auth, OAuth 2.0 PKCE flow, FastMCP wiring
**Confidence:** HIGH — all key findings verified directly from installed SDK source at `.venv/lib/python3.12/site-packages/mcp/`

## Summary

The MCP Python SDK 1.26.0 ships a complete OAuth 2.0 Authorization Server implementation under `mcp.server.auth`. FastMCP accepts an `auth_server_provider` + `auth=AuthSettings(...)` pair and automatically wires up all auth routes (`/.well-known/oauth-authorization-server`, `/authorize`, `/token`, `/register`, `/revoke`) and Bearer-token middleware. The SDK handles PKCE validation, token expiry checks, redirect-URI matching, and client secret generation — the provider only needs to store and retrieve the objects.

For a single-user trusted-network setup, the `authorize()` method can immediately generate an auth code and redirect back to the client's `redirect_uri` with no user interaction. Dynamic client registration (RFC 7591) is the mechanism Claude Desktop uses — it POSTs to `/register` before the first auth flow. The SDK handler generates `client_id` and `client_secret` automatically; the provider's `register_client()` just persists the `OAuthClientInformationFull` object.

The main change to `mcp_server.py` is: re-instantiate `mcp = FastMCP(...)` with two new kwargs (`auth_server_provider=` and `auth=AuthSettings(...)`), reading `DOTMD_BASE_URL` at module import time. The provider class lives in a new `src/dotmd/auth.py` file and is ~130–160 lines of JSON-backed storage.

**Primary recommendation:** Implement `DotMDOAuthProvider` in `auth.py` with JSON persistence at `/dotmd-index/oauth_state.json`, wire into `mcp` constructor, expose `DOTMD_BASE_URL` as a required env var (fail-fast if absent when auth is configured).

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| OAuth AS metadata endpoint | MCP HTTP server (port 8080) | — | `create_auth_routes()` adds `/.well-known/oauth-authorization-server` automatically |
| Dynamic client registration | MCP HTTP server | — | SDK handler at `/register`; provider stores client |
| Authorization endpoint + auto-redirect | MCP HTTP server | — | SDK handler calls `provider.authorize()` which returns redirect URL |
| PKCE code-challenge verification | MCP SDK (token handler) | — | SDK verifies SHA256(verifier)==challenge before calling `exchange_authorization_code` |
| Token issuance | Provider (`exchange_authorization_code`) | — | Provider generates tokens and stores them |
| Bearer token verification | MCP SDK middleware | Provider (`load_access_token`) | SDK middleware calls `provider.load_access_token(token)` per request |
| OAuth state persistence | Docker volume (`/dotmd-index/`) | — | JSON file survives container restarts; same volume as `index.db` |
| URL routing (Tailscale) | Tailscale Serve (`/dotmd` → 127.0.0.1:18082) | — | Already configured; all OAuth paths served under `https://senbonzakura.tailf87223.ts.net/dotmd/` |

## Standard Stack

### Core (already installed)

| Library | Version | Purpose | Source |
|---------|---------|---------|--------|
| `mcp[server]` | 1.26.0 (installed) | FastMCP + auth module | [VERIFIED: `.venv/lib/python3.12/site-packages/mcp/`] |
| `pydantic` | v2 (in use) | Model serialization for JSON state | [VERIFIED: existing codebase] |
| `secrets` (stdlib) | — | Cryptographic token generation | [VERIFIED: SDK uses it in `register.py`] |

No new dependencies required. Everything needed is already present.

**Version verification:** MCP 1.26.0 confirmed present and `mcp.server.auth` module confirmed present at `.venv/lib/python3.12/site-packages/mcp/server/auth/`. [VERIFIED: filesystem]

## Architecture Patterns

### System Architecture Diagram

```
Claude Desktop
     |
     | HTTPS (Tailscale)
     v
Tailscale Serve: senbonzakura.tailf87223.ts.net
  /dotmd → 127.0.0.1:18082
     |
     v
dotmd container (port 8080 → host 18082)
  FastMCP (streamable-http)
     |
     +-- /.well-known/oauth-authorization-server  [SDK: MetadataHandler]
     +-- /register  [SDK: RegistrationHandler → provider.register_client()]
     +-- /authorize [SDK: AuthorizationHandler → provider.authorize() → immediate redirect]
     +-- /token     [SDK: TokenHandler (PKCE verify) → provider.exchange_authorization_code()]
     +-- /mcp       [SDK: RequireAuthMiddleware → provider.load_access_token() → MCP tools]
     |
     v
DotMDOAuthProvider
     |
     v
/dotmd-index/oauth_state.json  (docker volume, persistent)
```

### Recommended File Structure

```
backend/src/dotmd/
  auth.py          # NEW — DotMDOAuthProvider (~150 lines)
  mcp_server.py    # MODIFIED — re-wire FastMCP constructor (~15 lines changed)
  core/config.py   # MODIFIED — add base_url field
```

### Pattern 1: FastMCP constructor wiring

**What:** Pass `auth_server_provider` and `auth=AuthSettings(...)` to the existing `mcp = FastMCP(...)` instantiation. The SDK then automatically creates all auth routes and wraps `/mcp` with `RequireAuthMiddleware`.

**Critical detail:** `issuer_url` must be the BASE URL where the OAuth endpoints are served — i.e., `https://senbonzakura.tailf87223.ts.net/dotmd` (with the `/dotmd` path prefix). The SDK builds endpoints as `issuer_url + "/authorize"`, `issuer_url + "/token"` etc., so the prefix must be included. `resource_server_url` is the MCP endpoint itself: `https://senbonzakura.tailf87223.ts.net/dotmd/mcp`.

[VERIFIED: `mcp/server/auth/routes.py` line 156: `authorization_url = AnyHttpUrl(str(issuer_url).rstrip("/") + AUTHORIZATION_PATH)`]

```python
# Source: mcp/server/fastmcp/server.py lines 147-176, auth/routes.py lines 156-184
import os
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions

_base_url = os.environ.get("DOTMD_BASE_URL", "")  # e.g. https://senbonzakura.tailf87223.ts.net/dotmd

mcp = FastMCP(
    "dotmd",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=8080,
    json_response=True,
    stateless_http=True,
    auth_server_provider=_provider if _base_url else None,
    auth=AuthSettings(
        issuer_url=_base_url,
        resource_server_url=f"{_base_url}/mcp",
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["dotmd"],
            default_scopes=["dotmd"],
        ),
    ) if _base_url else None,
)
```

**Important:** `_provider` must be instantiated BEFORE `mcp = FastMCP(...)` since it's passed to the constructor. The provider itself is stateless at init time (it loads from JSON on first use).

### Pattern 2: `OAuthAuthorizationServerProvider` — all required methods

All 8 methods of the Protocol must be implemented (Python Protocol does not enforce at class definition but the SDK calls them all):

[VERIFIED: `mcp/server/auth/provider.py` lines 106-275]

| Method | Called by | Required action |
|--------|-----------|----------------|
| `get_client(client_id)` | Authorize handler, Token handler | Load `OAuthClientInformationFull` from JSON by `client_id` |
| `register_client(client_info)` | Registration handler | Persist `OAuthClientInformationFull` to JSON |
| `authorize(client, params)` | Authorization handler | Generate auth code, store it, return redirect URL to `params.redirect_uri` |
| `load_authorization_code(client, code)` | Token handler | Load `AuthorizationCode` from JSON by code string |
| `exchange_authorization_code(client, auth_code)` | Token handler (after PKCE verified) | Delete auth code, generate access+refresh tokens, persist, return `OAuthToken` |
| `load_refresh_token(client, refresh_token)` | Token handler | Load `RefreshToken` from JSON |
| `exchange_refresh_token(client, refresh_token, scopes)` | Token handler | Rotate tokens, return new `OAuthToken` |
| `load_access_token(token)` | BearerAuthBackend middleware (per request) | Load `AccessToken` from JSON, check expiry |
| `revoke_token(token)` | Revocation handler | Delete token(s) from JSON |

**PKCE validation is done entirely by the SDK** (token handler, lines 175–185 of `token.py`): `sha256(code_verifier) == auth_code.code_challenge`. The provider only needs to store `code_challenge` in the `AuthorizationCode` object and return it faithfully from `load_authorization_code()`. [VERIFIED: `mcp/server/auth/handlers/token.py`]

### Pattern 3: `authorize()` auto-redirect implementation

The `authorize()` method must:
1. Generate a cryptographically secure auth code (`secrets.token_urlsafe(32)` gives 256 bits — exceeds 128-bit minimum)
2. Store an `AuthorizationCode` object with all required fields (including `code_challenge` from params)
3. Return a redirect URL to `params.redirect_uri` with `code=<code>` and `state=<params.state>` as query params

The SDK expects `authorize()` to return a `str` URL. Use the SDK's `construct_redirect_uri()` helper.

[VERIFIED: `mcp/server/auth/provider.py` line 135 — `async def authorize(...) -> str`; `handlers/authorize.py` line 207–214 — SDK does `RedirectResponse(url=await self.provider.authorize(...))`]

```python
# Source: mcp/server/auth/provider.py construct_redirect_uri()
from mcp.server.auth.provider import construct_redirect_uri, AuthorizationCode
import secrets, time

async def authorize(self, client, params):
    code = secrets.token_urlsafe(32)  # 256 bits entropy
    auth_code = AuthorizationCode(
        code=code,
        scopes=params.scopes or ["dotmd"],
        expires_at=time.time() + 300,   # 5 minutes — SDK checks this in token handler
        client_id=client.client_id,
        code_challenge=params.code_challenge,
        redirect_uri=params.redirect_uri,
        redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        resource=params.resource,
    )
    self._save_auth_code(auth_code)
    return construct_redirect_uri(
        str(params.redirect_uri),
        code=code,
        state=params.state,
    )
```

### Pattern 4: Token persistence — what to store in JSON

`OAuthClientInformationFull`, `AuthorizationCode`, `AccessToken`, and `RefreshToken` are all Pydantic BaseModel subclasses. Use `.model_dump()` / `model_validate()` for JSON round-trip.

[VERIFIED: `mcp/server/auth/provider.py` — all four are `BaseModel`]

Recommended JSON structure for `oauth_state.json`:

```json
{
  "clients": { "<client_id>": { ...OAuthClientInformationFull fields... } },
  "auth_codes": { "<code>": { ...AuthorizationCode fields... } },
  "access_tokens": { "<token>": { ...AccessToken fields... } },
  "refresh_tokens": { "<token>": { ...RefreshToken fields... } }
}
```

**Concurrency note:** `load_access_token()` is called on every MCP request (hot path). The JSON file should be loaded once at provider init and kept in-memory dict, with writes flushed to disk atomically on mutation. Use `json.dump()` to a temp file + `os.replace()` for atomicity. Do NOT read JSON from disk on every `load_access_token()` call.

### Pattern 5: Dynamic client registration — required by Claude Desktop

Claude Desktop performs dynamic client registration (RFC 7591) before the first auth flow. It POSTs client metadata to `/register`. The SDK's `RegistrationHandler` generates `client_id` (UUID4) and `client_secret` (64-char hex), then calls `provider.register_client(client_info)`.

To enable: set `ClientRegistrationOptions(enabled=True)` in `AuthSettings`. [VERIFIED: `mcp/server/auth/routes.py` line 118 — registration route added only if `client_registration_options.enabled`]

**Alternative (pre-registered client):** You can skip dynamic registration by hardcoding a client in `oauth_state.json` at startup and setting `ClientRegistrationOptions(enabled=False)`. However, Claude Desktop's remote connector flow expects to be able to register dynamically. The safer choice is `enabled=True` — any Tailnet user who reaches the server can register, which is fine under the single-user trusted-network threat model.

### Pattern 6: `/.well-known/oauth-authorization-server` — SDK auto-generated

The SDK builds this metadata document automatically from the `AuthSettings` parameters. Fields auto-populated:

- `issuer` = `issuer_url`
- `authorization_endpoint` = `issuer_url + "/authorize"`
- `token_endpoint` = `issuer_url + "/token"`
- `registration_endpoint` = `issuer_url + "/register"` (when `client_registration_options.enabled=True`)
- `code_challenge_methods_supported` = `["S256"]`
- `grant_types_supported` = `["authorization_code", "refresh_token"]`

[VERIFIED: `mcp/server/auth/routes.py` `build_metadata()` function, lines 150–187]

No code needed in the provider for this. The SDK serves it at the exact path Claude Desktop probes.

### Pattern 7: `DOTMD_BASE_URL` — path prefix required

`issuer_url` must include the `/dotmd` path prefix because:
1. Tailscale Serve maps `/dotmd` → `127.0.0.1:18082` (confirmed by `tailscale serve status`)
2. Claude Desktop discovers the auth server by fetching `<mcp_server_url>/.well-known/...`
3. The SDK appends `/authorize`, `/token` etc. directly to `issuer_url`

So `DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net/dotmd` is correct.

The OAuth metadata endpoint will be at `https://senbonzakura.tailf87223.ts.net/dotmd/.well-known/oauth-authorization-server`. The MCP endpoint remains at `https://senbonzakura.tailf87223.ts.net/dotmd/mcp`.

[VERIFIED: Tailscale Serve config shows `/dotmd → 127.0.0.1:18082`; FastMCP's `streamable_http_path` defaults to `/mcp` so full path is `/dotmd/mcp`]

### Pattern 8: `create_app()` compatibility

The current `create_app()` in `mcp_server.py` manually composes a Starlette app by calling `mcp.streamable_http_app()` and replacing the lifespan. After adding auth, `mcp.streamable_http_app()` will return a Starlette app that already includes the auth routes. The `create_app()` function copies the routes from this app — it must continue to copy ALL routes (including the new auth routes). The existing route-copying pattern (`routes=mcp_starlette.routes`) will pick them up automatically since `streamable_http_app()` assembles all routes into the Starlette app. [VERIFIED: `fastmcp/server.py` lines 950–1044 — `streamable_http_app()` builds full route list including auth routes when `auth_server_provider` is set]

### Anti-Patterns to Avoid

- **Reading JSON from disk per request:** `load_access_token()` is on the hot path (every MCP call). Load once at startup, keep in-memory, flush on write.
- **Returning `None` from unimplemented methods:** All 9 methods must be implemented. The Protocol doesn't enforce at class-definition time, but the SDK calls them all.
- **Using `expires_at=None` for access tokens:** The bearer middleware calls `load_access_token()` and the SDK does NOT check expiry itself — you must check `expires_at` inside `load_access_token()` and return `None` for expired tokens. [VERIFIED: `provider.py` `ProviderTokenVerifier.verify_token()` just delegates to `load_access_token()`]
- **Setting `issuer_url` to just the domain:** Must include `/dotmd` path or auth endpoints will 404 through Tailscale Serve.
- **Non-HTTPS issuer URL:** SDK validates HTTPS (except localhost). `senbonzakura.tailf87223.ts.net` is HTTPS via Tailscale. [VERIFIED: `routes.py` `validate_issuer_url()` lines 24–41]
- **Calling `mcp = FastMCP(auth_server_provider=...)` without `auth=AuthSettings(...)`:** Both must be present together — SDK raises ValueError if only one is set. [VERIFIED: `server.py` lines 218–224]

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| PKCE verification | Custom SHA256 check | SDK token handler | SDK does `sha256(verifier) == challenge` automatically before calling `exchange_authorization_code()` |
| OAuth metadata document | Custom `/.well-known/` handler | `create_auth_routes()` | SDK builds and serves the full RFC 8414 metadata document |
| Client registration protocol | Custom `/register` endpoint | `ClientRegistrationOptions(enabled=True)` | SDK generates client_id, client_secret, validates grant_types |
| Token entropy | Custom random generator | `secrets.token_urlsafe(32)` | stdlib, cryptographically secure, 256 bits |
| Redirect URI construction | Manual URL building | `construct_redirect_uri()` from `mcp.server.auth.provider` | Handles existing query params correctly |
| Bearer middleware | Custom auth middleware | FastMCP's automatic wiring via `token_verifier` | SDK wraps `/mcp` with `RequireAuthMiddleware` automatically |

**Key insight:** The SDK implements the entire OAuth 2.0 AS protocol. The provider is only a storage backend — serialize/deserialize Pydantic models to/from JSON.

## Runtime State Inventory

This is a greenfield auth feature, not a rename/refactor phase. No existing runtime state is involved.

However, note: after OAuth is wired in, the `stateless_http=True` setting on the `mcp` FastMCP instance means the SDK treats each POST as independent. This is compatible with `RequireAuthMiddleware` (bearer token checked per request) but means no SSE push. This is already the current architecture choice and is unchanged.

## Common Pitfalls

### Pitfall 1: Tailscale Serve path stripping

**What goes wrong:** OAuth redirect URIs and metadata discovery break if the `/dotmd` prefix is stripped or double-added.

**Why it happens:** Tailscale Serve with `/dotmd → http://127.0.0.1:18082` forwards requests AS-IS — it does NOT strip the `/dotmd` prefix. The container receives the full path `/dotmd/authorize`, `/dotmd/mcp` etc.

**How to avoid:** FastMCP mounts auth routes at the top level of the Starlette router (e.g., `/authorize`), not under `/dotmd/`. The Starlette router sees the path that the container receives. Since Tailscale Serve preserves the prefix, the container sees `/dotmd/authorize` but the FastMCP router only knows about `/authorize` — this is a **path mismatch**.

**Resolution:** Use FastMCP's `mount_path="/dotmd"` option OR configure `streamable_http_path="/dotmd/mcp"` and prefix all auth paths. Check: `FastMCP.__init__` accepts `mount_path: str = "/"`. Setting `mount_path="/dotmd"` would prefix all routes including auth routes. Alternatively, deploy a reverse proxy (nginx/Caddy) that strips `/dotmd` before forwarding to the container — but that adds complexity.

**Verified approach:** Check how Tailscale Serve actually delivers the path to the upstream, then decide on mount_path. [ASSUMED — Tailscale Serve path preservation behavior needs verification; see Open Questions #1]

### Pitfall 2: Token expiry not SDK-enforced for access tokens

**What goes wrong:** Expired access tokens continue to work.

**Why it happens:** The SDK's `ProviderTokenVerifier.verify_token()` just calls `provider.load_access_token(token)` and trusts whatever comes back. If `load_access_token()` returns an `AccessToken` with `expires_at` in the past, the SDK uses it.

**How to avoid:** Check `expires_at` inside `load_access_token()` and return `None` for expired tokens.

[VERIFIED: `provider.py` lines 288–301 — `ProviderTokenVerifier` does no expiry check itself]

### Pitfall 3: Auth code expiry is SDK-enforced

**What goes wrong:** Assuming auth codes never expire — they do.

**Why it happens:** The SDK token handler checks `auth_code.expires_at < time.time()` and returns `invalid_grant` if expired.

**How to avoid:** Set `expires_at = time.time() + 300` (5 minutes is standard). Clean up expired auth codes from the JSON on next write to keep the file tidy.

[VERIFIED: `handlers/token.py` lines 144–150]

### Pitfall 4: `stateless_http=True` and SSE sessions

**What goes wrong:** OAuth notifications (`notifications/tools/list_changed`) cannot be sent because there's no persistent SSE connection.

**Why it happens:** `stateless_http=True` is a pre-existing architecture choice (Phase 999.13 in backlog). Auth does not change this.

**How to avoid:** This is a known limitation already tracked as Phase 999.13. Don't let it block Phase 17. OAuth works fine with stateless HTTP — bearer token is checked on every POST.

### Pitfall 5: `mcp = FastMCP(...)` called at module import time

**What goes wrong:** If `DOTMD_BASE_URL` is not set in the environment when the module is imported, and auth provider instantiation is unconditional, the import fails.

**Why it happens:** `mcp = FastMCP(...)` is at module scope, executed on `import dotmd.mcp_server`.

**How to avoid:** Make auth conditional: `auth_server_provider = DotMDOAuthProvider(...)` only if `DOTMD_BASE_URL` is set, and pass `None` otherwise. This keeps the module importable without the env var (e.g., for stdio mode where auth is not needed).

### Pitfall 6: JSON file concurrency with async handlers

**What goes wrong:** Concurrent `load_access_token()` calls race with `register_client()` writes, corrupting `oauth_state.json`.

**Why it happens:** Auth handlers are async; if multiple requests hit simultaneously, both could read then write.

**How to avoid:** Use `asyncio.Lock()` on the provider instance to serialize all JSON reads/writes. The file itself is small (few clients, few tokens) so lock contention is negligible.

## Code Examples

### Minimal provider skeleton

```python
# Source: mcp/server/auth/provider.py — Protocol definition
import asyncio, json, os, secrets, time
from pathlib import Path
from mcp.server.auth.provider import (
    OAuthAuthorizationServerProvider,
    AuthorizationCode, AccessToken, RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

class DotMDOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, state_path: Path) -> None:
        self._path = state_path
        self._lock = asyncio.Lock()
        self._state: dict = {"clients": {}, "auth_codes": {}, "access_tokens": {}, "refresh_tokens": {}}
        if state_path.exists():
            self._state = json.loads(state_path.read_text())

    # --- storage helpers ---
    async def _flush(self) -> None:
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, indent=2, default=str))
        os.replace(tmp, self._path)

    # --- Protocol methods ---
    async def get_client(self, client_id: str) -> OAuthClientInformationFull | None:
        data = self._state["clients"].get(client_id)
        return OAuthClientInformationFull.model_validate(data) if data else None

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        async with self._lock:
            self._state["clients"][client_info.client_id] = client_info.model_dump(mode="json")
            await self._flush()

    async def authorize(self, client: OAuthClientInformationFull, params) -> str:
        code = secrets.token_urlsafe(32)
        auth_code = AuthorizationCode(
            code=code, scopes=params.scopes or ["dotmd"],
            expires_at=time.time() + 300,
            client_id=client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
        )
        async with self._lock:
            self._state["auth_codes"][code] = auth_code.model_dump(mode="json")
            await self._flush()
        return construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)

    async def load_authorization_code(self, client, code: str) -> AuthorizationCode | None:
        data = self._state["auth_codes"].get(code)
        return AuthorizationCode.model_validate(data) if data else None

    async def exchange_authorization_code(self, client, auth_code: AuthorizationCode) -> OAuthToken:
        access = secrets.token_urlsafe(32)
        refresh = secrets.token_urlsafe(32)
        exp = int(time.time()) + 86400 * 30  # 30-day access token
        async with self._lock:
            del self._state["auth_codes"][auth_code.code]
            self._state["access_tokens"][access] = AccessToken(
                token=access, client_id=client.client_id,
                scopes=auth_code.scopes, expires_at=exp,
            ).model_dump(mode="json")
            self._state["refresh_tokens"][refresh] = RefreshToken(
                token=refresh, client_id=client.client_id,
                scopes=auth_code.scopes,
            ).model_dump(mode="json")
            await self._flush()
        return OAuthToken(access_token=access, token_type="Bearer",
                          expires_in=86400 * 30, refresh_token=refresh)

    async def load_access_token(self, token: str) -> AccessToken | None:
        data = self._state["access_tokens"].get(token)
        if not data:
            return None
        at = AccessToken.model_validate(data)
        if at.expires_at and at.expires_at < time.time():
            return None  # expired — must check here; SDK doesn't
        return at

    async def load_refresh_token(self, client, token: str) -> RefreshToken | None:
        data = self._state["refresh_tokens"].get(token)
        return RefreshToken.model_validate(data) if data else None

    async def exchange_refresh_token(self, client, refresh_token: RefreshToken, scopes: list[str]) -> OAuthToken:
        # rotate both tokens
        new_access = secrets.token_urlsafe(32)
        new_refresh = secrets.token_urlsafe(32)
        exp = int(time.time()) + 86400 * 30
        async with self._lock:
            del self._state["refresh_tokens"][refresh_token.token]
            # also invalidate old access tokens for this client (optional but good practice)
            self._state["access_tokens"][new_access] = AccessToken(
                token=new_access, client_id=client.client_id,
                scopes=scopes, expires_at=exp,
            ).model_dump(mode="json")
            self._state["refresh_tokens"][new_refresh] = RefreshToken(
                token=new_refresh, client_id=client.client_id, scopes=scopes,
            ).model_dump(mode="json")
            await self._flush()
        return OAuthToken(access_token=new_access, token_type="Bearer",
                          expires_in=86400 * 30, refresh_token=new_refresh)

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        async with self._lock:
            self._state["access_tokens"].pop(token.token if hasattr(token, "token") else "", None)
            self._state["refresh_tokens"].pop(token.token if hasattr(token, "token") else "", None)
            await self._flush()
```

### FastMCP constructor wiring

```python
# Source: mcp/server/fastmcp/server.py __init__ signature lines 147-176
import os
from pathlib import Path
from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
from dotmd.auth import DotMDOAuthProvider

_base_url = os.environ.get("DOTMD_BASE_URL", "").rstrip("/")

_provider: DotMDOAuthProvider | None = None
if _base_url:
    _provider = DotMDOAuthProvider(Path("/dotmd-index/oauth_state.json"))

mcp = FastMCP(
    "dotmd",
    instructions=_INSTRUCTIONS,
    host="0.0.0.0",
    port=8080,
    json_response=True,
    stateless_http=True,
    auth_server_provider=_provider,
    auth=AuthSettings(
        issuer_url=_base_url,                  # e.g. https://senbonzakura.tailf87223.ts.net/dotmd
        resource_server_url=f"{_base_url}/mcp", # e.g. https://.../dotmd/mcp
        client_registration_options=ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["dotmd"],
            default_scopes=["dotmd"],
        ),
    ) if _base_url else None,
)
```

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| Stdio-only MCP (config file) | Remote MCP via OAuth 2.0 (UI-based connector) | Claude Desktop connects without config-file editing |
| No auth | Bearer token on every MCP request | Tailnet-only but cryptographically authenticated |
| MCP SDK 1.x (no auth) | MCP SDK 1.26.0 (`mcp.server.auth` module) | Full AS implementation, no custom OAuth code needed |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Tailscale Serve does NOT strip the `/dotmd` prefix before forwarding to `127.0.0.1:18082` | Pitfall 1, Pattern 7 | If Tailscale DOES strip the prefix, `mount_path="/dotmd"` is not needed and would BREAK routing (double prefix). Must verify before coding `mount_path`. |
| A2 | Claude Desktop's remote connector uses dynamic client registration (RFC 7591) rather than a pre-configured client | Pattern 5 | If Claude Desktop uses a fixed client_id, `ClientRegistrationOptions(enabled=False)` with a seeded client would be cleaner. |
| A3 | `stateless_http=True` is compatible with OAuth bearer token auth in `RequireAuthMiddleware` | Anti-pattern 4 | If stateless mode bypasses `RequireAuthMiddleware`, auth would silently not apply. |

**A1 is the highest-risk assumption.** It determines whether `mount_path="/dotmd"` is needed in the `FastMCP` constructor.

## Open Questions

1. **Does Tailscale Serve strip the `/dotmd` prefix?**
   - What we know: `tailscale serve status` shows `/dotmd → proxy http://127.0.0.1:18082`. The current MCP endpoint at `/dotmd/mcp` works, implying Tailscale does NOT strip.
   - What's unclear: Whether this is "no stripping" or the container is configured to handle `/dotmd/mcp` paths. FastMCP currently mounts at `streamable_http_path="/mcp"` but the working URL is `.../dotmd/mcp`.
   - Recommendation: Before coding, verify with `curl -v https://senbonzakura.tailf87223.ts.net/dotmd/health` and check what path the container logs. If container sees `/dotmd/health`, Tailscale does NOT strip — and `mount_path="/dotmd"` IS needed so auth routes mount at `/dotmd/authorize` etc. If container sees `/health`, Tailscale DOES strip — current auth route mounting at `/authorize` is correct.

2. **Token lifetime: how long should access tokens live?**
   - What we know: Single-user trusted-network deployment; no revocation needed for security (anyone with Tailnet access can re-authenticate anyway).
   - Recommendation: 30-day access tokens with no-expiry refresh tokens is reasonable. Planner can adjust.

3. **Should `DOTMD_BASE_URL` be required or optional at startup?**
   - What we know: Without it, auth is disabled and the server works as before (stdio + stateless HTTP without auth). This is useful for local dev.
   - Recommendation: Optional with auth disabled when absent — matches current behavior where the server works without auth for Hermes (which connects via stdio or internal Docker network).

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| `mcp.server.auth` module | OAuth provider wiring | Yes | 1.26.0 | — |
| `/dotmd-index/` writable | JSON state persistence | Yes (docker volume, container runs as root) | — | — |
| Tailscale Serve at `/dotmd` | HTTPS endpoint for Claude Desktop | Yes | — | — |
| `secrets` stdlib | Token generation | Yes (Python stdlib) | — | — |

No missing dependencies.

## Sources

### Primary (HIGH confidence — verified from installed SDK source)

- `mcp/server/auth/provider.py` — `OAuthAuthorizationServerProvider` Protocol, all 9 method signatures, `AuthorizationCode`/`AccessToken`/`RefreshToken` fields, `construct_redirect_uri()`
- `mcp/server/auth/settings.py` — `AuthSettings`, `ClientRegistrationOptions` fields
- `mcp/server/auth/routes.py` — `create_auth_routes()`, `build_metadata()`, `validate_issuer_url()`, route paths
- `mcp/server/auth/handlers/token.py` — PKCE verification (lines 175–185), expiry check (lines 144–150)
- `mcp/server/auth/handlers/register.py` — dynamic client registration flow, client_id/secret generation
- `mcp/server/auth/handlers/authorize.py` — `AuthorizationRequest` model, handler calls `provider.authorize()`
- `mcp/server/auth/handlers/revoke.py` — `provider.revoke_token()` call pattern
- `mcp/server/fastmcp/server.py` — `FastMCP.__init__` signature (lines 147–176), auth wiring in `streamable_http_app()` (lines 974–1036)
- `mcp/shared/auth.py` — `OAuthClientInformationFull`, `OAuthToken`, `OAuthMetadata` fields
- `tailscale serve status` output — confirmed `/dotmd → 127.0.0.1:18082`
- `/opt/docker/dotmd/docker-compose.override.yml` — port mapping `127.0.0.1:18082:8080`
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/mcp_server.py` — current `FastMCP` constructor, `create_app()` pattern

## Metadata

**Confidence breakdown:**
- FastMCP auth wiring: HIGH — verified from source
- Provider Protocol (all methods): HIGH — verified from source
- PKCE handling boundary: HIGH — verified from token.py
- Tailscale path handling (A1): ASSUMED — behavioral inference from working MCP endpoint
- Claude Desktop dynamic registration (A2): ASSUMED — standard MCP remote connector behavior
- `stateless_http` + auth compat (A3): ASSUMED — logical but not explicitly traced in SDK source

**Research date:** 2026-04-29
**Valid until:** 60 days (MCP auth module is new but SDK is pinned at 1.26.0 in the project)
