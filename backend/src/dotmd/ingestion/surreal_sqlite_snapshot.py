"""Read-only helpers for SQLite snapshot rows used by current Surreal admin tools."""

from __future__ import annotations

import json
import re
import sqlite3
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from dotmd.core.config import Settings
from dotmd.ingestion.pipeline import _model_to_table_suffix
from dotmd.storage.surreal_schema import SURREAL_SCHEMA_VERSION

_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SQLITE_INTERNAL_PREFIXES = ("sqlite_",)
_STABLE_UNSUPPORTED_CATEGORIES = [
    "stats",
    "search_log",
    "embedding_cache",
    "extraction_cache",
    "sqlite_internal",
]


@dataclass(slots=True, frozen=True)
class _SqliteVectorDataset:
    chunk_strategy: str
    model_key: str
    embedding_model: str
    vector_dimension: int | None
    meta_table: str
    vec_table: str
    config_table: str
    component_table: str | None
    embed_fingerprint_table: str | None
    meta_fingerprint_table: str | None


def _sqlite_connect_read_only(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.enable_load_extension(True)
    try:
        import sqlite_vec  # type: ignore[import-untyped]

        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)
    return conn


def _discover_tables(conn: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        ).fetchall()
    }


def _validate_table_name(table_name: str, known_tables: set[str]) -> str:
    if not _SAFE_TABLE_NAME.match(table_name):
        raise ValueError(f"unsafe table name: {table_name!r}")
    if table_name not in known_tables:
        raise ValueError(f"unknown table name: {table_name!r}")
    return table_name


def _fetch_all(
    conn: sqlite3.Connection, table_name: str, known_tables: set[str]
) -> list[sqlite3.Row]:
    safe_name = _validate_table_name(table_name, known_tables)
    conn.row_factory = sqlite3.Row
    return conn.execute(f"SELECT * FROM {safe_name}").fetchall()


def _count_rows(conn: sqlite3.Connection, table_name: str, known_tables: set[str]) -> int:
    safe_name = _validate_table_name(table_name, known_tables)
    return int(conn.execute(f"SELECT COUNT(*) FROM {safe_name}").fetchone()[0])


def _count_valid_vector_rows(
    conn: sqlite3.Connection,
    dataset: _SqliteVectorDataset,
    known_tables: set[str],
) -> int:
    meta_table = _validate_table_name(dataset.meta_table, known_tables)
    vec_table = _validate_table_name(dataset.vec_table, known_tables)
    return int(
        conn.execute(
            f"SELECT COUNT(*) FROM {meta_table} AS m "
            f"JOIN {vec_table} AS v ON v.rowid = m.rowid "
            "WHERE v.embedding IS NOT NULL"
        ).fetchone()[0]
    )


def _discover_chunk_strategies(known_tables: set[str]) -> list[str]:
    return sorted(
        table_name.removeprefix("chunks_")
        for table_name in known_tables
        if table_name.startswith("chunks_")
        and not table_name.startswith("chunks_fts_")
        and table_name != "chunks"
    )


def _runtime_embedding_model() -> str | None:
    model_name = Settings().embedding.model.strip()
    return model_name or None


def _resolve_vector_dataset_embedding_model(
    *,
    config_table: str,
    model_key: str,
    vec_config: dict[str, str],
) -> str:
    model_name = vec_config.get("model")
    if model_name not in (None, ""):
        return str(model_name)

    runtime_model = _runtime_embedding_model()
    if runtime_model is None:
        raise ValueError(
            f"{config_table} is missing required 'model' key for model_key={model_key!r}"
        )

    runtime_model_key = _model_to_table_suffix(runtime_model).removeprefix("_")
    if runtime_model_key != model_key:
        raise ValueError(
            f"{config_table} is missing required 'model' key for model_key={model_key!r}; "
            f"embedding.model={runtime_model!r} resolves to {runtime_model_key!r}"
        )
    return runtime_model


