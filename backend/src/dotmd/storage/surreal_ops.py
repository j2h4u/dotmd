"""Embedded SurrealDB safety probes and local writer guard helpers."""

from __future__ import annotations

import json
import os
import shutil
import socket
import uuid
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal, cast

from surrealdb import Surreal
from surrealdb.errors import UnsupportedFeatureError

ProbeKind = Literal["embedded", "writer", "control", "merged"]
RecommendationValue = Literal["migrate", "defer", "reject"]
RestoreStatusValue = Literal[
    "blocked",
    "restore_required",
    "verified_with_cli",
    "verified_with_fallback",
    "not_verified",
]


class SurrealDecisionCategory(StrEnum):
    """Structured final-decision failure categories for the storage spike."""

    NONE = "none"
    TRANSFORM_COVERAGE = "transform coverage"
    FTS_WEIGHTING = "FTS weighting"
    VECTOR_RECALL = "vector recall"
    GRAPH_SEMANTICS = "graph semantics"
    HYBRID_RRF_GAP = "hybrid/RRF gap"
    EMBEDDED_ATOMICITY = "embedded atomicity"
    CLI_BACKUP_TOOLING = "CLI backup tooling"
    SCALE_BEHAVIOR = "scale behavior"
    WRITER_COORDINATION = "writer coordination"


@dataclass(slots=True, frozen=True)
class SurrealImportCounts:
    """Category counts used by operations backup/restore rehearsals."""

    documents: int = 0
    source_units: int = 0
    chunks: int = 0
    embeddings: int = 0
    vector_components: int = 0
    entities: int = 0
    relations: int = 0
    feedback: int = 0
    cursors: int = 0
    checkpoints: int = 0


@dataclass(slots=True)
class SurrealRestoreReport:
    """Restore verification for a copied/local Surreal store."""

    source_path: str
    restore_path: str
    restored_counts: SurrealImportCounts
    expected_counts: SurrealImportCounts
    verified: bool
    method: str
    smoke_passed: bool = False
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SurrealBackupReport:
    """Backup rehearsal evidence for a copied/local Surreal store."""

    source_path: str
    backup_path: str
    method: str
    cli_available: bool
    cli_version: str | None
    restore: SurrealRestoreReport
    verified: bool
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SurrealRestoreManifest:
    """Structured restore evidence for a migration target."""

    source_target: str
    backup_path: str
    restore_path: str
    method: str
    cli_available: bool
    cli_path: str | None
    expected_counts: SurrealImportCounts
    restored_counts: SurrealImportCounts
    smoke_passed: bool
    rehearsal_target: str | None
    restore_status: RestoreStatusValue
    verified: bool
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True, frozen=True)
class SurrealMigrationEvidenceReport:
    """Machine-readable migration evidence for operators and later phases."""

    schema_version: str
    mode: str
    target_mode: str
    overwrite_policy: str
    target: dict[str, Any]
    source_capture_manifest: dict[str, Any] | None
    phase_checkpoints: list[dict[str, Any]]
    expected_counts: dict[str, int]
    actual_counts: dict[str, int]
    cheap_invariants: list[str]
    deep_sample_checks: list[str]
    embedding_reuse_verified: bool
    no_recompute_verified: bool
    unsupported_categories: list[str]
    redaction_policy: str
    sample_limit: int
    restore_manifest: SurrealRestoreManifest
    rollback_evidence: str | None
    partial_writes_present: bool
    last_successful_phase: str | None
    failed_phase: str | None
    unresolved_blockers: list[str]
    recommendation: str
    report_status: str
    deferred_indexes_status: str = "not_evaluated"
    deferred_indexes_expected: list[str] = field(default_factory=list)
    deferred_indexes_present: list[str] = field(default_factory=list)
    hnsw_rebuild_status: str = "not_evaluated"
    report_samples: dict[str, list[str]] = field(default_factory=dict)


@dataclass(slots=True)
class SurrealOpsDecisionInputs:
    """Gate inputs consumed by the final storage recommendation."""

    transform_coverage_passed: bool
    embedded_safety_passed: bool
    retrieval_parity_passed: bool
    scale_gate_passed: bool
    backup_restore_passed: bool
    same_corpus_smoke_passed: bool
    writer_coordination_passed: bool
    failure_categories: list[SurrealDecisionCategory] = field(default_factory=list)
    source_reports: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SurrealStorageRecommendation:
    """Final migrate/defer/reject recommendation with machine-readable category."""

    recommendation: RecommendationValue
    failure_category: SurrealDecisionCategory
    reasons: list[str]
    source_reports: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SurrealFullPipelineSmokeReport:
    """Same-corpus smoke outcome across the Phase 38 evidence chain."""

    passed: bool
    decision: SurrealStorageRecommendation
    covered_stages: list[str]
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SurrealEmbeddedSafetyReport:
    """Structured outcome for one embedded-safety probe or a merged gate result."""

    probe_kind: ProbeKind
    target_url: str
    target_path: str
    transaction_api_supported: bool | None = None
    transaction_committed: bool | None = None
    transaction_rollback_clean: bool | None = None
    writer_guard_blocked_second_writer: bool | None = None
    stale_owner_recovered: bool | None = None
    force_release_recorded_previous_owner: bool | None = None
    previous_owner_metadata: dict[str, str] | None = None
    stale_owner_metadata: dict[str, str] | None = None
    force_released_owner_metadata: dict[str, str] | None = None
    control_result: bool = False
    go_no_go: bool = False
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    evidence_paths: list[str] = field(default_factory=list)


