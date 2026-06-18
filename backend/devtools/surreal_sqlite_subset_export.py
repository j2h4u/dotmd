"""Export a small SQLite subset for standalone SurrealDB migration proof."""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from devtools.surreal_sqlite_source_probe import build_source_tables


@dataclass(frozen=True, slots=True)
class ExportConfig:
    sqlite_path: Path
    chunk_strategy: str
    embedding_model: str
    limit: int
    output: Path


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        import sqlite_vec  # type: ignore[import-untyped]

        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
    except Exception:
        conn.enable_load_extension(False)
    return conn


def _json_loads(value: str | None, default: object) -> object:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default


def _decode_f32_blob(blob: bytes) -> list[float]:
    if len(blob) % 4 != 0:
        raise ValueError(f"embedding blob length must be divisible by 4, got {len(blob)}")
    return list(struct.unpack(f"{len(blob) // 4}f", blob))


def _document_record(row: sqlite3.Row) -> dict[str, object]:
    return {
        "type": "document",
        "data": {
            "schema_version": 1,
            "namespace": row["namespace"],
            "document_ref": row["document_ref"],
            "ref": row["ref"],
            "source_uri": row["source_uri"],
            "file_path": row["file_path"],
            "media_type": row["media_type"],
            "parser_name": row["parser_name"],
            "document_type": row["document_type"],
            "title": row["title"],
            "updated_at": row["updated_at"],
            "content_fingerprint": row["content_fingerprint"],
            "metadata_fingerprint": row["metadata_fingerprint"],
            "metadata": _json_loads(row["metadata_json"], {}),
        },
    }