def _discover_vector_datasets(
    conn: sqlite3.Connection,
    known_tables: set[str],
) -> list[_SqliteVectorDataset]:
    strategies = _discover_chunk_strategies(known_tables)
    datasets: list[_SqliteVectorDataset] = []
    for meta_table in sorted(table for table in known_tables if table.startswith("vec_meta_")):
        suffix = meta_table.removeprefix("vec_meta_")
        strategy = next(
            (
                candidate
                for candidate in sorted(strategies, key=len, reverse=True)
                if suffix.startswith(f"{candidate}_")
            ),
            None,
        )
        if strategy is None:
            continue
        model_key = suffix.removeprefix(f"{strategy}_")
        vec_table = f"vec_chunks_{strategy}_{model_key}"
        config_table = f"vec_config_{strategy}_{model_key}"
        if vec_table not in known_tables or config_table not in known_tables:
            continue
        vec_config_rows = [dict(row) for row in _fetch_all(conn, config_table, known_tables)]
        vec_config = {str(row["key"]): str(row["value"]) for row in vec_config_rows}
        component_table = f"vec_components_{strategy}_{model_key}"
        embed_fingerprint_table = f"embed_fingerprints_{strategy}_{model_key}"
        meta_fingerprint_table = f"meta_fingerprints_{strategy}_{model_key}"
        datasets.append(
            _SqliteVectorDataset(
                chunk_strategy=strategy,
                model_key=model_key,
                embedding_model=_resolve_vector_dataset_embedding_model(
                    config_table=config_table,
                    model_key=model_key,
                    vec_config=vec_config,
                ),
                vector_dimension=int(vec_config["dim"]) if "dim" in vec_config else None,
                meta_table=meta_table,
                vec_table=vec_table,
                config_table=config_table,
                component_table=component_table if component_table in known_tables else None,
                embed_fingerprint_table=(
                    embed_fingerprint_table if embed_fingerprint_table in known_tables else None
                ),
                meta_fingerprint_table=(
                    meta_fingerprint_table if meta_fingerprint_table in known_tables else None
                ),
            )
        )
    return datasets


def _decode_embedding_blob(blob: bytes) -> list[float]:
    if not blob:
        return []
    size = len(blob) // 4
    return list(struct.unpack(f"{size}f", blob))


def _loads_json_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item) for item in value]
    if not isinstance(value, str) or not value:
        return []
    loaded = json.loads(value)
    if not isinstance(loaded, list):
        return []
    return [str(item) for item in loaded]


def _loads_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    loaded = json.loads(value)
    if not isinstance(loaded, dict):
        return {}
    return dict(loaded)


def _normalize_tags_text(value: Any) -> str:
    if isinstance(value, list):
        return " ".join(str(item).strip() for item in value if str(item).strip())
    if value in (None, ""):
        return ""
    return str(value).strip()


def _normalize_text_hash(value: Any) -> str:
    if value in (None, ""):
        return ""
    return str(value)


def _fingerprint_document_ref(row: dict[str, Any]) -> str:
    return str(row.get("file_path") or row.get("chunk_id") or row.get("document_ref") or "")


def _fingerprint_checksum(row: dict[str, Any]) -> str:
    return str(row.get("checksum") or row.get("fingerprint") or row.get("meta_checksum") or "")


def _fingerprint_metadata(row: dict[str, Any]) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if row.get("indexed_at") is not None:
        metadata["indexed_at"] = row["indexed_at"]
    if row.get("size_bytes") is not None:
        metadata["size_bytes"] = row["size_bytes"]
    return metadata


def _fingerprint_sort_key(row: dict[str, Any]) -> tuple[str, str]:
    metadata = row.get("metadata")
    indexed_at = ""
    if isinstance(metadata, dict):
        indexed_at = str(metadata.get("indexed_at") or "")
    checksum = str(row.get("content_fingerprint") or row.get("metadata_fingerprint") or "")
    return indexed_at, checksum


