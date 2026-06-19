from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

from dotmd.core.models import Chunk, ChunkProvenance, SourceDocument
from dotmd.ingestion.surreal_delta_sync import (
    FakeSurrealDeltaWriter,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaSourceSelection,
    SurrealDeltaSyncState,
    run_surreal_delta_sync,
)
from dotmd.ingestion.surreal_direct_sink import (
    SurrealDirectFileWrite,
    build_surreal_direct_manifest,
)


def _source_document() -> SourceDocument:
    return SourceDocument(
        namespace="filesystem",
        document_ref="/notes/alpha.md",
        ref="filesystem:/notes/alpha.md",
        title="Alpha note",
        source_uri="/notes/alpha.md",
        media_type="text/markdown",
        parser_name="markdown",
        document_type="document",
        updated_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        content_fingerprint="content-alpha",
        metadata_fingerprint="metadata-alpha",
        metadata_json={"tags": ["alpha", "beta"]},
        file_path=Path("/notes/alpha.md"),
    )


def _chunk(*, chunk_id: str, index: int, heading: str, text: str) -> Chunk:
    source_document = _source_document()
    return Chunk(
        chunk_id=chunk_id,
        file_paths=[Path("/notes/alpha.md")],
        heading_hierarchy=["Alpha note", heading],
        level=2,
        text=text,
        chunk_index=index,
        provenance=ChunkProvenance(
            namespace=source_document.namespace,
            document_ref=source_document.document_ref,
            ref=source_document.ref,
            source_unit_refs=[],
            chunk_strategy="contextual_512_50",
            parser_name=source_document.parser_name,
        ),
    )


def _write_fixture() -> SurrealDirectFileWrite:
    source_document = _source_document()
    chunks = [
        _chunk(
            chunk_id="chunk-alpha-0",
            index=0,
            heading="Overview",
            text="alpha body",
        ),
        _chunk(
            chunk_id="chunk-alpha-1",
            index=1,
            heading="Details",
            text="beta body",
        ),
    ]
    return SurrealDirectFileWrite(
        source_document=source_document,
        chunks=chunks,
        embeddings=[
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
        ],
        text_hashes={
            "chunk-alpha-0": "hash-alpha-0",
            "chunk-alpha-1": "hash-alpha-1",
        },
        chunk_strategy="contextual_512_50",
        embedding_model="multilingual_e5_large",
    )


def test_direct_sink_module_does_not_import_sqlite_migration_helpers() -> None:
    from dotmd.ingestion import surreal_direct_sink as direct_sink

    source = inspect.getsource(direct_sink)
    assert "migrate_surreal" not in source
    assert "load_sqlite_rows_for_surreal" not in source
    assert "sqlite_rows" not in source