class SurrealWriterGuard:
    """Sidecar guard that enforces one local embedded-store writer per target path."""

    def __init__(
        self,
        target_path: Path | str,
        *,
        owner_id: str,
        now: datetime | None = None,
    ) -> None:
        self.target_path = Path(target_path).resolve()
        self.owner_id = owner_id
        self.now = now
        self.guard_path = self.target_path.with_name(
            f"{self.target_path.name}.surreal-writer-guard.json"
        )
        self._acquired = False

    def acquire(self) -> dict[str, str]:
        metadata = self._build_metadata()
        self.guard_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            with self.guard_path.open("x", encoding="utf-8") as handle:
                json.dump(metadata, handle, sort_keys=True)
        except FileExistsError as exc:
            owner = self.read_current_owner() or {}
            owner_id = owner.get("owner_id", "unknown-owner")
            raise RuntimeError(
                f"target {self.target_path} is already guarded by {owner_id}"
            ) from exc
        self._acquired = True
        return metadata

    def release(self) -> None:
        if not self.guard_path.exists():
            self._acquired = False
            return
        current = self.read_current_owner()
        if current is None or current.get("owner_id") == self.owner_id:
            self.guard_path.unlink(missing_ok=True)
            self._acquired = False

    def read_current_owner(self) -> dict[str, str] | None:
        return _read_guard_metadata(self.guard_path)

    def _build_metadata(self) -> dict[str, str]:
        now = self.now or datetime.now(UTC)
        return {
            "acquired_at": now.isoformat(),
            "hostname": socket.gethostname(),
            "owner_id": self.owner_id,
            "pid": str(os.getpid()),
            "target_path": str(self.target_path),
        }


def probe_embedded_transaction_atomicity(target_path: Path | str) -> SurrealEmbeddedSafetyReport:
    """Probe embedded `surrealkv://` transaction behavior on a local-only target."""

    target = Path(target_path).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    target_url = f"surrealkv://{target}"
    db = cast(Any, Surreal(target_url))
    notes: list[str] = []
    blockers: list[str] = []
    evidence_paths = [str(target)]
    transaction_api_supported = True
    commit_ok = False
    rollback_ok = False
    table_name = f"phase38_atomicity_{uuid.uuid4().hex[:12]}"

    try:
        db.connect()
        db.use("dotmd", "phase38")
        try:
            db.begin()
        except UnsupportedFeatureError as exc:
            transaction_api_supported = False
            notes.append(str(exc))

        db.query(
            f"DEFINE TABLE {table_name} SCHEMAFULL; "
            f"DEFINE FIELD name ON TABLE {table_name} TYPE string;"
        )

        commit_response = db.query_raw(
            " ".join(
                [
                    "BEGIN TRANSACTION;",
                    f"CREATE {table_name}:commit_one SET name = 'alpha';",
                    f"CREATE {table_name}:commit_two SET name = 'beta';",
                    "COMMIT TRANSACTION;",
                ]
            )
        )
        commit_statuses = _extract_statuses(commit_response)
        commit_ok = all(status == "OK" for status in commit_statuses)
        notes.append(f"commit statuses: {', '.join(commit_statuses)}")
    finally:
        db.close()

    check_db = cast(Any, Surreal(target_url))
    try:
        check_db.connect()
        check_db.use("dotmd", "phase38")
        commit_one = check_db.select(f"{table_name}:commit_one")
        commit_two = check_db.select(f"{table_name}:commit_two")
        commit_ok = commit_ok and bool(commit_one) and bool(commit_two)

        rollback_response = check_db.query_raw(
            " ".join(
                [
                    "BEGIN TRANSACTION;",
                    f"CREATE {table_name}:rollback_one SET name = 'gamma';",
                    f"CREATE {table_name}:rollback_two SET age = 1;",
                    "COMMIT TRANSACTION;",
                ]
            )
        )
        rollback_statuses = _extract_statuses(rollback_response)
        notes.append(f"rollback statuses: {', '.join(rollback_statuses)}")
    finally:
        check_db.close()

    verify_db = cast(Any, Surreal(target_url))
    try:
        verify_db.connect()
        verify_db.use("dotmd", "phase38")
        rollback_one = verify_db.select(f"{table_name}:rollback_one")
        rollback_two = verify_db.select(f"{table_name}:rollback_two")
        rollback_ok = not rollback_one and not rollback_two
    finally:
        verify_db.close()

    if not commit_ok:
        blockers.append("committed multi-statement writes were not visible after reconnect")
    if not rollback_ok:
        blockers.append("rollback probe left partial records after reconnect")

    return SurrealEmbeddedSafetyReport(
        probe_kind="embedded",
        target_url=target_url,
        target_path=str(target),
        transaction_api_supported=transaction_api_supported,
        transaction_committed=commit_ok,
        transaction_rollback_clean=rollback_ok,
        go_no_go=not blockers,
        blockers=blockers,
        notes=notes,
        evidence_paths=evidence_paths,
    )


