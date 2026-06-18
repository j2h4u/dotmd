from __future__ import annotations

import json
import sqlite3
import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest
from devtools.surreal_sqlite_migration_runner import (
    SQLiteMigrationConfig,
    run_sqlite_migration,
)

from dotmd.storage.surreal import SurrealStoreConfig

pytestmark = pytest.mark.real_schema_check


def _write_fixture_db(path: Path) -> None:
    conn = sqlite3.connect(path)
    conn.executescript(
        """
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
        CREATE TABLE chunks_contextual_512_50 (
            chunk_id TEXT PRIMARY KEY,
            heading_hierarchy TEXT NOT NULL DEFAULT '[]',
            level INTEGER NOT NULL DEFAULT 0,
            text TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE chunk_file_paths_contextual_512_50 (
            chunk_id TEXT NOT NULL,
            file_path TEXT NOT NULL,
            chunk_index INTEGER NOT NULL,
            PRIMARY KEY (chunk_id, file_path, chunk_index)
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
        CREATE TABLE vec_meta_contextual_512_50_multilingual_e5_large (
            rowid INTEGER PRIMARY KEY AUTOINCREMENT,
            chunk_id TEXT NOT NULL UNIQUE,
            text_hash TEXT
        );
        CREATE TABLE vec_chunks_contextual_512_50_multilingual_e5_large (
            rowid INTEGER PRIMARY KEY,
            embedding BLOB NOT NULL
        );
        """
    )
    conn.execute(
        """
        INSERT INTO source_documents (
            namespace, document_ref, ref, source_uri, file_path, media_type,
            parser_name, document_type, title, updated_at, content_fingerprint,
            metadata_fingerprint, metadata_json
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "filesystem",
            "/mnt/doc.md",
            "filesystem:/mnt/doc.md",
            "file:///mnt/doc.md",
            "/mnt/doc.md",
            "text/markdown",
            "markdown",
            "document",
            "Doc",
            "2026-06-18T00:00:00Z",
            "content",
            "metadata",
            json.dumps({"date": "2026-06-18"}),
        ),
    )
    for index in range(1, 4):
        chunk_id = f"chunk-{index}"
        conn.execute(
            "INSERT INTO chunks_contextual_512_50 VALUES (?, ?, ?, ?)",
            (chunk_id, "[]", 0, f"text {index}"),
        )
        conn.execute(
            "INSERT INTO chunk_file_paths_contextual_512_50 VALUES (?, ?, ?)",
            (chunk_id, "/mnt/doc.md", index - 1),
        )
        conn.execute(
            "INSERT INTO chunk_source_provenance_contextual_512_50 VALUES (?, ?, ?, ?, ?, ?)",
            (chunk_id, "filesystem", "/mnt/doc.md", "[]", "contextual_512_50", "markdown"),
        )
        conn.execute(
            "INSERT INTO vec_meta_contextual_512_50_multilingual_e5_large (chunk_id, text_hash)"
            " VALUES (?, ?)",
            (chunk_id, f"hash-{index}"),
        )
        conn.execute(
            "INSERT INTO vec_chunks_contextual_512_50_multilingual_e5_large VALUES (?, ?)",
            (index, struct.pack("4f", 1.0, 2.0, 3.0, 4.0)),
        )
    conn.commit()
    conn.close()


@dataclass
class FakeSurrealConnection:
    config: SurrealStoreConfig
    batches: list[list[dict[str, Any]]] = field(default_factory=list)
    closed: bool = False

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> None:
        assert statement.startswith("FOR $row IN $rows")
        assert variables is not None
        self.batches.append(variables["rows"])

    def close(self) -> None:
        self.closed = True


def test_sqlite_migration_batches_and_writes_checkpoint(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "index.db"
    checkpoint_path = tmp_path / "checkpoint.json"
    _write_fixture_db(sqlite_path)
    holder: dict[str, FakeSurrealConnection] = {}

    def factory(config: SurrealStoreConfig) -> FakeSurrealConnection:
        connection = FakeSurrealConnection(config)
        holder["connection"] = connection
        return connection

    checkpoint = run_sqlite_migration(
        SurrealStoreConfig(),
        SQLiteMigrationConfig(
            sqlite_path=sqlite_path,
            chunk_strategy="contextual_512_50",
            embedding_model="intfloat/multilingual-e5-large",
            batch_chunks=2,
            checkpoint=checkpoint_path,
            limit_chunks=3,
            heartbeat_seconds=0,
        ),
        connection_factory=factory,
    )

    assert checkpoint.complete is True
    assert checkpoint.chunks_done == 3
    assert checkpoint.records_done == 14
    assert checkpoint.counts == {
        "document": 2,
        "chunk": 3,
        "chunk_file_binding": 3,
        "chunk_source_provenance": 3,
        "embedding": 3,
    }
    assert len(holder["connection"].batches) == 2
    assert holder["connection"].closed is True
    saved = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    assert saved["last_vector_rowid"] == 3
    assert saved["complete"] is True


def test_sqlite_migration_respects_complete_checkpoint(tmp_path: Path) -> None:
    sqlite_path = tmp_path / "index.db"
    checkpoint_path = tmp_path / "checkpoint.json"
    _write_fixture_db(sqlite_path)
    checkpoint_path.write_text(
        json.dumps(
            {
                "chunk_strategy": "contextual_512_50",
                "embedding_model": "intfloat/multilingual-e5-large",
                "last_vector_rowid": 3,
                "chunks_done": 3,
                "records_done": 14,
                "counts": {},
                "started_at": "2026-06-18T00:00:00+00:00",
                "updated_at": "2026-06-18T00:00:00+00:00",
                "complete": True,
            }
        ),
        encoding="utf-8",
    )

    def factory(config: SurrealStoreConfig) -> FakeSurrealConnection:
        raise AssertionError("complete checkpoint should not connect to SurrealDB")

    checkpoint = run_sqlite_migration(
        SurrealStoreConfig(),
        SQLiteMigrationConfig(
            sqlite_path=sqlite_path,
            chunk_strategy="contextual_512_50",
            embedding_model="intfloat/multilingual-e5-large",
            batch_chunks=2,
            checkpoint=checkpoint_path,
            limit_chunks=3,
        ),
        connection_factory=factory,
    )

    assert checkpoint.complete is True
    assert checkpoint.chunks_done == 3
