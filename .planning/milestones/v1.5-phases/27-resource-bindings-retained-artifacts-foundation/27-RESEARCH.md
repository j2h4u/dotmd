# Phase 27: Resource Bindings and Retained Artifacts Foundation - Research

**Researched:** 2026-05-07
**Domain:** Source-resource lifecycle, SQLite metadata, service visibility filtering
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Active resource bindings are the public visibility gate for normal dotMD `search/read`, not proof that retained content physically exists.
- **D-02:** Unbinding hides a resource from ordinary public output while retaining already computed artifacts for reuse.
- **D-03:** Phase 27 adds service diagnostics/counts only; no recycle-bin search or inactive-content browsing.
- **D-04:** Retain chunks, embeddings, FTS rows, graph artifacts, source/chunk provenance, and metadata needed to rebind equivalent content.
- **D-05:** Retained inactive artifacts must not leak through normal public output; service hydration filters inactive chunks.
- **D-06:** Old soft-delete TTL behavior is only historical intent and is superseded by v1.5 requirements.
- **D-07:** Reuse identity is based on content/source-unit fingerprints, not only prior source ref or filesystem path.
- **D-08:** Equivalent content should rebind to retained artifacts instead of recomputing TEI embeddings, FTS, graph/extraction, or chunks when fingerprints match.
- **D-09:** Missing filesystem paths should deactivate active bindings and hide resources while retaining artifacts.
- **D-10:** Filesystem conversion is the Phase 27 validation slice.
- **D-11:** Mandatory visibility filtering belongs in `DotMDService` hydration/public output.
- **D-12:** Do not delete graph nodes/edges on unbind in Phase 27.
- **D-13:** Avoid graph inactive-state schema unless proven to be the smallest public-visibility enforcement.
- **D-14:** Telegram upstream deletion flags are not dotMD resource unbinds.
- **D-15:** Preserve future Telegram deleted-message metadata, but do not build Telegram recycle-bin behavior.
- **D-16:** Add integration coverage proving unbind hides public search/read while retaining reusable artifacts.
- **D-17:** Local fixture/integration tests are enough for Phase 27; live Telegram smoke belongs later.

### the agent's Discretion

- Choose the exact active-binding schema and helper names.
- Choose whether service filtering is a metadata query, a provenance helper, or another small boundary.
- Choose whether reuse is fully exercised in Phase 27 or prepared with count/dry-run hooks, but filesystem deletion must move away from immediate hard purge.

### Deferred Ideas (OUT OF SCOPE)

- Telegram ingestion, `mcp-telegram` export API, edit/delete TTL policy, attachments/media, generic plugin UI.
- Recycle-bin search, inactive browsing, hard garbage collection lifecycle.
- Graph inactive-state schema unless needed for public visibility.
</user_constraints>

<architectural_responsibility_map>
## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|--------------|----------------|-----------|
| Active binding state | Database/Storage | API/Backend | SQLite metadata is the source of truth for source refs, provenance, chunks, and holder rows. |
| Public active filtering | API/Backend | Database/Storage | `DotMDService` is the public hydration boundary and must filter semantic/FTS/graph candidates before returning `SearchResult` or `read`. |
| Filesystem missing-resource behavior | API/Backend | Database/Storage | `IndexingPipeline._purge_file()` and `purge_orphaned_files()` currently hard-delete; Phase 27 changes that lifecycle decision. |
| Retained artifact reuse | Database/Storage | API/Backend | Existing content-addressed chunk IDs, split fingerprints, embedding `text_hash`, FTS, graph artifacts, and provenance are reusable if binding state is separate. |
| Regression coverage | Test suite | API/Backend | Existing pytest suites cover storage, pipeline purge, service search/read, fusion, and filesystem source behavior. |
</architectural_responsibility_map>

<research_summary>
## Summary

