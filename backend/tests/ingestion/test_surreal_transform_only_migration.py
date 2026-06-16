from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

import pytest


def _serialize_embedding(values: list[float]) -> bytes:
    return struct.pack(f"{len(values)}f", *values)


def _create_transform_only_fixture(db_path: Path) -> dict[str, str]:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript("""
            CREATE TABLE chunks_contextual_512_50 (
                chunk_id TEXT PRIMARY KEY,
                heading_hierarchy TEXT NOT NULL,
                level INTEGER NOT NULL,
                text TEXT NOT NULL
            );
            CREATE TABLE chunk_source_provenance_contextual_512_50 (
                chunk_id TEXT NOT NULL,
                namespace TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                source_unit_refs TEXT NOT NULL,
                chunk_strategy TEXT NOT NULL,
                parser_name TEXT,
                PRIMARY KEY (chunk_id, namespace, document_ref)
            );
            CREATE TABLE chunk_file_paths_contextual_512_50 (
                chunk_id TEXT NOT NULL,
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                PRIMARY KEY (chunk_id, file_path, chunk_index)
            );
            CREATE TABLE source_documents (
                namespace TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                ref TEXT NOT NULL,
                source_uri TEXT NOT NULL,
                file_path TEXT,
                media_type TEXT NOT NULL,
                parser_name TEXT NOT NULL,
                document_type TEXT NOT NULL,
                title TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                content_fingerprint TEXT NOT NULL,
                metadata_fingerprint TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, document_ref)
            );
            CREATE TABLE resource_bindings (
                namespace TEXT NOT NULL,
                resource_ref TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                ref TEXT NOT NULL,
                active INTEGER NOT NULL,
                bound_at TEXT NOT NULL,
                unbound_at TEXT,
                content_fingerprint TEXT NOT NULL,
                metadata_fingerprint TEXT NOT NULL,
                source_unit_refs TEXT NOT NULL DEFAULT '[]',
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, resource_ref)
            );
            CREATE TABLE chunk_fingerprints_contextual_512_50 (
                file_path TEXT PRIMARY KEY,
                mtime REAL NOT NULL,
                size_bytes INTEGER NOT NULL,
                checksum TEXT NOT NULL,
                indexed_at TEXT NOT NULL
            );
            CREATE TABLE embed_fingerprints_contextual_512_50_multilingual_e5_large (
                chunk_id TEXT PRIMARY KEY,
                fingerprint TEXT NOT NULL
            );
            CREATE TABLE meta_fingerprints_contextual_512_50_multilingual_e5_large (
                file_path TEXT PRIMARY KEY,
                meta_checksum TEXT NOT NULL
            );
            CREATE TABLE source_unit_fingerprints (
                namespace TEXT NOT NULL,
                document_ref TEXT NOT NULL,
                unit_ref TEXT NOT NULL,
                fingerprint TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                indexed_at TEXT NOT NULL,
                metadata_json TEXT NOT NULL DEFAULT '{}',
                PRIMARY KEY (namespace, document_ref, unit_ref)
            );
            CREATE TABLE source_checkpoints (
                namespace TEXT PRIMARY KEY,
                checkpoint_cursor TEXT,
                last_success_at TEXT,
                last_error TEXT,
                metadata_json TEXT NOT NULL DEFAULT '{}'
            );
            CREATE TABLE vec_meta_contextual_512_50_multilingual_e5_large (
                rowid INTEGER PRIMARY KEY,
                chunk_id TEXT NOT NULL UNIQUE,
                text_hash TEXT
            );
            CREATE TABLE vec_chunks_contextual_512_50_multilingual_e5_large (
                rowid INTEGER PRIMARY KEY,
                embedding BLOB NOT NULL
            );
            CREATE TABLE vec_config_contextual_512_50_multilingual_e5_large (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE vec_components_contextual_512_50_multilingual_e5_large (
                entity_id TEXT NOT NULL,
                component TEXT NOT NULL,
                embedding BLOB NOT NULL,
                PRIMARY KEY (entity_id, component)
            );
            CREATE TABLE search_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                query TEXT NOT NULL
            );
        """)

        weird_chunk_id = 'chunk:/ one {"quoted"} Привет'
        weird_entity_name = 'entity:/ two {"named"} Привет'
        weird_file_path = '/tmp/Doc One {"quoted"} Привет.md'
        weird_ref = f"filesystem:{weird_file_path}"
        weird_relation_id = 'rel:/ one {"typed"}'

        conn.execute(
            "INSERT INTO chunks_contextual_512_50 (chunk_id, heading_hierarchy, level, text) "
            "VALUES (?, ?, ?, ?), (?, ?, ?, ?)",
            (
                weird_chunk_id,
                '["Doc One", "Alpha"]',
                2,
                "Alpha body",
                "chunk:plain",
                '["Doc Two", "Beta"]',
                2,
                "Beta body",
            ),
        )
        conn.execute(
            "INSERT INTO chunk_source_provenance_contextual_512_50 "
            "(chunk_id, namespace, document_ref, source_unit_refs, chunk_strategy, parser_name) "
            "VALUES (?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?)",
            (
                weird_chunk_id,
                "filesystem",
                weird_file_path,
                '["unit:1", "unit:2"]',
                "contextual_512_50",
                "markdown",
                "chunk:plain",
                "filesystem",
                "/tmp/Doc Two.md",
                '["unit:3"]',
                "contextual_512_50",
                "markdown",
            ),
        )
        conn.execute(
            "INSERT INTO chunk_file_paths_contextual_512_50 (chunk_id, file_path, chunk_index) "
            "VALUES (?, ?, ?), (?, ?, ?)",
            (
                weird_chunk_id,
                weird_file_path,
                0,
                "chunk:plain",
                "/tmp/Doc Two.md",
                1,
            ),
        )
        conn.execute(
            "INSERT INTO source_documents "
            "(namespace, document_ref, ref, source_uri, file_path, media_type, parser_name, "
            "document_type, title, updated_at, content_fingerprint, metadata_fingerprint, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                weird_file_path,
                weird_ref,
                weird_file_path,
                weird_file_path,
                "text/markdown",
                "markdown",
                "document",
                "Doc One",
                "2026-06-12T00:00:00Z",
                "content-1",
                "meta-1",
                '{"lang":"ru"}',
                "filesystem",
                "/tmp/Doc Two.md",
                "filesystem:/tmp/Doc Two.md",
                "/tmp/Doc Two.md",
                "/tmp/Doc Two.md",
                "text/markdown",
                "markdown",
                "document",
                "Doc Two",
                "2026-06-12T00:05:00Z",
                "content-2",
                "meta-2",
                '{"lang":"en"}',
            ),
        )
        conn.execute(
            "INSERT INTO resource_bindings "
            "(namespace, resource_ref, document_ref, ref, active, bound_at, unbound_at, "
            "content_fingerprint, metadata_fingerprint, source_unit_refs, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                weird_file_path,
                weird_file_path,
                weird_ref,
                1,
                "2026-06-12T00:00:00Z",
                None,
                "content-1",
                "meta-1",
                '["unit:1", "unit:2"]',
                '{"state":"active"}',
                "filesystem",
                "/tmp/Doc Two.md",
                "/tmp/Doc Two.md",
                "filesystem:/tmp/Doc Two.md",
                0,
                "2026-06-12T00:05:00Z",
                "2026-06-12T00:10:00Z",
                "content-2",
                "meta-2",
                '["unit:3"]',
                '{"state":"inactive"}',
            ),
        )
        conn.execute(
            "INSERT INTO chunk_fingerprints_contextual_512_50 "
            "(file_path, mtime, size_bytes, checksum, indexed_at) VALUES (?, ?, ?, ?, ?)",
            (weird_file_path, 1718150400.0, 1234, "chunk-fp-1", "2026-06-12T00:00:00Z"),
        )
        conn.execute(
            "INSERT INTO embed_fingerprints_contextual_512_50_multilingual_e5_large "
            "(chunk_id, fingerprint) VALUES (?, ?), (?, ?)",
            (weird_chunk_id, "embed-fp-1", "chunk:plain", "embed-fp-2"),
        )
        conn.execute(
            "INSERT INTO meta_fingerprints_contextual_512_50_multilingual_e5_large "
            "(file_path, meta_checksum) VALUES (?, ?), (?, ?)",
            (weird_file_path, "meta-check-1", "/tmp/Doc Two.md", "meta-check-2"),
        )
        conn.execute(
            "INSERT INTO source_unit_fingerprints "
            "(namespace, document_ref, unit_ref, fingerprint, updated_at, indexed_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?), (?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                weird_file_path,
                "unit:1",
                "unit-fp-1",
                "2026-06-12T00:00:00Z",
                "2026-06-12T00:00:01Z",
                '{"speaker":"alice"}',
                "filesystem",
                weird_file_path,
                "unit:2",
                "unit-fp-2",
                "2026-06-12T00:00:02Z",
                "2026-06-12T00:00:03Z",
                '{"speaker":"bob"}',
                "filesystem",
                "/tmp/Doc Two.md",
                "unit:3",
                "unit-fp-3",
                "2026-06-12T00:05:00Z",
                "2026-06-12T00:05:01Z",
                '{"speaker":"carol"}',
            ),
        )
        conn.execute(
            "INSERT INTO source_checkpoints "
            "(namespace, checkpoint_cursor, last_success_at, last_error, metadata_json) VALUES (?, ?, ?, ?, ?)",
            ("filesystem", "cursor:{one}/Привет", "2026-06-12T00:11:00Z", None, '{"scope":"full"}'),
        )
        conn.execute(
            "INSERT INTO vec_meta_contextual_512_50_multilingual_e5_large "
            "(rowid, chunk_id, text_hash) VALUES (1, ?, ?), (2, ?, ?)",
            (weird_chunk_id, "hash-alpha", "chunk:plain", "hash-beta"),
        )
        conn.execute(
            "INSERT INTO vec_chunks_contextual_512_50_multilingual_e5_large (rowid, embedding) "
            "VALUES (?, ?), (?, ?)",
            (
                1,
                _serialize_embedding([0.11, 0.22, 0.33]),
                2,
                _serialize_embedding([0.44, 0.55, 0.66]),
            ),
        )
        conn.execute(
            "INSERT INTO vec_config_contextual_512_50_multilingual_e5_large (key, value) "
            "VALUES ('dim', '3'), ('model', 'multilingual-e5-large')",
        )
        conn.execute(
            "INSERT INTO vec_components_contextual_512_50_multilingual_e5_large "
            "(entity_id, component, embedding) VALUES (?, ?, ?), (?, ?, ?)",
            (
                weird_chunk_id,
                "text",
                _serialize_embedding([0.1, 0.2, 0.3]),
                weird_entity_name,
                "meta",
                _serialize_embedding([0.9, 0.8, 0.7]),
            ),
        )
        conn.execute("INSERT INTO search_log (query) VALUES (?)", ("alpha",))
        conn.commit()
    finally:
        conn.close()

    return {
        "chunk_id": weird_chunk_id,
        "entity_name": weird_entity_name,
        "file_path": weird_file_path,
        "ref": weird_ref,
        "relation_id": weird_relation_id,
    }


