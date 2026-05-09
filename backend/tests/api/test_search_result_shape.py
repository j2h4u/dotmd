"""SearchCandidate public contract tests (replaced SearchResult in Phase 34)."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError


def _search_candidate_kwargs(ref: str) -> dict[str, Any]:
    return {
        "ref": ref,
        "namespace": "filesystem",
        "descriptor_key": "filesystem-mnt",
        "source_kind": "markdown",
        "retrieval_kind": "semantic",
        "snippet": "snippet",
        "fused_score": 0.9,
        "can_read": True,
    }


class TestSearchCandidateRefContract:
    """Phase 34: SearchCandidate is source-ref-first."""

    def test_search_candidate_has_ref_not_file_paths(self) -> None:
        from dotmd.core.models import SearchCandidate

        fields = SearchCandidate.model_fields

        assert "ref" in fields
        assert "file_paths" not in fields
        assert "file_path" not in fields

    def test_filesystem_ref_is_accepted(self) -> None:
        from dotmd.core.models import SearchCandidate

        result = SearchCandidate(**_search_candidate_kwargs("filesystem:/mnt/test.md#0"))

        assert result.ref == "filesystem:/mnt/test.md#0"

    @pytest.mark.parametrize(
        "ref",
        [
            "filesystem-missing-colon",
            ":/mnt/test.md",
            "filesystem:",
        ],
    )
    def test_invalid_ref_is_rejected(self, ref: str) -> None:
        from dotmd.core.models import SearchCandidate

        with pytest.raises(ValidationError):
            SearchCandidate(**_search_candidate_kwargs(ref))
