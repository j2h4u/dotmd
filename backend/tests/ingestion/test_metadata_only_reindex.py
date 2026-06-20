"""End-to-end invariant: metadata-only change triggers exactly 1 TEI call (Phase 999.12).

This is the core correctness guarantee of Phase 999.12:
  tag update → 1 encode_batch call (for e_meta), NOT N calls (one per chunk).

No live TEI required — encode_batch is mocked.
"""

import pathlib
from datetime import UTC, datetime
from typing import Any, cast
from unittest.mock import MagicMock

import pytest


def _write_md(path: pathlib.Path, title: str, tags: list, body: str) -> None:
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else ""
    tags_section = f"tags:\n{tags_yaml}\n" if tags else ""
    path.write_text(
        f"---\ntitle: {title}\n{tags_section}kind: document\n---\n{body}",
        encoding="utf-8",
    )


def _vector_chunk_ids(pipeline) -> set[str]:  # type: ignore[no-untyped-def]
    return {
        row[0]
        for row in pipeline._conn.execute(
            f"SELECT chunk_id FROM {pipeline._vector_store._META_TABLE}"
        ).fetchall()
    }


def _chunk_ids_for_path(pipeline, path: pathlib.Path) -> list[str]:  # type: ignore[no-untyped-def]
    return pipeline._metadata_store.get_chunk_ids_by_file(
        pipeline._strategy,
        str(path),
    )


def _vector_blob_for_chunk(pipeline, chunk_id: str) -> bytes:  # type: ignore[no-untyped-def]
    row = pipeline._conn.execute(
        f"""
        SELECT v.embedding
        FROM {pipeline._vector_store._VEC_TABLE} v
        JOIN {pipeline._vector_store._META_TABLE} m ON m.rowid = v.rowid
        WHERE m.chunk_id = ?
        """,
        (chunk_id,),
    ).fetchone()
    assert row is not None
    return row[0]


def _fts_meta_for_chunk(pipeline, chunk_id: str) -> tuple[str, str]:  # type: ignore[no-untyped-def]
    row = pipeline._conn.execute(
        f"SELECT title, tags FROM {pipeline._fts_table} WHERE chunk_id = ?",
        (chunk_id,),
    ).fetchone()
    assert row is not None
    return row[0], row[1]


def _graph_node(pipeline, node_id: str) -> dict | None:  # type: ignore[no-untyped-def]
    for node in pipeline._graph_store.get_graph_data()["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def _graph_edges_from(pipeline, source_id: str, relation_type: str) -> list[dict]:  # type: ignore[no-untyped-def]
    return [
        edge
        for edge in pipeline._graph_store.get_graph_data()["edges"]
        if edge["source"] == source_id and edge["relation_type"] == relation_type
    ]


def _make_pipeline_with_directional_vectors(settings):  # type: ignore[no-untyped-def]
    from dotmd.ingestion.pipeline import IndexingPipeline

    def mock_encode_batch(texts):  # type: ignore[no-untyped-def]
        vectors = []
        for text in texts:
            if "Updated" in text or "beta" in text:
                vectors.append([0.0, 0.0, 1.0, 0.0])
            elif "Initial" in text or "alpha" in text:
                vectors.append([0.0, 1.0, 0.0, 0.0])
            else:
                vectors.append([1.0, 0.0, 0.0, 0.0])
        return vectors

    pipeline = IndexingPipeline(settings)
    mock_engine = MagicMock()
    mock_engine.encode_batch = mock_encode_batch
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine
    return pipeline


@pytest.fixture
def pipeline_settings(tmp_path):
    from dotmd.core.config import Settings
    from dotmd.core.models import ExtractDepth

    data_dir = tmp_path / "data"
    data_dir.mkdir()
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    return Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        embedding_weights="text=0.7,meta=0.3",
    )


@pytest.fixture
def surreal_pipeline_settings(pipeline_settings):
    return pipeline_settings.model_copy(
        update={
            "search_backend": "surreal",
            "surreal_retrieval_url": "http://surrealdb:8000",
            "surreal_retrieval_namespace": "dotmd",
            "surreal_retrieval_database": "phase46_direct_ingest",
            "surreal_retrieval_username": "root",
            "surreal_retrieval_password": "root",
            "surreal_retrieval_access_token": None,
            "surreal_retrieval_embedding_dimension": 768,
        }
    )