def test_dedupe_fingerprint_payloads_keeps_latest_indexed_at() -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        _dedupe_fingerprint_payloads,
    )

    rows = [
        {
            "fingerprint_id": "chunk::/tmp/doc.md",
            "content_fingerprint": "old",
            "metadata_fingerprint": None,
            "metadata": {"indexed_at": "2026-06-12T00:00:00Z"},
        },
        {
            "fingerprint_id": "chunk::/tmp/doc.md",
            "content_fingerprint": "new",
            "metadata_fingerprint": None,
            "metadata": {"indexed_at": "2026-06-12T00:01:00Z"},
        },
        {
            "fingerprint_id": "chunk::/tmp/other.md",
            "content_fingerprint": "other",
            "metadata_fingerprint": None,
            "metadata": {"indexed_at": "2026-06-12T00:00:30Z"},
        },
    ]

    deduped = _dedupe_fingerprint_payloads(rows)

    assert len(deduped) == 2
    by_id = {row["fingerprint_id"]: row for row in deduped}
    assert by_id["chunk::/tmp/doc.md"]["content_fingerprint"] == "new"
    assert by_id["chunk::/tmp/other.md"]["content_fingerprint"] == "other"


class _FakeGraphExporter:
    def __init__(self, fixture_ids: dict[str, str]) -> None:
        self.fixture_ids = fixture_ids
        self.inventory_calls = 0
        self.row_calls = 0

    def export_inventory(self) -> dict[str, object]:
        self.inventory_calls += 1
        return {
            "node_counts": {"File": 2, "Section": 2, "Entity": 1, "Tag": 1},
            "edge_count": 2,
            "relation_summaries": [
                {
                    "relation_label": "MENTIONS",
                    "count": 1,
                    "weights": [0.75],
                    "metadata_keys": ["evidence", "confirmed", "rank"],
                    "property_value_types": {
                        "weight": "float",
                        "evidence": "string",
                        "confirmed": "boolean",
                        "rank": "integer",
                    },
                },
                {
                    "relation_label": "HAS_TAG",
                    "count": 1,
                    "weights": [0.5],
                    "metadata_keys": ["source"],
                    "property_value_types": {"weight": "float", "source": "string"},
                },
            ],
        }

    def export_rows(self) -> dict[str, object]:
        self.row_calls += 1
        return {
            "entities": [
                {
                    "name": self.fixture_ids["entity_name"],
                    "entity_type": "PERSON",
                    "source": self.fixture_ids["chunk_id"],
                }
            ],
            "relations": [
                {
                    "relation_id": self.fixture_ids["relation_id"],
                    "source_id": self.fixture_ids["chunk_id"],
                    "target_id": self.fixture_ids["entity_name"],
                    "relation_type": "MENTIONS",
                    "weight": 0.75,
                    "properties": {
                        "evidence": "quoted name",
                        "confirmed": True,
                        "rank": 7,
                    },
                },
                {
                    "relation_id": "tag:1",
                    "source_id": self.fixture_ids["chunk_id"],
                    "target_id": "tag/phase38",
                    "relation_type": "HAS_TAG",
                    "weight": 0.5,
                    "properties": {"source": "frontmatter"},
                },
            ],
        }


