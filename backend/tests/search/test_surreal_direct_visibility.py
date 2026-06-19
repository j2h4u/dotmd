from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

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
        search_backend="surreal",
        chunk_strategy="contextual_512_50",
        surreal_retrieval_url=f"surrealkv://{surreal_db}",
        surreal_retrieval_database="direct_visibility",
        surreal_retrieval_embedding_dimension=3,
    )


def _index_direct_surreal_fixture(tmp_path: Path) -> tuple[Settings, Path]:
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
    finally:
        pipeline.close()

    return settings, file_path


def test_direct_surreal_ingest_is_visible_to_surreal_keyword_search(
    tmp_path: Path,
) -> None:
    _settings, _ = _index_direct_surreal_fixture(tmp_path)

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
    settings, file_path = _index_direct_surreal_fixture(tmp_path)
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
