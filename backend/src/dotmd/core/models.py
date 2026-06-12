"""Pydantic domain models for dotMD."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    computed_field,
    field_validator,
    model_validator,
)


class SearchMode(StrEnum):
    """Available search strategies."""

    SEMANTIC = "semantic"
    KEYWORD = "keyword"
    GRAPH = "graph"
    HYBRID = "hybrid"


class ExtractDepth(StrEnum):
    """Extraction depth levels."""

    STRUCTURAL = "structural"
    NER = "ner"


class DocKind(StrEnum):
    """Document kind from frontmatter ``kind`` field.

    Determines chunking pre-split strategy and enrichment via
    ``content_handlers.get_handler()``.
    """

    DOCUMENT = "document"
    MEETING_TRANSCRIPT = "meeting_transcript"
    VOICENOTE = "voicenote"


class TrickleStatus(StrEnum):
    """Background trickle indexer lifecycle states."""

    IDLE = "idle"
    BACKLOG = "backlog"
    WATCHING = "watching"
    STOPPING = "stopping"


class RelationType(StrEnum):
    """Edge types in the knowledge graph."""

    CONTAINS = "CONTAINS"
    HAS_TAG = "HAS_TAG"


class EntityType(StrEnum):
    """Node types for graph entities from frontmatter tags."""

    PERSON = "PERSON"
    TAG = "TAG"


class SourceCapability(StrEnum):
    """Closed source capability vocabulary for descriptor metadata."""

    LOCAL_SYNC = "local_sync"
    FEDERATED_SEARCH = "federated_search"
    READ_UNIT_WINDOW = "read_unit_window"
    MATERIALIZATION = "materialization"
    BROWSE_TREE = "browse_tree"
    ACL = "acl"
    INCREMENTAL_CURSOR = "incremental_cursor"


SOURCE_SCHEMA_FIELD_TYPES = frozenset({"str", "int", "bool", "path", "list[str]", "dict[str, Any]"})


class SourceDisplayMetadata(BaseModel):
    """Human-facing source display metadata."""

    model_config = ConfigDict(extra="forbid")

    display_name: str
    description: str
    labels: list[str] = Field(default_factory=list)
    docs_slug: str | None = None


class SourceSchemaField(BaseModel):
    """Declarative source configuration, auth, or cursor schema field."""

    model_config = ConfigDict(extra="forbid")

    name: str
    field_type: str
    required: bool = False
    description: str = ""

    @field_validator("field_type")
    @classmethod
    def _validate_field_type(cls, value: str) -> str:
        if value not in SOURCE_SCHEMA_FIELD_TYPES:
            raise ValueError(f"field_type must be one of {SOURCE_SCHEMA_FIELD_TYPES}")
        return value


class SourceConfigSchema(BaseModel):
    """Declarative source configuration schema."""

    model_config = ConfigDict(extra="forbid")

    name: str
    fields: list[SourceSchemaField] = Field(default_factory=list)
    empty: bool = False


class SourceAuthSchema(BaseModel):
    """Declarative source authentication schema."""

    model_config = ConfigDict(extra="forbid")

    auth_kind: str
    methods: list[str] = Field(default_factory=list)
    fields: list[SourceSchemaField] = Field(default_factory=list)
    delegated_to: str | None = None


class SourceCursorSchema(BaseModel):
    """Declarative source cursor schema."""

    model_config = ConfigDict(extra="forbid")

    cursor_kind: str
    examples: list[str] = Field(default_factory=list)
    description: str = ""


class SourceDescriptor(BaseModel):
    """Declarative source descriptor registered by namespace."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    source_kind: str
    display: SourceDisplayMetadata
    config_schema: SourceConfigSchema
    auth_schema: SourceAuthSchema
    cursor_schema: SourceCursorSchema
    capabilities: list[SourceCapability] = Field(default_factory=list)
    metadata_json: dict[str, Any] = Field(default_factory=dict)


class FileInfo(BaseModel):
    """Metadata about a discovered markdown file."""

    path: Path
    title: str
    last_modified: datetime
    size_bytes: int
    kind: str = DocKind.DOCUMENT
    frontmatter: dict = Field(default_factory=dict)


