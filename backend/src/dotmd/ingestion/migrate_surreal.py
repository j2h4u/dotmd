"""Production migration runner for Phase 41 Surreal imports."""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import struct
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


def _sqlite_connect_read_only(db_path: Path) -> sqlite3.Connection:
    return sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)


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


def load_sqlite_rows_for_surreal(sqlite_snapshot_path: Path) -> dict[str, Any]:
    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)

        chunk_rows = {
            str(row["chunk_id"]): dict(row)
            for row in _fetch_all(conn, "chunks_contextual_512_50", known_tables)
        }
        provenance_rows = [
            dict(row)
            for row in _fetch_all(conn, "chunk_source_provenance_contextual_512_50", known_tables)
        ]
        file_path_rows = [
            dict(row)
            for row in _fetch_all(conn, "chunk_file_paths_contextual_512_50", known_tables)
        ]
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
        vec_meta_rows = [
            dict(row)
            for row in _fetch_all(
                conn, "vec_meta_contextual_512_50_multilingual_e5_large", known_tables
            )
        ]
        vec_chunk_rows = {
            int(row["rowid"]): dict(row)
            for row in _fetch_all(
                conn, "vec_chunks_contextual_512_50_multilingual_e5_large", known_tables
            )
        }
        vec_component_rows = [
            dict(row)
            for row in _fetch_all(
                conn, "vec_components_contextual_512_50_multilingual_e5_large", known_tables
            )
        ]
        vec_config_rows = [
            dict(row)
            for row in _fetch_all(
                conn, "vec_config_contextual_512_50_multilingual_e5_large", known_tables
            )
        ]
        chunk_fingerprint_rows = [
            dict(row)
            for row in _fetch_all(conn, "chunk_fingerprints_contextual_512_50", known_tables)
        ]
        embed_fingerprint_rows = [
            dict(row)
            for row in _fetch_all(
                conn,
                "embed_fingerprints_contextual_512_50_multilingual_e5_large",
                known_tables,
            )
        ]
        meta_fingerprint_rows = [
            dict(row)
            for row in _fetch_all(
                conn, "meta_fingerprints_contextual_512_50_multilingual_e5_large", known_tables
            )
        ]

    vec_config = {str(row["key"]): str(row["value"]) for row in vec_config_rows}
    vector_dimension = int(vec_config["dim"]) if "dim" in vec_config else None
    embedding_model = vec_config.get("model", "unknown-model")

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
        vector_row = vec_chunk_rows.get(vector_rowid)
        embedding_payloads.append(
            {
                "schema_version": SURREAL_SCHEMA_VERSION,
                "chunk_id": str(row["chunk_id"]),
                "original_chunk_id": str(row["chunk_id"]),
                "embedding_model": embedding_model,
                "text_hash": row["text_hash"],
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
            "fingerprint_id": f"embed::{row['chunk_id']}",
            "fingerprint_kind": "embed",
            "namespace": "filesystem",
            "document_ref": str(row["chunk_id"]),
            "content_fingerprint": str(row["fingerprint"]),
            "metadata_fingerprint": None,
            "metadata": {},
        }
        for row in embed_fingerprint_rows
    )
    fingerprint_payloads.extend(
        {
            "schema_version": SURREAL_SCHEMA_VERSION,
            "fingerprint_id": f"meta::{row['file_path']}",
            "fingerprint_kind": "meta",
            "namespace": "filesystem",
            "document_ref": str(row["file_path"]),
            "content_fingerprint": None,
            "metadata_fingerprint": str(row["meta_checksum"]),
            "metadata": {},
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
    derived_section_ids = {str(row["source_id"]) for row in graph_rows["relations"]}
    derived_tag_ids = {
        str(row["target_id"])
        for row in graph_rows["relations"]
        if str(row.get("relation_type") or row.get("rel_type")) == "HAS_TAG"
    }
    return {
        "documents": len(sqlite_rows["documents"]),
        "source_units": len(sqlite_rows["source_units"]),
        "chunks": len(sqlite_rows["chunks"]),
        "chunk_file_bindings": len(sqlite_rows["chunk_file_bindings"]),
        "provenance": len(sqlite_rows["provenance"]),
        "bindings": len(sqlite_rows["bindings"]),
        "fingerprints": len(sqlite_rows["fingerprints"]),
        "embeddings": len(sqlite_rows["embeddings"]),
        "vector_components": len(sqlite_rows["vector_components"]),
        "graph_files": len(graph_rows["files"]),
        "graph_sections": max(len(graph_rows["sections"]), len(derived_section_ids)),
        "graph_entities": len(graph_rows["entities"]),
        "graph_tags": max(len(graph_rows["tags"]), len(derived_tag_ids)),
        "graph_relations": len(graph_rows["relations"]),
        "feedback": len(feedback_rows["rows"]),
        "cursors": len(sqlite_rows["cursors"]),
        "checkpoints": len(sqlite_rows["checkpoints"]),
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
    sqlite_rows = load_sqlite_rows_for_surreal(Path(sqlite_snapshot_path))
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))
    return SurrealMigrationManifest(
        schema_version=SURREAL_SCHEMA_VERSION,
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
        target_mode=target_mode,
        source_capture_manifest=_build_source_capture_manifest(
            sqlite_snapshot_path=Path(sqlite_snapshot_path),
            sqlite_rows=sqlite_rows,
            graph_export_path=Path(graph_export_path),
            graph_rows=graph_rows,
            feedback_export_path=Path(feedback_export_path),
            feedback_rows=feedback_rows,
            skew_policy=skew_policy,
        ),
        expected_counts=_build_expected_counts(sqlite_rows, graph_rows, feedback_rows),
        unsupported_categories=list(_STABLE_UNSUPPORTED_CATEGORIES),
        recompute_forbidden=True,
        expected_vector_dimension=sqlite_rows["expected_vector_dimension"],
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
    return {
        "documents": len(connection.scan_table("documents")),
        "source_units": len(connection.scan_table("source_units")),
        "chunks": len(connection.scan_table("chunks")),
        "chunk_file_bindings": len(connection.scan_table("chunk_file_bindings")),
        "provenance": len(connection.scan_table("provenance")),
        "bindings": len(connection.scan_table("bindings")),
        "fingerprints": len(connection.scan_table("fingerprints")),
        "embeddings": len(connection.scan_table("embeddings")),
        "vector_components": len(connection.scan_table("vector_components")),
        "graph_files": len(connection.scan_table("files")),
        "graph_sections": len(connection.scan_table("sections")),
        "graph_entities": len(connection.scan_table("entities")),
        "graph_tags": len(connection.scan_table("tags")),
        "graph_relations": len(connection.scan_table("relations")),
        "feedback": len(connection.scan_table("feedback")),
        "cursors": len(connection.scan_table("cursors")),
        "checkpoints": len(connection.scan_table("checkpoints")),
    }


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


def _write_phase(
    checkpoint: SurrealMigrationPhaseCheckpoint,
    *,
    report: SurrealMigrationReport,
    writer: Any,
) -> None:
    try:
        applied_count = int(writer())
    except Exception as exc:
        checkpoint.status = "failed"
        checkpoint.error = str(exc)
        report.failed_phase = checkpoint.phase_name
        report.errors.append(str(exc))
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
    sqlite_rows = load_sqlite_rows_for_surreal(Path(sqlite_snapshot_path))
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))
    with _connection_for_target(
        target_url=target_url,
        target_namespace=target_namespace,
        target_database=target_database,
    ) as connection:
        report.actual_counts = _count_target_rows(connection)
        schema_info = connection.inspect_schema()
        stored_embeddings = connection.scan_table("embeddings")
        stored_relations = connection.scan_table("relations")
        stored_feedback = connection.scan_table("feedback")
        stored_cursors = connection.scan_table("cursors")
        stored_checkpoints = connection.scan_table("checkpoints")

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
            for row in stored_embeddings
        ):
            report.cheap_invariants.append(
                f"vector dimension matched {report.expected_vector_dimension}"
            )
        else:
            report.errors.append("vector dimension mismatch detected")

    expected_embeddings = {str(row["chunk_id"]): row for row in sqlite_rows["embeddings"]}
    report.embedding_reuse_verified = all(
        any(
            str(stored.get("chunk_id")) == chunk_id
            and stored.get("text_hash") == expected_row.get("text_hash")
            and stored.get("vector_rowid") == expected_row.get("vector_rowid")
            and list(stored.get("embedding", [])) == list(expected_row.get("embedding", []))
            for stored in stored_embeddings
        )
        for chunk_id, expected_row in expected_embeddings.items()
    )
    if report.embedding_reuse_verified:
        report.cheap_invariants.append("embedding reuse verified")
    else:
        report.errors.append(
            "stored embeddings did not preserve text_hash/vector_rowid/value triples"
        )

    if verification_depth is SurrealVerificationDepth.DEEP:
        if stored_relations:
            relation_sample = stored_relations[0]
            if relation_sample.get("rel_type") and "properties" in relation_sample:
                report.deep_sample_checks.append(
                    "relation payload sample preserved rel_type and properties"
                )
        if stored_feedback:
            report.deep_sample_checks.append("feedback sample preserved provider-exported rows")
        if stored_cursors:
            report.deep_sample_checks.append("cursor sample preserved source refs")
        if stored_checkpoints:
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
    sqlite_rows = load_sqlite_rows_for_surreal(Path(sqlite_snapshot_path))
    graph_rows = load_graph_rows_for_surreal(Path(graph_export_path))
    feedback_rows = load_feedback_rows_for_surreal(Path(feedback_export_path))

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
    ):
        report.status = "target_not_empty"
        report.errors.append(
            "target contains existing rows; explicit_replace is required before destructive apply"
        )
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
    phase_checkpoints["embeddings"].planned_count = len(sqlite_rows["embeddings"])
    phase_checkpoints["vector_components"].planned_count = len(sqlite_rows["vector_components"])
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
            if overwrite_policy is SurrealOverwritePolicy.EXPLICIT_REPLACE:
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

            _write_phase(phase_checkpoints["schema"], report=report, writer=lambda: 1)
            _write_phase(
                phase_checkpoints["documents"],
                report=report,
                writer=lambda: metadata_store.replace_documents(sqlite_rows["documents"]),
            )
            _write_phase(
                phase_checkpoints["source_units"],
                report=report,
                writer=lambda: metadata_store.replace_source_units(sqlite_rows["source_units"]),
            )
            _write_phase(
                phase_checkpoints["chunks"],
                report=report,
                writer=lambda: metadata_store.replace_chunk_rows(sqlite_rows["chunks"]),
            )
            _write_phase(
                phase_checkpoints["chunk_file_bindings"],
                report=report,
                writer=lambda: len(sqlite_rows["chunk_file_bindings"]),
            )
            _write_phase(
                phase_checkpoints["provenance"],
                report=report,
                writer=lambda: metadata_store.replace_provenance_rows(sqlite_rows["provenance"]),
            )
            _write_phase(
                phase_checkpoints["bindings"],
                report=report,
                writer=lambda: metadata_store.replace_binding_rows(sqlite_rows["bindings"]),
            )
            _write_phase(
                phase_checkpoints["fingerprints"],
                report=report,
                writer=lambda: metadata_store.replace_fingerprint_rows(sqlite_rows["fingerprints"]),
            )
            _write_phase(
                phase_checkpoints["embeddings"],
                report=report,
                writer=lambda: vector_store.replace_embedding_rows(sqlite_rows["embeddings"]),
            )
            _write_phase(
                phase_checkpoints["vector_components"],
                report=report,
                writer=lambda: vector_store.replace_vector_component_rows(
                    sqlite_rows["vector_components"]
                ),
            )
            _write_phase(
                phase_checkpoints["graph"],
                report=report,
                writer=lambda: graph_store.replace_graph_rows(
                    entities=graph_rows["entities"],
                    relations=graph_rows["relations"],
                    files=graph_rows["files"],
                    sections=graph_rows["sections"],
                    tags=graph_rows["tags"],
                ),
            )
            _write_phase(
                phase_checkpoints["feedback"],
                report=report,
                writer=lambda: feedback_store.replace_feedback_rows(feedback_rows["rows"]),
            )
            _write_phase(
                phase_checkpoints["cursors"],
                report=report,
                writer=lambda: metadata_store.replace_cursor_rows(sqlite_rows["cursors"]),
            )
            _write_phase(
                phase_checkpoints["checkpoints"],
                report=report,
                writer=lambda: metadata_store.replace_checkpoint_rows(sqlite_rows["checkpoints"]),
            )
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
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
