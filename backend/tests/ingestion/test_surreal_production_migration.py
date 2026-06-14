from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict

import pytest

from tests.ingestion.test_surreal_transform_only_migration import (
    _create_transform_only_fixture,
    _FakeFeedbackProvider,
    _write_feedback_export,
    _write_gate_report,
    _write_graph_export,
)
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)


class _MigrationInputs(TypedDict):
    sqlite_snapshot_path: Path
    graph_export_path: Path
    feedback_export_path: Path
    fixture_ids: dict[str, str]


def _build_inputs(tmp_path: Path) -> _MigrationInputs:
    db_path = tmp_path / "production-source.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    with sqlite3.connect(db_path) as conn:
        conn.execute(
            "UPDATE source_documents SET metadata_json = ? WHERE document_ref = ?",
            (
                json.dumps({"lang": "ru", "tags": ["surreal", "retrieval"]}),
                fixture_ids["file_path"],
            ),
        )
        conn.execute(
            "UPDATE source_documents SET metadata_json = ? WHERE document_ref = ?",
            (
                json.dumps({"lang": "en", "tags": "beta"}),
                "/tmp/Doc Two.md",
            ),
        )
    feedback_provider = _FakeFeedbackProvider()
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        feedback_provider,
    )
    return {
        "sqlite_snapshot_path": db_path,
        "graph_export_path": graph_export_path,
        "feedback_export_path": feedback_export_path,
        "fixture_ids": fixture_ids,
    }


def test_build_manifest_records_source_capture_schema_counts_and_no_recompute_defaults(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealTargetMode,
        build_surreal_migration_manifest,
    )

    inputs = _build_inputs(tmp_path)

    manifest = build_surreal_migration_manifest(
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'manifest.db'}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        skew_policy="bounded_skew_accepted",
    )

    assert manifest.schema_version.startswith("41.")
    assert manifest.target_mode is SurrealTargetMode.EMBEDDED_LOCAL
    assert manifest.recompute_forbidden is True
    assert manifest.target_url.endswith("manifest.db")
    assert manifest.target_namespace == "dotmd"
    assert manifest.target_database == "phase41_migration"
    assert manifest.expected_counts["documents"] == 2
    assert manifest.expected_counts["chunks"] == 2
    assert manifest.expected_counts["chunk_file_bindings"] == 2
    assert manifest.expected_counts["graph_entities"] == 1
    assert manifest.expected_counts["graph_relations"] == 2
    assert manifest.expected_counts["feedback"] == 2
    assert manifest.unsupported_categories == [
        "stats",
        "search_log",
        "embedding_cache",
        "extraction_cache",
        "sqlite_internal",
    ]
    assert manifest.source_capture_manifest.sqlite_snapshot["path"].endswith("production-source.db")
    assert manifest.source_capture_manifest.sqlite_snapshot["sha256"]
    assert manifest.source_capture_manifest.graph_export["path"].endswith("graph-export.json")
    assert manifest.source_capture_manifest.graph_export["exported_at"] == "2026-06-12T00:12:00Z"
    assert manifest.source_capture_manifest.feedback_export["path"].endswith("feedback-export.json")
    assert manifest.source_capture_manifest.feedback_export["exported_at"] == "2026-06-12T00:13:00Z"
    assert manifest.source_capture_manifest.skew_policy == "bounded_skew_accepted"
    assert not (tmp_path / "manifest.db").exists()


