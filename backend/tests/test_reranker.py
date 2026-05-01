"""Tests for the cross-encoder reranker."""

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


class TestRerankerScoring:
    """Reranker preserves candidate mapping and optional floor behavior."""

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_candidate_texts_are_scored_in_chunk_id_order(self, MockCE: MagicMock) -> None:
        """Model input order follows requested chunk_ids, not store return order."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([1.0, 2.0, 3.0])
        MockCE.return_value = mock_model

        store = MagicMock()
        store.get_chunks.return_value = [
            MagicMock(chunk_id="chunk-b", text="Text B"),
            MagicMock(chunk_id="chunk-a", text="Text A"),
            MagicMock(chunk_id="chunk-c", text="Text C"),
        ]

        reranker = _make_reranker()
        reranker.rerank(
            "test query",
            ["chunk-a", "chunk-b", "chunk-c"],
            store,
            top_k=10,
        )

        assert mock_model.predict.call_args.args[0] == [
            ("test query", "Text A"),
            ("test query", "Text B"),
            ("test query", "Text C"),
        ]

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_scores_map_back_to_original_chunk_ids(self, MockCE: MagicMock) -> None:
        """Returned scores remain attached to the original requested chunk IDs."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([0.2, 9.0, 1.5])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(3)

        results = reranker.rerank(
            "test query",
            ["chunk-0", "chunk-1", "chunk-2"],
            mock_store,
            top_k=10,
        )

        assert results == [("chunk-1", 9.0), ("chunk-2", 1.5), ("chunk-0", 0.2)]

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_relevance_floor_none_keeps_low_scores(self, MockCE: MagicMock) -> None:
        """None disables raw-score filtering, including negative scores."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-20.0, -10.0, -5.0])
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(3)

        results = reranker.rerank(
            "test query",
            ["chunk-0", "chunk-1", "chunk-2"],
            mock_store,
            top_k=10,
        )

        assert results == [("chunk-2", -5.0), ("chunk-1", -10.0), ("chunk-0", -20.0)]

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_relevance_floor_filters_when_configured(self, MockCE: MagicMock) -> None:
        """Configured floors filter scores below the threshold."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-1.0, 0.5, 2.0])
        MockCE.return_value = mock_model

        reranker = Reranker(
            model_name="test-model",
            length_penalty=False,
            min_length=100,
            relevance_floor=0.0,
        )
        mock_store = _make_mock_store(3)

        results = reranker.rerank(
            "test query",
            ["chunk-0", "chunk-1", "chunk-2"],
            mock_store,
            top_k=10,
        )

        assert results == [("chunk-2", 2.0), ("chunk-1", 0.5)]

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_length_penalty_lowers_short_chunk_with_negative_scores(
        self,
        MockCE: MagicMock,
    ) -> None:
        """Length penalty lowers short chunks even when raw scores are negative."""
        mock_model = MagicMock()
        mock_model.predict.return_value = np.array([-5.0, -5.0])
        MockCE.return_value = mock_model

        store = MagicMock()
        store.get_chunks.return_value = [
            MagicMock(chunk_id="short", text="tiny"),
            MagicMock(chunk_id="long", text="Long text " * 30),
        ]

        reranker = Reranker(
            model_name="test-model",
            length_penalty=True,
            min_length=100,
        )

        results = reranker.rerank(
            "test query",
            ["short", "long"],
            store,
            top_k=10,
        )

        assert results[0][0] == "long"
        assert results[1][0] == "short"

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

    def test_settings_default_qwen3_reranker(self) -> None:
        """Settings defaults to the selected Phase 18 reranker."""
        from dotmd.core.config import Settings

        settings = Settings(embedding_url="http://test:8088")

        assert settings.reranker_backend == "cross_encoder"
        assert settings.reranker_model == "Qwen/Qwen3-Reranker-0.6B"
        assert settings.reranker_relevance_floor is None

    def test_settings_default_reranker_name(self) -> None:
        """Settings defaults to the stable Qwen reranker name."""
        from dotmd.core.config import Settings

        settings = Settings(embedding_url="http://test:8088")

        assert settings.reranker_name == "qwen3-0.6b"

    def test_settings_default_parsed_reranker_compare_names(self) -> None:
        """Settings exposes default comparison names as a parsed list."""
        from dotmd.core.config import Settings

        settings = Settings(embedding_url="http://test:8088")

        assert settings.parsed_reranker_compare_names == [
            "qwen3-0.6b",
            "msmarco-minilm",
            "mmarco-minilm",
            "gte-multilingual",
        ]

    def test_settings_parsed_reranker_compare_names_ignores_empty_entries(self) -> None:
        """Settings ignores blank entries in comma-separated comparison names."""
        from dotmd.core.config import Settings

        settings = Settings(
            embedding_url="http://test:8088",
            reranker_compare_names="qwen3-0.6b, ,msmarco-minilm",
        )

        assert settings.parsed_reranker_compare_names == [
            "qwen3-0.6b",
            "msmarco-minilm",
        ]
