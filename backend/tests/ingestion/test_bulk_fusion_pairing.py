"""Tests for bulk-path chunk-to-file fusion pairing and M2M shared-chunk behavior.

Cycle 3 review additions:
- Bulk path: multiple files' chunks must be correctly paired with per-file e_meta
  in _save_and_embed_chunks() / run() bulk embed loop (OpenCode HIGH-1 regression)
- M2M shared-chunk: same body in two files → chunk fused with primary file's e_meta,
  e_text identical for both (documents known last-write-wins semantics)

No live TEI required — encode_batch is mocked.
"""

import pathlib
from datetime import UTC, datetime
from typing import Any
from unittest.mock import MagicMock

import pytest

from dotmd.core.models import Chunk, ChunkProvenance, DocKind, FileInfo, SourceDocument


def _write_md(path: pathlib.Path, title: str, tags: list, body: str) -> None:
    tags_yaml = "\n".join(f"  - {t}" for t in tags) if tags else ""
    tags_section = f"tags:\n{tags_yaml}\n" if tags else ""
    path.write_text(
        f"---\ntitle: {title}\n{tags_section}kind: document\n---\n{body}",
        encoding="utf-8",
    )


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
            "surreal_retrieval_url": "http://surrealdb:8000",
            "surreal_retrieval_namespace": "dotmd",
            "surreal_retrieval_database": "phase46_direct_ingest",
            "surreal_retrieval_username": "root",
            "surreal_retrieval_password": "root",
            "surreal_retrieval_access_token": None,
            "surreal_retrieval_embedding_dimension": 768,
        }
    )


def _make_pipeline_tracking_inputs(settings):
    """Construct pipeline with mock encode_batch that tracks inputs per call.

    Returns (pipeline, call_log) where call_log is a list of
    {'texts': [...], 'vecs': [...], 'idx': int}.
    We distinguish meta calls (1 text) from chunk calls (N texts) by size.
    """
    from dotmd.ingestion.pipeline import IndexingPipeline

    call_counter = [0]
    call_log = []

    def mock_encode(texts):
        # Assign a unique per-call counter to track ordering
        idx = call_counter[0]
        call_counter[0] += 1
        # Return slightly different vectors per call so we can distinguish them
        vec = [0.1 + idx * 0.01] * 768
        vecs = [vec[:] for _ in texts]
        call_log.append({"texts": list(texts), "vecs": vecs, "idx": idx})
        return vecs

    pipeline = IndexingPipeline(settings)
    mock_engine = MagicMock()
    mock_engine.encode_batch = mock_encode
    mock_engine.get_tei_model_id = MagicMock(return_value="test-model")
    pipeline._semantic_engine = mock_engine
    return pipeline, call_log


def _direct_source_document(file_info: FileInfo) -> SourceDocument:
    resolved = file_info.path.resolve()
    return SourceDocument(
        namespace="filesystem",
        document_ref=str(resolved),
        ref=f"filesystem:{resolved}",
        title=file_info.title,
        source_uri=str(file_info.path),
        media_type="text/markdown",
        parser_name="markdown",
        document_type=file_info.kind,
        updated_at=file_info.last_modified,
        content_fingerprint="content-fingerprint",
        metadata_fingerprint="metadata-fingerprint",
        metadata_json={"tags": file_info.frontmatter.get("tags", [])},
        file_path=file_info.path,
    )


# ── Bulk-path chunk-to-file fusion pairing ────────────────────────────────────


