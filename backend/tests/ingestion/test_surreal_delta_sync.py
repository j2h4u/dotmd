from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dotmd.ingestion.surreal_delta_sync import (
    DELTA_MANIFEST_SCHEMA_VERSION,
    FakeSurrealDeltaWriter,
    SurrealDeltaChange,
    SurrealDeltaChangeType,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaScope,
    SurrealDeltaSection,
    SurrealDeltaSourceSelection,
    SurrealDeltaStoreWriter,
    SurrealDeltaSyncState,
    SurrealDeltaTombstone,
    build_surreal_delta_manifest,
    build_surreal_delta_manifest_from_rows,
    run_surreal_delta_sync,
)


def _base_manifest_kwargs() -> dict[str, object]:
    return {
        "source_selection": SurrealDeltaSourceSelection(
            source_name="filesystem",
            table_name="source_documents",
            changed_at=datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
            cursor="filesystem:changed:42",
        ),
        "checkpoint_candidate": SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:42",
            watermark="watermark:42",
        ),
    }


def _row_manifest_fixture() -> dict[str, list[dict[str, object]]]:
    changed_ref = "/notes/changed.md"
    other_ref = "/notes/other.md"
    deleted_ref = "/notes/deleted.md"
    chunk_strategy = "contextual_512_50"
    embedding_model = "multilingual_e5_large"
    return {
        "documents": [
            {
                "namespace": "filesystem",
                "document_ref": changed_ref,
                "ref": f"filesystem:{changed_ref}",
                "title": "Changed note",
                "media_type": "text/markdown",
                "metadata": {},
            },
            {
                "namespace": "filesystem",
                "document_ref": deleted_ref,
                "ref": f"filesystem:{deleted_ref}",
                "title": "Deleted note",
                "media_type": "text/markdown",
                "metadata": {},
            },
            {
                "namespace": "filesystem",
                "document_ref": other_ref,
                "ref": f"filesystem:{other_ref}",
                "title": "Other note",
                "media_type": "text/markdown",
                "metadata": {},
            },
        ],
        "source_units": [
            {
                "namespace": "filesystem",
                "document_ref": changed_ref,
                "unit_ref": "unit-1",
                "fingerprint": "unit-fp-changed",
                "metadata": {},
            },
            {
                "namespace": "filesystem",
                "document_ref": other_ref,
                "unit_ref": "unit-9",
                "fingerprint": "unit-fp-other",
                "metadata": {},
            },
        ],
        "chunks": [
            {
                "chunk_id": "chunk-changed",
                "chunk_strategy": chunk_strategy,
                "document_ref": changed_ref,
                "ref": f"filesystem:{changed_ref}#chunk-1",
                "heading_hierarchy": ["Changed note"],
                "level": 1,
                "title": "Changed note",
                "tags_text": "",
                "text": "Changed chunk",
                "metadata": {},
            },
            {
                "chunk_id": "chunk-other",
                "chunk_strategy": chunk_strategy,
                "document_ref": other_ref,
                "ref": f"filesystem:{other_ref}#chunk-1",
                "heading_hierarchy": ["Other note"],
                "level": 1,
                "title": "Other note",
                "tags_text": "",
                "text": "Other chunk",
                "metadata": {},
            },
        ],
        "chunk_file_bindings": [
            {
                "binding_id": "chunk-changed\x1f/notes/changed.md\x1f0",
                "chunk_id": "chunk-changed",
                "file_path": changed_ref,
                "chunk_index": 0,
                "metadata": {},
            },
            {
                "binding_id": "chunk-other\x1f/notes/other.md\x1f0",
                "chunk_id": "chunk-other",
                "file_path": other_ref,
                "chunk_index": 0,
                "metadata": {},
            },
        ],
        "provenance": [
            {
                "provenance_id": "chunk-changed\x1ffilesystem\x1f/notes/changed.md",
                "chunk_id": "chunk-changed",
                "namespace": "filesystem",
                "document_ref": changed_ref,
                "source_unit_refs": ["unit-1"],
                "chunk_strategy": chunk_strategy,
                "parser_name": "markdown",
                "metadata": {},
            },
            {
                "provenance_id": "chunk-other\x1ffilesystem\x1f/notes/other.md",
                "chunk_id": "chunk-other",
                "namespace": "filesystem",
                "document_ref": other_ref,
                "source_unit_refs": ["unit-9"],
                "chunk_strategy": chunk_strategy,
                "parser_name": "markdown",
                "metadata": {},
            },
        ],
        "bindings": [
            {
                "namespace": "filesystem",
                "resource_ref": changed_ref,
                "document_ref": changed_ref,
                "ref": f"filesystem:{changed_ref}",
                "active": True,
                "bound_at": datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
                "unbound_at": None,
                "content_fingerprint": "content-changed",
                "metadata_fingerprint": "metadata-changed",
                "source_unit_refs": ["unit-1"],
                "metadata": {},
            },
            {
                "namespace": "filesystem",
                "resource_ref": other_ref,
                "document_ref": other_ref,
                "ref": f"filesystem:{other_ref}",
                "active": True,
                "bound_at": datetime(2026, 6, 19, 12, 0, tzinfo=UTC),
                "unbound_at": None,
                "content_fingerprint": "content-other",
                "metadata_fingerprint": "metadata-other",
                "source_unit_refs": ["unit-9"],
                "metadata": {},
            },
        ],
        "fingerprints": [
            {
                "fingerprint_id": "source_unit::/notes/changed.md::unit-1",
                "fingerprint_kind": "source_unit",
                "namespace": "filesystem",
                "document_ref": changed_ref,
                "content_fingerprint": "unit-fp-changed",
                "metadata_fingerprint": None,
                "metadata": {},
            },
            {
                "fingerprint_id": "source_unit::/notes/other.md::unit-9",
                "fingerprint_kind": "source_unit",
                "namespace": "filesystem",
                "document_ref": other_ref,
                "content_fingerprint": "unit-fp-other",
                "metadata_fingerprint": None,
                "metadata": {},
            },
        ],
        "embeddings": [
            {
                "chunk_strategy": chunk_strategy,
                "embedding_model": embedding_model,
                "chunk_id": "chunk-changed",
                "text_hash": "hash-changed",
                "vector_rowid": 1,
                "vector": [0.1, 0.2],
                "metadata": {},
            },
            {
                "chunk_strategy": chunk_strategy,
                "embedding_model": embedding_model,
                "chunk_id": "chunk-other",
                "text_hash": "hash-other",
                "vector_rowid": 2,
                "vector": [0.3, 0.4],
                "metadata": {},
            },
        ],
        "vector_components": [
            {
                "chunk_strategy": chunk_strategy,
                "embedding_model": embedding_model,
                "chunk_id": "chunk-changed",
                "component": "0",
                "embedding": [0.5, 0.6],
                "metadata": {},
            },
            {
                "chunk_strategy": chunk_strategy,
                "embedding_model": embedding_model,
                "chunk_id": "chunk-other",
                "component": "0",
                "embedding": [0.7, 0.8],
                "metadata": {},
            },
        ],
    }


