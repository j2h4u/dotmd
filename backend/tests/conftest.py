"""Shared test fixtures for dotMD."""

from __future__ import annotations

import sqlite3
from collections.abc import Generator
from pathlib import Path
from typing import Any, cast
from unittest.mock import patch

import pytest

from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth
from dotmd.storage.base import MetadataStoreProtocol

# ---------------------------------------------------------------------------
# Global env fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _dotmd_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Set minimal env vars so Settings() and IndexingPipeline can be constructed.

    - DOTMD_EMBEDDING_URL: required field with no default (prevents misconfiguration
      in production). A non-routable stub is fine — tests that need real embeddings
      mock the HTTP call at a higher level.
    - DOTMD_EXTRACT_DEPTH: override to 'structural' so tests that construct a full
      IndexingPipeline do not accidentally load NER models or call TEI during ingest.
      Tests that specifically exercise NER must override this fixture or set the env
      var directly.
    """
    monkeypatch.setenv("DOTMD_EMBEDDING_URL", "http://test-tei:8088")
    monkeypatch.setenv("DOTMD_EXTRACT_DEPTH", "structural")


class InMemoryGraphStore:
    """Small test double for GraphStoreProtocol.

    Unit tests exercise pipeline behavior, not graph-backend connectivity. Keep
    this fake in tests only so production has a single real retrieval backend.
    """

    def __init__(self) -> None:
        self.nodes: dict[str, dict] = {}
        self.edges: list[dict] = []

    def add_file_node(self, file_path: str, title: str) -> None:
        self.nodes[file_path] = {
            "id": file_path,
            "label": "File",
            "properties": {"title": title},
        }

    def add_section_node(
        self,
        chunk_id: str,
        heading: str,
        level: int,
        file_path: str,
        text_preview: str,
    ) -> None:
        self.nodes[chunk_id] = {
            "id": chunk_id,
            "label": "Section",
            "properties": {
                "heading": heading,
                "level": level,
                "file_path": file_path,
                "text_preview": text_preview,
            },
        }

    def add_entity_node(self, name: str, entity_type: str, source: str) -> None:
        self.nodes[name] = {
            "id": name,
            "label": "Entity",
            "properties": {"type": entity_type, "source": source},
        }

    def add_tag_node(self, name: str) -> None:
        self.nodes[name] = {"id": name, "label": "Tag", "properties": {}}

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        self.edges = [
            edge
            for edge in self.edges
            if not (
                edge["source"] == source_id
                and edge["target"] == target_id
                and edge["relation_type"] == relation_type
            )
        ]
        self.edges.append(
            {
                "source": source_id,
                "target": target_id,
                "relation_type": relation_type,
                "weight": weight,
            }
        )

    def batch_add_section_nodes(self, sections: list[dict]) -> None:
        for section in sections:
            self.add_section_node(
                chunk_id=section["chunk_id"],
                heading=section["heading"],
                level=section["level"],
                file_path=section["file_path"],
                text_preview=section["text_preview"],
            )

    def batch_add_entity_nodes(self, entities: list[dict]) -> None:
        for entity in entities:
            self.add_entity_node(
                name=entity["name"],
                entity_type=entity["entity_type"],
                source=entity["source"],
            )

    def batch_add_tag_nodes(self, tags: list[str]) -> None:
        for tag in tags:
            self.add_tag_node(tag)

    def batch_add_file_nodes(self, files: list[dict]) -> None:
        for file in files:
            self.add_file_node(file_path=file["file_path"], title=file["title"])

    def batch_add_edges(self, edges: list[dict]) -> None:
        for edge in edges:
            self.add_edge(
                source_id=edge["source_id"],
                target_id=edge["target_id"],
                relation_type=edge["relation_type"],
                weight=edge.get("weight", 1.0),
            )

    def get_related_sections(self, chunk_id: str) -> list[tuple[str, str, float]]:
        mentioned = {
            edge["target"]
            for edge in self.edges
            if edge["source"] == chunk_id and edge["relation_type"] in {"MENTIONS", "HAS_TAG"}
        }
        return [
            (edge["source"], edge["relation_type"], edge["weight"])
            for edge in self.edges
            if (
                edge["source"] != chunk_id
                and edge["target"] in mentioned
                and edge["relation_type"] in {"MENTIONS", "HAS_TAG"}
            )
        ]

    def get_all_entity_names(self) -> list[str]:
        return sorted(node_id for node_id, node in self.nodes.items() if node["label"] == "Entity")

    def get_chunks_by_entity(self, entity_name: str) -> list[str]:
        return sorted(
            edge["source"]
            for edge in self.edges
            if edge["target"] == entity_name
            and self.nodes.get(edge["source"], {}).get("label") == "Section"
        )

    def get_entities_by_file(self, file_path: str) -> list[str]:
        chunk_ids = {
            node_id
            for node_id, node in self.nodes.items()
            if node["label"] == "Section" and node["properties"].get("file_path") == file_path
        }
        return sorted(
            edge["target"]
            for edge in self.edges
            if edge["source"] in chunk_ids
            and self.nodes.get(edge["target"], {}).get("label") == "Entity"
        )

    def delete_all(self) -> None:
        self.nodes.clear()
        self.edges.clear()

    def delete_file_subgraph(self, file_path: str) -> None:
        chunk_ids = [
            node_id
            for node_id, node in self.nodes.items()
            if node["label"] == "Section" and node["properties"].get("file_path") == file_path
        ]
        for chunk_id in chunk_ids:
            self.nodes.pop(chunk_id, None)
        self.nodes.pop(file_path, None)
        removed = set(chunk_ids) | {file_path}
        self.edges = [
            edge
            for edge in self.edges
            if edge["source"] not in removed and edge["target"] not in removed
        ]

    def delete_chunks_from_graph(self, chunk_ids: list[str]) -> None:
        removed = set(chunk_ids)
        for chunk_id in chunk_ids:
            self.nodes.pop(chunk_id, None)
        self.edges = [
            edge
            for edge in self.edges
            if edge["source"] not in removed and edge["target"] not in removed
        ]

    def delete_file_node(self, file_path: str) -> None:
        self.nodes.pop(file_path, None)
        self.edges = [
            edge
            for edge in self.edges
            if edge["source"] != file_path and edge["target"] != file_path
        ]

    def delete_frontmatter_edges(self, file_path: str) -> None:
        self.edges = [
            edge
            for edge in self.edges
            if not (
                edge["source"] == file_path
                and edge["relation_type"] in {"HAS_TAG", "HAS_PARTICIPANT"}
            )
        ]

    def node_count(self) -> int:
        return len(self.nodes)

    def edge_count(self) -> int:
        return len(self.edges)

    def delete_isolated_nodes(self) -> int:
        connected = {edge["source"] for edge in self.edges} | {
            edge["target"] for edge in self.edges
        }
        isolated = [
            node_id
            for node_id, node in self.nodes.items()
            if node["label"] in {"Entity", "Tag"} and node_id not in connected
        ]
        for node_id in isolated:
            self.nodes.pop(node_id, None)
        return len(isolated)

    def get_graph_data(self) -> dict:
        return {
            "nodes": list(self.nodes.values()),
            "edges": list(self.edges),
        }


@pytest.fixture(autouse=True)
def _mock_graph_store_factory(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    with patch("dotmd.ingestion.pipeline._NoopGraphStore", InMemoryGraphStore):
        yield


@pytest.fixture(autouse=True)
def _mock_semantic_engine(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Patch SemanticSearchEngine to avoid real HTTP/model calls in tests.

    Tests that exercise the actual embedding pipeline should override this
    fixture or un-patch locally. The stub returns zero-vectors (dimension 8)
    which is enough for schema/idempotency tests that only check row counts.
    """
    if request.node.get_closest_marker("real_semantic_encode_batch"):
        yield
        return

    def _stub_encode_batch(texts: list[str]) -> list[list[float]]:
        return [[0.0] * 8 for _ in texts]

    def _stub_get_tei_model_id(self) -> str | None:  # type: ignore[no-untyped-def]
        return "stub-model"

    with (
        patch(
            "dotmd.search.semantic.SemanticSearchEngine.encode_batch",
            side_effect=_stub_encode_batch,
        ),
        patch(
            "dotmd.search.semantic.SemanticSearchEngine.get_tei_model_id",
            _stub_get_tei_model_id,
        ),
    ):
        yield


@pytest.fixture(autouse=True)
def _mock_schema_version_check(request: pytest.FixtureRequest) -> Generator[None, None, None]:
    """Patch _check_schema_version to no-op in all tests.

    Prevents the schema wipe from firing when tests construct an IndexingPipeline
    with a pre-populated fixture DB (which has chunk_fingerprints rows and therefore
    looks like a pre-999.12 DB to the real check).

    Tests that specifically exercise _check_schema_version must opt out with:
        @pytest.mark.real_schema_check
    """
    if request.node.get_closest_marker("real_schema_check"):
        yield
        return
    with patch("dotmd.ingestion.pipeline.IndexingPipeline._check_schema_version"):
        yield


# ---------------------------------------------------------------------------
# Shared service helpers
# ---------------------------------------------------------------------------


def make_surreal_runtime_settings(**overrides: object) -> Settings:
    """Construct runtime-ready Settings with the Surreal retrieval fields set."""
    settings_kwargs: dict[str, Any] = {
        "data_dir": Path("/mnt"),
        "index_dir": Path("/dotmd-index"),
        "indexing_paths": ["/mnt"],
        "embedding_url": "http://tei:80",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "chunk_strategy": "heading_512_50",
        "extract_depth": ExtractDepth.NER,
        "ner_model_name": "urchade/gliner_multi-v2.1",
        "reranker_name": "mmarco-minilm",
        "reranker_model": "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1",
        "reranker_backend": "cross_encoder",
        "embedding_weights": "text=0.7,meta=0.3",
        "surreal_retrieval_url": "http://surrealdb:8000",
        "surreal_retrieval_namespace": "dotmd",
        "surreal_retrieval_database": "production",
        "surreal_retrieval_username": None,
        "surreal_retrieval_password": None,
        "surreal_retrieval_access_token": "token",
        "surreal_retrieval_embedding_dimension": 1024,
        "surreal_retrieval_hnsw_ef": 40,
        "surreal_retrieval_embedding_shard_count": 1,
    }
    settings_kwargs.update(overrides)
    return Settings(**cast(Any, settings_kwargs))


