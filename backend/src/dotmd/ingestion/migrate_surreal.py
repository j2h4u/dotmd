"""Transform-only SQLite/Falkor/feedback import helpers for Phase 38."""

from __future__ import annotations

import json
import re
import sqlite3
import struct
from dataclasses import dataclass, field
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

_SAFE_TABLE_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SurrealImportMode(StrEnum):
    """Supported import execution modes."""

    DRY_RUN = "dry-run"
    APPLY = "apply"


@dataclass(slots=True, frozen=True)
class SurrealImportCounts:
    """Row counts for the transform-only prototype."""

    documents: int = 0
    source_units: int = 0
    chunks: int = 0
    embeddings: int = 0
    vector_components: int = 0
    entities: int = 0
    relations: int = 0
    feedback: int = 0
    cursors: int = 0
    checkpoints: int = 0

    def total_records(self) -> int:
        return (
            self.documents
            + self.source_units
            + self.chunks
            + self.embeddings
            + self.vector_components
            + self.entities
            + self.relations
            + self.feedback
            + self.cursors
            + self.checkpoints
        )


@dataclass(slots=True)
class SurrealImportReport:
    """Outcome for one dry-run or apply invocation."""

    mode: SurrealImportMode
    counts: SurrealImportCounts
    status: str
    target_url: str | None
    committed: bool = False
    rolled_back: bool = False
    applied_records: int = 0
    gate_status: str = "not_required"
    unsupported_categories: list[str] = field(default_factory=list)
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


def load_sqlite_rows_for_surreal(sqlite_snapshot_path: Path) -> dict[str, Any]:
    """Load current SQLite rows as transform-only data records."""

    source_path = Path(sqlite_snapshot_path)
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)

        chunk_rows = {
            str(row["chunk_id"]): dict(row)
            for row in _fetch_all(conn, "chunks_contextual_512_50", known_tables)
        }
        provenance_rows = [
            dict(row)
            for row in _fetch_all(
                conn, "chunk_source_provenance_contextual_512_50", known_tables
            )
        ]
        file_path_rows = [
            dict(row)
            for row in _fetch_all(conn, "chunk_file_paths_contextual_512_50", known_tables)
        ]
        source_document_rows = [
            dict(row) for row in _fetch_all(conn, "source_documents", known_tables)
        ]
        binding_rows = [
            dict(row) for row in _fetch_all(conn, "resource_bindings", known_tables)
        ]
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

    file_paths_by_chunk: dict[str, list[str]] = {}
    for row in file_path_rows:
        file_paths_by_chunk.setdefault(str(row["chunk_id"]), []).append(str(row["file_path"]))

    provenance_by_chunk: dict[str, list[dict[str, Any]]] = {}
    for row in provenance_rows:
        chunk_id = str(row["chunk_id"])
        payload = {
            "provenance_id": f"{chunk_id}::{row['document_ref']}",
            "chunk_id": chunk_id,
            "namespace": str(row["namespace"]),
            "document_ref": str(row["document_ref"]),
            "source_unit_refs": _loads_json_list(row["source_unit_refs"]),
            "chunk_strategy": str(row["chunk_strategy"]),
            "parser_name": row["parser_name"],
        }
        provenance_by_chunk.setdefault(chunk_id, []).append(payload)

    chunk_payloads: list[dict[str, Any]] = []
    for chunk_id, row in chunk_rows.items():
        provenance_for_chunk = provenance_by_chunk.get(chunk_id, [])
        first_provenance = provenance_for_chunk[0] if provenance_for_chunk else {}
        document_ref = first_provenance.get("document_ref")
        namespace = first_provenance.get("namespace")
        chunk_payloads.append(
            {
                "original_chunk_id": chunk_id,
                "chunk_id": chunk_id,
                "heading_hierarchy": _loads_json_list(row["heading_hierarchy"]),
                "level": int(row["level"]),
                "text": str(row["text"]),
                "file_paths": list(file_paths_by_chunk.get(chunk_id, [])),
                "document_ref": document_ref,
                "ref": f"{namespace}:{document_ref}" if namespace and document_ref else None,
                "source_unit_refs": first_provenance.get("source_unit_refs", []),
            }
        )

    embedding_payloads: list[dict[str, Any]] = []
    for row in vec_meta_rows:
        vector_rowid = int(row["rowid"])
        vector_row = vec_chunk_rows.get(vector_rowid)
        embedding_payloads.append(
            {
                "chunk_id": str(row["chunk_id"]),
                "original_chunk_id": str(row["chunk_id"]),
                "text_hash": row["text_hash"],
                "vector_rowid": vector_rowid,
                "embedding": (
                    _decode_embedding_blob(vector_row["embedding"])
                    if vector_row is not None
                    else []
                ),
            }
        )

    vector_component_payloads = [
        {
            "entity_id": str(row["entity_id"]),
            "component": str(row["component"]),
            "embedding": _decode_embedding_blob(row["embedding"]),
        }
        for row in vec_component_rows
    ]

    fingerprint_payloads: list[dict[str, Any]] = []
    for row in chunk_fingerprint_rows:
        fingerprint_payloads.append(
            {
                "fingerprint_id": f"chunk::{row['file_path']}",
                "category": "chunk",
                **row,
            }
        )
    for row in embed_fingerprint_rows:
        fingerprint_payloads.append(
            {
                "fingerprint_id": f"embed::{row['chunk_id']}",
                "category": "embed",
                **row,
            }
        )
    for row in meta_fingerprint_rows:
        fingerprint_payloads.append(
            {
                "fingerprint_id": f"meta::{row['file_path']}",
                "category": "meta",
                **row,
            }
        )
    for row in source_unit_rows:
        fingerprint_payloads.append(
            {
                "fingerprint_id": f"source_unit::{row['document_ref']}::{row['unit_ref']}",
                "category": "source_unit",
                **row,
            }
        )

    cursor_rows = [
        {
            "original_ref": str(row["ref"]),
            "resource_ref": str(row["resource_ref"]),
            "document_ref": str(row["document_ref"]),
            "active": bool(row["active"]),
            "bound_at": row["bound_at"],
            "unbound_at": row["unbound_at"],
        }
        for row in binding_rows
    ]

    unsupported_categories = ["search_log"]

    return {
        "documents": source_document_rows,
        "source_units": source_unit_rows,
        "chunks": chunk_payloads,
        "provenance": [row for rows in provenance_by_chunk.values() for row in rows],
        "bindings": binding_rows,
        "fingerprints": fingerprint_payloads,
        "embeddings": embedding_payloads,
        "vector_components": vector_component_payloads,
        "cursors": cursor_rows,
        "checkpoints": checkpoint_rows,
        "unsupported_categories": unsupported_categories,
    }


