"""RED test skeletons for DotMDService.search returning file_paths (P5 — Task 1).

These tests verify the service facade returns SearchResult with file_paths list.
They FAIL until P5 (wave 5) updates the service.
Imports are deferred so --collect-only works before P5 ships.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings
    settings = Settings(index_dir=tmp_path)
    return DotMDService(settings)


def test_format_elapsed_ms_for_human_diagnostics() -> None:
    from dotmd.api.service import format_elapsed_ms

    assert format_elapsed_ms(123.4) == "123ms"
    assert format_elapsed_ms(12_592.2) == "13s"
    assert format_elapsed_ms(197_214.1) == "3m17s"
    assert format_elapsed_ms(3_723_000.0) == "1h02m03s"


class TestSearchReturnsFilePaths:
    """DotMDService.search returns SearchResult instances with file_paths list."""

    def test_search_returns_file_paths_list(self, tmp_path: Path) -> None:
        """search() forwards contract args and returns results with file_paths."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchMode, SearchResult
        stub_result = SearchResult(
            chunk_id="a" * 64,
            file_paths=[Path(tmp_path / "test.md")],
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
            assert hasattr(r, "file_paths"), (
                "SearchResult must have file_paths attribute (P5 Decision #2)"
            )
            assert isinstance(r.file_paths, list), (
                f"file_paths must be list, got {type(r.file_paths)!r}"
            )


class TestSearchRespectsTopK:
    """DotMDService.search respects the top_k parameter."""

    def test_search_respects_top_k(self, tmp_path: Path) -> None:
        """search(top_k=3) forwards top_k and rerank pool_size to execution."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchResult
        stub_results = [
            SearchResult(
                chunk_id=str(i) * 64,
                file_paths=[Path(tmp_path / f"test_{i}.md")],
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
        assert by_name["msmarco-minilm"]["returned_count"] == 1
        assert len(by_name["msmarco-minilm"]["scores"]) == 1
        assert comparison["rerankers"][-1]["name"] == "mmarco-minilm"

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