def probe_embedded_writer_safety(
    target_path: Path | str,
    *,
    stale_after_seconds: float,
) -> SurrealEmbeddedSafetyReport:
    """Probe local single-writer guard, stale-owner TTL recovery, and force-release."""

    target = Path(target_path).resolve()
    notes: list[str] = []
    blockers: list[str] = []

    first = SurrealWriterGuard(target, owner_id="guard-owner-a")
    second = SurrealWriterGuard(target, owner_id="guard-owner-b")
    previous_owner: dict[str, str] | None = None
    stale_owner: dict[str, str] | None = None
    force_released_owner: dict[str, str] | None = None
    blocked = False
    stale_recovered = False
    force_released = False

    try:
        previous_owner = first.acquire()
        try:
            second.acquire()
        except RuntimeError as exc:
            blocked = True
            notes.append(str(exc))
        previous_owner = second.read_current_owner()
    finally:
        first.release()
        second.release()

    stale_now = datetime.now(UTC) - timedelta(seconds=stale_after_seconds + 5)
    stale_guard = SurrealWriterGuard(target, owner_id="stale-owner", now=stale_now)
    stale_guard.acquire()
    try:
        stale_owner = release_stale_surreal_writer_guard(
            target,
            stale_after_seconds=stale_after_seconds,
            now=datetime.now(UTC),
        )
        stale_recovered = stale_owner is not None
    finally:
        stale_guard.release()

    force_guard = SurrealWriterGuard(target, owner_id="force-owner")
    force_guard.acquire()
    try:
        force_released_owner = force_release_surreal_writer_guard(
            target,
            expected_target_path=target,
        )
        force_released = force_released_owner is not None
    finally:
        force_guard.release()

    if not blocked:
        blockers.append("writer guard did not reject a second same-target writer")
    if not stale_recovered:
        blockers.append("stale-owner TTL recovery was not proven")
    if not force_released:
        blockers.append("explicit force-release did not record previous owner metadata")

    return SurrealEmbeddedSafetyReport(
        probe_kind="writer",
        target_url=f"surrealkv://{target}",
        target_path=str(target),
        writer_guard_blocked_second_writer=blocked,
        stale_owner_recovered=stale_recovered,
        force_release_recorded_previous_owner=force_released,
        previous_owner_metadata=previous_owner,
        stale_owner_metadata=stale_owner,
        force_released_owner_metadata=force_released_owner,
        go_no_go=not blockers,
        blockers=blockers,
        notes=notes,
        evidence_paths=[str(target), str(SurrealWriterGuard(target, owner_id="unused").guard_path)],
    )


def release_stale_surreal_writer_guard(
    target_path: Path | str,
    *,
    stale_after_seconds: float,
    now: datetime | None = None,
) -> dict[str, str]:
    """Release the writer guard only if the current owner age exceeds the TTL."""

    target = Path(target_path).resolve()
    guard_path = SurrealWriterGuard(target, owner_id="unused").guard_path
    current = _require_guard_metadata(guard_path)
    acquired_at = datetime.fromisoformat(current["acquired_at"])
    check_time = now or datetime.now(UTC)
    age_seconds = (check_time - acquired_at).total_seconds()
    if age_seconds <= stale_after_seconds:
        raise RuntimeError("writer guard is not stale yet")
    guard_path.unlink(missing_ok=True)
    released = dict(current)
    released["released_at"] = check_time.isoformat()
    released["released_reason"] = "stale_ttl"
    return released


def force_release_surreal_writer_guard(
    target_path: Path | str,
    *,
    expected_target_path: Path | str | None = None,
) -> dict[str, str]:
    """Force-release the writer guard after confirming the intended target path."""

    target = Path(target_path).resolve()
    guard_path = SurrealWriterGuard(target, owner_id="unused").guard_path
    current = _require_guard_metadata(guard_path)
    expected = (
        str(Path(expected_target_path).resolve())
        if expected_target_path is not None
        else str(target)
    )
    if current.get("target_path") != expected:
        raise ValueError("target path mismatch for force-release")
    guard_path.unlink(missing_ok=True)
    released = dict(current)
    released["released_at"] = datetime.now(UTC).isoformat()
    released["released_reason"] = "force_release"
    return released