def test_row_manifest_builder_filters_to_changed_refs_and_emits_tombstones() -> None:
    manifest = build_surreal_delta_manifest_from_rows(
        **_base_manifest_kwargs(),
        sqlite_rows=_row_manifest_fixture(),
        changed_document_refs=["/notes/changed.md"],
        tombstoned_document_refs=["/notes/deleted.md"],
    )

    upsert_rows = [
        row for row in manifest.documents.rows if row.change_type is SurrealDeltaChangeType.UPSERT
    ]
    tombstone_rows = [
        row for row in manifest.documents.rows if row.change_type is SurrealDeltaChangeType.TOMBSTONE
    ]

    assert manifest.graph.deferred is True
    assert manifest.graph.deferred_reason == "graph sync is deferred for this slice"
    assert manifest.feedback.deferred is True
    assert manifest.feedback.deferred_reason == "feedback sync is deferred for this slice"

    assert [row.ref for row in upsert_rows] == ["filesystem:/notes/changed.md"]
    assert [row.row["document_ref"] for row in upsert_rows] == ["/notes/changed.md"]
    assert len(tombstone_rows) == 1
    assert tombstone_rows[0].ref == "filesystem:/notes/deleted.md"
    assert tombstone_rows[0].tombstone is not None
    assert tombstone_rows[0].tombstone.previous_row["title"] == "Deleted note"

    assert [row.row["document_ref"] for row in manifest.source_units.rows] == ["/notes/changed.md"]
    assert [row.row["document_ref"] for row in manifest.chunks.rows] == ["/notes/changed.md"]
    assert [row.row["chunk_id"] for row in manifest.chunk_file_bindings.rows] == ["chunk-changed"]
    assert [row.row["file_path"] for row in manifest.chunk_file_bindings.rows] == ["/notes/changed.md"]
    assert [row.row["document_ref"] for row in manifest.provenance.rows] == ["/notes/changed.md"]
    assert [row.row["document_ref"] for row in manifest.resource_bindings.rows] == ["/notes/changed.md"]
    assert [row.row["document_ref"] for row in manifest.fingerprints.rows] == ["/notes/changed.md"]
    assert [row.row["chunk_id"] for row in manifest.embeddings.rows] == ["chunk-changed"]
    assert [row.row["chunk_id"] for row in manifest.vector_components.rows] == ["chunk-changed"]
    assert all("/notes/other.md" not in row.ref for row in manifest.documents.rows)
    assert all("/notes/other.md" not in row.row.get("document_ref", "") for row in manifest.source_units.rows)


