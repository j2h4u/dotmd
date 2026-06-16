"""CLI runner for Phase 41 Surreal migration evidence and reporting."""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotmd.ingestion.migrate_surreal import (
    SurrealMigrationManifest,
    SurrealMigrationMode,
    SurrealOverwritePolicy,
    SurrealTargetMode,
    SurrealVerificationDepth,
    build_surreal_migration_manifest,
    run_surreal_migration,
    verify_surreal_migration_target,
)
from dotmd.storage.surreal_ops import (
    SurrealImportCounts,
    SurrealMigrationEvidenceReport,
    SurrealRestoreManifest,
    build_surreal_restore_manifest,
    classify_surreal_migration_report,
    write_surreal_migration_evidence_reports,
)


@dataclass(slots=True, frozen=True)
class SurrealMigrationRunnerConfig:
    """Filesystem inputs and outputs for one migration command."""

    mode: str
    target_mode: str
    sqlite_snapshot: Path
    source_capture_manifest_json: Path | None
    graph_export_json: Path
    feedback_export_json: Path
    target_url: str
    target_namespace: str = "dotmd"
    target_database: str = "phase41_migration"
    gate_report: Path | None = None
    overwrite_policy: str = "refuse"
    verification_depth: str = "cheap"
    manifest_json: Path | None = None
    report_json: Path | None = None
    report_markdown: Path | None = None
    progress_json: Path | None = None
    resume_from_progress: bool = False
    restore_manifest_json: Path | None = None
    owner_id: str = "unknown"
    max_report_samples: int = 0
    redact_report_samples: bool = False


@dataclass(slots=True, frozen=True)
class SurrealMigrationRunnerResult:
    """Structured command outcome."""

    report: SurrealMigrationEvidenceReport
    restore_manifest: SurrealRestoreManifest
    exit_code: int


