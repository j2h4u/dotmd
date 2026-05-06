"""SearchResult public contract tests."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from typing import Any


def _search_result_kwargs(ref: str) -> dict[str, Any]:
    return {
        "chunk_id": "a" * 64,
        "ref": ref,
        "heading_path": "# Heading",
        "snippet": "snippet",
        "fused_score": 0.9,
    }


class TestSearchResultRefContract:
    """Phase 26: SearchResult is source-ref-first."""

    def test_search_result_has_ref_not_file_paths(self) -> None:
        from dotmd.core.models import SearchResult

        fields = SearchResult.model_fields

        assert "ref" in fields
        assert "file_paths" not in fields
        assert "file_path" not in fields

    def test_filesystem_ref_is_accepted(self) -> None:
        from dotmd.core.models import SearchResult

        result = SearchResult(**_search_result_kwargs("filesystem:/mnt/test.md"))

        assert result.ref == "filesystem:/mnt/test.md"

    @pytest.mark.parametrize(
        "ref",
        [
            "filesystem-missing-colon",
            ":/mnt/test.md",
            "filesystem:",
        ],
    )
    def test_invalid_ref_is_rejected(self, ref: str) -> None:
        from dotmd.core.models import SearchResult

        with pytest.raises(ValidationError):
            SearchResult(**_search_result_kwargs(ref))