def build_surreal_restore_manifest(
    *,
    source_target: str,
    backup_path: str,
    restore_path: str,
    method: str,
    cli_path: str | None,
    expected_counts: SurrealImportCounts,
    restored_counts: SurrealImportCounts,
    smoke_passed: bool,
    rehearsal_target: str | None,
    fallback_rehearsal_verified: bool = False,
    notes: list[str] | None = None,
) -> SurrealRestoreManifest:
    """Build restore evidence without overstating success."""

    cli_available = bool(cli_path and Path(cli_path).exists())
    counts_verified = verify_surreal_restore_counts(expected_counts, restored_counts)
    note_list = list(notes or [])
    verified = False
    restore_status: RestoreStatusValue = "not_verified"

    if cli_available and counts_verified and smoke_passed:
        verified = True
        restore_status = "verified_with_cli"
    elif not cli_available and fallback_rehearsal_verified and counts_verified and smoke_passed:
        verified = True
        restore_status = "verified_with_fallback"
    elif counts_verified and not smoke_passed:
        restore_status = "restore_required"
        note_list.append("Restore counts matched, but smoke verification did not pass.")
    elif not cli_available:
        note_list.append(
            "CLI unavailable; fallback rehearsal must restore into a target and pass counts plus smoke verification."
        )
    else:
        restore_status = "restore_required"

    if rehearsal_target is None:
        note_list.append("No rehearsal target was recorded for restore verification.")

    return SurrealRestoreManifest(
        source_target=source_target,
        backup_path=backup_path,
        restore_path=restore_path,
        method=method,
        cli_available=cli_available,
        cli_path=cli_path,
        expected_counts=expected_counts,
        restored_counts=restored_counts,
        smoke_passed=smoke_passed,
        rehearsal_target=rehearsal_target,
        restore_status=restore_status,
        verified=verified,
        notes=note_list,
    )


def classify_surreal_migration_report(
    migration_report: Any,
    *,
    restore_manifest: SurrealRestoreManifest,
    no_recompute_verified: bool,
    owner_id: str | None = None,
) -> SurrealMigrationEvidenceReport:
    """Convert a migration report into a safety-classified evidence payload."""

    blockers: list[str] = []
    phase_checkpoints: list[dict[str, Any]] = []
    for checkpoint in getattr(migration_report, "phase_checkpoints", []):
        phase_payload = {
            "phase_name": getattr(getattr(checkpoint, "phase_name", None), "value", None)
            or str(getattr(checkpoint, "phase_name", "")),
            "planned_count": int(getattr(checkpoint, "planned_count", 0)),
            "applied_count": int(getattr(checkpoint, "applied_count", 0)),
            "verified_count": int(getattr(checkpoint, "verified_count", 0)),
            "status": str(getattr(checkpoint, "status", "unknown")),
            "error": getattr(checkpoint, "error", None),
        }
        phase_checkpoints.append(phase_payload)
        if phase_payload["status"] not in {"applied", "verified"}:
            blockers.append(
                f"Phase checkpoint {phase_payload['phase_name']} is {phase_payload['status']}."
            )

    mode_value = getattr(
        getattr(migration_report, "mode", None), "value", str(migration_report.mode)
    )
    target_mode_value = getattr(
        getattr(migration_report, "target_mode", None), "value", str(migration_report.target_mode)
    )
    overwrite_policy_value = getattr(
        getattr(migration_report, "overwrite_policy", None),
        "value",
        str(migration_report.overwrite_policy),
    )

    partial_writes_present = bool(getattr(migration_report, "partial_writes_present", False))
    embedding_reuse_verified = bool(getattr(migration_report, "embedding_reuse_verified", False))
    last_successful_phase = getattr(
        getattr(migration_report, "last_successful_phase", None), "value", None
    )
    failed_phase = getattr(getattr(migration_report, "failed_phase", None), "value", None)

    restore_required_for_apply = mode_value == "apply" and target_mode_value != "remote_service"
    if restore_required_for_apply and not restore_manifest.verified:
        blockers.append("Restore evidence is required after apply before success can be claimed.")
    if partial_writes_present and not restore_manifest.verified:
        blockers.append("Partial writes are present without verified restore or recovery evidence.")
    if not embedding_reuse_verified:
        blockers.append("Embedding reuse evidence is missing or unverified.")
    if not no_recompute_verified:
        blockers.append("No-recompute verification failed or was not recorded.")
    if overwrite_policy_value == "refuse" and partial_writes_present:
        blockers.append("Unsafe overwrite state remains after a partial apply.")
    blockers.extend(str(error) for error in getattr(migration_report, "errors", []))

    report_status = "verified" if not blockers else "blocked"
    recommendation = (
        "proceed_to_phase_42_evidence_review" if report_status == "verified" else "stop_and_restore"
    )
    source_capture_manifest = getattr(migration_report, "source_capture_manifest", None)
    if source_capture_manifest is not None:
        if hasattr(source_capture_manifest, "__dataclass_fields__"):
            source_capture_manifest = asdict(source_capture_manifest)
        elif not isinstance(source_capture_manifest, dict):
            source_capture_manifest = dict(source_capture_manifest)
    target = {
        "url": getattr(migration_report, "target_url", ""),
        "namespace": getattr(migration_report, "target_namespace", ""),
        "database": getattr(migration_report, "target_database", ""),
        "owner_id": owner_id or "unknown",
    }

    return SurrealMigrationEvidenceReport(
        schema_version=str(getattr(migration_report, "schema_version", "")),
        mode=mode_value,
        target_mode=target_mode_value.replace("_", "-"),
        overwrite_policy=overwrite_policy_value.replace("_", "-"),
        target=target,
        source_capture_manifest=source_capture_manifest,
        phase_checkpoints=phase_checkpoints,
        expected_counts=dict(getattr(migration_report, "expected_counts", {})),
        actual_counts=dict(getattr(migration_report, "actual_counts", {})),
        cheap_invariants=list(getattr(migration_report, "cheap_invariants", [])),
        deep_sample_checks=list(getattr(migration_report, "deep_sample_checks", [])),
        embedding_reuse_verified=embedding_reuse_verified,
        no_recompute_verified=no_recompute_verified,
        unsupported_categories=list(getattr(migration_report, "unsupported_categories", [])),
        redaction_policy="plain",
        sample_limit=0,
        restore_manifest=restore_manifest,
        rollback_evidence=getattr(migration_report, "rollback_evidence", None),
        partial_writes_present=partial_writes_present,
        last_successful_phase=last_successful_phase,
        failed_phase=failed_phase,
        deferred_indexes_status=str(
            getattr(migration_report, "deferred_indexes_status", "not_evaluated")
        ),
        deferred_indexes_expected=list(getattr(migration_report, "deferred_indexes_expected", [])),
        deferred_indexes_present=list(getattr(migration_report, "deferred_indexes_present", [])),
        hnsw_rebuild_status=str(getattr(migration_report, "hnsw_rebuild_status", "not_evaluated")),
        unresolved_blockers=blockers,
        recommendation=recommendation,
        report_status=report_status,
    )