Phase 27 should not introduce a broad plugin or Telegram path. The smallest robust foundation is a generic `resource_bindings` storage layer that records `(namespace, resource_ref/document_ref)` activity independently from retained derived rows. Existing `source_documents`, `chunk_source_provenance_<strategy>`, `chunk_file_paths_<strategy>`, chunk tables, FTS5 rows, vector rows, graph artifacts, split fingerprints, and embedding `text_hash` stay intact when a binding is deactivated.

The current deletion path is the main risk. `IndexingPipeline._holder_aware_chunk_cleanup()` deletes `source_documents`, provenance, holder rows, orphan chunks, vectors, FTS rows, and post-commit graph nodes. Phase 27 should split this into an inactive-binding operation and keep the hard purge code as an explicit later garbage-collection primitive or strategy-drop path. Public leakage is then prevented by service-level filtering that checks active provenance/bindings after engines produce candidate chunk IDs.

**Primary recommendation:** add a minimal active-binding table plus metadata helpers first, route filesystem missing-path handling through deactivation/rebind semantics, then enforce the same active gate in search/read/drill and focused regression tests.
</research_summary>

<standard_stack>
## Standard Stack

No new external library is needed.

| Component | Current Tool | Role |
|-----------|--------------|------|
| Storage | SQLite + FTS5 + sqlite-vec | Holds metadata, FTS rows, vector metadata, and retained derived work. |
| Public facade | `DotMDService` | Search/read/drill boundary where public active filtering belongs. |
| Ingestion | `IndexingPipeline` | Current filesystem diff, purge, chunk, embedding, FTS, graph, and fingerprint orchestration. |
| Tests | pytest via `uv run pytest` | Existing project-native regression harness. |
</standard_stack>

<architecture_patterns>
## Architecture Patterns

### Recommended Component Shape

```
filesystem discovery/diff
  -> new/modified files -> existing chunk/embed/FTS/graph paths
  -> deleted/missing files -> deactivate resource binding
       retained chunks/provenance/vectors/FTS/graph stay present

search engines
  -> candidate chunk IDs from semantic/FTS/graph
  -> DotMDService active-binding filter/hydration
  -> public SearchResult(ref, snippet, scores)

read/drill(ref)
  -> resolve source document
  -> require active binding
  -> return content/metadata only for active refs
```

### Pattern 1: Active Binding as Visibility State

Keep binding activity separate from retained artifacts. A concrete SQLite shape can be:

- `resource_bindings(namespace TEXT, resource_ref TEXT, document_ref TEXT, ref TEXT, active INTEGER NOT NULL DEFAULT 1, content_fingerprint TEXT, metadata_fingerprint TEXT, source_unit_refs TEXT DEFAULT '[]', bound_at TEXT, unbound_at TEXT, metadata_json TEXT DEFAULT '{}', PRIMARY KEY(namespace, resource_ref))`
- filesystem can use `resource_ref == document_ref == str(Path(path).resolve())`.
- later Telegram can use namespace `telegram` with dialog/message/source-unit refs without changing the visibility concept.

### Pattern 2: Service-Level Candidate Filtering

Do not rely on each engine to understand inactive state in Phase 27. Semantic, FTS5, and graph-direct can keep returning retained chunk IDs. `DotMDService` should over-fetch, call a storage helper such as `get_active_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`, drop inactive candidates, and then hydrate only active results. This matches D-11 and avoids graph schema churn.

### Pattern 3: Deactivation Before Hard Garbage Collection

Rename or split deletion primitives so call sites make lifecycle intent explicit:

- `deactivate_resource_binding(...)`: public visibility off, retained artifacts preserved.
- `hard_purge_resource_artifacts(...)`: later GC/strategy drop only, not normal missing-file handling.

Phase 27 should route `_incremental_index()` deleted files and `purge_orphaned_files()` missing paths to deactivation, not `_purge_file()` hard purge.
</architecture_patterns>

<common_pitfalls>
## Common Pitfalls

