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


class TestRerankerNoThreshold:
    """Reranker must return ALL scored candidates regardless of score value."""

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_all_candidates_returned_regardless_of_score(self, MockCE: MagicMock) -> None:
        """Reranker.rerank() returns ALL scored candidates even with very negative scores."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-20.0, -10.0, -5.0, 2.0, 8.0])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(5)

        results = reranker.rerank("test query", [f"chunk-{i}" for i in range(5)], mock_store, top_k=10)

        # All 5 must be returned -- no filtering
        assert len(results) == 5
        # Sorted descending by score
        scores = [s for _, s in results]
        assert scores == [8.0, 2.0, -5.0, -10.0, -20.0]
        # All chunk_ids present
        ids = {cid for cid, _ in results}
        assert ids == {f"chunk-{i}" for i in range(5)}

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_top_k_truncation_works(self, MockCE: MagicMock) -> None:
        """top_k limits output count (performance limit, not relevance filter)."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-20.0, -10.0, -5.0, 2.0, 8.0])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(5)

        results = reranker.rerank("test query", [f"chunk-{i}" for i in range(5)], mock_store, top_k=3)

        assert len(results) == 3
        scores = [s for _, s in results]
        assert scores == [8.0, 2.0, -5.0]

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
