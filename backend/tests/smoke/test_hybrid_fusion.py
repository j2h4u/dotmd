"""Smoke test for hybrid fusion (TEST-04)."""

import httpx
import pytest

pytestmark = [pytest.mark.smoke, pytest.mark.usefixtures("ensure_indexed")]


class TestHybridFusion:
    """Hybrid mode fuses results from multiple engines."""

    def test_hybrid_combines_multiple_engines(self, client: httpx.Client):
        """TEST-04: Hybrid returns results from at least 2 engines."""
        r = client.get("/search", params={"q": "test", "top_k": 10, "mode": "hybrid"})
        assert r.status_code == 200
        data = r.json()
        assert data["count"] > 0, "Hybrid search returned no results"

        all_engines = set()
        for result in data["results"]:
            all_engines.update(result["matched_engines"])

        assert len(all_engines) >= 2, (
            f"Expected results from >= 2 engines, got only: {all_engines}"
        )
