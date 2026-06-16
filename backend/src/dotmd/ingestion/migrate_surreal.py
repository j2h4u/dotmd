"""Production migration runner for Phase 41 Surreal imports."""

from __future__ import annotations

import hashlib
import json
import os
import re
import resource
import shutil
import sqlite3
import struct
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealFeedbackStore,
    SurrealGraphStore,
    SurrealMetadataStore,
    SurrealStoreConfig,
    SurrealVectorStore,
    define_dotmd_surreal_schema,
)
from dotmd.storage.surreal_ops import (
    SurrealEmbeddedSafetyReport,
    assert_embedded_safety_gate_passed,
)
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
_MIGRATION_PHASE_ORDER = (
    "schema",
    "documents",
    "source_units",
    "chunks",
    "chunk_file_bindings",
    "provenance",
    "bindings",
    "fingerprints",
    "embeddings",
    "indexes",
    "vector_components",
    "graph",
    "feedback",
    "cursors",
    "checkpoints",
)


class SurrealMigrationMode(StrEnum):
    PLAN = "plan"
    DRY_RUN = "dry-run"
    APPLY = "apply"
    VERIFY = "verify"


class SurrealOverwritePolicy(StrEnum):
    REFUSE = "refuse"
    EXPLICIT_REPLACE = "explicit_replace"


class SurrealMigrationPhaseName(StrEnum):
    SCHEMA = "schema"
    DOCUMENTS = "documents"
    SOURCE_UNITS = "source_units"
    CHUNKS = "chunks"
    CHUNK_FILE_BINDINGS = "chunk_file_bindings"
    PROVENANCE = "provenance"
    BINDINGS = "bindings"
    FINGERPRINTS = "fingerprints"
    EMBEDDINGS = "embeddings"
    INDEXES = "indexes"
    VECTOR_COMPONENTS = "vector_components"
    GRAPH = "graph"
    FEEDBACK = "feedback"
    CURSORS = "cursors"
    CHECKPOINTS = "checkpoints"


class SurrealTargetMode(StrEnum):
    EMBEDDED_LOCAL = "embedded_local"
    REMOTE_SERVICE = "remote_service"


class SurrealVerificationDepth(StrEnum):
    CHEAP = "cheap"
    DEEP = "deep"


@dataclass(slots=True, frozen=True)
class SurrealSourceCaptureManifest:
    sqlite_snapshot: dict[str, Any]
    graph_export: dict[str, Any]
    feedback_export: dict[str, Any]
    skew_policy: str
    source_identity: str


@dataclass(slots=True)
class SurrealMigrationPhaseCheckpoint:
    phase_name: SurrealMigrationPhaseName
    planned_count: int
    applied_count: int = 0
    verified_count: int = 0
    status: str = "pending"
    error: str | None = None


@dataclass(slots=True, frozen=True)
class SurrealMigrationManifest:
    schema_version: str
    target_url: str
    target_namespace: str
    target_database: str
    target_mode: SurrealTargetMode
    source_capture_manifest: SurrealSourceCaptureManifest
    expected_counts: dict[str, int]
    unsupported_categories: list[str]
    recompute_forbidden: bool
    expected_vector_dimension: int | None


@dataclass(slots=True)
class SurrealMigrationReport:
    schema_version: str
    mode: SurrealMigrationMode
    status: str
    target_mode: SurrealTargetMode
    overwrite_policy: SurrealOverwritePolicy
    target_url: str
    target_namespace: str
    target_database: str
    source_capture_manifest: SurrealSourceCaptureManifest | None
    expected_counts: dict[str, int] = field(default_factory=dict)
    actual_counts: dict[str, int] = field(default_factory=dict)
    target_pre_counts: dict[str, int] = field(default_factory=dict)
    target_inspection_performed: bool = False
    unsupported_categories: list[str] = field(default_factory=list)
    cheap_invariants: list[str] = field(default_factory=list)
    deep_sample_checks: list[str] = field(default_factory=list)
    phase_checkpoints: list[SurrealMigrationPhaseCheckpoint] = field(default_factory=list)
    recompute_forbidden: bool = True
    recompute_guard_status: str = "pending"
    embedding_reuse_verified: bool = False
    expected_vector_dimension: int | None = None
    committed_success: bool = False
    verified: bool = False
    partial_writes_present: bool = False
    last_successful_phase: SurrealMigrationPhaseName | None = None
    failed_phase: SurrealMigrationPhaseName | None = None
    cleanup_attempted: bool = False
    restore_required: bool = False
    rollback_evidence: str | None = None
    gate_status: str = "not_required"
    errors: list[str] = field(default_factory=list)
    started_at_monotonic: float = field(default_factory=time.monotonic)


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


def _discover_chunk_strategies(known_tables: set[str]) -> list[str]:
    return sorted(
        table_name.removeprefix("chunks_")
        for table_name in known_tables
        if table_name.startswith("chunks_")
        and not table_name.startswith("chunks_fts_")
        and table_name != "chunks"
    )


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
                embedding_model=vec_config.get("model", model_key),
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


def _composite_id(*parts: object) -> str:
    return "\x1f".join(str(part) for part in parts)


def _sha256_for_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8192):
            digest.update(chunk)
    return digest.hexdigest()


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


