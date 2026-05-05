---
phase: "25"
plan: "03"
type: execute
wave: 3
depends_on:
  - "25-01"
  - "25-02"
files_modified:
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/storage/test_metadata_m2m.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/mcp/test_search_tool.py
  - backend/tests/ingestion/test_pipeline_purge.py
  - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-02: Persistent chunk provenance includes namespace, document_ref, source_unit_refs, chunk_strategy, and parser_name"
    - "D-09: Existing SearchResult.file_paths and MCP read(file_path, start, end) remain valid"
    - "D-10: Frontmatter metadata remains accessible to FTS, metadata embeddings, and graph behavior"
    - "D-11: New source provenance persistence does not break delete or metadata-only fast-path behavior"
    - "No raw source-unit mirror, SourceAsset table, entity catalog table, TTL policy, or Telegram runtime table is added"
---

# Phase 25 Plan 03: Persist Provenance and Preserve Read/Search Compatibility

<objective>
Persist the minimal source/document/chunk provenance needed by the source-aware
shim while keeping filesystem `file_paths`, search hydration, and MCP
`read(file_path, start, end)` behavior compatible.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Provenance tables leave orphan rows after file deletion | HIGH | Add provenance cleanup to holder-aware purge and test deletion cascades. |
| Search clients lose `file_paths` while refs are introduced | HIGH | Keep `SearchResult.file_paths` and MCP `SearchHit.file_paths` unchanged; any `ref` metadata is additive. |
| New schema stores raw private source-unit text unnecessarily | MEDIUM | Persist provenance refs and metadata only; no durable raw source-unit mirror in Phase 25. |
| Storage migration breaks existing index databases | HIGH | Use idempotent `CREATE TABLE IF NOT EXISTS` and additive columns/tables only. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Add additive SQLite provenance tables</title>
<read_first>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Add additive provenance persistence to `SQLiteMetadataStore` without replacing
`chunk_file_paths_<strategy>`.

Concrete target state:
- Add an idempotent table for source documents, for example
  `source_documents_<strategy>` or a non-strategy table if document metadata is
  intentionally strategy-independent. It must store:
  - `namespace`
  - `document_ref`
  - `ref`
  - `source_uri`
  - `file_path`
  - `media_type`
  - `parser_name`
  - `document_type`
  - `title`
  - `updated_at`
  - `content_fingerprint`
  - `metadata_fingerprint`
  - `metadata_json`
- Add a strategy-scoped chunk provenance table, for example
  `chunk_source_provenance_<strategy>`, storing:
  - `chunk_id`
  - `namespace`
  - `document_ref`
  - `source_unit_refs` as JSON text
  - `chunk_strategy`
  - `parser_name`
- Add helper methods with concrete names chosen by implementation, for example:
  - `ensure_source_tables(strategy)`
  - `upsert_source_document(...)`
  - `add_chunk_provenance(...)`
  - `get_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`
  - `delete_source_document_for_file(strategy, file_path, conn=...)`
  - `delete_chunk_provenance(strategy, chunk_ids, conn=...)`
- Use `CREATE TABLE IF NOT EXISTS`.
- Use idempotent insert/upsert semantics.
- Keep `chunk_file_paths_<strategy>` as the compatibility source for
  `file_paths`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `source_documents`.
- `backend/src/dotmd/storage/metadata.py` contains `chunk_source_provenance`.
- `backend/src/dotmd/storage/metadata.py` contains `source_unit_refs`.
- `backend/src/dotmd/storage/metadata.py` still contains `chunk_file_paths_`.
- `backend/src/dotmd/storage/metadata.py` contains `CREATE TABLE IF NOT EXISTS`.
- `backend/tests/storage/test_metadata_m2m.py` contains a test for source document persistence.
- `backend/tests/storage/test_metadata_m2m.py` contains a test for chunk provenance batch hydration.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Write provenance during chunk save without changing file path hydration</title>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_pipeline_m2m_insert.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
When saving adapter-routed chunks, persist source documents and chunk
provenance alongside existing chunks and file path M2M associations.