class _FakeFeedbackProvider:
    def __init__(self) -> None:
        self.calls: list[tuple[int, bool]] = []

    def list_all(self, limit: int = 50, include_closed: bool = False) -> list[dict[str, object]]:
        self.calls.append((limit, include_closed))
        return [
            {
                "id": 'feedback:/ one {"quoted"}',
                "submitted_at": 1718150400,
                "message": "Alpha feedback",
                "severity": "bug",
                "status": "done",
                "context": "surreal import",
                "model": "gpt-5",
            },
            {
                "id": "feedback:plain",
                "submitted_at": 1718150410,
                "message": "Beta feedback",
                "severity": "suggestion",
                "status": "open",
                "context": None,
                "model": "gpt-5",
            },
        ]


def _write_gate_report(path: Path, *, go_no_go: str = "PASS") -> Path:
    path.write_text(
        "\n".join(
            [
                "# Phase 38 Plan 05 Embedded Safety Gate",
                "",
                "- generated_at: 2026-06-12T14:38:46.886752+00:00",
                "- downstream_plan: 38-02",
                f"- go_no_go: {go_no_go}",
                "- requirement: STOR-04",
                "",
                "## Decision",
                "Embedded `surrealkv://` atomicity and writer-safety evidence passed. `38-02` may continue.",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return path


def _write_graph_export(path: Path, fixture_ids: dict[str, str]) -> Path:
    exporter = _FakeGraphExporter(fixture_ids)
    payload = {
        "exported_at": "2026-06-12T00:12:00Z",
        "inventory": exporter.export_inventory(),
        "rows": exporter.export_rows(),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def _write_feedback_export(
    path: Path,
    provider: _FakeFeedbackProvider,
    *,
    rows: list[dict[str, object]] | None = None,
    truncated: bool = False,
) -> Path:
    payload = {
        "exported_at": "2026-06-12T00:13:00Z",
        "truncated": truncated,
        "rows": rows if rows is not None else provider.list_all(limit=10_000, include_closed=True),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    return path


def test_phase38_runner_surface_is_replaced_by_phase41_runner() -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    assert hasattr(migrate_module, "run_surreal_migration")
    assert hasattr(migrate_module, "SurrealMigrationMode")
    assert not hasattr(migrate_module, "run_surreal_import")
    assert not hasattr(migrate_module, "SurrealImportMode")


def test_run_surreal_migration_dry_run_counts_transformable_rows_without_writing(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealTargetMode,
        build_surreal_migration_manifest,
        run_surreal_migration,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    feedback_provider = _FakeFeedbackProvider()
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    graph_payload = json.loads(graph_export_path.read_text(encoding="utf-8"))
    graph_payload["rows"]["files"] = [
        {
            "id": fixture_ids["file_path"],
            "original_id": fixture_ids["file_path"],
            "file_path": fixture_ids["file_path"],
            "path": fixture_ids["file_path"],
            "title": "Doc One",
            "metadata": {},
        }
    ]
    graph_payload["rows"]["sections"] = [
        {
            "id": fixture_ids["chunk_id"],
            "original_id": fixture_ids["chunk_id"],
            "chunk_id": fixture_ids["chunk_id"],
            "heading": "Doc One",
            "level": 1,
            "file_path": fixture_ids["file_path"],
            "text_preview": "Alpha body",
            "metadata": {},
        }
    ]
    graph_payload["rows"]["tags"] = [
        {
            "id": "tag/phase38",
            "original_id": "tag/phase38",
            "name": "tag/phase38",
            "metadata": {},
        }
    ]
    graph_export_path.write_text(
        json.dumps(graph_payload, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        feedback_provider,
    )

    manifest = build_surreal_migration_manifest(
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{tmp_path / 'dry-run.db'}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
    )

    report = run_surreal_migration(
        mode=SurrealMigrationMode.DRY_RUN,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{tmp_path / 'dry-run.db'}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
    )

    assert manifest.schema_version == report.schema_version
    assert report.mode is SurrealMigrationMode.DRY_RUN
    assert report.status == "dry-run"
    assert report.committed_success is False
    assert report.expected_counts["documents"] == 2
    assert report.expected_counts["source_units"] == 3
    assert report.expected_counts["chunks"] == 2
    assert report.expected_counts["chunk_file_bindings"] == 2
    assert report.expected_counts["embeddings"] == 2
    assert report.expected_counts["vector_components"] == 0
    assert report.expected_counts["graph_files"] == 1
    assert report.expected_counts["graph_entities"] == 1
    assert report.expected_counts["graph_relations"] == 2
    assert report.expected_counts["feedback"] == 2
    assert report.expected_counts["cursors"] == 2
    assert report.expected_counts["checkpoints"] == 1
    assert report.source_capture_manifest is not None
    assert report.source_capture_manifest.skew_policy == "bounded_skew_accepted"
    assert report.target_inspection_performed is False
    assert not (tmp_path / "dry-run.db").exists()


def test_run_surreal_migration_apply_preserves_ids_vectors_feedback_and_graph_properties(
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
        SurrealRecordIdCodec,
        SurrealStoreConfig,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    feedback_provider = _FakeFeedbackProvider()
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        feedback_provider,
    )
    gate_path = _write_gate_report(tmp_path / "38-05-EMBEDDED-SAFETY-GATE.md")
    target_path = tmp_path / "surreal-import.db"

    report = run_surreal_migration(
        mode=SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{target_path}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=gate_path,
        overwrite_policy=SurrealOverwritePolicy.REFUSE,
    )

    assert report.status == "applied"
    assert report.committed_success is True
    assert report.gate_status == "passed"
    assert report.embedding_reuse_verified is True
    assert report.expected_vector_dimension == 3
    assert {checkpoint.phase_name.value for checkpoint in report.phase_checkpoints} >= {
        "schema",
        "documents",
        "chunks",
        "chunk_file_bindings",
        "embeddings",
        "feedback",
        "cursors",
        "checkpoints",
    }

    codec = SurrealRecordIdCodec()
    config = SurrealStoreConfig(
        url=f"surrealkv://{target_path}",
        namespace="dotmd",
        database="phase41_migration",
    )
    with SurrealConnection(config) as connection:
        stored_chunk = connection.select(codec.encode("chunks", fixture_ids["chunk_id"]))
        stored_embedding = connection.select(
            codec.encode(
                "embeddings",
                "contextual_512_50\x1fmultilingual-e5-large\x1f" + fixture_ids["chunk_id"],
            )
        )
        stored_entity = connection.select(codec.encode("entities", fixture_ids["entity_name"]))
        stored_relation = connection.select(codec.encode("relations", fixture_ids["relation_id"]))
        stored_feedback = connection.select(codec.encode("feedback", 'feedback:/ one {"quoted"}'))
        stored_checkpoint = connection.select(codec.encode("checkpoints", "filesystem"))
        stored_cursor = connection.select(codec.encode("cursors", fixture_ids["ref"]))
        file_bindings = connection.scan_table("chunk_file_bindings")

    assert stored_chunk["original_chunk_id"] == fixture_ids["chunk_id"]
    assert stored_chunk["ref"] == fixture_ids["ref"]
    assert stored_embedding["chunk_id"] == fixture_ids["chunk_id"]
    assert stored_embedding["chunk_strategy"] == "contextual_512_50"
    assert stored_embedding["text_hash"] == "hash-alpha"
    assert stored_embedding["vector_rowid"] == 1
    assert len(stored_embedding["embedding"]) == 3
    assert stored_entity["original_entity_name"] == fixture_ids["entity_name"]
    assert stored_relation["rel_type"] == "MENTIONS"
    assert stored_relation["weight"] == pytest.approx(0.75)
    assert stored_relation["properties"]["confirmed"] is True
    assert isinstance(stored_relation["properties"]["rank"], int)
    assert stored_feedback["original_feedback_id"] == 'feedback:/ one {"quoted"}'
    assert stored_checkpoint["checkpoint_cursor"] == "cursor:{one}/Привет"
    assert stored_cursor["ref"] == fixture_ids["ref"]
    assert [
        (row["chunk_id"], row["file_path"], row["chunk_index"])
        for row in sorted(file_bindings, key=lambda item: item["chunk_index"])
    ] == [
        (fixture_ids["chunk_id"], fixture_ids["file_path"], 0),
        ("chunk:plain", "/tmp/Doc Two.md", 1),
    ]


def test_feedback_export_limit_is_configurable_and_reports_truncation(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealMigrationMode,
        SurrealTargetMode,
        run_surreal_migration,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    provider = _FakeFeedbackProvider()
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    feedback_rows = provider.list_all(limit=1, include_closed=True)
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        provider,
        rows=feedback_rows,
        truncated=True,
    )

    report = run_surreal_migration(
        mode=SurrealMigrationMode.PLAN,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{tmp_path / 'truncated.db'}",
        target_mode=SurrealTargetMode.EMBEDDED_LOCAL,
    )

    assert report.status == "source_capture_incomplete"
    assert report.committed_success is False
    assert report.errors
    assert any("truncated" in error.lower() for error in report.errors)


def test_run_surreal_migration_failed_apply_reports_partial_writes_without_rollback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]
    from dotmd.storage import surreal as surreal_module  # type: ignore[import-not-found]

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    feedback_provider = _FakeFeedbackProvider()
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        feedback_provider,
    )
    gate_path = _write_gate_report(tmp_path / "gate.md")
    target_path = tmp_path / "rollback.db"

    def _boom(self, rows):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced feedback import failure")

    monkeypatch.setattr(surreal_module.SurrealFeedbackStore, "replace_feedback_rows", _boom)

    report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{target_path}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=gate_path,
    )

    assert report.status == "failed"
    assert report.committed_success is False
    assert report.partial_writes_present is True
    assert report.restore_required is True
    assert report.cleanup_attempted is False
    assert report.last_successful_phase is not None
    assert report.failed_phase is not None
    assert report.errors

    config = surreal_module.SurrealStoreConfig(
        url=f"surrealkv://{target_path}",
        namespace="dotmd",
        database="phase41_migration",
    )
    with surreal_module.SurrealConnection(config) as connection:
        documents = connection.scan_table("documents")
        chunks = connection.scan_table("chunks")

    assert documents
    assert chunks


def test_apply_can_resume_from_progress_without_rewriting_completed_phases(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]
    from dotmd.storage import surreal as surreal_module  # type: ignore[import-not-found]

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_export_path = _write_graph_export(tmp_path / "graph-export.json", fixture_ids)
    feedback_export_path = _write_feedback_export(
        tmp_path / "feedback-export.json",
        _FakeFeedbackProvider(),
    )
    gate_path = _write_gate_report(tmp_path / "gate.md")
    target_path = tmp_path / "resume.db"
    progress_path = tmp_path / "progress.json"
    original_feedback_writer = surreal_module.SurrealFeedbackStore.replace_feedback_rows

    def _fail_feedback(self, rows):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced resume checkpoint")

    monkeypatch.setattr(surreal_module.SurrealFeedbackStore, "replace_feedback_rows", _fail_feedback)

    first_report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{target_path}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=gate_path,
        progress_path=progress_path,
    )

    assert first_report.status == "failed"
    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_payload["elapsed_seconds"] >= 0
    assert progress_payload["process_rss_bytes"] > 0
    assert progress_payload["target_size_bytes"] is not None
    assert "current_phase_percent" in progress_payload
    applied_phases = {
        row["phase_name"]
        for row in progress_payload["phase_checkpoints"]
        if row["status"] == "applied"
    }
    assert "documents" in applied_phases

    def _documents_should_be_skipped(self, rows):  # type: ignore[no-untyped-def]
        raise AssertionError("resume should skip completed document phase")

    monkeypatch.setattr(
        surreal_module.SurrealFeedbackStore,
        "replace_feedback_rows",
        original_feedback_writer,
    )
    monkeypatch.setattr(
        surreal_module.SurrealMetadataStore,
        "replace_documents",
        _documents_should_be_skipped,
    )

    second_report = migrate_module.run_surreal_migration(
        mode=migrate_module.SurrealMigrationMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_export_path=graph_export_path,
        feedback_export_path=feedback_export_path,
        target_url=f"surrealkv://{target_path}",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        gate_report_path=gate_path,
        progress_path=progress_path,
        resume_from_progress=True,
    )

    assert second_report.status == "applied", second_report.errors
    assert second_report.committed_success is True


def test_list_phase_progress_is_written_per_batch(tmp_path: Path) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    progress_path = tmp_path / "progress.json"
    checkpoint = migrate_module.SurrealMigrationPhaseCheckpoint(
        phase_name=migrate_module.SurrealMigrationPhaseName.CHUNKS,
        planned_count=2501,
    )
    report = migrate_module.SurrealMigrationReport(
        schema_version="test",
        mode=migrate_module.SurrealMigrationMode.APPLY,
        status="apply",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        overwrite_policy=migrate_module.SurrealOverwritePolicy.REFUSE,
        target_url=f"surrealkv://{tmp_path / 'target.db'}",
        target_namespace="dotmd",
        target_database="phase43",
        source_capture_manifest=None,
        phase_checkpoints=[checkpoint],
    )
    batch_lengths: list[int] = []

    def _writer(rows):  # type: ignore[no-untyped-def]
        batch_lengths.append(len(rows))
        return len(rows)

    migrate_module._write_list_phase(
        checkpoint,
        report=report,
        rows=[{"n": i} for i in range(2501)],
        writer=_writer,
        batch_size=1000,
        progress_path=progress_path,
    )

    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert batch_lengths == [1000, 1000, 501]
    assert progress_payload["current_phase"] == "chunks"
    assert progress_payload["current_phase_applied_count"] == 2501
    assert progress_payload["current_phase_percent"] == 100.0
    assert progress_payload["elapsed_seconds"] >= 0
    assert progress_payload["process_rss_bytes"] > 0
    assert "current_phase_eta_human" in progress_payload
    assert "overall_eta_human" in progress_payload


def test_progress_snapshot_estimates_eta_for_partial_work(tmp_path: Path) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    progress_path = tmp_path / "progress.json"
    checkpoint = migrate_module.SurrealMigrationPhaseCheckpoint(
        phase_name=migrate_module.SurrealMigrationPhaseName.CHUNKS,
        planned_count=100,
        status="running",
    )
    report = migrate_module.SurrealMigrationReport(
        schema_version="test",
        mode=migrate_module.SurrealMigrationMode.APPLY,
        status="apply",
        target_mode=migrate_module.SurrealTargetMode.EMBEDDED_LOCAL,
        overwrite_policy=migrate_module.SurrealOverwritePolicy.REFUSE,
        target_url=f"surrealkv://{tmp_path / 'target.db'}",
        target_namespace="dotmd",
        target_database="phase43",
        source_capture_manifest=None,
        phase_checkpoints=[checkpoint],
    )
    report.started_at_monotonic -= 10

    migrate_module._write_progress_snapshot(
        progress_path,
        report=report,
        checkpoint=checkpoint,
        applied_count=25,
    )

    progress_payload = json.loads(progress_path.read_text(encoding="utf-8"))
    assert progress_payload["current_phase_rate_per_second"] == pytest.approx(2.5, abs=0.1)
    assert progress_payload["current_phase_eta_seconds"] == pytest.approx(30.0, abs=1.0)
    assert progress_payload["current_phase_eta_human"] in {"30s", "31s"}
    assert progress_payload["overall_eta_seconds"] == pytest.approx(30.0, abs=1.0)
    assert progress_payload["overall_eta_human"] in {"30s", "31s"}


def test_eta_human_omits_seconds_after_five_minutes() -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    assert migrate_module._format_duration(60) == "1m"
    assert migrate_module._format_duration(300) == "5m"
    assert migrate_module._format_duration(301) == "5m"
    assert migrate_module._format_duration(329) == "5m"
    assert migrate_module._format_duration(330) == "6m"
    assert migrate_module._format_duration(3900) == "1h 5m"
