# Tailscale OAuth MCP Playbook

This playbook describes the working pattern for exposing dotMD's HTTP MCP
server to hosted MCP connector clients such as ChatGPT and Claude through
Tailscale Funnel with OAuth 2.0.

Use it when a connector is configured through a hosted web UI, not through local
stdio MCP config. Hosted connectors must reach the MCP URL from the provider's
infrastructure, so a tailnet-only `tailscale serve` endpoint is not enough.

## What This Is

A playbook is an operational runbook: the exact known-good procedure, checks,
failure modes, and recovery steps. It exists to avoid rediscovering the same
OAuth, DNS, and Funnel behavior during future incidents.

## Known-Good Shape

For one MCP server, use one public Tailscale Funnel root proxy:

```text
https://dotmd.tailf87223.ts.net/
└── proxy http://dotmd:8080
```

Use the root-based MCP URL:

```text
https://dotmd.tailf87223.ts.net/mcp
```

Set the OAuth public base URL without a path:

```env
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
```

Do not use a path-prefixed issuer such as:

```text
https://dotmd.tailf87223.ts.net/dotmd
```

Path-prefixed issuers require extra `/.well-known/.../dotmd/...` routes. Those
worked inside the tailnet but failed intermittently through public Funnel with
`502`, so the reliable production shape is a single root proxy.

For multiple MCP servers, prefer one public Tailscale hostname per MCP server:

```text
https://dotmd.tailf87223.ts.net/mcp
https://calendar.tailf87223.ts.net/mcp
https://other-mcp.tailf87223.ts.net/mcp
```

Each hostname should still proxy `/` to exactly one MCP server, and each MCP
server should use its own root-based OAuth issuer:

```env
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
```

Do not put multiple hosted MCP servers under one hostname with path prefixes.
It complicates OAuth discovery and was the source of the earlier
`/.well-known/.../dotmd/...` Funnel failures.

### Important Tailscale Services Caveat

Tailscale has a feature named "Services" (`svc:<name>`), but it is not the same
thing as a public Funnel hostname for hosted MCP connectors.

Observed on this host:

```bash
tailscale serve --service dotmd --bg --yes http://127.0.0.1:8080
# invalid service name: "dotmd"

tailscale serve --service svc:dotmd --bg --yes http://127.0.0.1:8080
# service hosts must be tagged nodes
```

Official Tailscale Services are tailnet resources advertised by tagged service
hosts and governed by ACL grants. They are useful for internal tailnet service
discovery, but the current `tailscale funnel` CLI does not expose a `--service`
flag. Hosted connectors need public internet reachability, so the practical
multi-MCP public pattern is one Tailscale node hostname per MCP server, usually
implemented with a Tailscale sidecar/container per MCP service.

Sidecar pattern:

```text
dotmd container        listens on http://dotmd:8080
tailscale-dotmd node   hostname dotmd, Funnel / -> http://dotmd:8080

calendar container     listens on http://calendar:8080
tailscale-calendar     hostname calendar, Funnel / -> http://calendar:8080
```

This requires a Tailscale auth key or device-auth flow for each sidecar node.
Use tagged, ephemeral auth keys if possible, and restrict what those tagged
nodes can access.

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
POST /authorize
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

dotMD therefore keeps unrestricted dynamic registration disabled. Allowlisted
hosted clients may register, but they are stored as pending clients and cannot
receive an authorization code until the human enters a one-time pairing code on
the dotMD authorization page.

Create a one-time pairing code before initial connector setup or deliberate
re-pairing:

```bash
docker exec dotmd dotmd oauth code create
# or: docker exec dotmd dotmd oauth code create --ttl 10m
```

`--ttl` is optional and defaults to `10m`. Pending clients that do not complete
the browser authorization flow expire automatically; the default pending-client
TTL is `30m` and can be overridden with
`DOTMD_OAUTH_PENDING_CLIENT_TTL_SECONDS`.

Allowed redirect policy:

```text
Claude/Anthropic exact callback: https://claude.ai/api/mcp/auth_callback
ChatGPT callback prefix:        https://chatgpt.com/connector/oauth/
```

Production env:

```env
DOTMD_OAUTH_ALLOWED_REDIRECT_URIS=https://claude.ai/api/mcp/auth_callback
DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES=https://chatgpt.com/connector/oauth/
```

Security checks:

```bash
# Attacker callback must be rejected.
curl -i -X POST https://dotmd.tailf87223.ts.net/register \
  -H 'Content-Type: application/json' \
  -d '{"client_name":"evil","redirect_uris":["https://evil.example/callback"],"grant_types":["authorization_code","refresh_token"]}'

# Expected:
# HTTP/2 400
# {"error":"invalid_redirect_uri",...}

# With dynamic registration disabled, a trusted callback may register only as
# a pending client. It still cannot receive a token without a one-time code.
curl -i -X POST https://dotmd.tailf87223.ts.net/register \
  -H 'Content-Type: application/json' \
  -d '{"client_name":"ChatGPT","redirect_uris":["https://chatgpt.com/connector/oauth/test"],"grant_types":["authorization_code","refresh_token"],"response_types":["code"],"token_endpoint_auth_method":"none"}'

# Expected in steady state:
# HTTP/2 201
# Follow-up GET /authorize shows the pairing-code page until a valid code is entered.
```

## Required Endpoints

With `DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net`, FastMCP exposes:

```text
GET  /                                      health-style root response
GET  /.well-known/oauth-authorization-server
GET  /.well-known/oauth-protected-resource/mcp
GET  /authorize
POST /authorize
POST /register
POST /token
POST /mcp
```

The connector URL entered in the hosted connector UI is:

```text
https://dotmd.tailf87223.ts.net/mcp
```

Expected unauthenticated `/mcp` behavior is `401`, not `200`:

```text
HTTP/2 401
www-authenticate: Bearer ... resource_metadata="https://dotmd.tailf87223.ts.net/.well-known/oauth-protected-resource/mcp"
```

Do not expose compatibility aliases unless a specific client proves it needs
them. The final clean contract intentionally does not serve:

```text
GET /.well-known/oauth-authorization-server/mcp -> 404
GET /.well-known/oauth-protected-resource       -> 404
GET /.well-known/openid-configuration           -> 404
```

The OIDC probe is harmless; ChatGPT tries it and proceeds with OAuth metadata.

## Connector Setup: Claude/Anthropic

Anthropic's hosted connector flow was straightforward in this deployment. Once
Funnel, OAuth metadata, and the Claude callback allowlist were correct, it
connected on the first real attempt.

Use:

```text
Connector URL: https://dotmd.tailf87223.ts.net/mcp
Auth mode:     OAuth
Redirect URI: https://claude.ai/api/mcp/auth_callback
```

Setup sequence:

1. Generate a one-time code:

```bash
docker exec dotmd dotmd oauth code create
```

2. Create or reconnect the Claude connector with `https://dotmd.tailf87223.ts.net/mcp`.
3. When the browser opens the dotMD authorization page, enter the one-time code.
4. Confirm access log shows `/register 201`, `/authorize 200` for the pairing page, `/authorize 302` after the code, `/token 200`, then `/mcp 200`.

Expected Claude-style sequence:

```text
POST /mcp -> 401
GET  /.well-known/oauth-protected-resource/mcp -> 200
GET  /.well-known/openid-configuration -> 404
POST /register -> 201
GET  /authorize -> 200 pairing page
POST /authorize -> 302
POST /token -> 200
POST /mcp -> 200
```

## Connector Setup: ChatGPT

ChatGPT was the difficult case. The final working setup required cleaning stale
connector state, clearing dotMD OAuth state, recreating the container, and using
ChatGPT's public PKCE registration flow exactly.

Primary lesson from the incident: do not keep retrying ChatGPT against old
OAuth state. Most failed attempts were likely made against stale registered
clients, stale authorization codes, or stale connector state. Once
`/dotmd-index/oauth_state.json` was removed and the container was recreated,
ChatGPT connected cleanly twice, including after removing the experimental
compatibility endpoints.

Use:

```text
Connector URL:       https://dotmd.tailf87223.ts.net/mcp
Auth mode:           OAuth
Registration method: Dynamic Client Registration
Redirect prefix:     https://chatgpt.com/connector/oauth/
Client auth:         none
```

Do not use `Mixed` for this server. In testing, `Mixed` failed immediately in
ChatGPT's UI; switching back to `OAuth` and recreating the connector produced
the successful flow.

Before a clean ChatGPT registration:

```bash
docker exec dotmd sh -lc 'rm -f /dotmd-index/oauth_state.json'
```

If preserving forensic evidence matters, copy it first:

```bash
ts=$(date +%Y%m%d%H%M%S)
docker exec dotmd sh -lc "cp /dotmd-index/oauth_state.json /dotmd-index/oauth_state.json.bak-$ts 2>/dev/null || true; rm -f /dotmd-index/oauth_state.json"
```

Then create a one-time pairing code:

```bash
docker exec dotmd dotmd oauth code create
```

Successful ChatGPT trace from the final clean flow:

```text
POST /mcp -> 401
GET  /.well-known/oauth-protected-resource/mcp -> 200
GET  /.well-known/oauth-authorization-server -> 200
GET  /.well-known/openid-configuration -> 404
POST /register -> 201
GET  /authorize -> 200 pairing page
POST /authorize -> 302 with code, state, iss
POST /token -> 200
POST /mcp initialize -> 200
POST /mcp tools/list -> 200
POST /mcp resources/list -> 200
```