def test_direct_sink_builds_direct_manifest_rows_from_in_memory_models() -> None:
    source_document = _source_document()
    write = _write_fixture()

    manifest = build_surreal_direct_manifest(
        write,
        source_selection=SurrealDeltaSourceSelection(
            source_name=source_document.namespace,
            table_name="source_documents",
            changed_at=source_document.updated_at,
            cursor="filesystem:/notes/alpha.md:changed",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:alpha",
            watermark="watermark:alpha",
            source_time=source_document.updated_at,
        ),
    )

    assert manifest.graph.deferred is True
    assert manifest.graph.deferred_reason == "graph sync is deferred for the direct filesystem slice"
    assert manifest.feedback.deferred is True
    assert (
        manifest.feedback.deferred_reason
        == "feedback sync is deferred for the direct filesystem slice"
    )

    assert manifest.source_units.rows == []
    assert manifest.fingerprints.rows == []
    assert manifest.vector_components.rows == []

    assert [row.ref for row in manifest.documents.rows] == ["filesystem:/notes/alpha.md"]
    assert manifest.documents.rows[0].row["document_ref"] == "/notes/alpha.md"
    assert manifest.documents.rows[0].row["title"] == "Alpha note"
    assert manifest.documents.rows[0].row["metadata"] == {"tags": ["alpha", "beta"]}

    assert [row.ref for row in manifest.chunks.rows] == ["chunk-alpha-0", "chunk-alpha-1"]
    assert [row.row["chunk_id"] for row in manifest.chunks.rows] == [
        "chunk-alpha-0",
        "chunk-alpha-1",
    ]
    assert [row.row["original_chunk_id"] for row in manifest.chunks.rows] == [
        "chunk-alpha-0",
        "chunk-alpha-1",
    ]
    assert [row.row["chunk_strategy"] for row in manifest.chunks.rows] == [
        "contextual_512_50",
        "contextual_512_50",
    ]
    assert [row.row["title"] for row in manifest.chunks.rows] == ["Overview", "Details"]
    assert [row.row["file_paths"] for row in manifest.chunks.rows] == [
        ["/notes/alpha.md"],
        ["/notes/alpha.md"],
    ]

    assert [row.ref for row in manifest.chunk_file_bindings.rows] == [
        "chunk-alpha-0\x1f/notes/alpha.md\x1f0",
        "chunk-alpha-1\x1f/notes/alpha.md\x1f1",
    ]
    assert [row.row["binding_id"] for row in manifest.chunk_file_bindings.rows] == [
        "chunk-alpha-0\x1f/notes/alpha.md\x1f0",
        "chunk-alpha-1\x1f/notes/alpha.md\x1f1",
    ]
    assert [row.row["chunk_id"] for row in manifest.chunk_file_bindings.rows] == [
        "chunk-alpha-0",
        "chunk-alpha-1",
    ]

    assert [row.ref for row in manifest.provenance.rows] == [
        "chunk-alpha-0\x1ffilesystem\x1f/notes/alpha.md",
        "chunk-alpha-1\x1ffilesystem\x1f/notes/alpha.md",
    ]
    assert [row.row["provenance_id"] for row in manifest.provenance.rows] == [
        "chunk-alpha-0\x1ffilesystem\x1f/notes/alpha.md",
        "chunk-alpha-1\x1ffilesystem\x1f/notes/alpha.md",
    ]
    assert [row.row["chunk_id"] for row in manifest.provenance.rows] == [
        "chunk-alpha-0",
        "chunk-alpha-1",
    ]

    assert [row.ref for row in manifest.resource_bindings.rows] == [
        "filesystem\x1f/notes/alpha.md",
    ]
    assert manifest.resource_bindings.rows[0].row["ref"] == "filesystem\x1f/notes/alpha.md"
    assert manifest.resource_bindings.rows[0].row["resource_ref"] == "/notes/alpha.md"

    assert [row.ref for row in manifest.embeddings.rows] == [
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-0",
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-1",
    ]
    assert [row.row["text_hash"] for row in manifest.embeddings.rows] == [
        "hash-alpha-0",
        "hash-alpha-1",
    ]
    assert [row.row["vector"] for row in manifest.embeddings.rows] == [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
    ]


def test_direct_sink_manifest_is_idempotent_on_fresh_rerun_and_touches_only_expected_sections() -> None:
    write = _write_fixture()
    source_document = write.source_document
    manifest = build_surreal_direct_manifest(
        write,
        source_selection=SurrealDeltaSourceSelection(
            source_name=source_document.namespace,
            table_name="source_documents",
            changed_at=source_document.updated_at,
            cursor="filesystem:/notes/alpha.md:changed",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:alpha",
            watermark="watermark:alpha",
            source_time=source_document.updated_at,
        ),
    )

    writer = FakeSurrealDeltaWriter(target_size_bytes=8192)

    first_state = SurrealDeltaSyncState()
    first = run_surreal_delta_sync(manifest, writer, state=first_state, batch_size=50)
    first_snapshot = writer.snapshot()

    assert first.applied_counts == {
        "documents": 1,
        "chunks": 2,
        "chunk_file_bindings": 2,
        "provenance": 2,
        "resource_bindings": 1,
        "embeddings": 2,
        "checkpoint_candidate": 1,
    }
    assert writer.call_order == [
        "documents",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "embeddings",
        "checkpoint_candidate",
    ]

    second_state = SurrealDeltaSyncState()
    second = run_surreal_delta_sync(manifest, writer, state=second_state, batch_size=50)

    assert second.applied_counts == {
        "documents": 0,
        "chunks": 0,
        "chunk_file_bindings": 0,
        "provenance": 0,
        "resource_bindings": 0,
        "embeddings": 0,
        "checkpoint_candidate": 0,
    }
    assert writer.snapshot()["active_sections"] == first_snapshot["active_sections"]
    assert writer.snapshot()["tombstones"] == first_snapshot["tombstones"]
    assert writer.snapshot()["checkpoint_candidate"] == first_snapshot["checkpoint_candidate"]
    assert writer.call_order == [
        "documents",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "embeddings",
        "checkpoint_candidate",
        "documents",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "embeddings",
        "checkpoint_candidate",
    ]
    assert set(writer.write_counts) == {
        "documents",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "embeddings",
    }


def test_direct_sink_graph_and_feedback_are_deferred() -> None:
    manifest = build_surreal_direct_manifest(
        _write_fixture(),
        source_selection=SurrealDeltaSourceSelection(
            source_name="filesystem",
            table_name="source_documents",
            changed_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
            cursor="filesystem:/notes/alpha.md:changed",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:alpha",
            watermark="watermark:alpha",
        ),
    )

    assert manifest.graph.deferred is True
    assert manifest.feedback.deferred is True
    assert manifest.graph.rows == []
    assert manifest.feedback.rows == []