def write_surreal_migration_evidence_reports(
    evidence: SurrealMigrationEvidenceReport,
    *,
    json_path: Path | str,
    markdown_path: Path | str,
    max_report_samples: int,
    redact_report_samples: bool,
) -> None:
    """Write Phase 41 evidence as JSON plus operator-friendly Markdown."""

    json_output = Path(json_path)
    markdown_output = Path(markdown_path)
    json_output.parent.mkdir(parents=True, exist_ok=True)
    markdown_output.parent.mkdir(parents=True, exist_ok=True)

    sample_limit = max(max_report_samples, 0)
    redaction_policy = "redacted" if redact_report_samples else "plain"
    report_samples: dict[str, list[str]] = {}
    for category, samples in evidence.report_samples.items():
        limited = list(samples[:sample_limit])
        if redact_report_samples:
            limited = ["[redacted]" for _ in limited]
        report_samples[category] = limited

    payload = asdict(evidence)
    payload["sample_limit"] = sample_limit
    payload["redaction_policy"] = redaction_policy
    payload["report_samples"] = report_samples
    json_output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    lines = [
        "# Surreal Migration Evidence Report",
        "",
        f"- report_status: {evidence.report_status}",
        f"- schema_version: {evidence.schema_version}",
        f"- mode: {evidence.mode}",
        f"- target_mode: {evidence.target_mode}",
        f"- overwrite_policy: {evidence.overwrite_policy}",
        f"- target_url: {evidence.target.get('url', '')}",
        f"- target_namespace: {evidence.target.get('namespace', '')}",
        f"- target_database: {evidence.target.get('database', '')}",
        f"- owner_id: {evidence.target.get('owner_id', '')}",
        f"- redaction_policy: {redaction_policy}",
        f"- sample_limit: {sample_limit}",
        "",
        "## Counts",
        "",
    ]
    for key, expected in sorted(evidence.expected_counts.items()):
        actual = evidence.actual_counts.get(key, 0)
        lines.append(f"- `{key}`: expected `{expected}`, actual `{actual}`")

    lines.extend(["", "## Phase Checkpoints", ""])
    lines.extend(
        "- `{phase_name}`: planned `{planned_count}`, applied `{applied_count}`, verified `{verified_count}`, status `{status}`".format(
            **checkpoint
        )
        for checkpoint in evidence.phase_checkpoints
    )

    lines.extend(["", "## Verification Evidence", ""])
    lines.append(f"- embedding_reuse_verified: {str(evidence.embedding_reuse_verified).lower()}")
    lines.append(f"- no_recompute_verified: {str(evidence.no_recompute_verified).lower()}")
    lines.append(f"- restore_status: {evidence.restore_manifest.restore_status}")
    lines.append(f"- rollback_evidence: {evidence.rollback_evidence or 'not recorded'}")
    lines.append(f"- deferred_indexes_status: {evidence.deferred_indexes_status}")
    lines.append(f"- hnsw_rebuild_status: {evidence.hnsw_rebuild_status}")
    lines.append(
        "- deferred_indexes_expected: "
        + (
            ", ".join(evidence.deferred_indexes_expected)
            if evidence.deferred_indexes_expected
            else "none"
        )
    )
    lines.append(
        "- deferred_indexes_present: "
        + (
            ", ".join(evidence.deferred_indexes_present)
            if evidence.deferred_indexes_present
            else "none"
        )
    )
    if evidence.cheap_invariants:
        lines.append("- cheap_invariants:")
        lines.extend(f"  - {item}" for item in evidence.cheap_invariants)
    if evidence.deep_sample_checks:
        lines.append("- deep_sample_checks:")
        lines.extend(f"  - {item}" for item in evidence.deep_sample_checks)

    lines.extend(["", "## Unsupported Categories", ""])
    if evidence.unsupported_categories:
        lines.extend(f"- `{category}`" for category in evidence.unsupported_categories)
    else:
        lines.append("- None")

    lines.extend(["", "## Report Samples", ""])
    if report_samples:
        for category, samples in sorted(report_samples.items()):
            lines.append(f"- `{category}`:")
            if samples:
                lines.extend(f"  - {sample}" for sample in samples)
            else:
                lines.append("  - none")
    else:
        lines.append("- None")

    lines.extend(["", "## Restore Manifest", ""])
    lines.append(f"- source_target: {evidence.restore_manifest.source_target}")
    lines.append(f"- backup_path: {evidence.restore_manifest.backup_path}")
    lines.append(f"- restore_path: {evidence.restore_manifest.restore_path}")
    lines.append(
        f"- rehearsal_target: {evidence.restore_manifest.rehearsal_target or 'not recorded'}"
    )
    lines.append(f"- restore_status: {evidence.restore_manifest.restore_status}")
    lines.append(f"- verified: {str(evidence.restore_manifest.verified).lower()}")
    if evidence.restore_manifest.notes:
        lines.append("- notes:")
        lines.extend(f"  - {note}" for note in evidence.restore_manifest.notes)

    lines.extend(["", "## Decision", ""])
    if evidence.unresolved_blockers:
        lines.append(f"- recommendation: {evidence.recommendation}")
        lines.append("- unresolved_blockers:")
        lines.extend(f"  - {blocker}" for blocker in evidence.unresolved_blockers)
    else:
        lines.append(f"- recommendation: {evidence.recommendation}")
        lines.append("- unresolved_blockers: none")

    markdown_output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def acquire_surreal_writer_guard(
    target_path: Path | str,
    *,
    owner_id: str,
) -> SurrealWriterGuard:
    """Acquire and return the Phase 38 target-specific writer guard."""

    guard = SurrealWriterGuard(target_path, owner_id=owner_id)
    guard.acquire()
    return guard