### Pitfall 1: Deleting Provenance Removes the Filter Join
**What goes wrong:** inactive content cannot be identified or rebound because provenance rows were deleted.
**How to avoid:** normal unbind must preserve `chunk_source_provenance_<strategy>` and `source_documents` rows, with binding state indicating inactive.
**Warning signs:** tests still assert `_purge_file()` removes provenance for the normal missing-file path.

### Pitfall 2: Filtering Only Final Top-K Underfills Results
**What goes wrong:** engines return inactive chunks, service drops them, and public search returns fewer than requested even though active candidates exist just below the cutoff.
**How to avoid:** service over-fetches at least `max(pool_size, top_k * 3)` before filtering, then caps final public results at `top_k`.
**Warning signs:** inactive-filter tests only cover `top_k=1` with no active fallback candidate.

### Pitfall 3: `read(ref)` Falls Back to Existing Files
**What goes wrong:** a missing or inactive source can be read because the file exists or legacy holder rows remain.
**How to avoid:** require an active binding before filesystem fallback; existing-file fallback from Phase 26 must not bypass inactive state.
**Warning signs:** `read()` checks `Path.exists()` before checking active binding state.

### Pitfall 4: Rebind Accidentally Re-Embeds
**What goes wrong:** restored/equivalent content still goes through TEI and graph rebuilds even though retained work is present.
**How to avoid:** add countable helpers that detect retained chunk/provenance/vector/FTS rows by content fingerprint or chunk IDs before encoding. Tests should prove no TEI call on an unchanged rebind fixture where possible.
**Warning signs:** restored filesystem fixture calls `_embed_chunks()` despite unchanged content.
</common_pitfalls>

<validation_architecture>
## Validation Architecture

Automated validation should cover four layers:

1. Storage unit tests for active/inactive binding helpers and retained provenance/chunk/vector/FTS row counts.
2. Pipeline integration tests for missing filesystem paths deactivating bindings instead of hard-purging artifacts.
3. Service tests for `search`, `read`, and `drill` hiding inactive refs while preserving source-ref-first payloads.
4. Existing filesystem regression suite to prove Markdown indexing/search/read behavior remains compatible.

Recommended focused commands:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/api/test_service_search.py tests/test_fusion.py -q
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q
just typecheck
just lint
```
</validation_architecture>

<open_questions>
## Open Questions

1. **Should deactivated filesystem rows remain in `source_documents` or move entirely to `resource_bindings`?**
   - Recommendation: keep `source_documents` as retained document metadata and add binding activity separately. This minimizes migration and keeps ref resolution data.

2. **Should graph search be filtered before or after graph-direct returns chunk IDs?**
   - Recommendation: after, in `DotMDService`, unless implementation proves a storage-level join is cheaper and smaller. D-12/D-13 explicitly avoid graph lifecycle/schema work.

3. **How complete must reuse be in Phase 27?**
   - Recommendation: implement concrete filesystem rebind reuse for unchanged content where existing chunk IDs/text hashes already make it cheap; if graph reuse requires risky changes, count and preserve it but leave deeper graph lifecycle for a later phase.
</open_questions>

<sources>
## Sources

### Primary (HIGH confidence)

- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md` - locked phase decisions and boundaries.
- `.planning/REQUIREMENTS.md` - R1, R2, R8 acceptance criteria.
- `backend/src/dotmd/storage/metadata.py` - current source document, chunk provenance, M2M holder, and hard-delete helpers.
- `backend/src/dotmd/ingestion/pipeline.py` - current `_purge_file`, `purge_orphaned_files`, incremental diff, chunk/embed/FTS/graph paths.
- `backend/src/dotmd/api/service.py` and `backend/src/dotmd/search/fusion.py` - source-ref-first public hydration/read boundaries from Phase 26.

### Secondary (MEDIUM confidence)

- `docs/source-adapter-architecture.md` and `docs/source-adapter-architecture-panel-review.md` - architectural direction and delete/lifecycle warnings.
- Phase 25/26 plans and summaries - local implementation patterns for source-aware models and ref-first public APIs.
</sources>

## RESEARCH COMPLETE