def test_bulk_path_multiple_files_get_distinct_emeta(pipeline_settings, tmp_path):
    """index() bulk path encodes distinct e_meta for each file.

    Regression test for OpenCode HIGH-1 (Cycle 3): _save_and_embed_chunks()
    must pair each chunk with the e_meta of ITS OWN file, not a shared e_meta.

    Verifies that after initial index of two files with different titles,
    the pipeline makes separate e_meta encode calls for each file (or one
    batched call with two distinct meta texts), and that the resulting
    vec_components entries are not identical (different e_meta → different e_fused).
    """
    file_a = pipeline_settings.data_dir / "file_a.md"
    file_b = pipeline_settings.data_dir / "file_b.md"
    _write_md(file_a, "Alpha Document", ["alpha"], "Shared body content for both files.")
    _write_md(file_b, "Beta Document", ["beta"], "Completely different body content here.")

    pipeline, call_log = _make_pipeline_tracking_inputs(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    # Collect all texts sent to encode_batch
    all_texts = []
    for call in call_log:
        all_texts.extend(call["texts"])

    # Both file titles must appear somewhere in the encode inputs (as meta texts)
    meta_texts_seen = [
        t for t in all_texts if "Alpha" in t or "Beta" in t or "alpha" in t or "beta" in t
    ]
    assert len(meta_texts_seen) >= 2, (
        f"Both file meta texts must be encoded. Got meta-like texts: {meta_texts_seen}. "
        f"All encode inputs: {all_texts[:10]}"
    )

    # Verify the pipeline stored meta components for both files
    id_a = pipeline._meta_entity_id(file_a)
    id_b = pipeline._meta_entity_id(file_b)
    e_meta_a = pipeline._vec_components.get(id_a, "meta")
    e_meta_b = pipeline._vec_components.get(id_b, "meta")
    assert e_meta_a is not None, f"e_meta must be stored for file_a (entity_id={id_a})"
    assert e_meta_b is not None, f"e_meta must be stored for file_b (entity_id={id_b})"


def test_bulk_path_chunks_stored_with_correct_etext(pipeline_settings, tmp_path):
    """After bulk index(), VecComponentStore has e_text entries for all indexed chunks.

    Verifies that _save_and_embed_chunks() stores e_text per chunk (not just e_fused).
    This is the precondition for the metadata-only fast path to work on subsequent runs.
    """
    doc = pipeline_settings.data_dir / "test.md"
    _write_md(doc, "Test Doc", ["foo"], "Body text with enough content to chunk.")

    pipeline, _call_log = _make_pipeline_tracking_inputs(pipeline_settings)
    pipeline.index(pipeline_settings.data_dir)

    # VecComponentStore must have text components after bulk index
    text_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._vec_components._TABLE} WHERE component = 'text'"
    ).fetchone()[0]
    assert text_count > 0, (
        "_save_and_embed_chunks() must store e_text components in VecComponentStore. "
        "Got 0 text entries."
    )

    # VecComponentStore must have meta component for the file
    meta_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._vec_components._TABLE} WHERE component = 'meta'"
    ).fetchone()[0]
    assert meta_count > 0, (
        "_save_and_embed_chunks() must store e_meta component in VecComponentStore. "
        "Got 0 meta entries."
    )


