from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _settings(tmp_path: Path):  # type: ignore[no-untyped-def]
    from dotmd.core.config import Settings

    return Settings(
        index_dir=tmp_path,
        embedding_url="http://localhost:8088",
        embedding_model="intfloat/multilingual-e5-large",
        telegram_daemon_socket=None,
    )


def _backend_root() -> Path:
    return Path(__file__).resolve().parents[2]


def test_build_surreal_native_engine_overrides_uses_phase42_engine_contract(
    tmp_path: Path,
) -> None:
    from dotmd.search.surreal_fts import SurrealFTSSearchEngine
    from dotmd.search.surreal_graph import SurrealGraphDirectEngine
    from dotmd.search.surreal_native import build_surreal_native_engine_overrides
    from dotmd.search.surreal_vector import SurrealVectorSearchEngine

    settings = _settings(tmp_path)

    overrides = build_surreal_native_engine_overrides(
        MagicMock(),
        settings,
        embedding_dimension=1024,
    )

    assert set(overrides) == {"semantic", "keyword", "graph_direct"}
    assert isinstance(overrides["keyword"], SurrealFTSSearchEngine)
    assert isinstance(overrides["graph_direct"], SurrealGraphDirectEngine)
    assert isinstance(overrides["semantic"], SurrealVectorSearchEngine)
    assert overrides["semantic"]._embedding_dimension == 1024
    assert overrides["semantic"]._hnsw_ef == 40
    assert overrides["semantic"]._model_name == settings.embedding_model
    assert overrides["semantic"]._embedding_url == settings.embedding_url
    assert overrides["semantic"]._tei_batch_size == settings.tei_batch_size
    assert overrides["semantic"]._use_prefix is settings.needs_embedding_prefix
    assert overrides["semantic"]._query_instruction == settings.query_instruction


def test_build_surreal_native_engine_overrides_uses_vector_engine_bounds_validation(
    tmp_path: Path,
) -> None:
    from dotmd.search.surreal_native import build_surreal_native_engine_overrides

    connection = MagicMock()
    settings = _settings(tmp_path)

    overrides = build_surreal_native_engine_overrides(
        connection,
        settings,
        embedding_dimension=1024,
        hnsw_ef=9,
    )

    with pytest.raises(ValueError, match="hnsw_ef"):
        overrides["semantic"].search("surreal retrieval", top_k=5)

    connection.query.assert_not_called()


def test_surreal_hybrid_builder_stays_out_of_runtime_cutover_and_builtin_hybrid_helpers() -> None:
    import dotmd.search.surreal_native as surreal_native

    source = inspect.getsource(surreal_native)

    assert "search::rrf" not in source
    assert "search::hybrid" not in source
    assert "SurrealRetrievalCapabilityReport" not in source


def test_phase42_keeps_capability_probe_out_of_runtime_entrypoints() -> None:
    backend_root = _backend_root()

    for relative_path in (
        "src/dotmd/api/service.py",
        "src/dotmd/cli.py",
        "src/dotmd/mcp_server.py",
        "src/dotmd/core/config.py",
    ):
        source = (backend_root / relative_path).read_text(encoding="utf-8")
        assert "SurrealRetrievalCapabilityReport" not in source
