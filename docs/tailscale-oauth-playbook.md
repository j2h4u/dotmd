# Tailscale OAuth MCP Playbook

This playbook describes the working pattern for exposing dotMD's HTTP MCP
server to Claude Desktop through Tailscale Funnel with OAuth 2.0.

Use it when Claude Desktop is configured through the hosted connector UI, not
through local stdio MCP config. Hosted connectors must reach the MCP URL from
Anthropic's infrastructure, so a tailnet-only `tailscale serve` endpoint is not
enough.

## What This Is

A playbook is an operational runbook: the exact known-good procedure, checks,
failure modes, and recovery steps. It exists to avoid rediscovering the same
OAuth, DNS, and Funnel behavior during future incidents.

## Known-Good Shape

Use one public Tailscale Funnel root proxy:

```text
https://senbonzakura.tailf87223.ts.net/
└── proxy http://127.0.0.1:18082
```

Use the root-based MCP URL:

```text
https://senbonzakura.tailf87223.ts.net/mcp
```

Set the OAuth public base URL without a path:

```env
DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net
```

Do not use a path-prefixed issuer such as:

```text
https://senbonzakura.tailf87223.ts.net/dotmd
```

Path-prefixed issuers require extra `/.well-known/.../dotmd/...` routes. Those
worked inside the tailnet but failed intermittently through public Funnel with
`502`, so the reliable production shape is a single root proxy.

## Security Model

Tailscale Funnel exposes the HTTP MCP origin to the public internet. Treat this
as an internet-facing service, not as tailnet-private infrastructure.

Public unauthenticated endpoints are limited to:

```text
GET  /
GET  /.well-known/oauth-authorization-server
GET  /.well-known/oauth-protected-resource/mcp
POST /register
GET  /authorize
POST /token
```

The MCP tool endpoint itself must require a bearer token:

```text
POST /mcp -> 401 without Authorization: Bearer ...
```

The critical hardening rule is: dynamic OAuth client registration must not
accept arbitrary redirect URIs. If arbitrary redirects are accepted, any internet
client can register itself, receive an authorization code at its own callback,
exchange it for a token, and then call `search`/`read` against the personal
knowledgebase.

dotMD therefore disables dynamic client registration by default and also
allowlists redirect URIs when registration is temporarily enabled.

Normal steady state:

```env
DOTMD_OAUTH_DYNAMIC_REGISTRATION=false
```

Initial connector setup or deliberate re-pairing:

```env
DOTMD_OAUTH_DYNAMIC_REGISTRATION=true
```

After Claude connects successfully, set it back to `false` and recreate the
container. Existing registered clients and refresh tokens continue to work.

The default allowed redirect URI is:

```text
https://claude.ai/api/mcp/auth_callback
```

Override only if adding another trusted hosted MCP client:

```env
DOTMD_OAUTH_ALLOWED_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback,https://trusted.example/callback
```

Security checks:

```bash
# Attacker callback must be rejected.
curl -i -X POST https://senbonzakura.tailf87223.ts.net/register \
  -H 'Content-Type: application/json' \
  -d '{"client_name":"evil","redirect_uris":["https://evil.example/callback"],"grant_types":["authorization_code","refresh_token"]}'

# Expected:
# HTTP/2 400
# {"error":"invalid_redirect_uri",...}

# With dynamic registration disabled, even a Claude callback must be rejected.
curl -i -X POST https://senbonzakura.tailf87223.ts.net/register \
  -H 'Content-Type: application/json' \
  -d '{"client_name":"Claude","redirect_uris":["https://claude.ai/api/mcp/auth_callback"],"grant_types":["authorization_code","refresh_token"]}'

# Expected in steady state:
# HTTP/2 400
# {"error":"invalid_client_metadata","error_description":"OAuth dynamic client registration is disabled"}

# Claude callback should be accepted only during intentional setup with
# DOTMD_OAUTH_DYNAMIC_REGISTRATION=true.
curl -i -X POST https://senbonzakura.tailf87223.ts.net/register \
  -H 'Content-Type: application/json' \
  -d '{"client_name":"Claude","redirect_uris":["https://claude.ai/api/mcp/auth_callback"],"grant_types":["authorization_code","refresh_token"]}'

# Expected:
# HTTP/2 201
```

## Required Endpoints

With `DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net`, FastMCP exposes:

```text
GET  /                                      health-style root response
GET  /.well-known/oauth-authorization-server
GET  /.well-known/oauth-protected-resource/mcp
GET  /authorize
POST /register
POST /token
POST /mcp
```

The connector URL entered in Claude Desktop is:

```text
https://senbonzakura.tailf87223.ts.net/mcp
```

Expected unauthenticated `/mcp` behavior is `401`, not `200`:

```text
HTTP/2 401
www-authenticate: Bearer ... resource_metadata="https://senbonzakura.tailf87223.ts.net/.well-known/oauth-protected-resource/mcp"
```

## Server Configuration

Production compose files live under:

```text
/opt/docker/dotmd/
```

Relevant env file:

```text
/opt/docker/dotmd/.env
```

Required value:

```env
DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net
```

During live network debugging, `ENVIRONMENT=prod` may be used in
`/opt/docker/dotmd/docker-compose.override.yml` to skip the pre-flight gate.
Restore `ENVIRONMENT=dev` after debugging if the deployment should run ruff,
pyright ratchet, and e2e smoke tests before serving.

Apply env changes:

```bash
docker compose \
  -f /opt/docker/dotmd/docker-compose.yml \
  -f /opt/docker/dotmd/docker-compose.override.yml \
  --env-file /opt/docker/dotmd/.env \
  up -d --force-recreate dotmd
```

Wait for health:

```bash
for i in $(seq 1 60); do
  if curl -fsS http://127.0.0.1:18082/health >/dev/null; then
    echo healthy
    break
  fi
  sleep 1
done
```

## Tailscale Funnel Configuration

Reset any old path-based routes:

```bash
printf 'y\n' | tailscale funnel reset
printf 'y\n' | tailscale serve reset
```

Start a single root Funnel:

```bash
tailscale funnel --bg --yes http://127.0.0.1:18082
```

Expected status:

```text
# Funnel on:
#     - https://senbonzakura.tailf87223.ts.net

https://senbonzakura.tailf87223.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:18082
```

Do not configure separate handlers like:

```text
/.well-known/oauth-authorization-server/dotmd
/.well-known/oauth-protected-resource/dotmd/mcp
/dotmd
```

Those routes are the failure-prone shape this playbook replaces.

## Smoke Tests

Run from the host:

```bash
curl -i https://senbonzakura.tailf87223.ts.net/
curl -i https://senbonzakura.tailf87223.ts.net/.well-known/oauth-authorization-server
curl -i https://senbonzakura.tailf87223.ts.net/.well-known/oauth-protected-resource/mcp
curl -i -H 'Accept: application/json, text/event-stream' \
  https://senbonzakura.tailf87223.ts.net/mcp
```

Expected results:

```text
/                                           200 {"status":"ok","service":"dotmd"}
/.well-known/oauth-authorization-server     200 issuer metadata
/.well-known/oauth-protected-resource/mcp   200 resource metadata
/mcp                                        401 Authentication required
```

Browser-side Claude connector checks need CORS preflight to pass:

```bash
curl -i -X OPTIONS \
  -H 'Origin: https://claude.ai' \
  -H 'Access-Control-Request-Method: POST' \
  -H 'Access-Control-Request-Headers: content-type,authorization' \
  https://senbonzakura.tailf87223.ts.net/mcp
```

Expected:

```text
HTTP/2 200
access-control-allow-origin: https://claude.ai
access-control-allow-methods: GET, POST, OPTIONS
```

Also verify from outside the tailnet. A local `curl` may resolve the name to the
tailnet IP (`100.x.x.x`) and bypass public Funnel behavior.

Public DNS should expose Tailscale edge addresses:

```bash
dig +trace +short senbonzakura.tailf87223.ts.net A | tail
dig +short senbonzakura.tailf87223.ts.net AAAA @1.1.1.1
```

Inside the tailnet, `getent hosts` may show the private tailnet IP. That is
normal, but it is not proof that Claude can reach the endpoint.

## Manual OAuth + MCP Verification

If Claude reports authorization failures, reproduce the full flow from a shell.
This confirms whether the server is broken or Claude is reusing stale connector
state.

```bash
cd backend
uv run python - <<'PY'
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

BASE = "https://senbonzakura.tailf87223.ts.net"
MCP = f"{BASE}/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

with httpx.Client(timeout=30.0, follow_redirects=False) as client:
    reg = client.post(f"{BASE}/register", json={
        "client_name": "dotmd-debug",
        "redirect_uris": ["https://claude.ai/api/mcp/auth_callback"],
        "grant_types": ["authorization_code", "refresh_token"],
    })
    print("register", reg.status_code)
    reg.raise_for_status()
    registration = reg.json()

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()

    auth = client.get(f"{BASE}/authorize?" + urlencode({
        "client_id": registration["client_id"],
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "response_type": "code",
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": "debug-state",
        "resource": MCP,
    }))
    print("authorize", auth.status_code, auth.headers.get("location"))
    code = parse_qs(urlparse(auth.headers["location"]).query)["code"][0]

    token = client.post(f"{BASE}/token", data={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": "https://claude.ai/api/mcp/auth_callback",
        "client_id": registration["client_id"],
        "client_secret": registration["client_secret"],
        "code_verifier": verifier,
    })
    print("token", token.status_code)
    token.raise_for_status()
    access = token.json()["access_token"]
    headers = {**HEADERS, "Authorization": f"Bearer {access}"}

    calls = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "dotmd-debug", "version": "0"},
        }},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 2, "method": "resources/list", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "prompts/list", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list", "params": {}},
    ]

    for body in calls:
        response = client.post(MCP, headers=headers, json=body)
        print("mcp", body.get("method"), response.status_code, response.text[:300])
        response.raise_for_status()
PY
```

