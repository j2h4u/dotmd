# Phase 26 Pattern Map

## Files and Closest Analogs

| File | Role | Closest analog / pattern |
|------|------|--------------------------|
| `backend/src/dotmd/core/models.py` | Public domain shape | Phase 16 changed `SearchResult.file_path` to `file_paths` with Pydantic validators; Phase 26 should make a clean public break to `ref`. |
| `backend/src/dotmd/storage/metadata.py` | Provenance and holder lookup | Existing `get_chunk_provenance_for_chunk_ids()` mirrors `get_file_paths_for_chunk_ids()` and should be the batch hydration path for search refs. |
| `backend/src/dotmd/search/fusion.py` | Search result hydration | `build_search_results()` already batch-hydrates per top-K IDs; replace path hydration with provenance/ref hydration. |
| `backend/src/dotmd/api/service.py` | Public facade | `DotMDService.read()` is the current public read boundary; ref parsing/resolution should live here or in a small helper used by the service. |
| `backend/src/dotmd/mcp_server.py` | Agent-facing contract | `SearchHit`, `ReadResult`, tool parameter annotations, docstrings, and `_format_result()` define the MCP shape that agents consume. |
| `backend/src/dotmd/cli.py` | Human developer output | Search output rendering is thin and should follow `SearchResult.ref`. |
| `backend/tests/api/test_search_result_shape.py` | Domain/search contract tests | Rewrite path-first assertions to ref-first assertions while preserving internal holder tests elsewhere. |
| `backend/tests/mcp/test_search_tool.py` | MCP schema/output tests | Existing tools/list and call_tool tests are the right pattern for pinning `ref`, `read(ref)`, and `drill(ref)`. |
| `backend/tests/e2e/test_mcp_smoke.py` | Live MCP contract | Update pinned fields and read workflow to `search -> ref -> drill/read`. |
| `docs/source-adapter-architecture.md`, `docs/architecture.md`, `docs/mcp.md` | Public docs | Replace Phase 25 compatibility language with Phase 26 source-ref-first contract and keep holder mechanics internal. |

## Concrete Code Patterns

### SourceDocument invariant

`SourceDocument` already validates:

```python
expected_ref = f"{self.namespace}:{self.document_ref}"
if self.ref != expected_ref:
    raise ValueError(f"ref must be {expected_ref!r}")
```

Use the same invariant for public ref parsing.

### Batch provenance hydration

`SQLiteMetadataStore.get_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`
already returns `ChunkProvenance` keyed by chunk ID. This should become the
search hydration source:

```python
provenance_map = metadata_store.get_chunk_provenance_for_chunk_ids(strategy, top_ids)
ref = provenance_map[chunk_id].ref
```

### Existing read-by-path internals

`DotMDService.read()` currently calls:

```python
get_chunk_count_for_file(strategy, file_path)
get_chunks_for_file_range(strategy, file_path, start, end)
```

For filesystem refs, resolve `SourceDocument.file_path` once and reuse these
internal helpers. Do not rename holder tables in Phase 26.

## Landmines

- Do not make `chunk_file_paths_<strategy>` disappear. It is still needed for
  filesystem holder semantics, chunk indexes, delete detection, and local reads.
- Do not call `load_index()` inside search/read methods.
- Do not require `dotmd index --force` or any full rebuild.
- Do not generalize graph `File` nodes into all-source document abstractions in
  this phase.
- Do not leave MCP docs saying callers should pass `file_paths` values to
  `read`.
