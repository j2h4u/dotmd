"""MCP search/read source-ref contract tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import MagicMock

import pytest


def _import_mcp():  # type: ignore[no-untyped-def]
    """Deferred import for MCP server module."""
    import dotmd.mcp_server as mcp
    return mcp


def _tool_schema(name: str) -> dict[str, Any]:
    mcp = _import_mcp()
    tools = asyncio.run(mcp.mcp.list_tools())
    by_name = {tool.name: tool.model_dump(mode="json", exclude_none=True) for tool in tools}
    return by_name[name]


class TestSearchRefContract:
    """MCP search emits ref as the search-to-read key."""

    def test_registered_output_schema_has_ref_not_file_paths(self) -> None:
        schema = _tool_schema("search")["outputSchema"]
        hit_schema = schema["$defs"]["SearchHit"]
        properties = hit_schema["properties"]

        assert properties["ref"]["type"] == "string"
        assert "file_paths" not in properties
        assert "file_path" not in properties

    def test_tool_call_output_has_ref(self) -> None:
        mcp = _import_mcp()
        stub_result = SimpleNamespace(
            chunk_id="a" * 64,
            ref="filesystem:/mnt/test.md",
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
        payload = cast(dict[str, Any], structured["result"][0])
        assert payload["ref"] == "filesystem:/mnt/test.md"
        assert "file_paths" not in payload
        assert "file_path" not in payload
        service.search.assert_called_once_with("test", top_k=1)


class TestReadToolRefContract:
    """MCP read passes ref through to the service and returns ref."""

    def test_read_tool_uses_ref_and_returns_frontmatter_and_chunks(self) -> None:
        mcp = _import_mcp()
        service = MagicMock()
        service.read.return_value = {
            "ref": "filesystem:/mnt/test.md",
            "total_chunks": 2,
            "frontmatter": {
                "title": "Compatibility Note",
                "kind": "document",
                "tags": ["source"],
            },
            "chunks": [
                {
                    "index": 0,
                    "heading_hierarchy": ["Project", "Decision"],
                    "text": "Read by source ref.",
                }
            ],
        }
        previous_service = mcp._service
        mcp._service = service
        try:
            _content, structured_raw = asyncio.run(
                mcp.mcp.call_tool(
                    "read",
                    {"ref": "filesystem:/mnt/test.md", "start": 0, "end": 1},
                )
            )
        finally:
            mcp._service = previous_service

        structured = cast(dict[str, Any], structured_raw)
        assert structured["ref"] == "filesystem:/mnt/test.md"
        assert structured["total_chunks"] == 2
        assert structured["frontmatter"]["title"] == "Compatibility Note"
        assert structured["chunks"] == [
            {
                "index": 0,
                "heading": "Project > Decision",
                "text": "Read by source ref.",
            }
        ]
        assert "file_path" not in structured
        service.read.assert_called_once_with("filesystem:/mnt/test.md", 0, 1)

    def test_read_schema_uses_ref_input(self) -> None:
        schema = _tool_schema("read")["inputSchema"]
        properties = schema["properties"]

        assert "ref" in properties
        assert properties["ref"]["description"] == "Source ref from a search result."
        assert "file_path" not in properties

    def test_read_value_error_becomes_actionable_tool_error(self) -> None:
        mcp = _import_mcp()
        service = MagicMock()
        service.read.side_effect = ValueError("Unknown source ref")
        previous_service = mcp._service
        mcp._service = service
        try:
            with pytest.raises(Exception) as exc_info:
                asyncio.run(
                    mcp.mcp.call_tool(
                        "read",
                        {"ref": "not-a-ref", "start": 0, "end": 1},
                    )
                )
        finally:
            mcp._service = previous_service

        message = str(exc_info.value)
        assert "Unknown source ref" in message
        assert "not-a-ref" in message
        assert "Action: pass a ref returned by search." in message


class TestDrillToolRefContract:
    """MCP drill exposes source metadata for a ref."""

    def test_drill_tool_exists_and_returns_metadata(self) -> None:
        assert _tool_schema("drill")["name"] == "drill"

        mcp = _import_mcp()
        service = MagicMock()
        service.drill.return_value = {
            "ref": "filesystem:/mnt/test.md",
            "title": "Compatibility Note",
            "source_uri": "file:///mnt/test.md",
            "document_type": "markdown",
            "parser_name": "markdown",
            "frontmatter": {"title": "Compatibility Note"},
            "total_chunks": 2,
        }
        previous_service = mcp._service
        mcp._service = service
        try:
            _content, structured_raw = asyncio.run(
                mcp.mcp.call_tool("drill", {"ref": "filesystem:/mnt/test.md"})
            )
        finally:
            mcp._service = previous_service

        structured = cast(dict[str, Any], structured_raw)
        assert structured["ref"] == "filesystem:/mnt/test.md"
        assert structured["title"] == "Compatibility Note"
        assert structured["source_uri"] == "file:///mnt/test.md"
        assert structured["document_type"] == "markdown"
        assert structured["parser_name"] == "markdown"
        assert structured["frontmatter"] == {"title": "Compatibility Note"}
        assert structured["total_chunks"] == 2
        service.drill.assert_called_once_with("filesystem:/mnt/test.md")

    def test_drill_value_error_becomes_actionable_tool_error(self) -> None:
        mcp = _import_mcp()
        service = MagicMock()
        service.drill.side_effect = ValueError("Unsupported source namespace")
        previous_service = mcp._service
        mcp._service = service
        try:
            with pytest.raises(Exception) as exc_info:
                asyncio.run(mcp.mcp.call_tool("drill", {"ref": "telegram:1"}))
        finally:
            mcp._service = previous_service

        message = str(exc_info.value)
        assert "Unsupported source namespace" in message
        assert "telegram:1" in message
        assert "Action: pass a ref returned by search." in message