def test_metadata_only_reindex_exactly_one_tei_call(pipeline_settings):
    """After initial index, a tag-only change triggers exactly 1 encode_batch call.

    Phase 999.12 invariant: metadata-only fast path reads stored e_text BLOBs,
    calls encode_batch once for e_meta, recomputes e_fused locally.
    This test proves the O(1) TEI call property.

    PRECONDITION (addresses Codex HIGH review concern, Cycle 2):
    This invariant holds ONLY in steady-state: after a successful initial full index
    where e_text BLOBs for all chunks are stored in VecComponentStore.

    It does NOT hold in the following cases:
    - First run after schema version wipe (e_text BLOBs missing → fallback to full embed)
    - Fresh install with no prior index

    In those cases, the fast path detects missing e_text BLOBs and falls back to
    full re-embedding for the missing chunks (N+1 TEI calls instead of 1).
    This fallback is correct behavior, not a bug.

    Separate test `test_metadata_only_with_missing_etext_falls_back_to_full_embed`
    in test_pipeline_metadata.py covers the fallback path.
    """
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = pipeline_settings.data_dir / "test.md"
    _write_md(doc, "Test Document", ["alpha"], "This is the body text of the document.")

    dummy_vec = [0.1] * 768
    encode_calls = []

    def mock_encode_batch(texts):
        encode_calls.append(list(texts))
        return [dummy_vec[:] for _ in texts]

    pipeline = IndexingPipeline(pipeline_settings)
    mock_engine = MagicMock()
    mock_engine.encode_batch = mock_encode_batch
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine

    # Steady-state precondition: initial full index must complete successfully,
    # storing e_text BLOBs in VecComponentStore for all chunks.
    encode_calls.clear()
    pipeline.index(pipeline_settings.data_dir)
    assert len(encode_calls) >= 1, "Initial index must call encode_batch at least once"

    # Verify precondition: VecComponentStore has e_text entries after initial index
    assert pipeline._vec_components.count() > 0, (
        "Precondition failed: VecComponentStore must have e_text entries after initial index. "
        "The 1-TEI-call invariant only holds in steady-state."
    )

    # Metadata-only change: add tags, body unchanged
    _write_md(
        doc, "Test Document", ["alpha", "beta", "gamma"], "This is the body text of the document."
    )

    encode_calls.clear()
    pipeline.index(pipeline_settings.data_dir)

    # THE INVARIANT (steady-state only — see precondition note above)
    assert len(encode_calls) == 1, (
        f"Metadata-only change MUST trigger exactly 1 encode_batch call (for e_meta). "
        f"Got {len(encode_calls)} calls: {encode_calls}. "
        f"Precondition: this test verifies steady-state behavior after initial index. "
        f"For post-wipe behavior, see test_metadata_only_with_missing_etext_falls_back_to_full_embed."
    )
    assert len(encode_calls[0]) == 1, (
        f"The single encode_batch call MUST encode exactly 1 text (the meta string title+tags). "
        f"Got {len(encode_calls[0])} texts: {encode_calls[0]}"
    )


