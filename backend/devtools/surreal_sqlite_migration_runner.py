"""Migrate dotMD SQLite vector/index data into standalone SurrealDB."""

from __future__ import annotations

import argparse
import json
import sqlite3
import struct
import sys
import time
from collections.abc import Callable, Iterator
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from devtools.surreal_sqlite_source_probe import build_source_tables
from devtools.surreal_standalone_migration_proof import (
    _target_and_data,
    batch_upsert,
    format_eta,
)
from dotmd.storage.surreal import SurrealConnection, SurrealRecordIdCodec, SurrealStoreConfig


@dataclass(frozen=True, slots=True)
class SQLiteMigrationConfig:
    sqlite_path: Path
    chunk_strategy: str
    embedding_model: str
    batch_chunks: int
    checkpoint: Path
    limit_chunks: int | None = None
    heartbeat_seconds: int = 30


@dataclass(slots=True)
class MigrationCheckpoint:
    chunk_strategy: str
    embedding_model: str
    last_vector_rowid: int = 0
    chunks_done: int = 0
    records_done: int = 0
    counts: dict[str, int] = field(default_factory=dict)
    started_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    complete: bool = False

    @classmethod
    def load_or_new(cls, path: Path, config: SQLiteMigrationConfig) -> MigrationCheckpoint:
        if not path.exists():
            return cls(
                chunk_strategy=config.chunk_strategy,
                embedding_model=config.embedding_model,
            )
        data = json.loads(path.read_text(encoding="utf-8"))
        checkpoint = cls(
            chunk_strategy=data["chunk_strategy"],
            embedding_model=data["embedding_model"],
            last_vector_rowid=int(data.get("last_vector_rowid", 0)),
            chunks_done=int(data.get("chunks_done", 0)),
            records_done=int(data.get("records_done", 0)),
            counts={str(k): int(v) for k, v in data.get("counts", {}).items()},
            started_at=str(data.get("started_at") or datetime.now(UTC).isoformat()),
            updated_at=str(data.get("updated_at") or datetime.now(UTC).isoformat()),
            complete=bool(data.get("complete", False)),
        )
        if checkpoint.chunk_strategy != config.chunk_strategy:
            raise ValueError("checkpoint chunk_strategy does not match CLI args")
        if checkpoint.embedding_model != config.embedding_model:
            raise ValueError("checkpoint embedding_model does not match CLI args")
        return checkpoint

    def save(self, path: Path) -> None:
        self.updated_at = datetime.now(UTC).isoformat()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_suffix(f"{path.suffix}.tmp")
        tmp_path.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp_path.replace(path)


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


def _total_chunks(conn: sqlite3.Connection, config: SQLiteMigrationConfig) -> int:
    tables = build_source_tables(config.chunk_strategy, config.embedding_model)
    total = int(
        conn.execute(
            f"""
            SELECT count(*)
            FROM {tables.vec_meta} m
            JOIN {tables.chunks} c ON c.chunk_id = m.chunk_id
            JOIN {tables.vec_chunks} v ON v.rowid = m.rowid
            """
        ).fetchone()[0]
    )
    if config.limit_chunks is None:
        return total
    return min(total, config.limit_chunks)


def _load_batch(
    conn: sqlite3.Connection,
    config: SQLiteMigrationConfig,
    *,
    after_rowid: int,
    remaining_chunks: int,
) -> list[sqlite3.Row]:
    tables = build_source_tables(config.chunk_strategy, config.embedding_model)
    limit = min(config.batch_chunks, remaining_chunks)
    return conn.execute(
        f"""
        SELECT c.chunk_id, c.heading_hierarchy, c.level, c.text,
               m.rowid AS vector_rowid, m.text_hash, v.embedding
        FROM {tables.vec_meta} m
        JOIN {tables.chunks} c ON c.chunk_id = m.chunk_id
        JOIN {tables.vec_chunks} v ON v.rowid = m.rowid
        WHERE m.rowid > ?
        ORDER BY m.rowid
        LIMIT ?
        """,
        (after_rowid, limit),
    ).fetchall()


def _document_record(row: sqlite3.Row) -> dict[str, Any]:
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


def _records_for_batch(
    conn: sqlite3.Connection,
    config: SQLiteMigrationConfig,
    chunk_rows: list[sqlite3.Row],
) -> Iterator[dict[str, Any]]:
    tables = build_source_tables(config.chunk_strategy, config.embedding_model)
    document_refs: set[tuple[str, str]] = set()
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
                "metadata": {"sqlite_vector_rowid": int(chunk["vector_rowid"])},
            },
        }


def _emit(printer: Callable[..., None], message: str) -> None:
    printer(message, flush=True)


