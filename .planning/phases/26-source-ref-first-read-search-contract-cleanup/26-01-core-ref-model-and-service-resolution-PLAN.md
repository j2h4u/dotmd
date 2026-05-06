---
phase: "26"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/api/test_service_search.py
  - backend/tests/test_fusion.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-01: Public search-to-read key is a single string ref; filesystem refs use filesystem:<document_ref> where document_ref=str(Path(file_path).resolve())."
    - "D-02: Public callers pass ref, not {namespace, document_ref} and not a JSON source_ref object."
    - "D-04: Public search responses remove file_paths immediately and return ref as primary identity."
    - "D-07: Service read input becomes read(ref, start, end)."
    - "D-10: read remains focused on content; drill remains a separate metadata follow-up surface."
    - "D-11: The plan must not leave SearchResult.file_paths as the service/domain contract."
    - "D-12: Public MCP/API contracts and SearchResult become source-ref-first while lower-level filesystem holder mechanics stay internal."
    - "D-13: Chunk.file_paths and chunk_file_paths_<strategy> may remain internal filesystem/content-dedup holder mechanics."
    - "D-17: First answer: this plan does not require a full reindex."
    - "D-18: No dotmd index --force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild is required."
    - "D-19: Public refs are derived from source_documents and chunk_source_provenance_<strategy>."
    - "D-20: No data migration is expected; any missing-provenance backfill must be idempotent, resumable, scoped, and dry-run/count-first."
---

# Phase 26 Plan 01: Core Ref Model and Service Resolution

<objective>
Make `ref` the core public search/read identity in the domain and service
layers while keeping filesystem paths as internal holder/read mechanics.

Full-reindex answer: this plan must not require a full reindex. It derives refs
from Phase 25 `chunk_source_provenance_<strategy>` and `source_documents` rows.
No vectors, FTS5 rows, chunk text, graph data, or holder tables are rebuilt.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Search results still expose holder paths as public identity | HIGH | Replace `SearchResult.file_paths` with `SearchResult.ref` and update search hydration tests to assert `file_paths` is not a public field. |
| Legacy chunks without provenance silently fall back to public `file_paths` | HIGH | Add explicit missing-provenance behavior: raise/skip with a clear error or derive a filesystem ref only through a named bounded compatibility helper with tests. |
| `read(ref)` reloads indexes or scans all metadata per request | HIGH | Resolve the ref through existing metadata tables and reuse initialized stores; do not call `load_index()` in read/search methods. |
| Ref parsing mishandles filesystem paths containing colons | MEDIUM | Split only on the first colon and reject empty namespace/document_ref. |
| Internal holder mechanics break while removing public paths | HIGH | Preserve `Chunk.file_paths`, `chunk_file_paths_<strategy>`, and existing file-range helpers as internal implementation details. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Change SearchResult to ref-first</title>
<name>Change SearchResult to ref-first</name>
<read_first>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-RESEARCH.md`
- `backend/src/dotmd/core/models.py`
- `backend/tests/api/test_search_result_shape.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/tests/api/test_search_result_shape.py`
</files>
<action>
Replace the public `SearchResult.file_paths` contract with a single required
`ref: str` field.

Concrete target state:
- `SearchResult` has `ref: str`.
- `SearchResult` has no `file_paths` field and no `file_path` field.
- Keep `Chunk.file_paths` unchanged.
- Add validation for `ref`:
  - contains `:`;
  - namespace before the first `:` is non-empty;
  - document_ref after the first `:` is non-empty.
- Filesystem examples use exactly `filesystem:/mnt/example.md`.
- Update `backend/tests/api/test_search_result_shape.py` so it asserts:
  - `SearchResult.model_fields` contains `ref`;
  - `SearchResult.model_fields` does not contain `file_paths`;
  - constructing `SearchResult(ref="filesystem:/mnt/test.md", ...)` succeeds;
  - missing colon, empty namespace, and empty document_ref fail validation.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `ref: str` in `class SearchResult`.
- `backend/src/dotmd/core/models.py` does not contain `file_paths: list[Path] = Field(default_factory=list)` inside `class SearchResult`.
- `backend/src/dotmd/core/models.py` still contains `class Chunk` with `file_paths: list[Path]`.
- `backend/tests/api/test_search_result_shape.py` contains `assert "ref" in fields`.
- `backend/tests/api/test_search_result_shape.py` contains `assert "file_paths" not in fields`.
- `cd backend && uv run pytest tests/api/test_search_result_shape.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Hydrate search refs from chunk provenance</title>
<name>Hydrate search refs from chunk provenance</name>
<read_first>
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/test_fusion.py`
- `backend/tests/api/test_search_result_shape.py`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/test_fusion.py`
- `backend/tests/api/test_search_result_shape.py`
</files>
<action>
Change `build_search_results()` so public search results are hydrated from
source provenance instead of holder paths.

