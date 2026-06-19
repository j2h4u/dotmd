from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

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
    run_surreal_delta_sync,
)
from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealRecordIdCodec,
    SurrealStoreConfig,
    define_dotmd_surreal_schema,
)
from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION


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
