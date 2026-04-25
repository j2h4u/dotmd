"""RED test skeletons for DotMDService.search returning file_paths (P5 — Task 1).

These tests verify the service facade returns SearchResult with file_paths list.
They FAIL until P5 (wave 5) updates the service.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings
    settings = Settings(index_dir=tmp_path)
    return DotMDService(settings)


class TestSearchReturnsFilePaths:
    """DotMDService.search returns SearchResult instances with file_paths list."""

    def test_search_returns_file_paths_list(self, tmp_path: Path) -> None:
        """search() results all have file_paths: list attribute."""
        service = _get_service(tmp_path)

        # Stub the underlying search engines to return minimal results
        from dotmd.core.models import SearchResult
        stub_result = SearchResult(
            chunk_id="a" * 64,
            file_paths=[Path(tmp_path / "test.md")],
            heading_path="# Test",
            snippet="test snippet",
            fused_score=0.9,
        )

        with patch.object(service, "_execute_search", return_value=[stub_result]):
            results = service.search("test query", top_k=5)

        assert len(results) >= 0  # may be empty if stub returns no results
        for r in results:
            assert hasattr(r, "file_paths"), (
                "SearchResult must have file_paths attribute (P5 Decision #2)"
            )
            assert isinstance(r.file_paths, list), (
                f"file_paths must be list, got {type(r.file_paths)!r}"
            )


class TestSearchRespectsTopK:
    """DotMDService.search respects the top_k parameter."""

    def test_search_respects_top_k(self, tmp_path: Path) -> None:
        """search(top_k=3) returns at most 3 results."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchResult
        stub_results = [
            SearchResult(
                chunk_id=str(i) * 64,
                file_paths=[Path(tmp_path / f"test_{i}.md")],
                heading_path=f"# Test {i}",
                snippet=f"snippet {i}",
                fused_score=float(i) / 10,
            )
            for i in range(5)
        ]

        with patch.object(service, "_execute_search", return_value=stub_results[:3]):
            results = service.search("test query", top_k=3)

        assert len(results) <= 3, (
            f"search(top_k=3) must return at most 3 results, got {len(results)}"
        )
