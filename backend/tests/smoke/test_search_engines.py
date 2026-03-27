"""Smoke tests for individual search engines (TEST-01, TEST-02, TEST-03)."""

import httpx
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("ensure_indexed")]


class TestSearchEngines:
    """Each search engine returns results for a known query."""

    def test_semantic_returns_results(self, client: httpx.Client):
        """TEST-01: Semantic search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "semantic"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Semantic search returned no results"
        for result in data["results"]:
            assert "semantic" in result["matched_engines"]

    def test_bm25_returns_results(self, client: httpx.Client):
        """TEST-02: BM25 search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "bm25"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "BM25 search returned no results"
        for result in data["results"]:
            assert "bm25" in result["matched_engines"]

    def test_graph_returns_results(self, client: httpx.Client):
        """TEST-03: Graph search returns results."""
        r = client.get("/search", params={"q": "test", "top_k": 5, "mode": "graph"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Graph search returned no results"
        for result in data["results"]:
            assert "graph" in result["matched_engines"]
