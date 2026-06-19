"""Phase 46 delta manifest contract for incremental Surreal sync."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, ClassVar, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, model_validator

from dotmd.storage.surreal import SurrealConnection, SurrealRecordIdCodec
from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION, build_dotmd_surreal_schema_plan

DELTA_MANIFEST_SCHEMA_VERSION = "phase46_delta_manifest_v1"


def _surreal_writer_allowed_fields() -> dict[str, frozenset[str]]:
    plan = build_dotmd_surreal_schema_plan()
    allowed_fields = {
        table.name: frozenset(field.name for field in table.fields)
        for table in plan.tables
    }
    allowed_fields["checkpoints"] = allowed_fields["checkpoints"] | frozenset(
        {"last_success_at", "last_error"}
    )
    return allowed_fields


_SURREAL_WRITER_ALLOWED_FIELDS = _surreal_writer_allowed_fields()


class SurrealDeltaScope(StrEnum):
    """Selection scope allowed by the phase 46 delta contract."""

    CHANGED_ROWS = "changed_rows"
    WHOLE_TABLE = "whole_table"
    WHOLE_SOURCE = "whole_source"
    WHOLE_DATABASE = "whole_database"


class SurrealDeltaChangeType(StrEnum):
    """Explicit change kinds carried by the manifest."""

    UPSERT = "upsert"
    TOMBSTONE = "tombstone"


class SurrealDeltaSourceSelection(BaseModel):
    """Provenance for the changed-row slice that produced the manifest."""

    model_config = ConfigDict(extra="forbid")

    scope: SurrealDeltaScope = SurrealDeltaScope.CHANGED_ROWS
    source_name: str | None = None
    table_name: str | None = None
    database_name: str | None = None
    changed_at: datetime | None = None
    cursor: str | None = None

    @model_validator(mode="after")
    def _validate_scope(self) -> SurrealDeltaSourceSelection:
        if self.scope is not SurrealDeltaScope.CHANGED_ROWS:
            raise ValueError("delta manifest must be derived from changed rows only")
        if not any((self.source_name, self.table_name, self.database_name)):
            raise ValueError("delta manifest must identify the changed source")
        return self


class SurrealDeltaTombstone(BaseModel):
    """Explicit tombstone payload for deleted or retired refs."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    table: str
    deleted_at: datetime | None = None
    reason: str | None = None
    previous_row: dict[str, Any] = Field(default_factory=dict)


class SurrealDeltaChange(BaseModel):
    """One changed row or tombstoned ref in the delta manifest."""

    model_config = ConfigDict(extra="forbid")

    ref: str
    table: str
    change_type: SurrealDeltaChangeType = SurrealDeltaChangeType.UPSERT
    row: dict[str, Any] = Field(default_factory=dict)
    tombstone: SurrealDeltaTombstone | None = None

    @model_validator(mode="after")
    def _validate_change(self) -> SurrealDeltaChange:
        if self.change_type is SurrealDeltaChangeType.TOMBSTONE:
            if self.tombstone is None:
                raise ValueError("tombstone changes must include a tombstone payload")
            if self.tombstone.ref != self.ref:
                raise ValueError("tombstone ref must match the change ref")
            if self.tombstone.table != self.table:
                raise ValueError("tombstone table must match the change table")
            return self

        if not self.row:
            raise ValueError("changed rows must include row payload")
        if self.tombstone is not None:
            raise ValueError("upsert changes must not include tombstone payloads")
        return self


class SurrealDeltaSection(BaseModel):
    """Per-domain delta rows, optionally deferred for this phase."""

    model_config = ConfigDict(extra="forbid")

    deferred: bool = False
    deferred_reason: str | None = None
    rows: list[SurrealDeltaChange] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_section(self) -> SurrealDeltaSection:
        if self.deferred:
            if self.rows:
                raise ValueError("deferred sections must not include rows")
            if not self.deferred_reason:
                raise ValueError("deferred sections must include a reason")
            return self

        if self.deferred_reason is not None:
            raise ValueError("non-deferred sections must not include deferred_reason")
        return self


class SurrealDeltaCheckpointCandidate(BaseModel):
    """Checkpoint/watermark candidate carried forward but not advanced."""

    model_config = ConfigDict(extra="forbid")

    cursor: str
    watermark: str | None = None
    source_time: datetime | None = None
    advanced: bool = False

    @model_validator(mode="after")
    def _validate_checkpoint(self) -> SurrealDeltaCheckpointCandidate:
        if self.advanced:
            raise ValueError("delta manifest must not advance the checkpoint")
        return self


