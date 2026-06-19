from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from dotmd.ingestion.surreal_delta_sync import (
    DELTA_MANIFEST_SCHEMA_VERSION,
    SurrealDeltaChange,
    SurrealDeltaChangeType,
    SurrealDeltaCheckpointCandidate,
    SurrealDeltaScope,
    SurrealDeltaSection,
    SurrealDeltaSourceSelection,
    SurrealDeltaTombstone,
    build_surreal_delta_manifest,
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
