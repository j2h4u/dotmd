from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from dotmd.ingestion.migrate_surreal import load_sqlite_rows_for_surreal
from dotmd.ingestion.surreal_delta_sync import (
    SurrealDeltaChange,
    SurrealDeltaChangeType,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaSection,
    SurrealDeltaSourceSelection,
    SurrealDeltaStoreWriter,
    SurrealDeltaSyncState,
    SurrealDeltaTombstone,
    build_surreal_delta_manifest,
    build_surreal_delta_manifest_from_rows,
    run_surreal_delta_sync,
)
from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealRecordIdCodec,
    SurrealStoreConfig,
    define_dotmd_surreal_schema,
)
from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION
from tests.ingestion.test_surreal_transform_only_migration import _create_transform_only_fixture


def _scan_by_id(connection: SurrealConnection, table_name: str) -> dict[str, dict[str, object]]:
    return {str(row["id"]): dict(row) for row in connection.scan_table(table_name)}


def _seed_row(
    connection: SurrealConnection,
    codec: SurrealRecordIdCodec,
    table_name: str,
    raw_identifier: str,
    payload: dict[str, object],
) -> str:
    record_id = str(codec.encode(table_name, raw_identifier))
    connection.upsert(codec.encode(table_name, raw_identifier), payload)
    return record_id


def _seed_change(
    connection: SurrealConnection,
    writer: SurrealDeltaStoreWriter,
    change: SurrealDeltaChange,
    payload: dict[str, object] | None = None,
) -> str:
    raw_identifier_getters = {
        "source_documents": writer._document_raw_identifier,
        "documents": writer._document_raw_identifier,
        "source_units": writer._source_unit_raw_identifier,
        "chunks": writer._chunk_raw_identifier,
        "chunk_file_bindings": writer._chunk_file_binding_raw_identifier,
        "provenance": writer._provenance_raw_identifier,
        "resource_bindings": writer._binding_raw_identifier,
        "bindings": writer._binding_raw_identifier,
        "fingerprints": writer._fingerprint_raw_identifier,
        "embeddings": writer._embedding_raw_identifier,
        "vector_components": writer._vector_component_raw_identifier,
        "feedback": writer._feedback_raw_identifier,
    }
    raw_identifier = raw_identifier_getters[change.table](change)
    record_id = writer._record_id(change.table, raw_identifier)
    connection.upsert(record_id, dict(payload or change.row))
    return str(record_id)


