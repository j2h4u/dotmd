"""Smoke test configuration -- runs against a live dotMD MCP stack."""

import json

import httpx
import pytest

MCP_URL = "http://localhost:8080/mcp"
HEALTH_URL = "http://localhost:8080/health"
_MCP_HEADERS = {
    "Content-Type": "application/json",
    "Accept": "application/json, text/event-stream",
}


def mcp_call(method: str, params: dict | None = None) -> dict:
    """Single stateless JSON-RPC POST to the MCP endpoint."""
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}}
    resp = httpx.post(MCP_URL, json=body, headers=_MCP_HEADERS, timeout=60.0)
    resp.raise_for_status()
    return resp.json()


def tool_call(name: str, arguments: dict | None = None) -> dict:
    """Convenience wrapper for tools/call."""
    return mcp_call("tools/call", {"name": name, "arguments": arguments or {}})


def tool_result(data: dict) -> object:
    """Extract structuredContent.result, falling back to parsing the first text item."""
    structured = (data.get("result") or {}).get("structuredContent") or {}
    if "result" in structured:
        return structured["result"]
    content = (data.get("result") or {}).get("content", [])
    for c in content:
        if isinstance(c, dict) and c.get("type") == "text":
            return json.loads(c["text"])
    return {}


def is_tool_error(data: dict) -> bool:
    return bool((data.get("result") or {}).get("isError"))


def pytest_collection_modifyitems(config, items):
    """Skip all smoke tests if the MCP stack is unreachable."""
    try:
        r = httpx.get(HEALTH_URL, timeout=5.0)
        if r.status_code == 200:
            return
    except (httpx.ConnectError, httpx.TimeoutException):
        pass

    skip_marker = pytest.mark.skip(
        reason=f"dotMD stack not reachable at {HEALTH_URL}"
    )
    for item in items:
        if "smoke" in str(item.fspath):
            item.add_marker(skip_marker)


@pytest.fixture(scope="session", autouse=True)
def ensure_indexed():
    """Skip all smoke tests if no data has been indexed."""
    data = tool_call("status")
    payload = tool_result(data)
    if not isinstance(payload, dict) or payload.get("total_chunks", 0) == 0:
        pytest.skip("No data indexed -- smoke tests require indexed content")