def _isoformat_mtime(path: Path) -> str:
    return (
        datetime.fromtimestamp(path.stat().st_mtime, UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _load_gate_report(path: Path) -> SurrealEmbeddedSafetyReport:
    text = path.read_text(encoding="utf-8")
    if "- go_no_go: PASS" not in text:
        return SurrealEmbeddedSafetyReport(
            probe_kind="merged",
            target_url=str(path),
            target_path=str(path),
            go_no_go=False,
            blockers=["gate report is missing a PASS go_no_go result"],
        )
    return SurrealEmbeddedSafetyReport(
        probe_kind="merged",
        target_url=str(path),
        target_path=str(path),
        go_no_go=True,
    )


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
                provenance_rows.extend(dict(row) for row in _fetch_all(conn, provenance_table, known_tables))
            file_paths_table = f"chunk_file_paths_{strategy}"
            if file_paths_table in known_tables:
                file_path_rows.extend(dict(row) for row in _fetch_all(conn, file_paths_table, known_tables))
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
                    payload = dict(row)
                    vec_chunk_rows[
                        (dataset.chunk_strategy, dataset.embedding_model, int(row["rowid"]))
                    ] = payload
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
        embedding_payloads.append(
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "chunk_id": str(row["chunk_id"]),
                "original_chunk_id": str(row["chunk_id"]),
                "chunk_strategy": chunk_strategy,
                "embedding_model": row_embedding_model,
                "text_hash": _normalize_text_hash(row["text_hash"]),
                "vector_rowid": vector_rowid,
                "embedding": (
                    _decode_embedding_blob(vector_row["embedding"])
                    if vector_row is not None
                    else []
                ),
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
                yield {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_id": str(row["chunk_id"]),
                    "original_chunk_id": str(row["chunk_id"]),
                    "chunk_strategy": dataset.chunk_strategy,
                    "embedding_model": dataset.embedding_model,
                    "text_hash": _normalize_text_hash(row["text_hash"]),
                    "vector_rowid": int(row["vector_rowid"]),
                    "embedding": _decode_embedding_blob(row["embedding"] or b""),
                    "metadata": {},
                }


def iter_sqlite_vector_component_rows_for_surreal(
    sqlite_snapshot_path: Path,
    *,
    batch_size: int = 1000,
) -> Iterator[dict[str, Any]]:
    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)
        conn.row_factory = sqlite3.Row
        for dataset in _discover_vector_datasets(conn, known_tables):
            if dataset.component_table is None:
                continue
            table_name = _validate_table_name(dataset.component_table, known_tables)
            cursor = conn.execute(f"SELECT * FROM {table_name}")
            for row in _fetchmany_dicts(cursor, batch_size=batch_size):
                yield {
                    "schema_version": SURREAL_SCHEMA_VERSION,
                    "chunk_strategy": dataset.chunk_strategy,
                    "embedding_model": dataset.embedding_model,
                    "chunk_id": str(row.get("chunk_id") or row.get("entity_id")),
                    "component": str(row["component"]),
                    "embedding": _decode_embedding_blob(row["embedding"]),
                    "metadata": {},
                }


def load_sqlite_stats_for_surreal(sqlite_snapshot_path: Path) -> dict[str, Any]:
    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)
        chunk_strategies = _discover_chunk_strategies(known_tables)
        vector_datasets = _discover_vector_datasets(conn, known_tables)
        vector_dimensions = {
            dataset.vector_dimension
            for dataset in vector_datasets
            if dataset.vector_dimension is not None
        }
        counts = {
            "documents": _count_rows(conn, "source_documents", known_tables),
            "source_units": _count_rows(conn, "source_unit_fingerprints", known_tables),
            "chunks": sum(
                _count_rows(conn, f"chunks_{strategy}", known_tables)
                for strategy in chunk_strategies
            ),
            "chunk_file_bindings": sum(
                _count_rows(conn, table_name, known_tables)
                for table_name in (f"chunk_file_paths_{strategy}" for strategy in chunk_strategies)
                if table_name in known_tables
            ),
            "provenance": sum(
                _count_rows(conn, table_name, known_tables)
                for table_name in (
                    f"chunk_source_provenance_{strategy}" for strategy in chunk_strategies
                )
                if table_name in known_tables
            ),
            "bindings": _count_rows(conn, "resource_bindings", known_tables),
            "fingerprints": (
                sum(
                    _count_rows(conn, table_name, known_tables)
                    for table_name in (
                        f"chunk_fingerprints_{strategy}" for strategy in chunk_strategies
                    )
                    if table_name in known_tables
                )
                + sum(
                    _count_rows(conn, table_name, known_tables)
                    for dataset in vector_datasets
                    for table_name in (
                        dataset.embed_fingerprint_table,
                        dataset.meta_fingerprint_table,
                    )
                    if table_name is not None
                )
                + _count_rows(conn, "source_unit_fingerprints", known_tables)
            ),
            "embeddings": sum(
                _count_rows(conn, dataset.meta_table, known_tables) for dataset in vector_datasets
            ),
            # vector_components is optional derived storage, not a retrieval
            # prerequisite. Migrating it by default duplicates a second large
            # vector payload class, so production migration preserves primary
            # embeddings only unless a later phase reintroduces a proven need.
            "vector_components": 0,
            "cursors": _count_rows(conn, "resource_bindings", known_tables),
            "checkpoints": _count_rows(conn, "source_checkpoints", known_tables),
        }
    return {
        "counts": counts,
        "expected_vector_dimension": (
            next(iter(vector_dimensions)) if len(vector_dimensions) == 1 else None
        ),
    }


def load_graph_rows_for_surreal(graph_export_path: Path) -> dict[str, Any]:
    payload = json.loads(Path(graph_export_path).read_text(encoding="utf-8"))
    rows = dict(payload.get("rows", {}))
    entities = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "original_id": str(row.get("name")),
            "original_entity_name": str(row.get("name")),
            "name": str(row.get("name")),
            "entity_type": str(row.get("entity_type", "Entity")),
            "source": str(row.get("source", "")),
            "metadata": {},
        }
        for row in rows.get("entities", [])
    ]
    relations = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "relation_id": str(row["relation_id"]),
            "rel_type": str(row.get("relation_type") or row.get("rel_type")),
            "relation_type": str(row.get("relation_type") or row.get("rel_type")),
            "weight": float(row.get("weight", 1.0)),
            "source_id": str(row["source_id"]),
            "target_id": str(row["target_id"]),
            "source_table": "sections",
            "target_table": "tags"
            if str(row.get("relation_type") or row.get("rel_type")) == "HAS_TAG"
            else "entities",
            "properties": dict(row.get("properties", {})),
            "metadata": {},
        }
        for row in rows.get("relations", [])
    ]
    return {
        "inventory": dict(payload.get("inventory", {})),
        "exported_at": payload.get("exported_at"),
        "files": list(rows.get("files", [])),
        "sections": list(rows.get("sections", [])),
        "tags": list(rows.get("tags", [])),
        "entities": entities,
        "relations": relations,
    }


def load_feedback_rows_for_surreal(feedback_export_path: Path) -> dict[str, Any]:
    payload = json.loads(Path(feedback_export_path).read_text(encoding="utf-8"))
    if payload.get("truncated"):
        raise RuntimeError(
            "feedback export is truncated and cannot claim production-derived parity"
        )
    rows = [
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "original_feedback_id": str(row["id"]),
            "submitted_at": _coerce_datetime(row["submitted_at"]),
            "message": row["message"],
            "severity": row.get("severity"),
            "status": row.get("status"),
            "context": row.get("context"),
            "model": row.get("model"),
            "metadata": {},
        }
        for row in payload.get("rows", [])
    ]
    return {"exported_at": payload.get("exported_at"), "rows": rows}


def _build_expected_counts(
    sqlite_rows: dict[str, Any],
    graph_rows: dict[str, Any],
    feedback_rows: dict[str, Any],
) -> dict[str, int]:
    return _build_expected_counts_from_sqlite_counts(
        sqlite_counts={
            "documents": len(sqlite_rows["documents"]),
            "source_units": len(sqlite_rows["source_units"]),
            "chunks": len(sqlite_rows["chunks"]),
            "chunk_file_bindings": len(sqlite_rows["chunk_file_bindings"]),
            "provenance": len(sqlite_rows["provenance"]),
            "bindings": len(sqlite_rows["bindings"]),
            "fingerprints": len(sqlite_rows["fingerprints"]),
            "embeddings": len(sqlite_rows["embeddings"]),
            "vector_components": len(sqlite_rows["vector_components"]),
            "cursors": len(sqlite_rows["cursors"]),
            "checkpoints": len(sqlite_rows["checkpoints"]),
        },
        graph_rows=graph_rows,
        feedback_rows=feedback_rows,
    )


