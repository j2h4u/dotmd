"""Runner tests for the Phase 41 migration evidence workflow."""

from __future__ import annotations

import json
from pathlib import Path

import devtools.surreal_migration_runner as runner
import pytest
from devtools.surreal_migration_runner import (
    SurrealMigrationRunnerConfig,
    build_parser,
    load_feedback_rows_from_json,
    load_graph_rows_from_json,
    main,
    run_migration_command,
)
from tests.ingestion.test_surreal_production_migration import _build_inputs
from tests.ingestion.test_surreal_transform_only_migration import _write_gate_report

from dotmd.ingestion.migrate_surreal import (
    SurrealMigrationMode,
    SurrealTargetMode,
    run_surreal_migration,
)
from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION


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
            "--build-deferred-indexes",
            "--vector-index-type",
            "f16",
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
    assert args.build_deferred_indexes is True
    assert args.vector_index_type == "f16"


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
    progress_json = tmp_path / "progress.json"
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
            target_database="production",
            gate_report=gate_report,
            overwrite_policy="refuse",
            verification_depth="deep",
            manifest_json=tmp_path / "migration-manifest.json",
            report_json=report_json,
            report_markdown=report_markdown,
            progress_json=progress_json,
            restore_manifest_json=restore_manifest_json,
            owner_id="оператор",
            max_report_samples=1,
            redact_report_samples=False,
        )
    )

    payload = json.loads(report_json.read_text(encoding="utf-8"))
    markdown = report_markdown.read_text(encoding="utf-8")
    restore_payload = json.loads(restore_manifest_json.read_text(encoding="utf-8"))
    progress_payload = json.loads(progress_json.read_text(encoding="utf-8"))

    assert result.exit_code == 0
    assert payload["report_status"] == "verified"
    assert payload["mode"] == "apply"
    assert payload["target_mode"] == "embedded-local"
    assert payload["deferred_indexes_status"] == "skipped"
    assert payload["hnsw_rebuild_status"] == "not_rebuilt"
    assert payload["deferred_indexes_expected"] == [
        "embeddings_strategy_chunk_model_idx",
        "embeddings_strategy_model_idx",
        "embeddings_text_hash_idx",
    ]
    assert payload["deferred_indexes_present"] == []
    assert payload["redaction_policy"] == "plain"
    assert payload["sample_limit"] == 1
    assert "оператор" in payload["target"]["owner_id"]
    assert restore_payload["restore_status"] == "verified_with_fallback"
    assert "оператор" in markdown
    assert progress_payload["current_phase"] == "reporting"
    assert progress_payload["current_phase_status"] == "applied"
    applied_phases = {
        checkpoint["phase_name"]
        for checkpoint in progress_payload["phase_checkpoints"]
        if checkpoint["status"] == "applied"
    }
    assert {
        "source_capture",
        "documents",
        "verification",
        "restore_rehearsal",
        "reporting",
    } <= applied_phases


def test_resume_does_not_overwrite_existing_progress_before_core_runner(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sqlite_snapshot = tmp_path / "snapshot.db"
    graph_export = tmp_path / "graph.json"
    feedback_export = tmp_path / "feedback.json"
    progress_json = tmp_path / "progress.json"
    report_json = tmp_path / "report.json"
    report_markdown = tmp_path / "report.md"
    restore_manifest_json = tmp_path / "restore.json"
    manifest_json = tmp_path / "manifest.json"
    source_capture_manifest_json = tmp_path / "source-capture.json"
    sqlite_snapshot.write_bytes(b"sqlite")
    graph_export.write_bytes(b"graph")
    feedback_export.write_bytes(b"feedback")
    progress_json.write_text(
        json.dumps(
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "mode": "apply",
                "target_url": "http://127.0.0.1:8000",
                "phase_checkpoints": [
                    {
                        "phase_name": "embeddings",
                        "planned_count": 10,
                        "applied_count": 10,
                        "verified_count": 10,
                        "status": "applied",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    def fake_run_surreal_migration(**kwargs):  # type: ignore[no-untyped-def]
        payload = json.loads(progress_json.read_text(encoding="utf-8"))
        assert payload["phase_checkpoints"][0]["phase_name"] == "embeddings"
        assert payload["phase_checkpoints"][0]["status"] == "applied"
        return runner.SurrealMigrationReport(
            schema_version=SURREAL_SCHEMA_VERSION,
            mode=runner.SurrealMigrationMode.APPLY,
            status="apply",
            target_mode=runner.SurrealTargetMode.REMOTE_SERVICE,
            overwrite_policy=runner.SurrealOverwritePolicy.REFUSE,
            target_url=kwargs["target_url"],
            target_namespace=kwargs["target_namespace"],
            target_database=kwargs["target_database"],
            source_capture_manifest=None,
        )

    monkeypatch.setattr(runner, "run_surreal_migration", fake_run_surreal_migration)

    result = runner.run_migration_command(
        runner.SurrealMigrationRunnerConfig(
            mode="apply",
            target_mode="remote-service",
            sqlite_snapshot=sqlite_snapshot,
            source_capture_manifest_json=source_capture_manifest_json,
            graph_export_json=graph_export,
            feedback_export_json=feedback_export,
            target_url="http://127.0.0.1:8000",
            progress_json=progress_json,
            resume_from_progress=True,
            manifest_json=manifest_json,
            report_json=report_json,
            report_markdown=report_markdown,
            restore_manifest_json=restore_manifest_json,
        )
    )

    assert result.exit_code == 1


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
                target_database="production",
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