def _normalize_mode(value: str) -> SurrealMigrationMode:
    normalized = value.strip().lower()
    mapping = {
        "plan": SurrealMigrationMode.PLAN,
        "dry-run": SurrealMigrationMode.DRY_RUN,
        "apply": SurrealMigrationMode.APPLY,
        "verify": SurrealMigrationMode.VERIFY,
        "report": SurrealMigrationMode.VERIFY,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported mode: {value}") from exc


def _normalize_target_mode(value: str) -> SurrealTargetMode:
    normalized = value.strip().lower()
    mapping = {
        "embedded-local": SurrealTargetMode.EMBEDDED_LOCAL,
        "embedded_local": SurrealTargetMode.EMBEDDED_LOCAL,
        "remote-service": SurrealTargetMode.REMOTE_SERVICE,
        "remote_service": SurrealTargetMode.REMOTE_SERVICE,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported target mode: {value}") from exc


def _normalize_verification_depth(value: str) -> SurrealVerificationDepth:
    normalized = value.strip().lower()
    mapping = {
        "cheap": SurrealVerificationDepth.CHEAP,
        "deep": SurrealVerificationDepth.DEEP,
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported verification depth: {value}") from exc


def _normalize_overwrite_policy(value: str) -> str:
    normalized = value.strip().lower().replace("-", "_")
    mapping = {
        "refuse": "refuse",
        "explicit_replace": "explicit_replace",
    }
    try:
        return mapping[normalized]
    except KeyError as exc:
        raise ValueError(f"unsupported overwrite policy: {value}") from exc


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{path.name} line {exc.lineno} column {exc.colno}: invalid JSON") from exc


def _require_row_fields(
    *,
    path: Path,
    category: str,
    rows: list[dict[str, Any]],
    required_fields: tuple[str, ...],
) -> None:
    for row_index, row in enumerate(rows):
        for field_name in required_fields:
            value = row.get(field_name)
            if value in {None, ""}:
                raise ValueError(
                    f"{path.name}: category {category} row {row_index} field {field_name} is required"
                )


def load_graph_rows_from_json(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    rows = payload.get("rows", {})
    if not isinstance(rows, dict):
        raise ValueError(f"{path.name}: category rows must be an object")

    entities = rows.get("entities", [])
    relations = rows.get("relations", [])
    files = rows.get("files", [])
    sections = rows.get("sections", [])
    tags = rows.get("tags", [])
    for category_name, category_rows in {
        "entities": entities,
        "relations": relations,
        "files": files,
        "sections": sections,
        "tags": tags,
    }.items():
        if not isinstance(category_rows, list):
            raise ValueError(f"{path.name}: category {category_name} must be a list")
        if category_name == "entities":
            _require_row_fields(
                path=path,
                category=category_name,
                rows=category_rows,
                required_fields=("name",),
            )
        if category_name == "relations":
            _require_row_fields(
                path=path,
                category=category_name,
                rows=category_rows,
                required_fields=("relation_id", "source_id", "target_id"),
            )
    return payload


def load_feedback_rows_from_json(path: Path) -> dict[str, Any]:
    payload = _read_json(path)
    if not isinstance(payload, dict):
        raise ValueError(f"{path.name}: expected JSON object")
    rows = payload.get("rows", [])
    if not isinstance(rows, list):
        raise ValueError(f"{path.name}: category feedback must be a list")
    _require_row_fields(
        path=path,
        category="feedback",
        rows=rows,
        required_fields=("id", "submitted_at", "message"),
    )
    return payload


def _manifest_to_jsonable(manifest: SurrealMigrationManifest) -> dict[str, Any]:
    payload = asdict(manifest)
    payload["target_mode"] = manifest.target_mode.value
    return payload


def _counts_from_actual_counts(actual_counts: dict[str, int]) -> SurrealImportCounts:
    return SurrealImportCounts(
        documents=int(actual_counts.get("documents", 0)),
        source_units=int(actual_counts.get("source_units", 0)),
        chunks=int(actual_counts.get("chunks", 0)),
        embeddings=int(actual_counts.get("embeddings", 0)),
        vector_components=int(actual_counts.get("vector_components", 0)),
        entities=int(actual_counts.get("graph_entities", 0)),
        relations=int(actual_counts.get("graph_relations", 0)),
        feedback=int(actual_counts.get("feedback", 0)),
        cursors=int(actual_counts.get("cursors", 0)),
        checkpoints=int(actual_counts.get("checkpoints", 0)),
    )


def _counts_from_expected_counts(expected_counts: dict[str, int]) -> SurrealImportCounts:
    return SurrealImportCounts(
        documents=int(expected_counts.get("documents", 0)),
        source_units=int(expected_counts.get("source_units", 0)),
        chunks=int(expected_counts.get("chunks", 0)),
        embeddings=int(expected_counts.get("embeddings", 0)),
        vector_components=int(expected_counts.get("vector_components", 0)),
        entities=int(expected_counts.get("graph_entities", 0)),
        relations=int(expected_counts.get("graph_relations", 0)),
        feedback=int(expected_counts.get("feedback", 0)),
        cursors=int(expected_counts.get("cursors", 0)),
        checkpoints=int(expected_counts.get("checkpoints", 0)),
    )


def _rehearse_restore(
    *,
    config: SurrealMigrationRunnerConfig,
    mode: SurrealMigrationMode,
    target_mode: SurrealTargetMode,
    overwrite_policy: str,
    expected_counts: dict[str, int],
) -> SurrealRestoreManifest:
    expected = _counts_from_expected_counts(expected_counts)
    target_path = config.target_url.removeprefix("surrealkv://")
    if (
        mode is not SurrealMigrationMode.APPLY
        or target_mode is not SurrealTargetMode.EMBEDDED_LOCAL
    ):
        return build_surreal_restore_manifest(
            source_target=config.target_url,
            backup_path=str(config.restore_manifest_json or ""),
            restore_path=str(config.restore_manifest_json or ""),
            method="surreal-export-import",
            cli_path=None,
            expected_counts=expected,
            restored_counts=SurrealImportCounts(),
            smoke_passed=False,
            rehearsal_target=None,
            notes=["Restore rehearsal only runs for embedded-local apply mode."],
        )

    source_file = Path(target_path)
    if not source_file.exists():
        return build_surreal_restore_manifest(
            source_target=config.target_url,
            backup_path=str(config.restore_manifest_json or ""),
            restore_path=str(config.restore_manifest_json or ""),
            method="validated-fallback-copy",
            cli_path=None,
            expected_counts=expected,
            restored_counts=SurrealImportCounts(),
            smoke_passed=False,
            rehearsal_target=None,
            notes=["Target file does not exist, so restore rehearsal could not run."],
        )

    restore_root = (config.restore_manifest_json or source_file.with_suffix(".restore.json")).parent
    restore_root.mkdir(parents=True, exist_ok=True)
    backup_path = restore_root / f"{source_file.name}.backup"
    restore_path = restore_root / f"{source_file.name}.restored"
    if source_file.is_dir():
        shutil.copytree(source_file, backup_path, dirs_exist_ok=True)
        shutil.copytree(backup_path, restore_path, dirs_exist_ok=True)
    else:
        shutil.copy2(source_file, backup_path)
        shutil.copy2(backup_path, restore_path)

    rehearsal_report = verify_surreal_migration_target(
        sqlite_snapshot_path=config.sqlite_snapshot,
        graph_export_path=config.graph_export_json,
        feedback_export_path=config.feedback_export_json,
        target_url=f"surrealkv://{restore_path}",
        target_mode=target_mode,
        target_namespace=config.target_namespace,
        target_database=config.target_database,
        verification_depth=_normalize_verification_depth(config.verification_depth),
        overwrite_policy=getattr(
            SurrealOverwritePolicy,
            overwrite_policy.upper(),
        ),
    )
    restored_counts = _counts_from_actual_counts(rehearsal_report.actual_counts)
    return build_surreal_restore_manifest(
        source_target=config.target_url,
        backup_path=str(backup_path),
        restore_path=str(restore_path),
        method="validated-fallback-copy",
        cli_path=None,
        expected_counts=expected,
        restored_counts=restored_counts,
        smoke_passed=rehearsal_report.verified,
        rehearsal_target=str(restore_path),
        fallback_rehearsal_verified=rehearsal_report.verified,
        notes=["Embedded-local restore rehearsal verified counts and smoke checks."],
    )


def _build_evidence_report(
    *,
    config: SurrealMigrationRunnerConfig,
    migration_report: Any,
    restore_manifest: SurrealRestoreManifest,
) -> SurrealMigrationEvidenceReport:
    evidence = classify_surreal_migration_report(
        migration_report,
        restore_manifest=restore_manifest,
        no_recompute_verified=getattr(migration_report, "recompute_guard_status", "") == "passed",
        owner_id=config.owner_id,
    )
    samples = {
        "feedback_messages": list(restore_manifest.notes[: max(config.max_report_samples, 0)]),
        "graph_metadata": list(getattr(migration_report, "unsupported_categories", []))[
            : max(config.max_report_samples, 0)
        ],
    }
    return SurrealMigrationEvidenceReport(
        schema_version=evidence.schema_version,
        mode=evidence.mode,
        target_mode=evidence.target_mode,
        overwrite_policy=evidence.overwrite_policy,
        target=evidence.target,
        source_capture_manifest=evidence.source_capture_manifest,
        phase_checkpoints=evidence.phase_checkpoints,
        expected_counts=evidence.expected_counts,
        actual_counts=evidence.actual_counts,
        cheap_invariants=evidence.cheap_invariants,
        deep_sample_checks=evidence.deep_sample_checks,
        embedding_reuse_verified=evidence.embedding_reuse_verified,
        no_recompute_verified=evidence.no_recompute_verified,
        unsupported_categories=evidence.unsupported_categories,
        redaction_policy="redacted" if config.redact_report_samples else "plain",
        sample_limit=max(config.max_report_samples, 0),
        restore_manifest=restore_manifest,
        rollback_evidence=evidence.rollback_evidence,
        partial_writes_present=evidence.partial_writes_present,
        last_successful_phase=evidence.last_successful_phase,
        failed_phase=evidence.failed_phase,
        unresolved_blockers=evidence.unresolved_blockers,
        recommendation=evidence.recommendation,
        report_status=evidence.report_status,
        report_samples=samples,
    )


def run_migration_command(config: SurrealMigrationRunnerConfig) -> SurrealMigrationRunnerResult:
    """Run the requested migration command and write requested artifacts."""

    mode = _normalize_mode(config.mode)
    target_mode = _normalize_target_mode(config.target_mode)
    overwrite_policy = _normalize_overwrite_policy(config.overwrite_policy)
    verification_depth = _normalize_verification_depth(config.verification_depth)

    if mode is SurrealMigrationMode.APPLY and config.source_capture_manifest_json is None:
        raise ValueError("source_capture_manifest_json is required for apply mode")
    if (
        mode is SurrealMigrationMode.APPLY
        and target_mode is SurrealTargetMode.EMBEDDED_LOCAL
        and config.gate_report is None
    ):
        raise ValueError("gate_report is required for apply mode")
    if mode is SurrealMigrationMode.APPLY and not config.target_url:
        raise ValueError("target_url is required for apply mode")

    load_graph_rows_from_json(config.graph_export_json)
    load_feedback_rows_from_json(config.feedback_export_json)

    manifest = build_surreal_migration_manifest(
        sqlite_snapshot_path=config.sqlite_snapshot,
        graph_export_path=config.graph_export_json,
        feedback_export_path=config.feedback_export_json,
        target_url=config.target_url
        or f"surrealkv://{config.sqlite_snapshot.with_suffix('.surreal.db')}",
        target_mode=target_mode,
        target_namespace=config.target_namespace,
        target_database=config.target_database,
    )
    if config.manifest_json is not None:
        config.manifest_json.parent.mkdir(parents=True, exist_ok=True)
        config.manifest_json.write_text(
            json.dumps(
                _manifest_to_jsonable(manifest), ensure_ascii=False, indent=2, sort_keys=True
            )
            + "\n",
            encoding="utf-8",
        )
    if config.source_capture_manifest_json is not None:
        config.source_capture_manifest_json.parent.mkdir(parents=True, exist_ok=True)
        config.source_capture_manifest_json.write_text(
            json.dumps(
                asdict(manifest.source_capture_manifest),
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    migration_report = run_surreal_migration(
        mode=mode,
        sqlite_snapshot_path=config.sqlite_snapshot,
        graph_export_path=config.graph_export_json,
        feedback_export_path=config.feedback_export_json,
        target_url=manifest.target_url,
        target_mode=target_mode,
        target_namespace=config.target_namespace,
        target_database=config.target_database,
        overwrite_policy=getattr(
            SurrealOverwritePolicy,
            overwrite_policy.upper(),
        ),
        gate_report_path=config.gate_report,
        verification_depth=verification_depth,
        progress_path=config.progress_json,
        resume_from_progress=config.resume_from_progress,
    )

    restore_manifest = _rehearse_restore(
        config=config,
        mode=mode,
        target_mode=target_mode,
        overwrite_policy=overwrite_policy,
        expected_counts=manifest.expected_counts,
    )
    evidence = _build_evidence_report(
        config=config,
        migration_report=migration_report,
        restore_manifest=restore_manifest,
    )

    if config.restore_manifest_json is not None:
        config.restore_manifest_json.parent.mkdir(parents=True, exist_ok=True)
        config.restore_manifest_json.write_text(
            json.dumps(asdict(restore_manifest), ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    if config.report_json is not None and config.report_markdown is not None:
        write_surreal_migration_evidence_reports(
            evidence,
            json_path=config.report_json,
            markdown_path=config.report_markdown,
            max_report_samples=config.max_report_samples,
            redact_report_samples=config.redact_report_samples,
        )

    return SurrealMigrationRunnerResult(
        report=evidence,
        restore_manifest=restore_manifest,
        exit_code=0 if evidence.report_status == "verified" else 1,
    )


def build_parser() -> argparse.ArgumentParser:
    """Create the CLI parser for standalone execution."""

    parser = argparse.ArgumentParser(description="Run Phase 41 Surreal migration workflows.")
    parser.add_argument(
        "--mode",
        required=True,
        choices=("plan", "dry-run", "apply", "verify", "report"),
    )
    parser.add_argument(
        "--target-mode",
        required=True,
        choices=("embedded-local", "remote-service"),
    )
    parser.add_argument("--sqlite-snapshot", required=True, type=Path)
    parser.add_argument("--source-capture-manifest-json", type=Path, default=None)
    parser.add_argument("--target-url", default="")
    parser.add_argument("--target-namespace", default="dotmd")
    parser.add_argument("--target-database", default="phase41_migration")
    parser.add_argument("--graph-export-json", required=True, type=Path)
    parser.add_argument("--feedback-export-json", required=True, type=Path)
    parser.add_argument("--gate-report", type=Path, default=None)
    parser.add_argument(
        "--overwrite-policy",
        default="refuse",
        choices=("refuse", "explicit-replace"),
    )
    parser.add_argument(
        "--verification-depth",
        default="cheap",
        choices=("cheap", "deep"),
    )
    parser.add_argument("--manifest-json", type=Path, default=None)
    parser.add_argument("--report-json", type=Path, default=None)
    parser.add_argument("--report-markdown", type=Path, default=None)
    parser.add_argument("--progress-json", type=Path, default=None)
    parser.add_argument("--resume-from-progress", action="store_true")
    parser.add_argument("--restore-manifest-json", type=Path, default=None)
    parser.add_argument("--owner-id", default="unknown")
    parser.add_argument("--max-report-samples", type=int, default=0)
    parser.add_argument("--redact-report-samples", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Parse arguments, run the migration command, and return the exit code."""

    args = build_parser().parse_args(argv)
    result = run_migration_command(
        SurrealMigrationRunnerConfig(
            mode=args.mode,
            target_mode=args.target_mode,
            sqlite_snapshot=args.sqlite_snapshot,
            source_capture_manifest_json=args.source_capture_manifest_json,
            graph_export_json=args.graph_export_json,
            feedback_export_json=args.feedback_export_json,
            target_url=args.target_url,
            target_namespace=args.target_namespace,
            target_database=args.target_database,
            gate_report=args.gate_report,
            overwrite_policy=args.overwrite_policy,
            verification_depth=args.verification_depth,
            manifest_json=args.manifest_json,
            report_json=args.report_json,
            report_markdown=args.report_markdown,
            progress_json=args.progress_json,
            resume_from_progress=args.resume_from_progress,
            restore_manifest_json=args.restore_manifest_json,
            owner_id=args.owner_id,
            max_report_samples=args.max_report_samples,
            redact_report_samples=args.redact_report_samples,
        )
    )
    return result.exit_code


if __name__ == "__main__":
    raise SystemExit(main())
