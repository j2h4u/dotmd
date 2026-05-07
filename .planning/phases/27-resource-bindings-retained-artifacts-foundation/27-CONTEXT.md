# Phase 27: resource-bindings-retained-artifacts-foundation - Context

**Gathered:** 2026-05-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the resource binding and retained artifact foundation for v1.5.

This phase separates public source visibility from retained content and derived
artifacts. A resource can stop being active for dotMD search/read while its
chunks, embeddings, FTS rows, graph artifacts, and provenance remain available
for future reuse. The first real validation source is the existing filesystem
source path; Telegram follows in later phases.

This phase is not the Telegram adapter implementation, not a recycle-bin search
feature, and not a full source lifecycle or garbage-collection policy.

</domain>

<decisions>
## Implementation Decisions

### Active Bindings

- **D-01:** An active resource binding means the resource is visible to normal
  public dotMD `search/read` flows. It is the public visibility gate, not the
  same thing as whether retained content physically exists.
- **D-02:** If a whole resource is unbound from dotMD, ordinary `search/read`
  must hide it, but dotMD should retain already computed artifacts for reuse.
- **D-03:** Phase 27 should add only service diagnostics/counts for active,
  inactive, retained, and reused resources. Do not add user-facing recycle-bin
  search or inactive-content browsing in this phase.

### Retained Artifacts

- **D-04:** After unbind, retain all derived artifacts that are useful for
  avoiding recomputation: chunks, embeddings, FTS rows, graph artifacts,
  source/chunk provenance, and metadata needed to rebind equivalent content.
- **D-05:** Retained inactive artifacts must not leak through normal public
  output. Search engines may still return retained chunk IDs internally, but
  public hydration must filter them by active binding.
- **D-06:** The old `Soft-delete with TTL for removed source files` todo is
  folded only as an intent signal: avoid throwing away expensive indexed work
  immediately. Its old product behavior, especially showing deleted files in
  normal search with a flag, is not current truth and is superseded by v1.5
  requirements.

### Reuse Identity

- **D-07:** Reuse should be based on content/source-unit fingerprints rather
  than only the previous source ref or filesystem path.
- **D-08:** If equivalent content appears again through a new or restored
  binding, dotMD should be able to rebind it to retained artifacts instead of
  recomputing TEI embeddings, FTS, graph/extraction, or chunk content where the
  content and relevant metadata fingerprints still match.

### Filesystem Behavior

- **D-09:** Phase 27 should move filesystem deletion/missing-path handling from
  hard purge toward inactive binding semantics. If a file disappears from the
  active filesystem source set, dotMD should remove or deactivate the active
  binding, hide the resource from normal public search/read, and retain
  artifacts for future reuse.
- **D-10:** This filesystem conversion is the main Phase 27 validation slice.
  It makes the foundation real before Telegram ingestion starts.

### Search, Read, and Graph Visibility

- **D-11:** The mandatory minimum visibility filter belongs in `DotMDService`
  result hydration/public output. Semantic, FTS5, and graph engines may return
  retained inactive chunk IDs internally, but `SearchResult` and `read(ref)`
  must only expose active bindings.
- **D-12:** Do not delete graph nodes/edges on unbind in Phase 27. Preserve
  graph artifacts as retained derived work; if graph search returns inactive
  chunks, the service-level active-binding filter drops them before public
  output.
- **D-13:** Do not add graph inactive-state schema work in this phase unless
  research proves it is the smallest necessary way to enforce public visibility.

### Telegram Deletion Boundary

- **D-14:** Telegram messages marked deleted upstream by `mcp-telegram` are not
  resource unbinds for dotMD. If `mcp-telegram` still physically retains the
  message with a deletion flag, dotMD should treat it as a normal Telegram
  source unit with metadata such as `deleted_upstream`.
- **D-15:** Telegram deleted-message metadata should be preserved for later
  display/drill/read behavior, but Phase 27 should not build a Telegram recycle
  bin or treat those source units as inactive bindings.

### Validation

- **D-16:** Phase 27 must include an integration test proving the important
  behavior: unbind hides a resource from normal `search/read` while retaining
  chunks, embeddings, FTS/provenance, and other artifacts needed for reuse.
- **D-17:** Local fixture/integration tests are sufficient for Phase 27.
  Runtime Telegram live smoke belongs later, especially Phase 31.

### the agent's Discretion

- Decide the exact schema shape for active/inactive resource bindings as long
  as public visibility is gated by active binding and retained artifacts remain
  reusable.
- Decide whether the active-binding filter is implemented as a dedicated
  metadata query, a helper around provenance tables, or another small service
  boundary, as long as all public `search/read` output uses the same gate.
- Decide whether retained artifact reuse is fully exercised in Phase 27 or
  prepared with count/dry-run hooks, but the filesystem delete path must move
  away from immediate hard purge.

### Folded Todos

- `.planning/todos/pending/2026-03-28-soft-delete-with-ttl-for-removed-source-files.md`
  - Folded as historical intent only. The old todo captured the need to avoid
    instantly losing deleted-source knowledge and expensive indexed artifacts.
    It predates Phase 25/26 source refs and v1.5 requirements, so planning must
    update it to the current model: inactive resources are hidden from ordinary
    public search/read while retained artifacts stay available for reuse.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Definition

- `.planning/ROADMAP.md` - v1.5 phase list and Phase 27 position as the first
  Telegram Source Adapter foundation phase.