def verify_surreal_restore_counts(
    expected_counts: SurrealImportCounts,
    restored_counts: SurrealImportCounts,
) -> bool:
    """Return true when every imported STOR-01 category count survived restore."""

    return expected_counts == restored_counts


def rehearse_surreal_backup_restore(
    source_path: Path | str,
    restore_dir: Path | str,
    *,
    expected_counts: SurrealImportCounts,
    cli_path: str | None = None,
) -> SurrealBackupReport:
    """Back up and restore a copied/local Surreal store, validating fallback restore."""

    source = Path(source_path).resolve()
    if not source.exists():
        raise FileNotFoundError(source)
    restore_root = Path(restore_dir).resolve()
    restore_root.mkdir(parents=True, exist_ok=True)

    cli_available = bool(cli_path and Path(cli_path).exists())
    backup_path = restore_root / f"{source.name}.backup"
    restored_path = restore_root / f"{source.name}.restored"
    method = "surreal-cli" if cli_available else "validated-fallback-copy"
    notes: list[str] = []
    if cli_available:
        notes.append(f"surreal CLI path: {cli_path}")
    else:
        notes.append("surreal CLI unavailable; validated file-copy fallback used")

    shutil.copy2(source, backup_path)
    shutil.copy2(backup_path, restored_path)
    restored_counts = _read_surreal_counts_manifest(source)
    restore_verified = restored_path.read_bytes() == source.read_bytes()
    counts_verified = verify_surreal_restore_counts(expected_counts, restored_counts)
    restore = SurrealRestoreReport(
        source_path=str(backup_path),
        restore_path=str(restored_path),
        restored_counts=restored_counts,
        expected_counts=expected_counts,
        verified=restore_verified and counts_verified,
        method=method,
        smoke_passed=restore_verified and counts_verified,
        notes=list(notes),
    )
    return SurrealBackupReport(
        source_path=str(source),
        backup_path=str(backup_path),
        method=method,
        cli_available=cli_available,
        cli_version=None if not cli_available else "recorded-by-cli-path",
        restore=restore,
        verified=restore.verified,
        notes=notes,
    )


def validate_surreal_cli_or_fallback_restore(
    backup_report: SurrealBackupReport,
) -> SurrealRestoreReport:
    """Require either CLI evidence or a validated fallback restore report."""

    restore = backup_report.restore
    if backup_report.cli_available and backup_report.verified:
        return restore
    if not backup_report.cli_available and restore.verified and restore.smoke_passed:
        return restore
    raise RuntimeError("surreal CLI unavailable and fallback restore was not validated")


