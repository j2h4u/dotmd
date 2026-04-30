"""E2E test configuration — runs against a live dotMD MCP server.

Supports two transports, tested with the same suite:
  - http:  stateless JSON-RPC POST to http://localhost:8080/mcp
  - stdio: persistent dotmd mcp subprocess (one per session, shared to avoid
           repeated model warmup)

Run inside container:
    python -m pytest tests/e2e/ -v -p no:cacheprovider
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import threading
from collections.abc import Callable
from contextlib import AsyncExitStack
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import pytest

MCP_URL = "http://localhost:8080/mcp"
AUTH_BASE_URL = "http://localhost:8080"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}
_HTTP_ACCESS_TOKEN: str | None = None


# ---------------------------------------------------------------------------
# Response helpers (transport-agnostic)
# ---------------------------------------------------------------------------

def _tool_result_text(data: dict) -> str:
    """Extract the first text content item from a tools/call response."""
    content = data.get("result", {}).get("content", [])
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            return c["text"]
    return ""


def _tool_result_structured(data: dict) -> object:
    """Return structuredContent.result when available, else parse first text item.

    FastMCP emits structuredContent for typed return values (list[dict], dict).
    Both HTTP and stdio transports include it in the response.
    Falls back to parsing the first text content item for plain-text tools.
    """
    structured = (data.get("result") or {}).get("structuredContent") or {}
    if "result" in structured:
        return structured["result"]
    return json.loads(_tool_result_text(data))


def _is_tool_error(data: dict) -> bool:
    return bool((data.get("result") or {}).get("isError"))


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

def _http_access_token() -> str | None:
    """Return a cached OAuth access token when HTTP auth is enabled."""
    global _HTTP_ACCESS_TOKEN

    if not os.environ.get("DOTMD_BASE_URL"):
        return None
    if _HTTP_ACCESS_TOKEN:
        return _HTTP_ACCESS_TOKEN

    register = httpx.post(
        f"{AUTH_BASE_URL}/register",
        json={
            "client_name": "dotmd-e2e",
            "redirect_uris": ["http://localhost:8888/callback"],
            "grant_types": ["authorization_code", "refresh_token"],
        },
        timeout=60.0,
    )
    register.raise_for_status()
    registration = register.json()
    client_id = registration["client_id"]
    client_secret = registration["client_secret"]

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()
    ).rstrip(b"=").decode()
    authorize = httpx.get(
        f"{AUTH_BASE_URL}/authorize?{urlencode({
            'client_id': client_id,
            'redirect_uri': 'http://localhost:8888/callback',
            'response_type': 'code',
            'code_challenge': challenge,
            'code_challenge_method': 'S256',
            'state': 'e2e',
        })}",
        follow_redirects=False,
        timeout=60.0,
    )
    assert authorize.status_code == 302
    location = authorize.headers["location"]
    code = parse_qs(urlparse(location).query)["code"][0]

    token = httpx.post(
        f"{AUTH_BASE_URL}/token",
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": "http://localhost:8888/callback",
            "client_id": client_id,
            "client_secret": client_secret,
            "code_verifier": verifier,
        },
        timeout=60.0,
    )
    token.raise_for_status()
    _HTTP_ACCESS_TOKEN = token.json()["access_token"]
    return _HTTP_ACCESS_TOKEN


def _http_call(method: str, params: dict | None = None) -> dict:
    """Single stateless JSON-RPC POST — no session required."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    headers = dict(_MCP_HEADERS)
    token = _http_access_token()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = httpx.post(MCP_URL, json=body, headers=headers, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Stdio transport — persistent session
# ---------------------------------------------------------------------------

class _StdioSession:
    """Long-lived dotmd mcp subprocess, shared across all stdio tests in a session.

    Runs the entire async lifecycle (startup → serve → teardown) in one continuous
    coroutine on a dedicated background thread.  This keeps anyio cancel scopes valid
    during cleanup — closing them from the same task that created them.

    Sync pytest tests submit calls via run_coroutine_threadsafe; stop() signals
    shutdown via call_soon_threadsafe and joins the thread.

    One warmup per test run (~15s) instead of one per test call.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._session = None  # mcp.ClientSession
        self._ready: threading.Event = threading.Event()
        self._shutdown: asyncio.Event | None = None
        self._startup_error: BaseException | None = None

    def start(self) -> None:
        from mcp.client.stdio import StdioServerParameters, stdio_client

        from mcp import ClientSession

        async def _run() -> None:
            try:
                async with AsyncExitStack() as stack:
                    dotmd_env = {k: v for k, v in os.environ.items() if k.startswith("DOTMD_")}
                    server = StdioServerParameters(command="dotmd", args=["mcp"], env=dotmd_env)
                    read, write = await stack.enter_async_context(
                        stdio_client(server)
                    )
                    session = await stack.enter_async_context(
                        ClientSession(read, write)
                    )
                    await session.initialize()
                    self._session = session
                    self._shutdown = asyncio.Event()
                    self._ready.set()
                    await self._shutdown.wait()
                    # AsyncExitStack unwinds here — same task that created the
                    # anyio cancel scopes, so cleanup is valid.
            except Exception as exc:
                self._startup_error = exc
                self._ready.set()

        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=lambda: self._loop.run_until_complete(_run()),
            daemon=True,
            name="stdio-mcp-session",
        )
        self._thread.start()
        if not self._ready.wait(timeout=60):
            raise TimeoutError("stdio session failed to start within 60s")
        if self._startup_error is not None:
            raise self._startup_error

    def call(self, method: str, params: dict | None = None) -> dict:
        assert self._session is not None, "stdio session not started"
        assert self._loop is not None

        async def _call() -> dict:
            if method == "tools/list":
                result = await self._session.list_tools()
                return {
                    "result": {
                        "tools": [
                            t.model_dump(mode="json", exclude_none=True)
                            for t in result.tools
                        ]
                    }
                }
            if method == "tools/call":
                name = (params or {})["name"]
                args = (params or {}).get("arguments", {})
                result = await self._session.call_tool(name, args)
                return {
                    "result": {
                        "content": [
                            c.model_dump(mode="json") for c in result.content
                        ],
                        "structuredContent": result.structuredContent,
                        "isError": result.isError or False,
                    }
                }
            raise ValueError(f"unsupported method for stdio caller: {method!r}")

        future = asyncio.run_coroutine_threadsafe(_call(), self._loop)
        return future.result(timeout=60)

    def stop(self) -> None:
        if self._shutdown is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._shutdown.set)
        if self._thread is not None:
            self._thread.join(timeout=30)
        self._loop = None
        self._session = None
        self._shutdown = None


@pytest.fixture(scope="session")
def _stdio_session():
    """One dotmd mcp process for the entire test session."""
    sess = _StdioSession()
    sess.start()
    yield sess
    sess.stop()


# ---------------------------------------------------------------------------
# Parametrized transport fixture
# ---------------------------------------------------------------------------

@pytest.fixture(params=["http", "stdio"], ids=["http", "stdio"])
def mcp_call(request, _stdio_session: _StdioSession) -> Callable[[str, dict | None], dict]:
    """Callable mcp_call(method, params) — same interface for both transports."""
    if request.param == "http":
        return _http_call
    return _stdio_session.call


# ---------------------------------------------------------------------------
# Auto-skip when server is unreachable
# ---------------------------------------------------------------------------

def pytest_collection_modifyitems(config, items):
    """Skip all e2e tests if the MCP server is unreachable."""
    try:
        r = httpx.get("http://localhost:8080/health", timeout=5.0)
        if r.status_code == 200:
            return
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    skip = pytest.mark.skip(reason="dotMD MCP server not reachable at http://localhost:8080")
    for item in items:
        if "e2e" in str(item.fspath):
            item.add_marker(skip)
