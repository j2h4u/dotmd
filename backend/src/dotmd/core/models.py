"""Pydantic domain models for dotMD."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from pathlib import Path

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
            document_ref = str(self.file_path.resolve())
            if self.document_ref != document_ref:
                raise ValueError(
                    "filesystem document_ref must match resolved file_path"
                )

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
    metadata_json: dict = Field(default_factory=dict)
    chunking_hints: dict = Field(default_factory=dict)


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


class SearchResult(BaseModel):
    """A single search result after fusion and optional reranking."""

    chunk_id: str
    ref: str
    heading_path: str
    snippet: str
    fused_score: float
    semantic_score: float | None = None
    keyword_score: float | None = None
    graph_score: float | None = None
    graph_direct_score: float | None = None
    matched_engines: list[str] = Field(default_factory=list)

    @field_validator("ref")
    @classmethod
    def _validate_ref(cls, value: str) -> str:
        namespace, separator, document_ref = value.partition(":")
        if not separator or not namespace or not document_ref:
            raise ValueError(
                "ref must be formatted as '<namespace>:<document_ref>'"
            )
        return value


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
    trickle_status: str | None = None  # "idle", "backlog", "watching", "stopping", or None if not running
    trickle_indexed: int | None = None  # files indexed so far in current run
    trickle_total: int | None = None  # total files to index in current run
    trickle_current_file: str | None = None  # file currently being processed
    trickle_chunks_per_hour: float | None = None  # chunk throughput (TEI bottleneck)
    trickle_files_per_hour: float | None = None  # file throughput (for capacity estimates)
    trickle_eta_minutes: float | None = None  # estimated time remaining