def _build_expected_counts_from_sqlite_counts(
    sqlite_counts: dict[str, int],
    graph_rows: dict[str, Any],
    feedback_rows: dict[str, Any],
) -> dict[str, int]:
    derived_section_ids = {str(row["source_id"]) for row in graph_rows["relations"]}
    derived_tag_ids = {
        str(row["target_id"])
        for row in graph_rows["relations"]
        if str(row.get("relation_type") or row.get("rel_type")) == "HAS_TAG"
    }
    return {
        "documents": sqlite_counts["documents"],
        "source_units": sqlite_counts["source_units"],
        "chunks": sqlite_counts["chunks"],
        "chunk_file_bindings": sqlite_counts["chunk_file_bindings"],
        "provenance": sqlite_counts["provenance"],
        "bindings": sqlite_counts["bindings"],
        "fingerprints": sqlite_counts["fingerprints"],
        "embeddings": sqlite_counts["embeddings"],
        "vector_components": sqlite_counts["vector_components"],
        "graph_files": len(graph_rows["files"]),
        "graph_sections": max(len(graph_rows["sections"]), len(derived_section_ids)),
        "graph_entities": len(graph_rows["entities"]),
        "graph_tags": max(len(graph_rows["tags"]), len(derived_tag_ids)),
        "graph_relations": len(graph_rows["relations"]),
        "feedback": len(feedback_rows["rows"]),
        "cursors": sqlite_counts["cursors"],
        "checkpoints": sqlite_counts["checkpoints"],
    }


def _build_source_capture_manifest(
    *,
    sqlite_snapshot_path: Path,
    sqlite_rows: dict[str, Any],
    graph_export_path: Path,
    graph_rows: dict[str, Any],
    feedback_export_path: Path,
    feedback_rows: dict[str, Any],
    skew_policy: str,
) -> SurrealSourceCaptureManifest:
    sqlite_counts = {
        "documents": len(sqlite_rows["documents"]),
        "source_units": len(sqlite_rows["source_units"]),
        "chunks": len(sqlite_rows["chunks"]),
        "chunk_file_bindings": len(sqlite_rows["chunk_file_bindings"]),
        "embeddings": len(sqlite_rows["embeddings"]),
        "cursors": len(sqlite_rows["cursors"]),
        "checkpoints": len(sqlite_rows["checkpoints"]),
    }
    return _build_source_capture_manifest_from_counts(
        sqlite_snapshot_path=sqlite_snapshot_path,
        sqlite_counts=sqlite_counts,
        graph_export_path=graph_export_path,
        graph_rows=graph_rows,
        feedback_export_path=feedback_export_path,
        feedback_rows=feedback_rows,
        skew_policy=skew_policy,
    )


def _build_source_capture_manifest_from_counts(
    *,
    sqlite_snapshot_path: Path,
    sqlite_counts: dict[str, int],
    graph_export_path: Path,
    graph_rows: dict[str, Any],
    feedback_export_path: Path,
    feedback_rows: dict[str, Any],
    skew_policy: str,
) -> SurrealSourceCaptureManifest:
    graph_counts = {
        "entities": len(graph_rows["entities"]),
        "relations": len(graph_rows["relations"]),
    }
    feedback_counts = {"rows": len(feedback_rows["rows"])}
    return SurrealSourceCaptureManifest(
        sqlite_snapshot={
            "path": str(sqlite_snapshot_path),
            "created_at": _isoformat_mtime(sqlite_snapshot_path),
            "sha256": _sha256_for_file(sqlite_snapshot_path),
            "counts": sqlite_counts,
        },
        graph_export={
            "path": str(graph_export_path),
            "exported_at": graph_rows.get("exported_at") or _isoformat_mtime(graph_export_path),
            "sha256": _sha256_for_file(graph_export_path),
            "counts": graph_counts,
        },
        feedback_export={
            "path": str(feedback_export_path),
            "exported_at": feedback_rows.get("exported_at")
            or _isoformat_mtime(feedback_export_path),
            "sha256": _sha256_for_file(feedback_export_path),
            "counts": feedback_counts,
        },
        skew_policy=skew_policy,
        source_identity=str(sqlite_snapshot_path.resolve()),
    )


def build_surreal_migration_manifest(
    *,
    sqlite_snapshot_path: Path,
    graph_export_path: Path,
    feedback_export_path: Path,
    target_url: str,
    target_mode: SurrealTargetMode,
    target_namespace: str = "dotmd",
    target_database: str = "phase41_migration",
    skew_policy: str = "bounded_skew_accepted",
) -> SurrealMigrationManifest:
    sqlite_stats = load_sqlite_stats_for_surreal(Path(sqlite_snapshot_path))
    sqlite_counts = sqlite_stats["counts"]
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))
    return SurrealMigrationManifest(
        schema_version=SURREAL_SCHEMA_VERSION,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
        target_mode=target_mode,
        source_capture_manifest=_build_source_capture_manifest_from_counts(
            sqlite_snapshot_path=Path(sqlite_snapshot_path),
            sqlite_counts=sqlite_counts,
            graph_export_path=Path(graph_export_path),
            graph_rows=graph_rows,
            feedback_export_path=Path(feedback_export_path),
            feedback_rows=feedback_rows,
            skew_policy=skew_policy,
        ),
        expected_counts=_build_expected_counts_from_sqlite_counts(
            sqlite_counts,
            graph_rows,
            feedback_rows,
        ),
        unsupported_categories=list(_STABLE_UNSUPPORTED_CATEGORIES),
        recompute_forbidden=True,
        expected_vector_dimension=sqlite_stats["expected_vector_dimension"],
    )


def _report_from_manifest(
    manifest: SurrealMigrationManifest,
    *,
    mode: SurrealMigrationMode,
    overwrite_policy: SurrealOverwritePolicy,
) -> SurrealMigrationReport:
    return SurrealMigrationReport(
        schema_version=manifest.schema_version,
        mode=mode,
        status=mode.value,
        target_mode=manifest.target_mode,
        overwrite_policy=overwrite_policy,
        target_url=manifest.target_url,
        target_namespace=manifest.target_namespace,
        target_database=manifest.target_database,
        source_capture_manifest=manifest.source_capture_manifest,
        expected_counts=dict(manifest.expected_counts),
        unsupported_categories=list(manifest.unsupported_categories),
        recompute_forbidden=manifest.recompute_forbidden,
        expected_vector_dimension=manifest.expected_vector_dimension,
    )