def test_surreal_delta_store_writer_smoke_embedded_local_updates_and_deletes_in_place(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "delta-smoke.db"
    codec = SurrealRecordIdCodec()
    config = SurrealStoreConfig(
        url=f"surrealkv://{db_path}",
        namespace="dotmd_phase46",
        database="delta_smoke",
    )

    changed_ref = "filesystem:/notes/changed.md"
    changed_document_ref = "/notes/changed.md"
    keep_ref = "filesystem:/notes/keep.md"
    keep_document_ref = "/notes/keep.md"
    changed_chunk_id = "chunk-1"
    keep_chunk_id = "chunk-keep"
    changed_embedding_key = "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-1"
    keep_embedding_key = "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-keep"
    now = datetime(2026, 6, 19, 12, 0, tzinfo=UTC)

    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)

        seed_ids = {
            "document": _seed_row(
                connection,
                codec,
                "documents",
                changed_ref,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "namespace": "filesystem",
                    "document_ref": changed_document_ref,
                    "ref": changed_ref,
                    "title": "Bootstrap title",
                    "media_type": "text/markdown",
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "chunk": _seed_row(
                connection,
                codec,
                "chunks",
                changed_chunk_id,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "original_chunk_id": changed_chunk_id,
                    "chunk_id": changed_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "document_ref": changed_document_ref,
                    "ref": f"{changed_ref}#bootstrap",
                    "title": "Bootstrap chunk",
                    "tags_text": "bootstrap",
                    "text": "Bootstrap body",
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "embedding": _seed_row(
                connection,
                codec,
                "embeddings",
                changed_embedding_key,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": changed_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "multilingual_e5_large",
                    "text_hash": "hash-bootstrap",
                    "vector_rowid": 1,
                    "vector": [0.1, 0.2],
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "binding": _seed_row(
                connection,
                codec,
                "bindings",
                f"filesystem\x1f{changed_document_ref}",
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "namespace": "filesystem",
                    "document_ref": changed_document_ref,
                    "resource_ref": changed_document_ref,
                    "ref": f"{changed_ref}#bootstrap",
                    "active": False,
                    "bound_at": now,
                    "unbound_at": None,
                    "content_fingerprint": "content-bootstrap",
                    "metadata_fingerprint": "metadata-bootstrap",
                    "source_unit_refs": ["unit-bootstrap"],
                    "metadata": {"seed": "bootstrap"},
                },
            ),
        }

        unrelated_ids = {
            "document": _seed_row(
                connection,
                codec,
                "documents",
                keep_ref,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "namespace": "filesystem",
                    "document_ref": keep_document_ref,
                    "ref": keep_ref,
                    "title": "Unrelated title",
                    "media_type": "text/markdown",
                    "metadata": {"seed": "keep"},
                },
            ),
            "chunk": _seed_row(
                connection,
                codec,
                "chunks",
                keep_chunk_id,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "original_chunk_id": keep_chunk_id,
                    "chunk_id": keep_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "document_ref": keep_document_ref,
                    "ref": f"{keep_ref}#keep",
                    "title": "Unrelated chunk",
                    "tags_text": "keep",
                    "text": "Unrelated body",
                    "metadata": {"seed": "keep"},
                },
            ),
            "embedding": _seed_row(
                connection,
                codec,
                "embeddings",
                keep_embedding_key,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": keep_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "multilingual_e5_large",
                    "text_hash": "hash-keep",
                    "vector_rowid": 2,
                    "vector": [0.3, 0.4],
                    "metadata": {"seed": "keep"},
                },
            ),
        }

        manifest = build_surreal_delta_manifest(
            source_selection=SurrealDeltaSourceSelection(
                source_name="filesystem",
                table_name="source_documents",
                changed_at=now,
                cursor="filesystem:changed:46",
            ),
            checkpoint_candidate=SurrealDeltaCheckpointCandidate(
                cursor="checkpoint:46",
                watermark="watermark:46",
                source_time=now,
            ),
            documents=SurrealDeltaSection(
                rows=[
                    SurrealDeltaChange(
                        ref=changed_ref,
                        table="source_documents",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "namespace": "filesystem",
                            "document_ref": changed_document_ref,
                            "ref": changed_ref,
                            "title": "Updated title",
                            "media_type": "text/markdown",
                            "metadata": {},
                        },
                    )
                ]
            ),
            chunks=SurrealDeltaSection(
                rows=[
                    SurrealDeltaChange(
                        ref=f"{changed_ref}#chunk-1",
                        table="chunks",
                        change_type=SurrealDeltaChangeType.TOMBSTONE,
                        tombstone=SurrealDeltaTombstone(
                            ref=f"{changed_ref}#chunk-1",
                            table="chunks",
                            previous_row={
                                "chunk_id": changed_chunk_id,
                                "original_chunk_id": changed_chunk_id,
                            },
                        ),
                    ),
                    SurrealDeltaChange(
                        ref=f"{changed_ref}#chunk-1",
                        table="chunks",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "original_chunk_id": changed_chunk_id,
                            "chunk_id": changed_chunk_id,
                            "chunk_strategy": "contextual_512_50",
                            "document_ref": changed_document_ref,
                            "ref": f"{changed_ref}#chunk-1",
                            "title": "Updated chunk",
                            "tags_text": "updated",
                            "text": "Updated body",
                            "metadata": {},
                        },
                    ),
                ]
            ),
            resource_bindings=SurrealDeltaSection(
                rows=[
                    SurrealDeltaChange(
                        ref=f"filesystem:{changed_ref}",
                        table="resource_bindings",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "namespace": "filesystem",
                            "document_ref": changed_document_ref,
                            "resource_ref": changed_document_ref,
                            "ref": f"filesystem:{changed_ref}",
                            "active": True,
                            "bound_at": now,
                            "content_fingerprint": "content-updated",
                            "metadata_fingerprint": "metadata-updated",
                            "source_unit_refs": [],
                            "metadata": {},
                        },
                    )
                ]
            ),
            embeddings=SurrealDeltaSection(
                rows=[
                    SurrealDeltaChange(
                        ref=f"{changed_ref}#embedding",
                        table="embeddings",
                        change_type=SurrealDeltaChangeType.TOMBSTONE,
                        tombstone=SurrealDeltaTombstone(
                            ref=f"{changed_ref}#embedding",
                            table="embeddings",
                            previous_row={
                                "chunk_strategy": "contextual_512_50",
                                "embedding_model": "multilingual_e5_large",
                                "chunk_id": changed_chunk_id,
                            },
                        ),
                    ),
                    SurrealDeltaChange(
                        ref=f"{changed_ref}#embedding",
                        table="embeddings",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "chunk_id": changed_chunk_id,
                            "chunk_strategy": "contextual_512_50",
                            "embedding_model": "multilingual_e5_large",
                            "text_hash": "hash-updated",
                            "vector_rowid": 1,
                            "vector": [0.9, 0.8],
                            "metadata": {},
                        },
                    ),
                ]
            ),
        )

        writer = SurrealDeltaStoreWriter(connection=connection)
        state = SurrealDeltaSyncState()

        first = run_surreal_delta_sync(manifest, writer, state=state, batch_size=2)
        first_snapshot = {
            "documents": _scan_by_id(connection, "documents"),
            "chunks": _scan_by_id(connection, "chunks"),
            "bindings": _scan_by_id(connection, "bindings"),
            "embeddings": _scan_by_id(connection, "embeddings"),
            "checkpoints": _scan_by_id(connection, "checkpoints"),
        }

        assert first.applied_counts["tombstones"] == 2
        assert first.applied_counts["documents"] == 1
        assert first.applied_counts["chunks"] == 1
        assert first.applied_counts["resource_bindings"] == 1
        assert first.applied_counts["embeddings"] == 1
        assert first.applied_counts["checkpoint_candidate"] == 1

        assert first_snapshot["documents"][seed_ids["document"]]["title"] == "Updated title"
        assert first_snapshot["chunks"][seed_ids["chunk"]]["text"] == "Updated body"
        assert first_snapshot["bindings"][seed_ids["binding"]]["active"] is True
        assert first_snapshot["bindings"][seed_ids["binding"]]["content_fingerprint"] == "content-updated"
        assert first_snapshot["embeddings"][seed_ids["embedding"]]["vector"] == [0.9, 0.8]
        assert first_snapshot["embeddings"][seed_ids["embedding"]]["text_hash"] == "hash-updated"
        assert first_snapshot["documents"][unrelated_ids["document"]]["title"] == "Unrelated title"
        assert first_snapshot["chunks"][unrelated_ids["chunk"]]["text"] == "Unrelated body"
        assert first_snapshot["embeddings"][unrelated_ids["embedding"]]["vector"] == [0.3, 0.4]
        assert "last_success_at" in first_snapshot["checkpoints"][str(codec.encode("checkpoints", "phase46_delta"))]

        second = run_surreal_delta_sync(manifest, writer, state=state, batch_size=2)
        second_snapshot = {
            "documents": _scan_by_id(connection, "documents"),
            "chunks": _scan_by_id(connection, "chunks"),
            "bindings": _scan_by_id(connection, "bindings"),
            "embeddings": _scan_by_id(connection, "embeddings"),
            "checkpoints": _scan_by_id(connection, "checkpoints"),
        }

        fresh_state = SurrealDeltaSyncState()
        _fresh = run_surreal_delta_sync(manifest, writer, state=fresh_state, batch_size=2)
        fresh_snapshot = {
            "documents": _scan_by_id(connection, "documents"),
            "chunks": _scan_by_id(connection, "chunks"),
            "bindings": _scan_by_id(connection, "bindings"),
            "embeddings": _scan_by_id(connection, "embeddings"),
            "checkpoints": _scan_by_id(connection, "checkpoints"),
        }

    assert second.applied_counts.get("tombstones", 0) == 0
    assert second.applied_counts.get("documents", 0) == 0
    assert second.applied_counts.get("chunks", 0) == 0
    assert second.applied_counts.get("resource_bindings", 0) == 0
    assert second.applied_counts.get("embeddings", 0) == 0
    assert second.applied_counts.get("checkpoint_candidate", 0) == 0
    assert {"tombstones", "documents", "chunks", "resource_bindings", "embeddings", "checkpoint_candidate"}.issubset(
        set(second.skipped_phases)
    )
    assert second_snapshot == first_snapshot

    assert set(fresh_snapshot["documents"]) == set(first_snapshot["documents"])
    assert set(fresh_snapshot["chunks"]) == set(first_snapshot["chunks"])
    assert set(fresh_snapshot["bindings"]) == set(first_snapshot["bindings"])
    assert set(fresh_snapshot["embeddings"]) == set(first_snapshot["embeddings"])
    assert set(fresh_snapshot["checkpoints"]) == set(first_snapshot["checkpoints"])
    assert fresh_snapshot["documents"][seed_ids["document"]] == first_snapshot["documents"][seed_ids["document"]]
    assert fresh_snapshot["chunks"][seed_ids["chunk"]] == first_snapshot["chunks"][seed_ids["chunk"]]
    assert fresh_snapshot["bindings"][seed_ids["binding"]] == first_snapshot["bindings"][seed_ids["binding"]]
    assert fresh_snapshot["embeddings"][seed_ids["embedding"]] == first_snapshot["embeddings"][seed_ids["embedding"]]
    assert fresh_snapshot["documents"][unrelated_ids["document"]] == first_snapshot["documents"][unrelated_ids["document"]]
    assert fresh_snapshot["chunks"][unrelated_ids["chunk"]] == first_snapshot["chunks"][unrelated_ids["chunk"]]
    assert fresh_snapshot["embeddings"][unrelated_ids["embedding"]] == first_snapshot["embeddings"][unrelated_ids["embedding"]]