def test_surreal_backend_uses_noop_graph_store(
    surreal_pipeline_settings, monkeypatch
):
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    class FakeConnection:
        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    monkeypatch.setattr(
        pipeline_module,
        "_create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)

    assert pipeline._graph_store.node_count() == 0
    assert pipeline._graph_store.get_graph_data() == {"nodes": [], "edges": []}


def test_surreal_metadata_only_reindex_skips_local_vec_and_fts_artifacts(
    tmp_path, monkeypatch
):
    from dotmd.core.config import Settings
    from dotmd.core.models import ExtractDepth
    from dotmd.ingestion.pipeline import IndexingPipeline
    from dotmd.storage.surreal import SurrealConnection, SurrealStoreConfig
    from tests.fixtures.surreal_native import apply_surreal_native_retrieval_schema

    data_dir = tmp_path / "data"
    index_dir = tmp_path / "index"
    surreal_db = tmp_path / "surreal.db"
    data_dir.mkdir()
    index_dir.mkdir()

    settings = Settings(
        data_dir=data_dir,
        index_dir=index_dir,
        embedding_url="http://localhost:18088",
        indexing_paths=[str(data_dir)],
        extract_depth=ExtractDepth.STRUCTURAL,
        search_backend="surreal",
        chunk_strategy="contextual_512_50",
        surreal_retrieval_url=f"surrealkv://{surreal_db}",
        surreal_retrieval_database="metadata_only_visibility",
        surreal_retrieval_embedding_dimension=3,
    )

    doc = data_dir / "surreal.md"
    _write_md(doc, "Surreal Doc", ["alpha"], "Initial body text for surreal metadata-only smoke.")

    schema_config = SurrealStoreConfig(
        url=f"surrealkv://{surreal_db}",
        database="metadata_only_visibility",
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
        assert pipeline.index_file(doc) == 1
        assert pipeline._vector_store.count() == 0
        assert (
            pipeline._conn.execute(f"SELECT COUNT(*) FROM {pipeline._fts_table}").fetchone()[0]
            == 0
        )

        _write_md(
            doc,
            "Surreal Doc",
            ["alpha", "beta"],
            "Initial body text for surreal metadata-only smoke.",
        )
        pipeline.index_file(doc)
        assert pipeline._vector_store.count() == 0
        assert (
            pipeline._conn.execute(f"SELECT COUNT(*) FROM {pipeline._fts_table}").fetchone()[0]
            == 0
        )
    finally:
        pipeline.close()


def test_surreal_reindex_vectors_skips_local_vector_store_mutation(
    surreal_pipeline_settings, monkeypatch
):
    from dotmd.core.models import Chunk, ChunkProvenance
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = surreal_pipeline_settings.data_dir / "surreal-vectors.md"
    _write_md(doc, "Surreal Vectors", ["alpha"], "Initial body text for vector reindexing.")

    class FakeConnection:
        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    monkeypatch.setattr(
        "dotmd.ingestion.pipeline._create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)
    pipeline._semantic_engine.encode_batch = MagicMock(  # type: ignore[method-assign]
        return_value=[[1.0, 0.0, 0.0]]
    )
    pipeline._semantic_engine.get_tei_model_id = MagicMock(return_value="fixture-model")
    pipeline._write_surreal_direct_manifest = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )
    pipeline._write_surreal_graph_manifest = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )

    try:
        assert pipeline.index_file(doc) == 1

        legacy_path = surreal_pipeline_settings.data_dir / "legacy-vector.md"
        legacy_chunk = Chunk(
            chunk_id="legacy-vector-chunk",
            file_paths=[legacy_path],
            heading_hierarchy=["Legacy Vector"],
            level=1,
            text="Legacy vector body text.",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(legacy_path.resolve()),
                ref=f"filesystem:{legacy_path.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        )
        pipeline._vector_store.add_chunks(
            [legacy_chunk],
            [[0.9, 0.1, 0.0]],
            overwrite=False,
            text_hashes={legacy_chunk.chunk_id: "legacy-text-hash"},
        )
        pipeline._vec_components.store(legacy_chunk.chunk_id, "text", [0.9, 0.1, 0.0])
        pipeline._vec_components.store(str(legacy_path.resolve()), "meta", [0.2, 0.3, 0.5])
        pipeline._conn.commit()

        vector_meta_table = pipeline._vector_store._META_TABLE
        vec_components_table = pipeline._vec_components._TABLE
        vector_row_count = pipeline._vector_store.count()
        vec_component_row_count = pipeline._vec_components.count()
        legacy_vector_row_count = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM {vector_meta_table} WHERE chunk_id = ?",
            (legacy_chunk.chunk_id,),
        ).fetchone()[0]
        legacy_component_row_count = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM {vec_components_table} WHERE entity_id IN (?, ?)",
            (legacy_chunk.chunk_id, str(legacy_path.resolve())),
        ).fetchone()[0]

        monkeypatch.setattr(
            pipeline._vector_store,
            "delete_all",
            MagicMock(side_effect=lambda *args, **kwargs: pytest.fail("vector delete_all must not run")),
        )
        monkeypatch.setattr(
            pipeline._vector_store,
            "add_chunks",
            MagicMock(side_effect=lambda *args, **kwargs: pytest.fail("vector add_chunks must not run")),
        )
        monkeypatch.setattr(
            pipeline._vec_components,
            "delete_all",
            MagicMock(side_effect=lambda *args, **kwargs: pytest.fail("vec_components delete_all must not run")),
        )
        monkeypatch.setattr(
            pipeline._semantic_engine,
            "encode_batch",
            MagicMock(side_effect=lambda *args, **kwargs: pytest.fail("TEI encode must not run")),
        )

        assert pipeline.reindex_vectors() == 0

        pipeline._vector_store.delete_all.assert_not_called()
        pipeline._vector_store.add_chunks.assert_not_called()
        pipeline._vec_components.delete_all.assert_not_called()
        assert pipeline._vector_store.count() == vector_row_count
        assert pipeline._vec_components.count() == vec_component_row_count
        assert (
            pipeline._conn.execute(
                f"SELECT COUNT(*) FROM {vector_meta_table} WHERE chunk_id = ?",
                (legacy_chunk.chunk_id,),
            ).fetchone()[0]
            == legacy_vector_row_count
        )
        assert (
            pipeline._conn.execute(
                f"SELECT COUNT(*) FROM {vec_components_table} WHERE entity_id IN (?, ?)",
                (legacy_chunk.chunk_id, str(legacy_path.resolve())),
            ).fetchone()[0]
            == legacy_component_row_count
        )
    finally:
        pipeline.close()


