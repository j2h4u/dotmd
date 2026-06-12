"""Production MCP/Funnel connectivity smoke test.

This is intentionally a live-infrastructure check, not a unit test. It verifies
the exact path hosted Claude/ChatGPT use: Tailscale Funnel -> dotmd HTTP MCP ->
OAuth -> authenticated tools/list.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlencode


@dataclass(frozen=True)
class HttpResult:
    status: int
    headers: dict[str, str]
    body: bytes


def run(argv: list[str], *, check: bool = True) -> str:
    completed = subprocess.run(
        argv,
        check=check,
        text=True,
        capture_output=True,
    )
    return completed.stdout


def fail(message: str) -> None:
    raise SystemExit(f"FAIL: {message}")


def ok(message: str) -> None:
    print(f"ok - {message}")


def http_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    timeout: float = 10.0,
) -> HttpResult:
    request = urllib.request.Request(
        url,
        data=body,
        headers=headers or {},
        method=method,
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return HttpResult(
                status=response.status,
                headers={k.lower(): v for k, v in response.headers.items()},
                body=response.read(),
            )
    except urllib.error.HTTPError as exc:
        return HttpResult(
            status=exc.code,
            headers={k.lower(): v for k, v in exc.headers.items()},
            body=exc.read(),
        )


def json_body(result: HttpResult) -> dict[str, Any]:
    try:
        value = json.loads(result.body.decode("utf-8"))
    except Exception as exc:
        fail(f"response is not JSON: status={result.status} body={result.body[:200]!r}: {exc}")
        raise
    if not isinstance(value, dict):
        fail(f"response JSON is not an object: {value!r}")
        raise TypeError("response JSON is not an object")
    return value


def dotmd_container_id() -> str:
    return run(["docker", "inspect", "dotmd", "--format", "{{.Id}}"]).strip()


def assert_dotmd_healthy() -> None:
    status = run(
        ["docker", "inspect", "dotmd", "--format", "{{.State.Status}} {{.State.Health.Status}}"]
    ).strip()
    if status != "running healthy":
        fail(f"dotmd container is not healthy: {status}")
    result = http_request("GET", "http://127.0.0.1:18082/health")
    if result.status != 200 or json_body(result).get("status") != "ok":
        fail(f"local dotmd health failed: status={result.status} body={result.body!r}")
    ok("dotmd container is running healthy")


def inspect_container(name: str, template: str) -> str:
    return run(["docker", "inspect", name, "--format", template]).strip()


def assert_tailscale_sidecar_network() -> None:
    dotmd_id = dotmd_container_id()
    network_mode = inspect_container("tailscale-dotmd", "{{.HostConfig.NetworkMode}}")
    networks_json = inspect_container("tailscale-dotmd", "{{json .NetworkSettings.Networks}}")
    networks = json.loads(networks_json)
    if network_mode == f"container:{dotmd_id}":
        ok("tailscale-dotmd is bound to the current dotmd network namespace")
        return
    if network_mode.startswith("container:"):
        fail(
            "tailscale-dotmd is bound to a stale container network namespace: "
            f"actual={network_mode} current_dotmd=container:{dotmd_id}"
        )
    if "mcp" not in networks:
        fail(
            f"tailscale-dotmd is not attached to the shared mcp network: networks={sorted(networks)}"
        )
    ok("tailscale-dotmd is attached to the shared mcp network")


def assert_tailscale_ready() -> None:
    status = run(
        [
            "docker",
            "exec",
            "tailscale-dotmd",
            "tailscale",
            "--socket=/tmp/tailscaled.sock",
            "status",
        ]
    )
    if "dotmd" not in status or "offline" in status.splitlines()[0]:
        fail(f"tailscale status is not online:\n{status}")

    serve = run(
        [
            "docker",
            "exec",
            "tailscale-dotmd",
            "tailscale",
            "--socket=/tmp/tailscaled.sock",
            "serve",
            "status",
        ]
    )
    proxy_targets = ("http://dotmd:8080", "http://127.0.0.1:8080")
    if "Funnel on" not in serve or not any(target in serve for target in proxy_targets):
        fail(f"tailscale Funnel is not serving dotmd:\n{serve}")

    netcheck = run(
        [
            "docker",
            "exec",
            "tailscale-dotmd",
            "tailscale",
            "--socket=/tmp/tailscaled.sock",
            "netcheck",
        ]
    )
    required = ["* UDP: true", "* IPv4: yes", "* Nearest DERP:"]
    missing = [item for item in required if item not in netcheck]
    if missing or "Nearest DERP: unknown" in netcheck:
        fail(f"tailscale netcheck failed, missing={missing}:\n{netcheck}")
    ok("tailscale sidecar, Funnel, and DERP connectivity are healthy")


def dotmd_env(name: str) -> str:
    script = f"import os; print(os.environ.get({name!r}, ''))"
    return run(["docker", "exec", "-i", "dotmd", "python", "-c", script]).strip()


def assert_public_oauth(base_url: str) -> None:
    health = http_request("GET", f"{base_url}/health")
    if health.status != 200 or json_body(health).get("status") != "ok":
        fail(f"public health failed: status={health.status} body={health.body!r}")

    auth = http_request("GET", f"{base_url}/.well-known/oauth-authorization-server")
    auth_json = json_body(auth)
    if auth.status != 200 or auth_json.get("issuer") != base_url:
        fail(f"authorization metadata failed: status={auth.status} body={auth.body!r}")

    resource = http_request("GET", f"{base_url}/.well-known/oauth-protected-resource/mcp")
    resource_json = json_body(resource)
    if resource.status != 200 or resource_json.get("resource") != f"{base_url}/mcp":
        fail(f"protected resource metadata failed: status={resource.status} body={resource.body!r}")

    challenge = http_request(
        "POST",
        f"{base_url}/mcp",
        headers={
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        body=b'{"jsonrpc":"2.0","id":1,"method":"initialize","params":{}}',
    )
    www_auth = challenge.headers.get("www-authenticate", "")
    if challenge.status != 401 or "resource_metadata=" not in www_auth:
        fail(
            f"MCP unauthenticated challenge failed: status={challenge.status} www-authenticate={www_auth!r}"
        )
    ok("public health, OAuth metadata, and MCP auth challenge are reachable")


def access_token_for_client(client_name: str) -> str:
    script = r"""