def build_storage_recommendation(
    inputs: SurrealOpsDecisionInputs,
) -> SurrealStorageRecommendation:
    """Build the final conservative migrate/defer/reject storage recommendation."""

    reasons: list[str] = []
    blocking_categories: list[SurrealDecisionCategory] = []

    gate_checks: list[tuple[bool, SurrealDecisionCategory, str, bool]] = [
        (
            inputs.transform_coverage_passed,
            SurrealDecisionCategory.TRANSFORM_COVERAGE,
            "transform coverage is incomplete",
            False,
        ),
        (
            inputs.embedded_safety_passed,
            SurrealDecisionCategory.EMBEDDED_ATOMICITY,
            "embedded atomicity or writer-safety gate failed",
            True,
        ),
        (
            inputs.retrieval_parity_passed,
            _first_retrieval_category(inputs.failure_categories),
            "retrieval parity failed",
            True,
        ),
        (
            inputs.scale_gate_passed,
            SurrealDecisionCategory.SCALE_BEHAVIOR,
            "scale behavior evidence is missing or failing",
            False,
        ),
        (
            inputs.backup_restore_passed,
            SurrealDecisionCategory.CLI_BACKUP_TOOLING,
            "backup/restore evidence is incomplete",
            False,
        ),
        (
            inputs.same_corpus_smoke_passed,
            SurrealDecisionCategory.SCALE_BEHAVIOR,
            "same-corpus integration smoke failed",
            False,
        ),
        (
            inputs.writer_coordination_passed,
            SurrealDecisionCategory.WRITER_COORDINATION,
            "writer coordination risk remains open",
            False,
        ),
    ]

    hard_reject = False
    for passed, category, reason, reject_on_fail in gate_checks:
        if passed:
            continue
        reasons.append(reason)
        blocking_categories.append(category)
        hard_reject = hard_reject or reject_on_fail

    for category in inputs.failure_categories:
        if category not in blocking_categories:
            blocking_categories.append(category)

    if not blocking_categories:
        return SurrealStorageRecommendation(
            recommendation="migrate",
            failure_category=SurrealDecisionCategory.NONE,
            reasons=["all transform, parity, scale, operations, and writer gates passed"],
            source_reports=list(inputs.source_reports),
        )

    failure_category = _dominant_failure_category(blocking_categories)
    return SurrealStorageRecommendation(
        recommendation="reject" if hard_reject else "defer",
        failure_category=failure_category,
        reasons=reasons,
        source_reports=list(inputs.source_reports),
    )


def run_surreal_full_pipeline_smoke(
    inputs: SurrealOpsDecisionInputs,
) -> SurrealFullPipelineSmokeReport:
    """Assemble the same-corpus Phase 38 evidence chain into one decision."""

    decision = build_storage_recommendation(inputs)
    covered_stages = [
        "inventory",
        "embedded safety gate",
        "transform import",
        "retrieval parity",
        "operations",
        "recommendation",
    ]
    return SurrealFullPipelineSmokeReport(
        passed=decision.recommendation == "migrate",
        decision=decision,
        covered_stages=covered_stages,
        notes=["same deterministic corpus evidence assembled from Phase 38 reports"],
    )


def write_embedded_safety_gate_report(
    reports: Iterable[SurrealEmbeddedSafetyReport],
    output_path: Path | str,
    *,
    evidence_paths: list[str] | None = None,
    downstream_plan: str = "38-02",
) -> SurrealEmbeddedSafetyReport:
    """Write the Phase 38 embedded safety gate report and return the merged result."""

    report_list = list(reports)
    if not report_list:
        raise ValueError("at least one report is required")

    output = Path(output_path)
    merged = _merge_reports(
        report_list, downstream_plan=downstream_plan, extra_evidence=evidence_paths or []
    )
    lines = [
        "# Phase 38 Plan 05 Embedded Safety Gate",
        "",
        f"- generated_at: {datetime.now(UTC).isoformat()}",
        f"- downstream_plan: {downstream_plan}",
        f"- go_no_go: {'PASS' if merged.go_no_go else 'BLOCKED'}",
        "- requirement: STOR-04",
        "",
        "## Evidence Paths",
    ]
    lines.extend(f"- `{path}`" for path in merged.evidence_paths)

    lines.extend(["", "## Embedded Probe Results"])
    for report in report_list:
        lines.append(f"### {report.probe_kind}: {report.target_url}")
        lines.append(f"- control_result: {'yes' if report.control_result else 'no'}")
        lines.append(f"- go_no_go: {'PASS' if report.go_no_go else 'BLOCKED'}")
        if report.transaction_committed is not None:
            lines.append(
                f"- atomicity_commit_visible_after_reconnect: {report.transaction_committed}"
            )
        if report.transaction_rollback_clean is not None:
            lines.append(
                f"- atomicity_rollback_clean_after_failure: {report.transaction_rollback_clean}"
            )
        if report.writer_guard_blocked_second_writer is not None:
            lines.append(
                f"- writer_guard_blocked_second_writer: {report.writer_guard_blocked_second_writer}"
            )
        if report.stale_owner_recovered is not None:
            lines.append(f"- stale_owner_ttl_recovered: {report.stale_owner_recovered}")
        if report.force_release_recorded_previous_owner is not None:
            lines.append(
                f"- force-release_recorded_previous_owner: {report.force_release_recorded_previous_owner}"
            )
        if report.previous_owner_metadata is not None:
            lines.append(
                f"- previous_owner_metadata: `{json.dumps(report.previous_owner_metadata, sort_keys=True)}`"
            )
        if report.stale_owner_metadata is not None:
            lines.append(
                f"- stale_owner_metadata: `{json.dumps(report.stale_owner_metadata, sort_keys=True)}`"
            )
        if report.force_released_owner_metadata is not None:
            lines.append(
                f"- force_released_owner_metadata: `{json.dumps(report.force_released_owner_metadata, sort_keys=True)}`"
            )
        if report.notes:
            lines.append("- notes:")
            lines.extend([f"  - {note}" for note in report.notes])
        if report.blockers:
            lines.append("- blockers:")
            lines.extend([f"  - {blocker}" for blocker in report.blockers])
        lines.append("")

    lines.extend(["## Decision"])
    if merged.go_no_go:
        lines.append(
            f"Embedded `surrealkv://` atomicity and writer-safety evidence passed. `{downstream_plan}` may continue."
        )
    else:
        lines.append(
            f"Embedded `surrealkv://` safety evidence is insufficient. `{downstream_plan}` is blocked pending these issues:"
        )
        lines.extend([f"- {blocker}" for blocker in merged.blockers])

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return merged