The registered ChatGPT client should look like:

```text
client_name=ChatGPT
token_endpoint_auth_method=none
client_secret absent
redirect_uris=["https://chatgpt.com/connector/oauth/<random-id>"]
resource=https://dotmd.tailf87223.ts.net/mcp
scopes=["dotmd"]
```

Known ChatGPT pitfalls:

- ChatGPT may cache broken connector/OAuth state. If setup keeps failing with
  `Something went wrong with setting up the connection`, delete the connector
  and create it again.
- The redirect URI suffix is random. Allow the prefix
  `https://chatgpt.com/connector/oauth/`, not one exact callback URL.
- `/authorize` must redirect directly. Do not put a local consent page in the
  middle of this flow.
- The access-log middleware must replay `/token` form bodies after logging; if
  it consumes the body, `/token` fails.
- `iss` must be present in the authorization callback and advertised with
  `authorization_response_iss_parameter_supported=true`.

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
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
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

dotMD runs its public Tailscale endpoint as a compose-managed sidecar:

```text
dotmd             app container, listens on http://dotmd:8080
tailscale-dotmd   Tailscale sidecar, attached to Docker network mcp
```

Start or refresh the sidecar from the deployment compose directory:

```bash
cd /opt/docker/dotmd
docker compose up -d tailscale-dotmd
```

Reset old path-based routes from inside the sidecar only when changing the
Funnel shape:

```bash
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock funnel reset
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock serve reset
```

Start a single root Funnel from the sidecar to the app container:

```bash
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock funnel --bg --yes http://dotmd:8080
```

Expected sidecar status:

```text
# Funnel on:
#     - https://dotmd.tailf87223.ts.net

https://dotmd.tailf87223.ts.net (Funnel on)
|-- / proxy http://dotmd:8080
```

Do not configure separate handlers like:

```text
/.well-known/oauth-authorization-server/dotmd
/.well-known/oauth-protected-resource/dotmd/mcp
/dotmd
```

Those routes are the failure-prone shape this playbook replaces.

## Multi-MCP Hostname Pattern

Use this pattern when exposing several MCP servers from neighboring containers.

Target URL shape:

```text
https://<mcp-service>.tailf87223.ts.net/mcp
```

Recommended topology:

```text
Docker network: mcp

dotmd service
  container: dotmd
  listens:   http://dotmd:8080

dotmd Tailscale sidecar
  container: tailscale-dotmd
  hostname:  dotmd
  funnel:    / -> http://dotmd:8080
```

Repeat the pattern per MCP server. Do not share OAuth state between MCP servers.
Each server needs its own `DOTMD_BASE_URL`/issuer and its own token store.

Example compose service shape:

```yaml
services:
  tailscale-dotmd:
    image: tailscale/tailscale:stable
    container_name: tailscale-dotmd
    command:
      - tailscaled
      - --socket=/tmp/tailscaled.sock
      - --statedir=/var/lib/tailscale
      - --tun=userspace-networking
    volumes:
      - tailscale-dotmd-state:/var/lib/tailscale
    networks:
      - mcp
    depends_on:
      dotmd:
        condition: service_healthy
    restart: unless-stopped

volumes:
  tailscale-dotmd-state:
    external: true
    name: tailscale-dotmd-state
```

Then, inside the sidecar, configure Funnel:

```bash
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock funnel --bg --yes http://dotmd:8080
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock serve status
```

### Sidecar Network Anti-Pattern

Do not run the sidecar with Docker network mode `container:dotmd`:

```text
--network container:dotmd
```

Docker resolves that to the concrete `dotmd` container ID. If `dotmd` is
force-recreated, the sidecar can remain attached to the old network namespace
and lose its default route while still appearing to run.

The current live deployment avoids that by keeping `tailscale-dotmd` as a
compose service attached to the shared `mcp` network. The sidecar resolves the
app by Docker DNS name `dotmd`, so app container recreates do not strand the
sidecar in a stale namespace.

After changing compose, Tailscale, OAuth, or MCP routing, run the live
connectivity gate:

```bash
just test-mcp-remote
```

Set the MCP server env to the sidecar hostname:

```env
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
```

Connector URL:

```text
https://dotmd.tailf87223.ts.net/mcp
```

Security setup sequence:

1. Create a one-time pairing code:

```bash
docker exec dotmd dotmd oauth code create
```

2. Connect the hosted MCP client once.
3. Enter the one-time code on the dotMD authorization page.

Do not reuse one sidecar node for multiple path-prefixed MCPs unless the client
is tailnet-local and does not need hosted OAuth discovery.

## Smoke Tests

Run from the host:

```bash
curl -i https://dotmd.tailf87223.ts.net/
curl -i https://dotmd.tailf87223.ts.net/.well-known/oauth-authorization-server
curl -i https://dotmd.tailf87223.ts.net/.well-known/oauth-protected-resource/mcp
curl -i -H 'Accept: application/json, text/event-stream' \
  https://dotmd.tailf87223.ts.net/mcp
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
  https://dotmd.tailf87223.ts.net/mcp
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
dig +trace +short dotmd.tailf87223.ts.net A | tail
dig +short dotmd.tailf87223.ts.net AAAA @1.1.1.1
```

Inside the tailnet, `getent hosts` may show the private tailnet IP. That is
normal, but it is not proof that hosted connector infrastructure can reach the
endpoint.

## Manual OAuth + MCP Verification

If a connector reports authorization failures, reproduce the full flow from a
shell. This confirms whether the server is broken or the hosted client is
reusing stale connector state.

```bash
cd backend
uv run python - <<'PY'
from __future__ import annotations

import base64
import hashlib
import secrets
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

BASE = "https://dotmd.tailf87223.ts.net"
MCP = f"{BASE}/mcp"
HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}

with httpx.Client(timeout=30.0, follow_redirects=False) as client:
    reg = client.post(f"{BASE}/register", json={
        "client_name": "dotmd-debug",
        "redirect_uris": ["https://chatgpt.com/connector/oauth/debug"],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
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
        "redirect_uri": "https://chatgpt.com/connector/oauth/debug",
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
        "redirect_uri": "https://chatgpt.com/connector/oauth/debug",
        "client_id": registration["client_id"],
        "code_verifier": verifier,
        "resource": MCP,
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

Useful successful sequence from ChatGPT:

```text
POST /mcp -> 401
GET  /.well-known/oauth-protected-resource/mcp -> 200
GET  /.well-known/oauth-authorization-server -> 200
GET  /.well-known/openid-configuration -> 404
POST /register -> 201
GET  /authorize -> 200 pairing page
POST /authorize -> 302 with code, state, iss
POST /token -> 200
POST /mcp initialize -> 200
POST /mcp tools/list -> 200
POST /mcp resources/list -> 200
```

The `/.well-known/openid-configuration 404` probe is harmless. ChatGPT tries it
and proceeds with OAuth authorization server metadata.

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
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock funnel reset
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock serve reset
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock funnel --bg --yes http://dotmd:8080
just test-mcp-remote
```

Then use:

```text
https://dotmd.tailf87223.ts.net/mcp
```

### `Authorization with the MCP server failed`

If logs show `POST /token 200` and subsequent `POST /mcp 200`, server-side
authorization succeeded. The usual cause is stale connector credentials in the
hosted client from a previous URL or previous OAuth state.

Fix:

1. Delete the old connector in the hosted client.
2. Clear dotMD OAuth state if needed:

```bash
ts=$(date +%Y%m%d%H%M%S)
docker exec dotmd sh -lc \
  "cp /dotmd-index/oauth_state.json /dotmd-index/oauth_state.json.bak-$ts 2>/dev/null || true; rm -f /dotmd-index/oauth_state.json"
COMPOSE_PROJECT_NAME=dotmd docker compose -f /opt/docker/dotmd/docker-compose.yml up -d --force-recreate dotmd
```

3. Recreate the connector with:

```text
https://dotmd.tailf87223.ts.net/mcp
```

### Public checks fail but local checks pass

Local checks may use tailnet DNS and bypass Funnel:

```bash
getent hosts dotmd.tailf87223.ts.net
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
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
MCP URL=https://dotmd.tailf87223.ts.net/mcp
```

## Cleanup Checklist

After a debugging session:

1. Ensure no temporary tunnel remains:

```bash
docker ps --format 'table {{.ID}}\t{{.Image}}\t{{.Names}}\t{{.Status}}' | rg 'cloudflare|cloudflared|dotmd'
```

Only the compose-managed `dotmd` and `tailscale-dotmd` containers should remain.

2. Ensure Funnel is simple:

```bash
docker exec tailscale-dotmd tailscale --socket=/tmp/tailscaled.sock serve status
```

Expected:

```text
https://dotmd.tailf87223.ts.net (Funnel on)
|-- / proxy http://dotmd:8080
```

3. Ensure production env is root-based:

```bash
grep '^DOTMD_BASE_URL=' /opt/docker/dotmd/.env
```

Expected:

```text
DOTMD_BASE_URL=https://dotmd.tailf87223.ts.net
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

6. Run the production MCP/Funnel smoke gate:

```bash
just test-mcp-remote
```

This checks the `dotmd` healthcheck, the `tailscale-dotmd` network namespace,
Tailscale/Funnel status, public OAuth discovery, `/mcp` auth challenge, an
authenticated `tools/list`, and that untrusted dynamic registration is rejected.
