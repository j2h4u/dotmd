from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import TypedDict

import pytest

from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION
from tests.fixtures.surreal_native import (
    apply_surreal_native_retrieval_schema,
    isolated_surreal_connection,
)
from tests.ingestion.test_surreal_transform_only_migration import (
    _create_transform_only_fixture,
    _FakeFeedbackProvider,
    _serialize_embedding,
    _write_feedback_export,
    _write_gate_report,
    _write_graph_export,
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

    assert manifest.schema_version == SURREAL_SCHEMA_VERSION
    assert manifest.target_mode is SurrealTargetMode.EMBEDDED_LOCAL
    assert manifest.recompute_forbidden is True
    assert manifest.target_url.endswith("manifest.db")
    assert manifest.target_namespace == "dotmd"
    assert manifest.target_database == "production"
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


def test_plan_uses_sqlite_stats_without_materializing_source_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    inputs = _build_inputs(tmp_path)

    def _explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("PLAN must not materialize source rows")

    monkeypatch.setattr(migrate_module, "load_sqlite_rows_for_surreal", _explode)

    report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.PLAN,
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'plan.db'}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
    )

    assert report.status == "plan"
    assert report.expected_counts["embeddings"] == 2
    assert not (tmp_path / "plan.db").exists()


def test_load_sqlite_rows_for_surreal_materializes_title_and_tags_text_from_source_documents(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        load_sqlite_rows_for_surreal,
    )

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


def test_sqlite_rows_can_skip_vectors_for_streaming_apply(tmp_path: Path) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        iter_sqlite_embedding_rows_for_surreal,
        iter_sqlite_vector_component_rows_for_surreal,
        load_sqlite_rows_for_surreal,
    )

    inputs = _build_inputs(tmp_path)

    rows = load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"], include_vectors=False)
    embeddings = list(iter_sqlite_embedding_rows_for_surreal(inputs["sqlite_snapshot_path"]))
    vector_components = list(
        iter_sqlite_vector_component_rows_for_surreal(inputs["sqlite_snapshot_path"])
    )

    assert rows["embeddings"] == []
    assert rows["vector_components"] == []
    assert len(embeddings) == 2
    assert len(vector_components) == 2
    assert embeddings[0]["vector"]
    assert "embedding" not in embeddings[0]
    assert "original_chunk_id" not in embeddings[0]
    assert vector_components[0]["embedding"]


def test_streaming_embedding_rows_normalize_missing_text_hash(tmp_path: Path) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        iter_sqlite_embedding_rows_for_surreal,
        load_sqlite_rows_for_surreal,
    )

    inputs = _build_inputs(tmp_path)
    with sqlite3.connect(inputs["sqlite_snapshot_path"]) as conn:
        conn.execute(
            "UPDATE vec_meta_contextual_512_50_multilingual_e5_large "
            "SET text_hash = NULL WHERE rowid = 1"
        )

    streamed = list(iter_sqlite_embedding_rows_for_surreal(inputs["sqlite_snapshot_path"]))
    materialized = load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"])

    assert streamed[0]["text_hash"] == ""
    assert materialized["embeddings"][0]["text_hash"] == ""
    assert "embedding" not in streamed[0]
    assert "embedding" not in materialized["embeddings"][0]
    assert "original_chunk_id" not in streamed[0]
    assert "original_chunk_id" not in materialized["embeddings"][0]


def test_missing_vec_config_model_uses_matching_runtime_embedding_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        load_sqlite_rows_for_surreal,
    )

    inputs = _build_inputs(tmp_path)
    with sqlite3.connect(inputs["sqlite_snapshot_path"]) as conn:
        conn.execute(
            "DELETE FROM vec_config_contextual_512_50_multilingual_e5_large WHERE key = 'model'"
        )

    monkeypatch.setenv("DOTMD_EMBEDDING_MODEL", "intfloat/multilingual-e5-large")

    rows = load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"])

    assert rows["embedding_model"] == "intfloat/multilingual-e5-large"
    assert {row["embedding_model"] for row in rows["embeddings"]} == {
        "intfloat/multilingual-e5-large",
    }