def test_load_sqlite_rows_for_surreal_materializes_title_and_tags_text_from_source_documents(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import load_sqlite_rows_for_surreal  # type: ignore[import-not-found]

    inputs = _build_inputs(tmp_path)

    rows = load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"])
    chunk_payloads = {row["chunk_id"]: row for row in rows["chunks"]}

    tagged_chunk = chunk_payloads[inputs["fixture_ids"]["chunk_id"]]
    plain_chunk = chunk_payloads["chunk:plain"]

    assert tagged_chunk["title"] == "Doc One"
    assert tagged_chunk["tags_text"] == "surreal retrieval"
    assert plain_chunk["title"] == "Doc Two"
    assert plain_chunk["tags_text"] == "beta"
    assert tagged_chunk["text"] == "Alpha body"
    assert tagged_chunk["document_ref"] == inputs["fixture_ids"]["file_path"]
    assert tagged_chunk["ref"] == inputs["fixture_ids"]["ref"]


def test_phase42_fixture_applies_retrieval_schema_for_real_embedded_targets(tmp_path: Path) -> None:
    with isolated_surreal_connection(tmp_path) as connection:
        retrieval_plan = apply_surreal_native_retrieval_schema(
            connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )
        schema_info = connection.query_raw("INFO FOR TABLE embeddings;")

    assert retrieval_plan.embedding_dimension == 3
    assert "embedding" in str(schema_info)


@pytest.mark.parametrize("mode_name", ["PLAN", "DRY_RUN"])
def test_plan_and_dry_run_do_not_open_or_mutate_target_by_default(
    tmp_path: Path,
    mode_name: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    inputs = _build_inputs(tmp_path)

    def _explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("target connection must stay closed by default")

    monkeypatch.setattr(migrate_module, "SurrealConnection", _explode)

    report = migrate_module.run_surreal_migration(
        mode=getattr(migrate_module.SurrealMigrationMode, mode_name),
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'no-touch.db'}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
    )

    assert report.mode.value == mode_name.lower().replace("_", "-")
    assert report.target_inspection_performed is False
    assert report.actual_counts == {}
    assert report.committed_success is False
    assert not (tmp_path / "no-touch.db").exists()


def test_dry_run_optional_target_inspection_records_preexisting_counts(tmp_path: Path) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealTargetMode,
        run_surreal_migration,
    )
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealMetadataStore,
        SurrealStoreConfig,
        define_dotmd_surreal_schema,
    )

    inputs = _build_inputs(tmp_path)
    target_path = tmp_path / "inspected.db"
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="phase41_migration")
    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        SurrealMetadataStore(connection).replace_documents(
            [
                {
                    "schema_version": "41.1.0",
                    "namespace": "filesystem",
                    "document_ref": "/tmp/preexisting.md",
                    "ref": "filesystem:/tmp/preexisting.md",
                    "title": "Preexisting",
                    "metadata": {},
                }
            ]
        )

    report = run_surreal_migration(
        mode=SurrealMigrationMode.DRY_RUN,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{target_path}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        inspect_target=True,
    )

    assert report.target_inspection_performed is True
    assert report.target_pre_counts["documents"] == 1
    assert report.target_pre_counts["chunks"] == 0
    assert report.status == "dry-run"


@pytest.mark.parametrize("target_mode", ["EMBEDDED_LOCAL", "REMOTE_SERVICE"])
def test_apply_refuses_populated_target_without_explicit_replace(
    tmp_path: Path,
    target_mode: str,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealTargetMode,
        run_surreal_migration,
    )
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealMetadataStore,
        SurrealStoreConfig,
        define_dotmd_surreal_schema,
    )

    inputs = _build_inputs(tmp_path)
    target_path = tmp_path / f"refuse-{target_mode.lower()}.db"
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="phase41_migration")
    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        SurrealMetadataStore(connection).replace_documents(
            [
                {
                    "schema_version": "41.1.0",
                    "namespace": "filesystem",
                    "document_ref": "/tmp/already-there.md",
                    "ref": "filesystem:/tmp/already-there.md",
                    "title": "Already There",
                    "metadata": {},
                }
            ]
        )

    kwargs = {
        "mode": SurrealMigrationMode.APPLY,
        "sqlite_snapshot_path": inputs["sqlite_snapshot_path"],
        "graph_export_path": inputs["graph_export_path"],
        "feedback_export_path": inputs["feedback_export_path"],
        "target_url": f"surrealkv://{target_path}",
        "target_mode": getattr(SurrealTargetMode, target_mode),
        "inspect_target": True,
    }
    if target_mode == "EMBEDDED_LOCAL":
        kwargs["gate_report_path"] = _write_gate_report(tmp_path / f"{target_mode.lower()}-gate.md")

    report = run_surreal_migration(**kwargs)

    assert report.status == "target_not_empty"
    assert report.overwrite_policy.value == "refuse"
    assert report.target_pre_counts["documents"] == 1
    assert report.committed_success is False
    assert any("explicit_replace" in error.lower() for error in report.errors)


