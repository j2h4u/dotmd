"""Minimal monolithic SurrealDB schema plan for dotMD standalone storage."""

from __future__ import annotations

from dataclasses import dataclass

MONOLITHIC_TABLES: tuple[str, ...] = (
    "documents",
    "source_units",
    "chunks",
    "chunk_file_bindings",
    "chunk_source_provenance",
    "resource_bindings",
    "source_unit_fingerprints",
    "source_checkpoints",
    "embeddings",
    "entities",
    "relations",
    "feedback",
)


def build_embeddings_hnsw_index_statement(
    *,
    index_name: str = "embeddings_vector_hnsw",
    table: str = "embeddings",
    field: str = "vector",
    dimension: int,
    distance: str = "COSINE",
    vector_type: str = "F32",
    efc: int = 150,
    m: int = 12,
) -> str:
    return (
        f"DEFINE INDEX IF NOT EXISTS {index_name} ON TABLE {table} FIELDS {field} "
        f"HNSW DIMENSION {dimension} TYPE {vector_type} DIST {distance} "
        f"EFC {efc} M {m};"
    )


def build_embeddings_diskann_index_statement(
    *,
    index_name: str = "embeddings_vector_diskann",
    table: str = "embeddings",
    field: str = "vector",
    dimension: int,
    distance: str = "COSINE",
    vector_type: str = "F32",
    degree: int = 64,
    l_build: int = 100,
    alpha: float = 1.2,
) -> str:
    return (
        f"DEFINE INDEX IF NOT EXISTS {index_name} ON TABLE {table} FIELDS {field} "
        f"DISKANN DIMENSION {dimension} TYPE {vector_type} DIST {distance} "
        f"DEGREE {degree} L_BUILD {l_build} ALPHA {alpha};"
    )


def build_table_statement(table: str) -> str:
    return f"DEFINE TABLE IF NOT EXISTS {table} SCHEMAFULL;"


def build_field_statement(table: str, field: str, type_sql: str) -> str:
    return f"DEFINE FIELD IF NOT EXISTS {field} ON TABLE {table} TYPE {type_sql};"


def build_index_statement(index_name: str, table: str, fields: str) -> str:
    return f"DEFINE INDEX IF NOT EXISTS {index_name} ON TABLE {table} FIELDS {fields};"


