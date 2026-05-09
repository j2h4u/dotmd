"""Contract tests for SearchCandidate, SearchResponse, and SourceStatus models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from dotmd.core.models import (
    ChunkProvenance,
    SearchCandidate,
    SearchResponse,
    SourceStatus,
)


class TestSearchCandidateRequiredFields:
    """Test SearchCandidate construction with required fields only."""

    def test_search_candidate_required_fields_pin_local_shape(self) -> None:
        """Construct a SearchCandidate with minimal local shape."""
        candidate = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Some text snippet",
            fused_score=0.95,
            can_read=True,
        )
        assert candidate.can_materialize is False
        assert candidate.engine_scores is None
        assert candidate.provider_metadata is None
        assert candidate.source_native_score is None
        assert candidate.source_native_rank is None
        assert candidate.matched_engines == ()

    def test_search_candidate_required_fields_pin_federated_shape(self) -> None:
        """Construct a SearchCandidate with federated shape."""
        candidate = SearchCandidate(
            ref="telegram:dialog:1:message:7",
            namespace="telegram",
            descriptor_key="telegram",
            source_kind="chat",
            retrieval_kind="tg:fts",
            snippet="Message text",
            fused_score=0.88,
            can_read=True,
            source_native_score=0.93,
            source_native_rank=0,
            provider_metadata={"dialog_id": 1},
        )
        assert candidate.chunk_id is None
        assert candidate.provenance is None
        assert candidate.heading_path is None
        assert candidate.engine_scores is None

    def test_search_candidate_descriptor_key_is_required(self) -> None:
        """descriptor_key must be provided (no default)."""
        with pytest.raises(ValidationError) as exc_info:
            SearchCandidate(
                ref="filesystem:/tmp/a.md#0",
                namespace="filesystem",
                source_kind="markdown",
                retrieval_kind="semantic",
                snippet="Text",
                fused_score=0.9,
                can_read=True,
                # Intentionally omit descriptor_key to test it's required
            )  # type: ignore[call-arg]
        assert "descriptor_key" in str(exc_info.value).lower()

    def test_search_candidate_descriptor_key_distinguishes_sources(self) -> None:
        """Two candidates with different descriptor_key are distinguishable."""
        candidate1 = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Text",
            fused_score=0.9,
            can_read=True,
        )
        candidate2 = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-srv",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Text",
            fused_score=0.9,
            can_read=True,
        )
        assert candidate1 != candidate2
        assert candidate1.descriptor_key == "filesystem-mnt"
        assert candidate2.descriptor_key == "filesystem-srv"

    def test_search_candidate_rejects_extra_fields(self) -> None:
        """SearchCandidate with extra fields raises ValidationError."""
        with pytest.raises(ValidationError) as exc_info:
            SearchCandidate(
                ref="filesystem:/tmp/a.md#0",
                namespace="filesystem",
                descriptor_key="filesystem-mnt",
                source_kind="markdown",
                retrieval_kind="semantic",
                snippet="Text",
                fused_score=0.9,
                can_read=True,
                extra_field="not allowed",  # type: ignore[call-arg]
            )
        assert "extra" in str(exc_info.value).lower()

    def test_search_candidate_is_frozen_after_construction(self) -> None:
        """SearchCandidate rejects attribute assignment after construction."""
        candidate = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Text",
            fused_score=0.9,
            can_read=True,
        )
        with pytest.raises(ValidationError):
            candidate.snippet = "modified"  # type: ignore[misc]

    def test_search_candidate_frozen_is_shallow_for_container_fields(self) -> None:
        """SearchCandidate frozen=True is shallow: rebinding rejected, mutation succeeds."""
        candidate = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Text",
            fused_score=0.9,
            can_read=True,
            matched_engines=("semantic",),
            engine_scores={"semantic": 0.9},
            provider_metadata={"k": "v"},
        )

        # Top-level rebinding is rejected (frozen=True)
        with pytest.raises(ValidationError):
            candidate.snippet = "x"  # type: ignore[misc]

        with pytest.raises(ValidationError):
            candidate.matched_engines = ("other",)  # type: ignore[misc]

        with pytest.raises(ValidationError):
            candidate.engine_scores = {}  # type: ignore[misc]

        with pytest.raises(ValidationError):
            candidate.provider_metadata = None  # type: ignore[misc]

        # matched_engines is a tuple — truly immutable, no append
        assert candidate.matched_engines == ("semantic",)

        # Dict container fields are still shallow-mutable
        assert candidate.engine_scores is not None
        candidate.engine_scores["keyword"] = 0.5
        assert candidate.engine_scores["keyword"] == 0.5

        assert candidate.provider_metadata is not None
        candidate.provider_metadata["new"] = "z"
        assert candidate.provider_metadata["new"] == "z"

    def test_search_candidate_validates_ref_namespace_separator(self) -> None:
        """SearchCandidate validates ref format."""
        with pytest.raises(ValueError) as exc_info:
            SearchCandidate(
                ref="badref",
                namespace="filesystem",
                descriptor_key="filesystem-mnt",
                source_kind="markdown",
                retrieval_kind="semantic",
                snippet="Text",
                fused_score=0.9,
                can_read=True,
            )
        assert "formatted" in str(exc_info.value).lower()

    def test_engine_scores_only_populated_for_matching_engines(self) -> None:
        """engine_scores dict contains only engines that scored this ref."""
        candidate = SearchCandidate(
            ref="filesystem:/tmp/a.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="Text",
            fused_score=0.9,
            can_read=True,
            engine_scores={"semantic": 0.9},
        )
        assert candidate.engine_scores is not None
        assert "semantic" in candidate.engine_scores
        assert len(candidate.engine_scores) == 1

    def test_search_response_envelope_has_candidates_and_source_status(self) -> None:
        """SearchResponse has candidates and source_status fields."""
        response = SearchResponse(
            candidates=[],
            source_status=[],
        )
        assert response.candidates == []
        assert response.source_status == []

        # Verify extra forbid
        with pytest.raises(ValidationError):
            SearchResponse(
                candidates=[],
                source_status=[],
                extra_field="not allowed",  # type: ignore[call-arg]
            )

    def test_source_status_required_fields(self) -> None:
        """SourceStatus has required name, status, and optional fields."""
        status = SourceStatus(
            name="semantic",
            status="ok",
            candidate_count=3,
            elapsed_ms=12.5,
        )
        assert status.name == "semantic"
        assert status.status == "ok"
        assert status.reason is None

        # Test status literal validation
        with pytest.raises(ValidationError):
            SourceStatus(
                name="semantic",
                status="weird",  # type: ignore[arg-type]
                candidate_count=0,
            )

    def test_search_result_symbol_no_longer_exported(self) -> None:
        """SearchResult is not exported from core.models."""
        with pytest.raises(ImportError):
            from dotmd.core.models import SearchResult  # type: ignore[import-not-found]

        # Defense-in-depth: check the file does not contain SearchResult class
        from pathlib import Path

        models_file = Path(__file__).parent.parent.parent / "src" / "dotmd" / "core" / "models.py"
        with open(models_file) as f:
            content = f.read()
            # Rough check: class SearchResult should not be defined at module level
            import re

            class_def = re.search(r"^class SearchResult\b", content, re.MULTILINE)
            assert (
                class_def is None
            ), "SearchResult class definition found in models.py after removal"
