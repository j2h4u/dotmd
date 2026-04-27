"""Smoke tests for search quality and rerank behavior (TEST-01, TEST-02, TEST-03)."""

import pytest

from tests.smoke.conftest import is_tool_error, tool_call, tool_result

pytestmark = pytest.mark.smoke


class TestSearchEngines:
    """Search returns results for various query types."""

    def test_english_query_returns_results(self):
        """TEST-01: English query returns at least one result."""
        data = tool_call("search", {"query": "meeting notes", "top_k": 5})
        assert not is_tool_error(data)
        results = tool_result(data)
        assert len(results) > 0, "English query returned no results"

    def test_russian_query_returns_results(self):
        """TEST-02: Russian (multilingual) query returns results."""
        data = tool_call("search", {"query": "встреча", "top_k": 5})
        assert not is_tool_error(data)
        results = tool_result(data)
        assert len(results) > 0, "Russian query returned no results"

    def test_rerank_enabled_returns_results(self):
        """TEST-03: search with rerank=True returns results without error."""
        data = tool_call("search", {"query": "test", "top_k": 5, "rerank": True})
        assert not is_tool_error(data), f"rerank search returned error: {data}"
        results = tool_result(data)
        assert isinstance(results, list)
