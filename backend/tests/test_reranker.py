"""Tests for the cross-encoder reranker.

Verifies that the reranker reorders candidates by cross-encoder score
without applying any score threshold filter -- all scored candidates
survive reranking.
"""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from dotmd.search.reranker import Reranker


def _make_reranker() -> Reranker:
    """Create a Reranker without loading a real model."""
    return Reranker(
        model_name="test-model",
        length_penalty=False,
        min_length=100,
    )


def _make_mock_store(n: int = 5) -> MagicMock:
    """Create a mock MetadataStoreProtocol returning *n* chunks."""
    store = MagicMock()
    store.get_chunks.return_value = [
        MagicMock(chunk_id=f"chunk-{i}", text=f"Text for chunk {i} " * 20)
        for i in range(n)
    ]
    return store


class TestRerankerRelevanceFilter:
    """Reranker filters out candidates below the relevance floor (logit < 0)."""

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_irrelevant_candidates_filtered(self, MockCE: MagicMock) -> None:
        """Candidates with cross-encoder logit < 0 are dropped."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-20.0, -10.0, -5.0, 2.0, 8.0])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(5)

        results = reranker.rerank("test query", [f"chunk-{i}" for i in range(5)], mock_store, top_k=10)

        # Only logit >= 0 pass (2.0 and 8.0)
        assert len(results) == 2
        scores = [s for _, s in results]
        assert scores == [8.0, 2.0]
        # Only relevant chunk_ids present (indices 3 and 4 had scores 2.0 and 8.0)
        ids = {cid for cid, _ in results}
        assert ids == {"chunk-3", "chunk-4"}

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_top_k_truncation_works(self, MockCE: MagicMock) -> None:
        """top_k limits output even when more candidates pass relevance floor."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1.0, 3.0, 5.0, 7.0, 9.0])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(5)

        results = reranker.rerank("test query", [f"chunk-{i}" for i in range(5)], mock_store, top_k=3)

        assert len(results) == 3
        scores = [s for _, s in results]
        assert scores == [9.0, 7.0, 5.0]

    def test_empty_chunk_ids_returns_empty(self) -> None:
        """Reranker.rerank() with empty chunk_ids returns []."""
        reranker = _make_reranker()
        mock_store = MagicMock()
        results = reranker.rerank("test query", [], mock_store, top_k=10)
        assert results == []

    def test_init_rejects_score_threshold_parameter(self) -> None:
        """Reranker.__init__() does NOT accept score_threshold parameter."""
        with pytest.raises(TypeError):
            Reranker(
                model_name="test-model",
                length_penalty=False,
                min_length=100,
                score_threshold=-8.0,
            )

    def test_settings_has_no_rerank_score_threshold(self) -> None:
        """Settings class does NOT have rerank_score_threshold attribute."""
        from dotmd.core.config import Settings

        settings = Settings(embedding_url="http://test:8088")
        with pytest.raises(AttributeError):
            _ = settings.rerank_score_threshold
