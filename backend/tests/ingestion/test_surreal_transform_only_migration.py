from __future__ import annotations

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
            (weird_chunk_id, "hash-α", "chunk:plain", "hash-β"),
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


def test_run_surreal_import_dry_run_counts_transformable_rows_without_writing(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealImportMode,
        run_surreal_import,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_exporter = _FakeGraphExporter(fixture_ids)
    feedback_provider = _FakeFeedbackProvider()

    report = run_surreal_import(
        mode=SurrealImportMode.DRY_RUN,
        sqlite_snapshot_path=db_path,
        graph_exporter=graph_exporter,
        feedback_provider=feedback_provider,
        target_url=f"surrealkv://{tmp_path / 'dry-run.db'}",
    )

    assert report.mode is SurrealImportMode.DRY_RUN
    assert report.status == "dry-run"
    assert report.committed is False
    assert report.rolled_back is False
    assert report.applied_records == 0
    assert report.counts.documents == 2
    assert report.counts.source_units == 3
    assert report.counts.chunks == 2
    assert report.counts.embeddings == 2
    assert report.counts.vector_components == 2
    assert report.counts.entities == 1
    assert report.counts.relations == 2
    assert report.counts.feedback == 2
    assert report.counts.cursors == 2
    assert report.counts.checkpoints == 1
    assert "search_log" in report.unsupported_categories
    assert feedback_provider.calls == [(1001, True)]
    assert graph_exporter.inventory_calls == 1
    assert graph_exporter.row_calls == 1
    assert not (tmp_path / "dry-run.db").exists()


def test_run_surreal_import_apply_preserves_ids_vectors_feedback_and_graph_properties(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealImportMode,
        run_surreal_import,
    )
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealRecordIdCodec,
        SurrealStoreConfig,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_exporter = _FakeGraphExporter(fixture_ids)
    feedback_provider = _FakeFeedbackProvider()
    gate_path = _write_gate_report(tmp_path / "38-05-EMBEDDED-SAFETY-GATE.md")
    target_path = tmp_path / "surreal-import.db"

    report = run_surreal_import(
        mode=SurrealImportMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_exporter=graph_exporter,
        feedback_provider=feedback_provider,
        target_url=f"surrealkv://{target_path}",
        gate_report_path=gate_path,
    )

    assert report.status == "committed"
    assert report.committed is True
    assert report.rolled_back is False
    assert report.gate_status == "passed"
    assert report.applied_records == report.counts.total_records()

    codec = SurrealRecordIdCodec()
    config = SurrealStoreConfig(
        url=f"surrealkv://{target_path}",
        namespace="dotmd",
        database="phase38_import",
    )
    with SurrealConnection(config) as connection:
        stored_chunk = connection.select(codec.encode("chunks", fixture_ids["chunk_id"]))
        stored_embedding = connection.select(codec.encode("embeddings", fixture_ids["chunk_id"]))
        stored_entity = connection.select(codec.encode("entities", fixture_ids["entity_name"]))
        stored_relation = connection.select(codec.encode("relations", fixture_ids["relation_id"]))
        stored_feedback = connection.select(codec.encode("feedback", 'feedback:/ one {"quoted"}'))
        stored_checkpoint = connection.select(codec.encode("checkpoints", "filesystem"))
        stored_cursor = connection.select(
            codec.encode("cursors", f"filesystem\x1f{fixture_ids['file_path']}")
        )
        file_bindings = connection.scan_table("chunk_file_bindings")

    assert stored_chunk["original_chunk_id"] == fixture_ids["chunk_id"]
    assert stored_chunk["ref"] == fixture_ids["ref"]
    assert stored_embedding["chunk_id"] == fixture_ids["chunk_id"]
    assert stored_embedding["text_hash"] == "hash-α"
    assert stored_embedding["vector_rowid"] == 1
    assert len(stored_embedding["embedding"]) == 3
    assert stored_entity["original_entity_name"] == fixture_ids["entity_name"]
    assert stored_relation["relation_type"] == "MENTIONS"
    assert stored_relation["weight"] == pytest.approx(0.75)
    assert stored_relation["properties"]["confirmed"] is True
    assert isinstance(stored_relation["properties"]["rank"], int)
    assert stored_feedback["original_feedback_id"] == 'feedback:/ one {"quoted"}'
    assert stored_checkpoint["checkpoint_cursor"] == "cursor:{one}/Привет"
    assert stored_cursor["original_ref"] == fixture_ids["ref"]
    assert [
        (row["chunk_id"], row["file_path"], row["chunk_index"])
        for row in sorted(file_bindings, key=lambda item: item["chunk_index"])
    ] == [
        (fixture_ids["chunk_id"], fixture_ids["file_path"], 0),
        ("chunk:plain", "/tmp/Doc Two.md", 1),
    ]


@pytest.mark.parametrize(
    ("gate_state", "expected_status"),
    [("PASS", "passed"), ("BLOCKED", "gate_blocked")],
)
def test_run_surreal_import_apply_requires_embedded_safety_gate(
    tmp_path: Path,
    gate_state: str,
    expected_status: str,
) -> None:
    from dotmd.ingestion.migrate_surreal import (  # type: ignore[import-not-found]
        SurrealImportMode,
        run_surreal_import,
    )

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_exporter = _FakeGraphExporter(fixture_ids)
    feedback_provider = _FakeFeedbackProvider()
    gate_path = _write_gate_report(tmp_path / "gate.md", go_no_go=gate_state)

    report = run_surreal_import(
        mode=SurrealImportMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_exporter=graph_exporter,
        feedback_provider=feedback_provider,
        target_url=f"surrealkv://{tmp_path / 'gate-test.db'}",
        gate_report_path=gate_path,
    )

    assert report.gate_status == expected_status
    if gate_state == "PASS":
        assert report.committed is True
    else:
        assert report.committed is False
        assert report.applied_records == 0
        assert report.errors


def test_load_feedback_rows_for_surreal_uses_provider_and_never_opens_feedback_sqlite(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    provider = _FakeFeedbackProvider()

    def _forbid_feedback_connect(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("feedback.db direct access is forbidden in 38-02")

    monkeypatch.setattr(migrate_module.sqlite3, "connect", _forbid_feedback_connect)

    rows = migrate_module.load_feedback_rows_for_surreal(provider)

    assert len(rows) == 2
    assert provider.calls == [(1001, True)]


def test_load_feedback_rows_for_surreal_fails_when_export_may_be_truncated() -> None:
    from dotmd.ingestion.migrate_surreal import (
        load_feedback_rows_for_surreal,  # type: ignore[import-not-found]
    )

    class PageLimitProvider:
        def list_all(
            self, limit: int = 50, include_closed: bool = False
        ) -> list[dict[str, object]]:
            return [
                {
                    "id": f"feedback-{index}",
                    "submitted_at": index,
                    "message": "x",
                }
                for index in range(limit)
            ]

    with pytest.raises(RuntimeError, match="exhaustive feedback export"):
        load_feedback_rows_for_surreal(PageLimitProvider())


def test_load_graph_rows_for_surreal_preserves_labels_weights_keys_and_typed_properties(
    tmp_path: Path,
) -> None:
    from dotmd.ingestion.migrate_surreal import (
        load_graph_rows_for_surreal,  # type: ignore[import-not-found]
    )

    fixture_ids = {
        "chunk_id": 'chunk:/ one {"quoted"} Привет',
        "entity_name": 'entity:/ two {"named"} Привет',
        "relation_id": 'rel:/ one {"typed"}',
        "file_path": "/tmp/Doc One.md",
        "ref": "filesystem:/tmp/Doc One.md",
    }
    graph_exporter = _FakeGraphExporter(fixture_ids)

    graph_rows = load_graph_rows_for_surreal(graph_exporter)

    assert len(graph_rows["entities"]) == 1
    assert len(graph_rows["relations"]) == 2
    mentions = graph_rows["relations"][0]
    assert mentions["relation_type"] == "MENTIONS"
    assert mentions["weight"] == pytest.approx(0.75)
    assert mentions["properties"]["confirmed"] is True
    assert isinstance(mentions["properties"]["rank"], int)
    assert graph_exporter.inventory_calls == 1
    assert graph_exporter.row_calls == 1


def test_run_surreal_import_never_reaches_embedding_or_extraction_recomputation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_exporter = _FakeGraphExporter(fixture_ids)
    feedback_provider = _FakeFeedbackProvider()

    def _explode(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("transform-only import must not recompute embeddings or entities")

    monkeypatch.setattr(migrate_module, "encode_batch", _explode, raising=False)
    monkeypatch.setattr(migrate_module, "_embed_chunks", _explode, raising=False)
    monkeypatch.setattr(migrate_module, "from_pretrained", _explode, raising=False)
    monkeypatch.setattr(migrate_module, "index_single_file", _explode, raising=False)

    report = migrate_module.run_surreal_import(
        mode=migrate_module.SurrealImportMode.DRY_RUN,
        sqlite_snapshot_path=db_path,
        graph_exporter=graph_exporter,
        feedback_provider=feedback_provider,
        target_url=f"surrealkv://{tmp_path / 'recompute-guard.db'}",
    )

    assert report.status == "dry-run"


def test_run_surreal_import_rolls_back_written_records_on_apply_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dotmd.ingestion import migrate_surreal as migrate_module  # type: ignore[import-not-found]
    from dotmd.storage import surreal as surreal_module  # type: ignore[import-not-found]

    db_path = tmp_path / "transform-only.db"
    fixture_ids = _create_transform_only_fixture(db_path)
    graph_exporter = _FakeGraphExporter(fixture_ids)
    feedback_provider = _FakeFeedbackProvider()
    gate_path = _write_gate_report(tmp_path / "gate.md")
    target_path = tmp_path / "rollback.db"

    original_method = surreal_module.SurrealFeedbackStore.replace_feedback_rows

    def _boom(self, rows):  # type: ignore[no-untyped-def]
        raise RuntimeError("forced feedback import failure")

    monkeypatch.setattr(surreal_module.SurrealFeedbackStore, "replace_feedback_rows", _boom)

    report = migrate_module.run_surreal_import(
        mode=migrate_module.SurrealImportMode.APPLY,
        sqlite_snapshot_path=db_path,
        graph_exporter=graph_exporter,
        feedback_provider=feedback_provider,
        target_url=f"surrealkv://{target_path}",
        gate_report_path=gate_path,
    )

    assert report.status == "rolled_back"
    assert report.committed is False
    assert report.rolled_back is True
    assert report.errors

    monkeypatch.setattr(
        surreal_module.SurrealFeedbackStore,
        "replace_feedback_rows",
        original_method,
    )

    config = surreal_module.SurrealStoreConfig(
        url=f"surrealkv://{target_path}",
        namespace="dotmd",
        database="phase38_import",
    )
    with surreal_module.SurrealConnection(config) as connection:
        documents = connection.select("documents")
        chunks = connection.select("chunks")

    assert documents == []
    assert chunks == []
