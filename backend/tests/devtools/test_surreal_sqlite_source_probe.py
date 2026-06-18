from __future__ import annotations

import sqlite3

import pytest
from devtools.surreal_sqlite_source_probe import (
    build_source_tables,
    model_to_table_suffix,
    probe_sqlite_source,
)

pytestmark = pytest.mark.real_schema_check


def test_model_to_table_suffix_matches_runtime_convention() -> None:
    assert model_to_table_suffix("intfloat/multilingual-e5-large") == "_multilingual_e5_large"
    assert model_to_table_suffix("Qwen/Qwen3-Embedding-0.6B") == "_qwen3_embedding"
    assert model_to_table_suffix("BAAI/bge-small-en-v1.5") == "_bge_small_en_v1_5"


def test_probe_sqlite_source_reads_counts_config_and_sample(tmp_path) -> None:
    db_path = tmp_path / "index.db"
    tables = build_source_tables("contextual_512_50", "intfloat/multilingual-e5-large")
    conn = sqlite3.connect(db_path)
    conn.execute(
        f"CREATE TABLE {tables.chunks} (chunk_id TEXT PRIMARY KEY, heading_hierarchy TEXT, level INTEGER, text TEXT)"
    )
    conn.execute(
        f"CREATE TABLE {tables.chunk_file_paths} (chunk_id TEXT, file_path TEXT, chunk_index INTEGER)"
    )
    conn.execute(f"CREATE TABLE {tables.vec_meta} (rowid INTEGER PRIMARY KEY, chunk_id TEXT, text_hash TEXT)")
    conn.execute(f"CREATE TABLE {tables.vec_config} (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE source_documents (id TEXT)")
    conn.execute(
        f"INSERT INTO {tables.chunks} VALUES (?, ?, ?, ?)",
        ("chunk-1", '["Title"]', 1, "hello"),
    )
    conn.execute(
        f"INSERT INTO {tables.chunk_file_paths} VALUES (?, ?, ?)",
        ("chunk-1", "/mnt/doc.md", 0),
    )
    conn.execute(f"INSERT INTO {tables.vec_meta} VALUES (?, ?, ?)", (1, "chunk-1", "hash"))
    conn.execute(f"INSERT INTO {tables.vec_config} VALUES (?, ?)", ("dim", "1024"))
    conn.commit()
    conn.close()

    result = probe_sqlite_source(
        db_path,
        chunk_strategy="contextual_512_50",
        embedding_model="intfloat/multilingual-e5-large",
    )

    assert result.table_exists["chunks"] is True
    assert result.table_exists["vec_chunks"] is False
    assert result.counts["chunks"] == 1
    assert result.counts["vec_meta"] == 1
    assert result.vec_config["dim"] == "1024"
    assert result.sample_chunk is not None
    assert result.sample_chunk["file_path"] == "/mnt/doc.md"
    assert result.sample_payload_json_bytes is not None
    assert result.sample_payload_json_bytes > 0