def test_row_manifest_builder_rejects_noop_after_filtering() -> None:
    with pytest.raises(ValidationError, match="at least one changed row or tombstone"):
        build_surreal_delta_manifest_from_rows(
            **_base_manifest_kwargs(),
            sqlite_rows=_row_manifest_fixture(),
            changed_document_refs=[],
            tombstoned_document_refs=[],
        )


def test_valid_changed_file_manifest_carries_changed_rows_and_checkpoint_candidate() -> None:
    manifest = build_surreal_delta_manifest(
        **_base_manifest_kwargs(),
        documents=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/changed.md",
                    table="source_documents",
                    row={
                        "document_ref": "/notes/changed.md",
                        "title": "Changed note",
                        "content_fingerprint": "abc123",
                    },
                )
            ]
        ),
        source_units=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/changed.md#unit-1",
                    table="source_unit_fingerprints",
                    row={
                        "document_ref": "/notes/changed.md",
                        "unit_ref": "unit-1",
                        "fingerprint": "unit-fp-1",
                    },
                )
            ]
        ),
        graph=SurrealDeltaSection(
            deferred=True,
            deferred_reason="graph sync is intentionally deferred in task 1",
        ),
        feedback=SurrealDeltaSection(
            deferred=True,
            deferred_reason="feedback sync is intentionally deferred in task 1",
        ),
    )

    assert manifest.schema_version == DELTA_MANIFEST_SCHEMA_VERSION
    assert manifest.source_selection.scope is SurrealDeltaScope.CHANGED_ROWS
    assert manifest.documents.rows[0].row["title"] == "Changed note"
    assert manifest.checkpoint_candidate.cursor == "checkpoint:42"
    assert manifest.checkpoint_candidate.watermark == "watermark:42"
    assert manifest.graph.deferred is True
    assert manifest.feedback.deferred is True


def test_deferred_graph_and_feedback_are_explicit_and_stable() -> None:
    manifest = build_surreal_delta_manifest(
        **_base_manifest_kwargs(),
        documents=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/changed.md",
                    table="source_documents",
                    row={"document_ref": "/notes/changed.md", "title": "Changed note"},
                )
            ]
        ),
        graph=SurrealDeltaSection(
            deferred=True,
            deferred_reason="graph rows are deferred for this slice",
        ),
        feedback=SurrealDeltaSection(
            deferred=True,
            deferred_reason="feedback rows are deferred for this slice",
        ),
    )

    payload = manifest.model_dump()
    assert payload["graph"]["deferred"] is True
    assert payload["graph"]["deferred_reason"] == "graph rows are deferred for this slice"
    assert payload["feedback"]["deferred"] is True
    assert payload["feedback"]["deferred_reason"] == "feedback rows are deferred for this slice"