@dataclass(frozen=True, slots=True)
class SurrealSchemaPlan:
    """Simple monolithic schema plan for the standalone SurrealDB backend."""

    embedding_dimension: int = 1536
    embedding_field: str = "vector"

    def table_statements(self) -> tuple[str, ...]:
        return tuple(build_table_statement(table) for table in MONOLITHIC_TABLES)

    def field_statements(self) -> tuple[str, ...]:
        return (
            build_field_statement("documents", "schema_version", "int"),
            build_field_statement("documents", "namespace", "string"),
            build_field_statement("documents", "document_ref", "string"),
            build_field_statement("documents", "ref", "string"),
            build_field_statement("documents", "source_uri", "string"),
            build_field_statement("documents", "file_path", "option<string>"),
            build_field_statement("documents", "media_type", "string"),
            build_field_statement("documents", "parser_name", "string"),
            build_field_statement("documents", "document_type", "string"),
            build_field_statement("documents", "title", "string"),
            build_field_statement("documents", "updated_at", "string"),
            build_field_statement("documents", "content_fingerprint", "string"),
            build_field_statement("documents", "metadata_fingerprint", "string"),
            build_field_statement("documents", "metadata", "object FLEXIBLE"),
            build_field_statement("source_units", "document", "record<documents>"),
            build_field_statement("source_units", "namespace", "string"),
            build_field_statement("source_units", "document_ref", "string"),
            build_field_statement("source_units", "unit_ref", "string"),
            build_field_statement("source_units", "unit_type", "option<string>"),
            build_field_statement("source_units", "text", "option<string>"),
            build_field_statement("source_units", "order_key", "option<string>"),
            build_field_statement("source_units", "fingerprint", "option<string>"),
            build_field_statement("source_units", "updated_at", "option<string>"),
            build_field_statement("source_units", "metadata", "object FLEXIBLE"),
            build_field_statement("source_units", "chunking_hints", "object FLEXIBLE"),
            build_field_statement("chunks", "schema_version", "int"),
            build_field_statement("chunks", "chunk_id", "string"),
            build_field_statement("chunks", "original_chunk_id", "string"),
            build_field_statement("chunks", "chunk_strategy", "string"),
            build_field_statement("chunks", "document", "option<record<documents>>"),
            build_field_statement("chunks", "document_ref", "option<string>"),
            build_field_statement("chunks", "heading_hierarchy", "array<string>"),
            build_field_statement("chunks", "level", "int"),
            build_field_statement("chunks", "chunk_index", "int"),
            build_field_statement("chunks", "title", "option<string>"),
            build_field_statement("chunks", "text", "string"),
            build_field_statement("chunks", "metadata", "object FLEXIBLE"),
            build_field_statement("chunk_file_bindings", "chunk", "record<chunks>"),
            build_field_statement("chunk_file_bindings", "chunk_id", "string"),
            build_field_statement("chunk_file_bindings", "chunk_strategy", "string"),
            build_field_statement("chunk_file_bindings", "file_path", "string"),
            build_field_statement("chunk_file_bindings", "chunk_index", "int"),
            build_field_statement("chunk_source_provenance", "chunk", "record<chunks>"),
            build_field_statement("chunk_source_provenance", "chunk_id", "string"),
            build_field_statement("chunk_source_provenance", "namespace", "string"),
            build_field_statement("chunk_source_provenance", "document", "record<documents>"),
            build_field_statement("chunk_source_provenance", "document_ref", "string"),
            build_field_statement("chunk_source_provenance", "source_unit_refs", "array<string>"),
            build_field_statement("chunk_source_provenance", "chunk_strategy", "string"),
            build_field_statement("chunk_source_provenance", "parser_name", "option<string>"),
            build_field_statement("resource_bindings", "namespace", "string"),
            build_field_statement("resource_bindings", "resource_ref", "string"),
            build_field_statement("resource_bindings", "document", "record<documents>"),
            build_field_statement("resource_bindings", "document_ref", "string"),
            build_field_statement("resource_bindings", "ref", "string"),
            build_field_statement("resource_bindings", "active", "bool"),
            build_field_statement("resource_bindings", "bound_at", "string"),
            build_field_statement("resource_bindings", "unbound_at", "option<string>"),
            build_field_statement("resource_bindings", "content_fingerprint", "string"),
            build_field_statement("resource_bindings", "metadata_fingerprint", "string"),
            build_field_statement("resource_bindings", "source_unit_refs", "array<string>"),
            build_field_statement("resource_bindings", "metadata", "object FLEXIBLE"),
            build_field_statement("source_unit_fingerprints", "namespace", "string"),
            build_field_statement("source_unit_fingerprints", "document", "record<documents>"),
            build_field_statement("source_unit_fingerprints", "document_ref", "string"),
            build_field_statement("source_unit_fingerprints", "unit_ref", "string"),
            build_field_statement("source_unit_fingerprints", "fingerprint", "string"),
            build_field_statement("source_unit_fingerprints", "updated_at", "string"),
            build_field_statement("source_unit_fingerprints", "indexed_at", "string"),
            build_field_statement("source_unit_fingerprints", "metadata", "object FLEXIBLE"),
            build_field_statement("source_checkpoints", "namespace", "string"),
            build_field_statement("source_checkpoints", "checkpoint_cursor", "option<string>"),
            build_field_statement("source_checkpoints", "last_success_at", "option<string>"),
            build_field_statement("source_checkpoints", "last_error", "option<string>"),
            build_field_statement("source_checkpoints", "metadata", "object FLEXIBLE"),
            build_field_statement("embeddings", "schema_version", "int"),
            build_field_statement("embeddings", "chunk", "record<chunks>"),
            build_field_statement("embeddings", "chunk_id", "string"),
            build_field_statement("embeddings", "chunk_strategy", "string"),
            build_field_statement("embeddings", "embedding_model", "string"),
            build_field_statement("embeddings", "text_hash", "option<string>"),
            build_field_statement("embeddings", self.embedding_field, "array<float>"),
            build_field_statement("embeddings", "metadata", "object FLEXIBLE"),
            build_field_statement("entities", "chunk", "record<chunks>"),
            build_field_statement("entities", "name", "string"),
            build_field_statement("entities", "kind", "string"),
            build_field_statement("relations", "source", "record<entities>"),
            build_field_statement("relations", "target", "record<entities>"),
            build_field_statement("relations", "kind", "string"),
            build_field_statement("relations", "weight", "float"),
            build_field_statement("feedback", "chunk", "option<record<chunks>>"),
            build_field_statement("feedback", "query", "string"),
            build_field_statement("feedback", "message", "string"),
            build_field_statement("feedback", "rating", "option<int>"),
        )

    def scalar_index_statements(self) -> tuple[str, ...]:
        return (
            build_index_statement("documents_ref", "documents", "namespace, document_ref"),
            build_index_statement("chunks_chunk_id", "chunks", "chunk_id"),
            build_index_statement(
                "chunks_strategy_document",
                "chunks",
                "chunk_strategy, document_ref",
            ),
            build_index_statement(
                "chunk_file_bindings_file_path",
                "chunk_file_bindings",
                "file_path",
            ),
            build_index_statement(
                "chunk_source_provenance_chunk_id",
                "chunk_source_provenance",
                "chunk_id",
            ),
            build_index_statement(
                "resource_bindings_document_active",
                "resource_bindings",
                "namespace, document_ref, active",
            ),
            build_index_statement(
                "source_unit_fingerprints_document",
                "source_unit_fingerprints",
                "namespace, document_ref",
            ),
            build_index_statement(
                "embeddings_chunk_model",
                "embeddings",
                "chunk_id, chunk_strategy, embedding_model",
            ),
        )

    def index_statements(self, *, vector_index: str = "hnsw") -> tuple[str, ...]:
        if vector_index == "hnsw":
            return (
                build_embeddings_hnsw_index_statement(
                    dimension=self.embedding_dimension,
                    field=self.embedding_field,
                ),
            )
        if vector_index == "diskann":
            return (
                build_embeddings_diskann_index_statement(
                    dimension=self.embedding_dimension,
                    field=self.embedding_field,
                ),
            )
        if vector_index == "none":
            return ()
        raise ValueError("vector_index must be 'hnsw', 'diskann', or 'none'")

    def vector_index_statements(self) -> tuple[str, str]:
        return (
            build_embeddings_hnsw_index_statement(
                dimension=self.embedding_dimension,
                field=self.embedding_field,
            ),
            build_embeddings_diskann_index_statement(
                dimension=self.embedding_dimension,
                field=self.embedding_field,
            ),
        )

    def statements(self, *, vector_index: str = "hnsw") -> tuple[str, ...]:
        return (
            self.table_statements()
            + self.field_statements()
            + self.scalar_index_statements()
            + self.index_statements(vector_index=vector_index)
        )


def build_minimal_monolithic_schema_plan(embedding_dimension: int = 1536) -> SurrealSchemaPlan:
    return SurrealSchemaPlan(embedding_dimension=embedding_dimension)
