"""Phase 46 delta manifest contract for incremental Surreal sync."""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any, Protocol, runtime_checkable

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