def run_sqlite_migration(
    store_config: SurrealStoreConfig,
    migration_config: SQLiteMigrationConfig,
    *,
    connection_factory: Callable[[SurrealStoreConfig], SurrealConnection] = SurrealConnection,
    printer: Callable[..., None] = print,
    clock: Callable[[], float] = time.monotonic,
) -> MigrationCheckpoint:
    started = clock()
    checkpoint = MigrationCheckpoint.load_or_new(migration_config.checkpoint, migration_config)
    codec = SurrealRecordIdCodec()
    with _connect(migration_config.sqlite_path) as sqlite_conn:
        total_chunks = _total_chunks(sqlite_conn, migration_config)
        if checkpoint.chunks_done >= total_chunks:
            if not checkpoint.complete:
                checkpoint.complete = True
                checkpoint.save(migration_config.checkpoint)
            _emit(printer, "surreal sqlite migration: checkpoint already complete")
            return checkpoint
        _emit(
            printer,
            (
                "surreal sqlite migration: starting "
                f"sqlite={migration_config.sqlite_path} chunks={checkpoint.chunks_done}/{total_chunks} "
                f"last_rowid={checkpoint.last_vector_rowid} batch_chunks={migration_config.batch_chunks} "
                f"url={store_config.url} namespace={store_config.namespace} database={store_config.database}"
            ),
        )
        surreal = connection_factory(store_config)
        try:
            last_heartbeat = started
            while checkpoint.chunks_done < total_chunks:
                remaining = total_chunks - checkpoint.chunks_done
                batch_started = clock()
                chunk_rows = _load_batch(
                    sqlite_conn,
                    migration_config,
                    after_rowid=checkpoint.last_vector_rowid,
                    remaining_chunks=remaining,
                )
                if not chunk_rows:
                    break
                rows: list[dict[str, Any]] = []
                batch_counts: dict[str, int] = {}
                for record in _records_for_batch(sqlite_conn, migration_config, chunk_rows):
                    target, data = _target_and_data(record, codec)
                    rows.append({"id": target, "data": data})
                    record_type = str(record["type"])
                    batch_counts[record_type] = batch_counts.get(record_type, 0) + 1
                batch_upsert(surreal, rows)
                checkpoint.last_vector_rowid = int(chunk_rows[-1]["vector_rowid"])
                checkpoint.chunks_done += len(chunk_rows)
                checkpoint.records_done += len(rows)
                for key, value in batch_counts.items():
                    checkpoint.counts[key] = checkpoint.counts.get(key, 0) + value
                checkpoint.complete = checkpoint.chunks_done >= total_chunks
                checkpoint.save(migration_config.checkpoint)

                now = clock()
                if (
                    now - last_heartbeat >= migration_config.heartbeat_seconds
                    or checkpoint.complete
                ):
                    elapsed = max(now - started, 0.001)
                    rate = checkpoint.chunks_done / elapsed
                    remaining_seconds = (total_chunks - checkpoint.chunks_done) / rate if rate else 0
                    percent = checkpoint.chunks_done / total_chunks * 100 if total_chunks else 100
                    _emit(
                        printer,
                        (
                            "surreal sqlite migration: "
                            f"chunks={checkpoint.chunks_done}/{total_chunks} ({percent:.1f}%) "
                            f"records={checkpoint.records_done} "
                            f"last_rowid={checkpoint.last_vector_rowid} "
                            f"batch={len(chunk_rows)} chunks/{len(rows)} records "
                            f"batch_elapsed={now - batch_started:.3f}s "
                            f"rate={rate:.1f} chunks/s ETA {format_eta(remaining_seconds)}"
                        ),
                    )
                    last_heartbeat = now
        finally:
            surreal.close()
    return checkpoint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sqlite", type=Path, required=True)
    parser.add_argument("--chunk-strategy", default="contextual_512_50")
    parser.add_argument("--embedding-model", default="intfloat/multilingual-e5-large")
    parser.add_argument("--batch-chunks", type=int, default=250)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--limit-chunks", type=int)
    parser.add_argument("--heartbeat-seconds", type=int, default=30)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        checkpoint = run_sqlite_migration(
            SurrealStoreConfig.from_env(),
            SQLiteMigrationConfig(
                sqlite_path=args.sqlite,
                chunk_strategy=args.chunk_strategy,
                embedding_model=args.embedding_model,
                batch_chunks=args.batch_chunks,
                checkpoint=args.checkpoint,
                limit_chunks=args.limit_chunks,
                heartbeat_seconds=args.heartbeat_seconds,
            ),
        )
    except Exception as exc:
        print(f"surreal sqlite migration failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        "surreal sqlite migration ok: "
        f"chunks={checkpoint.chunks_done} records={checkpoint.records_done} "
        f"last_rowid={checkpoint.last_vector_rowid} complete={checkpoint.complete} "
        f"counts={json.dumps(checkpoint.counts, sort_keys=True)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
