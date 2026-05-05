# Phase 25: Document Source Abstraction - source adapter MVP - Context

**Gathered:** 2026-05-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Reproduce today's filesystem Markdown indexing behavior through a new,
source-aware internal model.

This phase should introduce the smallest useful source/document/source-unit
abstraction while preserving current behavior for `.md` files. It is not the
Telegram integration phase. Telegram read-only remains the first intended real
non-filesystem validation source after the filesystem shim proves the contract.

</domain>

<decisions>
## Implementation Decisions

### MVP Shape

- **D-01:** Phase 25 should first make current behavior work through a better
  implementation, not add a new data source. Existing filesystem Markdown
  indexing should become an adapter-backed path with the same product behavior.
- **D-02:** The new model should start with the minimum concepts needed to stop
  treating `file_path` as the universal identity: `namespace`, `document_ref`,
  canonical `ref`, source-unit provenance, parser/media metadata, and chunk
  provenance.
- **D-03:** Filesystem remains the first source namespace. Markdown remains the
  first parser/content format. PDF/DOCX/HTML support is not part of this phase.

### Architecture Panel Gate

- **D-04:** Before planning implementation details, the domain model and
  contracts need an expert-panel pass with architecture, data/indexing,
  retrieval, graph, security/privacy, QA, and operations perspectives.
- **D-05:** The panel should agree the contract boundaries, not invent a large
  future platform. It must decide the minimal model needed for the filesystem
  compatibility shim and explicitly mark Telegram, assets, entity catalogs,
  fuzzy identity resolution, and second-source validation as later slices unless
  a tiny piece is required for the shim.
- **D-06:** The existing backlog context is sufficient input for the panel:
  `docs/source-adapter-architecture.md` and
  `docs/source-adapter-architecture-panel-review.md` already capture the
  vocabulary, trade-offs, and risks.

### Telegram Boundary

- **D-07:** Telegram read-only is the first intended non-filesystem source, but
  it should not be implemented in Phase 25. Planning may keep Telegram examples
  in tests or docs only where they clarify the contract.
- **D-08:** dotMD should not read `mcp-telegram` private SQLite tables directly.
  The future Telegram adapter needs an export-oriented contract from
  `mcp-telegram`, but that belongs to a later phase unless planning finds a
  strictly non-runtime fixture useful.

### Compatibility Expectations

- **D-09:** Existing search/read behavior for current Markdown files must stay
  compatible from the user's perspective.
- **D-10:** Current frontmatter semantics remain document metadata: `title`,
  `kind`, `tags`, and `participants` must keep feeding chunking, metadata
  embeddings, FTS, and graph behavior as they do today.
- **D-11:** Existing incremental behavior remains important. The new model must
  preserve the distinction between content/kind changes and metadata-only
  changes instead of forcing unnecessary re-chunking or re-embedding.

### the agent's Discretion

- Choose the smallest code shape that makes the source model explicit without
  rewriting the entire ingestion stack in one pass.
- Decide whether the panel output should be a separate design note or folded
  into the Phase 25 research/plan artifacts, as long as downstream planning has
  a clear contract to follow.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Definition

- `.planning/ROADMAP.md` - Phase 25 goal, scope, dependency, and backlog source
  `999.22`.
- `.planning/STATE.md` - current workflow state and Phase 25 promotion note.
- `.planning/REQUIREMENTS.md` - v1.4 context; no dedicated Phase 25
  requirement is currently mapped.

### Source Adapter Architecture

- `docs/source-adapter-architecture.md` - source/document/source-unit/chunk
  vocabulary, source assets, metadata layers, source entity catalogs,
  cross-source identity resolution, parser/content-format axis, and MVP shape.
- `docs/source-adapter-architecture-panel-review.md` - expert-panel review and
  conflicts covering product scope, retrieval, indexing, graph, integration
  contracts, metadata, assets, security/privacy, QA, operations, and Kaizen
  scope control.
