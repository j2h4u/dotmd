"""Phase 46 delta manifest contract for incremental Surreal sync."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, model_validator

DELTA_MANIFEST_SCHEMA_VERSION = "phase46_delta_manifest_v1"


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