def test_surreal_reindex_fts5_skips_local_fts_mutation(surreal_pipeline_settings, monkeypatch):
    from dotmd.core.models import Chunk, ChunkProvenance
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = surreal_pipeline_settings.data_dir / "surreal-fts.md"
    _write_md(doc, "Surreal FTS", ["alpha"], "Initial body text for FTS reindexing.")

    class FakeConnection:
        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    monkeypatch.setattr(
        "dotmd.ingestion.pipeline._create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)
    pipeline._semantic_engine.encode_batch = MagicMock(  # type: ignore[method-assign]
        return_value=[[1.0, 0.0, 0.0]]
    )
    pipeline._semantic_engine.get_tei_model_id = MagicMock(return_value="fixture-model")
    pipeline._write_surreal_direct_manifest = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )
    pipeline._write_surreal_graph_manifest = (  # type: ignore[method-assign]
        lambda *_args, **_kwargs: None
    )

    try:
        assert pipeline.index_file(doc) == 1

        legacy_path = surreal_pipeline_settings.data_dir / "legacy-fts.md"
        legacy_chunk = Chunk(
            chunk_id="legacy-fts-chunk",
            file_paths=[legacy_path],
            heading_hierarchy=["Legacy FTS"],
            level=1,
            text="Legacy FTS body text.",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(legacy_path.resolve()),
                ref=f"filesystem:{legacy_path.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        )
        pipeline._keyword_engine.add_chunks(
            [legacy_chunk],
            file_meta={str(legacy_path.resolve()): ("Legacy FTS", "legacy")},
        )
        pipeline._conn.commit()

        fts_row_count = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM {pipeline._fts_table}"
        ).fetchone()[0]
        legacy_fts_row_count = pipeline._conn.execute(
            f"SELECT COUNT(*) FROM {pipeline._fts_table} WHERE chunk_id = ?",
            (legacy_chunk.chunk_id,),
        ).fetchone()[0]

        monkeypatch.setattr(
            pipeline._keyword_engine,
            "add_chunks",
            MagicMock(side_effect=lambda *args, **kwargs: pytest.fail("FTS add_chunks must not run")),
        )

        assert pipeline.reindex_fts5() == 0

        pipeline._keyword_engine.add_chunks.assert_not_called()
        assert (
            pipeline._conn.execute(f"SELECT COUNT(*) FROM {pipeline._fts_table}").fetchone()[0]
            == fts_row_count
        )
        assert (
            pipeline._conn.execute(
                f"SELECT COUNT(*) FROM {pipeline._fts_table} WHERE chunk_id = ?",
                (legacy_chunk.chunk_id,),
            ).fetchone()[0]
            == legacy_fts_row_count
        )
    finally:
        pipeline.close()