Expected final sequence:

```text
register 201
authorize 302
token 200
mcp initialize 200
mcp notifications/initialized 202
mcp resources/list 200
mcp prompts/list 200
mcp tools/list 200
```

## Reading Logs

dotMD access logs:

```bash
docker logs -f dotmd 2>&1 | rg 'dotmd.mcp_server: HTTP|dotmd.auth|OAuth|ERROR|WARNING'
```

Useful successful sequence from Claude:

```text
POST /mcp 401
GET  /.well-known/oauth-protected-resource/mcp 200
GET  /.well-known/openid-configuration 404
POST /register 201
GET  /authorize?... 302
GET  /.well-known/oauth-authorization-server 200
POST /token 200
POST /mcp 200
POST /mcp 202
POST /mcp 200  # resources/list, prompts/list, tools/list
```

The `/.well-known/openid-configuration 404` probe is harmless. Claude tries it,
then falls back to OAuth authorization server metadata.

Tailscale logs:

```bash
sudo journalctl -u tailscaled -f
```

Tailscale logs are useful for proxy errors and config changes, but they are not
a complete access log. dotMD's access middleware is the authoritative source for
which HTTP paths reached the application after proxying.

## Common Failures

### `Couldn't reach the MCP server`

Likely causes:

- Only `tailscale serve` is enabled, not `tailscale funnel`.
- Funnel has path-based handlers that return `502` from the public edge.
- The connector URL still points at the old `/dotmd/mcp` path.

Fix:

```bash
printf 'y\n' | tailscale funnel reset
printf 'y\n' | tailscale serve reset
tailscale funnel --bg --yes http://127.0.0.1:18082
```

Then use:

```text
https://senbonzakura.tailf87223.ts.net/mcp
```

### `Authorization with the MCP server failed`

If logs show `POST /token 200` and subsequent `POST /mcp 200`, server-side
authorization succeeded. The usual cause is stale connector credentials in
Claude from a previous URL.

Fix:

1. Delete the old connector in Claude.
2. Clear dotMD OAuth state if needed:

```bash
ts=$(date +%Y%m%d%H%M%S)
docker exec dotmd sh -lc \
  "cp /dotmd-index/oauth_state.json /dotmd-index/oauth_state.json.bak-$ts 2>/dev/null || true; rm -f /dotmd-index/oauth_state.json"
docker restart dotmd
```

3. Recreate the connector with:

```text
https://senbonzakura.tailf87223.ts.net/mcp
```

### Public checks fail but local checks pass

Local checks may use tailnet DNS and bypass Funnel:

```bash
getent hosts senbonzakura.tailf87223.ts.net
```

If this returns `100.x.x.x`, it proves only tailnet reachability. Test public
Tailscale edge behavior with public DNS or from a non-tailnet environment.

### `/mcp` returns `401`

This is correct before OAuth. It means the resource server is reachable and is
advertising the OAuth metadata URL.

### Path-prefixed `/dotmd/mcp` worked earlier but now fails

Do not use it for hosted Claude connectors. The reliable Funnel configuration is
root-based:

```text
DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net
MCP URL=https://senbonzakura.tailf87223.ts.net/mcp
```

## Cleanup Checklist

After a debugging session:

1. Ensure no temporary tunnel remains:

```bash
docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}' | rg 'cloudflare|cloudflared|dotmd'
```

Only `dotmd` should remain.

2. Ensure Funnel is simple:

```bash
tailscale funnel status
```

Expected:

```text
https://senbonzakura.tailf87223.ts.net (Funnel on)
|-- / proxy http://127.0.0.1:18082
```

3. Ensure production env is root-based:

```bash
grep '^DOTMD_BASE_URL=' /opt/docker/dotmd/.env
```

Expected:

```text
DOTMD_BASE_URL=https://senbonzakura.tailf87223.ts.net
```

4. Restore pre-flight if it was disabled:

```yaml
ENVIRONMENT: dev
```

in:

```text
/opt/docker/dotmd/docker-compose.override.yml
```

5. Recreate the container after env changes.
