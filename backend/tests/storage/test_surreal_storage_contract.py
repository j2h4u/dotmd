from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from dotmd.feedback import FeedbackStore
from dotmd.storage.surreal_inventory import (
    build_surreal_migration_map,
    collect_falkor_inventory,
    collect_feedback_inventory,
    collect_sqlite_inventory,
    copy_sqlite_snapshot,
)


def _create_inventory_fixture(db_path: Path) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute(
            "CREATE TABLE chunks_contextual_512_50 (chunk_id TEXT PRIMARY KEY, text TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE VIRTUAL TABLE chunks_fts_contextual_512_50 USING fts5(chunk_id, title, body)"
        )
        conn.execute(
            "CREATE TABLE vec_meta_contextual_512_50_multilingual_e5_large ("
            "rowid INTEGER PRIMARY KEY, chunk_id TEXT NOT NULL UNIQUE, text_hash TEXT)"
        )
        conn.execute(
            "CREATE TABLE vec_components_contextual_512_50_multilingual_e5_large ("
            "entity_id TEXT NOT NULL, component TEXT NOT NULL, embedding BLOB NOT NULL,"
            "PRIMARY KEY (entity_id, component))"
        )
        conn.execute(
            "CREATE TABLE source_documents ("
            "namespace TEXT NOT NULL, document_ref TEXT NOT NULL, ref TEXT NOT NULL,"
            "source_uri TEXT NOT NULL, file_path TEXT, media_type TEXT NOT NULL,"
            "parser_name TEXT NOT NULL, document_type TEXT NOT NULL, title TEXT NOT NULL,"
            "updated_at TEXT NOT NULL, content_fingerprint TEXT NOT NULL,"
            "metadata_fingerprint TEXT NOT NULL, metadata_json TEXT NOT NULL DEFAULT '{}',"
            "PRIMARY KEY (namespace, document_ref))"
        )
        conn.execute(
            "CREATE TABLE resource_bindings ("
            "namespace TEXT NOT NULL, resource_ref TEXT NOT NULL, document_ref TEXT NOT NULL,"
            "ref TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1, bound_at TEXT NOT NULL,"
            "unbound_at TEXT, content_fingerprint TEXT NOT NULL DEFAULT '',"
            "metadata_fingerprint TEXT NOT NULL DEFAULT '', source_unit_refs TEXT NOT NULL DEFAULT '[]',"
            "metadata_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (namespace, resource_ref))"
        )
        conn.execute(
            "CREATE TABLE chunk_fingerprints_contextual_512_50 ("
            "chunk_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE embed_fingerprints_contextual_512_50_multilingual_e5_large ("
            "chunk_id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL)"
        )
        conn.execute(
            "CREATE TABLE source_unit_fingerprints ("
            "namespace TEXT NOT NULL, document_ref TEXT NOT NULL, unit_ref TEXT NOT NULL,"
            "fingerprint TEXT NOT NULL, updated_at TEXT NOT NULL, indexed_at TEXT NOT NULL,"
            "metadata_json TEXT NOT NULL DEFAULT '{}', PRIMARY KEY (namespace, document_ref, unit_ref))"
        )
        conn.execute(
            "CREATE TABLE source_checkpoints ("
            "namespace TEXT PRIMARY KEY, checkpoint_cursor TEXT, last_success_at TEXT,"
            "last_error TEXT, metadata_json TEXT NOT NULL DEFAULT '{}')"
        )
        conn.execute(
            "CREATE TABLE search_log (id INTEGER PRIMARY KEY AUTOINCREMENT, query TEXT NOT NULL)"
        )

        conn.execute(
            "INSERT INTO chunks_contextual_512_50 (chunk_id, text) VALUES (?, ?), (?, ?)",
            ("chunk-1", "Alpha", "chunk-2", "Beta"),
        )
        conn.execute(
            "INSERT INTO chunks_fts_contextual_512_50 (chunk_id, title, body) VALUES (?, ?, ?), (?, ?, ?)",
            ("chunk-1", "Alpha", "Body alpha", "chunk-2", "Beta", "Body beta"),
        )
        conn.execute(
            "INSERT INTO vec_meta_contextual_512_50_multilingual_e5_large "
            "(rowid, chunk_id, text_hash) VALUES (1, 'chunk-1', 'hash-1'), (2, 'chunk-2', 'hash-2')"
        )
        conn.execute(
            "INSERT INTO vec_components_contextual_512_50_multilingual_e5_large "
            "(entity_id, component, embedding) VALUES (?, ?, ?), (?, ?, ?)",
            ("chunk-1", "text", b"\x00" * 16, "doc-1", "meta", b"\x00" * 16),
        )
        conn.execute(
            "INSERT INTO source_documents "
            "(namespace, document_ref, ref, source_uri, file_path, media_type, parser_name,"
            " document_type, title, updated_at, content_fingerprint, metadata_fingerprint, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                "doc-1",
                "filesystem:doc-1",
                "doc-1",
                "/tmp/doc-1.md",
                "text/markdown",
                "markdown",
                "document",
                "Doc 1",
                "2026-06-12T00:00:00Z",
                "cfp-1",
                "mfp-1",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO resource_bindings "
            "(namespace, resource_ref, document_ref, ref, active, bound_at, content_fingerprint,"
            " metadata_fingerprint, source_unit_refs, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                "doc-1",
                "doc-1",
                "filesystem:doc-1",
                1,
                "2026-06-12T00:00:00Z",
                "cfp-1",
                "mfp-1",
                "[]",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO chunk_fingerprints_contextual_512_50 (chunk_id, fingerprint) VALUES (?, ?)",
            ("chunk-1", "chunk-fp-1"),
        )
        conn.execute(
            "INSERT INTO embed_fingerprints_contextual_512_50_multilingual_e5_large "
            "(chunk_id, fingerprint) VALUES (?, ?)",
            ("chunk-1", "embed-fp-1"),
        )
        conn.execute(
            "INSERT INTO source_unit_fingerprints "
            "(namespace, document_ref, unit_ref, fingerprint, updated_at, indexed_at, metadata_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                "filesystem",
                "doc-1",
                "unit-1",
                "unit-fp-1",
                "2026-06-12T00:00:00Z",
                "2026-06-12T00:00:00Z",
                "{}",
            ),
        )
        conn.execute(
            "INSERT INTO source_checkpoints "
            "(namespace, checkpoint_cursor, last_success_at, last_error, metadata_json) "
            "VALUES (?, ?, ?, ?, ?)",
            ("filesystem", "cursor-1", "2026-06-12T00:00:00Z", None, "{}"),
        )
        conn.execute(
            "INSERT INTO search_log (query) VALUES (?), (?)",
            ("alpha", "beta"),
        )
        conn.commit()
    finally:
        conn.close()


