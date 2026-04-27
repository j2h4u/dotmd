"""Smoke test for MCP search response structure (TEST-05)."""

import pytest

from tests.smoke.conftest import is_tool_error, tool_call, tool_result

pytestmark = pytest.mark.smoke


class TestAPI:
    """MCP search returns well-formed responses."""

    def test_search_returns_results(self):
        """TEST-05: search tool returns a list with at least one result."""
        data = tool_call("search", {"query": "test", "top_k": 3})
        assert not is_tool_error(data), f"search returned error: {data}"
        results = tool_result(data)
        assert isinstance(results, list)
        assert len(results) > 0, "search returned no results"

    def test_result_has_required_fields(self):
        """Each search result has the expected fields."""
        data = tool_call("search", {"query": "test", "top_k": 3})
        results = tool_result(data)
        if not results:
            pytest.skip("no results to check fields")
        result = results[0]
        for field in ("file_paths", "heading", "snippet", "score"):
            assert field in result, f"missing field: {field!r}"

    def test_score_is_float_in_range(self):
        data = tool_call("search", {"query": "test", "top_k": 3})
        results = tool_result(data)
        if not results:
            pytest.skip("no results to check")
        score = results[0]["score"]
        assert isinstance(score, float), f"score must be float, got {type(score)}"
        assert 0.0 <= score <= 1.0, f"score out of range: {score}"

    def test_file_paths_is_list_of_strings(self):
        data = tool_call("search", {"query": "test", "top_k": 3})
        results = tool_result(data)
        if not results:
            pytest.skip("no results to check")
        fps = results[0]["file_paths"]
        assert isinstance(fps, list)
        assert all(isinstance(p, str) for p in fps)

    def test_top_k_respected(self):
        data = tool_call("search", {"query": "test", "top_k": 2})
        results = tool_result(data)
        assert len(results) <= 2, f"top_k=2 but got {len(results)} results"
