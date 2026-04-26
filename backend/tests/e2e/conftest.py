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
import json
from contextlib import AsyncExitStack
from typing import Callable

import httpx
import pytest

MCP_URL = "http://localhost:8080/mcp"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


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

def _http_call(method: str, params: dict | None = None) -> dict:
    """Single stateless JSON-RPC POST — no session required."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = httpx.post(MCP_URL, json=body, headers=_MCP_HEADERS, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


# ---------------------------------------------------------------------------
# Stdio transport — persistent session
# ---------------------------------------------------------------------------

class _StdioSession:
    """Long-lived dotmd mcp subprocess, shared across all stdio tests in a session.

    Uses a dedicated event loop so sync pytest tests can call async MCP SDK methods.
    One warmup per test run (~15s) instead of one per test call.
    """

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._exit_stack: AsyncExitStack | None = None
        self._session = None  # mcp.ClientSession

    def start(self) -> None:
        from mcp import ClientSession
        from mcp.client.stdio import StdioServerParameters, stdio_client

        async def _startup() -> None:
            self._exit_stack = AsyncExitStack()
            server = StdioServerParameters(command="dotmd", args=["mcp"])
            read, write = await self._exit_stack.enter_async_context(
                stdio_client(server)
            )
            session = await self._exit_stack.enter_async_context(
                ClientSession(read, write)
            )
            await session.initialize()
            self._session = session

        self._loop = asyncio.new_event_loop()
        self._loop.run_until_complete(_startup())

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

        return self._loop.run_until_complete(_call())

    def stop(self) -> None:
        if self._exit_stack and self._loop:
            self._loop.run_until_complete(self._exit_stack.aclose())
        if self._loop:
            self._loop.close()
        self._loop = None
        self._session = None
        self._exit_stack = None


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
        item.add_marker(skip)