@pytest.mark.parametrize(
    ("scope", "match"),
    [
        (SurrealDeltaScope.WHOLE_TABLE, "changed rows only"),
        (SurrealDeltaScope.WHOLE_SOURCE, "changed rows only"),
        (SurrealDeltaScope.WHOLE_DATABASE, "changed rows only"),
    ],
)
def test_whole_table_source_and_database_manifests_are_rejected(
    scope: SurrealDeltaScope,
    match: str,
) -> None:
    with pytest.raises(ValidationError, match=match):
        SurrealDeltaSourceSelection(
            scope=scope,
            source_name="filesystem",
            table_name="source_documents",
            database_name="dotmd",
        )


def test_unchanged_manifest_is_rejected_even_if_graph_and_feedback_are_deferred() -> None:
    with pytest.raises(ValidationError, match="at least one changed row or tombstone"):
        build_surreal_delta_manifest(
            **_base_manifest_kwargs(),
            graph=SurrealDeltaSection(
                deferred=True,
                deferred_reason="graph sync is deferred",
            ),
            feedback=SurrealDeltaSection(
                deferred=True,
                deferred_reason="feedback sync is deferred",
            ),
        )


def test_tombstoned_refs_are_represented_explicitly() -> None:
    deleted_at = datetime(2026, 6, 19, 12, 5, tzinfo=UTC)
    manifest = build_surreal_delta_manifest(
        **_base_manifest_kwargs(),
        documents=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/deleted.md",
                    table="source_documents",
                    change_type=SurrealDeltaChangeType.TOMBSTONE,
                    tombstone=SurrealDeltaTombstone(
                        ref="filesystem:/notes/deleted.md",
                        table="source_documents",
                        deleted_at=deleted_at,
                        reason="source file deleted",
                        previous_row={
                            "document_ref": "/notes/deleted.md",
                            "title": "Deleted note",
                        },
                    ),
                )
            ]
        ),
    )

    row = manifest.documents.rows[0]
    assert row.change_type is SurrealDeltaChangeType.TOMBSTONE
    assert row.tombstone is not None
    assert row.tombstone.deleted_at == deleted_at
    assert row.tombstone.reason == "source file deleted"
    assert row.tombstone.previous_row["title"] == "Deleted note"


def test_manifest_rejects_advanced_checkpoint_candidate() -> None:
    with pytest.raises(ValidationError, match="must not advance the checkpoint"):
        SurrealDeltaCheckpointCandidate(
            cursor="checkpoint:42",
            watermark="watermark:42",
            advanced=True,
        )


def _sync_manifest(*, graph_deferred: bool = False, feedback_deferred: bool = False) -> object:
    graph_section = (
        SurrealDeltaSection(
            deferred=True,
            deferred_reason="graph sync deferred for this slice",
        )
        if graph_deferred
        else SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/graph.md#1",
                    table="graph_nodes",
                    row={"node_id": "graph-1", "label": "Graph"},
                )
            ]
        )
    )
    feedback_section = (
        SurrealDeltaSection(
            deferred=True,
            deferred_reason="feedback sync deferred for this slice",
        )
        if feedback_deferred
        else SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/feedback.md#1",
                    table="feedback",
                    row={"feedback_id": "feedback-1", "status": "open"},
                )
            ]
        )
    )
    return build_surreal_delta_manifest(
        **_base_manifest_kwargs(),
        documents=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/deleted.md",
                    table="source_documents",
                    change_type=SurrealDeltaChangeType.TOMBSTONE,
                    tombstone=SurrealDeltaTombstone(
                        ref="filesystem:/notes/deleted.md",
                        table="source_documents",
                        reason="source file deleted",
                        previous_row={"document_ref": "/notes/deleted.md"},
                    ),
                ),
                SurrealDeltaChange(
                    ref="filesystem:/notes/changed.md",
                    table="source_documents",
                    row={"document_ref": "/notes/changed.md", "title": "Changed note"},
                ),
            ]
        ),
        source_units=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="filesystem:/notes/changed.md#unit-1",
                    table="source_unit_fingerprints",
                    row={"document_ref": "/notes/changed.md", "fingerprint": "unit-fp-1"},
                )
            ]
        ),
        chunks=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1",
                    table="chunks",
                    row={"chunk_id": "chunk-1", "text": "chunk text"},
                ),
                SurrealDeltaChange(
                    ref="chunk-2",
                    table="chunks",
                    row={"chunk_id": "chunk-2", "text": "chunk text two"},
                ),
            ]
        ),
        chunk_file_bindings=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:/notes/changed.md",
                    table="chunk_file_bindings",
                    row={"chunk_id": "chunk-1", "document_ref": "/notes/changed.md"},
                )
            ]
        ),
        provenance=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:prov",
                    table="chunk_provenance",
                    row={"chunk_id": "chunk-1", "source": "filesystem"},
                )
            ]
        ),
        resource_bindings=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:resource",
                    table="resource_bindings",
                    row={"chunk_id": "chunk-1", "resource_ref": "resource-1"},
                )
            ]
        ),
        fingerprints=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:fingerprint",
                    table="fingerprints",
                    row={"chunk_id": "chunk-1", "fingerprint": "fp-1"},
                )
            ]
        ),
        embeddings=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:embedding",
                    table="embeddings",
                    row={"chunk_id": "chunk-1", "vector": [0.1, 0.2]},
                )
            ]
        ),
        vector_components=SurrealDeltaSection(
            rows=[
                SurrealDeltaChange(
                    ref="chunk-1:vector-component",
                    table="vector_components",
                    row={"chunk_id": "chunk-1", "component": 0, "value": 0.1},
                )
            ]
        ),
        graph=graph_section,
        feedback=feedback_section,
    )