import json
from pathlib import Path

state = json.loads(Path("/dotmd-index/oauth_state.json").read_text())
clients = state.get("clients", {})
for token, data in state.get("access_tokens", {}).items():
    client = clients.get(data.get("client_id"), {})
    if client.get("client_name") == CLIENT_NAME:
        print(token)
        raise SystemExit(0)
raise SystemExit(1)
""".replace("CLIENT_NAME", repr(client_name))
    token = run(["docker", "exec", "-i", "dotmd", "python", "-c", script], check=False).strip()
    if not token:
        fail(f"no OAuth access token found for client_name={client_name!r}")
    return token


def assert_authenticated_tools_list(base_url: str, token: str) -> None:
    body = b'{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
    result = http_request(
        "POST",
        f"{base_url}/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": "2025-06-18",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        body=body,
    )
    payload = json_body(result)
    if result.status != 200:
        fail(f"authenticated tools/list failed: status={result.status} body={result.body!r}")
    tools = payload.get("result", {}).get("tools", [])
    names = sorted(tool.get("name") for tool in tools)
    if names != ["feedback", "read", "search"]:
        fail(f"unexpected tools/list names: {names!r}")
    for tool in tools:
        if "inputSchema" not in tool:
            fail(f"tool has no inputSchema: {tool.get('name')}")
        if "outputSchema" not in tool:
            fail(f"tool has no outputSchema: {tool.get('name')}")
        if "annotations" not in tool:
            fail(f"tool has no annotations: {tool.get('name')}")
    ok("authenticated tools/list returns search, read, feedback, and schemas")


def assert_feedback_call(base_url: str, token: str) -> None:
    marker = f"__remote_smoke_feedback__{int(time.time())}"
    body = json.dumps(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "feedback",
                "arguments": {
                    "message": marker,
                    "severity": "question",
                    "context": "remote MCP smoke",
                },
            },
        }
    ).encode("utf-8")
    result = http_request(
        "POST",
        f"{base_url}/mcp",
        headers={
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": "2025-06-18",
            "Accept": "application/json, text/event-stream",
            "Content-Type": "application/json",
        },
        body=body,
    )
    payload = json_body(result)
    if result.status != 200 or payload.get("result", {}).get("isError"):
        fail(f"feedback call failed: status={result.status} body={result.body!r}")
    cleanup = """