Concrete behavior:
- `save_chunks()` or the pipeline path must still call `add_file_path(...)`
  for every filesystem chunk.
- Persist one source document row per discovered Markdown file.
- Persist one chunk provenance row per chunk with `namespace="filesystem"`,
  the source document `document_ref`, `source_unit_refs`, strategy, and
  `parser_name="markdown"`.
- Do not persist raw source-unit text in the provenance table.
- Keep FTS5, vector, and graph write behavior equivalent.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` or `backend/src/dotmd/storage/metadata.py` calls `upsert_source_document` or the chosen source document helper.
- `backend/src/dotmd/ingestion/pipeline.py` or `backend/src/dotmd/storage/metadata.py` calls `add_chunk_provenance` or the chosen chunk provenance helper.
- `backend/src/dotmd/storage/metadata.py` still contains `add_file_path`.
- `backend/tests/storage/test_metadata_m2m.py` asserts `file_paths` are still returned for a chunk with provenance.
- `backend/tests/storage/test_metadata_m2m.py` asserts stored `source_unit_refs` round-trip as a list.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Preserve search and MCP read compatibility with additive refs only</title>
<read_first>
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
</read_first>
<files>
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Keep public search/read contracts stable while optionally exposing source refs
as additive metadata.

Concrete behavior:
- `SearchResult.file_paths` remains present and sorted.
- MCP `SearchHit.file_paths` remains present.
- MCP `read` continues to accept `file_path` and its parameter description
  remains compatible with "Absolute file path from a search result."
- Do not require clients to call `read(ref)` in Phase 25.
- If a `ref` or provenance metadata is exposed, add it without removing or
  renaming `file_paths`.
- `DotMDService.read(file_path, start, end)` continues to hydrate frontmatter
  from the filesystem path and chunks from `chunk_file_paths_<strategy>`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` still contains `file_paths: list[Path]`.
- `backend/src/dotmd/mcp_server.py` still contains `file_paths: list[str]`.
- `backend/src/dotmd/mcp_server.py` still contains `file_path: Annotated[str`.
- `backend/src/dotmd/mcp_server.py` does not contain `read_ref`.
- `backend/tests/api/test_search_result_shape.py` still asserts `file_paths`.
- `backend/tests/mcp/test_search_tool.py` still asserts `file_paths`.
- `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Extend delete cleanup to source provenance</title>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md`
</files>
<action>
Update holder-aware purge to clean source provenance rows for removed
filesystem Markdown files and orphaned chunks.

Concrete behavior:
- When a filesystem file is deleted, remove its source document row by
  compatibility `file_path` or by derived `document_ref`.
- When chunk IDs become orphaned, delete their `chunk_source_provenance_*`
  rows in the same DB cleanup path.
- Preserve current behavior for shared chunks: deleting one file holder must
  not delete shared chunk payload or provenance still held by another file.
- Keep graph cleanup failure handling as currently designed.
- Do not add TTL, soft-delete retention, or delayed purge policy.

Run:

```bash
cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py -q
```

Write `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md`
with commands run and delete/provenance behavior.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` or `backend/src/dotmd/storage/metadata.py` contains a call that deletes source document rows during purge.
- `backend/src/dotmd/ingestion/pipeline.py` or `backend/src/dotmd/storage/metadata.py` contains a call that deletes chunk provenance rows for orphan chunks.
- `backend/tests/ingestion/test_pipeline_purge.py` contains `source_documents` or the chosen source document table name.
- `backend/tests/ingestion/test_pipeline_purge.py` contains `chunk_source_provenance` or the chosen chunk provenance table name.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `ttl`.
- `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run focused verification:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q
cd backend && uv run pyright
```
</verification>

<success_criteria>
- Source document and chunk provenance are persisted additively.
- Existing `chunk_file_paths_*` remains the compatibility read/search path.
- Deleted filesystem files clean their source provenance.
- `SearchResult.file_paths`, MCP `search`, and MCP `read(file_path)` remain
  valid.
- No raw source-unit mirror, asset/entity catalog, TTL policy, Telegram table,
  or second-source validation is implemented.
</success_criteria>
