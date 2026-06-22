"""Tests for DotMDService search/read behavior."""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from dotmd.storage.metadata import SQLiteMetadataStore
from tests.conftest import make_surreal_runtime_settings, make_surreal_service


def _get_service(tmp_path: Path):  # type: ignore[no-untyped-def]
    # Explicitly disable Telegram socket so env vars from production deployment
    # (DOTMD_TELEGRAM_DAEMON_SOCKET) do not inject a live lifecycle bundle into
    # unit tests that only mock local search behavior.
    return make_surreal_service(
        tmp_path,
        data_dir=tmp_path,
        indexing_paths=[str(tmp_path)],
        embedding_url="http://localhost:8088",
        telegram_daemon_socket=None,
    )


class _LifecycleFactoryFixture:
    def __init__(self, provider: object | None) -> None:
        from dotmd.ingestion.source_registry import default_source_registry

        self.provider = provider
        self.calls: list[str] = []
        self._registry = default_source_registry()

    def build_if_configured(self, namespace: str) -> object | None:
        from dotmd.ingestion.source_lifecycle import (
            SourceAccess,
            SourceRuntimeBundle,
            TelegramSourceConfig,
        )
        from dotmd.ingestion.source_provider import ApplicationSourceProviderProtocol
        from dotmd.ingestion.source_registry import default_source_registry

        self.calls.append(namespace)
        if namespace != "telegram" or self.provider is None:
            return None
        return SourceRuntimeBundle(
            descriptor=default_source_registry().require(namespace),
            config=TelegramSourceConfig(socket_path=Path("/tmp/telegram.sock")),
            access=SourceAccess(kind="delegated", delegated_to="mcp-telegram"),
            cursor_store=MagicMock(),
            provider=cast(ApplicationSourceProviderProtocol, self.provider),
        )


class _FailingLifecycleFactoryFixture(_LifecycleFactoryFixture):
    def build_if_configured(self, namespace: str) -> object | None:
        self.calls.append(namespace)
        if namespace == "telegram":
            raise RuntimeError("telegram unavailable")
        return None


def test_build_telegram_provider_uses_lifecycle_factory(tmp_path: Path) -> None:
    service = _get_service(tmp_path)
    provider = MagicMock()
    factory = _LifecycleFactoryFixture(provider)
    service._source_runtime_factory = factory  # type: ignore[attr-defined]

    built = service._build_telegram_provider()

    assert built is provider
    assert factory.calls == ["telegram"]


def test_build_federated_bundles_registers_search_capable_bundle(tmp_path: Path) -> None:
    service = _get_service(tmp_path)
    provider = MagicMock()
    factory = _LifecycleFactoryFixture(provider)
    service._source_runtime_factory = factory  # type: ignore[attr-defined]
    service._lifecycle_bundles = {}
    service._lifecycle_init_errors = {}

    service._build_federated_bundles()

    assert factory.calls == ["filesystem", "telegram", "gmail"]
    assert set(service._lifecycle_bundles) == {"telegram"}
    assert service._lifecycle_bundles["telegram"].provider is provider
    assert service._lifecycle_init_errors == {}


def test_build_federated_bundles_records_lifecycle_errors(tmp_path: Path) -> None:
    service = _get_service(tmp_path)
    factory = _FailingLifecycleFactoryFixture(provider=None)
    service._source_runtime_factory = factory  # type: ignore[attr-defined]
    service._lifecycle_bundles = {}
    service._lifecycle_init_errors = {}

    service._build_federated_bundles()

    assert factory.calls == ["filesystem", "telegram", "gmail"]
    assert service._lifecycle_bundles == {}
    assert service._lifecycle_init_errors == {"telegram": "telegram unavailable"}


def test_format_elapsed_ms_for_human_diagnostics() -> None:
    from dotmd.api.service import format_elapsed_ms

    assert format_elapsed_ms(123.4) == "123ms"
    assert format_elapsed_ms(12_592.2) == "13s"
    assert format_elapsed_ms(197_214.1) == "3m17s"
    assert format_elapsed_ms(3_723_000.0) == "1h02m03s"


