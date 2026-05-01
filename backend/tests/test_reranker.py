"""Tests for the cross-encoder reranker."""

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from dotmd.search.reranker import Reranker, available_rerankers


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

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_provider_failure_can_raise_for_diagnostics(
        self,
        MockCE: MagicMock,
    ) -> None:
        """Diagnostic comparison can distinguish provider failure from empty output."""
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("provider failed")
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(1)

        with pytest.raises(RuntimeError, match="provider failed"):
            reranker.rerank(
                "test query",
                ["chunk-0"],
                mock_store,
                top_k=1,
                raise_on_provider_error=True,
            )

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_provider_failure_still_falls_back_for_normal_search(
        self,
        MockCE: MagicMock,
    ) -> None:
        """Normal search keeps the existing fused-ranking fallback behavior."""
        mock_model = MagicMock()
        mock_model.predict.side_effect = RuntimeError("provider failed")
        MockCE.return_value = mock_model

        reranker = _make_reranker()
        mock_store = _make_mock_store(1)

        results = reranker.rerank("test query", ["chunk-0"], mock_store, top_k=1)

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


class TestRerankerRegistry:
    """Built-in reranker registry exposes stable short names."""

    def test_available_rerankers_includes_builtin_names(self) -> None:
        """Available reranker names include all built-in registry entries."""
        assert available_rerankers() == [
            "bge-v2-m3",
            "gte-multilingual",
            "mmarco-minilm",
            "msmarco-minilm",
            "qwen3-0.6b",
        ]

    def test_qwen3_spec_maps_to_model_name(self) -> None:
        """The Qwen short name maps to the Phase 18 selected model."""
        from dotmd.search.reranker import BUILTIN_RERANKERS

        assert BUILTIN_RERANKERS["qwen3-0.6b"].model_name == "Qwen/Qwen3-Reranker-0.6B"

    def test_msmarco_minilm_spec_maps_to_model_name(self) -> None:
        """The legacy MiniLM short name maps to the existing baseline model."""
        from dotmd.search.reranker import BUILTIN_RERANKERS

        assert (
            BUILTIN_RERANKERS["msmarco-minilm"].model_name
            == "cross-encoder/ms-marco-MiniLM-L-6-v2"
        )


class TestRerankerFactory:
    """Reranker factory resolves stable names to cached adapter instances."""

    def test_create_reranker_resolves_qwen_name(self) -> None:
        """create_reranker returns an adapter with stable name and model metadata."""
        from dotmd.core.config import Settings
        from dotmd.search.reranker import create_reranker

        settings = Settings(embedding_url="http://test:8088")

        reranker = create_reranker("qwen3-0.6b", settings)

        assert reranker.name == "qwen3-0.6b"
        assert reranker.model_name == "Qwen/Qwen3-Reranker-0.6B"

    def test_create_reranker_rejects_unknown_name(self) -> None:
        """Unknown reranker names fail loudly with available names."""
        from dotmd.core.config import Settings
        from dotmd.search.reranker import create_reranker

        settings = Settings(embedding_url="http://test:8088")

        with pytest.raises(ValueError, match=r"Unknown reranker.*qwen3-0\.6b"):
            create_reranker("does-not-exist", settings)

    def test_factory_caches_instances_by_name(self) -> None:
        """A factory instance reuses the same adapter for repeated lookups."""
        from dotmd.core.config import Settings
        from dotmd.search.reranker import RerankerFactory

        settings = Settings(embedding_url="http://test:8088")
        factory = RerankerFactory(settings)

        assert factory.get("qwen3-0.6b") is factory.get("qwen3-0.6b")

    @patch("sentence_transformers.CrossEncoder", autospec=True)
    def test_cross_encoder_reranker_warmup_loads_model_without_scoring(
        self,
        MockCE: MagicMock,
    ) -> None:
        """warmup() uses the lazy load path without calling predict()."""
        from dotmd.search.reranker import CrossEncoderReranker

        mock_model = MagicMock()
        MockCE.return_value = mock_model

        reranker = CrossEncoderReranker(model_name="test-model", name="test")
        reranker.warmup()

        MockCE.assert_called_once_with("test-model")
        mock_model.predict.assert_not_called()

    def test_create_reranker_passes_settings_to_adapter(self) -> None:
        """Factory passes reranker scoring knobs from Settings into the adapter."""
        from dotmd.core.config import Settings
        from dotmd.search.reranker import create_reranker

        settings = Settings(
            embedding_url="http://test:8088",
            reranker_length_penalty=False,
            reranker_min_length=123,
            reranker_relevance_floor=0.25,
        )

        reranker = create_reranker("qwen3-0.6b", settings)

        assert reranker._length_penalty is False
        assert reranker._min_length == 123
        assert reranker._relevance_floor == 0.25

    def test_legacy_reranker_alias_still_constructs_cross_encoder_adapter(self) -> None:
        """The legacy Reranker import path remains a compatibility alias."""
        from dotmd.search.reranker import CrossEncoderReranker, Reranker

        assert Reranker is CrossEncoderReranker
