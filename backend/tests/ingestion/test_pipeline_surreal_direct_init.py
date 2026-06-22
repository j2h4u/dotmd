from __future__ import annotations

from pathlib import Path

from dotmd.core.config import Settings
from dotmd.core.models import ExtractDepth
from dotmd.ingestion.pipeline import IndexingPipeline
from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
from tests.fixtures.surreal_native import apply_surreal_native_retrieval_schema


def _direct_ingest_settings(tmp_path: Path) -> tuple[Settings, Path]:
    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    data_dir.mkdir()
    index_dir.mkdir()
    surreal_db = tmp_path / "surreal.db"
    settings = Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        chunk_strategy="contextual_512_50",
        surreal_retrieval_url=f"surrealkv://{surreal_db}",
        surreal_retrieval_database="direct_init",
        surreal_retrieval_embedding_dimension=3,
    )
    file_path = settings.data_dir / "directinitsmoke.md"
    file_path.write_text(
        "directinitsmoke proves direct ingest keeps local search artifacts out.\n",
        encoding="utf-8",
    )
    with SurrealConnection(
        SurrealStoreConfig(
            url=f"surrealkv://{surreal_db}",
            database="direct_init",
        )
    ) as schema_connection:
        apply_surreal_native_retrieval_schema(
            schema_connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )
    return settings, file_path


def test_direct_surreal_pipeline_init_skips_legacy_vec_and_fts(
    tmp_path: Path,
) -> None:
    settings, file_path = _direct_ingest_settings(tmp_path)
    pipeline = IndexingPipeline(settings)
    pipeline._semantic_engine.encode_batch = lambda texts: [  # type: ignore[method-assign]
        [1.0, 0.0, 0.0] for _text in texts
    ]
    pipeline._semantic_engine.get_tei_model_id = lambda: "fixture-model"  # type: ignore[method-assign]

    try:
        assert pipeline.index_file(file_path) == 1
        assert pipeline._vector_store.count() == 0

        tables = {
            row[0]
            for row in pipeline.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        }
        assert not any(name.startswith("vec_chunks_") for name in tables)
        assert not any(name.startswith("vec_meta_") for name in tables)
        assert f"chunks_fts_{pipeline._strategy}" not in tables

        assert pipeline.conn.execute("SELECT COUNT(*) FROM source_documents").fetchone()[0] == 1
        assert pipeline.conn.execute("SELECT COUNT(*) FROM resource_bindings").fetchone()[0] == 1
    finally:
        pipeline.close()


def test_direct_surreal_pipeline_internal_accessors_are_initialized(tmp_path: Path) -> None:
    settings, _file_path = _direct_ingest_settings(tmp_path)
    pipeline = IndexingPipeline(settings)

    try:
        assert pipeline.vector_store is pipeline._vector_store
        assert pipeline.keyword_engine is pipeline._keyword_engine
        assert pipeline.graph_store is pipeline._graph_store
    finally:
        pipeline.close()
