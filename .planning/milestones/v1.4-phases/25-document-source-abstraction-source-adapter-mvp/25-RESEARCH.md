# Phase 25: Document Source Abstraction - source adapter MVP - Research

**Researched:** 2026-05-05
**Status:** Complete
**Mode:** Research first

## Research Question

What needs to be known to plan Phase 25 well: a filesystem Markdown
compatibility shim through a new source-aware internal model, without pulling
Telegram, source assets, entity catalogs, out-of-process adapter transports,
TTL policy, or second-source validation into this phase?

## Executive Summary

Phase 25 should be planned as a compatibility-preserving internal refactor. The
current filesystem Markdown path already has useful ingredients: `FileInfo`
captures discovered-document metadata, `Chunk` is path-independent enough after
the Phase 16 M2M rewrite, and `chunk_checksum()` / `meta_checksum()` preserve
the body/kind versus title/tags distinction. The missing piece is an explicit
source/document/source-unit/provenance model at the ingestion boundary and
persistence layer.

The minimum implementation path is:

1. Add source-aware domain models and a filesystem Markdown adapter contract.
2. Map current Markdown discovery into `namespace=filesystem`,
   `document_ref=<normalized path>`, `ref=filesystem:<document_ref>`,
   `media_type=text/markdown`, and `parser_name=markdown`.
3. Attach source-unit provenance to emitted chunks without changing current
   chunk text, chunk IDs, frontmatter semantics, or MCP read behavior.
4. Persist only compatibility-critical provenance and metadata needed for the
   next source slice.
5. Verify current filesystem search/read behavior, metadata-only fast path, and
   delete behavior remain stable.

## Canonical Inputs Read

- `.planning/ROADMAP.md` - Phase 25 scope, dependency on Phase 24, and backlog
  source `999.22`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
  - locked user decisions D-01 through D-11.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-ARCHITECTURE-PANEL.md`
  - minimal shim contract and acceptance gate.
- `docs/source-adapter-architecture.md` - vocabulary and future architecture.
- `docs/source-adapter-architecture-panel-review.md` - risks and scoped
  expert-panel recommendations.
- `backend/src/dotmd/core/models.py` - current `FileInfo`, `Chunk`, and
  `SearchResult` shapes.
- `backend/src/dotmd/ingestion/reader.py` - Markdown discovery, frontmatter
  parsing, and fingerprint formulas.
- `backend/src/dotmd/ingestion/chunker.py` - current chunk text and chunk ID
  behavior.
- `backend/src/dotmd/ingestion/pipeline.py` - indexing orchestration,
  fingerprint gates, vector/FTS/graph writes, and deletes.
- `backend/src/dotmd/storage/metadata.py` - chunks table and file-path M2M
  persistence.
- `backend/src/dotmd/api/service.py` and `backend/src/dotmd/mcp_server.py` -
  public search/read behavior to preserve.

## Current Behavior To Preserve

### Discovery and Metadata

- `discover_files()` and `discover_files_multi()` discover only non-empty
  `.md` files.
- `FileInfo` carries `path`, `title`, `last_modified`, `size_bytes`, `kind`,
  and `frontmatter`.
- `parse_frontmatter()` strips YAML frontmatter and returns a dict plus body.
- `title` is frontmatter `title`, then the first top-level `#` heading, then
  file stem.
- `kind` defaults to `DocKind.DOCUMENT` and controls chunk pre-splitting.

### Fingerprints and Incrementality

- `chunk_checksum(path)` hashes `kind + "\n" + body`.
- `meta_checksum(path)` hashes `title + "\n" + sorted(tags)`.
- The pipeline uses a chunk tracker and meta tracker separately:
  body/kind changes re-chunk; title/tag changes can reuse existing chunk text
  and run the metadata-only embedding path.
- The plan must keep this split visible in the new adapter contract. A generic
  event or metadata blob that hides these fingerprints would likely regress
  indexing cost.

### Chunking and Search Inputs

- `chunk_file()` strips frontmatter before chunking.
- Chunk IDs are content-addressed from `body_checksum`, chunk index, and
  `chunk_strategy`, not from file path.
- Chunks currently carry `file_paths`, `heading_hierarchy`, `level`, `text`,
  `chunk_index`, and `kind`.
- `kind` selects content handlers for documents, meeting transcripts, and
  voicenotes.
- Search quality should not change in Phase 25; chunk text and frontmatter
  metadata signals should remain equivalent.

### Persistence and Read Compatibility

- `chunks_<strategy>` stores chunk payload by `chunk_id`.
- `chunk_file_paths_<strategy>` stores `(chunk_id, file_path, chunk_index)`.
- `SearchResult.file_paths` remains the public search compatibility field.
- MCP `search` returns `file_paths`, snippet, score, and optional heading.
- MCP `read(file_path, start, end)` remains the current deep-read path.

## Minimal Phase 25 Model

The implementation should make these concepts explicit, with final names left
to the implementer as long as the concepts remain visible:

### SourceDocument

Required fields for the filesystem shim:

- `namespace`
- `document_ref`
- `ref`
- `title`
- `source_uri`
- `media_type`
- `parser_name`
- `document_type`
- `updated_at`
- `content_fingerprint`
- `metadata_fingerprint`
- `metadata_json`
- compatibility `file_path` for filesystem documents

Filesystem mapping:

- `namespace = "filesystem"`
- `document_ref = stable normalized path/ref for one Markdown file`
- `ref = "filesystem:<document_ref>"`
- `source_uri = file path or file URI chosen consistently`
- `media_type = "text/markdown"`
- `parser_name = "markdown"`
- `document_type = current frontmatter kind`

### SourceUnit

Required fields for the shim:

- `namespace`
- `document_ref`
- `unit_ref`
- `unit_type`
- `text`
- `order_key`
- `fingerprint`
- `metadata_json`
- optional chunking hints

For Phase 25, source units can be parser-emitted Markdown sections,
paragraph-like pieces, or a thin unit wrapper around the existing chunker input.
The key requirement is that chunks can record which source unit refs they came
from without changing chunk text.

### Chunk Provenance

Required fields to attach to chunks:

- `namespace`
- `document_ref`
- `source_unit_refs[]`
- `chunk_strategy`
- optional `parser_name`
- existing chunk payload and heading metadata

Do not require durable raw source-unit storage unless current behavior cannot
be reproduced otherwise. Provenance and fingerprints are enough for Phase 25.

## Recommended Plan Shape

### Plan 25-01 - Domain Models and Filesystem Adapter Contract

Define source-aware model objects and a filesystem Markdown adapter that wraps
current reader behavior. Keep the adapter in-process and Protocol-style. This
plan should not modify search behavior yet.

Key files:

- `backend/src/dotmd/core/models.py`
- new `backend/src/dotmd/ingestion/source.py` or
  `backend/src/dotmd/ingestion/sources.py`
- `backend/src/dotmd/ingestion/reader.py`
- new `backend/tests/ingestion/test_source_filesystem.py`

### Plan 25-02 - Pipeline Routing and Compatibility Preservation

Route current Markdown indexing through the adapter-backed document/unit path.
Keep `discover_files()` or compatibility wrappers available if existing tests
and public callers use them. Preserve `file_paths`, chunk text, frontmatter
metadata, and fingerprint behavior.

Key files:

- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/chunker.py`
- `backend/tests/ingestion/test_incremental_pipeline.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_pipeline_purge.py`

### Plan 25-03 - Provenance Persistence and Read/Search Hydration

Persist source document/chunk provenance in SQLite with an additive schema
change. Keep M2M file-path compatibility authoritative for filesystem search
and read. Add hydration only where it does not break existing `SearchResult`
and MCP output.

Key files:

- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`

### Plan 25-04 - Regression Verification and Documentation

Add focused regression tests and documentation for the shim contract. The
tests should prove current Markdown indexing/search/read behavior did not drift
and future Telegram work remains deferred.

Key files:

- `backend/tests/ingestion/`
- `backend/tests/api/`
- `backend/tests/mcp/`
- `docs/source-adapter-architecture.md`
- `docs/architecture.md`

## Validation Strategy

Phase 25 should pass local tests without live TEI/FalkorDB containers. The
plans should require:

- Unit tests for filesystem adapter output:
  `namespace`, `document_ref`, `ref`, `media_type`, `parser_name`,
  `document_type`, `metadata_json`, content fingerprint, metadata fingerprint.
- Chunking compatibility tests proving existing chunk text and heading
  hierarchy remain unchanged for representative Markdown frontmatter and body.
- Metadata-only tests proving title/tag changes do not require body
  re-chunking and preserve the existing one-metadata-embedding path.
- Delete tests proving removed filesystem Markdown purges current file-path
  associations and source provenance at least as well as existing behavior.
- Search/result-shape tests proving `SearchResult.file_paths` remains present.
- MCP tests proving `search` still returns `file_paths` and
  `read(file_path, start, end)` remains valid.
- A grep/static test or documentation check proving the Phase 25 plans and docs
  do not add runtime Telegram, `SourceAsset`, entity catalog, TTL policy,
  out-of-process adapter transport, or second-source validation implementation
  tasks.

Recommended command set for plan verification:

```bash
cd backend
uv run pytest tests/ingestion tests/storage tests/api tests/mcp
uv run pyright
```

If the repo's `just` workflow wraps these commands, use the `just` target
instead during execution.

## Threat Model

### TH-25-01: Raw Source Unit Retention Expands Private Data Storage

Severity: medium

Phase 25 is filesystem-only, but a speculative source-unit mirror could retain
more private text than current chunk/search/read behavior. Mitigation: plans
must store provenance and fingerprints first; durable raw source units are
deferred unless required for compatibility.

### TH-25-02: Compatibility Ref Leak Confuses Agent Read Calls

Severity: medium

If search begins returning refs without preserving `file_paths`, agents may
call the wrong read path. Mitigation: keep `file_paths` and
`read(file_path, start, end)` stable. Any `ref` exposure must be additive and
tested.

### TH-25-03: Delete Regression Retains Removed File Content

Severity: high

Changing identity from `file_path` to `document_ref` could leave orphan chunks,
vectors, FTS rows, graph nodes, or provenance rows. Mitigation: delete tests
must cover both existing M2M cleanup and any new source provenance tables.

### TH-25-04: Fingerprint Regression Causes Costly Re-Embedding

Severity: medium

If content and metadata fingerprints collapse into one generic checksum,
metadata-only frontmatter edits can trigger full re-chunk/re-embed. Mitigation:
adapter contract must expose content and metadata fingerprints separately, and
tests must cover title/tag-only changes.

## Explicit Deferrals

Do not plan implementation tasks for:

- Telegram read-only adapter.
- `mcp-telegram` export API.
- Source assets, binary attachments, PDF/DOCX/HTML parsing.
- Entity catalogs, `SourceEntity`, `Mention`, `CanonicalEntity`, or fuzzy
  identity resolution.
- Out-of-process adapter transports such as Unix socket, HTTP, MCP, command
  invocation, or service daemon.
- TTL/soft-delete retention policy changes.
- Per-source scheduler/status/retry/backpressure infrastructure.
- Second-source validation with Perplexity, Notion, Google Docs, or another
  exporter.

## Planning Acceptance Gate

The generated `PLAN.md` files must answer:

- What is the canonical internal ref for a filesystem Markdown document?
- Where is `file_path` still intentionally preserved for compatibility?
- What object owns frontmatter metadata after the shim?
- How are source-unit refs attached to chunks?
- What schema or storage changes are required?
- How does metadata-only change detection still avoid full re-chunking?
- Which tests prove user-visible behavior did not change?

## RESEARCH COMPLETE