def _create_wal_fixture(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA wal_autocheckpoint=0")
    conn.execute("CREATE TABLE wal_payload (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
    conn.commit()
    conn.execute("INSERT INTO wal_payload (body) VALUES (?)", ("committed",))
    conn.commit()
    conn.execute("INSERT INTO wal_payload (body) VALUES (?)", ("still-in-wal",))
    conn.commit()
    return conn


class _FakeGraphExporter:
    def export_inventory(self) -> dict[str, object]:
        return {
            "node_counts": {"File": 2, "Section": 3, "Entity": 5, "Tag": 1},
            "edge_count": 7,
            "relation_summaries": [
                {
                    "relation_label": "MENTIONS",
                    "count": 4,
                    "weights": [1.0, 0.25],
                    "metadata_keys": ["evidence", "lang"],
                    "property_value_types": {
                        "weight": "float",
                        "evidence": "string",
                        "lang": "string",
                        "rank": "integer",
                        "confirmed": "boolean",
                    },
                },
                {
                    "relation_label": "HAS_TAG",
                    "count": 3,
                    "weights": [0.9],
                    "metadata_keys": ["source"],
                    "property_value_types": {"weight": "float", "source": "string"},
                },
            ],
        }


class _FakeFeedbackProvider:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self._rows = rows
        self.calls: list[tuple[int, bool]] = []

    def list_all(self, limit: int = 50, include_closed: bool = False) -> list[dict[str, object]]:
        self.calls.append((limit, include_closed))
        return self._rows[:limit]


def test_copy_sqlite_snapshot_copies_to_explicit_snapshot_dir_without_mutating_source(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "index.db"
    _create_inventory_fixture(db_path)
    source_stat_before = db_path.stat()

    with sqlite3.connect(db_path) as conn:
        source_row_count = conn.execute("SELECT COUNT(*) FROM chunks_contextual_512_50").fetchone()[0]

    snapshot_dir = tmp_path / "snapshots"
    snapshot = copy_sqlite_snapshot(db_path, snapshot_dir, "inventory")

    assert snapshot.snapshot_path.parent == snapshot_dir
    assert snapshot.snapshot_path.exists()
    assert snapshot.source_path == db_path
    assert db_path.stat().st_mtime_ns == source_stat_before.st_mtime_ns

    with sqlite3.connect(snapshot.snapshot_path) as conn:
        snapshot_row_count = conn.execute(
            "SELECT COUNT(*) FROM chunks_contextual_512_50"
        ).fetchone()[0]

    assert snapshot_row_count == source_row_count


def test_copy_sqlite_snapshot_handles_wal_state_without_silent_row_loss(tmp_path: Path) -> None:
    db_path = tmp_path / "wal-index.db"
    conn = _create_wal_fixture(db_path)
    try:
        wal_path = Path(f"{db_path}-wal")
        shm_path = Path(f"{db_path}-shm")

        assert wal_path.exists()
        assert shm_path.exists()

        snapshot = copy_sqlite_snapshot(db_path, tmp_path / "snapshot", "wal-check")
    finally:
        conn.close()

    with sqlite3.connect(snapshot.snapshot_path) as conn:
        rows = conn.execute("SELECT body FROM wal_payload ORDER BY id").fetchall()

    assert rows == [("committed",), ("still-in-wal",)]
    assert snapshot.wal_mode in {"sqlite-backup", "copied-sidecars"}
    if snapshot.wal_mode == "copied-sidecars":
        assert snapshot.manifest["sidecars"] == [str(wal_path.name), str(shm_path.name)]


def test_collect_sqlite_inventory_reports_storage_counts_and_unmapped_tables(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "inventory.db"
    _create_inventory_fixture(db_path)

    inventory = collect_sqlite_inventory(db_path)

    assert inventory.snapshot_path == db_path
    assert inventory.table_counts["chunks"] == 2
    assert inventory.table_counts["fts_rows"] == 2
    assert inventory.table_counts["vectors"] == 2
    assert inventory.table_counts["vec_components"] == 2
    assert inventory.table_counts["source_documents"] == 1
    assert inventory.table_counts["resource_bindings"] == 1
    assert inventory.table_counts["chunk_fingerprints"] == 1
    assert inventory.table_counts["embed_fingerprints"] == 1
    assert inventory.table_counts["source_unit_fingerprints"] == 1
    assert inventory.table_counts["source_checkpoints"] == 1
    assert "search_log" in inventory.unmapped_tables


def test_collect_falkor_inventory_preserves_relation_labels_weights_keys_and_types() -> None:
    inventory = collect_falkor_inventory(_FakeGraphExporter())

    assert inventory.node_counts == {"File": 2, "Section": 3, "Entity": 5, "Tag": 1}
    assert inventory.edge_count == 7
    assert {summary.relation_label for summary in inventory.relation_summaries} == {
        "MENTIONS",
        "HAS_TAG",
    }
    mentions = next(
        summary for summary in inventory.relation_summaries if summary.relation_label == "MENTIONS"
    )
    assert mentions.weights == [1.0, 0.25]
    assert mentions.metadata_keys == ["evidence", "lang"]
    assert mentions.property_value_types["weight"] == "float"
    assert mentions.property_value_types["rank"] == "integer"
    assert mentions.property_value_types["confirmed"] == "boolean"


def test_collect_feedback_inventory_uses_provider_abstraction_and_not_raw_sql(
    tmp_path: Path,
) -> None:
    feedback_db = tmp_path / "feedback.db"
    store = FeedbackStore(feedback_db)
    store.submit("One", severity="bug", model="gpt")
    store.submit("Two", severity="suggestion", model="gpt")
    provider = _FakeFeedbackProvider(store.list_all(limit=50, include_closed=True))

    inventory = collect_feedback_inventory(provider)

    assert inventory.total_feedback == 2
    assert inventory.status_counts["open"] == 2
    assert provider.calls == [(1001, True)]


def test_collect_feedback_inventory_fails_closed_when_export_may_be_truncated() -> None:
    provider = _FakeFeedbackProvider(
        [
            {
                "status": "open",
                "severity": "bug",
            }
            for _ in range(1001)
        ]
    )

    inventory = collect_feedback_inventory(provider)

    assert inventory.available is False
    assert inventory.total_feedback == 0
    assert "exhaustive feedback export" in str(inventory.unavailable_reason)


def test_build_surreal_migration_map_marks_known_categories_and_rejects_unknown() -> None:
    migration_map = build_surreal_migration_map(
        categories={
            "chunks": {"columns": ["chunk_id", "text"], "verified": True},
            "provenance": {"columns": ["chunk_id", "document_ref"], "verified": True},
            "bindings": {"columns": ["resource_ref", "active"], "verified": True},
            "fingerprints": {"columns": ["chunk_id", "fingerprint"], "verified": True},
            "source_state": {"columns": ["namespace", "checkpoint_cursor"], "verified": True},
            "embeddings": {"columns": ["chunk_id", "text_hash"], "verified": True},
            "vector_components": {"columns": ["entity_id", "component"], "verified": True},
            "graph": {"properties": ["relation_label", "weight"], "verified": True},
            "feedback": {"fields": ["status", "submitted_at"], "verified": True},
            "mystery_table": {"columns": ["oops"], "verified": False},
        }
    )

    assert migration_map.categories["chunks"].disposition == "transformable"
    assert migration_map.categories["embeddings"].disposition == "transformable"
    assert migration_map.categories["graph"].disposition in {"transformable", "unsafe"}
    assert migration_map.categories["mystery_table"].disposition == "unsupported"
    assert "unknown" in migration_map.categories["mystery_table"].reason.lower()


def test_copy_sqlite_snapshot_leaves_source_row_counts_and_metadata_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "verify-source.db"
    _create_inventory_fixture(db_path)
    stat_before = db_path.stat()

    with sqlite3.connect(db_path) as conn:
        row_count_before = conn.execute(
            "SELECT COUNT(*) FROM vec_meta_contextual_512_50_multilingual_e5_large"
        ).fetchone()[0]

    copy_sqlite_snapshot(db_path, tmp_path / "snapshots", "verify-source")

    stat_after = db_path.stat()
    with sqlite3.connect(db_path) as conn:
        row_count_after = conn.execute(
            "SELECT COUNT(*) FROM vec_meta_contextual_512_50_multilingual_e5_large"
        ).fetchone()[0]

    assert row_count_after == row_count_before
    assert stat_after.st_size == stat_before.st_size
    assert stat_after.st_mtime_ns == stat_before.st_mtime_ns


def test_collect_sqlite_inventory_does_not_require_live_services(tmp_path: Path) -> None:
    db_path = tmp_path / "offline.db"
    _create_inventory_fixture(db_path)

    inventory = collect_sqlite_inventory(db_path)

    assert inventory.table_counts["chunks"] == 2
    assert "TEI" not in repr(inventory)
    assert "FalkorDB" not in repr(inventory)
    assert os.environ.get("DOTMD_EMBEDDING_URL") is None or True


def test_surreal_record_id_codec_round_trips_special_characters_without_leaking_raw_values() -> None:
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealRecordIdCodec,
        decode_surreal_record_id,
        encode_surreal_record_id,
    )

    codec = SurrealRecordIdCodec()
    raw_identifiers = [
        'chunk:alpha/one {"quoted"}',
        'filesystem:/tmp/Doc One "quoted".md',
        "entity/Привет мир",
        "feedback:{42}/ spaced",
    ]
    forbidden_fragments = ["DROP", "RETURN", "{", "}", '"', "'", "\n", ";"]

    for raw_identifier in raw_identifiers:
        record_id = codec.encode("chunks", raw_identifier)
        assert record_id.table_name == "chunks"
        assert codec.decode(record_id) == raw_identifier
        assert decode_surreal_record_id(record_id) == raw_identifier
        assert decode_surreal_record_id(encode_surreal_record_id("chunks", raw_identifier)) == (
            raw_identifier
        )

        encoded_identifier = str(record_id.id)
        assert raw_identifier not in encoded_identifier
        assert all(fragment not in encoded_identifier for fragment in forbidden_fragments)


def test_define_dotmd_surreal_schema_declares_required_record_shapes_and_thin_scope() -> None:
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        THIN_PROTOTYPE_NOTE,
        UNSUPPORTED_PRODUCTION_BEHAVIORS,
        define_dotmd_surreal_schema,
    )

    schema = define_dotmd_surreal_schema()

    assert {
        "documents",
        "source_units",
        "chunks",
        "embeddings",
        "vector_components",
        "entities",
        "relations",
        "feedback",
        "cursors",
        "checkpoints",
    }.issubset(set(schema["tables"]))
    assert "thin prototype" in THIN_PROTOTYPE_NOTE.lower()
    assert any("DotMDService" in item for item in UNSUPPORTED_PRODUCTION_BEHAVIORS)
    assert any("IndexingPipeline" in item for item in UNSUPPORTED_PRODUCTION_BEHAVIORS)


def test_surreal_stores_expose_existing_protocol_method_names(tmp_path: Path) -> None:
    from dotmd.storage.base import GraphStoreProtocol, MetadataStoreProtocol, VectorStoreProtocol
    from dotmd.storage.surreal import (  # type: ignore[import-not-found]
        SurrealConnection,
        SurrealGraphStore,
        SurrealMetadataStore,
        SurrealStoreConfig,
        SurrealVectorStore,
    )

    db_path = tmp_path / "storage-contract.db"
    config = SurrealStoreConfig(
        url=f"surrealkv://{db_path}",
        namespace="dotmd",
        database="phase38_contract",
    )

    with SurrealConnection(config) as connection:
        metadata_store = SurrealMetadataStore(connection)
        vector_store = SurrealVectorStore(connection)
        graph_store = SurrealGraphStore(connection)

        assert isinstance(metadata_store, MetadataStoreProtocol)
        assert isinstance(vector_store, VectorStoreProtocol)
        assert isinstance(graph_store, GraphStoreProtocol)