def test_surreal_delta_store_writer_smoke_changed_file_from_old_stack_fixture(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "old-stack.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    sqlite_rows = load_sqlite_rows_for_surreal(db_path)
    now = datetime(2026, 6, 19, 13, 0, tzinfo=UTC)

    manifest = build_surreal_delta_manifest_from_rows(
        source_selection=SurrealDeltaSourceSelection(
            source_name="filesystem",
            table_name="source_documents",
            changed_at=now,
            cursor="filesystem:changed:46-smoke",
        ),
        checkpoint_candidate=SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:46-smoke",
            watermark="watermark:46-smoke",
            source_time=now,
        ),
        sqlite_rows=sqlite_rows,
        changed_document_refs=[fixture_ids["file_path"]],
    )

    doc_two_ref = "filesystem:/tmp/Doc Two.md"
    weird_chunk_id = fixture_ids["chunk_id"]
    doc_two_chunk_id = "chunk:plain"
    doc_two_embedding_key = f"contextual_512_50\x1fmultilingual_e5_large\x1f{doc_two_chunk_id}"

    assert [row.row["document_ref"] for row in manifest.documents.rows] == [fixture_ids["file_path"]]
    assert all(row.row["document_ref"] == fixture_ids["file_path"] for row in manifest.source_units.rows)
    assert all(row.row["document_ref"] == fixture_ids["file_path"] for row in manifest.chunks.rows)
    assert all(row.row["file_path"] == fixture_ids["file_path"] for row in manifest.chunk_file_bindings.rows)
    assert all(row.row["document_ref"] == fixture_ids["file_path"] for row in manifest.provenance.rows)
    assert all(row.row["document_ref"] == fixture_ids["file_path"] for row in manifest.resource_bindings.rows)
    assert all(row.row["document_ref"] == fixture_ids["file_path"] for row in manifest.fingerprints.rows)
    assert all(row.row["chunk_id"] == weird_chunk_id for row in manifest.embeddings.rows)
    assert manifest.graph.deferred is True
    assert manifest.feedback.deferred is True
    assert doc_two_ref not in {row.row.get("document_ref") for row in manifest.documents.rows}
    assert doc_two_ref not in {row.row.get("document_ref") for row in manifest.source_units.rows}
    assert doc_two_ref not in {row.row.get("document_ref") for row in manifest.chunks.rows}
    assert doc_two_ref not in {row.row.get("document_ref") for row in manifest.resource_bindings.rows}

    with SurrealConnection(
        SurrealStoreConfig(
            url=f"surrealkv://{tmp_path / 'surreal-delta-live.db'}",
            namespace="dotmd_phase46",
            database="delta_smoke",
        )
    ) as connection:
        define_dotmd_surreal_schema(connection)
        writer = SurrealDeltaStoreWriter(connection=connection)

        changed_bootstrap_ids = {
            "document": _seed_change(
                connection,
                writer,
                manifest.documents.rows[0],
                payload={
                    **dict(manifest.documents.rows[0].row),
                    "title": "Bootstrap title",
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "chunk": _seed_change(
                connection,
                writer,
                manifest.chunks.rows[0],
                payload={
                    **dict(manifest.chunks.rows[0].row),
                    "title": "Bootstrap chunk",
                    "text": "Bootstrap body",
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "binding": _seed_change(
                connection,
                writer,
                manifest.resource_bindings.rows[0],
                payload={
                    **dict(manifest.resource_bindings.rows[0].row),
                    "active": False,
                    "content_fingerprint": "content-bootstrap",
                    "metadata_fingerprint": "metadata-bootstrap",
                    "metadata": {"seed": "bootstrap"},
                },
            ),
            "embedding": _seed_change(
                connection,
                writer,
                manifest.embeddings.rows[0],
                payload={
                    **dict(manifest.embeddings.rows[0].row),
                    "text_hash": "hash-bootstrap",
                    "vector_rowid": 9,
                    "vector": [0.1, 0.2, 0.3],
                    "metadata": {"seed": "bootstrap"},
                },
            ),
        }
        for section_name, rows in (
            ("source_units", manifest.source_units.rows),
            ("chunk_file_bindings", manifest.chunk_file_bindings.rows),
            ("provenance", manifest.provenance.rows),
            ("fingerprints", manifest.fingerprints.rows),
        ):
            for index, row in enumerate(rows, start=1):
                _seed_change(
                    connection,
                    writer,
                    row,
                    payload={
                        **dict(row.row),
                        "metadata": {"seed": "bootstrap", "section": section_name, "index": index},
                    },
                )

        unrelated_ids = {
            "document": _seed_row(
                connection,
                writer.codec,
                "documents",
                doc_two_ref,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "namespace": "filesystem",
                    "document_ref": "/tmp/Doc Two.md",
                    "ref": doc_two_ref,
                    "title": "Doc Two bootstrap",
                    "media_type": "text/markdown",
                    "metadata": {"seed": "unrelated"},
                },
            ),
            "chunk": _seed_row(
                connection,
                writer.codec,
                "chunks",
                doc_two_chunk_id,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "original_chunk_id": doc_two_chunk_id,
                    "chunk_id": doc_two_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "document_ref": "/tmp/Doc Two.md",
                    "ref": "filesystem:/tmp/Doc Two.md#bootstrap",
                    "title": "Doc Two bootstrap chunk",
                    "tags_text": "bootstrap",
                    "text": "Bootstrap body",
                    "metadata": {"seed": "unrelated"},
                },
            ),
            "binding": _seed_row(
                connection,
                writer.codec,
                "bindings",
                "filesystem\x1f/tmp/Doc Two.md",
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "namespace": "filesystem",
                    "document_ref": "/tmp/Doc Two.md",
                    "resource_ref": "/tmp/Doc Two.md",
                    "ref": "filesystem:/tmp/Doc Two.md#bootstrap",
                    "active": False,
                    "bound_at": now,
                    "unbound_at": None,
                    "content_fingerprint": "content-unrelated",
                    "metadata_fingerprint": "metadata-unrelated",
                    "source_unit_refs": ["unit:unrelated"],
                    "metadata": {"seed": "unrelated"},
                },
            ),
            "embedding": _seed_row(
                connection,
                writer.codec,
                "embeddings",
                doc_two_embedding_key,
                {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": doc_two_chunk_id,
                    "chunk_strategy": "contextual_512_50",
                    "embedding_model": "multilingual_e5_large",
                    "text_hash": "hash-unrelated",
                    "vector_rowid": 2,
                    "vector": [0.4, 0.5, 0.6],
                    "metadata": {"seed": "unrelated"},
                },
            ),
        }

        first_state = SurrealDeltaSyncState()
        first = run_surreal_delta_sync(manifest, writer, state=first_state, batch_size=2)
        first_snapshot = {
            table: _scan_by_id(connection, table)
            for table in (
                "documents",
                "source_units",
                "chunks",
                "chunk_file_bindings",
                "provenance",
                "bindings",
                "fingerprints",
                "embeddings",
                "feedback",
                "relations",
                "checkpoints",
            )
        }

        assert first.applied_counts["documents"] == 1
        assert first.applied_counts["source_units"] == 2
        assert first.applied_counts["chunks"] == 1
        assert first.applied_counts["resource_bindings"] == 1
        assert first.applied_counts["embeddings"] == 1
        assert first.applied_counts["checkpoint_candidate"] == 1
        assert first.applied_counts.get("graph", 0) == 0
        assert first.applied_counts.get("feedback", 0) == 0
        assert {"graph", "feedback"}.issubset(set(first.skipped_phases))

        assert first_snapshot["documents"][changed_bootstrap_ids["document"]]["title"] == "Doc One"
        assert first_snapshot["chunks"][changed_bootstrap_ids["chunk"]]["text"] == "Alpha body"
        assert first_snapshot["bindings"][changed_bootstrap_ids["binding"]]["active"] is True
        assert first_snapshot["embeddings"][changed_bootstrap_ids["embedding"]]["text_hash"] == "hash-alpha"
        assert first_snapshot["documents"][unrelated_ids["document"]]["title"] == "Doc Two bootstrap"
        assert first_snapshot["chunks"][unrelated_ids["chunk"]]["text"] == "Bootstrap body"
        assert first_snapshot["bindings"][unrelated_ids["binding"]]["content_fingerprint"] == "content-unrelated"
        assert first_snapshot["embeddings"][unrelated_ids["embedding"]]["text_hash"] == "hash-unrelated"
        assert first_snapshot["feedback"] == {}
        assert first_snapshot["relations"] == {}
        assert first_snapshot["checkpoints"]

        second_state = SurrealDeltaSyncState()
        run_surreal_delta_sync(manifest, writer, state=second_state, batch_size=2)
        second_snapshot = {
            table: _scan_by_id(connection, table)
            for table in (
                "documents",
                "source_units",
                "chunks",
                "chunk_file_bindings",
                "provenance",
                "bindings",
                "fingerprints",
                "embeddings",
                "feedback",
                "relations",
                "checkpoints",
            )
        }

    assert second_snapshot == first_snapshot


def test_surreal_delta_store_writer_smoke_graph_relations_use_native_inserts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "surreal-graph-relations.db"
    codec = SurrealRecordIdCodec()
    file_path = "/notes/graph.md"
    stale_tag_name = "alpha"
    stale_participant_name = "Carol"
    fresh_tag_name = "beta"

    with SurrealConnection(
        SurrealStoreConfig(
            url=f"surrealkv://{db_path}",
            namespace="dotmd_phase46",
            database="delta_smoke",
        )
    ) as connection:
        define_dotmd_surreal_schema(connection)
        writer = SurrealDeltaStoreWriter(connection=connection)

        _seed_row(
            connection,
            codec,
            "files",
            file_path,
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "original_id": file_path,
                "path": file_path,
                "file_path": file_path,
                "metadata": {"seed": "graph"},
            },
        )
        _seed_row(
            connection,
            codec,
            "entities",
            stale_participant_name,
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "original_id": stale_participant_name,
                "name": stale_participant_name,
                "metadata": {"seed": "graph"},
            },
        )
        _seed_row(
            connection,
            codec,
            "tags",
            stale_tag_name,
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "original_id": stale_tag_name,
                "name": stale_tag_name,
                "metadata": {"seed": "graph"},
            },
        )
        connection.insert_relation_rows(
            "relations",
            [
                {
                    "id": str(
                        codec.encode(
                            "relations",
                            f"{file_path}\x1f{stale_participant_name}\x1fHAS_PARTICIPANT",
                        ).id
                    ),
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "relation_id": f"{file_path}\x1f{stale_participant_name}\x1fHAS_PARTICIPANT",
                    "rel_type": "HAS_PARTICIPANT",
                    "relation_type": "HAS_PARTICIPANT",
                    "weight": 1.0,
                    "source_id": file_path,
                    "target_id": stale_participant_name,
                    "source_table": "files",
                    "target_table": "entities",
                    "properties": {"seed": "stale"},
                    "metadata": {"seed": "stale"},
                    "in": codec.encode("files", file_path),
                    "out": codec.encode("entities", stale_participant_name),
                },
                {
                    "id": str(
                        codec.encode("relations", f"{file_path}\x1f{stale_tag_name}\x1fHAS_TAG").id
                    ),
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "relation_id": f"{file_path}\x1f{stale_tag_name}\x1fHAS_TAG",
                    "rel_type": "HAS_TAG",
                    "relation_type": "HAS_TAG",
                    "weight": 1.0,
                    "source_id": file_path,
                    "target_id": stale_tag_name,
                    "source_table": "files",
                    "target_table": "tags",
                    "properties": {"seed": "stale"},
                    "metadata": {"seed": "stale"},
                    "in": codec.encode("files", file_path),
                    "out": codec.encode("tags", stale_tag_name),
                },
            ],
        )

        manifest = build_surreal_delta_manifest(
            source_selection=SurrealDeltaSourceSelection(
                source_name="filesystem",
                table_name="source_documents",
                changed_at=datetime(2026, 6, 19, 14, 0, tzinfo=UTC),
                cursor="filesystem:changed:graph",
            ),
            checkpoint_candidate=SurrealDeltaCheckpointCandidate(
                cursor="checkpoint:graph",
                watermark="watermark:graph",
                source_time=datetime(2026, 6, 19, 14, 0, tzinfo=UTC),
            ),
            graph=SurrealDeltaSection(
                rows=[
                    SurrealDeltaChange(
                        ref=file_path,
                        table="files",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "path": file_path,
                            "title": "Graph note",
                        },
                    ),
                    SurrealDeltaChange(
                        ref=f"{file_path}#beta",
                        table="tags",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "name": fresh_tag_name,
                        },
                    ),
                    SurrealDeltaChange(
                        ref=f"{file_path}\x1f{fresh_tag_name}\x1fHAS_TAG",
                        table="relations",
                        row={
                            "schema_version": SURREAL_SCHEMA_VERSION,
                            "source_id": file_path,
                            "source_table": "files",
                            "target_id": fresh_tag_name,
                            "target_table": "tags",
                            "relation_type": "HAS_TAG",
                            "rel_type": "HAS_TAG",
                            "weight": 1.0,
                            "properties": {"source": "frontmatter"},
                            "metadata": {"kind": "relation"},
                        },
                    ),
                ]
            ),
        )

        first_state = SurrealDeltaSyncState()
        first = run_surreal_delta_sync(manifest, writer, state=first_state, batch_size=2)
        first_snapshot = {
            table: _scan_by_id(connection, table)
            for table in ("files", "tags", "entities", "relations", "checkpoints")
        }

        fresh_relation_id = str(
            writer.codec.encode("relations", f"{file_path}\x1f{fresh_tag_name}\x1fHAS_TAG")
        )
        stale_participant_id = str(
            writer.codec.encode("relations", f"{file_path}\x1f{stale_participant_name}\x1fHAS_PARTICIPANT")
        )
        stale_tag_id = str(writer.codec.encode("relations", f"{file_path}\x1f{stale_tag_name}\x1fHAS_TAG"))

        assert first.applied_counts["graph"] == 5
        assert fresh_relation_id in first_snapshot["relations"]
        assert stale_participant_id not in first_snapshot["relations"]
        assert stale_tag_id not in first_snapshot["relations"]
        assert first_snapshot["relations"][fresh_relation_id]["relation_type"] == "HAS_TAG"
        assert first_snapshot["relations"][fresh_relation_id]["in"] == writer.codec.encode("files", file_path)
        assert first_snapshot["relations"][fresh_relation_id]["out"] == writer.codec.encode("tags", fresh_tag_name)
        assert first_snapshot["relations"][fresh_relation_id]["source_id"] == file_path
        assert first_snapshot["relations"][fresh_relation_id]["target_id"] == fresh_tag_name
        assert first_snapshot["relations"][fresh_relation_id]["properties"] == {"source": "frontmatter"}

        second_state = SurrealDeltaSyncState()
        second = run_surreal_delta_sync(manifest, writer, state=second_state, batch_size=2)
        second_snapshot = {
            table: _scan_by_id(connection, table)
            for table in ("files", "tags", "entities", "relations", "checkpoints")
        }

    assert second.applied_counts.get("graph", 0) == 0
    assert second_snapshot == first_snapshot
