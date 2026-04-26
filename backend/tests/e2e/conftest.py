"""E2E test configuration — runs against a live dotMD MCP server.

Requires the container to be running: docker exec dotmd pytest tests/e2e/
The MCP server must be reachable at http://localhost:8080/mcp.
"""

from __future__ import annotations

import json

import httpx
import pytest

MCP_URL = "http://localhost:8080/mcp"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def _mcp_post(method: str, params: dict | None = None, rpc_id: int = 1) -> dict:
    """Send a single stateless JSON-RPC request to the MCP server."""
    body = {"jsonrpc": "2.0", "id": rpc_id, "method": method, "params": params or {}}
    resp = httpx.post(MCP_URL, json=body, headers=_MCP_HEADERS, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def _tool_result_text(data: dict) -> str:
    """Extract the first text content item from a tools/call response."""
    content = data.get("result", {}).get("content", [])
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            return c["text"]
    return ""


def _tool_result_structured(data: dict) -> object:
    """Return structuredContent.result when available, else parse first text item.

    FastMCP puts the typed return value in structuredContent.result.
    For list[dict] tools (search) each dict is also a separate content item,
    so we must use structuredContent rather than joining content texts.
    """
    structured = data.get("result", {}).get("structuredContent", {})
    if "result" in structured:
        return structured["result"]
    return json.loads(_tool_result_text(data))


# Alias used by single-object tools (status, drill)
_tool_result_json = _tool_result_structured


def _is_tool_error(data: dict) -> bool:
    return bool(data.get("result", {}).get("isError"))


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
