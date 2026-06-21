from __future__ import annotations

import json
import sqlite3
import struct
from pathlib import Path

from dotmd.ingestion.surreal_sqlite_snapshot import (
    iter_sqlite_embedding_rows_for_surreal,
    load_sqlite_rows_for_surreal,
)


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


def test_snapshot_loaders_read_transform_only_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshot.db"
    fixture_ids = _create_transform_only_fixture(db_path)

    sqlite_rows = load_sqlite_rows_for_surreal(db_path)

    assert sqlite_rows["documents"][0]["document_ref"] == fixture_ids["file_path"]
    assert sqlite_rows["chunks"][0]["chunk_id"] == fixture_ids["chunk_id"]
    assert sqlite_rows["embeddings"][0]["chunk_id"] == fixture_ids["chunk_id"]
    assert sqlite_rows["embeddings"][0]["vector"] == [
        0.10999999940395355,
        0.2199999988079071,
        0.33000001311302185,
    ]
    assert len(sqlite_rows["vector_components"]) == 2
    assert sqlite_rows["expected_vector_dimension"] == 3
    assert sqlite_rows["embedding_model"] == "multilingual-e5-large"
    assert sqlite_rows["internal_tables"] == ["sqlite_sequence"]


def test_iter_sqlite_embedding_rows_for_surreal_yields_expected_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "snapshot.db"
    fixture_ids = _create_transform_only_fixture(db_path)

    rows = list(iter_sqlite_embedding_rows_for_surreal(db_path, batch_size=1))

    assert [row["chunk_id"] for row in rows] == [fixture_ids["chunk_id"], "chunk:plain"]
    assert [row["vector_rowid"] for row in rows] == [1, 2]
    assert rows[0]["text_hash"] == "hash-alpha"
    assert rows[1]["embedding_model"] == "multilingual-e5-large"
    assert all(row["metadata"] == {} for row in rows)
    json.dumps(rows)