def _dedupe_fingerprint_payloads(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        fingerprint_id = str(row["fingerprint_id"])
        existing = by_id.get(fingerprint_id)
        if existing is None or _fingerprint_sort_key(row) >= _fingerprint_sort_key(existing):
            by_id[fingerprint_id] = row
    return list(by_id.values())


def _composite_id(*parts: object) -> str:
    return "\x1f".join(str(part) for part in parts)


def _coerce_datetime(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, (int, float)):
        return datetime.fromtimestamp(value, UTC)
    if isinstance(value, str):
        normalized = value.replace("Z", "+00:00")
        return datetime.fromisoformat(normalized)
    raise TypeError(f"unsupported datetime value: {value!r}")


def _fetchmany_dicts(cursor: sqlite3.Cursor, *, batch_size: int) -> Iterator[dict[str, Any]]:
    while rows := cursor.fetchmany(batch_size):
        for row in rows:
            yield dict(row)


def load_sqlite_rows_for_surreal(
    sqlite_snapshot_path: Path,
    *,
    include_vectors: bool = True,
) -> dict[str, Any]:
    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)
        chunk_strategies = _discover_chunk_strategies(known_tables)
        vector_datasets = _discover_vector_datasets(conn, known_tables)

        chunk_rows: dict[str, dict[str, Any]] = {}
        provenance_rows: list[dict[str, Any]] = []
        file_path_rows: list[dict[str, Any]] = []
        chunk_fingerprint_rows: list[dict[str, Any]] = []
        for strategy in chunk_strategies:
            for row in _fetch_all(conn, f"chunks_{strategy}", known_tables):
                payload = dict(row)
                payload.setdefault("chunk_strategy", strategy)
                chunk_rows[str(row["chunk_id"])] = payload
            provenance_table = f"chunk_source_provenance_{strategy}"
            if provenance_table in known_tables:
                provenance_rows.extend(
                    dict(row) for row in _fetch_all(conn, provenance_table, known_tables)
                )
            file_paths_table = f"chunk_file_paths_{strategy}"
            if file_paths_table in known_tables:
                file_path_rows.extend(
                    dict(row) for row in _fetch_all(conn, file_paths_table, known_tables)
                )
            chunk_fingerprint_table = f"chunk_fingerprints_{strategy}"
            if chunk_fingerprint_table in known_tables:
                chunk_fingerprint_rows.extend(
                    dict(row) for row in _fetch_all(conn, chunk_fingerprint_table, known_tables)
                )
        source_document_rows = [
            dict(row) for row in _fetch_all(conn, "source_documents", known_tables)
        ]
        binding_rows = [dict(row) for row in _fetch_all(conn, "resource_bindings", known_tables)]
        source_unit_rows = [
            dict(row) for row in _fetch_all(conn, "source_unit_fingerprints", known_tables)
        ]
        checkpoint_rows = [
            dict(row) for row in _fetch_all(conn, "source_checkpoints", known_tables)
        ]
        vec_meta_rows: list[dict[str, Any]] = []
        vec_chunk_rows: dict[tuple[str, str, int], dict[str, Any]] = {}
        vec_component_rows: list[dict[str, Any]] = []
        if include_vectors:
            for dataset in vector_datasets:
                for row in _fetch_all(conn, dataset.meta_table, known_tables):
                    payload = dict(row)
                    payload["chunk_strategy"] = dataset.chunk_strategy
                    payload["embedding_model"] = dataset.embedding_model
                    vec_meta_rows.append(payload)
                for row in _fetch_all(conn, dataset.vec_table, known_tables):
                    vec_chunk_rows[
                        (dataset.chunk_strategy, dataset.embedding_model, int(row["rowid"]))
                    ] = dict(row)
                if dataset.component_table is not None:
                    vec_component_rows.extend(
                        dict(row) for row in _fetch_all(conn, dataset.component_table, known_tables)
                    )
        embed_fingerprint_rows: list[dict[str, Any]] = []
        meta_fingerprint_rows: list[dict[str, Any]] = []
        for dataset in vector_datasets:
            if dataset.embed_fingerprint_table is not None:
                embed_fingerprint_rows.extend(
                    dict(row)
                    for row in _fetch_all(conn, dataset.embed_fingerprint_table, known_tables)
                )
            if dataset.meta_fingerprint_table is not None:
                meta_fingerprint_rows.extend(
                    dict(row)
                    for row in _fetch_all(conn, dataset.meta_fingerprint_table, known_tables)
                )

    vector_dimension = next(
        (dataset.vector_dimension for dataset in vector_datasets if dataset.vector_dimension),
        None,
    )
    embedding_model = next(
        (dataset.embedding_model for dataset in vector_datasets),
        "unknown-model",
    )

    file_paths_by_chunk: dict[str, list[str]] = {}
    file_bindings_by_chunk: dict[str, list[dict[str, Any]]] = {}
    chunk_file_binding_rows: list[dict[str, Any]] = []
    for row in file_path_rows:
        chunk_id = str(row["chunk_id"])
        binding_payload = {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "binding_id": _composite_id(chunk_id, row["file_path"], row["chunk_index"]),
            "chunk_id": chunk_id,
            "file_path": str(row["file_path"]),
            "chunk_index": int(row["chunk_index"]),
            "metadata": {},
        }
        file_paths_by_chunk.setdefault(chunk_id, []).append(str(row["file_path"]))
        file_bindings_by_chunk.setdefault(chunk_id, []).append(binding_payload)
        chunk_file_binding_rows.append(binding_payload)

    provenance_by_chunk: dict[str, list[dict[str, Any]]] = {}
    provenance_payloads: list[dict[str, Any]] = []
    for row in provenance_rows:
        chunk_id = str(row["chunk_id"])
        payload = {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "provenance_id": _composite_id(chunk_id, row["namespace"], row["document_ref"]),
            "chunk_id": chunk_id,
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "source_unit_refs": _loads_json_list(row["source_unit_refs"]),
            "chunk_strategy": str(row["chunk_strategy"]),
            "parser_name": row["parser_name"],
            "metadata": {},
        }
        provenance_by_chunk.setdefault(chunk_id, []).append(payload)
        provenance_payloads.append(payload)

    documents_by_identity = {
        (str(row["namespace"]), str(row["document_ref"])): dict(row) for row in source_document_rows
    }

    document_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "ref": str(row["ref"]),
            "title": str(row["title"]),
            "media_type": str(row["media_type"]),
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in source_document_rows
    ]

    binding_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "namespace": str(row["namespace"]),
            "resource_ref": str(row["resource_ref"]),
            "document_ref": str(row["document_ref"]),
            "ref": str(row["ref"]),
            "active": bool(row["active"]),
            "bound_at": _coerce_datetime(row["bound_at"]),
            "unbound_at": _coerce_datetime(row["unbound_at"]),
            "content_fingerprint": str(row["content_fingerprint"]),
            "metadata_fingerprint": str(row["metadata_fingerprint"]),
            "source_unit_refs": _loads_json_list(row["source_unit_refs"]),
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in binding_rows
    ]

    source_unit_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "unit_ref": str(row["unit_ref"]),
            "fingerprint": str(row["fingerprint"]),
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in source_unit_rows
    ]

    chunk_payloads: list[dict[str, Any]] = []
    for chunk_id, row in chunk_rows.items():
        provenance_for_chunk = provenance_by_chunk.get(chunk_id, [])
        first_provenance = provenance_for_chunk[0] if provenance_for_chunk else {}
        namespace = first_provenance.get("namespace")
        document_ref = first_provenance.get("document_ref")
        source_document = (
            documents_by_identity.get((str(namespace), str(document_ref)))
            if namespace is not None and document_ref is not None
            else None
        )
        source_metadata = (
            _loads_json_object(source_document["metadata_json"])
            if source_document is not None
            else {}
        )
        chunk_payloads.append(
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "original_chunk_id": chunk_id,
                "chunk_id": chunk_id,
                "chunk_strategy": first_provenance.get("chunk_strategy", "contextual_512_50"),
                "heading_hierarchy": _loads_json_list(row["heading_hierarchy"]),
                "level": int(row["level"]),
                "title": (
                    str(source_document["title"])
                    if source_document is not None and source_document.get("title") is not None
                    else ""
                ),
                "tags_text": _normalize_tags_text(source_metadata.get("tags")),
                "text": str(row["text"]),
                "file_paths": list(file_paths_by_chunk.get(chunk_id, [])),
                "file_bindings": list(file_bindings_by_chunk.get(chunk_id, [])),
                "document_ref": document_ref,
                "ref": (
                    str(source_document["ref"])
                    if source_document is not None and source_document.get("ref") is not None
                    else (f"{namespace}:{document_ref}" if namespace and document_ref else None)
                ),
                "source_unit_refs": first_provenance.get("source_unit_refs", []),
                "metadata": {},
            }
        )

    embedding_payloads: list[dict[str, Any]] = []
    for row in vec_meta_rows:
        vector_rowid = int(row["rowid"])
        chunk_strategy = str(row["chunk_strategy"])
        row_embedding_model = str(row["embedding_model"])
        vector_row = vec_chunk_rows.get((chunk_strategy, row_embedding_model, vector_rowid))
        if vector_row is None or not vector_row.get("embedding"):
            continue
        embedding_payloads.append(
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "chunk_id": str(row["chunk_id"]),
                "chunk_strategy": chunk_strategy,
                "embedding_model": row_embedding_model,
                "text_hash": _normalize_text_hash(row["text_hash"]),
                "vector_rowid": vector_rowid,
                "vector": _decode_embedding_blob(vector_row["embedding"]),
                "metadata": {},
            }
        )

    vector_component_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "chunk_id": str(row.get("chunk_id") or row.get("entity_id")),
            "component": str(row["component"]),
            "embedding": _decode_embedding_blob(row["embedding"]),
            "metadata": {},
        }
        for row in vec_component_rows
    ]

    fingerprint_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "fingerprint_id": f"chunk::{row['file_path']}",
            "fingerprint_kind": "chunk",
            "namespace": "filesystem",
            "document_ref": str(row["file_path"]),
            "content_fingerprint": str(row["checksum"]),
            "metadata_fingerprint": None,
            "metadata": {"indexed_at": row["indexed_at"], "size_bytes": row["size_bytes"]},
        }
        for row in chunk_fingerprint_rows
    ]
    fingerprint_payloads.extend(
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "fingerprint_id": f"embed::{_fingerprint_document_ref(row)}",
            "fingerprint_kind": "embed",
            "namespace": "filesystem",
            "document_ref": _fingerprint_document_ref(row),
            "content_fingerprint": _fingerprint_checksum(row),
            "metadata_fingerprint": None,
            "metadata": _fingerprint_metadata(row),
        }
        for row in embed_fingerprint_rows
    )
    fingerprint_payloads.extend(
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "fingerprint_id": f"meta::{_fingerprint_document_ref(row)}",
            "fingerprint_kind": "meta",
            "namespace": "filesystem",
            "document_ref": _fingerprint_document_ref(row),
            "content_fingerprint": None,
            "metadata_fingerprint": _fingerprint_checksum(row),
            "metadata": _fingerprint_metadata(row),
        }
        for row in meta_fingerprint_rows
    )
    fingerprint_payloads.extend(
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "fingerprint_id": f"source_unit::{row['document_ref']}::{row['unit_ref']}",
            "fingerprint_kind": "source_unit",
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "content_fingerprint": str(row["fingerprint"]),
            "metadata_fingerprint": None,
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in source_unit_rows
    )
    fingerprint_payloads = _dedupe_fingerprint_payloads(fingerprint_payloads)

    cursor_rows = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "cursor_id": str(row["ref"]),
            "namespace": str(row["namespace"]),
            "ref": str(row["ref"]),
            "document_ref": str(row["document_ref"]),
            "active": bool(row["active"]),
            "bound_at": _coerce_datetime(row["bound_at"]),
            "unbound_at": _coerce_datetime(row["unbound_at"]),
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in binding_rows
    ]

    checkpoint_payloads = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "namespace": str(row["namespace"]),
            "checkpoint_cursor": row["checkpoint_cursor"],
            "last_success_at": _coerce_datetime(row["last_success_at"]),
            "last_error": row["last_error"],
            "metadata": _loads_json_object(row["metadata_json"]),
        }
        for row in checkpoint_rows
    ]

    unsupported_categories = [
        *[category for category in _STABLE_UNSUPPORTED_CATEGORIES if category != "sqlite_internal"],
        "sqlite_internal",
    ]

    return {
        "documents": document_payloads,
        "source_units": source_unit_payloads,
        "chunks": chunk_payloads,
        "chunk_file_bindings": chunk_file_binding_rows,
        "provenance": provenance_payloads,
        "bindings": binding_payloads,
        "fingerprints": fingerprint_payloads,
        "embeddings": embedding_payloads,
        "vector_components": vector_component_payloads,
        "cursors": cursor_rows,
        "checkpoints": checkpoint_payloads,
        "unsupported_categories": unsupported_categories,
        "expected_vector_dimension": vector_dimension,
        "embedding_model": embedding_model,
        "internal_tables": sorted(
            table_name
            for table_name in known_tables
            if table_name.startswith(_SQLITE_INTERNAL_PREFIXES)
        ),
    }


def iter_sqlite_embedding_rows_for_surreal(
    sqlite_snapshot_path: Path,
    *,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)
        conn.row_factory = sqlite3.Row
        for dataset in _discover_vector_datasets(conn, known_tables):
            meta_table = _validate_table_name(dataset.meta_table, known_tables)
            vec_table = _validate_table_name(dataset.vec_table, known_tables)
            cursor = conn.execute(
                f"SELECT m.rowid AS vector_rowid, m.chunk_id AS chunk_id, "
                f"m.text_hash AS text_hash, v.embedding AS embedding "
                f"FROM {meta_table} AS m LEFT JOIN {vec_table} AS v ON v.rowid = m.rowid "
                f"ORDER BY m.rowid"
            )
            for row in _fetchmany_dicts(cursor, batch_size=batch_size):
                if not row["embedding"]:
                    continue
                yield {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_strategy": dataset.chunk_strategy,
                    "embedding_model": dataset.embedding_model,
                    "text_hash": _normalize_text_hash(row["text_hash"]),
                    "vector_rowid": int(row["vector_rowid"]),
                    "vector": _decode_embedding_blob(row["embedding"]),
                    "metadata": {},
                }
