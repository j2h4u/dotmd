"""Smoke test for hybrid fusion (TEST-04)."""

import pytest

from tests.smoke.conftest import tool_call, tool_result

pytestmark = pytest.mark.smoke


class TestHybridFusion:
    """Search fuses results from multiple engines."""

    def test_search_returns_multi_engine_results(self):
        """TEST-04: search returns results hit by at least 2 distinct engines."""
        data = tool_call("search", {"query": "test", "top_k": 50})
        results = tool_result(data)
        assert len(results) > 0, "search returned no results"

        all_engines: set[str] = set()
        for r in results:
            engines = r.get("matched_engines") or []
            all_engines.update(engines)

        assert len(all_engines) >= 2, (
            f"Expected results from >= 2 engines, got only: {all_engines}"
        )
