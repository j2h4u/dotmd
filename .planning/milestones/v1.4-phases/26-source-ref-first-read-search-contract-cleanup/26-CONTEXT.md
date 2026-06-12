# Phase 26: source-ref-first-read-search-contract-cleanup - Context

**Gathered:** 2026-05-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Remove the Phase 25 filesystem-path-first compatibility layer from dotMD's
public read/search contract before Telegram or other non-filesystem sources are
implemented.

This phase should make `ref` the primary public identity flowing from search to
read/drill. It should clean MCP/API/service-facing contracts and the
`SearchResult` domain shape, while preserving internal filesystem path usage
where it is still needed for filesystem discovery, local file reads, delete
detection, display/debugging, or content-dedup holder mechanics.

This is not the Telegram adapter phase. It is the cleanup that prevents Telegram
from inheriting a filesystem-shaped API.

</domain>

<decisions>
## Implementation Decisions

### Public Source Identity

- **D-01:** The public search-to-read key is a single string `ref`.
  Filesystem refs use the existing Phase 25 form:
  `filesystem:<document_ref>`, where `document_ref =
  str(Path(file_path).resolve())`.
- **D-02:** Public MCP/API callers should pass `ref`, not
  `{namespace, document_ref}` and not a JSON `source_ref` object. Internally the
  service may parse the string back into `namespace` and `document_ref`.
- **D-03:** The `ref` string is both the stable read key and the readable source
  pointer for filesystem results. Do not add `display_path`, `source_uri`, or
  deprecated `file_paths` to the public search result just to preserve old
  readability.

### Search Result Contract

- **D-04:** Public `search` responses should remove `file_paths` immediately and
  return `ref` as the primary identity.
- **D-05:** The target MCP search hit shape is approximately:
  `{ ref, heading?, snippet, score }`.
- **D-06:** If a prettier human label becomes useful later, it should be a
  neutral additive field such as `title`, not a filesystem-path-shaped public
  identity.

### Read and Drill Tools

- **D-07:** Replace MCP/service read input from `file_path` to `ref`.
  `read(ref, start, end)` reads source content/chunk ranges.
- **D-08:** Keep `drill` as a separate metadata/graph follow-up tool, but
  replace `drill(file_path)` with `drill(ref)`.
- **D-09:** The intended agent workflow is:
  `search(query) -> ref`, `drill(ref) -> frontmatter/entities/chunk_count`,
  and `read(ref, start, end) -> text chunks`.
- **D-10:** Do not merge `drill` into `read` in this phase. Keep read focused on
  content and drill focused on structured metadata/entities.

### Cleanup Depth

- **D-11:** Reject the shallow option that only changes MCP tool arguments while
  leaving `SearchResult.file_paths` as the service/domain contract.
- **D-12:** Choose the middle cleanup depth: public MCP/API contracts and the
  `SearchResult` domain model become source-ref-first, while lower-level
  filesystem holder mechanisms may stay internal if they are still needed.
- **D-13:** `Chunk.file_paths` and `chunk_file_paths_<strategy>` may remain as
  internal filesystem/content-dedup holder mechanics, but they must stop being
  treated as the public read/search contract.
- **D-14:** Do not attempt the most aggressive storage/graph rewrite unless
  research proves an incremental, no-full-reindex migration path. Replacing all
  path holder tables or graph `File` internals in the same phase is high risk.

### Telegram Boundary

- **D-15:** Telegram dialogs/messages must not be modeled as `File`.
  Future Telegram work should use `SourceDocument`/`SourceUnit` semantics rather
  than fitting Telegram into filesystem `File` nodes or path-shaped APIs.
- **D-16:** If current graph internals still use `File` nodes for filesystem
  documents, planning may leave them as filesystem-only legacy internals. Do not
  generalize `File` as the universal document abstraction for new sources.

### Reindex Constraint

- **D-17:** Every implementation plan must first answer: will this require a
  full reindex or not?
- **D-18:** Avoid full reindex whenever possible. Do not require `dotmd index
  --force`, full TEI re-embedding, full metadata-vector recomputation, full FTS
  rebuild, or full graph rebuild unless the plan proves there is no practical
  incremental path.
- **D-19:** Prefer deriving public refs from already persisted Phase 25 data:
  `source_documents`, `chunk_source_provenance_<strategy>`, and existing
  filesystem document refs.
- **D-20:** Any unavoidable data migration must be idempotent, resumable, and
  scoped to metadata/reference rows where possible, with dry-run/count reporting
  before writes.
- **D-21:** Any plan proposing full reindex is a major cost/risk item requiring
  explicit user decision. Current full rebuild cost is about three days.

### the agent's Discretion

- Decide the exact parser/helper API for `ref` strings, as long as the public
  contract stays a single string and parsing is deterministic.
- Decide whether FastAPI and CLI public outputs move in the same plan as MCP or
  in adjacent plans, as long as no public path-first contract remains at phase
  completion.
- Decide whether `chunk_file_paths_<strategy>` needs a clearer internal name or
  documentation note now, or whether that can wait until a deeper holder-table
  migration.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Definition

- `.planning/ROADMAP.md` - Phase 26 goal, boundary, backlog source `999.24`,
  and no-full-reindex constraint.
- `.planning/STATE.md` - Current workflow state, Phase 26 promotion note, and
  reindex avoidance decision.
- `.planning/REQUIREMENTS.md` - v1.4 requirement context; no dedicated Phase 26
  requirement is currently mapped.

### Phase 25 Source Adapter Context

- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
  - Prior decisions: minimal source model, filesystem-first shim, frontmatter
  semantics, and incremental behavior preservation.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-VERIFICATION.md`
  - Verified Phase 25 source model, provenance persistence, path-compatible
  search/read behavior, and residual risks.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-VALIDATION.md`
  - Nyquist coverage map for current source adapter tests.
- `docs/source-adapter-architecture.md` - Source/document/source-unit/chunk
  vocabulary, Phase 25 delivered state, future source context, and `read(ref)`
  discussion.
- `docs/source-adapter-architecture-panel-review.md` - Expert-panel review of
  source adapter model, retrieval/indexing, metadata, source entities, and
  future Telegram boundary.
- `docs/architecture.md` - Top-level architecture overview and Phase 25
  filesystem shim note.

### Current Public Contracts and Internal Holders

- `backend/src/dotmd/core/models.py` - `SourceDocument`, `ChunkProvenance`,
  current `Chunk.file_paths`, and current `SearchResult.file_paths`.
- `backend/src/dotmd/api/service.py` - `DotMDService.search()` result assembly
  and current `read(file_path, start, end)` implementation.
- `backend/src/dotmd/mcp_server.py` - Current MCP `SearchHit.file_paths`,
  `ReadResult.file_path`, `search`, `read`, and `drill` tool contracts.
- `backend/src/dotmd/storage/metadata.py` - `source_documents`,
  `chunk_source_provenance_<strategy>`, and `chunk_file_paths_<strategy>`
  holder tables/helpers.
- `backend/src/dotmd/search/fusion.py` - Search result hydration path that
  currently fills `file_paths`.
- `backend/src/dotmd/ingestion/pipeline.py` - Source provenance persistence,
  filesystem holder cleanup, graph writes, and no-full-reindex risk surface.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceDocument.ref` already exists and validates as
  `f"{namespace}:{document_ref}"`.
- `SQLiteMetadataStore.get_source_document()` can resolve a source document by
  `(namespace, document_ref)`.
- `chunk_source_provenance_<strategy>` already links chunk IDs to
  `namespace/document_ref`, which should let search hydration derive refs
  without touching embeddings or chunk text.
- `chunk_file_paths_<strategy>` already acts as the holder table for
  content-addressed dedup. It may remain useful internally even after public
  path-shaped contracts are removed.

### Established Patterns

- Public behavior should go through `DotMDService`, MCP, FastAPI, and CLI
  surfaces rather than exposing storage internals.
- dotMD has existing Protocol-style boundaries; new ref parsing/resolution
  helpers should stay small and explicit rather than becoming a source platform.
- Local tests should not require live containers, but Phase 26 also needs one
  explicit live MCP smoke because our own agents are the true consumer of the
  breaking contract.

### Integration Points

- `core/models.py`: likely needs `SearchResult` source-ref-first fields.
- `search/fusion.py` and `api/service.py`: likely need to hydrate refs from
  chunk provenance/source document tables instead of returning file paths.
- `mcp_server.py`: must change `search`, `read`, and `drill` schemas and tool
  descriptions so agents follow `search -> ref -> drill/read`.
- `storage/metadata.py`: may need helper methods for resolving refs and
  fetching chunk ranges by ref.
- Graph storage may remain filesystem-path-shaped internally in this phase, but
  planning must not make that the model for Telegram.

</code_context>

<specifics>
## Specific Ideas

- Use `read(ref="filesystem:/mnt/.../transcript.md")` as the public read form.
- Use `search(...) -> {ref, heading?, snippet, score}` as the target MCP search
  result shape.
- Keep `drill(ref)` separate from `read(ref)` so agents can cheaply inspect
  frontmatter/entities/chunk counts before reading text ranges.
- Treat `File` as filesystem-only legacy terminology, not as a universal source
  document abstraction.

</specifics>

<deferred>
## Deferred Ideas

- Telegram read-only adapter implementation.
- Replacing every internal graph/storage `File` or path holder in one phase,
  unless research proves an incremental no-full-reindex migration path.
- Renaming/replacing `chunk_file_paths_<strategy>` if it remains a correct
  internal dedup holder table after public cleanup.
- Pretty display labels for search hits, if `ref` alone later proves too noisy.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` matched on
  broad graph/file/index terms but remains historical graph migration work, not
  Phase 26 source-ref cleanup.
- `2026-03-27-background-trickle-indexer.md` matched on file/indexing terms but
  remains trickle scheduling/indexing work, not public contract cleanup.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` matched on
  source/delete terms but TTL/data lifecycle remains out of Phase 26.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` matched
  on search/context terms but remains embedding-model work.
- `2026-03-23-scout-other-dotmd-forks-for-ideas.md` matched only broad dotMD
  terms and is not folded.
- `2026-03-27-smoke-tests.md` matched on MCP/test contract terms. Do not fold
  the old todo wholesale, but Phase 26 should include a live MCP smoke after
  changing the contract.

</deferred>

---

*Phase: 26-source-ref-first-read-search-contract-cleanup*
*Context gathered: 2026-05-06*
