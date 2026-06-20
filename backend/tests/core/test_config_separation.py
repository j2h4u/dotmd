"""Settings boundary tests for operator config and internal defaults."""

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import Mock, patch

import pytest
from starlette.testclient import TestClient

from dotmd import mcp_server
from dotmd.api import server as api_server
from dotmd.api.service import DotMDService
from dotmd.core import config
from dotmd.core.config import Settings, load_runtime_settings
from dotmd.core.models import ExtractDepth, IndexStats, TrickleStatus


def _runtime_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
        "data_dir": Path("/mnt"),
        "index_dir": Path("/dotmd-index"),
        "indexing_paths": ["/mnt"],
        "embedding_url": "http://tei:80",
        "embedding_model": "BAAI/bge-small-en-v1.5",
        "search_backend": "surreal",
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
    values.update(overrides)
    return Settings(**values)


def test_settings_still_constructs_with_current_defaults() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert settings.embedding_url == "http://localhost:8088"
    assert settings.data_dir == Path()
    assert settings.index_dir == Path.home() / ".dotmd"
    assert settings.default_top_k == 10
    assert settings.base_url is None


def test_default_indexing_exclude_is_exported() -> None:
    assert "**/node_modules" in config.DEFAULT_INDEXING_EXCLUDE
    assert "**/.git" in config.DEFAULT_INDEXING_EXCLUDE
    assert "**/__pycache__" in config.DEFAULT_INDEXING_EXCLUDE
    assert "**/.cache" in config.DEFAULT_INDEXING_EXCLUDE


def test_effective_indexing_exclude_includes_builtin_defaults() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert all(
        pattern in settings.effective_indexing_exclude
        for pattern in config.DEFAULT_INDEXING_EXCLUDE
    )


def test_indexing_extra_exclude_is_additive() -> None:
    settings = Settings(
        embedding_url="http://localhost:8088",
        indexing_extra_exclude=["**/private"],
    )

    assert "**/.git" in settings.effective_indexing_exclude
    assert "**/private" in settings.effective_indexing_exclude


def test_surreal_runtime_settings_are_the_only_public_graph_runtime_config() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert "falkordb_url" not in Settings.model_fields
    assert "falkordb_graph_name" not in Settings.model_fields
    assert settings.surreal_retrieval_url == config.DEFAULT_SURREAL_URL
    assert settings.surreal_retrieval_namespace == config.DEFAULT_SURREAL_NAMESPACE


def test_surreal_runtime_defaults_export_surreal_settings() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert settings.surreal_retrieval_url == "http://127.0.0.1:8000"
    assert settings.surreal_retrieval_namespace == "dotmd"
    assert settings.surreal_retrieval_database is None
    assert settings.surreal_retrieval_embedding_dimension is None
    assert settings.surreal_retrieval_vector_index_type == "F32"


def test_surreal_search_backend_vector_index_type_normalizes_and_validates() -> None:
    settings = Settings(
        embedding_url="http://localhost:8088",
        surreal_retrieval_vector_index_type="f16",
    )

    assert settings.surreal_retrieval_vector_index_type == "F16"

    with pytest.raises(ValueError, match="surreal_retrieval_vector_index_type"):
        Settings(
            embedding_url="http://localhost:8088",
            surreal_retrieval_vector_index_type="diskann",
        )


def test_runtime_validation_requires_surreal_runtime_fields() -> None:
    settings = _runtime_settings(surreal_retrieval_database=None)

    with pytest.raises(ValueError, match="surreal_retrieval_database"):
        settings.validate_for_runtime()


def test_runtime_validation_accepts_surreal_runtime_configuration() -> None:
    settings = _runtime_settings(
        surreal_retrieval_url="http://surrealdb:8000",
        surreal_retrieval_database="production",
        surreal_retrieval_embedding_dimension=1024,
    )

    settings.validate_for_runtime()


@pytest.mark.parametrize(
    "overrides",
    [
        {"surreal_retrieval_username": "root"},
        {"surreal_retrieval_password": "secret"},
        {
            "surreal_retrieval_username": "root",
            "surreal_retrieval_password": "secret",
            "surreal_retrieval_access_token": "token",
        },
        {"surreal_retrieval_hnsw_ef": 0},
        {"surreal_retrieval_embedding_shard_count": 0},
    ],
)
def test_runtime_validation_rejects_invalid_surreal_runtime_auth_or_bounds(
    overrides: dict[str, object],
) -> None:
    settings = _runtime_settings(
        surreal_retrieval_url="http://surrealdb:8000",
        surreal_retrieval_database="production",
        surreal_retrieval_embedding_dimension=1024,
        **overrides,
    )

    with pytest.raises(ValueError, match="surreal_retrieval"):
        settings.validate_for_runtime()