Concrete target state:
- Add a narrow optional Protocol in `fusion.py`, for example
  `_ChunkProvenanceBatchStore`, with:
  `get_chunk_provenance_for_chunk_ids(strategy: str, chunk_ids: Sequence[str]) -> dict[str, ChunkProvenance]`.
- Keep or move `_FilePathsBatchStore` only for internal tests/holders; do not
  use it to populate public `SearchResult`.
- In `build_search_results()`:
  - derive `strategy` from `metadata_store._table` as today;
  - call `get_chunk_provenance_for_chunk_ids(strategy, top_ids)` once when available;
  - for each chunk result, set `ref=provenance.ref`;
  - do not pass `file_paths` to `SearchResult`;
  - preserve heading/snippet/fused/per-engine score behavior.
- Missing provenance behavior must be explicit:
  - preferred: skip the chunk and log a warning containing `missing source provenance`;
  - acceptable alternative: raise a `ValueError` containing `missing source provenance`.
  - Do not silently return public `file_paths`.
- Add tests proving a graph-direct hit and a semantic hit both produce `ref`
  from provenance.
</action>
<acceptance_criteria>
- `backend/src/dotmd/search/fusion.py` contains `get_chunk_provenance_for_chunk_ids`.
- `backend/src/dotmd/search/fusion.py` contains `ref=`.
- `backend/src/dotmd/search/fusion.py` does not contain `SearchResult(` followed by `file_paths=` in the same construction block.
- `backend/tests/test_fusion.py` or `backend/tests/api/test_search_result_shape.py` contains `filesystem:/graph/file.md` or another concrete `filesystem:` ref fixture.
- `backend/tests/test_fusion.py` or `backend/tests/api/test_search_result_shape.py` contains `missing source provenance`.
- `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/test_fusion.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="tdd">
<title>Add service ref parser, read(ref), and drill(ref)</title>
<name>Add service ref parser, read(ref), and drill(ref)</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/ingestion/reader.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/mcp/test_search_tool.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Change the service facade from path-first read to ref-first read and add a
metadata-focused drill method.

Concrete target state:
- Add a small parse helper, for example `_parse_ref(ref: str) -> tuple[str, str]`.
  It must split on the first colon only.
- Add a resolver helper, for example
  `_resolve_source_document(ref: str) -> SourceDocument`.
  It must call `metadata_store.get_source_document(namespace, document_ref)`.
- `DotMDService.read(ref: str, start: int = 0, end: int | None = None)`:
  - accepts `ref`, not `file_path`;
  - resolves the source document;
  - for `namespace == "filesystem"`, requires `SourceDocument.file_path`;
  - parses frontmatter by reading `SourceDocument.file_path`;
  - calls existing internal file-range helpers with the resolved file path:
    `get_chunk_count_for_file(strategy, file_path)` and
    `get_chunks_for_file_range(strategy, file_path, start, end)`;
  - returns a payload with `ref`, `total_chunks`, `frontmatter`, and `chunks`;
  - does not return `file_path` in the public payload.
- Add `DotMDService.drill(ref: str)` returning a metadata payload with at least:
  - `ref`
  - `title`
  - `source_uri`
  - `document_type`
  - `parser_name`
  - `frontmatter`
  - `total_chunks`
- Keep graph/entity enrichment out of `drill` unless an existing helper is cheap
  and does not require a graph rebuild. If included, failures must be
  non-fatal.
- Missing source documents should raise `ValueError` with `Unknown source ref`.
- Unsupported non-filesystem namespaces should raise `ValueError` with
  `Unsupported source namespace` until future source adapters implement reads.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `def read(self, ref: str`.
- `backend/src/dotmd/api/service.py` contains `def drill(self, ref: str`.
- `backend/src/dotmd/api/service.py` contains `get_source_document`.
- `backend/src/dotmd/api/service.py` contains `Unknown source ref`.
- `backend/src/dotmd/api/service.py` contains `Unsupported source namespace`.
- `backend/src/dotmd/api/service.py` does not contain `def read(self, file_path: str`.
- `backend/tests/api/test_service_search.py` or `backend/tests/mcp/test_search_tool.py` asserts read payload contains `ref`.
- `backend/tests/api/test_service_search.py` or `backend/tests/mcp/test_search_tool.py` asserts read payload does not contain `file_path`.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/mcp/test_search_tool.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q
cd backend && uv run pyright
```

Do not run `dotmd index --force`. Do not restart production for this plan alone.
</verification>

<success_criteria>
- `SearchResult` is ref-first and has no public `file_paths`.
- Search hydration uses `chunk_source_provenance_<strategy>`.
- `DotMDService.read(ref)` and `DotMDService.drill(ref)` exist and resolve
  filesystem refs without reindexing.
- Internal filesystem holder mechanics remain available.
</success_criteria>
