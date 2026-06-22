"""Production Surreal schema catalog for Phase 41 migration work."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from surrealdb import SurrealError

from dotmd.core.config import (
    DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
    SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES,
)

SURREAL_SCHEMA_VERSION = "42.1.0"
MIN_TOP_K = 1
MAX_TOP_K = 100
MIN_HNSW_M = 1
MAX_HNSW_M = 64
DEFAULT_HNSW_M = 12
MIN_HNSW_EF = 10
MAX_HNSW_EF = 400
DEFAULT_HNSW_EF = 40
DEFAULT_EMBEDDING_SHARD_COUNT = 1

_REQUIRED_MIGRATION_CATEGORIES = (
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
)

_UNSUPPORTED_MIGRATION_CATEGORIES = (
    "stats",
    "embedding_cache",
    "embedding_cache_meta",
    "extraction_cache",
    "extraction_cache_meta",
)

_REQUIRED_FIELDS: dict[str, tuple[str, ...]] = {
    "documents": ("schema_version", "namespace", "document_ref", "ref", "metadata"),
    "source_units": ("schema_version", "namespace", "document_ref", "unit_ref", "metadata"),
    "chunks": (
        "schema_version",
        "original_chunk_id",
        "chunk_strategy",
        "document_ref",
        "ref",
        "title",
        "tags_text",
        "text",
        "metadata",
    ),
    "provenance": (
        "schema_version",
        "chunk_id",
        "namespace",
        "document_ref",
        "source_unit_refs",
        "metadata",
    ),
    "chunk_file_bindings": (
        "schema_version",
        "chunk_id",
        "file_path",
        "chunk_index",
        "metadata",
    ),
    "bindings": (
        "schema_version",
        "namespace",
        "document_ref",
        "ref",
        "active",
        "bound_at",
        "unbound_at",
        "content_fingerprint",
        "metadata_fingerprint",
        "source_unit_refs",
        "metadata",
    ),
    "fingerprints": (
        "schema_version",
        "fingerprint_kind",
        "namespace",
        "document_ref",
        "metadata",
    ),
    "embeddings": (
        "schema_version",
        "chunk_id",
        "embedding_model",
        "text_hash",
        "vector_rowid",
        "vector",
        "metadata",
    ),
    "vector_components": (
        "schema_version",
        "chunk_id",
        "component",
        "embedding",
        "metadata",
    ),
    "files": ("schema_version", "original_id", "path", "metadata"),
    "sections": ("schema_version", "original_id", "document_ref", "metadata"),
    "entities": ("schema_version", "original_id", "name", "metadata"),
    "tags": ("schema_version", "original_id", "name", "metadata"),
    "relations": (
        "schema_version",
        "rel_type",
        "weight",
        "source_id",
        "target_id",
        "source_table",
        "target_table",
        "properties",
        "metadata",
    ),
    "feedback": ("schema_version", "original_feedback_id", "status", "submitted_at", "metadata"),
    "cursors": ("schema_version", "namespace", "ref", "document_ref", "metadata"),
    "checkpoints": ("schema_version", "namespace", "checkpoint_cursor", "metadata"),
}

_KNOWN_COMPATIBLE_PREVIOUS_VERSIONS = {"41.0.0", "41.1.0"}


class _SchemaConnectionProtocol(Protocol):
    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def query_raw(self, statement: str, variables: dict[str, Any] | None = None) -> Any: ...

    def inspect_schema(self) -> dict[str, Any]: ...


@dataclass(slots=True, frozen=True)
class SurrealFieldDefinition:
    name: str
    field_type: str
    required: bool = True
    flexible_json: bool = False
    note: str = ""


@dataclass(slots=True, frozen=True)
class SurrealIndexDefinition:
    name: str
    columns: tuple[str, ...]
    unique: bool = False
    note: str = ""


@dataclass(slots=True, frozen=True)
class SurrealTableDefinition:
    name: str
    note: str
    schema_mode: str
    fields: tuple[SurrealFieldDefinition, ...]
    indexes: tuple[SurrealIndexDefinition, ...] = ()
    statement: str = ""
    optional: bool = False
    derived_from: tuple[str, ...] = ()
    incoming_tables: tuple[str, ...] = ()
    outgoing_tables: tuple[str, ...] = ()
    relation_endpoints_enforced: bool = False


@dataclass(slots=True, frozen=True)
class SurrealSchemaPlan:
    schema_version: str
    tables: tuple[SurrealTableDefinition, ...]
    statements: tuple[str, ...]
    required_categories: tuple[str, ...]
    unsupported_categories: tuple[str, ...]
    preservation_notes: tuple[str, ...]
    downstream_phase_consumables: tuple[str, ...]


@dataclass(slots=True, frozen=True)
class SurrealSchemaApplyStatus:
    status: str
    applied: bool = False
    reason: str = ""
    existing_version: str | None = None
    statements_applied: int = 0


@dataclass(slots=True, frozen=True)
class SurrealRetrievalIndexPlan:
    embedding_dimension: int
    hnsw_m: int
    hnsw_ef: int
    vector_index_type: str
    analyzer_statement: str
    bm25_index_statements: tuple[str, ...]
    hnsw_index_statement: str
    relation_index_statements: tuple[str, ...]

    @property
    def statements(self) -> tuple[str, ...]:
        return (
            self.analyzer_statement,
            *self.bm25_index_statements,
            self.hnsw_index_statement,
            *self.relation_index_statements,
        )


@dataclass(slots=True, frozen=True)
class SurrealRetrievalCapabilityCheck:
    name: str
    required: bool
    passed: bool
    detail: str
    statement: str


@dataclass(slots=True, frozen=True)
class SurrealRetrievalCapabilityReport:
    runtime_version: str | None
    required_checks: tuple[SurrealRetrievalCapabilityCheck, ...]
    optional_observations: tuple[SurrealRetrievalCapabilityCheck, ...]

    @property
    def overall_passed(self) -> bool:
        return all(check.passed for check in self.required_checks)


def surreal_embedding_table_name(shard_index: int | None = None) -> str:
    if shard_index is None:
        return "embeddings"
    if shard_index < 0:
        raise ValueError("shard_index must be non-negative")
    return f"embeddings_{shard_index}"


def surreal_embedding_hnsw_index_name(shard_index: int | None = None) -> str:
    if shard_index is None:
        return "embeddings_vector_hnsw"
    if shard_index < 0:
        raise ValueError("shard_index must be non-negative")
    return f"embeddings_{shard_index}_vector_hnsw"


def surreal_embedding_shard_tables(shard_count: int) -> tuple[str, ...]:
    if shard_count <= 0:
        raise ValueError("shard_count must be positive")
    if shard_count == 1:
        return ("embeddings",)
    return tuple(surreal_embedding_table_name(index) for index in range(shard_count))


def _normalize_surreal_hnsw_vector_index_type(vector_index_type: str) -> str:
    if not isinstance(vector_index_type, str):
        raise ValueError("vector_index_type must be a string")
    normalized = vector_index_type.strip().upper()
    if normalized not in SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES:
        raise ValueError(
            "vector_index_type must be one of "
            f"{', '.join(SUPPORTED_SURREAL_HNSW_VECTOR_INDEX_TYPES)}"
        )
    return normalized


def _field(
    name: str,
    field_type: str,
    *,
    required: bool = True,
    flexible_json: bool = False,
    note: str = "",
) -> SurrealFieldDefinition:
    return SurrealFieldDefinition(
        name=name,
        field_type=field_type,
        required=required,
        flexible_json=flexible_json,
        note=note,
    )


def _index(
    name: str,
    *columns: str,
    unique: bool = False,
    note: str = "",
) -> SurrealIndexDefinition:
    return SurrealIndexDefinition(name=name, columns=columns, unique=unique, note=note)


def _field_statement(table_name: str, field_def: SurrealFieldDefinition) -> str:
    optional_prefix = "" if field_def.required else "option<"
    optional_suffix = "" if field_def.required else ">"
    declared_type = f"{optional_prefix}{field_def.field_type}{optional_suffix}"
    return f"DEFINE FIELD {field_def.name} ON TABLE {table_name} TYPE {declared_type};"


def _field_statements(
    table_name: str,
    field_def: SurrealFieldDefinition,
    *,
    schema_mode: str,
) -> tuple[str, ...]:
    statements = [_field_statement(table_name, field_def)]
    if field_def.flexible_json and schema_mode == "SCHEMAFULL":
        json_value_type = "option<object | string | number | bool | array>"
        statements.append(
            f"DEFINE FIELD {field_def.name}.* ON TABLE {table_name} TYPE {json_value_type} FLEXIBLE;"
        )
    return tuple(statements)


def _index_statement(table_name: str, index_def: SurrealIndexDefinition) -> str:
    unique_fragment = " UNIQUE" if index_def.unique else ""
    columns = ", ".join(index_def.columns)
    return (
        f"DEFINE INDEX {index_def.name} ON TABLE {table_name} COLUMNS {columns}{unique_fragment};"
    )


def _table(
    name: str,
    note: str,
    *,
    fields: tuple[SurrealFieldDefinition, ...],
    indexes: tuple[SurrealIndexDefinition, ...] = (),
    schema_mode: str = "SCHEMAFULL",
    optional: bool = False,
    derived_from: tuple[str, ...] = (),
    incoming_tables: tuple[str, ...] = (),
    outgoing_tables: tuple[str, ...] = (),
    relation_endpoints_enforced: bool = False,
) -> SurrealTableDefinition:
    if schema_mode == "RELATION":
        statement = "DEFINE TABLE relations TYPE RELATION;"
    else:
        statement = f"DEFINE TABLE {name} {schema_mode};"
    return SurrealTableDefinition(
        name=name,
        note=note,
        schema_mode=schema_mode,
        fields=fields,
        indexes=indexes,
        statement=statement,
        optional=optional,
        derived_from=derived_from,
        incoming_tables=incoming_tables,
        outgoing_tables=outgoing_tables,
        relation_endpoints_enforced=relation_endpoints_enforced,
    )


def required_migration_categories() -> tuple[str, ...]:
    return _REQUIRED_MIGRATION_CATEGORIES


def build_surreal_native_retrieval_index_plan(
    *,
    embedding_dimension: int,
    hnsw_m: int = DEFAULT_HNSW_M,
    hnsw_ef: int = DEFAULT_HNSW_EF,
    vector_index_type: str = DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
    fulltext_concurrently: bool = False,
) -> SurrealRetrievalIndexPlan:
    if embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be a positive integer")
    if hnsw_m < MIN_HNSW_M or hnsw_m > MAX_HNSW_M:
        raise ValueError(f"hnsw_m must be between {MIN_HNSW_M} and {MAX_HNSW_M}, inclusive")
    if hnsw_ef < MIN_HNSW_EF or hnsw_ef > MAX_HNSW_EF:
        raise ValueError(f"hnsw_ef must be between {MIN_HNSW_EF} and {MAX_HNSW_EF}, inclusive")
    normalized_vector_index_type = _normalize_surreal_hnsw_vector_index_type(vector_index_type)

    fulltext_suffix = " CONCURRENTLY" if fulltext_concurrently else ""

    return SurrealRetrievalIndexPlan(
        embedding_dimension=embedding_dimension,
        hnsw_m=hnsw_m,
        hnsw_ef=hnsw_ef,
        vector_index_type=normalized_vector_index_type,
        analyzer_statement=("DEFINE ANALYZER dotmd_fts TOKENIZERS CLASS,PUNCT FILTERS LOWERCASE"),
        bm25_index_statements=(
            f"DEFINE INDEX chunks_title_fts ON chunks FIELDS title FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75){fulltext_suffix}",
            f"DEFINE INDEX chunks_text_fts ON chunks FIELDS text FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75){fulltext_suffix}",
        ),
        hnsw_index_statement=build_surreal_embedding_hnsw_index_statement(
            table_name=surreal_embedding_table_name(),
            index_name=surreal_embedding_hnsw_index_name(),
            embedding_dimension=embedding_dimension,
            hnsw_m=hnsw_m,
            hnsw_ef=hnsw_ef,
            vector_index_type=normalized_vector_index_type,
        ),
        relation_index_statements=(
            "DEFINE INDEX relations_rel_type_idx ON TABLE relations COLUMNS rel_type;",
            "DEFINE INDEX relations_target_id_idx ON TABLE relations COLUMNS target_id;",
            "DEFINE INDEX relations_source_target_idx ON TABLE relations COLUMNS source_id, target_id;",
            "DEFINE INDEX relations_graph_direct_idx ON TABLE relations COLUMNS target_id, rel_type, source_table;",
        ),
    )


def build_surreal_embedding_hnsw_index_statement(
    *,
    table_name: str,
    index_name: str,
    embedding_dimension: int,
    hnsw_m: int = DEFAULT_HNSW_M,
    hnsw_ef: int = DEFAULT_HNSW_EF,
    vector_index_type: str = DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
) -> str:
    if not table_name:
        raise ValueError("table_name must not be empty")
    if not index_name:
        raise ValueError("index_name must not be empty")
    if embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be a positive integer")
    if hnsw_m < MIN_HNSW_M or hnsw_m > MAX_HNSW_M:
        raise ValueError(f"hnsw_m must be between {MIN_HNSW_M} and {MAX_HNSW_M}, inclusive")
    if hnsw_ef < MIN_HNSW_EF or hnsw_ef > MAX_HNSW_EF:
        raise ValueError(f"hnsw_ef must be between {MIN_HNSW_EF} and {MAX_HNSW_EF}, inclusive")
    normalized_vector_index_type = _normalize_surreal_hnsw_vector_index_type(vector_index_type)
    return (
        f"DEFINE INDEX {index_name} ON TABLE {table_name} FIELDS vector "
        f"HNSW DIMENSION {embedding_dimension} DIST COSINE TYPE {normalized_vector_index_type} "
        f"EFC {hnsw_ef} M {hnsw_m};"
    )


def validate_surreal_native_retrieval_contract(
    *,
    embedding_dimension: int,
    embedding_rows: list[dict[str, Any]],
    top_k: int,
    hnsw_ef: int,
) -> None:
    if embedding_dimension <= 0:
        raise ValueError("embedding_dimension must be a positive integer")
    if top_k < MIN_TOP_K or top_k > MAX_TOP_K:
        raise ValueError(f"top_k must be between {MIN_TOP_K} and {MAX_TOP_K}, inclusive")
    if hnsw_ef < MIN_HNSW_EF or hnsw_ef > MAX_HNSW_EF:
        raise ValueError(f"hnsw_ef must be between {MIN_HNSW_EF} and {MAX_HNSW_EF}, inclusive")
    if hnsw_ef < top_k:
        raise ValueError("hnsw_ef must be greater than or equal to top_k")

    active_models = {
        str(row["embedding_model"])
        for row in embedding_rows
        if row.get("embedding_model") not in (None, "")
    }
    if len(active_models) != 1:
        raise ValueError("target must contain a single active embedding_model")

    for row in embedding_rows:
        vector = row.get("vector")
        if not isinstance(vector, list) or not vector:
            continue
        if len(vector) != embedding_dimension:
            raise ValueError(
                f"embedding_dimension mismatch: expected {embedding_dimension}, got {len(vector)}"
            )


def build_dotmd_surreal_schema_plan() -> SurrealSchemaPlan:
    tables = (
        _table(
            "documents",
            "Canonical document envelopes preserved from source_documents.",
            fields=(
                _field("schema_version", "string"),
                _field("namespace", "string"),
                _field("document_ref", "string"),
                _field("ref", "string"),
                _field("title", "string", required=False),
                _field("media_type", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index("documents_ref_idx", "ref", unique=True),
                _index("documents_namespace_ref_idx", "namespace", "document_ref", unique=True),
            ),
        ),
        _table(
            "source_units",
            "Source-unit rows preserved from source_unit_fingerprints.",
            fields=(
                _field("schema_version", "string"),
                _field("namespace", "string"),
                _field("document_ref", "string"),
                _field("unit_ref", "string"),
                _field("fingerprint", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index(
                    "source_units_identity_idx",
                    "namespace",
                    "document_ref",
                    "unit_ref",
                    unique=True,
                ),
            ),
        ),
        _table(
            "chunks",
            "Content-addressed chunk payloads and source-preserving identifiers.",
            fields=(
                _field("schema_version", "string"),
                _field("original_chunk_id", "string"),
                _field("chunk_id", "string"),
                _field("chunk_strategy", "string"),
                _field("heading_hierarchy", "array", required=False),
                _field("level", "int", required=False),
                _field("document_ref", "string"),
                _field("ref", "string"),
                _field("title", "string", required=False),
                _field("tags_text", "string", required=False),
                _field("text", "string"),
                _field("file_paths", "array", required=False),
                _field("file_bindings", "array", required=False),
                _field("source_unit_refs", "array", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index("chunks_chunk_id_idx", "chunk_id", unique=True),
                _index("chunks_ref_idx", "ref"),
            ),
        ),
        _table(
            "provenance",
            "Chunk provenance, namespace/document identity, and source-unit refs.",
            fields=(
                _field("schema_version", "string"),
                _field("chunk_id", "string"),
                _field("provenance_id", "string", required=False),
                _field("namespace", "string"),
                _field("document_ref", "string"),
                _field("chunk_strategy", "string", required=False),
                _field("source_unit_refs", "array", required=False),
                _field("parser_name", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("provenance_chunk_idx", "chunk_id"),),
        ),
        _table(
            "chunk_file_bindings",
            "Many-to-many chunk/file/path/index bindings retained from SQLite holder rows.",
            fields=(
                _field("schema_version", "string"),
                _field("binding_id", "string", required=False),
                _field("chunk_id", "string"),
                _field("file_path", "string"),
                _field("chunk_index", "int"),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index("chunk_file_bindings_chunk_file_idx", "chunk_id", "file_path", unique=True),
            ),
        ),
        _table(
            "bindings",
            "Resource binding lifecycle state, including inactive retained artifacts.",
            fields=(
                _field("schema_version", "string"),
                _field("namespace", "string"),
                _field("document_ref", "string"),
                _field("ref", "string"),
                _field("resource_ref", "string", required=False),
                _field("active", "bool"),
                _field("bound_at", "datetime"),
                _field("unbound_at", "datetime", required=False),
                _field("content_fingerprint", "string", required=False),
                _field("metadata_fingerprint", "string", required=False),
                _field("source_unit_refs", "array", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index("bindings_ref_idx", "ref", unique=True),
                _index("bindings_namespace_document_idx", "namespace", "document_ref"),
            ),
        ),
        _table(
            "fingerprints",
            "Chunk, embed, metadata, and source-unit fingerprints kept as distinct records.",
            fields=(
                _field("schema_version", "string"),
                _field("fingerprint_id", "string", required=False),
                _field("fingerprint_kind", "string"),
                _field("namespace", "string", required=False),
                _field("document_ref", "string", required=False),
                _field("content_fingerprint", "string", required=False),
                _field("metadata_fingerprint", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("fingerprints_kind_doc_idx", "fingerprint_kind", "document_ref"),),
        ),
        _table(
            "embeddings",
            "Stored sqlite-vec rows preserved without TEI recomputation.",
            fields=(
                _field("schema_version", "string"),
                _field("chunk_id", "string"),
                _field("chunk_strategy", "string"),
                _field("embedding_model", "string"),
                _field("text_hash", "string"),
                _field("vector_rowid", "int"),
                _field("vector", "array<float>", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index(
                    "embeddings_strategy_chunk_model_idx",
                    "chunk_strategy",
                    "chunk_id",
                    "embedding_model",
                    unique=True,
                ),
                _index("embeddings_strategy_model_idx", "chunk_strategy", "embedding_model"),
                _index("embeddings_text_hash_idx", "text_hash"),
            ),
        ),
        _table(
            "vector_components",
            "Optional derived physical storage for per-component vectors when source rows exist.",
            fields=(
                _field("schema_version", "string"),
                _field("chunk_id", "string"),
                _field("chunk_strategy", "string"),
                _field("embedding_model", "string"),
                _field("component", "string"),
                _field("embedding", "array<float>"),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index(
                    "vector_components_strategy_model_chunk_component_idx",
                    "chunk_strategy",
                    "embedding_model",
                    "chunk_id",
                    "component",
                    unique=True,
                ),
            ),
            optional=True,
            derived_from=("embeddings",),
        ),
        _table(
            "files",
            "Graph file nodes imported from exporter data.",
            fields=(
                _field("schema_version", "string"),
                _field("original_id", "string"),
                _field("file_path", "string", required=False),
                _field("path", "string"),
                _field("title", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("files_path_idx", "path", unique=True),),
        ),
        _table(
            "sections",
            "Graph section nodes preserved for later relation traversal.",
            fields=(
                _field("schema_version", "string"),
                _field("original_id", "string"),
                _field("chunk_id", "string", required=False),
                _field("document_ref", "string", required=False),
                _field("file_path", "string", required=False),
                _field("heading", "string", required=False),
                _field("level", "int", required=False),
                _field("text_preview", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("sections_original_id_idx", "original_id", unique=True),),
        ),
        _table(
            "entities",
            "Graph entity nodes with preserved names and metadata.",
            fields=(
                _field("schema_version", "string"),
                _field("original_id", "string"),
                _field("original_entity_name", "string", required=False),
                _field("name", "string"),
                _field("entity_type", "string", required=False),
                _field("source", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("entities_name_idx", "name"),),
        ),
        _table(
            "tags",
            "Graph tag nodes used by the old stack and later Surreal traversal work.",
            fields=(
                _field("schema_version", "string"),
                _field("original_id", "string"),
                _field("name", "string"),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("tags_name_idx", "name"),),
        ),
        _table(
            "relations",
            "Metadata-carrying relation records preserving canonical rel_type and endpoint hints.",
            fields=(
                _field("schema_version", "string"),
                _field("relation_id", "string", required=False),
                _field("rel_type", "string"),
                _field("relation_type", "string", required=False),
                _field("weight", "number"),
                _field("source_id", "string"),
                _field("target_id", "string"),
                _field("source_table", "string"),
                _field("target_table", "string"),
                _field("properties", "object", required=False, flexible_json=True),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(
                _index("relations_rel_type_idx", "rel_type"),
                _index("relations_target_id_idx", "target_id"),
                _index("relations_source_target_idx", "source_id", "target_id"),
                _index("relations_graph_direct_idx", "target_id", "rel_type", "source_table"),
            ),
            schema_mode="RELATION",
            incoming_tables=("files", "sections", "entities", "tags"),
            outgoing_tables=("files", "sections", "entities", "tags"),
            relation_endpoints_enforced=False,
        ),
        _table(
            "feedback",
            "Feedback rows imported through the provider abstraction only.",
            fields=(
                _field("schema_version", "string"),
                _field("original_feedback_id", "string"),
                _field("status", "string"),
                _field("submitted_at", "datetime"),
                _field("message", "string", required=False),
                _field("severity", "string", required=False),
                _field("context", "string", required=False),
                _field("model", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("feedback_status_idx", "status"),),
        ),
        _table(
            "cursors",
            "Resource-ref keyed cursor and read-audit state.",
            fields=(
                _field("schema_version", "string"),
                _field("cursor_id", "string", required=False),
                _field("namespace", "string"),
                _field("ref", "string"),
                _field("document_ref", "string"),
                _field("active", "bool", required=False),
                _field("bound_at", "datetime", required=False),
                _field("unbound_at", "datetime", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("cursors_ref_idx", "ref", unique=True),),
        ),
        _table(
            "checkpoints",
            "Source checkpoint rows retained without recomputation.",
            fields=(
                _field("schema_version", "string"),
                _field("namespace", "string"),
                _field("checkpoint_cursor", "string", required=False),
                _field("last_success_at", "datetime", required=False),
                _field("last_error", "string", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("checkpoints_namespace_idx", "namespace", unique=True),),
        ),
        _table(
            "stats",
            "Noncanonical aggregate counts retained only as optional migration evidence.",
            fields=(
                _field("schema_version", "string"),
                _field("name", "string"),
                _field("value", "number"),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("stats_name_idx", "name", unique=True),),
            optional=True,
        ),
        _table(
            "schema_meta",
            "Schema-version sentinel used to make apply status explicit.",
            fields=(
                _field("schema_version", "string"),
                _field("catalog_name", "string"),
                _field("required_categories", "array", required=False),
                _field("metadata", "object", required=False, flexible_json=True),
            ),
            indexes=(_index("schema_meta_catalog_idx", "catalog_name", unique=True),),
        ),
    )

    statements: list[str] = []
    for table in tables:
        statements.append(table.statement)
        for field_def in table.fields:
            statements.extend(
                _field_statements(table.name, field_def, schema_mode=table.schema_mode)
            )
        statements.extend(_index_statement(table.name, index_def) for index_def in table.indexes)

    return SurrealSchemaPlan(
        schema_version=SURREAL_SCHEMA_VERSION,
        tables=tables,
        statements=tuple(statements),
        required_categories=required_migration_categories(),
        unsupported_categories=_UNSUPPORTED_MIGRATION_CATEGORIES,
        preservation_notes=(
            "SCHEMAFULL tables keep flexible metadata/properties fields for legacy JSON payloads.",
            "Relations preserve rel_type, weight, source_id, target_id, source_table, and target_table without ENFORCED endpoint rejection.",
            "vector_components remains optional derived storage and is not a retrieval prerequisite.",
            "stats and cache categories are not required migration-success criteria.",
        ),
        downstream_phase_consumables=(
            "documents.ref",
            "chunks.chunk_id",
            "chunks.ref",
            "chunks.title",
            "chunks.tags_text",
            "embeddings.vector_rowid",
            "relations.rel_type",
            "relations.source_id",
            "relations.target_id",
            "bindings.active",
            "checkpoints.checkpoint_cursor",
        ),
    )


def validate_dotmd_surreal_schema_plan(plan: SurrealSchemaPlan) -> None:
    tables_by_name = {table.name: table for table in plan.tables}
    missing_tables = [
        name for name in required_migration_categories() if name not in tables_by_name
    ]
    if missing_tables:
        raise ValueError(f"missing required schema categories: {', '.join(missing_tables)}")

    for table_name, required_fields in _REQUIRED_FIELDS.items():
        table = tables_by_name.get(table_name)
        if table is None:
            continue
        field_names = {field.name for field in table.fields}
        missing_fields = [
            field_name for field_name in required_fields if field_name not in field_names
        ]
        if missing_fields:
            raise ValueError(
                f"table {table_name} missing required fields: {', '.join(missing_fields)}"
            )


def _version_key(version: str) -> tuple[int, ...]:
    parts: list[int] = []
    current = ""
    for char in version:
        if char.isdigit():
            current += char
            continue
        if current:
            parts.append(int(current))
            current = ""
    if current:
        parts.append(int(current))
    return tuple(parts)


def _inspect_existing_schema(
    connection: _SchemaConnectionProtocol,
    plan: SurrealSchemaPlan,
) -> SurrealSchemaApplyStatus:
    existing = connection.inspect_schema()
    existing_version = existing.get("schema_version")
    table_modes = {
        str(name): str(mode)
        for name, mode in dict(existing.get("table_modes", {})).items()
        if isinstance(name, str)
    }

    if not existing_version and not table_modes:
        return SurrealSchemaApplyStatus(status="pending-apply")

    if any(mode.upper() == "SCHEMALESS" for mode in table_modes.values()):
        return SurrealSchemaApplyStatus(
            status="replace-required",
            reason="existing target includes SCHEMALESS tables from the Phase 38 prototype",
            existing_version=str(existing_version) if existing_version is not None else None,
        )

    if existing_version == plan.schema_version:
        return SurrealSchemaApplyStatus(
            status="already-current",
            existing_version=plan.schema_version,
        )

    if isinstance(existing_version, str):
        if existing_version in _KNOWN_COMPATIBLE_PREVIOUS_VERSIONS:
            return SurrealSchemaApplyStatus(
                status="pending-apply",
                reason=f"upgrade-needed from {existing_version}",
                existing_version=existing_version,
            )
        if _version_key(existing_version) > _version_key(plan.schema_version):
            return SurrealSchemaApplyStatus(
                status="replace-required",
                reason=f"existing target uses newer schema version {existing_version}",
                existing_version=existing_version,
            )

    return SurrealSchemaApplyStatus(
        status="replace-required",
        reason="existing target schema is incompatible and must be recreated or replaced",
        existing_version=str(existing_version) if existing_version is not None else None,
    )


def _serialize_table(table: SurrealTableDefinition) -> dict[str, Any]:
    return {
        "name": table.name,
        "note": table.note,
        "schema_mode": table.schema_mode,
        "optional": table.optional,
        "derived_from": list(table.derived_from),
        "incoming_tables": list(table.incoming_tables),
        "outgoing_tables": list(table.outgoing_tables),
        "relation_endpoints_enforced": table.relation_endpoints_enforced,
        "statement": table.statement,
        "fields": [
            {
                "name": field_def.name,
                "field_type": field_def.field_type,
                "required": field_def.required,
                "flexible_json": field_def.flexible_json,
                "note": field_def.note,
            }
            for field_def in table.fields
        ],
        "indexes": [
            {
                "name": index_def.name,
                "columns": list(index_def.columns),
                "unique": index_def.unique,
                "note": index_def.note,
            }
            for index_def in table.indexes
        ],
    }


def _runtime_version(connection: _SchemaConnectionProtocol) -> str | None:
    try:
        result = connection.query_raw("RETURN version();")
    except (RuntimeError, SurrealError):  # pragma: no cover - best-effort metadata only
        return None

    if isinstance(result, dict):
        rows = result.get("result")
        if isinstance(rows, list) and rows:
            first = rows[0]
            if isinstance(first, dict):
                value = first.get("result")
                if isinstance(value, str):
                    return value
                if isinstance(value, list) and value and isinstance(value[0], str):
                    return value[0]
    return None


def _normalize_probe_error(exc: Exception) -> str:
    return str(exc).strip() or exc.__class__.__name__


def _statement_already_exists(message: str) -> bool:
    lowered = message.lower()
    return "already exists" in lowered or "already defined" in lowered


def _run_probe_statement(
    connection: _SchemaConnectionProtocol,
    *,
    name: str,
    required: bool,
    statement: str,
) -> SurrealRetrievalCapabilityCheck:
    try:
        connection.query_raw(statement)
    except (RuntimeError, SurrealError) as exc:
        detail = _normalize_probe_error(exc)
        if _statement_already_exists(detail):
            return SurrealRetrievalCapabilityCheck(
                name=name,
                required=required,
                passed=True,
                detail="statement already existed on the isolated target",
                statement=statement,
            )
        return SurrealRetrievalCapabilityCheck(
            name=name,
            required=required,
            passed=False,
            detail=detail,
            statement=statement,
        )
    return SurrealRetrievalCapabilityCheck(
        name=name,
        required=required,
        passed=True,
        detail="statement accepted by current runtime",
        statement=statement,
    )


def probe_surreal_native_retrieval_capabilities(
    connection: _SchemaConnectionProtocol,
    *,
    embedding_dimension: int,
    hnsw_ef: int = DEFAULT_HNSW_EF,
    vector_index_type: str = DEFAULT_SURREAL_HNSW_VECTOR_INDEX_TYPE,
    allow_target_mutation: bool = False,
) -> SurrealRetrievalCapabilityReport:
    if not allow_target_mutation:
        raise ValueError("capability probe must run against an explicit scratch target")

    define_dotmd_surreal_schema(connection)
    retrieval_plan = build_surreal_native_retrieval_index_plan(
        embedding_dimension=embedding_dimension,
        hnsw_ef=hnsw_ef,
        vector_index_type=vector_index_type,
    )

    required_checks = (
        _run_probe_statement(
            connection,
            name="fts_analyzer",
            required=True,
            statement=retrieval_plan.analyzer_statement,
        ),
        _run_probe_statement(
            connection,
            name="fts_title_index",
            required=True,
            statement=retrieval_plan.bm25_index_statements[0],
        ),
        _run_probe_statement(
            connection,
            name="fts_text_index",
            required=True,
            statement=retrieval_plan.bm25_index_statements[1],
        ),
        _run_probe_statement(
            connection,
            name="hnsw_vector_index",
            required=True,
            statement=retrieval_plan.hnsw_index_statement,
        ),
        _run_probe_statement(
            connection,
            name="relation_table",
            required=True,
            statement="INFO FOR TABLE relations;",
        ),
        _run_probe_statement(
            connection,
            name="relations_target_id_idx",
            required=True,
            statement=retrieval_plan.relation_index_statements[1],
        ),
    )
    optional_observations = (
        _run_probe_statement(
            connection,
            name="fulltext_analyzer_v3",
            required=False,
            statement=(
                "DEFINE INDEX chunks_title_fulltext_probe_idx ON chunks FIELDS title FULLTEXT ANALYZER dotmd_fts BM25(1.2,0.75)"
            ),
        ),
        _run_probe_statement(
            connection,
            name="diskann_v3",
            required=False,
            statement=(
                "DEFINE INDEX embeddings_diskann_probe_idx ON TABLE embeddings FIELDS vector DISKANN DIMENSION 3 DIST COSINE;"
            ),
        ),
        _run_probe_statement(
            connection,
            name="built_in_hybrid_helpers",
            required=False,
            statement="RETURN search::rrf([], 10, 60);",
        ),
    )
    return SurrealRetrievalCapabilityReport(
        runtime_version=_runtime_version(connection),
        required_checks=required_checks,
        optional_observations=optional_observations,
    )


def define_dotmd_surreal_schema(
    connection: _SchemaConnectionProtocol | None = None,
) -> dict[str, Any]:
    plan = build_dotmd_surreal_schema_plan()
    validate_dotmd_surreal_schema_plan(plan)

    if connection is None:
        apply_status = SurrealSchemaApplyStatus(status="not-applied")
    else:
        apply_status = _inspect_existing_schema(connection, plan)
        if apply_status.status == "pending-apply":
            for statement in plan.statements:
                connection.query(statement)
            connection.query(
                "UPSERT schema_meta:dotmd_schema CONTENT $payload;",
                {
                    "payload": {
                        "schema_version": plan.schema_version,
                        "catalog_name": "dotmd",
                        "required_categories": list(plan.required_categories),
                        "metadata": {},
                    }
                },
            )
            apply_status = SurrealSchemaApplyStatus(
                status="applied",
                applied=True,
                reason=apply_status.reason,
                existing_version=apply_status.existing_version,
                statements_applied=len(plan.statements) + 1,
            )

    return {
        "schema_version": plan.schema_version,
        "tables": [table.name for table in plan.tables],
        "table_definitions": [_serialize_table(table) for table in plan.tables],
        "table_notes": {table.name: table.note for table in plan.tables},
        "statements": list(plan.statements),
        "required_categories": list(plan.required_categories),
        "unsupported_categories": list(plan.unsupported_categories),
        "preservation_notes": list(plan.preservation_notes),
        "downstream_phase_consumables": list(plan.downstream_phase_consumables),
        "apply_status": apply_status,
    }