class SurrealDeltaManifest(BaseModel):
    """Phase 46 delta manifest for changed old-stack rows only."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = DELTA_MANIFEST_SCHEMA_VERSION
    source_selection: SurrealDeltaSourceSelection
    checkpoint_candidate: SurrealDeltaCheckpointCandidate
    documents: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    source_units: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    chunks: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    chunk_file_bindings: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    provenance: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    resource_bindings: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    fingerprints: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    embeddings: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    vector_components: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    graph: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    feedback: SurrealDeltaSection = Field(default_factory=SurrealDeltaSection)
    created_at: datetime | None = None

    @model_validator(mode="after")
    def _validate_manifest(self) -> SurrealDeltaManifest:
        if self.schema_version != DELTA_MANIFEST_SCHEMA_VERSION:
            raise ValueError(
                f"schema_version must be {DELTA_MANIFEST_SCHEMA_VERSION!r}"
            )
        if self.checkpoint_candidate.advanced:
            raise ValueError("delta manifest must not advance the checkpoint")

        for name in (
            "documents",
            "source_units",
            "chunks",
            "chunk_file_bindings",
            "provenance",
            "resource_bindings",
            "fingerprints",
            "embeddings",
            "vector_components",
        ):
            section = getattr(self, name)
            if section.deferred:
                raise ValueError(f"{name} section cannot be deferred in phase 46 task 1")

        if not any(
            section.rows
            for section in (
                self.documents,
                self.source_units,
                self.chunks,
                self.chunk_file_bindings,
                self.provenance,
                self.resource_bindings,
                self.fingerprints,
                self.embeddings,
                self.vector_components,
                self.graph,
                self.feedback,
            )
        ):
            raise ValueError("delta manifest must include at least one changed row or tombstone")

        return self


def build_surreal_delta_manifest(
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    documents: SurrealDeltaSection | None = None,
    source_units: SurrealDeltaSection | None = None,
    chunks: SurrealDeltaSection | None = None,
    chunk_file_bindings: SurrealDeltaSection | None = None,
    provenance: SurrealDeltaSection | None = None,
    resource_bindings: SurrealDeltaSection | None = None,
    fingerprints: SurrealDeltaSection | None = None,
    embeddings: SurrealDeltaSection | None = None,
    vector_components: SurrealDeltaSection | None = None,
    graph: SurrealDeltaSection | None = None,
    feedback: SurrealDeltaSection | None = None,
    schema_version: str = DELTA_MANIFEST_SCHEMA_VERSION,
    created_at: datetime | None = None,
) -> SurrealDeltaManifest:
    """Build and validate a phase 46 delta manifest."""

    return SurrealDeltaManifest(
        schema_version=schema_version,
        source_selection=source_selection,
        checkpoint_candidate=checkpoint_candidate,
        documents=documents or SurrealDeltaSection(),
        source_units=source_units or SurrealDeltaSection(),
        chunks=chunks or SurrealDeltaSection(),
        chunk_file_bindings=chunk_file_bindings or SurrealDeltaSection(),
        provenance=provenance or SurrealDeltaSection(),
        resource_bindings=resource_bindings or SurrealDeltaSection(),
        fingerprints=fingerprints or SurrealDeltaSection(),
        embeddings=embeddings or SurrealDeltaSection(),
        vector_components=vector_components or SurrealDeltaSection(),
        graph=graph or SurrealDeltaSection(),
        feedback=feedback or SurrealDeltaSection(),
        created_at=created_at,
    )


def _stable_composite_ref(*parts: object) -> str:
    return "\x1f".join(str(part) for part in parts)


def _row_document_ref(row: Mapping[str, Any]) -> str | None:
    document_ref = row.get("document_ref")
    if document_ref is None:
        return None
    return str(document_ref)


def _selected_rows_by_document_ref(
    rows: Sequence[Mapping[str, Any]],
    changed_document_refs: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        document_ref = _row_document_ref(row)
        if document_ref is None or document_ref not in changed_document_refs:
            continue
        selected.append(dict(row))
    return selected


def _selected_rows_by_chunk_id(
    rows: Sequence[Mapping[str, Any]],
    selected_chunk_ids: set[str],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for row in rows:
        chunk_id = row.get("chunk_id") or row.get("entity_id") or row.get("original_chunk_id")
        if chunk_id is None or str(chunk_id) not in selected_chunk_ids:
            continue
        selected.append(dict(row))
    return selected


def build_surreal_delta_manifest_from_rows(
    *,
    source_selection: SurrealDeltaSourceSelection,
    checkpoint_candidate: SurrealDeltaCheckpointCandidate,
    sqlite_rows: Mapping[str, Sequence[Mapping[str, Any]]],
    changed_document_refs: Sequence[str],
    tombstoned_document_refs: Sequence[str] = (),
    graph_deferred_reason: str = "graph sync is deferred for this slice",
    feedback_deferred_reason: str = "feedback sync is deferred for this slice",
    embedding_rows: Sequence[Mapping[str, Any]] = (),
    vector_component_rows: Sequence[Mapping[str, Any]] = (),
) -> SurrealDeltaManifest:
    """Build a delta manifest from already transformed rows."""

    changed_refs = {str(ref) for ref in changed_document_refs if str(ref)}
    tombstoned_refs = {str(ref) for ref in tombstoned_document_refs if str(ref)}
    live_changed_refs = changed_refs - tombstoned_refs

    document_source_rows = list(sqlite_rows.get("documents", ()))
    documents_by_ref = {
        ref: dict(row)
        for row in document_source_rows
        if (ref := _row_document_ref(row)) is not None
    }
    selected_documents = _selected_rows_by_document_ref(document_source_rows, live_changed_refs)
    tombstoned_documents = [
        documents_by_ref.get(
            ref,
            {
                "document_ref": ref,
            },
        )
        for ref in sorted(tombstoned_refs)
    ]

    selected_chunk_rows = _selected_rows_by_document_ref(
        list(sqlite_rows.get("chunks", ())),
        live_changed_refs,
    )
    selected_chunk_ids = {
        str(row["chunk_id"])
        for row in selected_chunk_rows
        if row.get("chunk_id") is not None
    }

    source_units = _selected_rows_by_document_ref(list(sqlite_rows.get("source_units", ())), live_changed_refs)
    chunk_file_bindings = _selected_rows_by_chunk_id(
        list(sqlite_rows.get("chunk_file_bindings", ())),
        selected_chunk_ids,
    )
    provenance = _selected_rows_by_document_ref(list(sqlite_rows.get("provenance", ())), live_changed_refs)
    resource_bindings = _selected_rows_by_document_ref(list(sqlite_rows.get("bindings", ())), live_changed_refs)
    fingerprints = _selected_rows_by_document_ref(list(sqlite_rows.get("fingerprints", ())), live_changed_refs)

    embedding_source_rows = list(embedding_rows) if embedding_rows else list(sqlite_rows.get("embeddings", ()))
    vector_component_source_rows = (
        list(vector_component_rows)
        if vector_component_rows
        else list(sqlite_rows.get("vector_components", ()))
    )
    embeddings = _selected_rows_by_chunk_id(embedding_source_rows, selected_chunk_ids)
    vector_components = _selected_rows_by_chunk_id(vector_component_source_rows, selected_chunk_ids)

    def _document_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(row.get("ref") or f"{row['namespace']}:{row['document_ref']}")
        return SurrealDeltaChange(ref=ref, table="source_documents", row=dict(row))

    def _document_tombstone(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(row.get("ref") or row["document_ref"])
        previous_row = dict(row)
        return SurrealDeltaChange(
            ref=ref,
            table="source_documents",
            change_type=SurrealDeltaChangeType.TOMBSTONE,
            tombstone=SurrealDeltaTombstone(
                ref=ref,
                table="source_documents",
                previous_row=previous_row,
            ),
        )

    def _source_unit_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(
            row.get("ref")
            or _stable_composite_ref(row["namespace"], row["document_ref"], row["unit_ref"])
        )
        return SurrealDeltaChange(ref=ref, table="source_units", row=dict(row))

    def _chunk_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(row.get("ref") or row.get("chunk_id") or row.get("original_chunk_id"))
        return SurrealDeltaChange(ref=ref, table="chunks", row=dict(row))

    def _chunk_file_binding_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(
            row.get("binding_id")
            or _stable_composite_ref(row["chunk_id"], row["file_path"], row["chunk_index"])
        )
        return SurrealDeltaChange(ref=ref, table="chunk_file_bindings", row=dict(row))

    def _provenance_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(
            row.get("provenance_id")
            or _stable_composite_ref(row["chunk_id"], row["namespace"], row["document_ref"])
        )
        return SurrealDeltaChange(ref=ref, table="provenance", row=dict(row))

    def _resource_binding_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(row.get("ref") or f"{row['namespace']}:{row['document_ref']}")
        return SurrealDeltaChange(ref=ref, table="bindings", row=dict(row))

    def _fingerprint_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(row.get("fingerprint_id") or row.get("ref"))
        return SurrealDeltaChange(ref=ref, table="fingerprints", row=dict(row))

    def _embedding_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        ref = str(
            _stable_composite_ref(
                row.get("chunk_strategy", ""),
                row.get("embedding_model", ""),
                row["chunk_id"],
            )
        )
        return SurrealDeltaChange(ref=ref, table="embeddings", row=dict(row))

    def _vector_component_change(row: Mapping[str, Any]) -> SurrealDeltaChange:
        owner = row.get("chunk_id") or row.get("entity_id")
        ref = str(
            _stable_composite_ref(
                row.get("chunk_strategy", ""),
                row.get("embedding_model", ""),
                owner,
                row["component"],
            )
        )
        return SurrealDeltaChange(ref=ref, table="vector_components", row=dict(row))

    documents_section = SurrealDeltaSection(
        rows=_sorted_changes(
            [
                *map(_document_change, selected_documents),
                *map(_document_tombstone, tombstoned_documents),
            ]
        )
    )
    source_units_section = SurrealDeltaSection(
        rows=_sorted_changes(list(map(_source_unit_change, source_units)))
    )
    chunks_section = SurrealDeltaSection(rows=_sorted_changes(list(map(_chunk_change, selected_chunk_rows))))
    chunk_file_bindings_section = SurrealDeltaSection(
        rows=_sorted_changes(list(map(_chunk_file_binding_change, chunk_file_bindings)))
    )
    provenance_section = SurrealDeltaSection(rows=_sorted_changes(list(map(_provenance_change, provenance))))
    resource_bindings_section = SurrealDeltaSection(
        rows=_sorted_changes(list(map(_resource_binding_change, resource_bindings)))
    )
    fingerprints_section = SurrealDeltaSection(rows=_sorted_changes(list(map(_fingerprint_change, fingerprints))))
    embeddings_section = SurrealDeltaSection(rows=_sorted_changes(list(map(_embedding_change, embeddings))))
    vector_components_section = SurrealDeltaSection(
        rows=_sorted_changes(list(map(_vector_component_change, vector_components)))
    )

    return build_surreal_delta_manifest(
        source_selection=source_selection,
        checkpoint_candidate=checkpoint_candidate,
        documents=documents_section,
        source_units=source_units_section,
        chunks=chunks_section,
        chunk_file_bindings=chunk_file_bindings_section,
        provenance=provenance_section,
        resource_bindings=resource_bindings_section,
        fingerprints=fingerprints_section,
        embeddings=embeddings_section,
        vector_components=vector_components_section,
        graph=SurrealDeltaSection(deferred=True, deferred_reason=graph_deferred_reason),
        feedback=SurrealDeltaSection(deferred=True, deferred_reason=feedback_deferred_reason),
    )


@runtime_checkable
class SurrealDeltaWriterProtocol(Protocol):
    """Narrow writer contract for the incremental sync runner."""

    target_size_bytes: int | None

    def delete_tombstones(self, rows: Sequence[SurrealDeltaChange]) -> int:
        """Apply tombstones/deletes before any upserts."""
        ...

    def write_documents(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_source_units(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_chunks(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_chunk_file_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_provenance(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_resource_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_fingerprints(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_embeddings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_vector_components(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_graph(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_feedback(self, rows: Sequence[SurrealDeltaChange]) -> int:
        ...

    def write_checkpoint_candidate(self, candidate: SurrealDeltaCheckpointCandidate) -> int:
        ...


@dataclass(slots=True)
class SurrealDeltaStoreWriter:
    """Incremental Surreal writer that uses point upserts and exact deletes only."""

    connection: SurrealConnection | Any
    codec: SurrealRecordIdCodec = field(default_factory=SurrealRecordIdCodec)
    checkpoint_namespace: str = "phase46_delta"
    target_size_bytes: int | None = None

    _TABLE_ALIASES: ClassVar[dict[str, str]] = {
        "source_documents": "documents",
        "source_unit_fingerprints": "source_units",
        "chunk_provenance": "provenance",
        "resource_bindings": "bindings",
    }

    def _normalize_table_name(self, table: str) -> str:
        return self._TABLE_ALIASES.get(table, table)

    def _record_id(self, table: str, raw_identifier: str) -> Any:
        return self.codec.encode(self._normalize_table_name(table), raw_identifier)

    @staticmethod
    def _stable_composite_ref(*parts: object) -> str:
        return "\x1f".join(str(part) for part in parts)

    def _document_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        return str(row.get("ref") or change.ref)

    def _source_unit_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("ref") is not None:
            return str(row["ref"])
        if all(part is not None for part in (row.get("namespace"), row.get("document_ref"), row.get("unit_ref"))):
            return self._stable_composite_ref(row["namespace"], row["document_ref"], row["unit_ref"])
        return str(change.ref)

    def _chunk_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("chunk_id") is not None:
            return str(row["chunk_id"])
        if row.get("original_chunk_id") is not None:
            return str(row["original_chunk_id"])
        return str(change.ref)

    def _chunk_file_binding_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("binding_id") is not None:
            return str(row["binding_id"])
        if all(part is not None for part in (row.get("chunk_id"), row.get("file_path"), row.get("chunk_index"))):
            return self._stable_composite_ref(row["chunk_id"], row["file_path"], row["chunk_index"])
        return str(change.ref)

    def _provenance_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("provenance_id") is not None:
            return str(row["provenance_id"])
        if all(part is not None for part in (row.get("chunk_id"), row.get("namespace"), row.get("document_ref"))):
            return self._stable_composite_ref(row["chunk_id"], row["namespace"], row["document_ref"])
        return str(change.ref)

    def _binding_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("namespace") is not None and row.get("resource_ref") is not None:
            return self._stable_composite_ref(row["namespace"], row["resource_ref"])
        return str(change.ref)

    def _fingerprint_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("fingerprint_id") is not None:
            return str(row["fingerprint_id"])
        return str(change.ref)

    def _embedding_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if all(
            part is not None for part in (row.get("chunk_strategy"), row.get("embedding_model"), row.get("chunk_id"))
        ):
            return self._stable_composite_ref(
                row["chunk_strategy"], row["embedding_model"], row["chunk_id"]
            )
        return str(change.ref)

    def _vector_component_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        owner = row.get("chunk_id") or row.get("entity_id")
        if all(part is not None for part in (row.get("chunk_strategy"), row.get("embedding_model"), owner, row.get("component"))):
            return self._stable_composite_ref(
                row["chunk_strategy"],
                row["embedding_model"],
                owner,
                row["component"],
            )
        return str(change.ref)

    def _feedback_raw_identifier(self, change: SurrealDeltaChange) -> str:
        row = change.row
        if row.get("original_feedback_id") is not None:
            return str(row["original_feedback_id"])
        return str(change.ref)

    def _embedding_row_for_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        scan_table = getattr(self.connection, "scan_table", None)
        if scan_table is None:
            return None
        for row in scan_table("embeddings"):
            if str(row.get("chunk_id")) == chunk_id:
                return dict(row)
        return None

    def _prepare_payload(self, table: str, raw_identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        table = self._normalize_table_name(table)
        prepared = dict(payload)
        prepared.setdefault("schema_version", SURREAL_SCHEMA_VERSION)

        if table in {"documents", "source_units", "provenance", "chunk_file_bindings", "bindings", "fingerprints", "embeddings", "vector_components", "feedback", "chunks"}:
            prepared.setdefault("metadata", {})
        if table == "chunks":
            prepared.setdefault("file_paths", [])
            prepared.setdefault("file_bindings", [])
            prepared.setdefault("source_unit_refs", [])
        if table == "bindings":
            prepared.setdefault("resource_ref", prepared.get("document_ref"))
        if table == "provenance":
            prepared.setdefault("source_unit_refs", [])
        if table == "embeddings":
            prepared.setdefault("vector_rowid", None)
            prepared.setdefault("vector", [])
        if table == "vector_components":
            prepared.setdefault("embedding", [])
        if table == "feedback":
            prepared.setdefault("original_feedback_id", raw_identifier)
            prepared.setdefault("submitted_at", None)
        if table == "vector_components":
            prepared.setdefault("chunk_id", prepared.get("entity_id"))
            chunk_id = prepared.get("chunk_id")
            chunk_id_text = str(chunk_id) if chunk_id is not None else None
            if isinstance(chunk_id, str) and (
                prepared.get("chunk_strategy") is None or prepared.get("embedding_model") is None
            ):
                source_embedding = self._embedding_row_for_chunk(chunk_id)
                if source_embedding is not None:
                    prepared.setdefault("chunk_strategy", source_embedding.get("chunk_strategy"))
                    prepared.setdefault("embedding_model", source_embedding.get("embedding_model"))
            elif chunk_id_text is not None and (
                prepared.get("chunk_strategy") is None or prepared.get("embedding_model") is None
            ):
                source_embedding = self._embedding_row_for_chunk(chunk_id_text)
                if source_embedding is not None:
                    prepared.setdefault("chunk_id", chunk_id_text)
                    prepared.setdefault("chunk_strategy", source_embedding.get("chunk_strategy"))
                    prepared.setdefault("embedding_model", source_embedding.get("embedding_model"))

        allowed_fields = _SURREAL_WRITER_ALLOWED_FIELDS.get(table)
        if allowed_fields is None:
            return prepared
        return {key: value for key, value in prepared.items() if key in allowed_fields}

    def _tombstone_raw_identifier(self, change: SurrealDeltaChange) -> str:
        tombstone = change.tombstone
        if tombstone is None:
            return str(change.ref)
        table = self._normalize_table_name(tombstone.table)
        if table == "documents":
            return str(tombstone.ref or change.ref)

        previous_row = tombstone.previous_row
        if previous_row:
            previous_change = SurrealDeltaChange(
                ref=tombstone.ref,
                table=table,
                row=dict(previous_row),
            )
            selector_map: dict[str, Callable[[SurrealDeltaChange], str]] = {
                "source_units": self._source_unit_raw_identifier,
                "chunks": self._chunk_raw_identifier,
                "chunk_file_bindings": self._chunk_file_binding_raw_identifier,
                "provenance": self._provenance_raw_identifier,
                "bindings": self._binding_raw_identifier,
                "fingerprints": self._fingerprint_raw_identifier,
                "embeddings": self._embedding_raw_identifier,
                "vector_components": self._vector_component_raw_identifier,
                "feedback": self._feedback_raw_identifier,
            }
            selector = selector_map.get(table)
            if selector is not None:
                return selector(previous_change)
        return str(tombstone.ref or change.ref)

    def _existing_row(self, record_id: Any) -> dict[str, Any] | None:
        select = getattr(self.connection, "select", None)
        if select is None:
            return None
        existing = select(record_id)
        if isinstance(existing, list):
            existing = existing[0] if existing else None
        if not isinstance(existing, dict) or not existing:
            return None
        return dict(existing)

    def _same_row(self, left: dict[str, Any] | None, right: dict[str, Any]) -> bool:
        if left is None:
            return False
        left_payload = dict(left)
        left_payload.pop("id", None)
        right_payload = dict(right)
        right_payload.pop("id", None)
        return left_payload == right_payload

    def _upsert_point(self, table: str, raw_identifier: str, payload: dict[str, Any]) -> int:
        table = self._normalize_table_name(table)
        record_id = self._record_id(table, raw_identifier)
        existing = self._existing_row(record_id)
        prepared = self._prepare_payload(table, raw_identifier, payload)
        if self._same_row(existing, prepared):
            return 0
        self.connection.upsert(record_id, prepared)
        return 1

    def delete_tombstones(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            tombstone = change.tombstone
            table = self._normalize_table_name(
                tombstone.table if tombstone is not None else change.table
            )
            ref = self._tombstone_raw_identifier(change) if tombstone is not None else str(change.ref)
            record_id = self._record_id(table, ref)
            if self._existing_row(record_id) is None:
                continue
            self.connection.delete(record_id)
            applied += 1
        return applied

    def write_documents(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._document_raw_identifier(change)
            row.setdefault("ref", raw_identifier)
            if ":" in raw_identifier:
                namespace, document_ref = raw_identifier.split(":", 1)
                row.setdefault("namespace", namespace)
                row.setdefault("document_ref", document_ref)
            row.setdefault("metadata", {})
            applied += self._upsert_point("documents", raw_identifier, row)
        return applied

    def write_source_units(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._source_unit_raw_identifier(change)
            row.setdefault("ref", raw_identifier)
            row.setdefault("metadata", {})
            applied += self._upsert_point("source_units", raw_identifier, row)
        return applied

    def write_chunks(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._chunk_raw_identifier(change)
            row.setdefault("chunk_id", row.get("chunk_id") or raw_identifier)
            row.setdefault("original_chunk_id", row.get("original_chunk_id") or row["chunk_id"])
            row.setdefault("ref", raw_identifier)
            row.setdefault("metadata", {})
            applied += self._upsert_point("chunks", raw_identifier, row)
        return applied

    def write_chunk_file_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._chunk_file_binding_raw_identifier(change)
            row.setdefault("binding_id", raw_identifier)
            row.setdefault("metadata", {})
            applied += self._upsert_point("chunk_file_bindings", raw_identifier, row)
        return applied

    def write_provenance(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._provenance_raw_identifier(change)
            row.setdefault("provenance_id", raw_identifier)
            row.setdefault("source_unit_refs", [])
            row.setdefault("metadata", {})
            applied += self._upsert_point("provenance", raw_identifier, row)
        return applied

    def write_resource_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._binding_raw_identifier(change)
            row.setdefault("ref", raw_identifier)
            row.setdefault("resource_ref", row.get("resource_ref") or row.get("document_ref"))
            row.setdefault("metadata", {})
            applied += self._upsert_point("bindings", raw_identifier, row)
        return applied

    def write_fingerprints(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._fingerprint_raw_identifier(change)
            row.setdefault("fingerprint_id", raw_identifier)
            row.setdefault("metadata", {})
            applied += self._upsert_point("fingerprints", raw_identifier, row)
        return applied

    def write_embeddings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._embedding_raw_identifier(change)
            row.setdefault("metadata", {})
            row.setdefault("vector_rowid", None)
            applied += self._upsert_point("embeddings", raw_identifier, row)
        return applied

    def write_vector_components(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._vector_component_raw_identifier(change)
            row.setdefault("metadata", {})
            applied += self._upsert_point("vector_components", raw_identifier, row)
        return applied

    def write_graph(self, rows: Sequence[SurrealDeltaChange]) -> int:
        if rows:
            raise NotImplementedError("graph rows are deferred in this phase 46 slice")
        return 0

    def write_feedback(self, rows: Sequence[SurrealDeltaChange]) -> int:
        applied = 0
        for change in rows:
            row = dict(change.row)
            raw_identifier = self._feedback_raw_identifier(change)
            row.setdefault("original_feedback_id", raw_identifier)
            row.setdefault("metadata", {})
            applied += self._upsert_point("feedback", raw_identifier, row)
        return applied

    def write_checkpoint_candidate(self, candidate: SurrealDeltaCheckpointCandidate) -> int:
        payload = {
            "namespace": self.checkpoint_namespace,
            "checkpoint_cursor": candidate.cursor,
            "last_success_at": candidate.source_time,
            "last_error": None,
            "metadata": {
                "watermark": candidate.watermark,
                "advanced": candidate.advanced,
            },
        }
        return self._upsert_point("checkpoints", self.checkpoint_namespace, payload)


@dataclass(slots=True)
class SurrealDeltaSyncState:
    """Mutable resume state for incremental sync retries."""

    started_at_seconds: float | None = None
    completed_phases: list[str] = field(default_factory=list)
    completed_units: int = 0
    last_progress: SurrealDeltaSyncProgress | None = None
    checkpoint_applied: bool = False
    last_error: str | None = None


@dataclass(frozen=True, slots=True)
class SurrealDeltaSyncProgress:
    """Serializable progress snapshot for the incremental sync runner."""

    status: str
    total_units: int
    applied_units: int
    completed_units: int
    current_phase: str | None
    current_phase_units: int
    percent_complete: float
    elapsed_seconds: float
    elapsed: str
    eta_seconds: float | None
    eta: str | None
    target_size_bytes: int | None
    completed_phases: tuple[str, ...]
    checkpoint_applied: bool

    def model_dump(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "total_units": self.total_units,
            "applied_units": self.applied_units,
            "completed_units": self.completed_units,
            "current_phase": self.current_phase,
            "current_phase_units": self.current_phase_units,
            "percent_complete": self.percent_complete,
            "elapsed_seconds": self.elapsed_seconds,
            "elapsed": self.elapsed,
            "eta_seconds": self.eta_seconds,
            "eta": self.eta,
            "target_size_bytes": self.target_size_bytes,
            "completed_phases": list(self.completed_phases),
            "checkpoint_applied": self.checkpoint_applied,
        }


@dataclass(frozen=True, slots=True)
class SurrealDeltaSyncResult:
    """Outcome of a successful incremental sync run."""

    progress: SurrealDeltaSyncProgress
    applied_counts: dict[str, int]
    skipped_phases: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class _SyncPhase:
    name: str
    writer_method: str | None
    rows: tuple[SurrealDeltaChange, ...]


def _sorted_changes(rows: Sequence[SurrealDeltaChange]) -> tuple[SurrealDeltaChange, ...]:
    return tuple(sorted(rows, key=lambda row: (row.table, row.ref)))


def _manifest_units(manifest: SurrealDeltaManifest) -> list[_SyncPhase]:
    phases: list[_SyncPhase] = []
    all_tombstones = tuple(
        sorted(
            (
                row
                for section in (
                    manifest.documents,
                    manifest.source_units,
                    manifest.chunks,
                    manifest.chunk_file_bindings,
                    manifest.provenance,
                    manifest.resource_bindings,
                    manifest.fingerprints,
                    manifest.embeddings,
                    manifest.vector_components,
                    manifest.graph,
                    manifest.feedback,
                )
                for row in section.rows
                if row.change_type is SurrealDeltaChangeType.TOMBSTONE
            ),
            key=lambda row: (row.table, row.ref),
        )
    )
    phases.append(_SyncPhase("tombstones", "delete_tombstones", all_tombstones))

    for name, writer_method, section in (
        ("documents", "write_documents", manifest.documents),
        ("source_units", "write_source_units", manifest.source_units),
        ("chunks", "write_chunks", manifest.chunks),
        ("chunk_file_bindings", "write_chunk_file_bindings", manifest.chunk_file_bindings),
        ("provenance", "write_provenance", manifest.provenance),
        ("resource_bindings", "write_resource_bindings", manifest.resource_bindings),
        ("fingerprints", "write_fingerprints", manifest.fingerprints),
        ("embeddings", "write_embeddings", manifest.embeddings),
        ("vector_components", "write_vector_components", manifest.vector_components),
        ("graph", "write_graph", manifest.graph),
        ("feedback", "write_feedback", manifest.feedback),
    ):
        rows = tuple(
            row
            for row in _sorted_changes(section.rows)
            if row.change_type is SurrealDeltaChangeType.UPSERT
        )
        if section.deferred:
            rows = ()
        phases.append(_SyncPhase(name, writer_method, rows))

    phases.append(_SyncPhase("checkpoint_candidate", "write_checkpoint_candidate", ()))
    return phases


def _phase_units(phase: _SyncPhase) -> int:
    if phase.name == "checkpoint_candidate":
        return 1
    return len(phase.rows)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.0f}s"
    minutes = seconds / 60
    if minutes < 60:
        return f"{minutes:.1f}min"
    return f"{minutes / 60:.1f}hr"


def _build_progress(
    *,
    status: str,
    started_at_seconds: float,
    now_seconds: float,
    total_units: int,
    completed_units: int,
    current_phase: str | None,
    current_phase_units: int,
    target_size_bytes: int | None,
    completed_phases: Sequence[str],
    checkpoint_applied: bool,
) -> SurrealDeltaSyncProgress:
    elapsed_seconds = max(now_seconds - started_at_seconds, 0.0)
    applied_units = min(completed_units, total_units)
    percent_complete = 100.0 if total_units <= 0 else min(applied_units / total_units * 100.0, 100.0)
    eta_seconds: float | None = None
    eta: str | None = None
    if applied_units < total_units and elapsed_seconds >= 120.0 and applied_units > 0:
        rate = applied_units / elapsed_seconds if elapsed_seconds > 0 else 0.0
        if rate > 0:
            eta_seconds = (total_units - applied_units) / rate
            eta = f"ETA ~{_format_duration(eta_seconds)}"
    return SurrealDeltaSyncProgress(
        status=status,
        total_units=total_units,
        applied_units=applied_units,
        completed_units=completed_units,
        current_phase=current_phase,
        current_phase_units=current_phase_units,
        percent_complete=percent_complete,
        elapsed_seconds=elapsed_seconds,
        elapsed=_format_duration(elapsed_seconds),
        eta_seconds=eta_seconds,
        eta=eta,
        target_size_bytes=target_size_bytes,
        completed_phases=tuple(completed_phases),
        checkpoint_applied=checkpoint_applied,
    )


def _emit_progress(
    *,
    state: SurrealDeltaSyncState,
    progress_callback: Callable[[SurrealDeltaSyncProgress], None] | None,
    status: str,
    clock: Callable[[], float],
    total_units: int,
    current_phase: str | None,
    current_phase_units: int,
    target_size_bytes: int | None,
    applied_units: int,
) -> SurrealDeltaSyncProgress:
    now_seconds = clock()
    if state.started_at_seconds is None:
        state.started_at_seconds = now_seconds
    progress = _build_progress(
        status=status,
        started_at_seconds=state.started_at_seconds,
        now_seconds=now_seconds,
        total_units=total_units,
        completed_units=applied_units,
        current_phase=current_phase,
        current_phase_units=current_phase_units,
        target_size_bytes=target_size_bytes,
        completed_phases=state.completed_phases,
        checkpoint_applied=state.checkpoint_applied,
    )
    state.last_progress = progress
    if progress_callback is not None:
        progress_callback(progress)
    return progress


def _chunk_rows(
    rows: Sequence[SurrealDeltaChange],
    batch_size: int,
) -> list[tuple[SurrealDeltaChange, ...]]:
    return [tuple(rows[index : index + batch_size]) for index in range(0, len(rows), batch_size)]


def run_surreal_delta_sync(
    manifest: SurrealDeltaManifest,
    writer: SurrealDeltaWriterProtocol,
    *,
    state: SurrealDeltaSyncState | None = None,
    clock: Callable[[], float] = time.monotonic,
    batch_size: int = 1000,
    progress_callback: Callable[[SurrealDeltaSyncProgress], None] | None = None,
) -> SurrealDeltaSyncResult:
    """Apply a manifest in deterministic order against a writer protocol."""

    if batch_size <= 0:
        raise ValueError("batch_size must be positive")

    state = state or SurrealDeltaSyncState()
    target_size_bytes = getattr(writer, "target_size_bytes", None)
    phases = _manifest_units(manifest)
    total_units = sum(_phase_units(phase) for phase in phases)
    completed_phase_names = set(state.completed_phases)
    applied_counts: dict[str, int] = {}
    skipped_phases: list[str] = []

    _emit_progress(
        state=state,
        progress_callback=progress_callback,
        status="running",
        clock=clock,
        total_units=total_units,
        current_phase=None,
        current_phase_units=0,
        target_size_bytes=target_size_bytes,
        applied_units=state.completed_units,
    )

    try:
        for phase in phases:
            phase_units = _phase_units(phase)
            _emit_progress(
                state=state,
                progress_callback=progress_callback,
                status="running",
                clock=clock,
                total_units=total_units,
                current_phase=phase.name,
                current_phase_units=phase_units,
                target_size_bytes=target_size_bytes,
                applied_units=state.completed_units,
            )
            if phase.name in completed_phase_names:
                skipped_phases.append(phase.name)
                _emit_progress(
                    state=state,
                    progress_callback=progress_callback,
                    status="skipped",
                    clock=clock,
                    total_units=total_units,
                    current_phase=phase.name,
                    current_phase_units=phase_units,
                    target_size_bytes=target_size_bytes,
                    applied_units=state.completed_units,
                )
                continue

            if phase_units == 0:
                skipped_phases.append(phase.name)
                _emit_progress(
                    state=state,
                    progress_callback=progress_callback,
                    status="skipped",
                    clock=clock,
                    total_units=total_units,
                    current_phase=phase.name,
                    current_phase_units=0,
                    target_size_bytes=target_size_bytes,
                    applied_units=state.completed_units,
                )
                continue

            if phase.name == "checkpoint_candidate":
                applied = int(writer.write_checkpoint_candidate(manifest.checkpoint_candidate))
                applied_counts[phase.name] = applied
                state.checkpoint_applied = True
                state.completed_phases.append(phase.name)
                state.completed_units += phase_units
                _emit_progress(
                    state=state,
                    progress_callback=progress_callback,
                    status="applied",
                    clock=clock,
                    total_units=total_units,
                    current_phase=phase.name,
                    current_phase_units=phase_units,
                    target_size_bytes=target_size_bytes,
                    applied_units=state.completed_units,
                )
                continue

            writer_method = getattr(writer, phase.writer_method or "", None)
            if writer_method is None:
                raise AttributeError(f"writer does not implement {phase.writer_method}")

            phase_applied = 0
            for batch in _chunk_rows(phase.rows, batch_size):
                phase_applied += int(writer_method(batch))
                _emit_progress(
                    state=state,
                    progress_callback=progress_callback,
                    status="running",
                    clock=clock,
                    total_units=total_units,
                    current_phase=phase.name,
                    current_phase_units=phase_units,
                    target_size_bytes=target_size_bytes,
                    applied_units=state.completed_units + min(phase_applied, phase_units),
                )

            applied_counts[phase.name] = phase_applied
            state.completed_phases.append(phase.name)
            state.completed_units += phase_units
            _emit_progress(
                state=state,
                progress_callback=progress_callback,
                status="applied",
                clock=clock,
                total_units=total_units,
                current_phase=phase.name,
                current_phase_units=phase_units,
                target_size_bytes=target_size_bytes,
                applied_units=state.completed_units,
            )
    except Exception as exc:
        state.last_error = str(exc)
        _emit_progress(
            state=state,
            progress_callback=progress_callback,
            status="failed",
            clock=clock,
            total_units=total_units,
            current_phase=state.last_progress.current_phase if state.last_progress else None,
            current_phase_units=state.last_progress.current_phase_units if state.last_progress else 0,
            target_size_bytes=target_size_bytes,
            applied_units=state.last_progress.applied_units if state.last_progress else state.completed_units,
        )
        raise

    final_progress = _build_progress(
        status="applied",
        started_at_seconds=state.started_at_seconds if state.started_at_seconds is not None else clock(),
        now_seconds=clock(),
        total_units=total_units,
        completed_units=state.completed_units,
        current_phase="checkpoint_candidate",
        current_phase_units=1,
        target_size_bytes=target_size_bytes,
        completed_phases=state.completed_phases,
        checkpoint_applied=state.checkpoint_applied,
    )
    state.last_progress = final_progress
    if progress_callback is not None:
        progress_callback(final_progress)
    return SurrealDeltaSyncResult(
        progress=final_progress,
        applied_counts=applied_counts,
        skipped_phases=tuple(skipped_phases),
    )
def _change_record(change: SurrealDeltaChange) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "ref": change.ref,
        "table": change.table,
        "change_type": change.change_type.value,
        "row": dict(change.row),
    }
    if change.tombstone is not None:
        payload["tombstone"] = change.tombstone.model_dump()
    return payload
@dataclass(slots=True)
class FakeSurrealDeltaWriter:
    """In-memory idempotent writer used by the sync tests."""

    target_size_bytes: int | None = None
    fail_on_phase: str | None = None
    fail_after_batches: int | None = None
    active_sections: dict[str, dict[str, dict[str, Any]]] = field(default_factory=dict)
    tombstones: dict[str, dict[str, Any]] = field(default_factory=dict)
    checkpoint_candidate: dict[str, Any] | None = None
    write_counts: dict[str, int] = field(default_factory=dict)
    phase_batches: dict[str, int] = field(default_factory=dict)
    call_order: list[str] = field(default_factory=list)

    def _record_phase(self, phase: str, rows: Sequence[SurrealDeltaChange]) -> None:
        self.call_order.append(phase)
        self.phase_batches[phase] = self.phase_batches.get(phase, 0) + 1
        if self.fail_on_phase == phase and (
            self.fail_after_batches is not None
            and self.phase_batches[phase] > self.fail_after_batches
        ):
            raise RuntimeError(f"forced failure in {phase}")
        self.write_counts[phase] = self.write_counts.get(phase, 0) + len(rows)

    def delete_tombstones(self, rows: Sequence[SurrealDeltaChange]) -> int:
        self._record_phase("tombstones", rows)
        applied = 0
        for change in rows:
            removed = False
            for section_rows in self.active_sections.values():
                if section_rows.pop(change.ref, None) is not None:
                    removed = True
            tombstone_record = _change_record(change)
            if self.tombstones.get(change.ref) != tombstone_record:
                self.tombstones[change.ref] = tombstone_record
                removed = True
            if removed:
                applied += 1
        return applied

    def _write_section(self, phase: str, rows: Sequence[SurrealDeltaChange]) -> int:
        self._record_phase(phase, rows)
        section = self.active_sections.setdefault(phase, {})
        applied = 0
        for change in rows:
            record = _change_record(change)
            if section.get(change.ref) == record:
                continue
            section[change.ref] = record
            applied += 1
        return applied

    def write_documents(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("documents", rows)

    def write_source_units(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("source_units", rows)

    def write_chunks(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("chunks", rows)

    def write_chunk_file_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("chunk_file_bindings", rows)

    def write_provenance(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("provenance", rows)

    def write_resource_bindings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("resource_bindings", rows)

    def write_fingerprints(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("fingerprints", rows)

    def write_embeddings(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("embeddings", rows)

    def write_vector_components(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("vector_components", rows)

    def write_graph(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("graph", rows)

    def write_feedback(self, rows: Sequence[SurrealDeltaChange]) -> int:
        return self._write_section("feedback", rows)

    def write_checkpoint_candidate(self, candidate: SurrealDeltaCheckpointCandidate) -> int:
        self.call_order.append("checkpoint_candidate")
        record = candidate.model_dump()
        if self.checkpoint_candidate == record:
            return 0
        self.checkpoint_candidate = record
        return 1

    def snapshot(self) -> dict[str, Any]:
        return {
            "active_sections": {
                name: {ref: dict(record) for ref, record in rows.items()}
                for name, rows in self.active_sections.items()
            },
            "tombstones": {ref: dict(record) for ref, record in self.tombstones.items()},
            "checkpoint_candidate": (
                dict(self.checkpoint_candidate) if self.checkpoint_candidate is not None else None
            ),
            "write_counts": dict(self.write_counts),
            "call_order": list(self.call_order),
        }
