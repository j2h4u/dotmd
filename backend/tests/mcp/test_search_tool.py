"""RED test skeletons for MCP server file_paths output (DEDUP-09 — P5 Task 2).

After Phase 16 P5 ships:
  - MCP search tool emits "file_paths": [...] array (not "file_path": "...")
  - MCP tool docstring is updated to describe file_paths

These tests FAIL until P5 (wave 5) updates mcp_server.py.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, cast
from unittest.mock import MagicMock

from dotmd.core.models import SearchResult


def _import_mcp():  # type: ignore[no-untyped-def]
    """Deferred import — may raise if MCP server has import-time dependency issues."""
    import dotmd.mcp_server as mcp
    return mcp


def _search_tool_schema() -> dict[str, Any]:
    mcp = _import_mcp()
    tools = asyncio.run(mcp.mcp.list_tools())
    by_name = {tool.name: tool.model_dump(mode="json", exclude_none=True) for tool in tools}
    return by_name["search"]


class TestFilePathsIsJsonArray:
    """MCP search tool emits file_paths as a registered schema and call output."""

    def test_registered_output_schema_has_file_paths_array(self) -> None:
        """tools/list schema exposes file_paths as array, not file_path."""
        schema = _search_tool_schema()["outputSchema"]
        hit_schema = schema["$defs"]["SearchHit"]
        properties = hit_schema["properties"]

        assert properties["file_paths"]["type"] == "array"
        assert properties["file_paths"]["items"]["type"] == "string"
        assert "file_path" not in properties

    def test_tool_call_output_has_file_paths_array(self, tmp_path: Path) -> None:
        """Stubbed tools/call output contains file_paths list, not file_path."""
        mcp = _import_mcp()
        stub_result = SearchResult(
            chunk_id="a" * 64,
            file_paths=[Path("/path/to/file.md"), Path("/other/file.md")],
            heading_path="# Test",
            snippet="test snippet",
            fused_score=0.9,
        )
        service = MagicMock()
        service.search.return_value = [stub_result]
        previous_service = mcp._service
        mcp._service = service
        try:
            _content, structured_raw = asyncio.run(
                mcp.mcp.call_tool("search", {"query": "test", "top_k": 1})
            )
        finally:
            mcp._service = previous_service

        structured = cast(dict[str, Any], structured_raw)
        payload = structured["result"][0]
        payload = cast(dict[str, Any], payload)
        assert payload["file_paths"] == ["/other/file.md", "/path/to/file.md"]
        assert "file_path" not in payload
        service.search.assert_called_once_with("test", top_k=1)
