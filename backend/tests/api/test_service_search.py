"""Tests for DotMDService search/read behavior."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings
    settings = Settings(index_dir=tmp_path, embedding_url="http://localhost:8088")
    return DotMDService(settings)


def test_format_elapsed_ms_for_human_diagnostics() -> None:
    from dotmd.api.service import format_elapsed_ms

    assert format_elapsed_ms(123.4) == "123ms"
    assert format_elapsed_ms(12_592.2) == "13s"
    assert format_elapsed_ms(197_214.1) == "3m17s"
    assert format_elapsed_ms(3_723_000.0) == "1h02m03s"


class TestSearchReturnsFilePaths:
    """DotMDService.search returns SearchResult instances with public refs."""

    def test_search_returns_file_paths_list(self, tmp_path: Path) -> None:
        """search() forwards contract args and returns results with ref."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchMode, SearchResult
        stub_result = SearchResult(
            chunk_id="a" * 64,
            ref="filesystem:/mnt/test.md",
            heading_path="# Test",
            snippet="test snippet",
            fused_score=0.9,
        )

        with patch.object(service, "_execute_search", return_value=[stub_result]) as execute_search:
            results = service.search("test query", top_k=5, rerank=False, expand=False)

        execute_search.assert_called_once_with(
            search_query="test query",
            original_query="test query",
            top_k=5,
            mode=SearchMode.HYBRID,
            rerank=False,
            reranker_name=None,
            pool_size=5,
        )
        assert results == [stub_result]
        for r in results:
            assert r.ref == "filesystem:/mnt/test.md"


