"""MCP smoke tests — run inside the dotMD container against the live HTTP server.

Usage:
    docker exec dotmd pytest tests/e2e/ -v

PINNING CONTRACT
---------------
EXPECTED_TOOLS is the authoritative list of supported MCP tools.
test_tool_surface enforces an exact match: adding or removing a tool without
updating this set will fail the suite immediately. This prevents silent drift
where new tools ship without smoke coverage.

Workflow when adding a new tool:
  1. Add the tool name to EXPECTED_TOOLS.
  2. Add a smoke test class for it below (call + field shape check).
  3. Run the suite to confirm green.
"""

from __future__ import annotations

import json

import pytest

from tests.e2e.conftest import _is_tool_error, _mcp_post, _tool_result_structured, _tool_result_text

pytestmark = pytest.mark.e2e

# ---------------------------------------------------------------------------
# Pinned tool surface
# ---------------------------------------------------------------------------

# KEEP THIS IN SYNC WITH mcp_server.py.
# Exact match — test_tool_surface will fail if actual != expected.
EXPECTED_TOOLS: frozenset[str] = frozenset({"search", "drill", "status"})

# Pinned fields returned by search results.
# Update when adding/removing fields in _format_result().
EXPECTED_SEARCH_RESULT_FIELDS: frozenset[str] = frozenset(
    {"file_paths", "heading", "snippet", "score"}
)

# Pinned top-level keys returned by drill().
EXPECTED_DRILL_KEYS: frozenset[str] = frozenset(
    {"file_path", "frontmatter", "chunk_count", "entities"}
)


# ---------------------------------------------------------------------------
# Surface contract
# ---------------------------------------------------------------------------


class TestToolSurface:
    """Exact tool list — fails immediately when surface changes without test coverage."""

    def test_tool_list_matches_pinned(self):
        data = _mcp_post("tools/list")
        assert "result" in data, f"unexpected response: {data}"
        actual = frozenset(t["name"] for t in data["result"]["tools"])
        assert actual == EXPECTED_TOOLS, (
            f"MCP tool surface changed!\n"
            f"  Pinned : {sorted(EXPECTED_TOOLS)}\n"
            f"  Actual : {sorted(actual)}\n"
            f"  Added  : {sorted(actual - EXPECTED_TOOLS)}\n"
            f"  Removed: {sorted(EXPECTED_TOOLS - actual)}\n"
            "→ Add smoke tests for new tools, then update EXPECTED_TOOLS."
        )


# ---------------------------------------------------------------------------
# status smoke
# ---------------------------------------------------------------------------


class TestStatusSmoke:
    def test_returns_without_error(self):
        data = _mcp_post("tools/call", {"name": "status", "arguments": {}})
        assert not _is_tool_error(data), f"status returned error: {_tool_result_text(data)}"
        assert "result" in data

    def test_has_required_fields(self):
        data = _mcp_post("tools/call", {"name": "status", "arguments": {}})
        payload = _tool_result_structured(data)
        assert isinstance(payload, dict)
        for field in ("total_files", "total_chunks", "trickle_status"):
            assert field in payload, f"status missing field: {field!r}"

    def test_index_is_populated(self):
        data = _mcp_post("tools/call", {"name": "status", "arguments": {}})
        payload = _tool_result_structured(data)
        assert payload["total_files"] > 0, "index appears empty — smoke requires indexed data"
        assert payload["total_chunks"] > 0


# ---------------------------------------------------------------------------
# search smoke
# ---------------------------------------------------------------------------


class TestSearchSmoke:
    def test_returns_results_for_generic_query(self):
        data = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 3}})
        assert not _is_tool_error(data), f"search returned error: {_tool_result_text(data)}"
        results = _tool_result_structured(data)
        assert isinstance(results, list), f"search must return a list, got: {type(results)}"
        assert len(results) > 0, "search returned no results — index may be empty"

    def test_result_fields_match_pinned(self):
        """Catches silent field renames or additions in _format_result()."""
        data = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check fields against")
        actual_keys = frozenset(results[0].keys())
        assert actual_keys == EXPECTED_SEARCH_RESULT_FIELDS, (
            f"search result fields changed!\n"
            f"  Pinned: {sorted(EXPECTED_SEARCH_RESULT_FIELDS)}\n"
            f"  Actual: {sorted(actual_keys)}"
        )

    def test_file_paths_is_list(self):
        data = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check")
        assert isinstance(results[0]["file_paths"], list)
        assert all(isinstance(p, str) for p in results[0]["file_paths"])

    def test_score_is_float_in_range(self):
        data = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "тест"}})
        results = _tool_result_structured(data)
        if not results:
            pytest.skip("no results to check")
        score = results[0]["score"]
        assert isinstance(score, float), f"score must be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"score out of range: {score}"

    def test_top_k_respected(self):
        data = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "тест", "top_k": 2}})
        results = _tool_result_structured(data)
        assert len(results) <= 2, f"top_k=2 but got {len(results)} results"


# ---------------------------------------------------------------------------
# drill smoke
# ---------------------------------------------------------------------------


class TestDrillSmoke:
    def test_returns_without_error_for_nonexistent_path(self):
        """drill on a missing file returns empty frontmatter, not a crash."""
        data = _mcp_post("tools/call", {"name": "drill", "arguments": {"file_path": "/nonexistent/file.md"}})
        assert not data.get("error"), f"protocol-level error: {data.get('error')}"
        assert "result" in data

    def test_result_fields_match_pinned_for_nonexistent(self):
        data = _mcp_post("tools/call", {"name": "drill", "arguments": {"file_path": "/nonexistent/file.md"}})
        payload = _tool_result_structured(data)
        assert isinstance(payload, dict)
        actual_keys = frozenset(payload.keys())
        assert actual_keys == EXPECTED_DRILL_KEYS, (
            f"drill result fields changed!\n"
            f"  Pinned: {sorted(EXPECTED_DRILL_KEYS)}\n"
            f"  Actual: {sorted(actual_keys)}"
        )

    def test_drill_real_file_via_search(self):
        """Obtain a real file_path from search, then drill it for non-empty frontmatter."""
        search = _mcp_post("tools/call", {"name": "search", "arguments": {"query": "встреча", "top_k": 1}})
        results = _tool_result_structured(search)
        if not results:
            pytest.skip("search returned no results — cannot test drill on real file")

        file_path = results[0]["file_paths"][0]
        data = _mcp_post("tools/call", {"name": "drill", "arguments": {"file_path": file_path}})
        assert not _is_tool_error(data), f"drill errored on {file_path}: {_tool_result_text(data)}"

        payload = _tool_result_structured(data)
        assert payload["file_path"] == file_path
        assert isinstance(payload["frontmatter"], dict)
        assert isinstance(payload["entities"], list)
        assert isinstance(payload["chunk_count"], int)
        assert payload["chunk_count"] > 0, f"expected chunks for indexed file {file_path}"
