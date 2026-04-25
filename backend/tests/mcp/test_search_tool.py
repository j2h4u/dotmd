"""RED test skeletons for MCP server file_paths output (DEDUP-09 — P5 Task 2).

After Phase 16 P5 ships:
  - MCP search tool emits "file_paths": [...] array (not "file_path": "...")
  - MCP tool docstring is updated to describe file_paths

These tests FAIL until P5 (wave 5) updates mcp_server.py.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _import_mcp():  # type: ignore[no-untyped-def]
    """Deferred import — may raise if MCP server has import-time dependency issues."""
    import dotmd.mcp_server as mcp
    return mcp


class TestFilePathsIsJsonArray:
    """MCP search tool emits file_paths as a JSON array of strings."""

    def test_file_paths_is_json_array(self, tmp_path: Path) -> None:
        """MCP search response contains 'file_paths' as a list, not 'file_path' as string."""
        mcp = _import_mcp()

        from dotmd.core.models import SearchResult

        stub_result = SearchResult(
            chunk_id="a" * 64,
            file_paths=[Path("/path/to/file.md"), Path("/other/file.md")],
            heading_path="# Test",
            snippet="test snippet",
            fused_score=0.9,
        )

        # The MCP server formats results via _format_result or similar helper.
        # After P5, it must emit {"file_paths": ["/path/...", "/other/..."]}
        # and NOT {"file_path": "/path/..."}.

        if hasattr(mcp, "_format_result"):
            formatted = mcp._format_result(stub_result)
            assert "file_paths" in formatted, (
                f"MCP result must have 'file_paths' key after P5: {formatted!r}"
            )
            assert isinstance(formatted["file_paths"], list), (
                f"file_paths must be a list in MCP output: {formatted!r}"
            )
            assert "file_path" not in formatted, (
                f"MCP result must NOT have singular 'file_path' key after P5: {formatted!r}"
            )
        else:
            # If _format_result not yet added (P5 not shipped), the test fails here
            pytest.fail(
                "mcp_server._format_result not found — P5 must add this helper "
                "or the equivalent formatting logic."
            )


class TestDocstringMentionsFilePaths:
    """MCP search tool docstring references 'file_paths' after P5."""

    def test_docstring_mentions_file_paths(self) -> None:
        """The MCP search tool function docstring mentions 'file_paths'."""
        mcp = _import_mcp()

        # Find the search tool function (typically named 'search' or 'search_tool')
        search_fn = getattr(mcp, "search", None) or getattr(mcp, "search_tool", None)

        if search_fn is None:
            # Try to find it via the MCP server instance
            if hasattr(mcp, "_mcp_server"):
                # Look for a registered tool with 'search' in its name
                pytest.fail(
                    "Could not find search tool function in mcp_server module. "
                    "P5 must expose it so this test can assert on its docstring."
                )
            pytest.fail(
                "mcp_server has no 'search' or 'search_tool' function — "
                "P5 must expose the function for docstring assertion."
            )

        doc = getattr(search_fn, "__doc__", "") or ""
        assert "file_paths" in doc, (
            f"MCP search tool docstring must mention 'file_paths' after P5 update.\n"
            f"Current docstring:\n{doc!r}"
        )