def test_index_file_embed_routes_surreal_manifests_with_complete_text_hashes(
    surreal_pipeline_settings, monkeypatch
):
    from blake3 import blake3

    from dotmd.core.models import Chunk, ChunkProvenance
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline
    from dotmd.ingestion.reader import file_info_from_path

    doc = surreal_pipeline_settings.data_dir / "surreal.md"
    _write_md(doc, "Initial Title", ["alpha"], "Shared body text.")

    class FakeConnection:
        def __init__(self) -> None:
            self.closed = False

        def close(self) -> None:
            self.closed = True

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    run_calls: list[tuple[object, object, object]] = []

    monkeypatch.setattr(
        pipeline_module,
        "_create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )
    monkeypatch.setattr(
        pipeline_module,
        "run_surreal_delta_sync",
        lambda manifest, writer, state: run_calls.append((manifest, writer, state)),
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)
    assert pipeline._surreal_direct_writer is not None
    assert pipeline._surreal_direct_writer.connection.closed is False

    file_info = file_info_from_path(doc)
    assert file_info is not None
    chunks = [
        Chunk(
            chunk_id="surreal-chunk-0",
            file_paths=[doc],
            heading_hierarchy=["Initial Title", "Overview"],
            level=2,
            text="shared body zero",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(doc.resolve()),
                ref=f"filesystem:{doc.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
        Chunk(
            chunk_id="surreal-chunk-1",
            file_paths=[doc],
            heading_hierarchy=["Initial Title", "Details"],
            level=2,
            text="shared body one",
            chunk_index=1,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(doc.resolve()),
                ref=f"filesystem:{doc.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
    ]

    monkeypatch.setattr(
        pipeline,
        "_embed_chunks",
        lambda _chunks: (
            [[0.1, 0.2], [0.3, 0.4]],
            {
                "surreal-chunk-0": blake3(b"shared body zero").hexdigest(),
                "surreal-chunk-1": blake3(b"shared body one").hexdigest(),
            },
        ),
    )
    monkeypatch.setattr(pipeline, "_embed_meta_component", lambda _file_info: [1.0, 1.0])
    monkeypatch.setattr(
        pipeline,
        "_fuse_vectors",
        lambda e_text, e_meta, _weights: [e_text[0] + e_meta[0], e_text[1] + e_meta[1]],
    )

    pipeline._index_file_embed(
        file_info,
        chunks,
        body_changed=True,
        metadata_changed=True,
    )

    assert len(run_calls) == 1
    first_manifest = run_calls[0][0]
    assert [row.row["chunk_id"] for row in first_manifest.embeddings.rows] == [
        "surreal-chunk-0",
        "surreal-chunk-1",
    ]
    assert [row.row["text_hash"] for row in first_manifest.embeddings.rows] == [
        blake3(b"shared body zero").hexdigest(),
        blake3(b"shared body one").hexdigest(),
    ]
    assert [[round(value, 6) for value in row.row["vector"]] for row in first_manifest.embeddings.rows] == [
        [1.1, 1.2],
        [1.3, 1.4],
    ]

    _write_md(doc, "Updated Title", ["alpha", "beta"], "Shared body text.")
    updated_file_info = file_info_from_path(doc)
    assert updated_file_info is not None

    monkeypatch.setattr(
        pipeline,
        "_embed_chunks",
        lambda *_args, **_kwargs: pytest.fail("metadata-only cached path must not re-embed"),
    )

    pipeline._index_file_embed(
        updated_file_info,
        chunks,
        body_changed=False,
        metadata_changed=True,
    )

    assert len(run_calls) == 2
    second_manifest = run_calls[1][0]
    assert [row.row["chunk_id"] for row in second_manifest.embeddings.rows] == [
        "surreal-chunk-0",
        "surreal-chunk-1",
    ]
    assert [row.row["text_hash"] for row in second_manifest.embeddings.rows] == [
        blake3(b"shared body zero").hexdigest(),
        blake3(b"shared body one").hexdigest(),
    ]
    assert [[round(value, 6) for value in row.row["vector"]] for row in second_manifest.embeddings.rows] == [
        [1.1, 1.2],
        [1.3, 1.4],
    ]

    pipeline.close()
    assert pipeline._surreal_direct_writer.connection.closed is True


def test_extract_and_populate_graph_emits_surreal_graph_manifest(
    surreal_pipeline_settings,
    monkeypatch,
) -> None:
    from dotmd.core.models import (
        Chunk,
        ChunkProvenance,
        Entity,
        ExtractionResult,
        FileInfo,
        Relation,
    )
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    class FakeConnection:
        def close(self) -> None:
            pass

    class FakeWriter:
        def __init__(self) -> None:
            self.connection = FakeConnection()

    monkeypatch.setattr(
        pipeline_module,
        "_create_surreal_direct_writer",
        lambda _settings: FakeWriter(),
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)
    doc_path = surreal_pipeline_settings.data_dir / "graph.md"
    file_info = FileInfo(
        path=doc_path,
        title="Graph note",
        last_modified=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        size_bytes=2048,
        kind="meeting_transcript",
        frontmatter={
            "tags": ["alpha"],
            "participants": ["Carol"],
        },
    )
    chunks = [
        Chunk(
            chunk_id="graph-chunk-0",
            file_paths=[doc_path],
            heading_hierarchy=["Graph note", "Overview"],
            level=2,
            text="Carol and Beta discussed the roadmap.",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(doc_path.resolve()),
                ref=f"filesystem:{doc_path.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        )
    ]
    extraction = ExtractionResult(
        entities=[
            Entity(name="Beta", type="person", source="ner", chunk_ids=["graph-chunk-0"]),
            Entity(name="Alpha", type="tag", source="structural", chunk_ids=["graph-chunk-0"]),
        ],
        relations=[
            Relation(
                source_id="graph-chunk-0",
                target_id="Beta",
                relation_type="MENTIONS",
                weight=1.0,
            ),
            Relation(
                source_id="graph-chunk-0",
                target_id="Alpha",
                relation_type="HAS_TAG",
                weight=1.0,
            ),
        ],
    )
    extraction_bundle = pipeline_module._ExtractionBundle(
        entities=extraction.entities,
        relations=extraction.relations,
        total_entities=len(extraction.entities),
        total_relations=len(extraction.relations),
    )

    capture: dict[str, object] = {}
    monkeypatch.setattr(pipeline, "_run_extraction", lambda _chunks: extraction_bundle)
    monkeypatch.setattr(
        pipeline,
        "_populate_graph",
        lambda *args, **kwargs: pytest.fail("surreal graph path must not call Falkor"),
    )
    monkeypatch.setattr(
        pipeline,
        "_frontmatter_to_graph",
        lambda *args, **kwargs: pytest.fail("surreal graph path must not call Falkor"),
    )
    monkeypatch.setattr(
        pipeline,
        "_write_surreal_direct_manifest",
        lambda manifest: capture.setdefault("manifest", manifest),
    )

    result = pipeline._extract_and_populate_graph([file_info], chunks, "run-graph")

    assert result.total_entities == extraction_bundle.total_entities
    assert result.total_relations == extraction_bundle.total_relations
    manifest = cast(Any, capture["manifest"])
    graph_rows = manifest.graph.rows
    assert graph_rows
    assert manifest.graph.deferred is False
    assert [row.table for row in graph_rows].count("files") == 1
    assert [row.table for row in graph_rows].count("sections") == 1
    assert [row.table for row in graph_rows].count("entities") == 2
    assert [row.table for row in graph_rows].count("tags") == 2
    assert [row.table for row in graph_rows].count("relations") == 5
    assert {row.ref for row in graph_rows} == {
        str(doc_path),
        "graph-chunk-0",
        "Beta",
        "Carol",
        "alpha",
        "Alpha",
        f"{doc_path}\x1falpha\x1fHAS_TAG",
        f"{doc_path}\x1fCarol\x1fHAS_PARTICIPANT",
        f"{doc_path}\x1fgraph-chunk-0\x1fCONTAINS",
        "graph-chunk-0\x1fBeta\x1fMENTIONS",
        "graph-chunk-0\x1fAlpha\x1fHAS_TAG",
    }


def test_extract_and_populate_graph_keeps_default_sqlite_path(
    pipeline_settings,
    monkeypatch,
) -> None:
    from dotmd.core.models import (
        Chunk,
        ChunkProvenance,
        Entity,
        ExtractionResult,
        FileInfo,
        Relation,
    )
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(pipeline_settings)
    file_path = pipeline_settings.data_dir / "graph.md"
    file_info = FileInfo(
        path=file_path,
        title="Graph note",
        last_modified=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        size_bytes=2048,
        kind="document",
        frontmatter={"tags": ["alpha"]},
    )
    chunks = [
        Chunk(
            chunk_id="graph-chunk-0",
            file_paths=[file_path],
            heading_hierarchy=["Graph note", "Overview"],
            level=2,
            text="Beta discussed the roadmap.",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=str(file_path.resolve()),
                ref=f"filesystem:{file_path.resolve()}",
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        )
    ]
    extraction = ExtractionResult(
        entities=[Entity(name="Beta", type="person", source="ner", chunk_ids=["graph-chunk-0"])],
        relations=[
            Relation(
                source_id="graph-chunk-0",
                target_id="Beta",
                relation_type="MENTIONS",
                weight=1.0,
            )
        ],
    )
    extraction_bundle = pipeline_module._ExtractionBundle(
        entities=extraction.entities,
        relations=extraction.relations,
        total_entities=len(extraction.entities),
        total_relations=len(extraction.relations),
    )

    calls: dict[str, int] = {"populate": 0, "frontmatter": 0, "direct": 0}
    monkeypatch.setattr(pipeline, "_run_extraction", lambda _chunks: extraction_bundle)
    monkeypatch.setattr(
        pipeline,
        "_populate_graph",
        lambda *args, **kwargs: calls.__setitem__("populate", calls["populate"] + 1),
    )
    monkeypatch.setattr(
        pipeline,
        "_frontmatter_to_graph",
        lambda *args, **kwargs: calls.__setitem__("frontmatter", calls["frontmatter"] + 1),
    )
    monkeypatch.setattr(
        pipeline,
        "_write_surreal_direct_manifest",
        lambda _manifest: calls.__setitem__("direct", calls["direct"] + 1),
    )

    result = pipeline._extract_and_populate_graph([file_info], chunks, "run-sqlite")

    assert result.total_entities == extraction_bundle.total_entities
    assert result.total_relations == extraction_bundle.total_relations
    assert calls == {"populate": 1, "frontmatter": 1, "direct": 0}


def test_body_change_triggers_full_reembedding(pipeline_settings):
    """Body change triggers full re-embedding (chunk bodies + e_meta)."""
    from dotmd.ingestion.pipeline import IndexingPipeline

    doc = pipeline_settings.data_dir / "test.md"
    _write_md(doc, "Test Document", ["alpha"], "Original body content here.")

    dummy_vec = [0.1] * 768
    encode_calls = []

    def mock_encode_batch(texts):
        encode_calls.append(list(texts))
        return [dummy_vec[:] for _ in texts]

    pipeline = IndexingPipeline(pipeline_settings)
    mock_engine2 = MagicMock()
    mock_engine2.encode_batch = mock_encode_batch
    mock_engine2.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine2

    pipeline.index(pipeline_settings.data_dir)
    encode_calls.clear()

    _write_md(doc, "Test Document", ["alpha"], "Completely different body text now.")
    pipeline.index(pipeline_settings.data_dir)

    chunk_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM chunks_{pipeline._strategy}"
    ).fetchone()[0]
    total_texts = sum(len(c) for c in encode_calls)
    assert total_texts >= chunk_count + 1, (
        f"Body change must encode chunk bodies ({chunk_count}) + e_meta (1). "
        f"Got {total_texts} total texts across {len(encode_calls)} calls."
    )


def test_metadata_only_bulk_index_retains_vectors_for_unchanged_files(
    pipeline_settings,
):
    """Bulk metadata-only reindex must replace changed vectors without wiping siblings."""

    doc_a = pipeline_settings.data_dir / "a.md"
    doc_b = pipeline_settings.data_dir / "b.md"
    _write_md(doc_a, "Initial A", ["alpha"], "Stable body A.")
    _write_md(doc_b, "Initial B", ["alpha"], "Stable body B.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    doc_a_chunk_ids = set(_chunk_ids_for_path(pipeline, doc_a))
    doc_b_chunk_ids = set(_chunk_ids_for_path(pipeline, doc_b))
    assert doc_a_chunk_ids
    assert doc_b_chunk_ids
    assert _vector_chunk_ids(pipeline) == doc_a_chunk_ids | doc_b_chunk_ids

    _write_md(doc_a, "Updated A", ["alpha", "beta"], "Stable body A.")
    pipeline.index(pipeline_settings.data_dir)

    assert _vector_chunk_ids(pipeline) == doc_a_chunk_ids | doc_b_chunk_ids
    doc_a_chunk_id = next(iter(doc_a_chunk_ids))
    assert _fts_meta_for_chunk(pipeline, doc_a_chunk_id) == (
        "Updated A",
        "alpha, beta",
    )
    source_document = pipeline._metadata_store.get_source_document(
        "filesystem",
        str(doc_a.resolve()),
    )
    assert source_document is not None
    assert source_document.title == "Updated A"


def test_body_reindex_keeps_binding_active_and_updates_fingerprints(
    pipeline_settings,
):
    """Body changes use replacement reindex semantics, then refresh binding fingerprints."""

    doc = pipeline_settings.data_dir / "binding-body.md"
    _write_md(doc, "Stable Title", ["alpha"], "Original body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    document_ref = str(doc.resolve())
    before = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert before is not None
    assert before.active is True

    _write_md(doc, "Stable Title", ["alpha"], "Updated body.")
    pipeline.index(pipeline_settings.data_dir)

    after = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert after is not None
    assert after.active is True
    assert after.unbound_at is None
    assert after.content_fingerprint != before.content_fingerprint
    assert after.metadata_fingerprint == before.metadata_fingerprint


def test_metadata_only_refresh_keeps_binding_active_and_updates_fingerprints(
    pipeline_settings,
):
    """Metadata-only refresh updates binding fingerprints without deactivation."""

    doc = pipeline_settings.data_dir / "binding-meta.md"
    _write_md(doc, "Initial", ["alpha"], "Stable body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    document_ref = str(doc.resolve())
    before = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert before is not None
    assert before.active is True

    _write_md(doc, "Updated", ["alpha", "beta"], "Stable body.")
    pipeline.index(pipeline_settings.data_dir)

    after = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert after is not None
    assert after.active is True
    assert after.unbound_at is None
    assert after.content_fingerprint == before.content_fingerprint
    assert after.metadata_fingerprint != before.metadata_fingerprint


def test_metadata_only_index_file_replaces_existing_fused_vector(
    pipeline_settings,
):
    """Single-file metadata-only reindex must update vec0, not leave stale rows."""

    doc = pipeline_settings.data_dir / "single.md"
    _write_md(doc, "Initial", ["alpha"], "Stable body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    chunk_id = _chunk_ids_for_path(pipeline, doc)[0]
    before = _vector_blob_for_chunk(pipeline, chunk_id)

    _write_md(doc, "Updated", ["alpha", "beta"], "Stable body.")
    pipeline.index_file(doc)

    after = _vector_blob_for_chunk(pipeline, chunk_id)
    assert after != before
    assert _vector_chunk_ids(pipeline) == {chunk_id}
    assert _fts_meta_for_chunk(pipeline, chunk_id) == ("Updated", "alpha, beta")

    source_document = pipeline._metadata_store.get_source_document(
        "filesystem",
        str(doc.resolve()),
    )
    assert source_document is not None
    assert source_document.title == "Updated"


def test_modified_index_file_updates_binding_fingerprints_without_inactive_binding(
    pipeline_settings,
):
    """Trickle body changes keep replacement semantics and leave an active binding."""

    doc = pipeline_settings.data_dir / "binding-index-file.md"
    _write_md(doc, "Initial", ["alpha"], "Original body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index_file(doc)

    document_ref = str(doc.resolve())
    before = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert before is not None
    assert before.active is True

    _write_md(doc, "Initial", ["alpha"], "Modified body.")
    pipeline.index_file(doc)

    after = pipeline._metadata_store.get_resource_binding(
        "filesystem",
        document_ref,
    )
    assert after is not None
    assert after.active is True
    assert after.unbound_at is None
    assert after.content_fingerprint != before.content_fingerprint
    assert after.metadata_fingerprint == before.metadata_fingerprint


def test_metadata_only_index_file_refreshes_graph_title_and_removed_tags(
    pipeline_settings,
):
    """Single-file metadata-only update refreshes graph File title and tag edges."""

    doc = pipeline_settings.data_dir / "graph.md"
    _write_md(doc, "Initial", ["obsolete"], "Stable body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    path_str = str(doc)
    initial_node = _graph_node(pipeline, path_str)
    assert initial_node is not None
    assert initial_node["properties"]["title"] == "Initial"
    assert _graph_edges_from(pipeline, path_str, "HAS_TAG")

    doc.write_text(
        "---\ntitle: Updated\nkind: document\n---\nStable body.",
        encoding="utf-8",
    )
    pipeline.index_file(doc)

    updated_node = _graph_node(pipeline, path_str)
    assert updated_node is not None
    assert updated_node["properties"]["title"] == "Updated"
    assert _graph_edges_from(pipeline, path_str, "HAS_TAG") == []


def test_metadata_only_bulk_index_removes_stale_graph_tags(
    pipeline_settings,
):
    """Bulk metadata-only update deletes old frontmatter graph edges."""

    doc = pipeline_settings.data_dir / "bulk-graph.md"
    _write_md(doc, "Initial", ["obsolete"], "Stable body.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)
    path_str = str(doc)
    assert _graph_edges_from(pipeline, path_str, "HAS_TAG")

    doc.write_text(
        "---\ntitle: Updated\nkind: document\n---\nStable body.",
        encoding="utf-8",
    )
    pipeline.index(pipeline_settings.data_dir)

    updated_node = _graph_node(pipeline, path_str)
    assert updated_node is not None
    assert updated_node["properties"]["title"] == "Updated"
    assert _graph_edges_from(pipeline, path_str, "HAS_TAG") == []


def test_reindex_vectors_preserves_vectors_for_all_files(pipeline_settings):
    """Vector rebuild must wipe once, then append each file's chunks."""

    doc_a = pipeline_settings.data_dir / "a.md"
    doc_b = pipeline_settings.data_dir / "b.md"
    _write_md(doc_a, "Initial A", ["alpha"], "Stable body A.")
    _write_md(doc_b, "Initial B", ["alpha"], "Stable body B.")

    pipeline = _make_pipeline_with_directional_vectors(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    expected_chunk_ids = set(_chunk_ids_for_path(pipeline, doc_a)) | set(
        _chunk_ids_for_path(pipeline, doc_b)
    )
    assert expected_chunk_ids

    rebuilt = pipeline.reindex_vectors()

    assert rebuilt == len(expected_chunk_ids)
    assert _vector_chunk_ids(pipeline) == expected_chunk_ids