- `docs/architecture.md` - top-level architecture index linking to the source
  adapter context.

### Current Filesystem Markdown Path

- `backend/src/dotmd/core/models.py` - current `FileInfo`, `Chunk`, and
  `SearchResult` identity model.
- `backend/src/dotmd/ingestion/reader.py` - current Markdown discovery,
  frontmatter parsing, file checksums, and metadata checksums.
- `backend/src/dotmd/ingestion/chunker.py` - current Markdown/content-aware
  chunking behavior.
- `backend/src/dotmd/ingestion/pipeline.py` - current indexing orchestration,
  file trackers, storage writes, embeddings, FTS, extraction, and graph
  population.
- `backend/src/dotmd/storage/metadata.py` - current chunk table plus
  file-path M2M persistence.
- `backend/src/dotmd/api/service.py` - public indexing/search facade and search
  result hydration path.
- `backend/src/dotmd/mcp_server.py` - MCP `search` and `read` contract that
  current agents already use.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `FileInfo` already carries discovered-document metadata for filesystem
  Markdown: path, title, modification time, size, kind, and frontmatter.
- `Chunk` already separates chunk identity from `file_paths` through Phase 16's
  M2M model, which gives the source abstraction a useful starting point.
- `chunk_checksum()` and `meta_checksum()` already encode the important
  distinction between body/kind changes and title/tag metadata changes.
- `SQLiteMetadataStore` already has chunk persistence and file-path association
  helpers that can be evolved toward source/document references.

### Established Patterns

- dotMD uses Protocol-style boundaries for storage, search, and extraction.
  Source adapters should follow that style instead of exposing private tables
  directly.
- Public behavior should go through `DotMDService`, CLI, MCP, and FastAPI
  layers rather than leaking ingestion internals.
- Tests should stay tiered: local tests must not require live containers, and
  explicit live e2e remains a separate command.

### Integration Points

- `backend/src/dotmd/ingestion/reader.py` is the current source-discovery
  boundary and likely the first place to introduce a filesystem adapter shim.
- `backend/src/dotmd/ingestion/pipeline.py` is the main compatibility risk:
  it currently assumes discovered files and file-based trackers.
- `backend/src/dotmd/search/fusion.py`, `api/service.py`, and `mcp_server.py`
  define what search/read clients see; compatibility changes must be verified
  through those surfaces, not only through ingestion unit tests.

</code_context>

<specifics>
## Specific Ideas

- Treat Phase 25 as a contract-and-shim phase: same indexed Markdown corpus,
  same search/read behavior, cleaner internal identity model.
- Use Telegram examples in panel discussion because they reveal the future
  shape, but do not let Telegram implementation pull the phase out of MVP.
- The architecture panel should be practical and adversarial: the useful output
  is the minimum contract that can survive filesystem now and Telegram later.

</specifics>

<deferred>
## Deferred Ideas

- Telegram read-only source adapter implementation.
- `mcp-telegram` export API implementation.
- Source assets and binary attachment parsing.
- Entity catalogs, canonical identity resolution, and fuzzy/person-name merges.
- Second-source validation with Perplexity, Notion, Google Docs, or another
  exporter.

### Reviewed Todos (not folded)

- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` matched this
  phase strongly because it mentions deleted source files. Do not fold the TTL
  policy into Phase 25. Preserve today's delete behavior for filesystem
  compatibility; richer source-delete retention policy belongs to a later
  privacy/data-lifecycle phase.
- `2026-03-27-background-trickle-indexer.md` matched on file/indexing keywords
  but remains trickle scheduling work, not source model design.
- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` matched on
  broad graph/file keywords but is unrelated to the source adapter shim.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` matched
  on context keywords but remains embedding-model work.
- `2026-03-27-smoke-tests.md` matched on contract/testing keywords, but Phase
  23 already handled the test contract cleanup.

</deferred>

---

*Phase: 25-document-source-abstraction-source-adapter-mvp*
*Context gathered: 2026-05-05*
