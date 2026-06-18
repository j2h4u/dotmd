"""Probe a dotMD SQLite index before standalone SurrealDB migration."""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


def model_to_table_suffix(model_name: str) -> str:
    if not model_name:
        return "_default"
    name = model_name.rsplit("/", 1)[-1]
    name = re.sub(r"-[\d.]+[BbMm]?$", "", name)
    name = re.sub(r"[^a-zA-Z0-9]+", "_", name).strip("_").lower()
    return f"_{name}" if name else "_default"


@dataclass(slots=True, frozen=True)
class SourceTables:
    chunks: str
    chunk_file_paths: str
    chunk_source_provenance: str
    vec_meta: str
    vec_chunks: str
    vec_config: str


@dataclass(slots=True, frozen=True)
class SQLiteSourceProbe:
    sqlite_path: str
    chunk_strategy: str
    embedding_model: str
    tables: SourceTables
    table_exists: dict[str, bool]
    counts: dict[str, int]
    vec_config: dict[str, str]
    sample_chunk: dict[str, Any] | None
    sample_payload_json_bytes: int | None
    elapsed_seconds: float


def build_source_tables(chunk_strategy: str, embedding_model: str) -> SourceTables:
    model_suffix = model_to_table_suffix(embedding_model)
    return SourceTables(
        chunks=f"chunks_{chunk_strategy}",
        chunk_file_paths=f"chunk_file_paths_{chunk_strategy}",
        chunk_source_provenance=f"chunk_source_provenance_{chunk_strategy}",
        vec_meta=f"vec_meta_{chunk_strategy}{model_suffix}",
        vec_chunks=f"vec_chunks_{chunk_strategy}{model_suffix}",
        vec_config=f"vec_config_{chunk_strategy}{model_suffix}",
    )


def _connect_readonly(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        import sqlite_vec  # type: ignore[import-untyped]

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        conn.enable_load_extension(False)
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def _count(conn: sqlite3.Connection, table_name: str, *, exists: bool) -> int:
    if not exists:
        return 0
    return int(conn.execute(f"SELECT count(*) FROM {table_name}").fetchone()[0])


def _load_vec_config(conn: sqlite3.Connection, table_name: str, *, exists: bool) -> dict[str, str]:
    if not exists:
        return {}
    return {
        str(key): str(value)
        for key, value in conn.execute(f"SELECT key, value FROM {table_name} ORDER BY key")
    }


def _sample_chunk(
    conn: sqlite3.Connection,
    tables: SourceTables,
    table_exists: dict[str, bool],
) -> dict[str, Any] | None:
    if not table_exists["chunks"]:
        return None
    row = conn.execute(
        f"""
        SELECT c.chunk_id, c.heading_hierarchy, c.level, c.text,
               m.text_hash, p.file_path, p.chunk_index
        FROM {tables.chunks} c
        LEFT JOIN {tables.vec_meta} m ON m.chunk_id = c.chunk_id
        LEFT JOIN {tables.chunk_file_paths} p ON p.chunk_id = c.chunk_id
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    chunk_id, heading_hierarchy, level, text, text_hash, file_path, chunk_index = row
    return {
        "chunk_id": chunk_id,
        "heading_hierarchy": json.loads(heading_hierarchy or "[]"),
        "level": level,
        "text_chars": len(text or ""),
        "text_hash": text_hash,
        "file_path": file_path,
        "chunk_index": chunk_index,
    }


def probe_sqlite_source(
    sqlite_path: Path,
    *,
    chunk_strategy: str,
    embedding_model: str,
) -> SQLiteSourceProbe:
    started = time.monotonic()
    tables = build_source_tables(chunk_strategy, embedding_model)
    with _connect_readonly(sqlite_path) as conn:
        table_names = asdict(tables)
        exists = {logical: _table_exists(conn, name) for logical, name in table_names.items()}
        counts = {
            logical: _count(conn, table_names[logical], exists=table_exists)
            for logical, table_exists in exists.items()
        }
        config = _load_vec_config(conn, tables.vec_config, exists=exists["vec_config"])
        sample = _sample_chunk(conn, tables, exists)
    sample_payload_json_bytes = None
    if sample is not None:
        sample_payload_json_bytes = len(json.dumps(sample, ensure_ascii=False).encode("utf-8"))
    return SQLiteSourceProbe(
        sqlite_path=str(sqlite_path),
        chunk_strategy=chunk_strategy,
        embedding_model=embedding_model,
        tables=tables,
        table_exists=exists,
        counts=counts,
        vec_config=config,
        sample_chunk=sample,
        sample_payload_json_bytes=sample_payload_json_bytes,
        elapsed_seconds=round(time.monotonic() - started, 3),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--chunk-strategy", default="contextual_512_50")
    parser.add_argument("--embedding-model", default="intfloat/multilingual-e5-large")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = probe_sqlite_source(
            args.sqlite,
            chunk_strategy=args.chunk_strategy,
            embedding_model=args.embedding_model,
        )
    except Exception as exc:
        print(f"surreal sqlite source probe failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(asdict(result), ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
