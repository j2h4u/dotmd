from __future__ import annotations

import inspect
from datetime import UTC, datetime
from pathlib import Path

from dotmd.core.models import (
    ApplicationSourceChange,
    Chunk,
    ChunkProvenance,
    Entity,
    ExtractionResult,
    FileInfo,
    Relation,
    SourceDocument,
    SourceUnit,
)
from dotmd.ingestion.surreal_delta_sync import (
    FakeSurrealDeltaWriter,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaSourceSelection,
    SurrealDeltaSyncState,
    run_surreal_delta_sync,
)
from dotmd.ingestion.surreal_direct_sink import (
    SurrealApplicationSourceWrite,
    SurrealDirectFileWrite,
    build_surreal_application_source_manifest,
    build_surreal_direct_manifest,
    build_surreal_graph_manifest,
    build_surreal_graph_rows,
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


def _meeting_file_info() -> FileInfo:
    return FileInfo(
        path=Path("/notes/meeting.md"),
        title="Meeting note",
        last_modified=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        size_bytes=1024,
        kind="meeting_transcript",
        frontmatter={
            "tags": ["alpha"],
            "participants": ["Carol"],
        },
    )


def _application_source_document(document_ref: str, title: str) -> SourceDocument:
    return SourceDocument(
        namespace="fixture",
        document_ref=document_ref,
        ref=f"fixture:{document_ref}",
        title=title,
        source_uri=f"fixture://{document_ref}",
        media_type="text/plain",
        parser_name="fixture-parser",
        document_type="page",
        updated_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        content_fingerprint=f"{document_ref}:content",
        metadata_fingerprint=f"{document_ref}:meta",
        metadata_json={"tags": [title.lower()]},
    )


def _application_source_unit(
    document: SourceDocument,
    index: int,
    text: str,
) -> SourceUnit:
    return SourceUnit(
        namespace=document.namespace,
        document_ref=document.document_ref,
        unit_ref=f"{document.document_ref}:unit:{index}",
        unit_type="paragraph",
        text=text,
        order_key=f"{index:020d}",
        fingerprint=f"{document.document_ref}:unit:{index}:fingerprint",
        updated_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
        metadata_json={"speaker": f"speaker-{index}"},
        chunking_hints={},
    )


def _application_source_change(
    document: SourceDocument,
    index: int,
    text: str,
) -> ApplicationSourceChange:
    return ApplicationSourceChange(
        document=document,
        unit=_application_source_unit(document, index, text),
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


def _application_write_fixture() -> SurrealApplicationSourceWrite:
    doc_a = _application_source_document("doc:a", "Alpha")
    doc_b = _application_source_document("doc:b", "Beta")
    changes = [
        _application_source_change(doc_a, 1, "alpha one"),
        _application_source_change(doc_a, 2, "alpha two"),
        _application_source_change(doc_b, 1, "beta one"),
    ]
    chunks = [
        Chunk(
            chunk_id="chunk-alpha-1",
            file_paths=[],
            heading_hierarchy=["Alpha"],
            level=1,
            text="alpha one",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace=doc_a.namespace,
                document_ref=doc_a.document_ref,
                ref="fixture:doc:a:unit:1",
                source_unit_refs=[changes[0].unit.unit_ref],
                chunk_strategy="contextual_512_50",
                parser_name=doc_a.parser_name,
            ),
        ),
        Chunk(
            chunk_id="chunk-alpha-2",
            file_paths=[],
            heading_hierarchy=["Alpha"],
            level=1,
            text="alpha two",
            chunk_index=1,
            provenance=ChunkProvenance(
                namespace=doc_a.namespace,
                document_ref=doc_a.document_ref,
                ref="fixture:doc:a:unit:2",
                source_unit_refs=[changes[1].unit.unit_ref],
                chunk_strategy="contextual_512_50",
                parser_name=doc_a.parser_name,
            ),
        ),
        Chunk(
            chunk_id="chunk-beta-1",
            file_paths=[],
            heading_hierarchy=["Beta"],
            level=1,
            text="beta one",
            chunk_index=0,
            provenance=ChunkProvenance(
                namespace=doc_b.namespace,
                document_ref=doc_b.document_ref,
                ref="fixture:doc:b:unit:1",
                source_unit_refs=[changes[2].unit.unit_ref],
                chunk_strategy="contextual_512_50",
                parser_name=doc_b.parser_name,
            ),
        ),
    ]
    return SurrealApplicationSourceWrite(
        changes=changes,
        indexed_changes=changes,
        chunks=chunks,
        e_text_vectors=[
            [0.1, 0.2, 0.3],
            [0.4, 0.5, 0.6],
            [0.7, 0.8, 0.9],
        ],
        e_meta_by_source_key={
            (doc_a.namespace, doc_a.document_ref): [1.1, 1.2, 1.3],
            (doc_b.namespace, doc_b.document_ref): [2.1, 2.2, 2.3],
        },
        e_fused_vectors=[
            [3.1, 3.2, 3.3],
            [3.4, 3.5, 3.6],
            [3.7, 3.8, 3.9],
        ],
        text_hashes={
            "chunk-alpha-1": "hash-alpha-1",
            "chunk-alpha-2": "hash-alpha-2",
            "chunk-beta-1": "hash-beta-1",
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
    assert manifest.resource_bindings.rows[0].ref == "filesystem\x1f/notes/alpha.md"
    assert manifest.resource_bindings.rows[0].row["ref"] == "filesystem:/notes/alpha.md"
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


def test_application_source_direct_sink_builds_source_rows_and_vector_components() -> None:
    write = _application_write_fixture()

    manifest = build_surreal_application_source_manifest(
        write,
        source_selection=SurrealDeltaSourceSelection(
            source_name="fixture",
            table_name="source_units",
            cursor="offset:3",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="offset:3",
            watermark="watermark:fixture",
        ),
    )

    assert [row.ref for row in manifest.documents.rows] == ["fixture:doc:a", "fixture:doc:b"]
    assert [row.ref for row in manifest.source_units.rows] == [
        "fixture\x1fdoc:a\x1fdoc:a:unit:1",
        "fixture\x1fdoc:a\x1fdoc:a:unit:2",
        "fixture\x1fdoc:b\x1fdoc:b:unit:1",
    ]
    assert [row.row["fingerprint"] for row in manifest.source_units.rows] == [
        "doc:a:unit:1:fingerprint",
        "doc:a:unit:2:fingerprint",
        "doc:b:unit:1:fingerprint",
    ]

    assert [row.ref for row in manifest.chunks.rows] == [
        "fixture:doc:a:unit:1",
        "fixture:doc:a:unit:2",
        "fixture:doc:b:unit:1",
    ]
    assert [row.row["source_unit_refs"] for row in manifest.chunks.rows] == [
        [write.changes[0].unit.unit_ref],
        [write.changes[1].unit.unit_ref],
        [write.changes[2].unit.unit_ref],
    ]

    assert [row.ref for row in manifest.provenance.rows] == [
        "chunk-alpha-1\x1ffixture\x1fdoc:a",
        "chunk-alpha-2\x1ffixture\x1fdoc:a",
        "chunk-beta-1\x1ffixture\x1fdoc:b",
    ]
    assert [row.row["source_unit_refs"] for row in manifest.provenance.rows] == [
        [write.changes[0].unit.unit_ref],
        [write.changes[1].unit.unit_ref],
        [write.changes[2].unit.unit_ref],
    ]

    assert [row.ref for row in manifest.resource_bindings.rows] == [
        "fixture\x1fdoc:a",
        "fixture\x1fdoc:b",
    ]
    assert [row.row["active"] for row in manifest.resource_bindings.rows] == [True, True]

    assert [row.ref for row in manifest.embeddings.rows] == [
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-1",
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-2",
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-beta-1",
    ]
    assert [row.row["text_hash"] for row in manifest.embeddings.rows] == [
        "hash-alpha-1",
        "hash-alpha-2",
        "hash-beta-1",
    ]

    assert [row.ref for row in manifest.vector_components.rows] == [
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-1\x1ftext",
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-alpha-2\x1ftext",
        "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-beta-1\x1ftext",
        "contextual_512_50\x1fmultilingual_e5_large\x1ffixture:doc:a\x1fmeta",
        "contextual_512_50\x1fmultilingual_e5_large\x1ffixture:doc:b\x1fmeta",
    ]
    assert [row.row["component"] for row in manifest.vector_components.rows] == [
        "text",
        "text",
        "text",
        "meta",
        "meta",
    ]
    assert [row.row["chunk_id"] for row in manifest.vector_components.rows] == [
        "chunk-alpha-1",
        "chunk-alpha-2",
        "chunk-beta-1",
        "fixture:doc:a",
        "fixture:doc:b",
    ]
    assert [row.row["embedding"] for row in manifest.vector_components.rows] == [
        [0.1, 0.2, 0.3],
        [0.4, 0.5, 0.6],
        [0.7, 0.8, 0.9],
        [1.1, 1.2, 1.3],
        [2.1, 2.2, 2.3],
    ]


def test_graph_rows_cover_files_sections_entities_tags_and_relations() -> None:
    file_info = _meeting_file_info()
    chunks = [
        Chunk(
            chunk_id="chunk-meeting-0",
            file_paths=[file_info.path],
            heading_hierarchy=["Meeting note", "Overview"],
            level=2,
            text="Carol and Beta discussed the roadmap.",
            chunk_index=0,
        ),
        Chunk(
            chunk_id="chunk-meeting-1",
            file_paths=[file_info.path],
            heading_hierarchy=["Meeting note", "Details"],
            level=2,
            text="Alpha remained a frontmatter tag.",
            chunk_index=1,
        ),
    ]
    extraction = ExtractionResult(
        entities=[
            Entity(name="Beta", type="person", source="ner", chunk_ids=["chunk-meeting-0"]),
            Entity(name="Alpha", type="tag", source="structural", chunk_ids=["chunk-meeting-1"]),
        ],
        relations=[
            Relation(
                source_id="chunk-meeting-0",
                target_id="Beta",
                relation_type="MENTIONS",
                weight=2.0,
            ),
            Relation(
                source_id="chunk-meeting-1",
                target_id="Alpha",
                relation_type="HAS_TAG",
                weight=1.0,
            ),
        ],
    )

    rows = build_surreal_graph_rows([file_info], chunks, extraction)
    manifest = build_surreal_graph_manifest(
        [file_info],
        chunks,
        extraction,
        source_selection=SurrealDeltaSourceSelection(
            source_name="filesystem",
            table_name="source_documents",
            cursor="graph-test",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="graph-test",
            watermark="graph-test",
        ),
    )

    assert len(rows) == 13
    assert [row.table for row in rows].count("files") == 1
    assert [row.table for row in rows].count("sections") == 2
    assert [row.table for row in rows].count("entities") == 2
    assert [row.table for row in rows].count("tags") == 2
    assert [row.table for row in rows].count("relations") == 6
    assert {row.ref for row in rows} == {
        "/notes/meeting.md",
        "chunk-meeting-0",
        "chunk-meeting-1",
        "Beta",
        "Carol",
        "Alpha",
        "alpha",
        "/notes/meeting.md\x1falpha\x1fHAS_TAG",
        "/notes/meeting.md\x1fCarol\x1fHAS_PARTICIPANT",
        "/notes/meeting.md\x1fchunk-meeting-0\x1fCONTAINS",
        "/notes/meeting.md\x1fchunk-meeting-1\x1fCONTAINS",
        "chunk-meeting-0\x1fBeta\x1fMENTIONS",
        "chunk-meeting-1\x1fAlpha\x1fHAS_TAG",
    }

    file_row = rows[0]
    assert file_row.row["path"] == "/notes/meeting.md"
    assert file_row.row["title"] == "Meeting note"

    section_row = rows[1]
    assert section_row.row["chunk_id"] == "chunk-meeting-0"
    assert section_row.row["document_ref"] == "/notes/meeting.md"
    assert section_row.row["text_preview"] == "Carol and Beta discussed the roadmap."

    row_by_ref = {row.ref: row for row in rows}
    assert row_by_ref["Beta"].row["entity_type"] == "person"
    assert row_by_ref["Carol"].row["entity_type"] == "PERSON"
    assert row_by_ref["Alpha"].row["name"] == "Alpha"
    assert row_by_ref["alpha"].row["name"] == "alpha"

    relation_rows = {row.ref: row for row in rows[5:]}
    assert relation_rows["/notes/meeting.md\x1fCarol\x1fHAS_PARTICIPANT"].row["source_table"] == "files"
    assert relation_rows["/notes/meeting.md\x1fCarol\x1fHAS_PARTICIPANT"].row["target_table"] == "entities"
    assert relation_rows["/notes/meeting.md\x1falpha\x1fHAS_TAG"].row["target_table"] == "tags"
    assert relation_rows["chunk-meeting-0\x1fBeta\x1fMENTIONS"].row["source_table"] == "sections"
    assert relation_rows["chunk-meeting-0\x1fBeta\x1fMENTIONS"].row["target_table"] == "entities"
    assert relation_rows["chunk-meeting-0\x1fBeta\x1fMENTIONS"].row["weight"] == 2.0
    assert relation_rows["chunk-meeting-1\x1fAlpha\x1fHAS_TAG"].row["target_table"] == "tags"

    assert manifest.graph.deferred is False
    assert [row.ref for row in manifest.graph.rows] == [row.ref for row in rows]


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
