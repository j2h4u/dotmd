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
    SurrealDeltaSyncState,
    SurrealDeltaTombstone,
    build_surreal_delta_manifest,
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