def test_incremental_sync_is_deterministic_and_noop_on_repeat() -> None:
    manifest = _sync_manifest()
    writer = FakeSurrealDeltaWriter(target_size_bytes=8192)
    state = SurrealDeltaSyncState()

    result = run_surreal_delta_sync(manifest, writer, state=state, batch_size=50)
    snapshot = writer.snapshot()

    assert result.skipped_phases == ()
    assert writer.call_order == [
        "tombstones",
        "documents",
        "source_units",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "fingerprints",
        "embeddings",
        "vector_components",
        "graph",
        "feedback",
        "checkpoint_candidate",
    ]
    assert result.progress.checkpoint_applied is True
    assert result.progress.target_size_bytes == 8192
    assert state.completed_phases == [
        "tombstones",
        "documents",
        "source_units",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "resource_bindings",
        "fingerprints",
        "embeddings",
        "vector_components",
        "graph",
        "feedback",
        "checkpoint_candidate",
    ]

    repeat = run_surreal_delta_sync(manifest, writer, state=state, batch_size=50)

    assert repeat.skipped_phases == tuple(state.completed_phases)
    assert writer.snapshot()["active_sections"] == snapshot["active_sections"]
    assert writer.snapshot()["tombstones"] == snapshot["tombstones"]
    assert writer.snapshot()["checkpoint_candidate"] == snapshot["checkpoint_candidate"]
    assert writer.snapshot()["write_counts"] == snapshot["write_counts"]
    assert writer.snapshot()["call_order"] == snapshot["call_order"]


def test_incremental_sync_resume_skips_completed_phases_after_forced_failure() -> None:
    manifest = _sync_manifest()
    writer = FakeSurrealDeltaWriter(fail_on_phase="chunks", fail_after_batches=1)
    state = SurrealDeltaSyncState()

    with pytest.raises(RuntimeError, match="forced failure in chunks"):
        run_surreal_delta_sync(manifest, writer, state=state, batch_size=1)

    assert state.completed_phases == [
        "tombstones",
        "documents",
        "source_units",
    ]
    assert state.last_progress is not None
    assert state.last_progress.status == "failed"
    assert state.last_progress.current_phase == "chunks"
    assert state.checkpoint_applied is False

    writer.fail_on_phase = None
    resumed = run_surreal_delta_sync(manifest, writer, state=state, batch_size=1)

    assert resumed.progress.checkpoint_applied is True
    assert writer.active_sections["documents"]["filesystem:/notes/changed.md"]["row"]["title"] == "Changed note"
    assert writer.active_sections["chunks"]["chunk-1"]["row"]["chunk_id"] == "chunk-1"
    assert writer.active_sections["feedback"]["filesystem:/notes/feedback.md#1"]["row"]["status"] == "open"
    assert state.completed_phases[-1] == "checkpoint_candidate"


class _AdvancingClock:
    def __init__(self, start: float = 0.0, step: float = 60.0) -> None:
        self.now = start
        self.step = step

    def __call__(self) -> float:
        current = self.now
        self.now += self.step
        return current