class TestSearchRespectsTopK:
    """DotMDService.search respects the top_k parameter."""

    def test_search_respects_top_k(self, tmp_path: Path) -> None:
        """search(top_k=3) forwards top_k and rerank pool_size to execution."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchResult
        stub_results = [
            SearchResult(
                chunk_id=str(i) * 64,
                ref=f"filesystem:/mnt/test_{i}.md",
                heading_path=f"# Test {i}",
                snippet=f"snippet {i}",
                fused_score=float(i) / 10,
            )
            for i in range(5)
        ]

        with patch.object(service, "_execute_search", return_value=stub_results) as execute_search:
            results = service.search("test query", top_k=3)

        assert results == stub_results
        kwargs = execute_search.call_args.kwargs
        assert kwargs["top_k"] == 3
        assert kwargs["pool_size"] == service._settings.rerank_pool_size
        assert kwargs["rerank"] is True


def _source_document(file_path: Path, *, namespace: str = "filesystem"):
    from dotmd.core.models import SourceDocument

    document_ref = str(file_path.resolve()) if namespace == "filesystem" else "doc:1"
    return SourceDocument(
        namespace=namespace,
        document_ref=document_ref,
        ref=f"{namespace}:{document_ref}",
        source_uri=str(file_path),
        file_path=file_path if namespace == "filesystem" else None,
        media_type="text/markdown",
        parser_name="markdown",
        document_type="document",
        title="Service Note",
        updated_at=datetime(2026, 5, 6),
        content_fingerprint="content",
        metadata_fingerprint="metadata",
        metadata_json={},
    )


def _search_chunk(chunk_id: str, text: str = "target snippet"):
    from dotmd.core.models import Chunk

    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path(f"/mnt/{chunk_id}.md")],
        heading_hierarchy=["H"],
        level=1,
        text=text,
        chunk_index=0,
    )


def _chunk_provenance(chunk_id: str):
    from dotmd.core.models import ChunkProvenance

    return ChunkProvenance(
        namespace="filesystem",
        document_ref=f"/mnt/{chunk_id}.md",
        ref=f"filesystem:/mnt/{chunk_id}.md",
        source_unit_refs=[],
        chunk_strategy="contextual_512_50",
        parser_name="markdown",
    )


class _SearchMetadataStore:
    _table = "chunks_contextual_512_50"

    def __init__(self, chunks: list[str], active_chunks: set[str]) -> None:
        self._chunks = {chunk_id: _search_chunk(chunk_id) for chunk_id in chunks}
        self._active_chunks = active_chunks

    def count_missing_source_provenance(self, strategy: str) -> int:
        return 0

    def get_chunks(self, chunk_ids: list[str]):
        return [self._chunks[chunk_id] for chunk_id in chunk_ids if chunk_id in self._chunks]

    def get_chunk_provenance_for_chunk_ids(self, strategy: str, chunk_ids: list[str]):
        return {
            chunk_id: _chunk_provenance(chunk_id)
            for chunk_id in chunk_ids
            if chunk_id in self._chunks
        }

    def get_active_chunk_provenance_for_chunk_ids(
        self,
        strategy: str,
        chunk_ids: list[str],
    ):
        return {
            chunk_id: _chunk_provenance(chunk_id)
            for chunk_id in chunk_ids
            if chunk_id in self._active_chunks
        }


class TestActiveSearchFiltering:
    """Public search hides inactive retained candidates before rerank/hydration."""

    def test_execute_search_skips_inactive_fused_candidates_before_hydration(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            ["inactive-1", "inactive-2", "active-1", "active-2"],
            {"active-1", "active-2"},
        )
        service._pipeline._metadata_store = metadata
        service._pipeline.log_search = MagicMock()
        service._collect_candidate_pool = MagicMock(
            return_value={
                "fused": [
                    ("inactive-1", 0.9),
                    ("inactive-2", 0.8),
                    ("active-1", 0.7),
                    ("active-2", 0.6),
                ],
                "engine_results": {
                    "semantic": [
                        ("inactive-1", 0.9),
                        ("inactive-2", 0.8),
                        ("active-1", 0.7),
                        ("active-2", 0.6),
                    ],
                },
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 4,
            }
        )

        results = service._execute_search(
            search_query="target",
            original_query="target",
            top_k=2,
            mode="hybrid",
            rerank=False,
            reranker_name=None,
            pool_size=4,
        )

        assert [result.ref for result in results] == [
            "filesystem:/mnt/active-1.md",
            "filesystem:/mnt/active-2.md",
        ]
        assert all("inactive" not in result.ref for result in results)

    def test_inactive_skewed_pool_uses_named_active_filter_policy(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            [f"inactive-{i}" for i in range(40)] + ["active-1"],
            {"active-1"},
        )
        service._pipeline._metadata_store = metadata
        service._pipeline.log_search = MagicMock()
        service._collect_candidate_pool = MagicMock(
            return_value={
                "fused": [(f"inactive-{i}", 1.0 - i / 100) for i in range(40)]
                + [("active-1", 0.1)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 52,
            }
        )

        results = service.search("target", top_k=2, rerank=False, expand=False)

        service._collect_candidate_pool.assert_called_once()
        assert service._collect_candidate_pool.call_args.kwargs["pool_size"] >= 52
        assert [result.ref for result in results] == ["filesystem:/mnt/active-1.md"]
        assert "active filter underfilled" in caplog.text

    def test_reranker_receives_only_active_chunk_ids(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            ["inactive-1", "active-1", "active-2"],
            {"active-1", "active-2"},
        )
        service._pipeline._metadata_store = metadata
        service._pipeline.log_search = MagicMock()
        service._collect_candidate_pool = MagicMock(
            return_value={
                "fused": [
                    ("inactive-1", 0.9),
                    ("active-1", 0.8),
                    ("active-2", 0.7),
                ],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 3,
            }
        )
        reranker = MagicMock()
        reranker.rerank.return_value = [("active-2", 0.95), ("active-1", 0.8)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = reranker

        service._execute_search(
            search_query="target",
            original_query="target",
            top_k=2,
            mode="hybrid",
            rerank=True,
            reranker_name=None,
            pool_size=3,
        )

        assert reranker.rerank.call_args.args[1] == ["active-1", "active-2"]

    def test_graph_direct_candidates_use_active_filter(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            ["graph-inactive", "graph-active"],
            {"graph-active"},
        )
        service._pipeline._metadata_store = metadata
        service._pipeline.log_search = MagicMock()
        service._collect_candidate_pool = MagicMock(
            return_value={
                "fused": [("graph-inactive", 0.9), ("graph-active", 0.8)],
                "engine_results": {
                    "graph_direct": [("graph-inactive", 0.9), ("graph-active", 0.8)]
                },
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [("graph-inactive", 0.9), ("graph-active", 0.8)],
                "pool_size": 2,
            }
        )

        results = service._execute_search(
            search_query="target",
            original_query="target",
            top_k=1,
            mode="hybrid",
            rerank=False,
            reranker_name=None,
            pool_size=2,
        )

        assert [result.ref for result in results] == ["filesystem:/mnt/graph-active.md"]
        assert results[0].graph_direct_score == 0.8


class TestReadRefContract:
    """DotMDService.read resolves source refs and keeps paths internal."""

    def test_read_ref_returns_ref_not_file_path_and_uses_active_strategy(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "note.md"
        note_path.write_text("---\ntitle: Service Note\n---\nBody", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.get_chunk_count_for_file.return_value = 2
        metadata.get_chunks_for_file_range.return_value = [
            {"index": 0, "heading_hierarchy": ["H"], "text": "Body"},
        ]
        service._pipeline._metadata_store = metadata

        payload = service.read(document.ref, 0, 1)

        assert payload["ref"] == document.ref
        assert "file_path" not in payload
        assert payload["frontmatter"]["title"] == "Service Note"
        assert payload["total_chunks"] == 2
        assert payload["chunks"] == [
            {"index": 0, "heading_hierarchy": ["H"], "text": "Body"}
        ]
        metadata.get_chunk_count_for_file.assert_called_once_with(
            service._settings.chunk_strategy,
            str(note_path.resolve()),
        )
        metadata.get_chunks_for_file_range.assert_called_once_with(
            service._settings.chunk_strategy,
            str(note_path.resolve()),
            0,
            1,
        )

    def test_read_ref_rejects_unknown_and_malformed_refs(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = None
        service._pipeline._metadata_store = metadata

        for ref in ["not-a-ref", "filesystem:/missing.md"]:
            try:
                service.read(ref)
            except ValueError as exc:
                assert "Unknown source ref" in str(exc)
            else:
                raise AssertionError("read() should reject unknown refs")

    def test_read_ref_falls_back_for_existing_filesystem_provenance_without_source_document(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "legacy.md"
        note_path.write_text("---\ntitle: Legacy Note\n---\nBody", encoding="utf-8")
        ref = f"filesystem:{note_path.resolve()}"
        metadata = MagicMock()
        metadata.get_source_document.return_value = None
        metadata.get_chunk_count_for_file.return_value = 1
        metadata.get_chunks_for_file_range.return_value = [
            {"index": 0, "heading_hierarchy": [], "text": "Body"},
        ]
        service._pipeline._metadata_store = metadata

        payload = service.read(ref, 0, 1)

        assert payload["ref"] == ref
        assert payload["frontmatter"]["title"] == "Legacy Note"
        assert payload["total_chunks"] == 1
        metadata.get_chunk_count_for_file.assert_any_call(
            service._settings.chunk_strategy,
            str(note_path.resolve()),
        )

    def test_read_ref_rejects_existing_filesystem_path_not_in_active_index(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "not-indexed.md"
        note_path.write_text("---\ntitle: Secret\n---\nBody", encoding="utf-8")
        metadata = MagicMock()
        metadata.get_source_document.return_value = None
        metadata.get_chunk_count_for_file.return_value = 0
        service._pipeline._metadata_store = metadata

        try:
            service.drill(f"filesystem:{note_path.resolve()}")
        except ValueError as exc:
            assert "Unknown source ref" in str(exc)
        else:
            raise AssertionError("drill() should reject existing non-indexed files")

        metadata.get_chunk_count_for_file.assert_called_once_with(
            service._settings.chunk_strategy,
            str(note_path.resolve()),
        )

    def test_read_ref_rejects_unsupported_namespace(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        document = _source_document(tmp_path / "telegram.md", namespace="telegram")
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        service._pipeline._metadata_store = metadata

        try:
            service.read(document.ref)
        except ValueError as exc:
            assert "Unsupported source namespace" in str(exc)
        else:
            raise AssertionError("read() should reject unsupported namespaces")

    def test_read_ref_rejects_source_with_no_active_strategy_chunks(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "note.md"
        note_path.write_text("Body", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.get_chunk_count_for_file.return_value = 0
        service._pipeline._metadata_store = metadata

        try:
            service.read(document.ref)
        except ValueError as exc:
            assert "No chunks for source ref in active strategy" in str(exc)
        else:
            raise AssertionError("read() should reject inactive-strategy refs")

    def test_read_ref_frontmatter_parse_failure_is_non_fatal(
        self,
        tmp_path: Path,
        caplog,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "note.md"
        note_path.write_text("Body", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.get_chunk_count_for_file.return_value = 1
        metadata.get_chunks_for_file_range.return_value = []
        service._pipeline._metadata_store = metadata

        with patch("dotmd.api.service.parse_frontmatter", side_effect=ValueError("bad")):
            payload = service.read(document.ref)

        assert payload["frontmatter"] == {}
        assert "frontmatter parse failed" in caplog.text


class TestDrillRefContract:
    """DotMDService.drill returns metadata for a source ref."""

    def test_drill_ref_returns_metadata_payload(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "note.md"
        note_path.write_text("---\ntitle: Service Note\n---\nBody", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.get_chunk_count_for_file.return_value = 3
        service._pipeline._metadata_store = metadata

        payload = service.drill(document.ref)

        assert payload["ref"] == document.ref
        assert payload["title"] == "Service Note"
        assert payload["source_uri"] == str(note_path)
        assert payload["document_type"] == "document"
        assert payload["parser_name"] == "markdown"
        assert payload["frontmatter"]["title"] == "Service Note"
        assert payload["total_chunks"] == 3


class TestCompareRerankers:
    """DotMDService.compare_rerankers uses one shared candidate pool."""

    def test_compare_collects_shared_candidate_pool_once(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2), ("c3", 0.1)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 3,
            }
        )
        first = MagicMock(name="first", model_name="FirstModel")
        first.name = "mmarco-minilm"
        first.model_name = "MMARCO"
        first.rerank.return_value = [("c2", 0.9), ("c1", 0.8)]
        second = MagicMock(name="second", model_name="SecondModel")
        second.name = "msmarco-minilm"
        second.model_name = "MiniLM"
        second.rerank.return_value = [("c1", 0.7), ("c3", 0.6)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [first, second]

        comparison = service.compare_rerankers("q", ["mmarco-minilm", "msmarco-minilm"])

        service._collect_candidate_pool.assert_called_once()
        assert first.rerank.call_args.args[1] == ["c1", "c2", "c3"]
        assert second.rerank.call_args.args[1] == ["c1", "c2", "c3"]
        assert comparison["shared_pool_size"] == 3
        assert all(
            isinstance(run["elapsed_ms"], float) and run["elapsed_ms"] >= 0.0
            for run in comparison["rerankers"]
        )
        assert all(
            isinstance(run["load_ms"], float) and run["load_ms"] >= 0.0
            for run in comparison["rerankers"]
        )
        assert all(
            isinstance(run["rerank_ms"], float) and run["rerank_ms"] >= 0.0
            for run in comparison["rerankers"]
        )
        assert all(run["elapsed"] and run["load"] and run["rerank"] for run in comparison["rerankers"])
        for run in comparison["rerankers"]:
            assert run["returned_count"] == len(run["top_chunk_ids"]) == len(run["scores"])

    def test_compare_isolates_per_reranker_errors(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 2,
            }
        )
        failing = MagicMock()
        failing.name = "mmarco-minilm"
        failing.model_name = "MMARCO"
        failing.rerank.side_effect = RuntimeError("boom")
        successful = MagicMock()
        successful.name = "msmarco-minilm"
        successful.model_name = "MiniLM"
        successful.rerank.return_value = [("c2", 0.8)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [failing, successful]

        comparison = service.compare_rerankers("q", ["mmarco-minilm", "msmarco-minilm"])

        assert (
            failing.rerank.call_args.kwargs["raise_on_provider_error"] is True
        )
        by_name = {run["name"]: run for run in comparison["rerankers"]}
        assert by_name["mmarco-minilm"]["error"] == "boom"
        assert by_name["mmarco-minilm"]["returned_count"] == 0
        assert by_name["mmarco-minilm"]["top_chunk_ids"] == []
        assert by_name["mmarco-minilm"]["scores"] == []
        assert by_name["msmarco-minilm"]["error"] is None
        assert by_name["msmarco-minilm"]["top_chunk_ids"] == ["c2"]

    def test_compare_sorts_successful_rerankers_by_elapsed_time(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 2,
            }
        )
        slow = MagicMock()
        slow.name = "mmarco-minilm"
        slow.model_name = "MMARCO"
        slow.rerank.return_value = [("c1", 0.9)]
        fast = MagicMock()
        fast.name = "msmarco-minilm"
        fast.model_name = "MiniLM"
        fast.rerank.return_value = [("c2", 0.8)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [slow, fast]

        with patch(
            "dotmd.api.service.time.perf_counter",
            side_effect=[0.0, 0.1, 2.1, 10.0, 10.1, 10.6],
        ):
            comparison = service.compare_rerankers(
                "q",
                ["mmarco-minilm", "msmarco-minilm"],
            )

        assert [run["name"] for run in comparison["rerankers"]] == [
            "msmarco-minilm",
            "mmarco-minilm",
        ]
        assert comparison["overlap_reference"] == "msmarco-minilm"

    def test_compare_default_names_include_configured_models(
        self, tmp_path: Path
    ) -> None:
        service = _get_service(tmp_path)
        service._settings.reranker_compare_names = "mmarco-minilm,msmarco-minilm"
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 2,
            }
        )
        mmarco = MagicMock()
        mmarco.name = "mmarco-minilm"
        mmarco.model_name = "MMARCO"
        mmarco.rerank.return_value = [("c2", 0.9), ("c1", 0.8)]
        minilm = MagicMock()
        minilm.name = "msmarco-minilm"
        minilm.model_name = "MiniLM"
        minilm.rerank.return_value = [("c1", 0.7)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [mmarco, minilm]

        comparison = service.compare_rerankers("q")

        by_name = {run["name"]: run for run in comparison["rerankers"]}
        assert set(by_name) == {"mmarco-minilm", "msmarco-minilm"}
        assert by_name["mmarco-minilm"]["top_chunk_ids"] == ["c2", "c1"]
        assert by_name["mmarco-minilm"]["scores"] == [0.9, 0.8]

    def test_compare_three_rerankers_reuses_retrieval_engines_once(
        self, tmp_path: Path
    ) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._semantic_engine.search = MagicMock(return_value=[("c1", 0.9)])
        service._keyword_engine.search = MagicMock(return_value=[("c2", 0.8)])
        service._graph_direct_engine.search = MagicMock(return_value=[("c3", 0.7)])
        service._graph_engine.search = MagicMock(return_value=[])

        rerankers = []
        for name, chunk_id in [
            ("mmarco-minilm", "c1"),
            ("msmarco-minilm", "c2"),
            ("mxbai-xsmall-v1", "c3"),
        ]:
            reranker = MagicMock()
            reranker.name = name
            reranker.model_name = name
            reranker.rerank.return_value = [(chunk_id, 0.9)]
            rerankers.append(reranker)
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = rerankers

        comparison = service.compare_rerankers(
            "q",
            ["mmarco-minilm", "msmarco-minilm", "mxbai-xsmall-v1"],
            top_k=2,
        )

        service._semantic_engine.search.assert_called_once()
        service._keyword_engine.search.assert_called_once()
        service._graph_direct_engine.search.assert_called_once()
        service._graph_engine.search.assert_called_once()
        assert [run["returned_count"] for run in comparison["rerankers"]] == [1, 1, 1]

    def test_compare_overlap_uses_first_successful_reranker(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2), ("c3", 0.1)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 3,
            }
        )
        failing = MagicMock()
        failing.name = "mmarco-minilm"
        failing.model_name = "MMARCO"
        failing.rerank.side_effect = RuntimeError("boom")
        reference = MagicMock()
        reference.name = "msmarco-minilm"
        reference.model_name = "MiniLM"
        reference.rerank.return_value = [("c1", 0.9), ("c2", 0.8)]
        candidate = MagicMock()
        candidate.name = "mxbai-xsmall-v1"
        candidate.model_name = "MXBAI"
        candidate.rerank.return_value = [("c2", 0.7), ("c3", 0.6)]
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [failing, reference, candidate]

        with patch(
            "dotmd.api.service.time.perf_counter",
            side_effect=[0.0, 0.1, 1.0, 1.0, 1.1, 1.6, 1.6, 1.7, 3.2],
        ):
            comparison = service.compare_rerankers(
                "q",
                ["mmarco-minilm", "msmarco-minilm", "mxbai-xsmall-v1"],
            )

        assert comparison["overlap_reference"] == "msmarco-minilm"
        assert comparison["overlap"] == {"msmarco-minilm": 2, "mxbai-xsmall-v1": 1}

    def test_compare_all_failures_returns_errors_and_empty_overlap(
        self, tmp_path: Path
    ) -> None:
        service = _get_service(tmp_path)
        service._query_expander = MagicMock()
        service._query_expander.expand.return_value = MagicMock(expanded_text="expanded q")
        service._collect_candidate_pool = MagicMock(
            return_value={
                "search_query": "expanded q",
                "original_query": "q",
                "fused": [("c1", 0.3), ("c2", 0.2)],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
                "graph_direct_hits": [],
                "pool_size": 2,
            }
        )
        first = MagicMock()
        first.name = "mmarco-minilm"
        first.model_name = "MMARCO"
        first.rerank.side_effect = RuntimeError("first failed")
        second = MagicMock()
        second.name = "msmarco-minilm"
        second.model_name = "MiniLM"
        second.rerank.side_effect = RuntimeError("second failed")
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.side_effect = [first, second]

        comparison = service.compare_rerankers("q", ["mmarco-minilm", "msmarco-minilm"])

        by_name = {run["name"]: run for run in comparison["rerankers"]}
        assert by_name["mmarco-minilm"]["error"] == "first failed"
        assert by_name["msmarco-minilm"]["error"] == "second failed"
        assert comparison["overlap_reference"] is None
        assert comparison["overlap"] == {}


class TestServiceWarmup:
    """Service warmup preserves search availability when reranking is unavailable."""

    def test_warmup_logs_and_continues_when_reranker_fails(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        service._semantic_engine.warmup = MagicMock()
        service._keyword_engine.load_index = MagicMock()
        service._graph_direct_engine.load_catalog = MagicMock()
        service._check_embedding_model = MagicMock()
        failing_reranker = MagicMock()
        failing_reranker.warmup.side_effect = RuntimeError("model unavailable")
        service._reranker_factory = MagicMock()
        service._reranker_factory.get.return_value = failing_reranker

        service.warmup()

        service._semantic_engine.warmup.assert_called_once()
        failing_reranker.warmup.assert_called_once()
        service._keyword_engine.load_index.assert_called_once()
        service._graph_direct_engine.load_catalog.assert_called_once()
        service._check_embedding_model.assert_called_once()


class TestSearchApiRerankerSurfaces:
    """FastAPI exposes reranker selection and comparison diagnostics."""

    def test_search_endpoint_accepts_reranker_name(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.search.return_value = []
        server._service = service
        client = TestClient(server.app)

        response = client.get("/search?q=test&reranker=msmarco-minilm")

        assert response.status_code == 200
        service.search.assert_called_once()
        assert service.search.call_args.kwargs["reranker_name"] == "msmarco-minilm"

    def test_search_endpoint_unknown_reranker_returns_400(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.search.side_effect = ValueError(
            "Unknown reranker 'missing'; available: mmarco-minilm"
        )
        server._service = service
        client = TestClient(server.app)

        response = client.get("/search?q=test&reranker=missing")

        assert response.status_code == 400
        assert "Unknown reranker" in response.json()["detail"]

    def test_compare_endpoint_returns_typed_payload(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.compare_rerankers.return_value = {
            "query": "test",
            "search_query": "expanded test",
            "shared_pool_size": 2,
            "rerankers": [
                {
                    "name": "mmarco-minilm",
                    "model_name": "MMARCO",
                    "elapsed_ms": 12.3,
                    "elapsed": "12s",
                    "load_ms": 2.3,
                    "load": "2s",
                    "rerank_ms": 10.0,
                    "rerank": "10s",
                    "returned_count": 2,
                    "top_chunk_ids": ["c1", "c2"],
                    "scores": [0.9, 0.8],
                    "error": None,
                },
                {
                    "name": "msmarco-minilm",
                    "model_name": "MiniLM",
                    "elapsed_ms": 4.5,
                    "elapsed": "5s",
                    "load_ms": 1.0,
                    "load": "1s",
                    "rerank_ms": 3.5,
                    "rerank": "4s",
                    "returned_count": 1,
                    "top_chunk_ids": ["c2"],
                    "scores": [0.7],
                    "error": None,
                },
            ],
            "overlap_reference": "mmarco-minilm",
            "overlap": {"mmarco-minilm": 2, "msmarco-minilm": 1},
        }
        server._service = service
        client = TestClient(server.app)

        response = client.get(
            "/rerank/compare?q=test&rerankers=mmarco-minilm,msmarco-minilm"
        )

        assert response.status_code == 200
        assert response.json()["shared_pool_size"] == 2
        assert response.json()["rerankers"][0]["elapsed_ms"] == 12.3
        assert response.json()["rerankers"][0]["elapsed"] == "12s"
        assert response.json()["rerankers"][0]["load_ms"] == 2.3
        assert response.json()["rerankers"][0]["rerank_ms"] == 10.0
        service.compare_rerankers.assert_called_once_with(
            query="test",
            reranker_names=["mmarco-minilm", "msmarco-minilm"],
            top_k=10,
            mode="hybrid",
            expand=True,
        )

    def test_compare_endpoint_unknown_reranker_returns_400(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.compare_rerankers.side_effect = ValueError(
            "Unknown reranker 'missing'; available: mmarco-minilm"
        )
        server._service = service
        client = TestClient(server.app)

        response = client.get("/rerank/compare?q=test&rerankers=missing")

        assert response.status_code == 400
        assert "Unknown reranker" in response.json()["detail"]

    def test_compare_endpoint_surfaces_schema_drift(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.compare_rerankers.return_value = {
            "query": "test",
            "search_query": "test",
            "shared_pool_size": 0,
            "rerankers": [],
            "overlap_reference": None,
        }
        server._service = service
        client = TestClient(server.app, raise_server_exceptions=False)

        response = client.get("/rerank/compare?q=test")

        assert response.status_code == 500


class TestSourceProvenanceSafetyGate:
    """Search enforces active source provenance before result hydration."""

    def test_execute_search_backfills_missing_active_strategy_provenance(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.count_missing_source_provenance.side_effect = [2, 0]
        metadata.backfill_missing_source_provenance_from_file_paths.return_value = 2
        service._pipeline._metadata_store = metadata
        service._collect_candidate_pool = MagicMock(
            return_value={
                "fused": [],
                "engine_results": {},
                "semantic_hits": [],
                "keyword_hits": [],
            }
        )

        results = service._execute_search(
            search_query="expanded",
            original_query="query",
            top_k=5,
            mode="hybrid",
            rerank=False,
            reranker_name=None,
            pool_size=5,
        )

        assert results == []
        metadata.backfill_missing_source_provenance_from_file_paths.assert_called_once_with(
            service._settings.chunk_strategy,
            dry_run=False,
        )

    def test_execute_search_blocks_when_active_strategy_backfill_is_incomplete(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.count_missing_source_provenance.side_effect = [2, 1]
        metadata.backfill_missing_source_provenance_from_file_paths.return_value = 1
        service._pipeline._metadata_store = metadata

        try:
            service._execute_search(
                search_query="expanded",
                original_query="query",
                top_k=5,
                mode="hybrid",
                rerank=False,
                reranker_name=None,
                pool_size=5,
            )
        except ValueError as exc:
            assert "source provenance backfill incomplete" in str(exc)
        else:
            raise AssertionError("search should block incomplete provenance backfill")
