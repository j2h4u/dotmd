"""Pydantic domain models for dotMD."""

from __future__ import annotations

import hashlib
from datetime import datetime
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, Field, computed_field


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

    @computed_field  # type: ignore[prop-decorator]
    @property
    def checksum(self) -> str:
        """blake2b hash of raw file bytes including frontmatter. Reads from disk on every access.

        Used only for graph File nodes (informational). For change detection,
        use ``reader.chunk_checksum()`` (body+kind) or ``reader.embed_checksum()``
        (body+kind+title+tags). Raises ``FileNotFoundError`` if the file no longer exists.
        """
        return hashlib.blake2b(self.path.read_bytes()).hexdigest()


class Chunk(BaseModel):
    """A section of a markdown file after chunking."""

    chunk_id: str
    file_path: Path
    heading_hierarchy: list[str] = Field(default_factory=list)
    level: int = 0
    text: str
    chunk_index: int
    char_offset: int
    kind: str = DocKind.DOCUMENT

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
    file_path: Path
    heading_path: str
    snippet: str
    fused_score: float
    semantic_score: float | None = None
    keyword_score: float | None = None
    graph_score: float | None = None
    graph_direct_score: float | None = None
    matched_engines: list[str] = Field(default_factory=list)


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
