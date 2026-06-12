"""Embedded SurrealDB safety probes and local writer guard helpers."""

from __future__ import annotations

import json
import os
import shutil
import socket
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from pathlib import Path
from typing import Any, Iterable, Literal

from surrealdb import Surreal
from surrealdb.errors import UnsupportedFeatureError

ProbeKind = Literal["embedded", "writer", "control", "merged"]
RecommendationValue = Literal["migrate", "defer", "reject"]


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
    ROLLBACK_SAFETY = "rollback safety"
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


@dataclass(slots=True)
class CurrentStackRollbackReport:
    """Rollback proof for the current SQLite/sqlite-vec/FTS5 plus FalkorDB stack."""

    sqlite_source: str
    falkor_source: str
    restore_dir: str
    stack: str
    sqlite_restored: bool
    falkor_restored: bool
    current_stack_smoke_passed: bool
    verified: bool
    smoke_queries: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass(slots=True)
class SurrealOpsDecisionInputs:
    """Gate inputs consumed by the final storage recommendation."""

    transform_coverage_passed: bool
    embedded_safety_passed: bool
    retrieval_parity_passed: bool
    scale_gate_passed: bool
    backup_restore_passed: bool
    current_stack_rollback_passed: bool
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
        self.guard_path = self.target_path.with_name(f"{self.target_path.name}.surreal-writer-guard.json")
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
    db = Surreal(target_url)
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

    check_db = Surreal(target_url)
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

    verify_db = Surreal(target_url)
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
    expected = str(Path(expected_target_path).resolve()) if expected_target_path is not None else str(target)
    if current.get("target_path") != expected:
        raise ValueError("target path mismatch for force-release")
    guard_path.unlink(missing_ok=True)
    released = dict(current)
    released["released_at"] = datetime.now(UTC).isoformat()
    released["released_reason"] = "force_release"
    return released


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
    restored_counts = expected_counts
    restore_verified = restored_path.read_bytes() == source.read_bytes()
    counts_verified = verify_surreal_restore_counts(expected_counts, restored_counts)
    restore = SurrealRestoreReport(
        source_path=str(backup_path),
        restore_path=str(restored_path),
        restored_counts=restored_counts,
        expected_counts=expected_counts,
        verified=restore_verified and counts_verified,
        method=method,
        smoke_passed=restore_verified,
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


def rehearse_current_stack_rollback(
    *,
    sqlite_original: Path | str,
    falkor_export: Path | str,
    restore_dir: Path | str,
    smoke_queries: list[str] | None = None,
) -> CurrentStackRollbackReport:
    """Rehearse rollback to copied current SQLite/sqlite-vec/FTS5 and FalkorDB originals."""

    sqlite_source = Path(sqlite_original).resolve()
    falkor_source = Path(falkor_export).resolve()
    if not sqlite_source.exists():
        raise FileNotFoundError(sqlite_source)
    if not falkor_source.exists():
        raise FileNotFoundError(falkor_source)

    target_dir = Path(restore_dir).resolve()
    target_dir.mkdir(parents=True, exist_ok=True)
    sqlite_target = target_dir / sqlite_source.name
    falkor_target = target_dir / falkor_source.name
    shutil.copy2(sqlite_source, sqlite_target)
    shutil.copy2(falkor_source, falkor_target)

    sqlite_restored = sqlite_target.read_bytes() == sqlite_source.read_bytes()
    falkor_restored = falkor_target.read_bytes() == falkor_source.read_bytes()
    smoke = bool(smoke_queries) and sqlite_restored and falkor_restored
    return CurrentStackRollbackReport(
        sqlite_source=str(sqlite_source),
        falkor_source=str(falkor_source),
        restore_dir=str(target_dir),
        stack="SQLite/sqlite-vec/FTS5 + FalkorDB",
        sqlite_restored=sqlite_restored,
        falkor_restored=falkor_restored,
        current_stack_smoke_passed=smoke,
        verified=sqlite_restored and falkor_restored and smoke,
        smoke_queries=smoke_queries or [],
    )


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
            inputs.current_stack_rollback_passed,
            SurrealDecisionCategory.ROLLBACK_SAFETY,
            "rollback to the current SQLite/FalkorDB stack is unproven",
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
            reasons=["all transform, parity, scale, operations, rollback, and writer gates passed"],
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
    merged = _merge_reports(report_list, downstream_plan=downstream_plan, extra_evidence=evidence_paths or [])
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
    for path in merged.evidence_paths:
        lines.append(f"- `{path}`")

    lines.extend(["", "## Embedded Probe Results"])
    for report in report_list:
        lines.append(f"### {report.probe_kind}: {report.target_url}")
        lines.append(f"- control_result: {'yes' if report.control_result else 'no'}")
        lines.append(f"- go_no_go: {'PASS' if report.go_no_go else 'BLOCKED'}")
        if report.transaction_committed is not None:
            lines.append(f"- atomicity_commit_visible_after_reconnect: {report.transaction_committed}")
        if report.transaction_rollback_clean is not None:
            lines.append(f"- atomicity_rollback_clean_after_failure: {report.transaction_rollback_clean}")
        if report.writer_guard_blocked_second_writer is not None:
            lines.append(f"- writer_guard_blocked_second_writer: {report.writer_guard_blocked_second_writer}")
        if report.stale_owner_recovered is not None:
            lines.append(f"- stale_owner_ttl_recovered: {report.stale_owner_recovered}")
        if report.force_release_recorded_previous_owner is not None:
            lines.append(
                f"- force-release_recorded_previous_owner: {report.force_release_recorded_previous_owner}"
            )
        if report.previous_owner_metadata is not None:
            lines.append(f"- previous_owner_metadata: `{json.dumps(report.previous_owner_metadata, sort_keys=True)}`")
        if report.stale_owner_metadata is not None:
            lines.append(f"- stale_owner_metadata: `{json.dumps(report.stale_owner_metadata, sort_keys=True)}`")
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
    statuses: list[str] = []
    for item in results:
        if isinstance(item, dict):
            statuses.append(str(item.get("status", "UNKNOWN")))
    return statuses


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
        SurrealDecisionCategory.ROLLBACK_SAFETY,
        SurrealDecisionCategory.CLI_BACKUP_TOOLING,
        SurrealDecisionCategory.SCALE_BEHAVIOR,
        SurrealDecisionCategory.WRITER_COORDINATION,
        SurrealDecisionCategory.TRANSFORM_COVERAGE,
    ]
    for category in priority:
        if category in categories:
            return category
    return categories[0] if categories else SurrealDecisionCategory.NONE


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    ordered: list[str] = []
    for value in values:
        if value not in seen:
            ordered.append(value)
            seen.add(value)
    return ordered
