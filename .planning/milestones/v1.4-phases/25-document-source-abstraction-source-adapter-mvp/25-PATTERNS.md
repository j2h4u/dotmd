# Phase 25: Document Source Abstraction - Pattern Map

**Mapped:** 2026-05-05
**Status:** Complete

## Purpose

Concrete code patterns the Phase 25 executor should read before modifying the
source-aware filesystem Markdown shim. This map is scoped to filesystem
Markdown compatibility only.

## Files To Create Or Modify

| File | Role | Closest Existing Pattern |
|------|------|--------------------------|
| `backend/src/dotmd/core/models.py` | Domain model definitions for source documents, source units, and chunk provenance | Existing Pydantic `FileInfo`, `Chunk`, `SearchResult` models with `ConfigDict(extra="forbid")` on `Chunk` |
| `backend/src/dotmd/ingestion/source.py` or `backend/src/dotmd/ingestion/sources.py` | New Protocol-style source adapter boundary and filesystem Markdown adapter | Storage/search Protocol boundaries plus current `reader.py` discovery helpers |
| `backend/src/dotmd/ingestion/reader.py` | Compatibility wrappers for `.md` discovery, frontmatter parsing, checksums | Current `discover_files_multi()`, `_add_file()`, `chunk_checksum()`, `meta_checksum()` |
| `backend/src/dotmd/ingestion/chunker.py` | Attach provenance without changing Markdown chunk text | Current `chunk_file()` signature and `Chunk(...)` construction |
| `backend/src/dotmd/ingestion/pipeline.py` | Route indexing through adapter-backed documents/units and preserve fingerprint paths | Current `index()`, `_chunk_files()`, `_save_and_embed_chunks()`, `_incremental_index()` |
| `backend/src/dotmd/storage/metadata.py` | Add additive provenance persistence while keeping `chunk_file_paths_*` compatibility | Existing M2M DDL helpers and idempotent `INSERT OR IGNORE` methods |
| `backend/src/dotmd/search/fusion.py` | Hydrate additive source refs only after preserving `file_paths` | Current batch hydration via `get_file_paths_for_chunk_ids()` |
| `backend/src/dotmd/api/service.py` | Preserve `read(file_path, start, end)` and search facade behavior | Existing `ReadPayload` and `search()` result path |
| `backend/src/dotmd/mcp_server.py` | Preserve MCP `search` and `read` compatibility | Existing `SearchHit.file_paths` and `read_document(file_path, ...)` |
| `backend/tests/ingestion/test_source_filesystem.py` | New adapter contract tests | Existing ingestion tests with tmp_path fixtures and mocked TEI |
| `backend/tests/ingestion/test_metadata_only_reindex.py` | Regression coverage for metadata-only path | Existing encode call counting pattern |
| `backend/tests/ingestion/test_pipeline_purge.py` | Delete/provenance cleanup coverage | Existing holder-aware purge patterns |
| `backend/tests/storage/test_metadata_m2m.py` | SQLite provenance and M2M coverage | Existing minimal sqlite schema tests |
| `backend/tests/api/test_search_result_shape.py` | Search result compatibility coverage | Existing `SearchResult.file_paths` assertions |
| `backend/tests/mcp/test_search_tool.py` | MCP output compatibility coverage | Existing stubbed `mcp.mcp.call_tool()` tests |

## Current Model Patterns

`FileInfo` is the existing discovered-document model:

```python
class FileInfo(BaseModel):
    """Metadata about a discovered markdown file."""

    path: Path
    title: str
    last_modified: datetime
    size_bytes: int
    kind: str = DocKind.DOCUMENT
    frontmatter: dict = Field(default_factory=dict)
```

Use this as the migration bridge, not the final universal identity. New source
models should be additive and explicit:

- `namespace`
- `document_ref`
- `ref`
- `source_uri`
- `media_type`
- `parser_name`
- `document_type`
- content and metadata fingerprints
- `metadata_json`
- filesystem compatibility path

`Chunk` currently rejects unknown fields:

```python
class Chunk(BaseModel):
    model_config = ConfigDict(extra="forbid")
```

Any chunk provenance fields must be added deliberately and tested, not passed
as accidental extras.

## Reader and Fingerprint Patterns

Current frontmatter parsing is tolerant and should remain the source of truth
for Markdown:

```python
def parse_frontmatter(content: str) -> tuple[dict, str]:
    if not content.startswith("---"):
        return {}, content
```

The checksum split is a hard compatibility invariant:

```python
def chunk_checksum(path: Path) -> str:
    content = read_file(path)
    frontmatter, body = parse_frontmatter(content)
    kind = frontmatter.get("kind", DocKind.DOCUMENT)
    payload = f"{kind}\n{body}"
    return blake3.blake3(payload.encode()).hexdigest()
```

```python
def meta_checksum(path: Path) -> str:
    content = read_file(path)
    frontmatter, _ = parse_frontmatter(content)
    title = str(frontmatter.get("title", "") or "")
    tags = frontmatter.get("tags", []) or []
    tags_str = ",".join(sorted(str(t) for t in tags)) if tags else ""
    return blake3.blake3(f"{title}\n{tags_str}".encode()).hexdigest()
```

The filesystem adapter should reuse these formulas or centralize them behind
source document fingerprint fields without changing behavior.

## Chunking Patterns

`chunk_file()` strips frontmatter and constructs path-compatible chunks:

```python
_, body = parse_frontmatter(content)
body_checksum = _blake3.blake3(f"{kind}\n{body}".encode()).hexdigest()
```

Chunk construction currently sets `file_paths=[file_path]` and `chunk_index`.
Phase 25 can attach provenance, but must not change:

- body/frontmatter stripping;
- heading hierarchy computation;
- kind-specific pre-split handler;
- chunk text;
- `chunk_id` formula unless explicitly documented and tested.

## Pipeline Patterns

`IndexingPipeline.index()` currently starts with `discover_files(directory)`.
The adapter-backed route should preserve that public behavior while moving the
boundary:

```python
files = discover_files(directory)
diff = self._chunk_tracker.diff(files)
```

The metadata-only path is split from body changes:

```python
meta_diff = self._meta_tracker.diff(files)
meta_changed_paths = set(meta_diff.new) | set(meta_diff.modified)
```

The chunk save/embed path groups by `chunk.file_paths[0]`. If `SourceDocument`
becomes the authoritative internal identity, the plan must still preserve this
grouping or replace it with a source-document keyed equivalent that can recover
the compatibility file path.

## Metadata Store Patterns

Current additive persistence is per-strategy and idempotent:

```python
CREATE TABLE IF NOT EXISTS chunk_file_paths_{strategy} (
    chunk_id    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)
```

Use the same pattern for source provenance:

- strategy-scoped table names where the data is chunk-strategy-specific;
- `CREATE TABLE IF NOT EXISTS`;
- `INSERT OR IGNORE` or explicit upsert semantics;
- caller-owned transaction boundaries for purge cascades;
- no replacement of `chunk_file_paths_*` in Phase 25.

Delete helpers currently return orphans after removing M2M rows. Any provenance
table must be cleaned in the same holder-aware cascade path.

## API and MCP Compatibility Patterns

MCP search output is already array-shaped:

```python
class SearchHit(BaseModel):
    file_paths: list[str]
```

MCP read is still path-based:

```python
async def read_document(file_path: str, start: int = 0, end: int | None = None)
```

Phase 25 may add an internal `ref` and possibly additive result metadata, but
must not remove `file_paths` or break `read(file_path, start, end)`.

## Test Patterns

Use existing local, container-free test style:

- `tmp_path` for Markdown fixtures and sqlite databases;
- `MagicMock` for TEI `encode_batch`;
- count encode calls for metadata-only invariants;
- stub MCP service for output shape tests;
- minimal sqlite schema setup for storage helpers.

Representative commands for execution-phase verification:

```bash
cd backend
uv run pytest tests/ingestion tests/storage tests/api tests/mcp
uv run pyright
```

## Explicit Non-Patterns For Phase 25

Do not follow or introduce these patterns in Phase 25:

- direct reads from `mcp-telegram` private SQLite tables;
- runtime Telegram adapter implementation;
- `SourceAsset`, `SourceEntity`, `Mention`, or `CanonicalEntity` tables;
- Unix socket, HTTP, MCP, command, or daemon adapter transports;
- TTL or soft-delete retention policy;
- source scheduler/status/retry/backpressure infrastructure;
- search quality tuning or reranker changes.

## PATTERN MAPPING COMPLETE