def make_surreal_service(
    tmp_path: Path,
    *,
    semantic_engine: Any | None = None,
    keyword_engine: Any | None = None,
    graph_direct_engine: Any | None = None,
    **settings_overrides: object,
) -> Any:
    """Construct DotMDService through the Surreal-only retrieval path."""
    from unittest.mock import MagicMock, patch

    from dotmd.api.service import DotMDService

    class _PipelineMetadataStoreProxy:
        def __init__(self, pipeline: Any) -> None:
            self._pipeline = pipeline

        def __getattr__(self, name: str) -> object:
            return getattr(self._pipeline._metadata_store, name)

    settings = make_surreal_runtime_settings(index_dir=tmp_path, **settings_overrides)
    connection = MagicMock()
    connection.raw = MagicMock()
    semantic_engine = semantic_engine or MagicMock(name="semantic_engine")
    keyword_engine = keyword_engine or MagicMock(name="keyword_engine")
    graph_direct_engine = graph_direct_engine or MagicMock(name="graph_direct_engine")

    with (
        patch("dotmd.storage.surreal.SurrealConnection", return_value=connection),
        patch(
            "dotmd.search.surreal_native.build_surreal_native_engine_overrides",
            return_value={
                "semantic": semantic_engine,
                "keyword": keyword_engine,
                "graph_direct": graph_direct_engine,
            },
        ),
    ):
        service = DotMDService(settings)
        service._surreal_metadata_store = cast(
            MetadataStoreProtocol, _PipelineMetadataStoreProxy(service._pipeline)
        )
        return service


# ---------------------------------------------------------------------------
# Shared convenience fixtures (used by pre-phase-16 test files)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_dir(tmp_path: Path) -> Path:
    """Alias for tmp_path — used by test files that predate pytest's tmp_path name."""
    return tmp_path


@pytest.fixture
def sqlite_conn(tmp_path: Path) -> Generator[sqlite3.Connection, None, None]:
    """In-memory SQLite connection for FileTracker tests."""
    conn = sqlite3.connect(":memory:")
    yield conn
    conn.close()


@pytest.fixture
def metadata_store(tmp_path: Path):
    """SQLiteMetadataStore with M2M table for the default strategy."""
    from dotmd.storage.metadata import SQLiteMetadataStore

    strategy = "heading_512_50"
    db_path = tmp_path / "metadata.db"
    store = SQLiteMetadataStore(db_path=db_path, table_name=f"chunks_{strategy}")
    store.ensure_m2m_table(strategy)
    return store


@pytest.fixture
def graph_store() -> InMemoryGraphStore:
    return InMemoryGraphStore()