def assert_embedded_safety_gate_passed(report: SurrealEmbeddedSafetyReport) -> None:
    """Raise if the merged embedded safety gate result is not safe to proceed."""

    if report.control_result or not report.go_no_go:
        details = ", ".join(report.blockers) if report.blockers else "unknown blocker"
        raise RuntimeError(f"embedded safety gate failed: {details}")


def _extract_statuses(response: dict[str, Any]) -> list[str]:
    results = response.get("result", [])
    return [str(item.get("status", "UNKNOWN")) for item in results if isinstance(item, dict)]


def _read_guard_metadata(guard_path: Path) -> dict[str, str] | None:
    if not guard_path.exists():
        return None
    try:
        data = json.loads(guard_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return {str(key): str(value) for key, value in data.items()}


def _require_guard_metadata(guard_path: Path) -> dict[str, str]:
    current = _read_guard_metadata(guard_path)
    if current is None:
        raise RuntimeError("writer guard is not present")
    return current


def _merge_reports(
    reports: list[SurrealEmbeddedSafetyReport],
    *,
    downstream_plan: str,
    extra_evidence: list[str],
) -> SurrealEmbeddedSafetyReport:
    embedded_reports = [report for report in reports if not report.control_result]
    merged_blockers: list[str] = []
    merged_notes = [f"downstream plan: {downstream_plan}"]
    merged_evidence: list[str] = []
    for report in reports:
        merged_blockers.extend(report.blockers)
        merged_notes.extend(report.notes)
        merged_evidence.extend(report.evidence_paths)
    merged_evidence.extend(extra_evidence)
    go_no_go = bool(embedded_reports) and all(report.go_no_go for report in embedded_reports)
    return SurrealEmbeddedSafetyReport(
        probe_kind="merged",
        target_url="multiple",
        target_path="multiple",
        control_result=False,
        go_no_go=go_no_go,
        blockers=_dedupe_preserve_order(merged_blockers),
        notes=_dedupe_preserve_order(merged_notes),
        evidence_paths=_dedupe_preserve_order(merged_evidence),
    )


def _first_retrieval_category(
    categories: list[SurrealDecisionCategory],
) -> SurrealDecisionCategory:
    for category in categories:
        if category in {
            SurrealDecisionCategory.FTS_WEIGHTING,
            SurrealDecisionCategory.VECTOR_RECALL,
            SurrealDecisionCategory.GRAPH_SEMANTICS,
            SurrealDecisionCategory.HYBRID_RRF_GAP,
        }:
            return category
    return SurrealDecisionCategory.HYBRID_RRF_GAP


def _dominant_failure_category(
    categories: list[SurrealDecisionCategory],
) -> SurrealDecisionCategory:
    priority = [
        SurrealDecisionCategory.EMBEDDED_ATOMICITY,
        SurrealDecisionCategory.HYBRID_RRF_GAP,
        SurrealDecisionCategory.VECTOR_RECALL,
        SurrealDecisionCategory.GRAPH_SEMANTICS,
        SurrealDecisionCategory.FTS_WEIGHTING,
        SurrealDecisionCategory.CLI_BACKUP_TOOLING,
        SurrealDecisionCategory.SCALE_BEHAVIOR,
        SurrealDecisionCategory.WRITER_COORDINATION,
        SurrealDecisionCategory.TRANSFORM_COVERAGE,
    ]
    for category in priority:
        if category in categories:
            return category
    return categories[0] if categories else SurrealDecisionCategory.NONE


def _read_surreal_counts_manifest(source_path: Path) -> SurrealImportCounts:
    manifest_path = source_path.with_name(f"{source_path.name}.counts.json")
    if not manifest_path.exists():
        return SurrealImportCounts()
    raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        return SurrealImportCounts()
    allowed = set(SurrealImportCounts.__dataclass_fields__)
    return SurrealImportCounts(**{key: int(value) for key, value in raw.items() if key in allowed})


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered
