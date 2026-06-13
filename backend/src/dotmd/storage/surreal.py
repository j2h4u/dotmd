"""SurrealDB storage adapters and schema wiring for migration work."""

from __future__ import annotations

import base64
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

from surrealdb import RecordID, Surreal

from dotmd.core.models import Chunk, ChunkProvenance, IndexStats
from dotmd.storage.surreal_schema import (
    build_dotmd_surreal_schema_plan,
    define_dotmd_surreal_schema,
)

__all__ = (
    "SurrealConnection",
    "SurrealRecordIdCodec",
    "SurrealStoreConfig",
    "define_dotmd_surreal_schema",
)


def _urlsafe_encode(raw_identifier: str) -> str:
    encoded = base64.urlsafe_b64encode(raw_identifier.encode("utf-8")).decode("ascii")
    return "u8_" + encoded.rstrip("=")


def _urlsafe_decode(encoded_identifier: str) -> str:
    if not encoded_identifier.startswith("u8_"):
        raise ValueError("unsupported Surreal record identifier encoding")
    payload = encoded_identifier[3:]
    padding = "=" * (-len(payload) % 4)
    return base64.urlsafe_b64decode(payload + padding).decode("utf-8")


@dataclass(slots=True, frozen=True)
class SurrealStoreConfig:
    """Connection settings for the prototype store."""

    url: str
    namespace: str = "dotmd"
    database: str = "phase38_import"


class SurrealRecordIdCodec:
    """Central codec for safe Surreal record identifiers."""

    def encode(self, table_name: str, raw_identifier: str) -> RecordID:
        if not table_name:
            raise ValueError("table_name must not be empty")
        return RecordID(table_name, _urlsafe_encode(raw_identifier))

    def decode(self, record: RecordID | str) -> str:
        record_id = record if isinstance(record, RecordID) else RecordID.parse(record)
        return _urlsafe_decode(str(record_id.id))


def encode_surreal_record_id(table_name: str, raw_identifier: str) -> RecordID:
    """Encode a caller-owned identifier into a safe Surreal RecordID."""

    return SurrealRecordIdCodec().encode(table_name, raw_identifier)


def decode_surreal_record_id(record: RecordID | str) -> str:
    """Decode a Surreal RecordID created by :func:`encode_surreal_record_id`."""

    return SurrealRecordIdCodec().decode(record)


def _composite_id(*parts: object) -> str:
    return "\x1f".join(str(part) for part in parts)


def _schema_table_names() -> tuple[str, ...]:
    return tuple(table.name for table in build_dotmd_surreal_schema_plan().tables)


def _extract_table_mode(info: Any) -> str | None:
    if isinstance(info, dict):
        result = info.get("result")
        if isinstance(result, list) and result:
            return _extract_table_mode(result[0])
        if isinstance(result, dict):
            return _extract_table_mode(result)
        for key in ("schemafull", "kind"):
            value = info.get(key)
            if isinstance(value, bool):
                return "SCHEMAFULL" if value else "SCHEMALESS"
            if isinstance(value, str):
                upper_value = value.upper()
                if "RELATION" in upper_value:
                    return "RELATION"
                if upper_value in {"SCHEMAFULL", "SCHEMALESS"}:
                    return upper_value
        tables = info.get("tables")
        if isinstance(tables, dict):
            return _extract_table_mode(tables)
    if isinstance(info, list):
        for item in info:
            mode = _extract_table_mode(item)
            if mode is not None:
                return mode
    if isinstance(info, str):
        upper_value = info.upper()
        if "TYPE RELATION" in upper_value or "RELATION" in upper_value:
            return "RELATION"
        if "SCHEMAFULL" in upper_value:
            return "SCHEMAFULL"
        if "SCHEMALESS" in upper_value:
            return "SCHEMALESS"
    return None


class SurrealConnection:
    """Small connection wrapper that normalizes select/query behavior."""

    def __init__(self, config: SurrealStoreConfig) -> None:
        self.config = config
        self._db = cast(Any, Surreal(config.url))
        self._db.connect()
        self._db.use(config.namespace, config.database)

    def __enter__(self) -> SurrealConnection:
        return self

    def __exit__(self, _exc_type, _exc, _tb) -> None:  # type: ignore[no-untyped-def]
        self.close()

    @property
    def raw(self) -> Any:
        return self._db

    def close(self) -> None:
        self._db.close()

    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        return self._db.query(statement, variables)

    def query_raw(self, statement: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
        return self._db.query_raw(statement, variables)

    def create(self, record: RecordID | str, data: dict[str, Any]) -> Any:
        return self._db.create(record, data)

    def upsert(self, record: RecordID | str, data: dict[str, Any]) -> Any:
        return self._db.upsert(record, data)

    def delete(self, record: RecordID | str) -> Any:
        return self._db.delete(record)

    def select(self, record: RecordID | str) -> Any:
        selected = self._db.select(record)
        if isinstance(record, RecordID):
            if isinstance(selected, list):
                return selected[0] if selected else {}
            return selected
        return selected

    def scan_table(self, table_name: str) -> list[dict[str, Any]]:
        selected = self._db.select(table_name)
        if not isinstance(selected, list):
            return []
        return [dict(row) for row in selected if isinstance(row, dict)]

    def inspect_schema(self) -> dict[str, Any]:
        """Best-effort schema inspection for apply-status decisions."""

        meta_rows = self.scan_table("schema_meta")
        meta = meta_rows[0] if meta_rows else self.select("schema_meta:dotmd_schema")
        schema_version = None
        if isinstance(meta, dict):
            raw_version = meta.get("schema_version")
            if isinstance(raw_version, str):
                schema_version = raw_version

        table_modes: dict[str, str] = {}
        try:
            db_info = self.query_raw("INFO FOR DB;")
            raw_tables = {}
            if isinstance(db_info, dict):
                results = db_info.get("result")
                if isinstance(results, list) and results:
                    first = results[0]
                    if isinstance(first, dict):
                        inner = first.get("result")
                        if isinstance(inner, dict):
                            raw_tables = dict(inner.get("tables", {}))
            for table_name, definition in raw_tables.items():
                mode = _extract_table_mode(definition)
                if mode is not None:
                    table_modes[str(table_name)] = mode
        except Exception:  # pragma: no cover - best-effort fallback for different backends
            pass

        return {"schema_version": schema_version, "table_modes": table_modes}

    def delete_all_from_table(self, table_name: str) -> int:
        deleted = 0
        for row in self.scan_table(table_name):
            record = row.get("id")
            if record is None:
                continue
            self._db.delete(record)
            deleted += 1
        return deleted

    def clear_schema_owned_tables(self) -> int:
        deleted = 0
        for table_name in _schema_table_names():
            deleted += self.delete_all_from_table(table_name)
        return deleted

    def clear_phase38_tables(self) -> int:
        return self.clear_schema_owned_tables()


class SurrealMetadataStore:
    """Prototype metadata adapter that keeps existing method names."""

    def __init__(self, connection: SurrealConnection) -> None:
        self._connection = connection
        self._codec = SurrealRecordIdCodec()

    def save_chunks(self, chunks: list[Chunk]) -> None:
        for chunk in chunks:
            file_paths = [str(path) for path in chunk.file_paths]
            payload = {
                "original_chunk_id": chunk.chunk_id,
                "chunk_id": chunk.chunk_id,
                "heading_hierarchy": list(chunk.heading_hierarchy),
                "level": chunk.level,
                "text": chunk.text,
                "chunk_index": chunk.chunk_index,
                "file_paths": file_paths,
                "ref": chunk.provenance.ref if chunk.provenance is not None else None,
                "document_ref": (
                    chunk.provenance.document_ref if chunk.provenance is not None else None
                ),
                "source_unit_refs": (
                    list(chunk.provenance.source_unit_refs) if chunk.provenance is not None else []
                ),
            }
            self._connection.upsert(self._codec.encode("chunks", chunk.chunk_id), payload)

    def get_chunk(self, chunk_id: str) -> Chunk | None:
        stored = self._connection.select(self._codec.encode("chunks", chunk_id))
        if not stored:
            return None
        provenance = None
        ref = stored.get("ref")
        document_ref = stored.get("document_ref")
        if isinstance(ref, str) and isinstance(document_ref, str):
            provenance = ChunkProvenance(
                namespace=ref.split(":", 1)[0],
                document_ref=document_ref,
                ref=ref,
                source_unit_refs=list(stored.get("source_unit_refs", [])),
                chunk_strategy="contextual_512_50",
                parser_name="markdown",
            )
        return Chunk(
            chunk_id=str(stored["chunk_id"]),
            file_paths=[Path(path) for path in stored.get("file_paths", [])],
            heading_hierarchy=[str(item) for item in stored.get("heading_hierarchy", [])],
            level=int(stored.get("level", 0)),
            text=str(stored.get("text", "")),
            chunk_index=int(stored.get("chunk_index", 0)),
            provenance=provenance,
        )

    def get_chunks(self, chunk_ids: list[str]) -> list[Chunk]:
        result: list[Chunk] = []
        for chunk_id in chunk_ids:
            chunk = self.get_chunk(chunk_id)
            if chunk is not None:
                result.append(chunk)
        return result

    def get_all_chunks(self) -> list[Chunk]:
        result: list[Chunk] = []
        for row in self._connection.scan_table("chunks"):
            original_chunk_id = row.get("original_chunk_id")
            if isinstance(original_chunk_id, str):
                chunk = self.get_chunk(original_chunk_id)
                if chunk is not None:
                    result.append(chunk)
        return result

    def save_stats(self, stats: IndexStats) -> None:
        self._connection.upsert(
            self._codec.encode("stats", "latest"),
            {
                "total_files": stats.total_files,
                "total_chunks": stats.total_chunks,
                "total_entities": stats.total_entities,
                "total_edges": stats.total_edges,
                "last_indexed": stats.last_indexed.isoformat() if stats.last_indexed else None,
            },
        )

    def get_stats(self) -> IndexStats | None:
        stored = self._connection.select(self._codec.encode("stats", "latest"))
        if not stored:
            return None
        return IndexStats(
            total_files=int(stored.get("total_files", 0)),
            total_chunks=int(stored.get("total_chunks", 0)),
            total_entities=int(stored.get("total_entities", 0)),
            total_edges=int(stored.get("total_edges", 0)),
            last_indexed=stored.get("last_indexed"),
        )

    def get_chunk_ids_by_file(self, file_path: str) -> list[str]:
        rows = [
            row
            for row in self._connection.scan_table("chunk_file_bindings")
            if row.get("file_path") == file_path
        ]
        rows.sort(key=lambda row: int(row.get("chunk_index", 0)))
        return [str(row["chunk_id"]) for row in rows]

    def delete_chunks_by_file(self, file_path: str) -> int:
        deleted = 0
        for chunk_id in self.get_chunk_ids_by_file(file_path):
            self._connection.delete(self._codec.encode("chunks", chunk_id))
            deleted += 1
        return deleted

    def delete_all(self) -> None:
        for table_name in (
            "chunks",
            "chunk_file_bindings",
            "documents",
            "source_units",
            "provenance",
            "bindings",
            "fingerprints",
            "cursors",
            "checkpoints",
            "stats",
        ):
            self._connection.delete_all_from_table(table_name)

    def replace_documents(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("documents", str(row["ref"])),
                dict(row),
            )
        return len(rows)

    def replace_source_units(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode(
                    "source_units",
                    _composite_id(row["namespace"], row["document_ref"], row["unit_ref"]),
                ),
                dict(row),
            )
        return len(rows)

    def replace_provenance_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("provenance", str(row["provenance_id"])),
                dict(row),
            )
        return len(rows)

    def replace_chunk_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            payload = dict(row)
            file_bindings = list(payload.pop("file_bindings", []))
            self._connection.upsert(
                self._codec.encode("chunks", str(payload["chunk_id"])),
                payload,
            )
            for binding in file_bindings:
                binding_payload = dict(binding)
                binding_id = _composite_id(
                    binding_payload["chunk_id"],
                    binding_payload["file_path"],
                    binding_payload["chunk_index"],
                )
                self._connection.upsert(
                    self._codec.encode("chunk_file_bindings", binding_id),
                    binding_payload,
                )
        return len(rows)

    def replace_binding_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode(
                    "bindings", _composite_id(row["namespace"], row["resource_ref"])
                ),
                dict(row),
            )
        return len(rows)

    def replace_fingerprint_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("fingerprints", str(row["fingerprint_id"])),
                dict(row),
            )
        return len(rows)

    def replace_checkpoint_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("checkpoints", str(row["namespace"])),
                dict(row),
            )
        return len(rows)

    def replace_cursor_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("cursors", str(row["ref"])),
                dict(row),
            )
        return len(rows)


class SurrealVectorStore:
    """Prototype vector adapter that treats imported embeddings as data."""

    def __init__(self, connection: SurrealConnection) -> None:
        self._connection = connection
        self._codec = SurrealRecordIdCodec()

    def add_chunks(
        self,
        chunks: list[Chunk],
        embeddings: list[list[float]],
        *,
        overwrite: bool = True,
        text_hashes: dict[str, str] | None = None,
    ) -> None:
        if overwrite:
            self._connection.delete_all_from_table("embeddings")
        for chunk, embedding in zip(chunks, embeddings, strict=False):
            payload = {
                "chunk_id": chunk.chunk_id,
                "original_chunk_id": chunk.chunk_id,
                "text_hash": text_hashes.get(chunk.chunk_id) if text_hashes else None,
                "vector_rowid": None,
                "embedding": list(embedding),
            }
            self._connection.upsert(self._codec.encode("embeddings", chunk.chunk_id), payload)

    def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
        scored: list[tuple[str, float]] = []
        for row in self._connection.scan_table("embeddings"):
            embedding = [float(value) for value in row.get("embedding", [])]
            if not embedding:
                continue
            score = _cosine_similarity(query_embedding, embedding)
            scored.append((str(row["chunk_id"]), score))
        scored.sort(key=lambda item: item[1], reverse=True)
        return scored[:top_k]

    def delete_all(self) -> None:
        self._connection.delete_all_from_table("embeddings")
        self._connection.delete_all_from_table("vector_components")

    def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
        deleted = 0
        for chunk_id in chunk_ids:
            existing = self._connection.select(self._codec.encode("embeddings", chunk_id))
            if existing:
                self._connection.delete(self._codec.encode("embeddings", chunk_id))
                deleted += 1
        return deleted

    def count(self) -> int:
        return len(self._connection.scan_table("embeddings"))

    def lookup_embeddings_by_text_hash(self, text_hashes: list[str]) -> dict[str, list[float]]:
        if not text_hashes:
            return {}
        result: dict[str, list[float]] = {}
        for row in self._connection.scan_table("embeddings"):
            text_hash = row.get("text_hash")
            if isinstance(text_hash, str) and text_hash in text_hashes:
                result[text_hash] = [float(value) for value in row.get("embedding", [])]
        return result

    def replace_embedding_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            self._connection.upsert(
                self._codec.encode("embeddings", str(row["chunk_id"])),
                dict(row),
            )
        return len(rows)

    def replace_vector_component_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            component_owner = row.get("chunk_id") or row.get("entity_id")
            component_id = f"{component_owner}::{row['component']}"
            self._connection.upsert(
                self._codec.encode("vector_components", component_id),
                dict(row),
            )
        return len(rows)