def test_incremental_sync_reports_percent_elapsed_target_size_and_eta_for_long_runs() -> None:
    manifest = _sync_manifest(graph_deferred=True, feedback_deferred=True)
    writer = FakeSurrealDeltaWriter(target_size_bytes=16384)
    state = SurrealDeltaSyncState()
    clock = _AdvancingClock(step=30.0)
    snapshots: list[object] = []

    result = run_surreal_delta_sync(
        manifest,
        writer,
        state=state,
        clock=clock,
        batch_size=1,
        progress_callback=snapshots.append,
    )

    eta_snapshots = [snapshot for snapshot in snapshots if snapshot.eta is not None]

    assert result.progress.target_size_bytes == 16384
    assert any(snapshot.percent_complete > 0 for snapshot in snapshots)
    assert any(snapshot.elapsed_seconds >= 120 for snapshot in snapshots)
    assert eta_snapshots, "expected at least one ETA-bearing progress snapshot"
    assert all(snapshot.eta.startswith("ETA ~") for snapshot in eta_snapshots)


class _FakeSurrealConnection:
    def __init__(self) -> None:
        self.tables: dict[str, dict[str, dict[str, object]]] = {}
        self.calls: list[tuple[str, str, str]] = []

    @staticmethod
    def _table_name(record: object) -> str:
        return str(record).split(":", 1)[0]

    @staticmethod
    def _record_key(record: object) -> str:
        return str(record)

    def select(self, record: object) -> dict[str, object]:
        table = self._table_name(record)
        key = self._record_key(record)
        return dict(self.tables.get(table, {}).get(key, {}))

    def upsert(self, record: object, data: dict[str, object]) -> None:
        table = self._table_name(record)
        key = self._record_key(record)
        self.calls.append(("upsert", table, key))
        stored = dict(data)
        stored["id"] = key
        self.tables.setdefault(table, {})[key] = stored

    def delete(self, record: object) -> None:
        table = self._table_name(record)
        key = self._record_key(record)
        self.calls.append(("delete", table, key))
        self.tables.get(table, {}).pop(key, None)

    def delete_all_from_table(self, table_name: str) -> int:
        raise AssertionError(f"bulk delete is not allowed for {table_name}")

    def insert_rows(self, table_name: str, rows: list[dict[str, object]], *, batch_size: int = 1000) -> object:
        raise AssertionError(f"bulk insert is not allowed for {table_name}")


def test_surreal_delta_store_writer_uses_point_ops_and_is_idempotent() -> None:
    manifest = _sync_manifest(graph_deferred=True)
    connection = _FakeSurrealConnection()
    connection.tables["unrelated"] = {
        "unrelated:keep": {"id": "unrelated:keep", "marker": "keep"}
    }
    writer = SurrealDeltaStoreWriter(connection=connection)

    first_state = SurrealDeltaSyncState()
    first = run_surreal_delta_sync(manifest, writer, state=first_state, batch_size=2)
    first_snapshot = {
        table: {key: dict(row) for key, row in rows.items()}
        for table, rows in connection.tables.items()
    }

    assert first.progress.checkpoint_applied is True
    assert connection.tables["unrelated"] == {"unrelated:keep": {"id": "unrelated:keep", "marker": "keep"}}
    assert all(call[0] != "delete_all" for call in connection.calls)
    assert all(call[0] != "insert_rows" for call in connection.calls)

    second_state = SurrealDeltaSyncState()
    second = run_surreal_delta_sync(manifest, writer, state=second_state, batch_size=2)

    assert second.applied_counts == {
        "tombstones": 0,
        "documents": 0,
        "source_units": 0,
        "chunks": 0,
        "chunk_file_bindings": 0,
        "provenance": 0,
        "resource_bindings": 0,
        "fingerprints": 0,
        "embeddings": 0,
        "vector_components": 0,
        "feedback": 0,
        "checkpoint_candidate": 0,
    }
    assert connection.tables == first_snapshot
    assert connection.tables["unrelated"] == {"unrelated:keep": {"id": "unrelated:keep", "marker": "keep"}}