class TestSearchReturnsFilePaths:
    """DotMDService.search returns SearchResponse with SearchCandidate instances."""

    def test_local_only_search_returns_searchcandidate(self, tmp_path: Path) -> None:
        """search() returns SearchResponse envelope with candidates."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchCandidate, SearchMode, SearchResponse

        stub_result = SearchCandidate(
            ref="filesystem:/mnt/test.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            title="Test",
            snippet="test snippet",
            fused_score=0.9,
            can_read=True,
            can_materialize=False,
        )

        with patch.object(service, "_execute_search", return_value=[stub_result]) as execute_search:
            response = service.search("test query", top_k=5, rerank=False, expand=False)

        execute_search.assert_called_once_with(
            search_query="test query",
            original_query="test query",
            top_k=5,
            mode=SearchMode.HYBRID,
            rerank=False,
            reranker_name=None,
            pool_size=55,
        )
        assert isinstance(response, SearchResponse)
        assert response.candidates == [stub_result]
        assert isinstance(response.candidates[0], SearchCandidate)
        assert response.candidates[0].ref == "filesystem:/mnt/test.md#0"
        assert response.candidates[0].can_read is True


class TestSearchRespectsTopK:
    """DotMDService.search respects the top_k parameter."""

    def test_search_respects_top_k(self, tmp_path: Path) -> None:
        """search(top_k=3) forwards top_k and rerank pool_size to execution."""
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchCandidate

        stub_results = [
            SearchCandidate(
                ref=f"filesystem:/mnt/test_{i}.md#0",
                namespace="filesystem",
                descriptor_key="filesystem-mnt",
                source_kind="markdown",
                retrieval_kind="semantic",
                snippet=f"snippet {i}",
                fused_score=float(i) / 10,
                can_read=True,
            )
            for i in range(5)
        ]

        with patch.object(service, "_execute_search", return_value=stub_results) as execute_search:
            response = service.search("test query", top_k=3)

        # top_k=3 → merge returns at most 3 candidates sorted by fused_score desc.
        # stub_results has scores [0.0, 0.1, 0.2, 0.3, 0.4]; top 3 are [0.4, 0.3, 0.2].
        assert len(response.candidates) == 3
        assert (
            response.candidates
            == sorted(stub_results, key=lambda c: c.fused_score, reverse=True)[:3]
        )
        kwargs = execute_search.call_args.kwargs
        assert kwargs["top_k"] == 3
        assert kwargs["pool_size"] == max(
            service._settings.rerank_pool_size,
            3 * 5,
            3 + 50,
        )
        assert kwargs["rerank"] is True


class TestFederatedSearchOptIn:
    """Federated providers only run when explicitly requested."""

    def test_default_search_does_not_call_federated_provider(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchCandidate
        from tests.search.conftest import make_federated_bundle

        local_candidate = SearchCandidate(
            ref="filesystem:/mnt/local.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="local snippet",
            fused_score=0.9,
            can_read=True,
        )
        provider = MagicMock()
        provider.search_native.return_value = []
        bundle = make_federated_bundle(name="telegram", provider=provider)
        service._lifecycle_bundles["telegram"] = bundle

        with patch.object(service, "_execute_search", return_value=[local_candidate]):
            response = service.search("test query", rerank=False, expand=False)

        provider.search_native.assert_not_called()
        assert response.candidates == [local_candidate]

    def test_include_federated_search_calls_federated_provider(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)

        from dotmd.core.models import SearchCandidate
        from tests.search.conftest import make_federated_bundle

        local_candidate = SearchCandidate(
            ref="filesystem:/mnt/local.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="local snippet",
            fused_score=0.9,
            can_read=True,
        )
        federated_candidate = SearchCandidate(
            ref="telegram:result:0",
            namespace="telegram",
            descriptor_key="telegram",
            source_kind="test",
            retrieval_kind="telegram:fts",
            snippet="federated snippet",
            fused_score=0.0,
            can_read=False,
        )
        provider = MagicMock()
        provider.search_native.return_value = [federated_candidate]
        bundle = make_federated_bundle(name="telegram", provider=provider)
        service._lifecycle_bundles["telegram"] = bundle

        with patch.object(service, "_execute_search", return_value=[local_candidate]):
            response = service.search(
                "test query",
                rerank=False,
                expand=False,
                include_federated=True,
            )

        provider.search_native.assert_called_once_with("test query", limit=10)
        assert any(candidate.ref == federated_candidate.ref for candidate in response.candidates)


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
        updated_at=datetime(2026, 5, 6, tzinfo=UTC),
        content_fingerprint="content",
        metadata_fingerprint="metadata",
        metadata_json={},
    )


def _telegram_document():
    from dotmd.core.models import SourceDocument

    return SourceDocument(
        namespace="telegram",
        document_ref="dialog:-1001",
        ref="telegram:dialog:-1001",
        title="Project Chat",
        source_uri="telegram://dialog/-1001",
        media_type="text/plain",
        parser_name="telegram-message",
        document_type="dialog",
        updated_at=datetime(2026, 5, 7, tzinfo=UTC),
        content_fingerprint="telegram-content",
        metadata_fingerprint="telegram-metadata",
        metadata_json={"dialog_id": -1001, "dialog_name": "Project Chat"},
    )


def _telegram_unit(message_id: int, text: str, *, target: bool = False):
    from dotmd.core.models import SourceUnit

    return SourceUnit(
        namespace="telegram",
        document_ref="dialog:-1001",
        unit_ref=f"dialog:-1001:message:{message_id}",
        unit_type="message",
        text=text,
        order_key=f"{message_id:020d}",
        fingerprint=f"fingerprint-{message_id}",
        updated_at=datetime(2026, 5, 7, 12, message_id % 60, tzinfo=UTC),
        metadata_json={
            "dialog_id": -1001,
            "dialog_name": "Project Chat",
            "message_id": message_id,
            "sender_id": message_id * 10,
            "sender_name": f"User {message_id}",
            "sent_at": f"2026-05-07T12:{message_id % 60:02d}:00.000000Z",
            "topic_id": 7,
            "topic_title": "Deployments",
            "reply_to_msg_id": 41 if message_id == 42 else None,
            "target": target,
        },
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


def _write_markdown(path: Path, title: str, body: str) -> None:
    path.write_text(
        f"---\ntitle: {title}\ntags:\n  - phase27\n---\n{body}",
        encoding="utf-8",
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


class _RecordingSearchEngine:
    def __init__(self, results: list[tuple[str, float]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, int]] = []

    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        self.calls.append((query, top_k))
        return list(self._results)


class _RecordingGraphExpansionEngine:
    def __init__(self, results: list[tuple[str, float]]) -> None:
        self._results = list(results)
        self.calls: list[tuple[str, int, list[str]]] = []

    def search(
        self,
        query: str,
        top_k: int = 10,
        seed_chunk_ids: list[str] | None = None,
    ) -> list[tuple[str, float]]:
        self.calls.append((query, top_k, list(seed_chunk_ids or [])))
        return list(self._results)


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
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
        service._pipeline.log_search = MagicMock()
        active_provenance_map = {
            "active-1": _chunk_provenance("active-1"),
            "active-2": _chunk_provenance("active-2"),
        }
        service._collect_active_candidate_pool = MagicMock(
            return_value=(
                {
                    "search_query": "target",
                    "original_query": "target",
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
                },
                [("active-1", 0.7), ("active-2", 0.6)],  # filtered_fused (only active)
                active_provenance_map,
                2,  # inactive_count
            )
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
        logging.getLogger("dotmd").handlers.clear()
        logging.getLogger("dotmd").propagate = True
        caplog.set_level(logging.WARNING, logger="dotmd.api.service")
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            [f"inactive-{i}" for i in range(40)] + ["active-1"],
            {"active-1"},
        )
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
        service._pipeline.log_search = MagicMock()
        active_provenance_map = {
            "active-1": _chunk_provenance("active-1"),
        }
        service._collect_active_candidate_pool = MagicMock(
            return_value=(
                {
                    "search_query": "target",
                    "original_query": "target",
                    "fused": [(f"inactive-{i}", 1.0 - i / 100) for i in range(40)]
                    + [("active-1", 0.1)],
                    "engine_results": {},
                    "semantic_hits": [],
                    "keyword_hits": [],
                    "graph_direct_hits": [],
                    "pool_size": 52,
                },
                [("active-1", 0.1)],  # filtered_fused
                active_provenance_map,
                40,  # inactive_count
            )
        )

        response = service.search("target", top_k=2, rerank=False, expand=False)

        service._collect_active_candidate_pool.assert_called_once()
        assert service._collect_active_candidate_pool.call_args.kwargs["pool_size"] >= 52
        assert [result.ref for result in response.candidates] == ["filesystem:/mnt/active-1.md"]
        assert "active filter underfilled" in caplog.text

    def test_active_filter_expands_pool_until_visible_results_are_found(
        self,
        tmp_path: Path,
    ) -> None:
        """Test active filter returns results when they exist in expanded pool.

        Current behavior: single call with a large enough pool_size returns active results.
        Pool expansion logic (multiple calls with increasing pool_size) is deferred.
        """
        service = _get_service(tmp_path)
        inactive = [f"inactive-{i}" for i in range(55)]
        active = ["active-1", "active-2"]
        metadata = _SearchMetadataStore(inactive + active, set(active))
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
        service._pipeline.log_search = MagicMock()

        # Build provenance for active items
        active_provenance_map = {
            "active-1": _chunk_provenance("active-1"),
            "active-2": _chunk_provenance("active-2"),
        }

        # Single call returns a large pool containing all items
        service._collect_active_candidate_pool = MagicMock(
            return_value=(
                {
                    "search_query": "target",
                    "original_query": "target",
                    "fused": [
                        (chunk_id, 1.0 - i / 100) for i, chunk_id in enumerate(inactive + active)
                    ],
                    "engine_results": {},
                    "semantic_hits": [],
                    "keyword_hits": [],
                    "graph_direct_hits": [],
                    "pool_size": 110,
                },
                [("active-1", 0.44), ("active-2", 0.43)],  # filtered_fused with active items
                active_provenance_map,
                55,  # inactive_count
            )
        )

        response = service.search("target", top_k=2, rerank=False, expand=False)

        assert [result.ref for result in response.candidates] == [
            "filesystem:/mnt/active-1.md",
            "filesystem:/mnt/active-2.md",
        ]
        # Single call with pool_size = max(10, 2*5, 2+50) = 52 to find active results
        assert service._collect_active_candidate_pool.call_count == 1
        assert service._collect_active_candidate_pool.call_args.kwargs["pool_size"] == 52

    def test_reranker_receives_only_active_chunk_ids(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(
            ["inactive-1", "active-1", "active-2"],
            {"active-1", "active-2"},
        )
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
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
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
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
        assert results[0].engine_scores is not None
        assert results[0].engine_scores.get("graph_direct") == 0.8


class TestReadRefContract:
    """DotMDService.read resolves source refs and keeps paths internal."""

    def test_parse_telegram_message_ref_keeps_dialog_binding_scope(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.api.service import _parse_telegram_message_ref

        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = _telegram_document()
        metadata.is_resource_binding_active.return_value = True
        service._pipeline._metadata_store = metadata

        document_ref, unit_ref = _parse_telegram_message_ref("telegram:dialog:-1001:message:42")
        document, target_unit_ref = service._require_active_telegram_message_ref(
            "telegram:dialog:-1001:message:42"
        )

        assert document_ref == "dialog:-1001"
        assert unit_ref == "dialog:-1001:message:42"
        assert document.document_ref == "dialog:-1001"
        assert target_unit_ref == "dialog:-1001:message:42"
        metadata.is_resource_binding_active.assert_called_once_with(
            "telegram",
            "dialog:-1001",
        )

    def test_read_telegram_ref_uses_provider_window_and_marks_target(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import SourceUnitWindow

        service = _get_service(tmp_path)
        metadata = MagicMock()
        # FEDERATED_ONLY path: no local document
        metadata.get_source_document.return_value = None
        service._pipeline._metadata_store = metadata
        provider = MagicMock()
        provider.read_unit_window.return_value = SourceUnitWindow(
            namespace="telegram",
            document_ref="dialog:-1001",
            unit_ref="dialog:-1001:message:42",
            units=[
                _telegram_unit(41, "Can someone verify the migration window?"),
                _telegram_unit(42, "Deployment checklist is ready", target=True),
                _telegram_unit(43, "Smoke confirms the deployment path"),
            ],
            metadata_json={"dialog_id": -1001},
        )
        service._telegram_provider = provider

        payload = cast(
            dict[str, Any],
            service.read("telegram:dialog:-1001:message:42", start=2, end=4),
        )

        provider.read_unit_window.assert_called_once_with(
            "dialog:-1001:message:42",
            before=2,
            after=4,
        )
        assert payload["ref"] == "telegram:dialog:-1001:message:42"
        assert payload["frontmatter"] == {}
        assert [unit["message_id"] for unit in payload["units"]] == [41, 42, 43]
        assert [unit["text"] for unit in payload["units"]] == [
            "Can someone verify the migration window?",
            "Deployment checklist is ready",
            "Smoke confirms the deployment path",
        ]
        assert [unit["target"] for unit in payload["units"]] == [False, True, False]

    def test_read_telegram_ref_defaults_and_clamps_window_sizes(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import SourceUnitWindow

        service = _get_service(tmp_path)
        metadata = MagicMock()
        # FEDERATED_ONLY path: no local document
        metadata.get_source_document.return_value = None
        service._pipeline._metadata_store = metadata
        provider = MagicMock()
        provider.read_unit_window.return_value = SourceUnitWindow(
            namespace="telegram",
            document_ref="dialog:-1001",
            unit_ref="dialog:-1001:message:42",
            units=[_telegram_unit(42, "Deployment checklist is ready")],
            metadata_json={},
        )
        service._telegram_provider = provider

        service.read("telegram:dialog:-1001:message:42", start=99, end=None)

        provider.read_unit_window.assert_called_once_with(
            "dialog:-1001:message:42",
            before=50,
            after=5,
        )

    def test_read_telegram_ref_falls_back_to_indexed_chunks_without_provider(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import Chunk, ChunkProvenance

        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = _telegram_document()
        metadata.is_resource_binding_active.return_value = True
        metadata.get_chunks_by_source_unit_ref.return_value = [
            Chunk(
                chunk_id="c" * 64,
                file_paths=[],
                heading_hierarchy=["Telegram", "Project Chat"],
                level=2,
                text="Deployment checklist is ready",
                chunk_index=0,
                provenance=ChunkProvenance(
                    namespace="telegram",
                    document_ref="dialog:-1001",
                    ref="telegram:dialog:-1001",
                    source_unit_refs=["dialog:-1001:message:42"],
                    chunk_strategy=service._settings.chunk_strategy,
                    parser_name="telegram-message",
                ),
            )
        ]
        service._pipeline._metadata_store = metadata
        service._telegram_provider = None

        payload = cast(dict[str, Any], service.read("telegram:dialog:-1001:message:42"))

        metadata.get_chunks_by_source_unit_ref.assert_called_once_with(
            "telegram",
            "dialog:-1001",
            "dialog:-1001:message:42",
            service._settings.chunk_strategy,
        )
        assert payload["ref"] == "telegram:dialog:-1001:message:42"
        assert payload["target_unit_ref"] == "dialog:-1001:message:42"
        assert payload["chunks"] == [
            {
                "index": 0,
                "heading_hierarchy": ["Telegram", "Project Chat"],
                "text": "Deployment checklist is ready",
                "target": True,
                "source_unit_refs": ["dialog:-1001:message:42"],
            }
        ]

    def test_read_telegram_ref_rejects_inactive_dialog_binding(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = _telegram_document()
        metadata.is_resource_binding_active.return_value = False
        service._pipeline._metadata_store = metadata

        with pytest.raises(PermissionError, match="Telegram ref has INACTIVE binding"):
            service.read("telegram:dialog:-1001:message:42")

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
        assert payload["chunks"] == [{"index": 0, "heading_hierarchy": ["H"], "text": "Body"}]
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

    def test_read_ref_rejects_inactive_binding_with_retained_chunks(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "inactive.md"
        note_path.write_text("---\ntitle: Retained\n---\nBody", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.is_resource_binding_active.return_value = False
        metadata.get_chunk_count_for_file.return_value = 1
        service._pipeline._metadata_store = metadata

        try:
            service.read(document.ref)
        except ValueError as exc:
            assert "Unknown source ref" in str(exc)
        else:
            raise AssertionError("read() should reject inactive retained refs")

    def test_read_ref_rejects_inactive_filesystem_binding_with_present_file(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "present-but-inactive.md"
        note_path.write_text("Body", encoding="utf-8")
        ref = f"filesystem:{note_path.resolve()}"
        metadata = MagicMock()
        metadata.get_source_document.return_value = None
        metadata.is_resource_binding_active.return_value = False
        metadata.get_chunk_count_for_file.return_value = 1
        service._pipeline._metadata_store = metadata

        try:
            service.read(ref)
        except ValueError as exc:
            assert "Unknown source ref" in str(exc)
        else:
            raise AssertionError("read() should reject inactive filesystem fallback refs")

    def test_read_ref_rejects_missing_binding_before_synthetic_fallback(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "missing-binding.md"
        note_path.write_text("Body", encoding="utf-8")
        ref = f"filesystem:{note_path.resolve()}"
        metadata = MagicMock()
        metadata.get_source_document.return_value = None
        metadata.is_resource_binding_active.return_value = False
        metadata.get_chunk_count_for_file.return_value = 1
        service._pipeline._metadata_store = metadata

        try:
            service.read(ref)
        except ValueError as exc:
            assert "Unknown source ref" in str(exc)
        else:
            raise AssertionError("read() should reject missing active binding")

    def test_drill_ref_rejects_inactive_binding(self, tmp_path: Path) -> None:
        service = _get_service(tmp_path)
        note_path = tmp_path / "inactive-drill.md"
        note_path.write_text("Body", encoding="utf-8")
        document = _source_document(note_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = document
        metadata.is_resource_binding_active.return_value = False
        metadata.get_chunk_count_for_file.return_value = 1
        service._pipeline._metadata_store = metadata

        try:
            service.drill(document.ref)
        except ValueError as exc:
            assert "Unknown source ref" in str(exc)
        else:
            raise AssertionError("drill() should reject inactive refs")

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

    def test_drill_telegram_ref_returns_metadata_without_frontmatter(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = _telegram_document()
        metadata.is_resource_binding_active.return_value = True
        service._pipeline._metadata_store = metadata

        payload = cast(dict[str, Any], service.drill("telegram:dialog:-1001:message:42"))

        assert payload["ref"] == "telegram:dialog:-1001:message:42"
        assert payload["document_ref"] == "dialog:-1001"
        assert payload["target_unit_ref"] == "dialog:-1001:message:42"
        assert payload["title"] == "Project Chat"
        assert payload["source_uri"] == "telegram://dialog/-1001"
        assert payload["document_type"] == "dialog"
        assert payload["parser_name"] == "telegram-message"
        assert payload["metadata"]["dialog_id"] == -1001
        assert payload["frontmatter"] == {}

    def test_drill_telegram_ref_rejects_inactive_dialog_binding(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.get_source_document.return_value = _telegram_document()
        metadata.is_resource_binding_active.return_value = False
        service._pipeline._metadata_store = metadata

        with pytest.raises(PermissionError, match="Telegram ref has INACTIVE binding"):
            service.drill("telegram:dialog:-1001:message:42")


class TestBindingDiagnostics:
    """Service diagnostics expose counts without inactive content browsing."""

    def test_binding_diagnostics_returns_active_inactive_retained_and_reused_counts(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.count_resource_bindings.return_value = {
            "active": 2,
            "inactive": 1,
            "total": 3,
        }
        metadata.count_retained_inactive_chunks.return_value = 4
        metadata.count_reused_chunks_from_bindings.return_value = 6
        service._pipeline._metadata_store = metadata
        object.__setattr__(
            service._pipeline,
            "_last_rebind_diagnostic",
            {"reused_chunks": 7},
        )

        diagnostics = service.binding_diagnostics()

        assert diagnostics == {
            "active": 2,
            "inactive": 1,
            "retained": 4,
            "reused": 7,
        }

    def test_binding_diagnostics_do_not_duplicate_source_document_metadata(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.count_resource_bindings.return_value = {
            "active": 1,
            "inactive": 0,
            "total": 1,
        }
        metadata.count_retained_inactive_chunks.return_value = 0
        metadata.count_reused_chunks_from_bindings.return_value = 0
        metadata.get_source_document.side_effect = AssertionError(
            "diagnostics must not duplicate source document metadata"
        )
        service._pipeline._metadata_store = metadata

        diagnostics = service.binding_diagnostics()

        assert diagnostics == {
            "active": 1,
            "inactive": 0,
            "retained": 0,
            "reused": 0,
        }
        metadata.get_source_document.assert_not_called()


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
        assert all(
            run["elapsed"] and run["load"] and run["rerank"] for run in comparison["rerankers"]
        )
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

        assert failing.rerank.call_args.kwargs["raise_on_provider_error"] is True
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

    def test_compare_default_names_include_configured_models(self, tmp_path: Path) -> None:
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

    def test_compare_three_rerankers_reuses_retrieval_engines_once(self, tmp_path: Path) -> None:
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


class TestSurrealHybridOverrides:
    def test_surreal_runtime_retrieval_engines_are_replaced(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.api.service import DotMDService
        from dotmd.core.models import SearchMode

        semantic = _RecordingSearchEngine([("semantic-hit", 0.91)])
        keyword = _RecordingSearchEngine([("keyword-hit", 0.72)])
        graph_direct = _RecordingSearchEngine([("graph-hit", 1.0)])
        connection = MagicMock()
        connection.raw = MagicMock()

        settings = make_surreal_runtime_settings(
            index_dir=tmp_path,
            embedding_url="http://localhost:8088",
            surreal_retrieval_username="root",
            surreal_retrieval_password="root",
            surreal_retrieval_access_token=None,
            surreal_retrieval_hnsw_ef=80,
            telegram_daemon_socket=None,
        )

        with (
            patch("dotmd.storage.surreal.SurrealConnection", return_value=connection) as conn_cls,
            patch(
                "dotmd.search.surreal_native.build_surreal_native_engine_overrides",
                return_value={
                    "semantic": semantic,
                    "keyword": keyword,
                    "graph_direct": graph_direct,
                },
            ) as build_overrides,
        ):
            service = DotMDService(settings)

        assert conn_cls.call_count >= 1
        for call in conn_cls.call_args_list:
            config = call.args[0]
            assert config.url == "http://surrealdb:8000"
            assert config.namespace == "dotmd"
            assert config.database == "production"
            assert config.username == "root"
            assert config.password == "root"
        build_overrides.assert_called_once_with(
            connection,
            settings,
            embedding_dimension=1024,
            hnsw_ef=80,
            embedding_shard_count=1,
        )
        assert service._semantic_engine is semantic
        assert service._keyword_engine is keyword
        assert service._graph_direct_engine is graph_direct
        assert service._graph_engine.__class__.__name__ == "_DisabledGraphEnrichmentEngine"

        with patch("dotmd.api.service.fuse_results", return_value=[("semantic-hit", 0.9)]):
            pool = service._collect_candidate_pool(
                search_query="expanded query",
                original_query="raw query",
                mode=SearchMode.HYBRID,
                pool_size=3,
            )

        assert semantic.calls == [("expanded query", 3)]
        assert keyword.calls == [("expanded query", 3)]
        assert graph_direct.calls == [("raw query", 3)]
        assert "graph" not in pool["engine_results"]

    def test_collect_candidate_pool_uses_engine_overrides_and_existing_fusion(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import SearchMode

        service = _get_service(tmp_path)
        semantic = _RecordingSearchEngine([("shared", 0.91), ("semantic-only", 0.83)])
        keyword = _RecordingSearchEngine([("shared", 0.72), ("keyword-only", 0.64)])
        graph_direct = _RecordingSearchEngine([("graph-only", 1.0)])
        service._graph_engine.search = MagicMock(return_value=[])

        expected_engine_results = {
            "semantic": [("shared", 0.91), ("semantic-only", 0.83)],
            "keyword": [("shared", 0.72), ("keyword-only", 0.64)],
            "graph_direct": [("graph-only", 1.0)],
        }
        fused_results = [("shared", 0.4), ("graph-only", 0.3), ("keyword-only", 0.2)]

        with patch(
            "dotmd.api.service.fuse_results", return_value=fused_results
        ) as fuse_results_mock:
            pool = service._collect_candidate_pool(
                search_query="expanded query",
                original_query="raw query",
                mode=SearchMode.HYBRID,
                pool_size=4,
                engine_overrides={
                    "semantic": semantic,
                    "keyword": keyword,
                    "graph_direct": graph_direct,
                },
            )

        assert semantic.calls == [("expanded query", 4)]
        assert keyword.calls == [("expanded query", 4)]
        assert graph_direct.calls == [("raw query", 4)]
        fuse_results_mock.assert_called_once_with(
            expected_engine_results, k=service._settings.fusion_k
        )
        service._graph_engine.search.assert_called_once_with(
            "expanded query",
            top_k=4,
            seed_chunk_ids=["shared", "graph-only", "keyword-only"],
        )
        assert pool["engine_results"] == expected_engine_results
        assert pool["fused"] == fused_results

    def test_collect_candidate_pool_uses_graph_override_when_supplied(
        self,
        tmp_path: Path,
    ) -> None:
        from dotmd.core.models import SearchMode

        service = _get_service(tmp_path)
        semantic = _RecordingSearchEngine([("shared", 0.91)])
        graph_override = _RecordingGraphExpansionEngine([("graph-added", 0.8)])
        service._keyword_engine.search = MagicMock(return_value=[])
        service._graph_direct_engine.search = MagicMock(return_value=[])
        service._graph_engine.search = MagicMock(return_value=[("should-not-run", 1.0)])

        pool = service._collect_candidate_pool(
            search_query="expanded query",
            original_query="raw query",
            mode=SearchMode.HYBRID,
            pool_size=3,
            engine_overrides={
                "semantic": semantic,
                "graph": graph_override,
            },
        )

        service._graph_engine.search.assert_not_called()
        assert graph_override.calls == [("expanded query", 3, ["shared"])]
        assert pool["engine_results"]["graph"] == [("graph-added", 0.8)]
        assert [chunk_id for chunk_id, _score in pool["fused"]] == ["shared", "graph-added"]
        assert pool["fused"][1][1] == pytest.approx(pool["fused"][0][1] * 0.5)

    def test_execute_search_preserves_engine_attribution_for_overlapping_hits(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = _SearchMetadataStore(["shared"], {"shared"})
        service._pipeline._metadata_store = cast(SQLiteMetadataStore, metadata)
        service._pipeline.log_search = MagicMock()
        service._collect_active_candidate_pool = MagicMock(
            return_value=(
                {
                    "search_query": "expanded",
                    "original_query": "raw",
                    "fused": [("shared", 0.9)],
                    "engine_results": {
                        "semantic": [("shared", 0.8)],
                        "keyword": [("shared", 0.7)],
                        "graph_direct": [("shared", 0.6)],
                    },
                    "semantic_hits": [("shared", 0.8)],
                    "keyword_hits": [("shared", 0.7)],
                    "graph_direct_hits": [("shared", 0.6)],
                    "pool_size": 1,
                },
                [("shared", 0.9)],
                {"shared": _chunk_provenance("shared")},
                0,
            )
        )

        results = service._execute_search(
            search_query="expanded",
            original_query="raw",
            top_k=1,
            mode="hybrid",
            rerank=False,
            reranker_name=None,
            pool_size=1,
        )

        assert len(results) == 1
        assert results[0].matched_engines == ("graph_direct", "keyword", "semantic")
        assert results[0].engine_scores == {
            "semantic": 0.8,
            "keyword": 0.7,
            "graph_direct": 0.6,
        }

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

    def test_compare_all_failures_returns_errors_and_empty_overlap(self, tmp_path: Path) -> None:
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

    def test_search_endpoint_awaits_async_service_path(self) -> None:
        from dotmd.api import server
        from dotmd.core.models import SearchCandidate, SearchMode, SearchResponse

        candidate = SearchCandidate(
            ref="filesystem:/mnt/test.md#0",
            namespace="filesystem",
            descriptor_key="filesystem-mnt",
            source_kind="markdown",
            retrieval_kind="semantic",
            snippet="test snippet",
            fused_score=0.9,
            can_read=True,
            can_materialize=False,
        )
        service = MagicMock()
        service.search = MagicMock(side_effect=AssertionError("search() should not be called"))
        service.search_async = AsyncMock(
            return_value=SearchResponse(candidates=[candidate], source_status=[])
        )
        server._service = service
        client = TestClient(server.app)

        response = client.get("/search?q=test&reranker=msmarco-minilm")

        assert response.status_code == 200
        service.search.assert_not_called()
        service.search_async.assert_awaited_once_with(
            query="test",
            top_k=10,
            mode=SearchMode.HYBRID,
            rerank=True,
            expand=True,
            reranker_name="msmarco-minilm",
            include_federated=False,
        )
        payload = response.json()
        assert payload["count"] == 1
        assert payload["results"][0]["ref"] == "filesystem:/mnt/test.md#0"

    def test_search_endpoint_includes_federated_when_requested(self) -> None:
        from dotmd.api import server
        from dotmd.core.models import SearchMode, SearchResponse

        service = MagicMock()
        service.search = MagicMock(side_effect=AssertionError("search() should not be called"))
        service.search_async = AsyncMock(
            return_value=SearchResponse(candidates=[], source_status=[])
        )
        server._service = service
        client = TestClient(server.app)

        response = client.get("/search?q=test&federated=true")

        assert response.status_code == 200
        service.search.assert_not_called()
        service.search_async.assert_awaited_once_with(
            query="test",
            top_k=10,
            mode=SearchMode.HYBRID,
            rerank=True,
            expand=True,
            reranker_name=None,
            include_federated=True,
        )

    def test_search_endpoint_unknown_reranker_returns_400(self) -> None:
        from dotmd.api import server

        service = MagicMock()
        service.search_async = AsyncMock(
            side_effect=ValueError("Unknown reranker 'missing'; available: mmarco-minilm")
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

        response = client.get("/rerank/compare?q=test&rerankers=mmarco-minilm,msmarco-minilm")

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

    def test_execute_search_backfills_missing_filesystem_source_documents(
        self,
        tmp_path: Path,
    ) -> None:
        service = _get_service(tmp_path)
        metadata = MagicMock()
        metadata.count_missing_source_provenance.return_value = 0
        service._pipeline._metadata_store = metadata
        service._pipeline.backfill_filesystem_source_documents_from_provenance = MagicMock(
            return_value={
                "missing_source_documents": 2,
                "inserted_source_documents": 2,
                "inserted_bindings": 2,
                "missing_files": 0,
                "skipped_files": 0,
            }
        )
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
        service._pipeline.backfill_filesystem_source_documents_from_provenance.assert_called_once_with(
            service._settings.chunk_strategy,
            dry_run=False,
        )


class TestMergeWithFederatedQuota:
    """Unit tests for the module-level _merge_with_federated_quota function."""

    def _local(self, n: int, base_score: float = 0.9) -> list:
        from dotmd.core.models import SearchCandidate

        return [
            SearchCandidate(
                ref=f"filesystem:/mnt/doc_{i}.md#0",
                namespace="filesystem",
                descriptor_key="filesystem-mnt",
                source_kind="markdown",
                retrieval_kind="semantic",
                snippet=f"local result {i} with enough content to pass filters",
                fused_score=base_score - i * 0.05,
                can_read=True,
            )
            for i in range(n)
        ]

    def _fed(self, n: int, snippet_template: str = "telegram message about {i}") -> list:
        from dotmd.core.models import SearchCandidate

        return [
            SearchCandidate(
                ref=f"telegram:dialog:-100123:message:{i}",
                namespace="telegram",
                descriptor_key="telegram-dialog--100123",
                source_kind="telegram_message",
                retrieval_kind="fts",
                snippet=snippet_template.format(i=i),
                fused_score=0.0,  # daemon returns no score
                can_read=False,
            )
            for i in range(n)
        ]

    def test_federated_quota_candidates_appear_when_local_fills_top_k(self) -> None:
        """Fed candidates appear even when local results could fill all top_k slots."""
        from dotmd.api.service import _merge_with_federated_quota

        local = self._local(10)
        fed = self._fed(3)
        result = _merge_with_federated_quota(local, fed, top_k=5, fed_quota=3)
        assert len(result) == 5
        fed_refs = {c.ref for c in fed}
        assert sum(1 for c in result if c.ref in fed_refs) == 3

    def test_federated_quota_adaptive_slots(self) -> None:
        """When fewer fed candidates exist than quota, local fills the remainder."""
        from dotmd.api.service import _merge_with_federated_quota

        local = self._local(10)
        fed = self._fed(1)  # only 1 fed result, quota is 3
        result = _merge_with_federated_quota(local, fed, top_k=5, fed_quota=3)
        assert len(result) == 5
        fed_refs = {c.ref for c in fed}
        assert sum(1 for c in result if c.ref in fed_refs) == 1
        # local fills the 4 remaining slots
        assert sum(1 for c in result if c.ref not in fed_refs) == 4

    def test_federated_quota_filters_low_signal(self) -> None:
        """Low-signal fed snippets (short/emoji) are dropped before quota math."""
        from dotmd.api.service import _merge_with_federated_quota
        from dotmd.core.models import SearchCandidate

        low_signal = SearchCandidate(
            ref="telegram:dialog:-100123:message:99",
            namespace="telegram",
            descriptor_key="telegram-dialog--100123",
            source_kind="telegram_message",
            retrieval_kind="fts",
            snippet="ok",  # very short — is_low_signal_telegram_text returns True
            fused_score=0.0,
            can_read=False,
        )
        local = self._local(5)
        result = _merge_with_federated_quota(local, [low_signal], top_k=5, fed_quota=3)
        assert all(c.ref != low_signal.ref for c in result), "low-signal candidate must be excluded"

    def test_federated_quota_empty_fed_returns_sorted_local(self) -> None:
        """Empty fed list returns local candidates sorted by fused_score descending."""
        from dotmd.api.service import _merge_with_federated_quota

        # create local in reverse score order to verify sorting
        local = self._local(5, base_score=0.5)
        local_shuffled = list(reversed(local))
        result = _merge_with_federated_quota(local_shuffled, [], top_k=3, fed_quota=3)
        assert len(result) == 3
        assert result[0].fused_score >= result[1].fused_score >= result[2].fused_score
