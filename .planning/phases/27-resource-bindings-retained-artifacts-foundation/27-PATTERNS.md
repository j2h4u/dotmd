# Phase 27 Pattern Map

**Generated:** 2026-05-07
**Phase:** 27 - Resource bindings and retained artifacts foundation

## Files To Modify And Local Analogs

| Target File | Role | Closest Existing Analog | Pattern To Preserve |
|-------------|------|-------------------------|---------------------|
| `backend/src/dotmd/core/models.py` | Domain models | `SourceDocument`, `SourceUnit`, `ChunkProvenance`, `SearchResult` | Pydantic v2 models with `extra="forbid"` and validators for source refs. |
| `backend/src/dotmd/storage/metadata.py` | SQLite metadata helpers | `ensure_chunk_source_provenance_table`, `upsert_source_document`, `get_chunk_provenance_for_chunk_ids` | Idempotent table creation, caller-owned transaction scope for mutation helpers, narrow read helpers for service use. |
| `backend/src/dotmd/ingestion/pipeline.py` | Filesystem lifecycle | `_holder_aware_chunk_cleanup`, `_purge_file`, `purge_orphaned_files`, `_incremental_index` | Keep transaction boundaries explicit; separate SQLite mutation from best-effort graph/fingerprint cleanup. |
| `backend/src/dotmd/search/fusion.py` | Result hydration | `build_search_results()` | Build public results from provenance, not holder paths; raise on invariant breaks. |
| `backend/src/dotmd/api/service.py` | Public facade | `_ensure_source_provenance_ready`, `_resolve_source_document`, `search`, `read`, `drill` | No per-request index reloads; public source-ref-first behavior flows through service. |
| `backend/src/dotmd/mcp_server.py` | Tool payload/error contract | `search`, `read_document`, `drill`, `_ref_tool_error` | Keep public tool errors actionable and source-ref-first. |
| `backend/tests/storage/test_metadata_m2m.py` | Storage tests | Existing source document/provenance/M2M tests | Table-count and helper behavior assertions with temp SQLite DB. |
| `backend/tests/ingestion/test_pipeline_purge.py` | Lifecycle regression | Existing hard-purge tests | Update normal missing-file semantics while retaining hard-purge coverage only for explicit GC/drop paths. |
| `backend/tests/api/test_service_search.py` | Service contract tests | Phase 26 read/ref tests | Mock metadata helpers to prove active filtering before public payloads. |
| `backend/tests/test_fusion.py` | Hydration tests | Phase 26 provenance hydration tests | Candidate chunk IDs can exist, but inactive provenance must not hydrate to public results. |

## Concrete Code Patterns

### Metadata Store

- Use `_CREATE_*` SQL constants for new tables.
- Use `ensure_*_table()` before helpers that touch optional per-phase tables.
- Mutating helpers that participate in pipeline transactions accept `conn: sqlite3.Connection` and do not commit.
- Read helpers that are service-facing use `self._conn`.

### Pipeline

- `_purge_file()` is currently a hard purge. Phase 27 should either keep it as an explicitly named hard-purge primitive or wrap it behind a new explicit GC-only path.
- `purge_orphaned_files()` currently means "missing from active filesystem source set"; Phase 27 changes this call site to deactivation semantics.
- Post-commit graph cleanup currently deletes chunks/file nodes; normal unbind must skip those deletes to preserve graph artifacts.

### Service

- Public filtering belongs after candidate collection and before final `SearchResult` hydration.
- `read(ref)` and `drill(ref)` should reject inactive refs with `ValueError("Unknown source ref: ...")` or a similarly existing public-ref error, so MCP can preserve the current `Action: pass a ref returned by search.` guidance.
- Do not call `load_index()` from `search`, `read`, or `drill`.

## Data Flow

```
index run
  -> discover active filesystem docs
  -> diff
  -> new/modified: existing indexing path, active binding upsert
  -> deleted/missing: deactivate binding, retain artifacts

search
  -> semantic/FTS/graph candidates
  -> active provenance/binding helper
  -> public SearchResult refs only for active bindings

read/drill
  -> parse ref
  -> resolve document
  -> require active binding
  -> return payload
```

## Landmines

- Do not remove `chunk_source_provenance_<strategy>` on normal unbind; it is the join from retained chunk to source ref.
- Do not drop `chunk_file_paths_<strategy>` for normal unbind until a replacement holder/rebind strategy exists.
- Do not delete graph artifacts for normal unbind.
- Do not narrow `DOTMD_DATA_DIR` or require `dotmd index --force`.
- Do not add Telegram runtime behavior in Phase 27.

## PATTERN MAPPING COMPLETE
