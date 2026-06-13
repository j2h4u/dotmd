"""Runner tests for the Phase 41 migration evidence workflow."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from devtools.surreal_migration_runner import (
    SurrealMigrationRunnerConfig,
    build_parser,
    load_feedback_rows_from_json,
    load_graph_rows_from_json,
    main,
    run_migration_command,
)
from dotmd.ingestion.migrate_surreal import (
    SurrealMigrationMode,
    SurrealTargetMode,
    run_surreal_migration,
)
from tests.ingestion.test_surreal_production_migration import _build_inputs
from tests.ingestion.test_surreal_transform_only_migration import _write_gate_report


def _write_json(path: Path, payload: dict[str, object]) -> Path:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def test_build_parser_exposes_phase_41_modes_and_safety_flags() -> None:
    parser = build_parser()

    args = parser.parse_args(
        [
            "--mode",
            "report",
            "--target-mode",
            "embedded-local",
            "--sqlite-snapshot",
            "snapshot.db",
            "--source-capture-manifest-json",
            "manifest.json",
            "--graph-export-json",
            "graph.json",
            "--feedback-export-json",
            "feedback.json",
            "--report-json",
            "report.json",
            "--report-markdown",
            "report.md",
            "--restore-manifest-json",
            "restore.json",
            "--owner-id",
            "ops-user",
            "--max-report-samples",
            "2",
            "--redact-report-samples",
        ]
    )

    assert args.mode == "report"
    assert args.target_mode == "embedded-local"
    assert args.sqlite_snapshot == Path("snapshot.db")
    assert args.source_capture_manifest_json == Path("manifest.json")
    assert args.graph_export_json == Path("graph.json")
    assert args.feedback_export_json == Path("feedback.json")
    assert args.report_json == Path("report.json")
    assert args.report_markdown == Path("report.md")
    assert args.restore_manifest_json == Path("restore.json")
    assert args.owner_id == "ops-user"
    assert args.max_report_samples == 2
    assert args.redact_report_samples is True


def test_json_loaders_distinguish_syntax_and_semantic_failures(tmp_path: Path) -> None:
    syntax_invalid = tmp_path / "graph-invalid.json"
    syntax_invalid.write_text('{"rows": [\n', encoding="utf-8")

    with pytest.raises(ValueError, match=r"graph-invalid\.json line 2 column 1: invalid JSON"):
        load_graph_rows_from_json(syntax_invalid)

    semantic_invalid_graph = _write_json(
        tmp_path / "graph-semantic.json",
        {
            "rows": {
                "entities": [{"entity_type": "Person"}],
                "relations": [],
                "files": [],
                "sections": [],
                "tags": [],
            }
        },
    )
    with pytest.raises(
        ValueError,
        match=r"graph-semantic\.json: category entities row 0 field name is required",
    ):
        load_graph_rows_from_json(semantic_invalid_graph)

    semantic_invalid_feedback = _write_json(
        tmp_path / "feedback-semantic.json",
        {"rows": [{"submitted_at": "2026-06-12T00:13:00Z", "message": "hi"}]},
    )
    with pytest.raises(
        ValueError,
        match=r"feedback-semantic\.json: category feedback row 0 field id is required",
    ):
        load_feedback_rows_from_json(semantic_invalid_feedback)


def test_run_migration_command_writes_json_markdown_and_preserves_non_ascii(
    tmp_path: Path,
) -> None:
    inputs = _build_inputs(tmp_path)
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"
    restore_manifest_json = tmp_path / "restore.json"
    manifest_json = tmp_path / "source-manifest.json"
    gate_report = _write_gate_report(tmp_path / "gate.md")
    target_path = tmp_path / "runner-target.db"

    result = run_migration_command(
        SurrealMigrationRunnerConfig(
            mode="apply",
            target_mode="embedded-local",
            sqlite_snapshot=inputs["sqlite_snapshot_path"],
            source_capture_manifest_json=manifest_json,
            graph_export_json=inputs["graph_export_path"],
            feedback_export_json=inputs["feedback_export_path"],
            target_url=f"surrealkv://{target_path}",
            target_namespace="dotmd",
            target_database="phase41_migration",
            gate_report=gate_report,
            overwrite_policy="refuse",
            verification_depth="deep",
            manifest_json=tmp_path / "migration-manifest.json",
            report_json=report_json,
            report_markdown=report_markdown,
            restore_manifest_json=restore_manifest_json,
            owner_id="оператор",
            max_report_samples=1,
            redact_report_samples=False,
        )
    )

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    markdown = report_markdown.read_text(encoding="utf-8")
    restore_payload = json.loads(restore_manifest_json.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert payload["report_status"] == "verified"
    assert payload["mode"] == "apply"
    assert payload["target_mode"] == "embedded-local"
    assert payload["redaction_policy"] == "plain"
    assert payload["sample_limit"] == 1
    assert "оператор" in payload["target"]["owner_id"]
    assert "verified_with_fallback" == restore_payload["restore_status"]
    assert "оператор" in markdown


def test_run_migration_command_refuses_unsafe_apply_without_gate_or_target_inputs(
    tmp_path: Path,
) -> None:
    inputs = _build_inputs(tmp_path)

    with pytest.raises(ValueError, match="gate_report is required for apply mode"):
        run_migration_command(
            SurrealMigrationRunnerConfig(
                mode="apply",
                target_mode="embedded-local",
                sqlite_snapshot=inputs["sqlite_snapshot_path"],
                source_capture_manifest_json=tmp_path / "source-manifest.json",
                graph_export_json=inputs["graph_export_path"],
                feedback_export_json=inputs["feedback_export_path"],
                target_url="",
                target_namespace="dotmd",
                target_database="phase41_migration",
                gate_report=None,
                overwrite_policy="refuse",
                verification_depth="cheap",
                manifest_json=tmp_path / "manifest.json",
                report_json=tmp_path / "report.json",
                report_markdown=tmp_path / "report.md",
                restore_manifest_json=tmp_path / "restore.json",
                owner_id="ops-user",
                max_report_samples=1,
                redact_report_samples=True,
            )
        )


def test_direct_run_surreal_migration_fails_closed_for_unsafe_apply(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)

    report = run_surreal_migration(
        mode=SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url="",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
    )

    assert report.status in {"invalid_target", "gate_blocked"}
    assert report.committed_success is False
    assert any("required" in error.lower() for error in report.errors)


def test_main_rejects_apply_without_source_capture_and_gate(tmp_path: Path) -> None:
    inputs = _build_inputs(tmp_path)

    with pytest.raises(ValueError, match="source_capture_manifest_json is required for apply mode"):
        main(
            [
                "--mode",
                "apply",
                "--target-mode",
                "embedded-local",
                "--sqlite-snapshot",
                str(inputs["sqlite_snapshot_path"]),
                "--graph-export-json",
                str(inputs["graph_export_path"]),
                "--feedback-export-json",
                str(inputs["feedback_export_path"]),
                "--target-url",
                f"surrealkv://{tmp_path / 'target.db'}",
                "--report-json",
                str(tmp_path / "report.json"),
                "--report-markdown",
                str(tmp_path / "report.md"),
                "--restore-manifest-json",
                str(tmp_path / "restore.json"),
            ]
        )
