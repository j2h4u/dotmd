from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from click.testing import CliRunner
from fastapi.testclient import TestClient
from tests.fixtures.surreal_native import apply_surreal_native_retrieval_schema

from dotmd.api.service import DotMDService
from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth, SearchMode
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig


def _pipeline_settings(tmp_path: Path, surreal_db: Path) -> Settings:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        chunk_strategy="contextual_512_50",
        surreal_retrieval_url=f"surrealkv://{surreal_db}",
        surreal_retrieval_database="direct_visibility",
        surreal_retrieval_embedding_dimension=3,
    )


def _index_direct_surreal_fixture(tmp_path: Path) -> tuple[Settings, Path, int, int]:
    surreal_db = tmp_path / "surreal.db"
    settings = _pipeline_settings(tmp_path, surreal_db)
    file_path = settings.data_dir / "surrealcutoversmoke42.md"
    file_path.write_text(
        "surrealcutoversmoke42 proves direct Surreal visibility.\n",
        encoding="utf-8",
    )

    schema_config = SurrealStoreConfig(
        url=f"surrealkv://{surreal_db}",
        database="direct_visibility",
    )
    with SurrealConnection(schema_config) as schema_connection:
        apply_surreal_native_retrieval_schema(
            schema_connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )

    pipeline = IndexingPipeline(settings)
    pipeline._semantic_engine.encode_batch = MagicMock(  # type: ignore[method-assign]
        side_effect=lambda texts: [[1.0, 0.0, 0.0] for _text in texts]
    )
    pipeline._semantic_engine.get_tei_model_id = lambda: "fixture-model"  # type: ignore[method-assign]

    try:
        assert pipeline.index_file(file_path) == 1
        vector_count = pipeline._vector_store.count()
    finally:
        pipeline.close()

    with sqlite3.connect(settings.index_db_path) as conn:
        table_names = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert f"vec_chunks_{pipeline._strategy}{pipeline._model_suffix}" not in table_names
        assert f"chunks_fts_{pipeline._strategy}" not in table_names
        assert conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0] == 1
        assert conn.execute("SELECT COUNT(*) FROM resource_bindings").fetchone()[0] == 1

    fts_count = 0

    return settings, file_path, vector_count, fts_count


def _build_direct_surreal_service(settings: Settings) -> DotMDService:
    service = DotMDService(settings)
    service.warmup = MagicMock()  # type: ignore[method-assign]
    return service


def test_direct_surreal_ingest_is_visible_to_surreal_keyword_search(
    tmp_path: Path,
) -> None:
    _settings, _, vector_count, fts_count = _index_direct_surreal_fixture(tmp_path)

    assert vector_count == 0
    assert fts_count == 0

    # This smoke only proves search visibility; read() still resolves through local metadata.
    with SurrealConnection(
        SurrealStoreConfig(
            url=f"surrealkv://{tmp_path / 'surreal.db'}",
            database="direct_visibility",
        )
    ) as search_connection:
        from dotmd.search.surreal_fts import SurrealFTSSearchEngine

        engine = SurrealFTSSearchEngine(
            search_connection,
            chunk_strategy="contextual_512_50",
        )
        results = engine.search("surrealcutoversmoke42", top_k=5)

    assert len(results) == 1
    assert isinstance(results[0][0], str)


def test_direct_surreal_ingest_is_visible_through_service_keyword_search(
    tmp_path: Path,
) -> None:
    settings, file_path, _, _ = _index_direct_surreal_fixture(tmp_path)
    service = DotMDService(settings)

    try:
        response = service.search(
            "surrealcutoversmoke42",
            top_k=5,
            mode=SearchMode.KEYWORD,
            rerank=False,
            expand=False,
        )
    finally:
        service.close()

    assert response.candidates
    candidate = response.candidates[0]
    assert candidate.ref.startswith(f"filesystem:{file_path.resolve()}")
    assert "surrealcutoversmoke42" in candidate.snippet


def test_direct_surreal_ingest_is_visible_through_api_search_entrypoint(
    tmp_path: Path,
) -> None:
    settings, file_path, _, _ = _index_direct_surreal_fixture(tmp_path)
    service = _build_direct_surreal_service(settings)

    from dotmd.api import server

    try:
        with pytest.MonkeyPatch.context() as monkeypatch:
            monkeypatch.setattr(server, "load_runtime_settings", lambda: settings)
            monkeypatch.setattr(server, "DotMDService", lambda _settings: service)
            with TestClient(server.app) as client:
                response = client.get(
                    "/search?q=surrealcutoversmoke42&mode=keyword&rerank=false&expand=false"
                )
    finally:
        service.close()

    assert response.status_code == 200
    payload = response.json()
    assert payload["count"] == 1
    assert payload["results"][0]["ref"].startswith(f"filesystem:{file_path.resolve()}")
    assert "surrealcutoversmoke42" in payload["results"][0]["snippet"]


def test_direct_surreal_ingest_is_visible_through_cli_search_entrypoint(
    tmp_path: Path,
) -> None:
    settings, file_path, _, _ = _index_direct_surreal_fixture(tmp_path)
    service = _build_direct_surreal_service(settings)

    from unittest.mock import patch

    from dotmd.cli import main

    try:
        with (
            patch("dotmd.cli.load_settings", return_value=settings),
            patch("dotmd.cli.DotMDService", return_value=service),
        ):
            result = CliRunner().invoke(
                main,
                [
                    "--index-dir",
                    str(settings.index_dir),
                    "search",
                    "surrealcutoversmoke42",
                    "--mode",
                    "keyword",
                    "--no-rerank",
                    "--no-expand",
                ],
            )
    finally:
        service.close()

    assert result.exit_code == 0, result.output
    assert f"filesystem:{file_path.resolve()}" in result.output
    assert "surrealcutoversmoke42" in result.output


def test_direct_surreal_ingest_is_visible_through_mcp_search_tool(
    tmp_path: Path,
) -> None:
    settings, file_path, _, _ = _index_direct_surreal_fixture(tmp_path)
    service = _build_direct_surreal_service(settings)

    import asyncio
    from types import SimpleNamespace

    import dotmd.mcp_server as mcp

    reranker = MagicMock()
    reranker.model_name = "fixture-reranker"
    reranker.warmup = MagicMock()
    reranker.rerank = MagicMock(
        side_effect=lambda *args, **kwargs: [
            (chunk_id, 1.0 - (index * 0.01))
            for index, chunk_id in enumerate(args[1][: kwargs.get("top_k", len(args[1]))])
        ]
    )
    service._semantic_engine.search = MagicMock(return_value=[])  # type: ignore[method-assign]
    service._graph_direct_engine.search = MagicMock(return_value=[])  # type: ignore[method-assign]
    service._query_expander.expand = MagicMock(  # type: ignore[method-assign]
        return_value=SimpleNamespace(expanded_text="")
    )
    service._reranker_factory.get = MagicMock(return_value=reranker)  # type: ignore[method-assign]
    previous_service = mcp._service
    mcp._service = service

    try:
        _content, structured_raw = asyncio.run(
            mcp.mcp.call_tool("search", {"query": "surrealcutoversmoke42", "top_k": 5})
        )
    finally:
        mcp._service = previous_service
        service.close()

    payload = structured_raw if isinstance(structured_raw, dict) else structured_raw.model_dump()
    assert payload["candidates"]
    assert payload["candidates"][0]["ref"].startswith(f"filesystem:{file_path.resolve()}")
    assert "surrealcutoversmoke42" in payload["candidates"][0]["snippet"]