def test_bulk_path_calls_direct_surreal_sink_with_in_memory_rows(
    surreal_pipeline_settings, tmp_path, monkeypatch
):
    """_save_and_embed_chunks() must hand the direct sink in-memory bulk rows.

    The seam is the only thing this test exercises. SQLite reread helpers are
    patched to fail so the manifest cannot be assembled from persisted rows.
    """
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    file_path = surreal_pipeline_settings.data_dir / "direct.md"
    _write_md(file_path, "Direct Doc", ["direct"], "Bulk direct sink body.")

    monkeypatch.setattr(
        pipeline_module,
        "_create_surreal_direct_writer",
        lambda _settings: object(),
    )
    pipeline = IndexingPipeline(surreal_pipeline_settings)
    file_info = FileInfo(
        path=file_path,
        title="Direct Doc",
        last_modified=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        size_bytes=128,
        kind=DocKind.DOCUMENT,
        frontmatter={"tags": ["direct"]},
    )
    source_document = _direct_source_document(file_info)
    chunks = [
        Chunk(
            chunk_id="direct-chunk-0",
            file_paths=[file_path],
            heading_hierarchy=["Direct Doc", "Overview"],
            level=2,
            text="chunk body zero",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=source_document.document_ref,
                ref=source_document.ref,
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
        Chunk(
            chunk_id="direct-chunk-1",
            file_paths=[file_path],
            heading_hierarchy=["Direct Doc", "Details"],
            level=2,
            text="chunk body one",
            chunk_index=1,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=source_document.document_ref,
                ref=source_document.ref,
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
    ]

    captured: list[Any] = []

    monkeypatch.setattr(
        pipeline,
        "_source_document_for_file_info",
        lambda _file_info: source_document,
    )
    monkeypatch.setattr(
        pipeline,
        "_embed_chunks",
        lambda _chunks: (
            [[0.1, 0.1], [0.2, 0.2]],
            {"direct-chunk-0": "hash-0", "direct-chunk-1": "hash-1"},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_embed_meta_component",
        lambda _file_info: [1.0, 1.0],
    )
    monkeypatch.setattr(
        pipeline,
        "_fuse_vectors",
        lambda e_text, e_meta, _weights: [e_text[0] + e_meta[0], e_text[1] + e_meta[1]],
    )
    monkeypatch.setattr(
        pipeline,
        "_write_surreal_direct_manifest",
        lambda manifest: captured.append(manifest),
    )
    monkeypatch.setattr(
        pipeline._metadata_store,
        "get_chunk_ids_by_file",
        lambda *_args, **_kwargs: pytest.fail("chunk reread helper must not be used"),
    )
    monkeypatch.setattr(
        pipeline._metadata_store,
        "get_chunks",
        lambda *_args, **_kwargs: pytest.fail("chunk reread helper must not be used"),
    )
    monkeypatch.setattr(pipeline._metadata_store, "save_chunks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_persist_chunk_source_provenance",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        pipeline._vector_store,
        "add_chunks",
        MagicMock(),
    )
    monkeypatch.setattr(
        pipeline._keyword_engine,
        "add_chunks",
        MagicMock(),
    )
    monkeypatch.setattr(
        pipeline,
        "_upsert_active_filesystem_binding",
        lambda *_args, **_kwargs: None,
    )

    pipeline._save_and_embed_chunks(chunks, [file_info], run_id="test-direct-sink")

    assert len(captured) == 1
    manifest = captured[0]
    assert [row.ref for row in manifest.documents.rows] == [source_document.ref]
    assert [row.row["document_ref"] for row in manifest.documents.rows] == [
        source_document.document_ref
    ]
    assert [row.row["title"] for row in manifest.chunks.rows] == ["Overview", "Details"]
    assert [row.row["chunk_id"] for row in manifest.embeddings.rows] == [
        "direct-chunk-0",
        "direct-chunk-1",
    ]
    assert [row.row["text_hash"] for row in manifest.embeddings.rows] == ["hash-0", "hash-1"]
    assert [row.row["vector"] for row in manifest.embeddings.rows] == [
        [1.1, 1.1],
        [1.2, 1.2],
    ]


def test_surreal_backend_builds_direct_writer_and_routes_delta_sync(
    surreal_pipeline_settings, tmp_path, monkeypatch
):
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    file_path = surreal_pipeline_settings.data_dir / "direct-route.md"
    _write_md(file_path, "Route Doc", ["route"], "Bulk route body.")

    schema_calls: list[object] = []
    run_calls: list[tuple[object, object, object]] = []

    class FakeSurrealConnection:
        def __init__(self, config):
            self.config = config
            self.closed = False

        def close(self):
            self.closed = True

    class FakeSurrealWriter:
        def __init__(self, connection):
            self.connection = connection

    def fake_define_schema(connection):
        schema_calls.append(connection)

    def fake_run_surreal_delta_sync(manifest, writer, state):
        run_calls.append((manifest, writer, state))
        return None

    monkeypatch.setattr("dotmd.storage.surreal.SurrealConnection", FakeSurrealConnection)
    monkeypatch.setattr("dotmd.storage.surreal_schema.define_dotmd_surreal_schema", fake_define_schema)
    monkeypatch.setattr(
        "dotmd.ingestion.surreal_delta_sync.SurrealDeltaStoreWriter",
        FakeSurrealWriter,
    )
    monkeypatch.setattr(
        pipeline_module,
        "run_surreal_delta_sync",
        fake_run_surreal_delta_sync,
    )

    pipeline = IndexingPipeline(surreal_pipeline_settings)
    assert isinstance(pipeline._surreal_direct_writer, FakeSurrealWriter)
    assert schema_calls == [pipeline._surreal_direct_writer.connection]
    assert pipeline._surreal_direct_writer.connection.config.url == "http://surrealdb:8000"
    assert pipeline._surreal_direct_writer.connection.config.namespace == "dotmd"
    assert (
        pipeline._surreal_direct_writer.connection.config.database
        == "phase46_direct_ingest"
    )
    assert pipeline._surreal_direct_writer.connection.config.username == "root"
    assert pipeline._surreal_direct_writer.connection.config.password == "root"

    file_info = FileInfo(
        path=file_path,
        title="Route Doc",
        last_modified=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        size_bytes=128,
        kind=DocKind.DOCUMENT,
        frontmatter={"tags": ["route"]},
    )
    source_document = _direct_source_document(file_info)
    chunks = [
        Chunk(
            chunk_id="route-chunk-0",
            file_paths=[file_path],
            heading_hierarchy=["Route Doc", "Overview"],
            level=2,
            text="chunk body zero",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=source_document.document_ref,
                ref=source_document.ref,
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
        Chunk(
            chunk_id="route-chunk-1",
            file_paths=[file_path],
            heading_hierarchy=["Route Doc", "Details"],
            level=2,
            text="chunk body one",
            chunk_index=1,
            provenance=ChunkProvenance(
                namespace="filesystem",
                document_ref=source_document.document_ref,
                ref=source_document.ref,
                source_unit_refs=[],
                chunk_strategy=pipeline._strategy,
                parser_name="markdown",
            ),
        ),
    ]

    monkeypatch.setattr(
        pipeline,
        "_source_document_for_file_info",
        lambda _file_info: source_document,
    )
    monkeypatch.setattr(
        pipeline,
        "_embed_chunks",
        lambda _chunks: (
            [[0.1, 0.1], [0.2, 0.2]],
            {"route-chunk-0": "hash-0", "route-chunk-1": "hash-1"},
        ),
    )
    monkeypatch.setattr(
        pipeline,
        "_embed_meta_component",
        lambda _file_info: [1.0, 1.0],
    )
    monkeypatch.setattr(
        pipeline,
        "_fuse_vectors",
        lambda e_text, e_meta, _weights: [e_text[0] + e_meta[0], e_text[1] + e_meta[1]],
    )
    monkeypatch.setattr(
        pipeline._metadata_store,
        "get_chunk_ids_by_file",
        lambda *_args, **_kwargs: pytest.fail("chunk reread helper must not be used"),
    )
    monkeypatch.setattr(
        pipeline._metadata_store,
        "get_chunks",
        lambda *_args, **_kwargs: pytest.fail("chunk reread helper must not be used"),
    )
    monkeypatch.setattr(pipeline._metadata_store, "save_chunks", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        pipeline,
        "_persist_chunk_source_provenance",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(pipeline._vector_store, "add_chunks", MagicMock())
    monkeypatch.setattr(pipeline._keyword_engine, "add_chunks", MagicMock())
    monkeypatch.setattr(
        pipeline,
        "_upsert_active_filesystem_binding",
        lambda *_args, **_kwargs: None,
    )

    pipeline._save_and_embed_chunks(chunks, [file_info], run_id="test-surreal-route")

    assert len(run_calls) == 1
    manifest, writer, state = run_calls[0]
    assert writer is pipeline._surreal_direct_writer
    assert state is pipeline._surreal_direct_sync_state
    assert [row.ref for row in manifest.documents.rows] == [source_document.ref]
    assert [row.row["chunk_id"] for row in manifest.embeddings.rows] == [
        "route-chunk-0",
        "route-chunk-1",
    ]


def test_default_sqlite_settings_do_not_create_surreal_writer(
    pipeline_settings, monkeypatch
):
    from dotmd.ingestion import pipeline as pipeline_module
    from dotmd.ingestion.pipeline import IndexingPipeline

    monkeypatch.setattr(
        pipeline_module,
        "_create_surreal_direct_writer",
        lambda _settings: pytest.fail("sqlite defaults must not create a surreal writer"),
    )

    pipeline = IndexingPipeline(pipeline_settings)
    assert pipeline._surreal_direct_writer is None


def test_meta_entity_id_normalizes_path(pipeline_settings):
    """_meta_entity_id() returns the same canonical path regardless of input form.

    Verifies that str(Path(p).resolve()) is used consistently, preventing
    the normalization divergence that would cause silent fast-path cache misses.
    (Addresses Codex HIGH Cycle 3: meta component reads may not be normalized.)
    """
    from dotmd.ingestion.pipeline import IndexingPipeline

    pipeline = IndexingPipeline(pipeline_settings)

    # Various input forms for the same path
    base = str(pipeline_settings.data_dir / "test.md")
    # All should produce the same canonical entity_id
    id1 = pipeline._meta_entity_id(base)
    id2 = pipeline._meta_entity_id(pathlib.Path(base))

    assert id1 == id2, (
        f"_meta_entity_id() must return the same string for str and Path inputs. "
        f"Got: {id1!r} vs {id2!r}"
    )
    assert id1 == str(pathlib.Path(base).resolve()), (
        f"_meta_entity_id() must equal str(Path(path).resolve()). Got: {id1!r}"
    )


# ── M2M shared-chunk behavior ─────────────────────────────────────────────────


def test_m2m_shared_chunk_behavior_documented(pipeline_settings, tmp_path):
    """Two files with same body reuse e_text and store distinct e_meta components.

    Documents known M2M shared-chunk behavior (both reviewers, Cycle 3 MEDIUM):
    When the same chunk body text appears in multiple files (M2M schema), the chunk
    gets one chunk_id. e_text is identical for both files (same body → same hash →
    VecComponentStore hit on second file). e_meta differs because each file has a
    different title.

    This test asserts that the pipeline handles shared chunks without errors and
    that e_text is reused through the local component cache.
    """
    shared_body = "This is the shared body text that appears in both files."
    file_a = pipeline_settings.data_dir / "shared_a.md"
    file_b = pipeline_settings.data_dir / "shared_b.md"
    _write_md(file_a, "File A Title", ["tag_a"], shared_body)
    _write_md(file_b, "File B Title", ["tag_b"], shared_body)

    pipeline, _call_log = _make_pipeline_tracking_inputs(pipeline_settings)

    # Must not raise — shared chunks are a valid state in the M2M schema
    pipeline.index(pipeline_settings.data_dir)

    # Both files must have their meta component stored
    id_a = pipeline._meta_entity_id(file_a)
    id_b = pipeline._meta_entity_id(file_b)
    e_meta_a = pipeline._vec_components.get(id_a, "meta")
    e_meta_b = pipeline._vec_components.get(id_b, "meta")
    assert e_meta_a is not None, "File A must have e_meta stored"
    assert e_meta_b is not None, "File B must have e_meta stored"

    # VecComponentStore must have e_text components
    text_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._vec_components._TABLE} WHERE component = 'text'"
    ).fetchone()[0]
    assert text_count > 0, "Shared chunks must have e_text stored in VecComponentStore"


def test_embed_existing_chunks_model_switch_does_not_use_cached_etext(pipeline_settings, tmp_path):
    """model_switch=True path re-encodes e_text from scratch — does NOT use VecComponentStore.

    Regression test for OpenCode HIGH-2 (Cycle 3): _embed_existing_chunks() must
    distinguish model-switch (full re-encode) from metadata-only (cached e_text).

    Verifies that when model_switch=True, _embed_existing_chunks() encodes both
    chunk bodies AND metadata via TEI (not just e_meta), even when VecComponentStore
    has stored e_text from the old model.
    """
    from dotmd.core.models import FileInfo
    from dotmd.ingestion.reader import parse_frontmatter

    doc = pipeline_settings.data_dir / "switch.md"
    _write_md(doc, "Switch Doc", ["foo"], "Body text for model switch test.")

    pipeline, call_log = _make_pipeline_tracking_inputs(pipeline_settings)

    # Initial index — stores e_text in VecComponentStore
    pipeline.index(pipeline_settings.data_dir)
    initial_text_count = pipeline._conn.execute(
        f"SELECT COUNT(*) FROM {pipeline._vec_components._TABLE} WHERE component = 'text'"
    ).fetchone()[0]
    assert initial_text_count > 0, (
        "Precondition: VecComponentStore must have e_text after initial index"
    )

    call_log.clear()

    # Load chunks for this file
    canonical = pipeline._meta_entity_id(doc)
    chunk_ids = pipeline._metadata_store.get_chunk_ids_by_file(pipeline._strategy, canonical)
    assert chunk_ids, (
        f"get_chunk_ids_by_file returned empty after confirmed index (canonical={canonical!r})"
    )

    # Construct a valid FileInfo for the file
    stat = doc.stat()
    content = doc.read_text()
    fm, _ = parse_frontmatter(content)
    fi = FileInfo(
        path=doc,
        title=fm.get("title", "Switch Doc"),
        last_modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
        size_bytes=stat.st_size,
        frontmatter=fm,
    )

    # Call with model_switch=True — must NOT use cached e_text
    pipeline._embed_existing_chunks([fi], model_switch=True)

    # With model_switch=True: encode_batch must have been called for chunk bodies
    # (not just 1 call for e_meta — should be at least 2 calls or 1 call with N>1 texts)
    chunk_count = len(chunk_ids)
    total_texts = sum(len(c["texts"]) for c in call_log)
    assert total_texts >= chunk_count + 1, (
        f"model_switch=True must re-encode chunk bodies ({chunk_count}) + e_meta (1). "
        f"Got {total_texts} texts across {len(call_log)} calls. "
        f"If only 1 call with 1 text, the method is only encoding e_meta and reusing "
        f"stale e_text from VecComponentStore — this is the HIGH-2 bug."
    )