def test_surreal_delta_store_writer_normalizes_source_document_tombstone_alias() -> None:
    connection = _FakeSurrealConnection()
    writer = SurrealDeltaStoreWriter(connection=connection)
    exact_ref = "filesystem:/notes/deleted.md"
    sibling_ref = "filesystem:/notes/deleted.md.backup"
    exact_id = str(writer.codec.encode("documents", exact_ref))
    sibling_id = str(writer.codec.encode("documents", sibling_ref))
    connection.tables["documents"] = {
        exact_id: {"id": exact_id, "ref": exact_ref, "title": "Deleted"},
        sibling_id: {"id": sibling_id, "ref": sibling_ref, "title": "Sibling"},
    }
    tombstone = SurrealDeltaChange(
        ref=exact_ref,
        table="source_documents",
        change_type=SurrealDeltaChangeType.TOMBSTONE,
        tombstone=SurrealDeltaTombstone(
            ref=exact_ref,
            table="source_documents",
            previous_row={"ref": exact_ref},
        ),
    )

    applied = writer.delete_tombstones([tombstone])

    assert applied == 1
    assert exact_id not in connection.tables["documents"]
    assert sibling_id in connection.tables["documents"]


def test_surreal_delta_store_writer_deletes_chunk_tombstone_by_previous_row_chunk_id() -> None:
    connection = _FakeSurrealConnection()
    writer = SurrealDeltaStoreWriter(connection=connection)

    chunk_id = "chunk-1"
    sibling_chunk_id = "chunk-2"
    chunk_record_id = str(writer.codec.encode("chunks", chunk_id))
    sibling_record_id = str(writer.codec.encode("chunks", sibling_chunk_id))
    connection.tables["chunks"] = {
        chunk_record_id: {
            "id": chunk_record_id,
            "chunk_id": chunk_id,
            "original_chunk_id": chunk_id,
            "ref": "filesystem:/notes/changed.md#bootstrap-chunk",
            "text": "Deleted chunk",
        },
        sibling_record_id: {
            "id": sibling_record_id,
            "chunk_id": sibling_chunk_id,
            "original_chunk_id": sibling_chunk_id,
            "ref": "filesystem:/notes/changed.md#bootstrap-sibling",
            "text": "Sibling chunk",
        },
    }
    tombstone = SurrealDeltaChange(
        ref="filesystem:/notes/changed.md#chunk-1",
        table="chunks",
        change_type=SurrealDeltaChangeType.TOMBSTONE,
        tombstone=SurrealDeltaTombstone(
            ref="filesystem:/notes/changed.md#chunk-1",
            table="chunks",
            previous_row={
                "chunk_id": chunk_id,
                "original_chunk_id": chunk_id,
            },
        ),
    )

    applied = writer.delete_tombstones([tombstone])

    assert applied == 1
    assert chunk_record_id not in connection.tables["chunks"]
    assert sibling_record_id in connection.tables["chunks"]


def test_surreal_delta_store_writer_deletes_embedding_tombstone_by_previous_row_stable_key() -> None:
    connection = _FakeSurrealConnection()
    writer = SurrealDeltaStoreWriter(connection=connection)

    chunk_strategy = "contextual_512_50"
    embedding_model = "multilingual_e5_large"
    chunk_id = "chunk-1"
    sibling_chunk_id = "chunk-2"
    embedding_id = str(
        writer.codec.encode("embeddings", "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-1")
    )
    sibling_embedding_id = str(
        writer.codec.encode("embeddings", "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-2")
    )
    connection.tables["embeddings"] = {
        embedding_id: {
            "id": embedding_id,
            "chunk_strategy": chunk_strategy,
            "embedding_model": embedding_model,
            "chunk_id": chunk_id,
            "ref": "filesystem:/notes/changed.md#embedding-bootstrap",
            "vector": [0.1, 0.2],
        },
        sibling_embedding_id: {
            "id": sibling_embedding_id,
            "chunk_strategy": chunk_strategy,
            "embedding_model": embedding_model,
            "chunk_id": sibling_chunk_id,
            "ref": "filesystem:/notes/changed.md#embedding-sibling",
            "vector": [0.3, 0.4],
        },
    }
    tombstone = SurrealDeltaChange(
        ref="filesystem:/notes/changed.md#embedding",
        table="embeddings",
        change_type=SurrealDeltaChangeType.TOMBSTONE,
        tombstone=SurrealDeltaTombstone(
            ref="filesystem:/notes/changed.md#embedding",
            table="embeddings",
            previous_row={
                "chunk_strategy": chunk_strategy,
                "embedding_model": embedding_model,
                "chunk_id": chunk_id,
            },
        ),
    )

    applied = writer.delete_tombstones([tombstone])

    assert applied == 1
    assert embedding_id not in connection.tables["embeddings"]
    assert sibling_embedding_id in connection.tables["embeddings"]