def test_missing_vec_config_model_with_mismatching_runtime_embedding_model_raises_value_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        load_sqlite_rows_for_surreal,
    )

    inputs = _build_inputs(tmp_path)
    with sqlite3.connect(inputs["sqlite_snapshot_path"]) as conn:
        conn.execute(
            "DELETE FROM vec_config_contextual_512_50_multilingual_e5_large WHERE key = 'model'"
        )

    monkeypatch.setenv("DOTMD_EMBEDDING_MODEL", "vendor/other-model")

    with pytest.raises(
        ValueError,
        match=(
            r"vec_config_contextual_512_50_multilingual_e5_large is missing required 'model' "
            r"key for model_key='multilingual_e5_large'"
        ),
    ):
        load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"])


def test_migration_discovers_multiple_chunk_strategy_model_pairs(tmp_path: Path) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealTargetMode,
        build_surreal_migration_manifest,
        iter_sqlite_embedding_rows_for_surreal,
        load_sqlite_rows_for_surreal,
    )

    inputs = _build_inputs(tmp_path)
    with sqlite3.connect(inputs["sqlite_snapshot_path"]) as conn:
        conn.executescript("""
            CREATE TABLE chunks_heading_512_50 (
                chunk_id TEXT PRIMARY KEY,
                heading_hierarchy TEXT NOT NULL,
                level INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE chunk_source_provenance_heading_512_50 (
                chunk_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                source_unit_refs TEXT NOT NULL,
                chunk_strategy TEXT NOT NULL,
                parser_name TEXT,
                PRIMARY KEY (chunk_id, namespace, document_ref)
            );
            CREATE TABLE chunk_file_paths_heading_512_50 (
                chunk_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                PRIMARY KEY (chunk_id, file_path, chunk_index)
            );
            CREATE TABLE vec_meta_heading_512_50_other_model (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            );
            CREATE TABLE vec_chunks_heading_512_50_other_model (
                rowid INTEGER PRIMARY KEY,
                embedding BLOB NOT NULL
            );
            CREATE TABLE vec_config_heading_512_50_other_model (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE embed_fingerprints_heading_512_50_other_model (
                chunk_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL
            );
            CREATE TABLE meta_fingerprints_heading_512_50_other_model (
                file_path TEXT PRIMARY KEY,
                meta_checksum TEXT NOT NULL
            );
        """)
        conn.execute(
            "INSERT INTO chunks_heading_512_50 VALUES (?, ?, ?, ?)",
            ("heading:chunk", '["Heading"]', 1, "Heading body"),
        )
        conn.execute(
            "INSERT INTO chunk_source_provenance_heading_512_50 VALUES (?, ?, ?, ?, ?, ?)",
            ("heading:chunk", "filesystem", "/tmp/Doc Two.md", '["unit:3"]', "heading_512_50", "markdown"),
        )
        conn.execute(
            "INSERT INTO chunk_file_paths_heading_512_50 VALUES (?, ?, ?)",
            ("heading:chunk", "/tmp/Doc Two.md", 2),
        )
        conn.execute(
            "INSERT INTO vec_meta_heading_512_50_other_model VALUES (?, ?, ?)",
            (1, "heading:chunk", "hash-heading"),
        )
        conn.execute(
            "INSERT INTO vec_chunks_heading_512_50_other_model VALUES (?, ?)",
            (1, _serialize_embedding([0.7, 0.8, 0.9])),
        )
        conn.execute(
            "INSERT INTO vec_config_heading_512_50_other_model VALUES ('dim', '3'), ('model', 'vendor/other-model')"
        )
        conn.execute(
            "INSERT INTO embed_fingerprints_heading_512_50_other_model VALUES (?, ?)",
            ("heading:chunk", "embed-heading"),
        )
        conn.execute(
            "INSERT INTO meta_fingerprints_heading_512_50_other_model VALUES (?, ?)",
            ("/tmp/Doc Two.md", "meta-heading"),
        )

    manifest = build_surreal_migration_manifest(
        sqlite_snapshot_path=inputs["sqlite_snapshot_path"],
        graph_export_path=inputs["graph_export_path"],
        feedback_export_path=inputs["feedback_export_path"],
        target_url=f"surrealkv://{tmp_path / 'multi.db'}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
    )
    materialized = load_sqlite_rows_for_surreal(inputs["sqlite_snapshot_path"])
    streamed = list(iter_sqlite_embedding_rows_for_surreal(inputs["sqlite_snapshot_path"]))

    assert manifest.expected_counts["chunks"] == 3
    assert manifest.expected_counts["embeddings"] == 3
    assert {row["chunk_strategy"] for row in streamed} == {"contextual_512_50", "heading_512_50"}
    assert {row["embedding_model"] for row in streamed} == {
        "multilingual-e5-large",
        "vendor/other-model",
    }
    assert materialized["embeddings"][-1]["chunk_strategy"] == "heading_512_50"
    assert all("embedding" not in row for row in streamed)
    assert all("embedding" not in row for row in materialized["embeddings"])


