# Phase 26 Research: Source-ref-first read/search contract cleanup

## Research Complete

Phase 26 can be planned as an incremental public-contract cleanup. The Phase 25
source provenance tables already contain enough identity data to derive public
refs from existing indexed chunks without re-embedding, rebuilding FTS5, or
rebuilding graph data.

## Current Contract Map

### Domain models

- `backend/src/dotmd/core/models.py` defines `SourceDocument` with
  `namespace`, `document_ref`, and validated `ref =
  f"{namespace}:{document_ref}"`.
- Filesystem source documents validate `document_ref ==
  str(file_path.resolve())`.
- `Chunk.file_paths` remains an internal holder field for filesystem/content
  dedup mechanics.
- `SearchResult` is still path-first through `file_paths: list[Path]`.

### Storage and provenance

- `backend/src/dotmd/storage/metadata.py` already creates global
  `source_documents` keyed by `(namespace, document_ref)`.
- `chunk_source_provenance_<strategy>` maps chunk IDs to
  `namespace/document_ref`, with `source_unit_refs=[]` for filesystem chunks.
- Existing helper `get_source_document(namespace, document_ref)` resolves the
  source document row.
- Existing helper `get_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`
  batch-hydrates provenance by chunk ID.
- Existing `chunk_file_paths_<strategy>` remains the holder table for dedup,
  delete detection, chunk indexes per filesystem file, and path-range reads.

### Search path

- `backend/src/dotmd/search/fusion.py` hydrates search results with
  `get_file_paths_for_chunk_ids(strategy, top_ids)` and constructs
  `SearchResult(file_paths=...)`.
- This is the natural point to replace public `file_paths` hydration with
  source provenance hydration:
  `get_chunk_provenance_for_chunk_ids(strategy, top_ids)` ->
  `SearchResult(ref=f"{namespace}:{document_ref}")`.
- Multi-holder chunks need one public ref. The existing source provenance row is
  one row per `chunk_id`, so it is already the authoritative public source for a
  chunk. The M2M `file_paths` holder list should remain internal, not public.

### Read path

- `DotMDService.read(file_path, start, end)` parses frontmatter by reading the
  filesystem path, gets chunk counts through `get_chunk_count_for_file`, and
  reads ranges through `get_chunks_for_file_range`.
- For Phase 26, `read(ref, start, end)` can parse `filesystem:<document_ref>`,
  resolve the `SourceDocument`, and use its `file_path` for the existing
  filesystem range helpers.
- This preserves the existing chunk-order/range implementation and avoids a
  storage rewrite. Future non-filesystem sources can branch on namespace later.

### MCP/API/CLI path

- `backend/src/dotmd/mcp_server.py` currently exposes:
  - `SearchHit.file_paths`
  - `ReadResult.file_path`
  - `search()` docstring instructing agents to switch from search to read by
    file path
  - `read(file_path, start, end)`
- No `drill` MCP tool currently exists in the live file, even though Phase 26
  context names `drill(file_path)` as a prior contract. Planning should add
  `drill(ref)` as the metadata follow-up tool rather than assuming an existing
  function can be renamed.
- CLI search output still renders `file_paths`; Phase 26 should change it to
  render `ref` as the stable source pointer.

### Test path

- `backend/tests/api/test_search_result_shape.py` and
  `backend/tests/mcp/test_search_tool.py` currently pin `file_paths`.
- `backend/tests/e2e/test_mcp_smoke.py` pins MCP fields and read arguments to
  `file_paths` / `file_path`; it must be updated to `ref`.
- Phase 25 tests remain useful as internal holder/provenance regression tests.
  Do not delete all `file_paths` tests; move expectations so `Chunk.file_paths`
  and `chunk_file_paths_*` are internal-only.

## Implementation Findings

1. The lowest-risk migration is a model/search/service/MCP/API/test/docs
   cleanup. No table rebuild is required.
2. Add small ref helpers instead of a large source platform:
   - parse a public ref string into `namespace` and `document_ref` using the
     first colon only;
   - reject empty namespace/document_ref;
   - resolve a `SourceDocument` through metadata storage;
   - for filesystem refs, require `SourceDocument.file_path`.
3. Search hydration should prefer chunk provenance. If a legacy chunk has no
   provenance, the phase must not silently fall back to public `file_paths`;
   either derive a filesystem ref from the first holder path through a bounded
   compatibility helper or skip/raise with a clear error. Because Phase 25
   shipped provenance, this should be exceptional and test-covered.
4. `drill(ref)` should return structured metadata such as `ref`, `title`,
   `frontmatter`, `source_uri`, `document_type`, `parser_name`, and
   `total_chunks`. Entity lists can be included only if the existing graph
   helper is cheap and stable; do not make graph internals block the contract.
5. Keep graph `File` nodes filesystem-only for now. Renaming graph internals or
   changing FalkorDB node labels would increase risk and could require a graph
   rebuild, which violates the phase constraint.

## No-full-reindex Assessment

Phase 26 should not require:

- `dotmd index --force`
- full TEI re-embedding
- vector table rebuild
- FTS5 table rebuild
- full graph rebuild
- rewriting `chunk_file_paths_<strategy>` holder tables

The plan can derive public refs from existing:

- `source_documents`
- `chunk_source_provenance_<strategy>`
- filesystem `document_ref = str(Path(file_path).resolve())`

Any migration should be limited to optional lightweight metadata checks or
backfills for missing source provenance, with dry-run/count reporting before
writes. Research did not find evidence that such a migration is mandatory for
the Phase 25 indexed state.

## Validation Architecture

### Automated coverage

- Model/unit tests:
  - `SearchResult` has `ref: str` and no public `file_paths` field.
  - ref parser accepts `filesystem:/mnt/a.md` and rejects missing colon, empty
    namespace, and empty document_ref.
- Storage/search tests:
  - `build_search_results()` hydrates `ref` from
    `chunk_source_provenance_<strategy>`.
  - `chunk_file_paths_<strategy>` remains available for internal holder reads.
- Service tests:
  - `DotMDService.read(ref, start, end)` resolves a filesystem ref through
    `source_documents` and uses existing chunk range helpers.
  - `DotMDService.drill(ref)` returns metadata and chunk count without chunk
    text.
- MCP tests:
  - tools/list exposes search results with `ref`, not `file_paths`.
  - `read` input schema uses `ref`, not `file_path`.
  - `drill` is present and uses `ref`.
- CLI/docs tests:
  - CLI search output renders `ref`.
  - docs no longer instruct public callers to use `file_paths` or
    `read(file_path)`.

### Live smoke

Run the live MCP smoke inside the running container after implementation and a
single batched restart:

```bash
docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"
```

The smoke should prove:

- `search(query)` returns at least one result with `ref`;
- `read(ref)` metadata-only succeeds;
- `read(ref, 0, 3)` returns chunks;
- `drill(ref)` returns structured metadata.

## Planning Recommendation

Use three plans:

1. Core source-ref domain, storage hydration, and service read/drill helpers.
2. MCP/API/CLI public contract change from paths to refs.
3. Regression suite, live MCP smoke, and documentation cleanup.

This sequencing keeps internal holder mechanics intact, makes the public
contract break explicit, and proves the result through both local tests and a
live MCP consumer smoke.