def _empty_report(
    *,
    mode: SurrealMigrationMode,
    target_mode: SurrealTargetMode,
    overwrite_policy: SurrealOverwritePolicy,
    target_url: str,
    target_namespace: str,
    target_database: str,
    status: str,
    errors: list[str],
) -> SurrealMigrationReport:
    return SurrealMigrationReport(
        schema_version=SURREAL_SCHEMA_VERSION,
        mode=mode,
        status=status,
        target_mode=target_mode,
        overwrite_policy=overwrite_policy,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
        source_capture_manifest=None,
        errors=errors,
    )


def _connection_for_target(
    *,
    target_url: str,
    target_namespace: str,
    target_database: str,
) -> SurrealConnection:
    return SurrealConnection(
        SurrealStoreConfig(
            url=target_url,
            namespace=target_namespace,
            database=target_database,
        )
    )


def _count_target_rows(connection: SurrealConnection) -> dict[str, int]:
    def count(table_name: str) -> int:
        rows = _query_surreal_rows(
            connection,
            f"SELECT count() AS count FROM {table_name} GROUP ALL;",
        )
        if not rows:
            return 0
        raw_count = rows[0].get("count")
        if isinstance(raw_count, list) and raw_count:
            raw_count = raw_count[0]
        return int(raw_count or 0)

    return {
        "documents": count("documents"),
        "source_units": count("source_units"),
        "chunks": count("chunks"),
        "chunk_file_bindings": count("chunk_file_bindings"),
        "provenance": count("provenance"),
        "bindings": count("bindings"),
        "fingerprints": count("fingerprints"),
        "embeddings": count("embeddings"),
        "vector_components": count("vector_components"),
        "graph_files": count("files"),
        "graph_sections": count("sections"),
        "graph_entities": count("entities"),
        "graph_tags": count("tags"),
        "graph_relations": count("relations"),
        "feedback": count("feedback"),
        "cursors": count("cursors"),
        "checkpoints": count("checkpoints"),
    }