@pytest.mark.parametrize(
    ("field", "overrides"),
    [
        ("data_dir", {"data_dir": Path()}),
        ("index_dir", {"index_dir": Path.home() / ".dotmd"}),
        ("indexing_paths", {"indexing_paths": []}),
        ("data_dir", {"data_dir": Path("/data")}),
        ("index_dir", {"index_dir": Path("/tmp/dotmd-index")}),
    ],
)
def test_runtime_validation_rejects_unsafe_deployment_defaults(
    field: str,
    overrides: dict[str, object],
) -> None:
    settings = _runtime_settings(**overrides)

    with pytest.raises(ValueError, match=field):
        settings.validate_for_runtime()


@pytest.mark.parametrize(
    ("field", "overrides"),
    [
        ("data_dir", {"data_dir": Path("data")}),
        ("index_dir", {"index_dir": Path("idx")}),
        ("indexing_paths", {"indexing_paths": ["data"]}),
    ],
)
def test_runtime_validation_rejects_relative_runtime_paths(
    field: str,
    overrides: dict[str, object],
) -> None:
    settings = _runtime_settings(**overrides)

    with pytest.raises(ValueError, match=field):
        settings.validate_for_runtime()


def test_runtime_validation_accepts_absolute_indexing_globs() -> None:
    settings = _runtime_settings(indexing_paths=["/mnt/**/*.md"])

    settings.validate_for_runtime()


def test_runtime_validation_accepts_explicit_deployment_values() -> None:
    settings = _runtime_settings()

    settings.validate_for_runtime()


def test_runtime_loader_forces_surreal_even_if_backend_override_requests_sqlite() -> None:
    settings = load_runtime_settings(
        data_dir=Path("/mnt"),
        index_dir=Path("/dotmd-index"),
        indexing_paths=["/mnt"],
        embedding_url="http://tei:80",
        search_backend="sqlite",
        surreal_retrieval_url="http://surrealdb:8000",
        surreal_retrieval_database="production",
        surreal_retrieval_embedding_dimension=1024,
    )

    assert settings.search_backend == "surreal"


def test_base_url_none_remains_valid() -> None:
    settings = Settings(embedding_url="http://localhost:8088", base_url=None)

    assert settings.base_url is None


def test_service_status_consumes_effective_indexing_exclude() -> None:
    settings = Settings(
        embedding_url="http://localhost:8088",
        indexing_paths=["/mnt"],
        indexing_extra_exclude=["**/private"],
    )
    service: Any = object.__new__(DotMDService)
    service._settings = settings
    service._pipeline = SimpleNamespace(
        metadata_store=SimpleNamespace(get_stats=Mock(return_value=IndexStats())),
        conn=None,
        graph_store=SimpleNamespace(
            node_count=Mock(side_effect=RuntimeError("not needed")),
            edge_count=Mock(side_effect=RuntimeError("not needed")),
        ),
        chunk_tracker=SimpleNamespace(diff=Mock()),
    )
    service._trickle_indexer = SimpleNamespace(
        state=SimpleNamespace(
            status=TrickleStatus.IDLE,
            indexed_count=0,
            total_files=0,
            current_file=None,
            chunks_per_hour=0.0,
            files_per_hour=0.0,
            eta_minutes=None,
        )
    )

    with patch("dotmd.ingestion.reader.discover_files_multi", return_value=[]) as discover:
        service.status()

    discover.assert_called_once_with(settings.indexing_paths, settings.effective_indexing_exclude)
    assert "**/.git" in discover.call_args.args[1]
    assert "**/private" in discover.call_args.args[1]


def test_mcp_stdio_runtime_path_uses_runtime_settings_helper() -> None:
    settings = _runtime_settings()

    with (
        patch("dotmd.mcp_server.load_runtime_settings", return_value=settings) as load_runtime,
        patch("dotmd.mcp_server.DotMDService") as service_cls,
        patch("dotmd.mcp_server.FeedbackStore") as feedback_cls,
    ):
        mcp_server.init_service()

    load_runtime.assert_called_once_with()
    service_cls.assert_called_once_with(settings)
    feedback_cls.assert_called_once_with(settings.index_dir / "feedback.db")


def test_fastapi_runtime_path_uses_runtime_settings_helper() -> None:
    settings = _runtime_settings()

    with (
        patch("dotmd.api.server.load_runtime_settings", return_value=settings) as load_runtime,
        patch("dotmd.api.server.DotMDService") as service_cls,
    ):
        service = service_cls.return_value
        service.warmup.return_value = None
        with TestClient(api_server.app) as client:
            assert client.get("/health").status_code == 200

    load_runtime.assert_called_once_with()
    service_cls.assert_called_once_with(settings)
    service.warmup.assert_called_once_with()
