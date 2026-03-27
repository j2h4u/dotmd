"""Smoke test for API response structure (TEST-05)."""

import httpx
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("ensure_indexed")]


class TestAPI:
    """API returns well-formed responses."""

    def test_search_returns_valid_json(self, client: httpx.Client):
        """TEST-05: Search endpoint returns HTTP 200 with valid JSON structure."""
        r = client.get("/search", params={"q": "test", "top_k": 3})
        assert r.status_code == 200

        data = r.json()

        # Top-level fields
        assert "query" in data
        assert "results" in data
        assert "count" in data
        assert isinstance(data["results"], list)
        assert data["count"] == len(data["results"])

        # Per-result structure (if results exist)
        if data["results"]:
            result = data["results"][0]
            assert "chunk_id" in result
            assert "file_path" in result
            assert "snippet" in result
            assert "fused_score" in result
            assert isinstance(result["fused_score"], (int, float))
            assert result["fused_score"] > 0
            assert "matched_engines" in result
            assert isinstance(result["matched_engines"], list)
            assert len(result["matched_engines"]) > 0