- `.planning/STATE.md` - Current milestone state: v1.5 active, Phase 27 ready
  for planning after context.
- `.planning/REQUIREMENTS.md` - v1.5 requirements, especially R1 Resource
  Binding Foundation, R2 Retained Derived Artifacts, and R8 Validation And
  Smoke.
- `.planning/todos/pending/2026-03-28-soft-delete-with-ttl-for-removed-source-files.md`
  - Historical intent for soft deletion/retention. Use only for intent, not as
  current architecture truth.

### Prior Source-Adapter Decisions

- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
  - Minimal source/document/source-unit model, filesystem shim boundary, and
  Telegram deferral.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  - Source-ref-first public contract, `ref` as public identity, no-full-reindex
  guardrail, and Telegram-not-File boundary.
- `docs/source-adapter-architecture.md` - Source documents, source units,
  retained source state, metadata layers, and future delete/source lifecycle
  context.
- `docs/source-adapter-architecture-panel-review.md` - Expert-panel warnings
  around deletes, privacy, source events, and future adapter contracts.
- `docs/architecture.md` - Current Future Source Adapters section documenting
  Phase 25/26 shipped state and no-full-reindex constraint.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py` - `SourceDocument`, `SourceUnit`,
  `ChunkProvenance`, and current `Chunk.file_paths` holder mechanics.
- `backend/src/dotmd/storage/metadata.py` - `source_documents`,
  `chunk_source_provenance_<strategy>`, `chunk_file_paths_<strategy>`, and
  current source-document delete/provenance helpers.
- `backend/src/dotmd/ingestion/pipeline.py` - Current filesystem missing-file
  purge path, holder-aware cleanup, orphan sweep, graph cleanup, and no-full
  reindex risk surface.
- `backend/src/dotmd/api/service.py` - Public service hydration boundary where
  active-binding visibility filtering should be enforced.
- `backend/src/dotmd/search/fts5.py`, `backend/src/dotmd/search/semantic.py`,
  and `backend/src/dotmd/search/graph_direct.py` - Search engines that may
  return retained inactive chunks internally before service-level filtering.
- `backend/src/dotmd/mcp_server.py` - Public MCP `search/read/drill` behavior
  that must not leak inactive resources.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceDocument` already provides `(namespace, document_ref, ref)` identity
  and filesystem validation.
- `SourceUnit` already exists as the intended source-unit boundary, though
  filesystem Markdown currently has empty source-unit refs.
- `chunk_source_provenance_<strategy>` links chunks to source refs and is the
  likely active-binding filter join point.
- `chunk_file_paths_<strategy>` remains an internal filesystem/content-dedup
  holder table for discovery, local file reads, delete detection, and chunk
  sharing.
- Current holder-aware cleanup in `IndexingPipeline` already knows which chunks
  become orphaned when a filesystem path is removed; Phase 27 should redirect
  that moment toward inactive binding/retention instead of immediate hard
  deletion.

### Established Patterns

- Public behavior flows through `DotMDService`, MCP, CLI, and FastAPI surfaces.
  Do not expose storage internals directly.
- dotMD prefers Protocol-style and facade boundaries over broad platform
  abstractions.
- Migrations/backfills should be idempotent, countable, and avoid full reindex.
- `graphify` may be used during research/planning to inspect codebase
  relationships and dependency clusters, but graphify output is advisory.
  Researchers/planners must verify any finding against the live source files.

### Integration Points

- `SQLiteMetadataStore` likely needs an active binding representation and
  helpers for resolving active refs/chunks.
- `IndexingPipeline._purge_file()`, `_holder_aware_chunk_cleanup()`, and
  `purge_orphaned_files()` are the current filesystem hard-purge path that
  Phase 27 must reshape.
- `DotMDService.search()` and `read(ref, start, end)` must enforce the public
  active-binding gate.
- Graph cleanup should stop deleting retained graph artifacts on unbind unless
  planning proves a smaller safe alternative.

</code_context>

<specifics>
## Specific Ideas

- Treat active binding as the switch for ordinary public visibility.
- Treat retained artifacts as hidden reusable work, not as public archive
  content.
- Treat Telegram `deleted_upstream` messages as normal source-unit metadata
  because `mcp-telegram` keeps the message content and deletion marker.
- Keep recycle-bin search, inactive browsing, TTL policy, and full delete/GC
  lifecycle out of Phase 27.

</specifics>

<deferred>
## Deferred Ideas

- Recycle-bin or `include_inactive` search mode.
- User-facing inactive resource browser.
- TTL/hard garbage collection policy for retained artifacts.
- Source-specific delete lifecycle rules beyond recording source metadata.
- Telegram adapter ingestion and live Telegram smoke.
- Graph schema changes for inactive node marking unless proven necessary.

### Reviewed Todos (not folded)

- `2026-03-27-background-trickle-indexer.md` matched broad indexing terms but
  belongs more naturally to Phase 30 incremental sync/reuse if it remains
  relevant.
- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` matched on
  storage/file/fingerprint terms but is historical graph migration work.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` matched
  on context/search terms but remains embedding-model work.
- `2026-03-23-scout-other-dotmd-forks-for-ideas.md` matched only broad
  visibility terms and is not Phase 27 scope.
- `2026-03-27-smoke-tests.md` matched on MCP/testing terms; Phase 27 needs
  local integration coverage, while broader live smoke belongs later.

</deferred>

---

*Phase: 27-resource-bindings-retained-artifacts-foundation*
*Context gathered: 2026-05-07*
