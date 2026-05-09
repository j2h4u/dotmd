"""Tests for keyword-only survival through hybrid search pipeline.

Verifies that all RRF fusion candidates survive through reranking:
- Candidates beyond pool_size are merged back with fusion-only scores
- Keyword-only matches that score low on cross-encoder still appear in results
- Diagnostic logging reports keyword-only survival counts
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from sqlite3 import Connection
from typing import TYPE_CHECKING, cast
from unittest.mock import MagicMock, patch

import pytest

if TYPE_CHECKING:
    from dotmd.api.service import DotMDService


def _make_service(tmp_path: Path) -> DotMDService:
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


def _seed_chunk_provenance(service: DotMDService, chunk_ids: list[str]) -> None:
    """Seed source provenance for synthetic chunks returned by mocked engines."""
    from dotmd.core.models import ChunkProvenance, ResourceBinding, SourceDocument

    strategy = service._settings.chunk_strategy
    store = service._pipeline.metadata_store
    store.ensure_chunk_source_provenance_table(strategy)
    store.ensure_resource_bindings_table()
    now = datetime.now(tz=UTC)
    conn = cast(Connection, store._conn)
    for chunk_id in chunk_ids:
        document_ref = f"/test/{chunk_id}.md"
        document = SourceDocument(
            namespace="filesystem",
            document_ref=document_ref,
            ref=f"filesystem:{document_ref}",
            source_uri=document_ref,
            file_path=Path(document_ref),
            media_type="text/markdown",
            parser_name="markdown",
            document_type="document",
            title=f"{chunk_id}.md",
            updated_at=now,
            content_fingerprint=f"content-{chunk_id}",
            metadata_fingerprint=f"metadata-{chunk_id}",
            metadata_json={},
        )
        store.upsert_source_document(document, conn=conn)
        store.upsert_resource_binding(
            ResourceBinding(
                namespace="filesystem",
                resource_ref=document_ref,
                document_ref=document_ref,
                ref=f"filesystem:{document_ref}",
                active=True,
                bound_at=now,
                content_fingerprint=f"content-{chunk_id}",
                metadata_fingerprint=f"metadata-{chunk_id}",
                source_unit_refs=[],
                metadata_json={},
            ),
            conn=conn,
        )
        store.add_chunk_provenance(
            strategy,
            ChunkProvenance(
                namespace="filesystem",
                document_ref=document_ref,
                ref=f"filesystem:{document_ref}",
                source_unit_refs=[],
                chunk_strategy=strategy,
                parser_name="test",
            ),
            chunk_id,
            conn=conn,
        )
    conn.commit()


class TestMergeBackBeyondPoolSize:
    """Fusion candidates beyond pool_size are preserved via merge-back."""

    def test_candidates_beyond_pool_size_preserved(self, tmp_path: Path) -> None:
        """After reranking, candidates beyond pool_size appear with fusion-only scores."""
        service = _make_service(tmp_path)

        # Create 25 unique fused results (pool_size=20, so 5 skip the reranker)
        # Semantic returns 15 unique chunks, keyword returns 15 unique (5 overlap)
        semantic_hits = [(f"sem-{i}", 0.9 - i * 0.05) for i in range(15)]
        keyword_hits = [(f"kw-{i}", 8.0 - i * 0.3) for i in range(15)]
        _seed_chunk_provenance(
            service,
            [cid for cid, _score in semantic_hits + keyword_hits],
        )

        # Mock search engines
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = keyword_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        # Mock reranker to return scored results for pool_size candidates
        def mock_rerank(query, chunk_ids, store, top_k=5):
            # Return all chunk_ids it receives with sequential scores
            return [(cid, 10.0 - i * 0.5) for i, cid in enumerate(chunk_ids)]

        reranker = MagicMock()
        reranker.rerank.side_effect = mock_rerank
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        # Mock metadata store for build_search_results
        mock_chunk = MagicMock()
        mock_chunk.heading_hierarchy = []
        mock_chunk.text = "Some text content for testing"
        mock_chunk.file_path = Path("/test/file.md")
        service._pipeline.metadata_store.get_chunks = MagicMock(
            return_value=[mock_chunk]
        )


        # Patch build_candidates to capture fused list before it's truncated
        import dotmd.search.fusion as fusion_module

        original_build = fusion_module.build_candidates

        captured_fused = []

        def capture_build(fused, **kwargs):
            captured_fused.extend(fused)
            return original_build(fused, **kwargs)

        with patch.object(fusion_module, "build_candidates", side_effect=capture_build):
            service.search("test query", top_k=30, mode="hybrid", rerank=True)

        # The fused list passed to build_search_results should contain more
        # than pool_size candidates (merge-back appended the extras)
        assert len(captured_fused) > 20, (
            f"Expected > 20 candidates after merge-back, got {len(captured_fused)}"
        )

        # The reranker pool expands to satisfy the requested top_k.
        call_args = reranker.rerank.call_args
        assert len(call_args[0][1]) == 30  # chunk_ids arg


class TestRerankCandidatePool:
    """Reusable candidate pool preserves retrieval/fusion behavior."""

    def test_collect_candidate_pool_appends_graph_enrichment(self, tmp_path: Path) -> None:
        """Graph enrichment candidates are returned in fused and engine results."""
        service = _make_service(tmp_path)

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = [("b1", 5.0)]
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = [("g1", 0.7)]
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = [("gx1", 0.6), ("s1", 0.4)]

        pool = service._collect_candidate_pool(
            search_query="expanded query",
            original_query="original query",
            mode="hybrid",
            pool_size=10,
        )

        fused_ids = [cid for cid, _score in pool["fused"]]
        assert "gx1" in fused_ids
        assert "graph" in pool["engine_results"]
        assert pool["engine_results"]["graph"] == [("gx1", 0.6), ("s1", 0.4)]

    def test_collect_candidate_pool_calls_each_engine_once(self, tmp_path: Path) -> None:
        """One search request collects candidates from each engine exactly once."""
        service = _make_service(tmp_path)

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = [("b1", 5.0)]
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = [("g1", 0.7)]
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = [("gx1", 0.6)]

        pool = service._collect_candidate_pool(
            search_query="expanded query",
            original_query="original query",
            mode="hybrid",
            pool_size=10,
        )

        assert pool["fused"]
        service._semantic_engine.search.assert_called_once_with("expanded query", top_k=10)
        service._keyword_engine.search.assert_called_once_with("expanded query", top_k=10)
        service._graph_direct_engine.search.assert_called_once_with("original query", top_k=10)
        service._graph_engine.search.assert_called_once_with(
            "expanded query",
            top_k=10,
            seed_chunk_ids=[cid for cid, _score in pool["fused"] if cid != "gx1"][:10],
        )


class TestKeywordSurvivalThroughReranking:
    """Keyword-only candidates must survive even with low cross-encoder scores."""

    def test_keyword_only_candidate_survives_low_reranker_score(self, tmp_path: Path) -> None:
        """A keyword-only hit scored very low by cross-encoder still appears in final results."""
        service = _make_service(tmp_path)

        # Keyword finds "b1", semantic finds "s1" -- no overlap
        semantic_hits = [("s1", 0.9)]
        keyword_hits = [("b1", 5.0)]
        _seed_chunk_provenance(service, ["s1", "b1"])

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = keyword_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        # Reranker scores "b1" very low (-15.0) but it must still survive
        def mock_rerank(query, chunk_ids, store, top_k=5):
            scores = {"s1": 8.0, "b1": -15.0}
            results = [(cid, scores.get(cid, 0.0)) for cid in chunk_ids]
            results.sort(key=lambda x: x[1], reverse=True)
            return results

        reranker = MagicMock()
        reranker.rerank.side_effect = mock_rerank
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        # Capture fused list
        import dotmd.search.fusion as fusion_module

        original_build = fusion_module.build_candidates
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

        with patch.object(fusion_module, "build_candidates", side_effect=capture_build):
            service.search("test query", top_k=10, mode="hybrid", rerank=True)

        fused_ids = {cid for cid, _ in captured_fused}
        assert "b1" in fused_ids, f"Keyword-only candidate 'b1' missing from final fused: {fused_ids}"
        assert "s1" in fused_ids, f"Semantic candidate 's1' missing from final fused: {fused_ids}"

    def test_empty_reranker_output_falls_back_to_fused(self, tmp_path: Path) -> None:
        """Empty reranker output must not erase otherwise valid fused results."""
        from dotmd.core.models import Chunk

        service = _make_service(tmp_path)

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = [("b1", 5.0)]
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        reranker = MagicMock()
        reranker.rerank.return_value = []
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        chunks = {
            cid: Chunk(
                chunk_id=cid,
                file_paths=[Path(f"/test/{cid}.md")],
                heading_hierarchy=[],
                text=f"Some text for {cid}",
                chunk_index=i,
            )
            for i, cid in enumerate(["s1", "b1"])
        }
        service._pipeline.metadata_store.get_chunks = MagicMock(
            side_effect=lambda ids: [chunks[cid] for cid in ids if cid in chunks]
        )
        _seed_chunk_provenance(service, ["s1", "b1"])
        service._pipeline.log_search = MagicMock()

        results = service.search("test query", top_k=10, mode="hybrid", rerank=True)

        assert results
        service._pipeline.log_search.assert_called_once()
        assert service._pipeline.log_search.call_args.kwargs["reranked"] is False


class TestRerankerFactorySearchWiring:
    """Normal search resolves rerankers through the service factory."""

    def test_runtime_reranker_name_calls_factory(self, tmp_path: Path) -> None:
        """Explicit reranker_name is passed to the cached factory."""
        from dotmd.core.models import Chunk

        service = _make_service(tmp_path)
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = []
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        reranker = MagicMock()
        reranker.rerank.return_value = [("s1", 1.0)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        chunk = Chunk(
            chunk_id="s1",
            file_paths=[Path("/test/s1.md")],
            heading_hierarchy=[],
            text="Some text for s1",
            chunk_index=0,
        )
        service._pipeline.metadata_store.get_chunks = MagicMock(return_value=[chunk])
        _seed_chunk_provenance(service, ["s1"])
        service._pipeline.log_search = MagicMock()

        results = service.search(
            "test query",
            top_k=10,
            mode="hybrid",
            rerank=True,
            reranker_name="msmarco-minilm",
        )

        assert [result.chunk_id for result in results.candidates] == ["s1"]
        service._reranker_factory.get.assert_called_once_with("msmarco-minilm")

    def test_default_reranker_name_calls_factory_with_none(self, tmp_path: Path) -> None:
        """Default search asks the factory for its configured default."""
        from dotmd.core.models import Chunk

        service = _make_service(tmp_path)
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = []
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        reranker = MagicMock()
        reranker.rerank.return_value = [("s1", 1.0)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        chunk = Chunk(
            chunk_id="s1",
            file_paths=[Path("/test/s1.md")],
            heading_hierarchy=[],
            text="Some text for s1",
            chunk_index=0,
        )
        service._pipeline.metadata_store.get_chunks = MagicMock(return_value=[chunk])
        _seed_chunk_provenance(service, ["s1"])
        service._pipeline.log_search = MagicMock()

        service.search("test query", top_k=10, mode="hybrid", rerank=True)

        service._reranker_factory.get.assert_called_once_with(None)

    def test_rerank_false_skips_factory_and_uses_graph_enriched_pool(self, tmp_path: Path) -> None:
        """Skipping rerank still returns the post-graph-enrichment fused order."""
        from dotmd.core.models import Chunk

        service = _make_service(tmp_path)
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = [("gx1", 0.6)]
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")
        service._reranker_factory = MagicMock()

        chunks = {
            cid: Chunk(
                chunk_id=cid,
                file_paths=[Path(f"/test/{cid}.md")],
                heading_hierarchy=[],
                text=f"Some text for {cid}",
                chunk_index=i,
            )
            for i, cid in enumerate(["s1", "gx1"])
        }
        service._pipeline.metadata_store.get_chunks = MagicMock(
            side_effect=lambda ids: [chunks[cid] for cid in ids if cid in chunks]
        )
        _seed_chunk_provenance(service, ["s1", "gx1"])
        service._pipeline.log_search = MagicMock()

        results = service.search(
            "test query",
            top_k=10,
            mode="hybrid",
            rerank=False,
            reranker_name="msmarco-minilm",
        )

        assert [result.chunk_id for result in results.candidates] == ["s1", "gx1"]
        service._reranker_factory.get.assert_not_called()


class TestSearchResultContracts:
    """Search result construction and logging contracts remain stable."""

    def test_graph_appended_merge_back_keeps_enrichment_score(self, tmp_path: Path) -> None:
        """Fusion-only merge-back keeps graph-enriched candidate scores unchanged."""
        service = _make_service(tmp_path)
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = [("gx1", 0.6)]
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        reranker = MagicMock()
        reranker.rerank.return_value = [("s1", 1.0)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker
        service._pipeline.log_search = MagicMock()
        _seed_chunk_provenance(service, ["s1", "gx1"])

        import dotmd.api.service as svc_module

        captured_fused: list[tuple[str, float]] = []

        def capture_build(fused, **kwargs):
            captured_fused.extend(fused)
            return []

        with patch.object(svc_module, "build_search_results", side_effect=capture_build):
            service.search("test query", top_k=10, mode="hybrid", rerank=True)

        fused_scores = dict(captured_fused)
        expected_graph_score = (1.0 / (service._settings.fusion_k + 1)) * 0.5
        assert fused_scores["gx1"] == pytest.approx(expected_graph_score)

    def test_scored_reranker_output_logs_reranked_true(self, tmp_path: Path) -> None:
        """Search logging records reranked=True only when scores were applied."""
        from dotmd.core.models import Chunk

        service = _make_service(tmp_path)
        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = [("s1", 0.9)]
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = []
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        reranker = MagicMock()
        reranker.rerank.return_value = [("s1", 1.0)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        chunk = Chunk(
            chunk_id="s1",
            file_paths=[Path("/test/s1.md")],
            heading_hierarchy=[],
            text="Some text for s1",
            chunk_index=0,
        )
        service._pipeline.metadata_store.get_chunks = MagicMock(return_value=[chunk])
        _seed_chunk_provenance(service, ["s1"])
        service._pipeline.log_search = MagicMock()

        service.search("test query", top_k=10, mode="hybrid", rerank=True)

        service._pipeline.log_search.assert_called_once()
        assert service._pipeline.log_search.call_args.kwargs["reranked"] is True


class TestDiagnosticLogging:
    """Diagnostic logging reports keyword-only survival count."""

    def test_keyword_survival_logged_at_debug(self, tmp_path: Path) -> None:
        """Log message matching 'keyword-only' present in captured logs at DEBUG level."""
        service = _make_service(tmp_path)

        semantic_hits = [("s1", 0.9)]
        keyword_hits = [("b1", 5.0)]

        service._semantic_engine = MagicMock()
        service._semantic_engine.search.return_value = semantic_hits
        service._keyword_engine = MagicMock()
        service._keyword_engine.search.return_value = keyword_hits
        service._graph_engine = MagicMock()
        service._graph_engine.search.return_value = []
        service._graph_direct_engine = MagicMock()
        service._graph_direct_engine.search.return_value = []
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="test query")

        def mock_rerank(query, chunk_ids, store, top_k=5):
            return [(cid, 1.0 - i * 0.1) for i, cid in enumerate(chunk_ids)]

        reranker = MagicMock()
        reranker.rerank.side_effect = mock_rerank
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        mock_chunk = MagicMock()
        mock_chunk.heading_hierarchy = []
        mock_chunk.text = "Some text"
        mock_chunk.file_path = Path("/test/file.md")
        service._pipeline.metadata_store.get_chunks = MagicMock(
            return_value=[mock_chunk]
        )
        _seed_chunk_provenance(service, ["s1", "b1"])

        captured: list[str] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                captured.append(record.getMessage())

        handler = _Capture(level=logging.DEBUG)
        svc_logger = logging.getLogger("dotmd.api.service")
        svc_logger.addHandler(handler)
        svc_logger.setLevel(logging.DEBUG)
        try:
            service.search("test query", top_k=10, mode="hybrid", rerank=True)
        finally:
            svc_logger.removeHandler(handler)

        assert any("keyword-only" in m for m in captured), (
            f"Expected log message containing 'keyword-only', got: {captured}"
        )