import sqlite3
from pathlib import Path

conn = sqlite3.connect(str(Path("/dotmd-index/feedback.db")))
try:
    conn.execute("DELETE FROM feedback WHERE message = ?", (MESSAGE,))
    conn.commit()
finally:
    conn.close()
""".replace("MESSAGE", repr(marker))
    run(["docker", "exec", "-i", "dotmd", "python", "-c", cleanup])
    ok("feedback tool records successfully")


def cleanup_pending_oauth_client(client_id: str) -> None:
    cleanup = """
import json
import os
from pathlib import Path

path = Path("/dotmd-index/oauth_state.json")
state = json.loads(path.read_text(encoding="utf-8"))
state.get("pending_clients", {}).pop(CLIENT_ID, None)
tmp = path.with_suffix(".tmp")
tmp.write_text(json.dumps(state, indent=2, default=str), encoding="utf-8")
os.replace(tmp, path)
""".replace("CLIENT_ID", repr(client_id))
    run(["docker", "exec", "-i", "dotmd", "python", "-c", cleanup])


def assert_registration_is_code_gated(base_url: str) -> None:
    redirect_uri = "https://evil.example/callback"
    body = json.dumps(
        {
            "client_name": "smoke-code-gate",
            "redirect_uris": [redirect_uri],
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        }
    ).encode("utf-8")
    result = http_request(
        "POST",
        f"{base_url}/register",
        headers={"Content-Type": "application/json"},
        body=body,
    )
    payload = json_body(result)
    allowlist_configured = bool(dotmd_env("DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES"))
    if allowlist_configured:
        if result.status != 400 or payload.get("error") != "invalid_redirect_uri":
            fail(
                f"untrusted redirect registration was not rejected: status={result.status} body={result.body!r}"
            )
        ok("configured OAuth redirect allowlist rejects untrusted callbacks")
        return
    if result.status != 201:
        fail(
            f"registration should be accepted when redirect allowlist is empty: status={result.status} body={result.body!r}"
        )
    client_id = payload.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        fail(f"registration response did not include client_id: {payload!r}")
    assert isinstance(client_id, str)
    authorize_query = urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "dotmd",
            "state": "smoke-code-gate",
            "code_challenge": "challenge",
            "code_challenge_method": "S256",
            "resource": f"{base_url}/mcp",
        }
    )
    authorize = http_request("GET", f"{base_url}/authorize?{authorize_query}")
    if authorize.status != 200 or b"Pairing code" not in authorize.body:
        fail(
            f"registered client was not held behind pairing code: status={authorize.status} body={authorize.body[:300]!r}"
        )
    cleanup_pending_oauth_client(client_id)
    ok("empty OAuth redirect allowlist accepts registration but keeps clients code-gated")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url",
        default="",
        help="Public MCP base URL; defaults to DOTMD_BASE_URL inside dotmd.",
    )
    parser.add_argument(
        "--client-name",
        default="Claude",
        help="OAuth client name whose token is used for tools/list.",
    )
    parser.add_argument(
        "--skip-registration-closed",
        action="store_true",
        help="Skip the steady-state OAuth registration/code-gate check.",
    )
    args = parser.parse_args()

    base_url = args.base_url.rstrip("/") or dotmd_env("DOTMD_BASE_URL").rstrip("/")
    if not base_url:
        fail("base URL is empty; set DOTMD_BASE_URL or pass --base-url")

    assert_dotmd_healthy()
    assert_tailscale_sidecar_network()
    assert_tailscale_ready()
    assert_public_oauth(base_url)
    token = access_token_for_client(args.client_name)
    assert_authenticated_tools_list(base_url, token)
    assert_feedback_call(base_url, token)
    if not args.skip_registration_closed:
        assert_registration_is_code_gated(base_url)
    ok("remote MCP smoke passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