def _iter_records(conn: sqlite3.Connection, config: ExportConfig) -> Iterator[dict[str, object]]:
    tables = build_source_tables(config.chunk_strategy, config.embedding_model)
    chunk_rows = conn.execute(
        f"""
        SELECT c.chunk_id, c.heading_hierarchy, c.level, c.text,
               m.rowid AS vector_rowid, m.text_hash, v.embedding
        FROM {tables.vec_meta} m
        JOIN {tables.chunks} c ON c.chunk_id = m.chunk_id
        JOIN {tables.vec_chunks} v ON v.rowid = m.rowid
        ORDER BY m.rowid
        LIMIT ?
        """,
        (config.limit,),
    ).fetchall()

    document_refs: set[tuple[str, str]] = set()
    source_unit_refs: set[tuple[str, str, str]] = set()
    provenance_by_chunk: dict[str, list[sqlite3.Row]] = {}
    bindings_by_chunk: dict[str, list[sqlite3.Row]] = {}
    for chunk in chunk_rows:
        chunk_id = str(chunk["chunk_id"])
        provenance_rows = conn.execute(
            f"""
            SELECT chunk_id, namespace, document_ref, source_unit_refs,
                   chunk_strategy, parser_name
            FROM {tables.chunk_source_provenance}
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchall()
        provenance_by_chunk[chunk_id] = provenance_rows
        for row in provenance_rows:
            document_refs.add((str(row["namespace"]), str(row["document_ref"])))
            for unit_ref in _json_loads(row["source_unit_refs"], []):
                if isinstance(unit_ref, str):
                    source_unit_refs.add(
                        (str(row["namespace"]), str(row["document_ref"]), unit_ref)
                    )
        bindings_by_chunk[chunk_id] = conn.execute(
            f"""
            SELECT chunk_id, file_path, chunk_index
            FROM {tables.chunk_file_paths}
            WHERE chunk_id = ?
            """,
            (chunk_id,),
        ).fetchall()

    for namespace, document_ref in sorted(document_refs):
        row = conn.execute(
            """
            SELECT namespace, document_ref, ref, source_uri, file_path, media_type,
                   parser_name, document_type, title, updated_at, content_fingerprint,
                   metadata_fingerprint, metadata_json
            FROM source_documents
            WHERE namespace = ? AND document_ref = ?
            """,
            (namespace, document_ref),
        ).fetchone()
        if row is not None:
            yield _document_record(row)

    for namespace, document_ref, unit_ref in sorted(source_unit_refs):
        row = conn.execute(
            """
            SELECT namespace, document_ref, unit_ref, fingerprint, updated_at,
                   indexed_at, metadata_json
            FROM source_unit_fingerprints
            WHERE namespace = ? AND document_ref = ? AND unit_ref = ?
            """,
            (namespace, document_ref, unit_ref),
        ).fetchone()
        if row is None:
            continue
        metadata = _json_loads(row["metadata_json"], {})
        yield {
            "type": "source_unit",
            "data": {
                "namespace": row["namespace"],
                "document_ref": row["document_ref"],
                "unit_ref": row["unit_ref"],
                "unit_type": None,
                "text": None,
                "order_key": None,
                "fingerprint": row["fingerprint"],
                "updated_at": row["updated_at"],
                "metadata": metadata,
                "chunking_hints": {},
            },
        }
        yield {
            "type": "source_unit_fingerprint",
            "data": {
                "namespace": row["namespace"],
                "document_ref": row["document_ref"],
                "unit_ref": row["unit_ref"],
                "fingerprint": row["fingerprint"],
                "updated_at": row["updated_at"],
                "indexed_at": row["indexed_at"],
                "metadata": metadata,
            },
        }

    for chunk in chunk_rows:
        chunk_id = str(chunk["chunk_id"])
        first_provenance = provenance_by_chunk[chunk_id][0] if provenance_by_chunk[chunk_id] else None
        first_binding = bindings_by_chunk[chunk_id][0] if bindings_by_chunk[chunk_id] else None
        document_ref = str(first_provenance["document_ref"]) if first_provenance else None
        namespace = str(first_provenance["namespace"]) if first_provenance else None
        yield {
            "type": "chunk",
            "data": {
                "schema_version": 1,
                "chunk_id": chunk_id,
                "original_chunk_id": chunk_id,
                "chunk_strategy": config.chunk_strategy,
                "document_ref": document_ref,
                "heading_hierarchy": _json_loads(chunk["heading_hierarchy"], []),
                "level": int(chunk["level"] or 0),
                "chunk_index": int(first_binding["chunk_index"]) if first_binding else 0,
                "title": None,
                "text": chunk["text"],
                "metadata": {"namespace": namespace} if namespace else {},
            },
        }
        for binding in bindings_by_chunk[chunk_id]:
            yield {
                "type": "chunk_file_binding",
                "data": {
                    "chunk_id": chunk_id,
                    "chunk_strategy": config.chunk_strategy,
                    "file_path": binding["file_path"],
                    "chunk_index": int(binding["chunk_index"]),
                },
            }
        for provenance in provenance_by_chunk[chunk_id]:
            yield {
                "type": "chunk_source_provenance",
                "data": {
                    "chunk_id": chunk_id,
                    "namespace": provenance["namespace"],
                    "document_ref": provenance["document_ref"],
                    "source_unit_refs": _json_loads(provenance["source_unit_refs"], []),
                    "chunk_strategy": provenance["chunk_strategy"],
                    "parser_name": provenance["parser_name"],
                },
            }
        yield {
            "type": "embedding",
            "data": {
                "schema_version": 1,
                "chunk_id": chunk_id,
                "chunk_strategy": config.chunk_strategy,
                "embedding_model": config.embedding_model,
                "text_hash": chunk["text_hash"],
                "vector": _decode_f32_blob(chunk["embedding"]),
                "metadata": {
                    "sqlite_vector_rowid": int(chunk["vector_rowid"]),
                },
            },
        }


def export_subset(config: ExportConfig) -> dict[str, object]:
    started = time.monotonic()
    counts: dict[str, int] = {}
    with _connect(config.sqlite_path) as conn, config.output.open("w", encoding="utf-8") as fh:
        for record in _iter_records(conn, config):
            record_type = str(record["type"])
            counts[record_type] = counts.get(record_type, 0) + 1
            fh.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            fh.write("\n")
    return {
        "output": str(config.output),
        "chunk_strategy": config.chunk_strategy,
        "embedding_model": config.embedding_model,
        "limit": config.limit,
        "counts": counts,
        "elapsed_seconds": round(time.monotonic() - started, 3),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--chunk-strategy", default="contextual_512_50")
    parser.add_argument("--embedding-model", default="intfloat/multilingual-e5-large")
    parser.add_argument("--limit", type=int, default=100)
    parser.add_argument("--output", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = export_subset(
            ExportConfig(
                sqlite_path=args.sqlite,
                chunk_strategy=args.chunk_strategy,
                embedding_model=args.embedding_model,
                limit=args.limit,
                output=args.output,
            )
        )
    except Exception as exc:
        print(f"surreal sqlite subset export failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