def load_graph_rows_for_surreal(exporter: Any) -> dict[str, Any]:
    """Load graph entity and relation rows through the exporter abstraction."""

    inventory = exporter.export_inventory()
    rows = exporter.export_rows()
    return {
        "inventory": inventory,
        "entities": [dict(row) for row in rows.get("entities", [])],
        "relations": [dict(row) for row in rows.get("relations", [])],
    }


def load_feedback_rows_for_surreal(provider: Any) -> list[dict[str, Any]]:
    """Load feedback rows through the provider surface and never raw SQL."""

    rows = list(provider.list_all(limit=1000, include_closed=True))
    return [
        {
            "original_feedback_id": str(row["id"]),
            "submitted_at": row["submitted_at"],
            "message": row["message"],
            "severity": row.get("severity"),
            "status": row.get("status"),
            "context": row.get("context"),
            "model": row.get("model"),
        }
        for row in rows
    ]


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


def _build_counts(
    sqlite_rows: dict[str, Any],
    graph_rows: dict[str, Any],
    feedback_rows: list[dict[str, Any]],
) -> SurrealImportCounts:
    return SurrealImportCounts(
        documents=len(sqlite_rows["documents"]),
        source_units=len(sqlite_rows["source_units"]),
        chunks=len(sqlite_rows["chunks"]),
        embeddings=len(sqlite_rows["embeddings"]),
        vector_components=len(sqlite_rows["vector_components"]),
        entities=len(graph_rows["entities"]),
        relations=len(graph_rows["relations"]),
        feedback=len(feedback_rows),
        cursors=len(sqlite_rows["cursors"]),
        checkpoints=len(sqlite_rows["checkpoints"]),
    )


def run_surreal_import(
    *,
    mode: SurrealImportMode,
    sqlite_snapshot_path: Path,
    graph_exporter: Any,
    feedback_provider: Any,
    target_url: str,
    gate_report_path: Path | None = None,
) -> SurrealImportReport:
    """Run the transform-only import proof in dry-run or apply mode."""

    sqlite_rows = load_sqlite_rows_for_surreal(sqlite_snapshot_path)
    graph_rows = load_graph_rows_for_surreal(graph_exporter)
    feedback_rows = load_feedback_rows_for_surreal(feedback_provider)
    counts = _build_counts(sqlite_rows, graph_rows, feedback_rows)
    report = SurrealImportReport(
        mode=mode,
        counts=counts,
        status=mode.value,
        target_url=target_url,
        unsupported_categories=list(sqlite_rows["unsupported_categories"]),
    )

    if mode is SurrealImportMode.DRY_RUN:
        report.status = "dry-run"
        return report

    if gate_report_path is None:
        report.status = "gate_blocked"
        report.gate_status = "gate_missing"
        report.errors.append("gate_report_path is required for apply mode")
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
    config = SurrealStoreConfig(url=target_url)
    with SurrealConnection(config) as connection:
        define_dotmd_surreal_schema(connection)
        connection.clear_phase38_tables()
        metadata_store = SurrealMetadataStore(connection)
        vector_store = SurrealVectorStore(connection)
        graph_store = SurrealGraphStore(connection)
        feedback_store = SurrealFeedbackStore(connection)

        try:
            metadata_store.replace_documents(sqlite_rows["documents"])
            metadata_store.replace_source_units(sqlite_rows["source_units"])
            metadata_store.replace_chunk_rows(sqlite_rows["chunks"])
            metadata_store.replace_provenance_rows(sqlite_rows["provenance"])
            metadata_store.replace_binding_rows(sqlite_rows["bindings"])
            metadata_store.replace_fingerprint_rows(sqlite_rows["fingerprints"])
            metadata_store.replace_checkpoint_rows(sqlite_rows["checkpoints"])
            metadata_store.replace_cursor_rows(sqlite_rows["cursors"])
            vector_store.replace_embedding_rows(sqlite_rows["embeddings"])
            vector_store.replace_vector_component_rows(sqlite_rows["vector_components"])
            graph_store.replace_entity_rows(graph_rows["entities"])
            graph_store.replace_relation_rows(graph_rows["relations"])
            feedback_store.replace_feedback_rows(feedback_rows)
        except Exception as exc:
            connection.clear_phase38_tables()
            report.status = "rolled_back"
            report.rolled_back = True
            report.errors.append(str(exc))
            return report

    report.status = "committed"
    report.committed = True
    report.applied_records = counts.total_records()
    return report
