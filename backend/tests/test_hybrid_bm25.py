"""Tests for BM25 survival through hybrid search pipeline.

Verifies that all RRF fusion candidates survive through reranking:
- Candidates beyond pool_size are merged back with fusion-only scores
- BM25-only matches that score low on cross-encoder still appear in results
- Diagnostic logging reports BM25-only survival counts
"""

import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_service(tmp_path: Path) -> "DotMDService":
    """Create a DotMDService with real internals for integration testing."""
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings

    settings = Settings(
        index_dir=tmp_path / "idx",
        embedding_url="http://test:8088",
        rerank_pool_size=20,
    )
    service = DotMDService(settings=settings)
    return service


class TestMergeBackBeyondPoolSize:
    """Fusion candidates beyond pool_size are preserved via merge-back."""

    def test_candidates_beyond_pool_size_preserved(self, tmp_path: Path) -> None:
        """After reranking, candidates beyond pool_size appear with fusion-only scores."""
        service = _make_service(tmp_path)

        # Create 25 unique fused results (pool_size=20, so 5 skip the reranker)
        # Semantic returns 15 unique chunks, BM25 returns 15 unique (5 overlap)
        semantic_hits = [(f"sem-{i}", 0.9 - i * 0.05) for i in range(15)]
        bm25_hits = [(f"bm25-{i}", 8.0 - i * 0.3) for i in range(15)]

        # Mock search engines
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._bm25_engine = MagicMock()
        service._bm25_engine.search.return_value = bm25_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        # Mock reranker to return scored results for pool_size candidates
        def mock_rerank(query, chunk_ids, store, top_k=5):
            # Return all chunk_ids it receives with sequential scores
            return [(cid, 10.0 - i * 0.5) for i, cid in enumerate(chunk_ids)]

        service._reranker = MagicMock()
        service._reranker.rerank.side_effect = mock_rerank

        # Mock metadata store for build_search_results
        mock_chunk = MagicMock()
        mock_chunk.heading_hierarchy = []
        mock_chunk.text = "Some text content for testing"
        mock_chunk.file_path = Path("/test/file.md")
        service._pipeline.metadata_store.get_chunks = MagicMock(
            return_value=[mock_chunk]
        )

        results_raw = []

        # Patch build_search_results to capture fused list before it's truncated
        original_build = None
        import dotmd.api.service as svc_module

        original_build = svc_module.build_search_results

        captured_fused = []

        def capture_build(fused, **kwargs):
            captured_fused.extend(fused)
            return original_build(fused, **kwargs)

        with patch.object(svc_module, "build_search_results", side_effect=capture_build):
            service.search("test query", top_k=30, mode="hybrid", rerank=True)

        # The fused list passed to build_search_results should contain more
        # than pool_size candidates (merge-back appended the extras)
        assert len(captured_fused) > 20, (
            f"Expected > 20 candidates after merge-back, got {len(captured_fused)}"
        )

        # The reranker should have been called with exactly pool_size (20) candidates
        call_args = service._reranker.rerank.call_args
        assert len(call_args[0][1]) == 20  # chunk_ids arg


class TestBM25SurvivalThroughReranking:
    """BM25-only candidates must survive even with low cross-encoder scores."""

    def test_bm25_only_candidate_survives_low_reranker_score(self, tmp_path: Path) -> None:
        """A BM25-only hit scored very low by cross-encoder still appears in final results."""
        service = _make_service(tmp_path)

        # BM25 finds "b1", semantic finds "s1" -- no overlap
        semantic_hits = [("s1", 0.9)]
        bm25_hits = [("b1", 5.0)]

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._bm25_engine = MagicMock()
        service._bm25_engine.search.return_value = bm25_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        # Reranker scores "b1" very low (-15.0) but it must still survive
        def mock_rerank(query, chunk_ids, store, top_k=5):
            scores = {"s1": 8.0, "b1": -15.0}
            results = [(cid, scores.get(cid, 0.0)) for cid in chunk_ids]
            results.sort(key=lambda x: x[1], reverse=True)
            return results

        service._reranker = MagicMock()
        service._reranker.rerank.side_effect = mock_rerank

        # Capture fused list
        import dotmd.api.service as svc_module

        original_build = svc_module.build_search_results
        captured_fused = []

        def capture_build(fused, **kwargs):
            captured_fused.extend(fused)
            return original_build(fused, **kwargs)

        mock_chunk = MagicMock()
        mock_chunk.heading_hierarchy = []
        mock_chunk.text = "Some text"
        mock_chunk.file_path = Path("/test/file.md")
        service._pipeline.metadata_store.get_chunks = MagicMock(
            return_value=[mock_chunk]
        )

        with patch.object(svc_module, "build_search_results", side_effect=capture_build):
            service.search("test query", top_k=10, mode="hybrid", rerank=True)

        fused_ids = {cid for cid, _ in captured_fused}
        assert "b1" in fused_ids, f"BM25-only candidate 'b1' missing from final fused: {fused_ids}"
        assert "s1" in fused_ids, f"Semantic candidate 's1' missing from final fused: {fused_ids}"


class TestDiagnosticLogging:
    """Diagnostic logging reports BM25-only survival count."""

    def test_bm25_survival_logged_at_debug(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        """Log message matching 'BM25-only' present in captured logs at DEBUG level."""
        service = _make_service(tmp_path)

        semantic_hits = [("s1", 0.9)]
        bm25_hits = [("b1", 5.0)]

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._bm25_engine = MagicMock()
        service._bm25_engine.search.return_value = bm25_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        def mock_rerank(query, chunk_ids, store, top_k=5):
            return [(cid, 1.0 - i * 0.1) for i, cid in enumerate(chunk_ids)]

        service._reranker = MagicMock()
        service._reranker.rerank.side_effect = mock_rerank

        mock_chunk = MagicMock()
        mock_chunk.heading_hierarchy = []
        mock_chunk.text = "Some text"
        mock_chunk.file_path = Path("/test/file.md")
        service._pipeline.metadata_store.get_chunks = MagicMock(
            return_value=[mock_chunk]
        )

        with caplog.at_level(logging.DEBUG, logger="dotmd.api.service"):
            service.search("test query", top_k=10, mode="hybrid", rerank=True)

        bm25_log_messages = [r.message for r in caplog.records if "BM25-only" in r.message]
        assert len(bm25_log_messages) > 0, (
            f"Expected log message containing 'BM25-only', got: {[r.message for r in caplog.records]}"
        )