def test_surreal_delta_store_writer_updates_bootstrap_rows_in_place() -> None:
    connection = _FakeSurrealConnection()
    writer = SurrealDeltaStoreWriter(connection=connection)

    chunk_id = "chunk-1"
    chunk_record_id = str(writer.codec.encode("chunks", chunk_id))
    embedding_id = str(
        writer.codec.encode("embeddings", "contextual_512_50\x1fmultilingual_e5_large\x1fchunk-1")
    )
    binding_id = str(writer.codec.encode("bindings", "filesystem\x1f/notes/changed.md"))
    connection.tables["chunks"] = {
        chunk_record_id: {
            "id": chunk_record_id,
            "chunk_id": chunk_id,
            "original_chunk_id": chunk_id,
            "ref": "filesystem:/notes/changed.md#old",
            "text": "old text",
        }
    }
    connection.tables["embeddings"] = {
        embedding_id: {
            "id": embedding_id,
            "chunk_strategy": "contextual_512_50",
            "embedding_model": "multilingual_e5_large",
            "chunk_id": chunk_id,
            "ref": "filesystem:/notes/changed.md#embedding",
            "vector": [0.1, 0.2],
        }
    }
    connection.tables["bindings"] = {
        binding_id: {
            "id": binding_id,
            "namespace": "filesystem",
            "resource_ref": "/notes/changed.md",
            "ref": "filesystem:/notes/changed.md#stale",
            "active": False,
        }
    }

    chunk_changes = [
        SurrealDeltaChange(
            ref="filesystem:/notes/changed.md#chunk-1",
            table="chunks",
            row={
                "chunk_id": chunk_id,
                "original_chunk_id": chunk_id,
                "ref": "filesystem:/notes/changed.md#chunk-1",
                "text": "new text",
            },
        )
    ]
    embedding_changes = [
        SurrealDeltaChange(
            ref="filesystem:/notes/changed.md#embedding",
            table="embeddings",
            row={
                "chunk_strategy": "contextual_512_50",
                "embedding_model": "multilingual_e5_large",
                "chunk_id": chunk_id,
                "ref": "filesystem:/notes/changed.md#embedding",
                "vector": [0.9, 0.8],
            },
        )
    ]
    binding_changes = [
        SurrealDeltaChange(
            ref="filesystem:/notes/changed.md#binding",
            table="resource_bindings",
            row={
                "namespace": "filesystem",
                "resource_ref": "/notes/changed.md",
                "document_ref": "/notes/changed.md",
                "ref": "filesystem:/notes/changed.md#binding",
                "active": True,
            },
        )
    ]

    assert writer.write_chunks(chunk_changes) == 1
    assert writer.write_embeddings(embedding_changes) == 1
    assert writer.write_resource_bindings(binding_changes) == 1

    assert set(connection.tables["chunks"]) == {chunk_record_id}
    assert connection.tables["chunks"][chunk_record_id]["text"] == "new text"
    assert set(connection.tables["embeddings"]) == {embedding_id}
    assert connection.tables["embeddings"][embedding_id]["vector"] == [0.9, 0.8]
    assert set(connection.tables["bindings"]) == {binding_id}
    assert connection.tables["bindings"][binding_id]["active"] is True


def test_surreal_delta_store_writer_rejects_non_deferred_graph_rows() -> None:
    writer = SurrealDeltaStoreWriter(connection=_FakeSurrealConnection())

    with pytest.raises(NotImplementedError, match="graph rows are deferred"):
        writer.write_graph(
            [
                SurrealDeltaChange(
                    ref="graph-1",
                    table="graph_nodes",
                    row={"node_id": "graph-1", "label": "Graph"},
                )
            ]
        )