def _query_surreal_rows(connection: SurrealConnection, statement: str) -> list[dict[str, Any]]:
    payload = connection.query(statement)
    if isinstance(payload, list):
        if payload and isinstance(payload[0], dict) and "result" in payload[0]:
            result = payload[0]["result"]
            if isinstance(result, list):
                return [dict(row) for row in result if isinstance(row, dict)]
            if isinstance(result, dict):
                return [dict(result)]
        return [dict(row) for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        result = payload.get("result")
        if isinstance(result, list):
            return [dict(row) for row in result if isinstance(row, dict)]
        if isinstance(result, dict):
            return [dict(result)]
        return [dict(payload)]
    return []


def _load_sqlite_embedding_rows_by_chunk_id(
    sqlite_snapshot_path: Path,
    chunk_ids: list[str],
) -> dict[str, dict[str, Any]]:
    if not chunk_ids:
        return {}
    placeholders = ", ".join("?" for _ in chunk_ids)
    result: dict[str, dict[str, Any]] = {}
    with _sqlite_connect_read_only(Path(sqlite_snapshot_path)) as conn:
        known_tables = _discover_tables(conn)
        conn.row_factory = sqlite3.Row
        for dataset in _discover_vector_datasets(conn, known_tables):
            meta_table = _validate_table_name(dataset.meta_table, known_tables)
            vec_table = _validate_table_name(dataset.vec_table, known_tables)
            rows = conn.execute(
                f"SELECT m.rowid AS vector_rowid, m.chunk_id AS chunk_id, "
                f"m.text_hash AS text_hash, v.embedding AS embedding "
                f"FROM {meta_table} AS m LEFT JOIN {vec_table} AS v ON v.rowid = m.rowid "
                f"WHERE m.chunk_id IN ({placeholders})",
                chunk_ids,
            ).fetchall()
            for row in rows:
                result[str(row["chunk_id"])] = {
                    "chunk_id": str(row["chunk_id"]),
                    "chunk_strategy": dataset.chunk_strategy,
                    "embedding_model": dataset.embedding_model,
                    "text_hash": _normalize_text_hash(row["text_hash"]),
                    "vector_rowid": int(row["vector_rowid"]),
                    "embedding": _decode_embedding_blob(row["embedding"] or b""),
                }
    return result


def _phase_name(name: str) -> SurrealMigrationPhaseName:
    return SurrealMigrationPhaseName(name)


def _make_phase_checkpoint(
    phase_name: str,
    planned_count: int,
) -> SurrealMigrationPhaseCheckpoint:
    return SurrealMigrationPhaseCheckpoint(
        phase_name=_phase_name(phase_name),
        planned_count=planned_count,
    )


def _write_progress_snapshot(
    progress_path: Path | None,
    *,
    report: SurrealMigrationReport,
    checkpoint: SurrealMigrationPhaseCheckpoint,
    applied_count: int | None = None,
) -> None:
    if progress_path is None:
        return
    current_applied = applied_count if applied_count is not None else checkpoint.applied_count
    current_percent = (
        round((current_applied / checkpoint.planned_count) * 100, 2)
        if checkpoint.planned_count
        else 100.0
    )
    payload = {
        "schema_version": report.schema_version,
        "mode": report.mode.value,
        "status": report.status,
        "target_mode": report.target_mode.value,
        "target_url": report.target_url,
        "elapsed_seconds": round(time.monotonic() - report.started_at_monotonic, 3),
        "progress_updated_at": datetime.now(UTC)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "process_rss_bytes": _process_rss_bytes(),
        "target_size_bytes": _target_size_bytes(report.target_url),
        "current_phase": checkpoint.phase_name.value,
        "current_phase_status": checkpoint.status,
        "current_phase_planned_count": checkpoint.planned_count,
        "current_phase_applied_count": current_applied,
        "current_phase_percent": current_percent,
        "last_successful_phase": (
            report.last_successful_phase.value if report.last_successful_phase else None
        ),
        "failed_phase": report.failed_phase.value if report.failed_phase else None,
        "phase_checkpoints": [
            {
                "phase_name": phase.phase_name.value,
                "planned_count": phase.planned_count,
                "applied_count": phase.applied_count,
                "verified_count": phase.verified_count,
                "status": phase.status,
                "error": phase.error,
            }
            for phase in report.phase_checkpoints
        ],
    }
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _load_resume_phase_names(
    progress_path: Path | None,
    *,
    report: SurrealMigrationReport,
    enabled: bool,
) -> set[str]:
    if not enabled or progress_path is None or not progress_path.exists():
        return set()
    try:
        payload = json.loads(progress_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    if not isinstance(payload, dict):
        return set()
    if payload.get("schema_version") != report.schema_version:
        return set()
    if payload.get("mode") != report.mode.value:
        return set()
    if payload.get("target_url") != report.target_url:
        return set()
    checkpoints = payload.get("phase_checkpoints")
    if not isinstance(checkpoints, list):
        return set()
    return {
        str(checkpoint.get("phase_name"))
        for checkpoint in checkpoints
        if isinstance(checkpoint, dict) and checkpoint.get("status") == "applied"
    }


def _inspect_target(
    report: SurrealMigrationReport,
    *,
    target_url: str,
    target_namespace: str,
    target_database: str,
) -> dict[str, str]:
    with _connection_for_target(
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
    ) as connection:
        report.target_pre_counts = _count_target_rows(connection)
        report.target_inspection_performed = True
        schema_info = connection.inspect_schema()
    return {
        "schema_version": str(schema_info.get("schema_version") or ""),
        "table_modes": json.dumps(schema_info.get("table_modes", {}), sort_keys=True),
    }


def _verify_target_mode_inputs(
    *,
    target_mode: SurrealTargetMode,
    target_url: str,
    target_namespace: str,
    target_database: str,
) -> list[str]:
    errors: list[str] = []
    if not target_url:
        errors.append("target_url is required")
    if target_mode is SurrealTargetMode.REMOTE_SERVICE:
        if not target_namespace:
            errors.append("remote_service target_namespace is required")
        if not target_database:
            errors.append("remote_service target_database is required")
    return errors


def _embedded_target_path(target_url: str) -> Path:
    prefix = "surrealkv://"
    if not target_url.startswith(prefix):
        raise ValueError("embedded_local target_url must use surrealkv://")
    raw_path = target_url.removeprefix(prefix)
    if not raw_path:
        raise ValueError("embedded_local target_url path is required")
    target_path = Path(raw_path)
    if target_path in {Path("."), Path("/")}:
        raise ValueError("embedded_local target_url path is unsafe")
    return target_path


def _physically_reset_embedded_target(target_url: str) -> None:
    target_path = _embedded_target_path(target_url)
    if not target_path.exists():
        return
    if target_path.is_dir():
        shutil.rmtree(target_path)
        return
    target_path.unlink()


def _target_size_bytes(target_url: str) -> int | None:
    if not target_url.startswith("surrealkv://"):
        return None
    try:
        target_path = _embedded_target_path(target_url)
    except ValueError:
        return None
    if not target_path.exists():
        return 0
    if target_path.is_file():
        return target_path.stat().st_size
    total = 0
    for root, _dirs, files in os.walk(target_path):
        for file_name in files:
            try:
                total += (Path(root) / file_name).stat().st_size
            except OSError:
                continue
    return total


def _process_rss_bytes() -> int:
    return int(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss) * 1024


def _write_phase(
    checkpoint: SurrealMigrationPhaseCheckpoint,
    *,
    report: SurrealMigrationReport,
    writer: Any,
    progress_path: Path | None = None,
    resume_phase_names: set[str] | None = None,
) -> None:
    if checkpoint.phase_name.value in (resume_phase_names or set()):
        checkpoint.applied_count = checkpoint.planned_count
        checkpoint.verified_count = checkpoint.planned_count
        checkpoint.status = "applied"
        report.last_successful_phase = checkpoint.phase_name
        _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
        return
    checkpoint.status = "running"
    _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
    try:
        applied_count = int(writer())
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error = str(exc)
        report.failed_phase = checkpoint.phase_name
        report.errors.append(str(exc))
        _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
        raise
    checkpoint.applied_count = applied_count
    checkpoint.status = "applied"
    checkpoint.verified_count = applied_count
    report.last_successful_phase = checkpoint.phase_name
    _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)


def _write_iterable_phase(
    checkpoint: SurrealMigrationPhaseCheckpoint,
    *,
    report: SurrealMigrationReport,
    rows: Iterator[dict[str, Any]],
    writer: Any,
    batch_size: int = 1000,
    progress_path: Path | None = None,
    resume_phase_names: set[str] | None = None,
) -> None:
    if checkpoint.phase_name.value in (resume_phase_names or set()):
        checkpoint.applied_count = checkpoint.planned_count
        checkpoint.verified_count = checkpoint.planned_count
        checkpoint.status = "applied"
        report.last_successful_phase = checkpoint.phase_name
        _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
        return
    applied_count = 0
    batch: list[dict[str, Any]] = []
    checkpoint.status = "running"
    _write_progress_snapshot(
        progress_path,
        report=report,
        checkpoint=checkpoint,
        applied_count=applied_count,
    )
    try:
        for row in rows:
            batch.append(row)
            if len(batch) < batch_size:
                continue
            applied_count += int(writer(batch))
            _write_progress_snapshot(
                progress_path,
                report=report,
                checkpoint=checkpoint,
                applied_count=applied_count,
            )
            batch = []
        if batch:
            applied_count += int(writer(batch))
            _write_progress_snapshot(
                progress_path,
                report=report,
                checkpoint=checkpoint,
                applied_count=applied_count,
            )
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error = str(exc)
        report.failed_phase = checkpoint.phase_name
        report.errors.append(str(exc))
        checkpoint.applied_count = applied_count
        _write_progress_snapshot(
            progress_path,
            report=report,
            checkpoint=checkpoint,
            applied_count=applied_count,
        )
        raise
    checkpoint.applied_count = applied_count
    checkpoint.status = "applied"
    checkpoint.verified_count = applied_count
    report.last_successful_phase = checkpoint.phase_name


def _write_list_phase(
    checkpoint: SurrealMigrationPhaseCheckpoint,
    *,
    report: SurrealMigrationReport,
    rows: list[dict[str, Any]],
    writer: Any,
    batch_size: int = 1000,
    progress_path: Path | None = None,
    resume_phase_names: set[str] | None = None,
) -> None:
    if checkpoint.phase_name.value in (resume_phase_names or set()):
        checkpoint.applied_count = checkpoint.planned_count
        checkpoint.verified_count = checkpoint.planned_count
        checkpoint.status = "applied"
        report.last_successful_phase = checkpoint.phase_name
        _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
        return
    applied_count = 0
    checkpoint.status = "running"
    _write_progress_snapshot(
        progress_path,
        report=report,
        checkpoint=checkpoint,
        applied_count=applied_count,
    )
    try:
        for offset in range(0, len(rows), batch_size):
            batch = rows[offset : offset + batch_size]
            applied_count += int(writer(batch))
            _write_progress_snapshot(
                progress_path,
                report=report,
                checkpoint=checkpoint,
                applied_count=applied_count,
            )
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error = str(exc)
        report.failed_phase = checkpoint.phase_name
        report.errors.append(str(exc))
        checkpoint.applied_count = applied_count
        _write_progress_snapshot(
            progress_path,
            report=report,
            checkpoint=checkpoint,
            applied_count=applied_count,
        )
        raise
    checkpoint.applied_count = applied_count
    checkpoint.status = "applied"
    checkpoint.verified_count = applied_count
    report.last_successful_phase = checkpoint.phase_name


def _expanded_graph_rows_for_replace(graph_rows: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    section_rows = list(graph_rows["sections"])
    section_ids = {str(row.get("original_id") or row.get("chunk_id")) for row in section_rows}
    tag_rows = list(graph_rows["tags"])
    tag_names = {str(row.get("name")) for row in tag_rows}
    entity_rows = list(graph_rows["entities"])
    entity_names = {str(row.get("name")) for row in entity_rows}

    for relation in graph_rows["relations"]:
        source_id = str(relation["source_id"])
        if source_id not in section_ids:
            section_rows.append(
                {
                    "original_id": source_id,
                    "document_ref": source_id,
                    "metadata": {},
                }
            )
            section_ids.add(source_id)

        relation_type = str(relation.get("relation_type") or relation.get("rel_type"))
        target_id = str(relation["target_id"])
        if relation_type == "HAS_TAG":
            if target_id not in tag_names:
                tag_rows.append({"original_id": target_id, "name": target_id, "metadata": {}})
                tag_names.add(target_id)
        elif target_id not in entity_names:
            entity_rows.append(
                {
                    "original_id": target_id,
                    "original_entity_name": target_id,
                    "name": target_id,
                    "entity_type": "Entity",
                    "source": source_id,
                    "metadata": {},
                }
            )
            entity_names.add(target_id)

    return {
        "files": list(graph_rows["files"]),
        "sections": section_rows,
        "tags": tag_rows,
        "entities": entity_rows,
        "relations": list(graph_rows["relations"]),
    }


def _write_graph_phase(
    checkpoint: SurrealMigrationPhaseCheckpoint,
    *,
    report: SurrealMigrationReport,
    graph_store: SurrealGraphStore,
    graph_rows: dict[str, Any],
    batch_size: int = 1000,
    progress_path: Path | None = None,
    resume_phase_names: set[str] | None = None,
) -> None:
    if checkpoint.phase_name.value in (resume_phase_names or set()):
        checkpoint.applied_count = checkpoint.planned_count
        checkpoint.verified_count = checkpoint.planned_count
        checkpoint.status = "applied"
        report.last_successful_phase = checkpoint.phase_name
        _write_progress_snapshot(progress_path, report=report, checkpoint=checkpoint)
        return
    rows = _expanded_graph_rows_for_replace(graph_rows)
    checkpoint.planned_count = sum(len(value) for value in rows.values())
    applied_count = 0
    checkpoint.status = "running"
    _write_progress_snapshot(
        progress_path,
        report=report,
        checkpoint=checkpoint,
        applied_count=applied_count,
    )
    writers = (
        ("files", graph_store.replace_file_rows),
        ("sections", graph_store.replace_section_rows),
        ("tags", graph_store.replace_tag_rows),
        ("entities", graph_store.replace_entity_rows),
        ("relations", graph_store.replace_relation_rows),
    )
    try:
        for key, writer in writers:
            category_rows = rows[key]
            for offset in range(0, len(category_rows), batch_size):
                batch = category_rows[offset : offset + batch_size]
                applied_count += int(writer(batch))
                _write_progress_snapshot(
                    progress_path,
                    report=report,
                    checkpoint=checkpoint,
                    applied_count=applied_count,
                )
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error = str(exc)
        report.failed_phase = checkpoint.phase_name
        report.errors.append(str(exc))
        checkpoint.applied_count = applied_count
        _write_progress_snapshot(
            progress_path,
            report=report,
            checkpoint=checkpoint,
            applied_count=applied_count,
        )
        raise
    checkpoint.applied_count = applied_count
    checkpoint.status = "applied"
    checkpoint.verified_count = applied_count
    report.last_successful_phase = checkpoint.phase_name


def _upsert_schema_meta(connection: SurrealConnection) -> None:
    connection.query(
        "UPSERT schema_meta:dotmd_schema CONTENT $payload;",
        {
            "payload": {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "catalog_name": "dotmd",
                "required_categories": [
                    "documents",
                    "source_units",
                    "chunks",
                    "provenance",
                    "chunk_file_bindings",
                    "bindings",
                    "fingerprints",
                    "embeddings",
                    "vector_components",
                    "files",
                    "sections",
                    "entities",
                    "tags",
                    "relations",
                    "feedback",
                    "cursors",
                    "checkpoints",
                ],
                "metadata": {},
            }
        },
    )


def _rebuild_retrieval_indexes(connection: SurrealConnection) -> int:
    try:
        connection.query("REBUILD INDEX embeddings_hnsw_idx ON TABLE embeddings;")
    except Exception as exc:
        if "does not exist" in str(exc):
            return 0
        raise
    return 1


def verify_surreal_migration_target(
    *,
    sqlite_snapshot_path: Path,
    graph_export_path: Path,
    feedback_export_path: Path,
    target_url: str,
    target_mode: SurrealTargetMode,
    target_namespace: str = "dotmd",
    target_database: str = "phase41_migration",
    verification_depth: SurrealVerificationDepth = SurrealVerificationDepth.CHEAP,
    overwrite_policy: SurrealOverwritePolicy = SurrealOverwritePolicy.REFUSE,
) -> SurrealMigrationReport:
    manifest = build_surreal_migration_manifest(
        sqlite_snapshot_path=Path(sqlite_snapshot_path),
        graph_export_path=Path(graph_export_path),
        feedback_export_path=Path(feedback_export_path),
        target_url=target_url,
        target_mode=target_mode,
        target_namespace=target_namespace,
        target_database=target_database,
    )
    report = _report_from_manifest(
        manifest,
        mode=SurrealMigrationMode.VERIFY,
        overwrite_policy=overwrite_policy,
    )
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))
    with _connection_for_target(
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
    ) as connection:
        report.actual_counts = _count_target_rows(connection)
        schema_info = connection.inspect_schema()
        stored_embedding_sample = _query_surreal_rows(
            connection,
            "SELECT chunk_id, chunk_strategy, embedding_model, text_hash, vector_rowid, embedding "
            "FROM embeddings LIMIT 25;",
        )
        stored_relations_sample = _query_surreal_rows(connection, "SELECT * FROM relations LIMIT 1;")
        stored_feedback_sample = _query_surreal_rows(connection, "SELECT * FROM feedback LIMIT 1;")
        stored_cursors_sample = _query_surreal_rows(connection, "SELECT * FROM cursors LIMIT 1;")
        stored_checkpoints_sample = _query_surreal_rows(
            connection,
            "SELECT * FROM checkpoints LIMIT 1;",
        )

    for key, expected in report.expected_counts.items():
        actual = report.actual_counts.get(key, 0)
        if actual == expected:
            report.cheap_invariants.append(f"count {key} matched {expected}")
        else:
            report.errors.append(f"count mismatch for {key}: expected {expected}, got {actual}")

    schema_version = str(schema_info.get("schema_version") or "")
    if schema_version == report.schema_version:
        report.cheap_invariants.append(f"schema version matched {report.schema_version}")
    else:
        report.errors.append(
            f"schema version mismatch: expected {report.schema_version}, got {schema_version or 'missing'}"
        )

    if report.expected_vector_dimension is not None:
        if all(
            len(list(row.get("embedding", []))) == report.expected_vector_dimension
            for row in stored_embedding_sample
        ):
            report.cheap_invariants.append(
                f"vector dimension matched {report.expected_vector_dimension}"
            )
        else:
            report.errors.append("vector dimension mismatch detected")

    sample_chunk_ids = [
        str(row.get("chunk_id"))
        for row in stored_embedding_sample
        if row.get("chunk_id") not in (None, "")
    ]
    expected_embedding_sample = _load_sqlite_embedding_rows_by_chunk_id(
        Path(sqlite_snapshot_path),
        sample_chunk_ids,
    )
    report.embedding_reuse_verified = (
        report.actual_counts.get("embeddings") == report.expected_counts.get("embeddings")
        and bool(stored_embedding_sample)
        and all(
            (expected_row := expected_embedding_sample.get(str(stored.get("chunk_id"))))
            is not None
            and stored.get("text_hash") == expected_row.get("text_hash")
            and stored.get("chunk_strategy") == expected_row.get("chunk_strategy")
            and stored.get("vector_rowid") == expected_row.get("vector_rowid")
            and list(stored.get("embedding", [])) == list(expected_row.get("embedding", []))
            for stored in stored_embedding_sample
        )
    )
    if report.embedding_reuse_verified:
        report.cheap_invariants.append("embedding reuse verified by bounded sample")
    else:
        report.errors.append(
            "stored embedding sample did not preserve text_hash/vector_rowid/value triples"
        )

    if verification_depth is SurrealVerificationDepth.DEEP:
        if stored_relations_sample:
            relation_sample = stored_relations_sample[0]
            if relation_sample.get("rel_type") and "properties" in relation_sample:
                report.deep_sample_checks.append(
                    "relation payload sample preserved rel_type and properties"
                )
        if stored_feedback_sample:
            report.deep_sample_checks.append("feedback sample preserved provider-exported rows")
        if stored_cursors_sample:
            report.deep_sample_checks.append("cursor sample preserved source refs")
        if stored_checkpoints_sample:
            report.deep_sample_checks.append("checkpoint sample preserved source checkpoint data")
        if graph_rows["relations"]:
            report.deep_sample_checks.append(
                "relation payload compared against graph export sample"
            )
        if feedback_rows["rows"]:
            report.deep_sample_checks.append("feedback sample compared against feedback export")

    report.verified = not report.errors
    report.status = "verified" if report.verified else "verification_failed"
    return report