class SourceDocument(BaseModel):
    """Source-aware document identity and metadata."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    document_ref: str
    ref: str
    title: str
    source_uri: str
    media_type: str
    parser_name: str
    document_type: str = DocKind.DOCUMENT
    updated_at: datetime
    content_fingerprint: str
    metadata_fingerprint: str
    metadata_json: dict = Field(default_factory=dict)
    file_path: Path | None = None

    @model_validator(mode="after")
    def _validate_refs(self) -> SourceDocument:
        expected_ref = f"{self.namespace}:{self.document_ref}"
        if self.ref != expected_ref:
            raise ValueError(f"ref must be {expected_ref!r}")

        if self.namespace == "filesystem" and self.file_path is not None:
            file_path_ref = str(self.file_path)
            resolved_ref = str(self.file_path.resolve())
            if self.document_ref not in {file_path_ref, resolved_ref}:
                raise ValueError(
                    "filesystem document_ref must match file_path or resolved file_path"
                )

        return self


class ResourceBinding(BaseModel):
    """Active/inactive binding between a source resource and a document ref."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    resource_ref: str
    document_ref: str
    ref: str
    active: bool = True
    bound_at: datetime
    unbound_at: datetime | None = None
    content_fingerprint: str
    metadata_fingerprint: str
    source_unit_refs: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_refs(self) -> ResourceBinding:
        expected_ref = f"{self.namespace}:{self.document_ref}"
        if self.ref != expected_ref:
            raise ValueError(f"ref must be {expected_ref!r}")

        if self.namespace == "filesystem" and self.resource_ref != self.document_ref:
            raise ValueError("filesystem resource_ref must match document_ref")

        return self


class SourceUnit(BaseModel):
    """Parser-emitted unit before dotMD chunking."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    document_ref: str
    unit_ref: str
    unit_type: str
    text: str
    order_key: str
    fingerprint: str
    updated_at: datetime
    metadata_json: dict = Field(default_factory=dict)
    chunking_hints: dict = Field(default_factory=dict)


class SourceUnitWindow(BaseModel):
    """Neighboring source units around a provider-owned unit reference."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    document_ref: str
    unit_ref: str
    units: list[SourceUnit]
    metadata_json: dict = Field(default_factory=dict)


LEGACY_CAPABILITY_ALIASES: dict[str, str] = {
    "unit-window": SourceCapability.READ_UNIT_WINDOW.value,
    "incremental-export": SourceCapability.INCREMENTAL_CURSOR.value,
}


class ApplicationSourceDescription(BaseModel):
    """Description of an application source exposed by a provider."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    source_kind: str
    display_name: str
    capabilities: list[str] = Field(default_factory=list)
    metadata_json: dict = Field(default_factory=dict)

    @classmethod
    def from_descriptor(
        cls,
        descriptor: SourceDescriptor,
    ) -> ApplicationSourceDescription:
        """Build the lightweight provider description from a descriptor."""
        return cls(
            namespace=descriptor.namespace,
            source_kind=descriptor.source_kind,
            display_name=descriptor.display.display_name,
            capabilities=[capability.value for capability in descriptor.capabilities],
            metadata_json=dict(descriptor.metadata_json),
        )

    def normalized_capabilities(self) -> list[str]:
        """Return canonical capability strings for comparison."""
        return [
            LEGACY_CAPABILITY_ALIASES.get(capability, capability)
            for capability in self.capabilities
        ]


class ApplicationSourceChange(BaseModel):
    """One active source change carrying a document envelope and source unit."""

    model_config = ConfigDict(extra="forbid")

    document: SourceDocument
    unit: SourceUnit


class ApplicationSourceChangeBatch(BaseModel):
    """Provider export batch with cursors controlled by the provider."""

    model_config = ConfigDict(extra="forbid")

    changes: list[ApplicationSourceChange] = Field(default_factory=list)
    next_cursor: str | None = None
    checkpoint_cursor: str | None = None
    updated_after: str | None = None
    updated_after_cursor: str | None = None


class ChunkProvenance(BaseModel):
    """Source-unit provenance attached to a dotMD chunk."""

    model_config = ConfigDict(extra="forbid")

    namespace: str
    document_ref: str
    ref: str
    source_unit_refs: list[str] = Field(default_factory=list)
    chunk_strategy: str
    parser_name: str | None = None


class Chunk(BaseModel):
    """A section of a markdown file after chunking.

    Phase 16 (Decision #8): char_offset dropped; file_path replaced by
    file_paths: list[Path] (single-element list when emitted by the chunker).
    chunk_index stays on the Chunk at creation time but is stored only in the
    chunk_file_paths_* M2M table, not in chunks_* columns.
    """

    model_config = ConfigDict(extra="forbid")

    chunk_id: str
    file_paths: list[Path] = Field(default_factory=list)
    heading_hierarchy: list[str] = Field(default_factory=list)
    level: int = 0
    text: str
    chunk_index: int
    kind: str = DocKind.DOCUMENT
    provenance: ChunkProvenance | None = None

    @computed_field  # type: ignore[prop-decorator]
    @property
    def heading(self) -> str:
        return self.heading_hierarchy[-1] if self.heading_hierarchy else ""


class Entity(BaseModel):
    """A named entity extracted from a chunk."""

    name: str
    type: str
    source: str  # "structural", "ner"
    chunk_ids: list[str] = Field(default_factory=list)


class Relation(BaseModel):
    """A relation between two entities or nodes."""

    source_id: str
    target_id: str
    relation_type: str
    weight: float = 1.0
    properties: dict[str, str] = Field(default_factory=dict)


class ExtractionResult(BaseModel):
    """Output from an extractor: entities and relations found in chunks."""

    entities: list[Entity] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)


class ExpandedQuery(BaseModel):
    """A query after expansion."""

    original: str
    expanded_terms: list[str] = Field(default_factory=list)
    expanded_text: str = ""


class SearchCandidate(BaseModel):
    """A single search candidate from local or federated sources.

    This is the unified public search result type at both service and MCP layers.

    Container fields (matched_engines, engine_scores, provider_metadata) are
    shallow-frozen by Pydantic's frozen=True: attribute rebinding is rejected,
    but container content mutation (list.append, dict assignment) succeeds. This
    is documented behavior and callers must not mutate after construction.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    # Core identity and content
    ref: str
    namespace: str
    descriptor_key: str  # Required — identifies the source descriptor
    source_kind: str
    retrieval_kind: str
    title: str | None = None
    snippet: str
    fused_score: float

    # Readability and materialization
    can_read: bool
    can_materialize: bool = False

    # Local-specific provenance
    chunk_id: str | None = None
    heading_path: str | None = None
    provenance: ChunkProvenance | None = None

    # Matched engines and per-engine scores
    matched_engines: tuple[str, ...] = Field(default_factory=tuple)
    engine_scores: dict[str, float] | None = None

    # Federated-specific fields
    source_native_score: float | None = None
    source_native_rank: int | None = None
    provider_metadata: dict[str, Any] | None = None

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, value: str) -> str:
        namespace, separator, document_ref = value.partition(":")
        if not separator or not namespace or not document_ref:
            raise ValueError("ref must be formatted as '<namespace>:<document_ref>'")
        return value


class SourceStatus(BaseModel):
    """Status report for a single source engine during search."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    status: Literal["ok", "skipped", "error"]
    reason: str | None = None
    candidate_count: int = 0
    elapsed_ms: float | None = None


class SearchResponse(BaseModel):
    """Envelope for search results including per-source status."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidates: list[SearchCandidate] = Field(default_factory=list)
    source_status: list[SourceStatus] = Field(default_factory=list)


class IndexStats(BaseModel):
    """Summary statistics about the current index."""

    total_files: int = 0
    total_chunks: int = 0
    total_entities: int = 0
    total_edges: int = 0
    last_indexed: datetime | None = None
    new_files: int = 0
    modified_files: int = 0
    deleted_files: int = 0
    unchanged_files: int = 0
    data_dir: str | None = None

    # Trickle indexer progress
    trickle_status: str | None = (
        None  # "idle", "backlog", "watching", "stopping", or None if not running
    )
    trickle_indexed: int | None = None  # files indexed so far in current run
    trickle_total: int | None = None  # total files to index in current run
    trickle_current_file: str | None = None  # file currently being processed
    trickle_chunks_per_hour: float | None = None  # chunk throughput (TEI bottleneck)
    trickle_files_per_hour: float | None = None  # file throughput (for capacity estimates)
    trickle_eta_minutes: float | None = None  # estimated time remaining