class SurrealGraphStore:
    """Prototype graph adapter with bounded graph-direct semantics."""

    def __init__(self, connection: SurrealConnection) -> None:
        self._connection = connection
        self._codec = SurrealRecordIdCodec()

    def add_file_node(self, file_path: str, title: str) -> None:
        self._connection.upsert(
            self._codec.encode("files", file_path),
            {"file_path": file_path, "title": title},
        )

    def add_section_node(
        self,
        chunk_id: str,
        heading: str,
        level: int,
        file_path: str,
        text_preview: str,
    ) -> None:
        self._connection.upsert(
            self._codec.encode("sections", chunk_id),
            {
                "chunk_id": chunk_id,
                "heading": heading,
                "level": level,
                "file_path": file_path,
                "text_preview": text_preview,
            },
        )

    def add_entity_node(self, name: str, entity_type: str, source: str) -> None:
        self._connection.upsert(
            self._codec.encode("entities", name),
            {
                "name": name,
                "original_entity_name": name,
                "entity_type": entity_type,
                "source": source,
            },
        )

    def add_tag_node(self, name: str) -> None:
        self._connection.upsert(
            self._codec.encode("tags", name),
            {"name": name},
        )

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        relation_type: str,
        weight: float = 1.0,
    ) -> None:
        relation_id = f"{source_id}->{relation_type}->{target_id}"
        self._connection.upsert(
            self._codec.encode("relations", relation_id),
            {
                "relation_id": relation_id,
                "source_id": source_id,
                "target_id": target_id,
                "relation_type": relation_type,
                "weight": weight,
                "properties": {},
            },
        )

    def batch_add_section_nodes(self, sections: list[dict[str, Any]]) -> None:
        for row in sections:
            self.add_section_node(
                chunk_id=str(row["chunk_id"]),
                heading=str(row["heading"]),
                level=int(row["level"]),
                file_path=str(row["file_path"]),
                text_preview=str(row["text_preview"]),
            )

    def batch_add_entity_nodes(self, entities: list[dict[str, Any]]) -> None:
        for row in entities:
            self.add_entity_node(
                name=str(row["name"]),
                entity_type=str(row["entity_type"]),
                source=str(row["source"]),
            )

    def batch_add_tag_nodes(self, tags: list[str]) -> None:
        for tag in tags:
            self.add_tag_node(tag)

    def batch_add_file_nodes(self, files: list[dict[str, Any]]) -> None:
        for row in files:
            self.add_file_node(file_path=str(row["file_path"]), title=str(row["title"]))

    def batch_add_edges(self, edges: list[dict[str, Any]]) -> None:
        for row in edges:
            self.add_edge(
                source_id=str(row["source_id"]),
                target_id=str(row["target_id"]),
                relation_type=str(row["relation_type"]),
                weight=float(row.get("weight", 1.0)),
            )

    def get_related_sections(self, chunk_id: str) -> list[tuple[str, str, float]]:
        source_targets = {
            str(row.get("target_id"))
            for row in self._connection.scan_table("relations")
            if row.get("source_id") == chunk_id
            and row.get("relation_type") in {"MENTIONS", "HAS_TAG"}
        }
        related: list[tuple[str, str, float]] = []
        for row in self._connection.scan_table("relations"):
            if row.get("source_id") == chunk_id:
                continue
            if row.get("target_id") not in source_targets:
                continue
            relation_type = str(row.get("relation_type", ""))
            if relation_type not in {"MENTIONS", "HAS_TAG"}:
                continue
            related.append(
                (
                    str(row["source_id"]),
                    relation_type,
                    float(row.get("weight", 1.0)),
                )
            )
        return related

    def delete_all(self) -> None:
        for table_name in ("files", "sections", "entities", "tags", "relations"):
            self._connection.delete_all_from_table(table_name)

    def delete_file_subgraph(self, file_path: str) -> None:
        section_ids = [
            str(row["chunk_id"])
            for row in self._connection.scan_table("sections")
            if row.get("file_path") == file_path
        ]
        self.delete_chunks_from_graph(section_ids)
        self.delete_file_node(file_path)

    def delete_chunks_from_graph(self, chunk_ids: list[str]) -> None:
        if not chunk_ids:
            return
        for row in list(self._connection.scan_table("relations")):
            if row.get("source_id") in chunk_ids or row.get("target_id") in chunk_ids:
                self._connection.delete(row["id"])
        for chunk_id in chunk_ids:
            self._connection.delete(self._codec.encode("sections", chunk_id))

    def delete_file_node(self, file_path: str) -> None:
        self._connection.delete(self._codec.encode("files", file_path))

    def delete_frontmatter_edges(self, file_path: str) -> None:
        section_ids = {
            str(row["chunk_id"])
            for row in self._connection.scan_table("sections")
            if row.get("file_path") == file_path
        }
        for row in list(self._connection.scan_table("relations")):
            if row.get("source_id") in section_ids and row.get("relation_type") == "HAS_TAG":
                self._connection.delete(row["id"])

    def get_all_entity_names(self) -> list[str]:
        names = [str(row.get("name")) for row in self._connection.scan_table("entities")]
        return sorted(name for name in names if name)

    def get_chunks_by_entity(self, entity_name: str) -> list[str]:
        chunk_ids = [
            str(row["source_id"])
            for row in self._connection.scan_table("relations")
            if row.get("target_id") == entity_name and row.get("relation_type") == "MENTIONS"
        ]
        return sorted(chunk_ids)

    def get_entities_by_file(self, file_path: str) -> list[str]:
        section_ids = {
            str(row["chunk_id"])
            for row in self._connection.scan_table("sections")
            if row.get("file_path") == file_path
        }
        entity_names = {
            str(row["target_id"])
            for row in self._connection.scan_table("relations")
            if row.get("source_id") in section_ids and row.get("relation_type") == "MENTIONS"
        }
        return sorted(entity_names)

    def node_count(self) -> int:
        return sum(
            len(self._connection.scan_table(table_name))
            for table_name in ("files", "sections", "entities", "tags")
        )

    def edge_count(self) -> int:
        return len(self._connection.scan_table("relations"))

    def delete_isolated_nodes(self) -> int:
        relation_ids = set()
        for row in self._connection.scan_table("relations"):
            relation_ids.add(str(row.get("source_id")))
            relation_ids.add(str(row.get("target_id")))
        deleted = 0
        for table_name, key_name in (
            ("files", "file_path"),
            ("sections", "chunk_id"),
            ("entities", "name"),
            ("tags", "name"),
        ):
            for row in self._connection.scan_table(table_name):
                key = row.get(key_name)
                if not isinstance(key, str) or key in relation_ids:
                    continue
                self._connection.delete(row["id"])
                deleted += 1
        return deleted

    def get_graph_data(self) -> dict[str, list[dict[str, Any]]]:
        nodes: list[dict[str, Any]] = []
        for table_name, label in (
            ("files", "File"),
            ("sections", "Section"),
            ("entities", "Entity"),
            ("tags", "Tag"),
        ):
            nodes.extend(
                {"id": str(row.get("id")), "label": label, "properties": dict(row)}
                for row in self._connection.scan_table(table_name)
            )
        edges = [
            {
                "source": str(row.get("source_id")),
                "target": str(row.get("target_id")),
                "relation_type": str(row.get("relation_type")),
                "weight": float(row.get("weight", 1.0)),
            }
            for row in self._connection.scan_table("relations")
        ]
        return {"nodes": nodes, "edges": edges}

    def replace_entity_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            payload = dict(row)
            payload.setdefault("original_entity_name", str(payload.get("name", "")))
            self._connection.upsert(
                self._codec.encode("entities", str(payload["name"])),
                payload,
            )
        return len(rows)

    def replace_relation_rows(self, rows: list[dict[str, Any]]) -> int:
        payloads: list[dict[str, Any]] = []
        for row in rows:
            payload = dict(row)
            payload.setdefault("rel_type", payload.get("relation_type"))
            payload.setdefault("relation_type", payload.get("rel_type"))
            relation_id = str(payload.pop("relation_id"))
            payload["id"] = str(self._codec.encode("relations", relation_id).id)
            source_table = str(payload.get("source_table", "sections"))
            target_table = str(payload.get("target_table", "entities"))
            payload.setdefault("in", self._codec.encode(source_table, str(payload["source_id"])))
            payload.setdefault("out", self._codec.encode(target_table, str(payload["target_id"])))
            payloads.append(payload)
        if payloads:
            self._connection.query("INSERT RELATION INTO relations $rows;", {"rows": payloads})
        return len(rows)

    def replace_file_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            payload = dict(row)
            payload.setdefault("schema_version", "41.1.0")
            payload.setdefault("metadata", {})
            original_id = str(payload.get("original_id") or payload.get("path"))
            self._connection.upsert(self._codec.encode("files", original_id), payload)
        return len(rows)

    def replace_section_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            payload = dict(row)
            payload.setdefault("schema_version", "41.1.0")
            payload.setdefault("metadata", {})
            original_id = str(payload.get("original_id") or payload.get("chunk_id"))
            self._connection.upsert(self._codec.encode("sections", original_id), payload)
        return len(rows)

    def replace_tag_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            payload = dict(row)
            payload.setdefault("schema_version", "41.1.0")
            payload.setdefault("metadata", {})
            payload.setdefault("original_id", str(payload.get("name")))
            name = str(payload.get("name"))
            self._connection.upsert(self._codec.encode("tags", name), payload)
        return len(rows)

    def replace_graph_rows(
        self,
        *,
        entities: list[dict[str, Any]],
        relations: list[dict[str, Any]],
        files: list[dict[str, Any]] | None = None,
        sections: list[dict[str, Any]] | None = None,
        tags: list[dict[str, Any]] | None = None,
    ) -> int:
        replaced = 0
        section_rows = list(sections or [])
        section_ids = {
            str(row.get("original_id") or row.get("chunk_id"))
            for row in section_rows
        }
        tag_rows = list(tags or [])
        tag_names = {str(row.get("name")) for row in tag_rows}
        entity_rows = list(entities)
        entity_names = {str(row.get("name")) for row in entity_rows}

        for relation in relations:
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

        if files:
            replaced += self.replace_file_rows(files)
        if section_rows:
            replaced += self.replace_section_rows(section_rows)
        if tag_rows:
            replaced += self.replace_tag_rows(tag_rows)
        replaced += self.replace_entity_rows(entity_rows)
        replaced += self.replace_relation_rows(relations)
        return replaced


class SurrealFeedbackStore:
    """Prototype feedback adapter used by transform import."""

    def __init__(self, connection: SurrealConnection) -> None:
        self._connection = connection
        self._codec = SurrealRecordIdCodec()

    def replace_feedback_rows(self, rows: list[dict[str, Any]]) -> int:
        for row in rows:
            feedback_id = str(row["original_feedback_id"])
            self._connection.upsert(
                self._codec.encode("feedback", feedback_id),
                dict(row),
            )
        return len(rows)

    def list_all(self) -> list[dict[str, Any]]:
        return self._connection.scan_table("feedback")


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot_product = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot_product / (left_norm * right_norm)
