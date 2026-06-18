from __future__ import annotations

import pytest

from dotmd.core.config import Settings

pytestmark = pytest.mark.real_schema_check


def test_search_backend_defaults_to_legacy() -> None:
    settings = Settings(embedding_url="http://localhost:8088")

    assert settings.search_backend == "legacy"
    assert settings.surreal_vector_index_name == "embeddings_vector_hnsw"
    assert settings.surreal_vector_ef == 80
    assert settings.surreal_query_timeout_seconds == 30


def test_search_backend_can_be_set_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DOTMD_SEARCH_BACKEND", "surreal")
    monkeypatch.setenv("DOTMD_SURREAL_VECTOR_EF", "200")
    monkeypatch.setenv("DOTMD_SURREAL_QUERY_TIMEOUT_SECONDS", "45")

    settings = Settings(embedding_url="http://localhost:8088")

    assert settings.search_backend == "surreal"
    assert settings.surreal_vector_ef == 200
    assert settings.surreal_query_timeout_seconds == 45