def test_phase42_fixture_applies_retrieval_schema_for_real_embedded_targets(tmp_path: Path) -> None:
    with isolated_surreal_connection(tmp_path) as connection:
        retrieval_plan = apply_surreal_native_retrieval_schema(
            connection,
            embedding_dimension=3,
            hnsw_ef=40,
        )
        schema_info = connection.query_raw("INFO FOR TABLE embeddings;")

    assert retrieval_plan.embedding_dimension == 3
    assert "vector" in str(schema_info)


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
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="production")
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
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="production")
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
    monkeypatch: pytest.MonkeyPatch,
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
    config = SurrealStoreConfig(url=f"surrealkv://{target_path}", database="production")
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

    def _clear_schema_should_not_run_for_embedded_reset(self):  # type: ignore[no-untyped-def]
        raise AssertionError("embedded explicit_replace should physically reset the target")

    monkeypatch.setattr(
        SurrealConnection,
        "clear_schema_owned_tables",
        _clear_schema_should_not_run_for_embedded_reset,
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

    assert report.status == "applied", report.errors
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
        "indexes",
        "vector_components",
        "graph",
        "feedback",
        "cursors",
        "checkpoints",
        "verification",
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
        database="production",
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


def test_remote_target_connection_uses_surreal_auth_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    captured = {}

    class FakeConnection:
        def __init__(self, config):  # type: ignore[no-untyped-def]
            captured["config"] = config

    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_USERNAME", "root")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_PASSWORD", "secret")
    monkeypatch.setattr(migrate_module, "SurrealConnection", FakeConnection)

    migrate_module._connection_for_target(
        target_url="http://127.0.0.1:8000",
        target_namespace="dotmd",
        target_database="production",
    )

    config = captured["config"]
    assert config.url == "http://127.0.0.1:8000"
    assert config.namespace == "dotmd"
    assert config.database == "production"
    assert config.username == "root"
    assert config.password == "secret"
    assert config.access_token is None


def test_remote_target_connection_rejects_conflicting_surreal_auth_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_USERNAME", "root")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_PASSWORD", "secret")
    monkeypatch.setenv("DOTMD_SURREAL_RETRIEVAL_ACCESS_TOKEN", "token")

    with pytest.raises(ValueError, match="must not be combined"):
        migrate_module._connection_for_target(
            target_url="http://127.0.0.1:8000",
            target_namespace="dotmd",
            target_database="production",
        )


def test_resume_target_inspection_can_skip_large_row_counts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    class FakeConnection:
        def __init__(self, _config):  # type: ignore[no-untyped-def]
            pass

        def __enter__(self):  # type: ignore[no-untyped-def]
            return self

        def __exit__(self, *_args):  # type: ignore[no-untyped-def]
            return None

        def inspect_schema(self):  # type: ignore[no-untyped-def]
            return {"schema_version": "42.1.0", "table_modes": {"embeddings": "SCHEMAFULL"}}

    def fail_count_rows(_connection):  # type: ignore[no-untyped-def]
        raise AssertionError("row counts should be skipped during resume inspection")

    report = migrate_module.SurrealMigrationReport(
        schema_version="42.1.0",
        mode=migrate_module.SurrealMigrationMode.APPLY,
        status="apply",
        target_mode=migrate_module.SurrealTargetMode.REMOTE_SERVICE,
        overwrite_policy=migrate_module.SurrealOverwritePolicy.REFUSE,
        target_url="http://127.0.0.1:8000",
        target_namespace="dotmd",
        target_database="production",
        source_capture_manifest=None,
    )
    monkeypatch.setattr(migrate_module, "SurrealConnection", FakeConnection)
    monkeypatch.setattr(migrate_module, "_count_target_rows", fail_count_rows)

    schema_info = migrate_module._inspect_target(
        report,
        target_url="http://127.0.0.1:8000",
        target_namespace="dotmd",
        target_database="production",
        count_rows=False,
    )

    assert report.target_pre_counts == {}
    assert report.target_inspection_performed is True
    assert schema_info["schema_version"] == "42.1.0"