def test_explicit_replace_is_the_only_destructive_path_and_records_pre_counts(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealOverwritePolicy,
        SurrealTargetMode,
        run_surreal_migration,
    )
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealMetadataStore,
        SurrealStoreConfig,
        define_dotmd_surreal_schema,
    )

    inputs = _build_inputs(tmp_path)
    target_path = tmp_path / "replace.db"
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="phase41_migration")
    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        SurrealMetadataStore(connection).replace_documents(
            [
                {
                    "schema_version": "41.1.0",
                    "namespace": "filesystem",
                    "document_ref": "/tmp/old.md",
                    "ref": "filesystem:/tmp/old.md",
                    "title": "Old",
                    "metadata": {},
                }
            ]
        )

    report = run_surreal_migration(
        mode=SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{target_path}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=_write_gate_report(tmp_path / "replace-gate.md"),
        overwrite_policy=SurrealOverwritePolicy.EXPLICIT_REPLACE,
        inspect_target=True,
    )

    assert report.status == "applied"
    assert report.overwrite_policy is SurrealOverwritePolicy.EXPLICIT_REPLACE
    assert report.target_pre_counts["documents"] == 1
    assert report.committed_success is True


def test_apply_reports_phase_checkpoints_embedding_reuse_and_verification_depths(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealTargetMode,
        SurrealVerificationDepth,
        run_surreal_migration,
        verify_surreal_migration_target,
    )

    inputs = _build_inputs(tmp_path)
    target_path = tmp_path / "verify.db"
    report = run_surreal_migration(
        mode=SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{target_path}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=_write_gate_report(tmp_path / "verify-gate.md"),
        verification_depth=SurrealVerificationDepth.CHEAP,
    )

    assert report.status == "applied"
    assert report.embedding_reuse_verified is True
    assert report.expected_vector_dimension == 3
    assert report.recompute_guard_status == "passed"
    assert report.cheap_invariants
    assert report.deep_sample_checks == []
    assert [checkpoint.phase_name.value for checkpoint in report.phase_checkpoints] == [
        "schema",
        "documents",
        "source_units",
        "chunks",
        "chunk_file_bindings",
        "provenance",
        "bindings",
        "fingerprints",
        "embeddings",
        "vector_components",
        "graph",
        "feedback",
        "cursors",
        "checkpoints",
    ]

    deep_report = verify_surreal_migration_target(
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{target_path}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        verification_depth=SurrealVerificationDepth.DEEP,
    )

    assert deep_report.verified is True
    assert deep_report.deep_sample_checks
    assert any("relation payload" in check.lower() for check in deep_report.deep_sample_checks)
    assert any("feedback sample" in check.lower() for check in deep_report.deep_sample_checks)


def test_apply_fails_closed_for_recompute_requests_schemaless_targets_and_partial_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]
    from dotmd.storage import surreal as surreal_module  # type: ignore[import-not-found]

    inputs = _build_inputs(tmp_path)

    recompute_report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'recompute.db'}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=_write_gate_report(tmp_path / "recompute-gate.md"),
        requested_recompute_steps=("tei", "chunking"),
    )

    assert recompute_report.status == "recompute_blocked"
    assert recompute_report.committed_success is False
    assert recompute_report.recompute_guard_status == "blocked"

    schema_mismatch_path = tmp_path / "schemaless.db"
    config = surreal_module.SurrealStoreConfig(
        url=f"surrealkv://{schema_mismatch_path}",
        database="phase41_migration",
    )
    with surreal_module.SurrealConnection(config) as connection:
        connection.query("DEFINE TABLE documents SCHEMALESS;")

    schema_report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{schema_mismatch_path}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=_write_gate_report(tmp_path / "schemaless-gate.md"),
        inspect_target=True,
    )

    assert schema_report.status == "schema_mismatch"
    assert schema_report.committed_success is False
    assert any("schemaless" in error.lower() for error in schema_report.errors)

    def _boom(self, rows):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced late-phase failure")

    monkeypatch.setattr(surreal_module.SurrealFeedbackStore, "replace_feedback_rows", _boom)
    failed_report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'partial.db'}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=_write_gate_report(tmp_path / "partial-gate.md"),
    )

    assert failed_report.status == "failed"
    assert failed_report.committed_success is False
    assert failed_report.partial_writes_present is True
    assert failed_report.cleanup_attempted is False
    assert failed_report.restore_required is True
    assert failed_report.last_successful_phase is not None
    assert failed_report.failed_phase is not None
    assert failed_report.rollback_evidence == "no_automatic_cleanup"