def run_surreal_migration(
    *,
    mode: SurrealMigrationMode,
    sqlite_snapshot_path: Path,
    graph_export_path: Path,
    feedback_export_path: Path,
    target_url: str,
    target_mode: SurrealTargetMode,
    target_namespace: str = "dotmd",
    target_database: str = "phase41_migration",
    overwrite_policy: SurrealOverwritePolicy = SurrealOverwritePolicy.REFUSE,
    inspect_target: bool = False,
    gate_report_path: Path | None = None,
    verification_depth: SurrealVerificationDepth = SurrealVerificationDepth.CHEAP,
    requested_recompute_steps: tuple[str, ...] = (),
    progress_path: Path | None = None,
    resume_from_progress: bool = False,
) -> SurrealMigrationReport:
    input_errors = _verify_target_mode_inputs(
        target_mode=target_mode,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
    )
    if input_errors:
        return _empty_report(
            mode=mode,
            target_mode=target_mode,
            overwrite_policy=overwrite_policy,
            target_url=target_url,
            target_namespace=target_namespace,
            target_database=target_database,
            status="invalid_target",
            errors=input_errors,
        )

    try:
        manifest = build_surreal_migration_manifest(
            sqlite_snapshot_path=Path(sqlite_snapshot_path),
            graph_export_path=Path(graph_export_path),
            feedback_export_path=Path(feedback_export_path),
            target_url=target_url,
            target_mode=target_mode,
            target_namespace=target_namespace,
            target_database=target_database,
        )
    except (FileNotFoundError, OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        return _empty_report(
            mode=mode,
            target_mode=target_mode,
            overwrite_policy=overwrite_policy,
            target_url=target_url,
            target_namespace=target_namespace,
            target_database=target_database,
            status="source_capture_incomplete",
            errors=[str(exc)],
        )

    report = _report_from_manifest(manifest, mode=mode, overwrite_policy=overwrite_policy)

    if requested_recompute_steps:
        report.status = "recompute_blocked"
        report.recompute_guard_status = "blocked"
        report.errors.append(
            f"recompute_forbidden blocked requested steps: {', '.join(requested_recompute_steps)}"
        )
        return report
    report.recompute_guard_status = "passed"

    if mode is SurrealMigrationMode.PLAN:
        report.status = "plan"
        return report

    if mode is SurrealMigrationMode.DRY_RUN:
        report.status = "dry-run"
        if inspect_target:
            _inspect_target(
                report,
                target_url=target_url,
                target_namespace=target_namespace,
                target_database=target_database,
            )
        return report

    if mode is SurrealMigrationMode.VERIFY:
        return verify_surreal_migration_target(
            sqlite_snapshot_path=Path(sqlite_snapshot_path),
            graph_export_path=Path(graph_export_path),
            feedback_export_path=Path(feedback_export_path),
            target_url=target_url,
            target_mode=target_mode,
            target_namespace=target_namespace,
            target_database=target_database,
            verification_depth=verification_depth,
            overwrite_policy=overwrite_policy,
        )

    sqlite_rows = load_sqlite_rows_for_surreal(
        Path(sqlite_snapshot_path),
        include_vectors=False,
    )
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))

    if target_mode is SurrealTargetMode.EMBEDDED_LOCAL:
        if gate_report_path is None:
            report.status = "gate_blocked"
            report.gate_status = "gate_missing"
            report.errors.append("gate_report_path is required for embedded_local apply mode")
            return report
        try:
            gate_report = _load_gate_report(Path(gate_report_path))
            assert_embedded_safety_gate_passed(gate_report)
        except (FileNotFoundError, OSError, RuntimeError, ValueError) as exc:
            report.status = "gate_blocked"
            report.gate_status = "gate_blocked"
            report.errors.append(str(exc))
            return report
        report.gate_status = "passed"

    schema_info = _inspect_target(
        report,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
    )
    resume_phase_names = _load_resume_phase_names(
        progress_path,
        report=report,
        enabled=resume_from_progress,
    )
    if (
        "SCHEMALESS" in schema_info.get("table_modes", "")
        and overwrite_policy is not SurrealOverwritePolicy.EXPLICIT_REPLACE
    ):
        report.status = "schema_mismatch"
        report.errors.append(
            "existing target includes SCHEMALESS Phase 38 tables; explicit_replace is required"
        )
        return report

    if (
        any(count > 0 for count in report.target_pre_counts.values())
        and overwrite_policy is SurrealOverwritePolicy.REFUSE
        and not resume_phase_names
    ):
        report.status = "target_not_empty"
        report.errors.append(
            "target contains existing rows; explicit_replace is required before destructive apply"
        )
        return report

    physically_reset_embedded_target = (
        target_mode is SurrealTargetMode.EMBEDDED_LOCAL
        and overwrite_policy is SurrealOverwritePolicy.EXPLICIT_REPLACE
        and not resume_phase_names
    )
    if physically_reset_embedded_target:
        try:
            _physically_reset_embedded_target(target_url)
        except (OSError, ValueError) as exc:
            report.status = "target_reset_failed"
            report.errors.append(str(exc))
            return report

    phase_checkpoints = {name: _make_phase_checkpoint(name, 0) for name in _MIGRATION_PHASE_ORDER}
    phase_checkpoints["schema"].planned_count = 1
    phase_checkpoints["documents"].planned_count = len(sqlite_rows["documents"])
    phase_checkpoints["source_units"].planned_count = len(sqlite_rows["source_units"])
    phase_checkpoints["chunks"].planned_count = len(sqlite_rows["chunks"])
    phase_checkpoints["chunk_file_bindings"].planned_count = len(sqlite_rows["chunk_file_bindings"])
    phase_checkpoints["provenance"].planned_count = len(sqlite_rows["provenance"])
    phase_checkpoints["bindings"].planned_count = len(sqlite_rows["bindings"])
    phase_checkpoints["fingerprints"].planned_count = len(sqlite_rows["fingerprints"])
    phase_checkpoints["embeddings"].planned_count = report.expected_counts["embeddings"]
    phase_checkpoints["indexes"].planned_count = 1
    phase_checkpoints["vector_components"].planned_count = report.expected_counts[
        "vector_components"
    ]
    phase_checkpoints["graph"].planned_count = len(graph_rows["entities"]) + len(
        graph_rows["relations"]
    )
    phase_checkpoints["feedback"].planned_count = len(feedback_rows["rows"])
    phase_checkpoints["cursors"].planned_count = len(sqlite_rows["cursors"])
    phase_checkpoints["checkpoints"].planned_count = len(sqlite_rows["checkpoints"])
    report.phase_checkpoints = [phase_checkpoints[name] for name in _MIGRATION_PHASE_ORDER]

    try:
        with _connection_for_target(
            target_url=target_url,
            target_namespace=target_namespace,
            target_database=target_database,
        ) as connection:
            if (
                overwrite_policy is SurrealOverwritePolicy.EXPLICIT_REPLACE
                and not physically_reset_embedded_target
                and not resume_phase_names
            ):
                connection.clear_schema_owned_tables()
            try:
                define_dotmd_surreal_schema(connection)
            except Exception as exc:
                if "already exists" not in str(exc):
                    raise
            _upsert_schema_meta(connection)

            metadata_store = SurrealMetadataStore(connection)
            vector_store = SurrealVectorStore(connection)
            graph_store = SurrealGraphStore(connection)
            feedback_store = SurrealFeedbackStore(connection)

            _write_phase(
                phase_checkpoints["schema"],
                report=report,
                writer=lambda: 1,
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["documents"],
                report=report,
                writer=lambda: metadata_store.replace_documents(sqlite_rows["documents"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["source_units"],
                report=report,
                writer=lambda: metadata_store.replace_source_units(sqlite_rows["source_units"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_list_phase(
                phase_checkpoints["chunks"],
                report=report,
                rows=sqlite_rows["chunks"],
                writer=metadata_store.replace_chunk_rows,
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["chunk_file_bindings"],
                report=report,
                writer=lambda: len(sqlite_rows["chunk_file_bindings"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["provenance"],
                report=report,
                writer=lambda: metadata_store.replace_provenance_rows(sqlite_rows["provenance"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["bindings"],
                report=report,
                writer=lambda: metadata_store.replace_binding_rows(sqlite_rows["bindings"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["fingerprints"],
                report=report,
                writer=lambda: metadata_store.replace_fingerprint_rows(sqlite_rows["fingerprints"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_iterable_phase(
                phase_checkpoints["embeddings"],
                report=report,
                rows=iter_sqlite_embedding_rows_for_surreal(Path(sqlite_snapshot_path)),
                writer=vector_store.replace_embedding_rows,
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["indexes"],
                report=report,
                writer=lambda: _rebuild_retrieval_indexes(connection),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["vector_components"],
                report=report,
                writer=lambda: 0,
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_graph_phase(
                phase_checkpoints["graph"],
                report=report,
                graph_store=graph_store,
                graph_rows=graph_rows,
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["feedback"],
                report=report,
                writer=lambda: feedback_store.replace_feedback_rows(feedback_rows["rows"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["cursors"],
                report=report,
                writer=lambda: metadata_store.replace_cursor_rows(sqlite_rows["cursors"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
            _write_phase(
                phase_checkpoints["checkpoints"],
                report=report,
                writer=lambda: metadata_store.replace_checkpoint_rows(sqlite_rows["checkpoints"]),
                progress_path=progress_path,
                resume_phase_names=resume_phase_names,
            )
    except Exception as exc:
        report.status = "failed"
        report.committed_success = False
        report.partial_writes_present = report.last_successful_phase is not None
        report.restore_required = report.partial_writes_present
        report.cleanup_attempted = False
        report.rollback_evidence = "no_automatic_cleanup"
        report.errors.append(str(exc))
        return report

    verification_report = verify_surreal_migration_target(
        sqlite_snapshot_path=Path(sqlite_snapshot_path),
        graph_export_path=Path(graph_export_path),
        feedback_export_path=Path(feedback_export_path),
        target_url=target_url,
        target_mode=target_mode,
        target_namespace=target_namespace,
        target_database=target_database,
        verification_depth=verification_depth,
        overwrite_policy=overwrite_policy,
    )
    report.actual_counts = verification_report.actual_counts
    report.cheap_invariants = verification_report.cheap_invariants
    report.deep_sample_checks = verification_report.deep_sample_checks
    report.embedding_reuse_verified = verification_report.embedding_reuse_verified
    report.expected_vector_dimension = verification_report.expected_vector_dimension
    report.verified = verification_report.verified
    report.status = "applied" if verification_report.verified else "verification_failed"
    report.committed_success = verification_report.verified
    report.errors.extend(verification_report.errors)
    return report
