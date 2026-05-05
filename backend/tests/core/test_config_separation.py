"""Settings boundary tests for operator config and internal defaults."""

from pathlib import Path
from typing import Any

import pytest

from dotmd.core import config
from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth


def _runtime_settings(**overrides: object) -> Settings:
    values: dict[str, Any] = {
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
        "graph_backend": "falkordb",
        "falkordb_url": "redis://falkordb:6379",
    }
    values.update(overrides)
    return Settings(**values)


def test_settings_still_constructs_with_current_defaults() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert settings.embedding_url == "http://localhost:8088"
    assert settings.data_dir == Path(".")
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


def test_default_falkordb_url_is_exported() -> None:
    assert config.DEFAULT_FALKORDB_URL == "redis://localhost:6379"


@pytest.mark.parametrize(
    ("field", "overrides"),
    [
        ("data_dir", {"data_dir": Path(".")}),
        ("index_dir", {"index_dir": Path.home() / ".dotmd"}),
        ("indexing_paths", {"indexing_paths": []}),
    ],
)
def test_runtime_validation_rejects_unsafe_deployment_defaults(
    field: str,
    overrides: dict[str, object],
) -> None:
    settings = _runtime_settings(**overrides)

    with pytest.raises(ValueError, match=field):
        settings.validate_for_runtime()


def test_runtime_validation_accepts_explicit_deployment_values() -> None:
    settings = _runtime_settings()

    settings.validate_for_runtime()


@pytest.mark.parametrize("falkordb_url", ["", config.DEFAULT_FALKORDB_URL])
def test_runtime_validation_rejects_missing_or_default_falkordb_url(
    falkordb_url: str,
) -> None:
    settings = _runtime_settings(falkordb_url=falkordb_url)

    with pytest.raises(ValueError, match="falkordb_url"):
        settings.validate_for_runtime()


@pytest.mark.parametrize("falkordb_url", ["", config.DEFAULT_FALKORDB_URL])
def test_runtime_validation_allows_ladybugdb_without_falkordb_url(
    falkordb_url: str,
) -> None:
    settings = _runtime_settings(
        graph_backend="ladybugdb",
        falkordb_url=falkordb_url,
    )

    settings.validate_for_runtime()


def test_base_url_none_remains_valid() -> None:
    settings = Settings(embedding_url="http://localhost:8088", base_url=None)

    assert settings.base_url is None
