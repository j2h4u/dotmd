"""End-to-end invariant: metadata-only change triggers exactly 1 TEI call (Phase 999.12).

This is the core correctness guarantee of Phase 999.12:
  tag update → 1 encode_batch call (for e_meta), NOT N calls (one per chunk).

No live TEI required — encode_batch is mocked.
"""

import pathlib
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
