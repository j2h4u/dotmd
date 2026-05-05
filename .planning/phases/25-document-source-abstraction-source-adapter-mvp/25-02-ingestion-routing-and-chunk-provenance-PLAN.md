---
phase: "25"
plan: "02"
type: execute
wave: 2
depends_on:
  - "25-01"
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/chunker.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/source.py
  - backend/tests/ingestion/test_chunker.py
  - backend/tests/ingestion/test_metadata_only_reindex.py
  - backend/tests/ingestion/test_source_filesystem.py
  - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-01: Existing filesystem Markdown indexing becomes adapter-backed while preserving product behavior"
    - "D-02: Chunks carry source-unit provenance in addition to existing compatibility file_paths"
    - "D-07: Telegram examples may appear only as documentation or fixtures, not runtime implementation"
    - "D-09: Existing Markdown chunk text, search inputs, and read compatibility remain stable"
    - "D-10: Frontmatter title, kind, tags, and participants remain document metadata feeding current search and graph behavior"
    - "D-11: Metadata-only changes keep the fast path and do not force body re-chunking"
---

# Phase 25 Plan 02: Route Ingestion Through Source Documents and Preserve Chunk Behavior

<objective>
Route current filesystem Markdown indexing through the source-aware document
and unit path created in Plan 01, while preserving current chunk text, chunk
IDs, frontmatter behavior, metadata-only reindexing, and compatibility
`file_paths`.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Adapter routing changes chunk text and search quality | HIGH | Add tests comparing adapter-routed chunks against existing `chunk_file()` output for representative Markdown. |
| Metadata-only changes re-enter full chunk path | HIGH | Preserve split fingerprint flow and keep encode-call-count tests green. |
| File path compatibility is lost during the internal ref migration | HIGH | Keep `Chunk.file_paths` populated for filesystem chunks in every chunking path. |
| Source-unit provenance is too vague for future non-filesystem source work | MEDIUM | Attach deterministic `source_unit_refs` and `document_ref` to chunks, but keep raw unit storage out of scope. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Attach chunk provenance without changing chunk payload semantics</title>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/chunker.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-RESEARCH.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/chunker.py`
- `backend/tests/ingestion/test_chunker.py`
</files>
<action>
Extend `Chunk` to carry optional source-aware provenance while keeping existing
fields and chunk text stable.

Concrete target state:
- Add `provenance: ChunkProvenance | None = None` or equivalent explicit
  provenance fields to `Chunk`.
- Keep `file_paths: list[Path]` unchanged and populated for filesystem chunks.
- Update `chunk_file()` to accept optional provenance inputs:
  - `namespace: str = "filesystem"` or a provenance object
  - `document_ref: str | None = None`
  - `source_unit_refs` or enough source-unit context to populate it
  - `parser_name: str | None = "markdown"`
- If the caller does not pass source provenance, preserve current output except
  for default filesystem provenance if that is the chosen implementation.
- Do not change `_make_chunk_id()` formula unless a test explicitly proves
  existing content-addressed IDs remain stable for unchanged content.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `ChunkProvenance`.
- `backend/src/dotmd/core/models.py` contains `provenance`.
- `backend/src/dotmd/ingestion/chunker.py` still contains `_make_chunk_id(body_checksum, chunk_index, chunk_strategy)`.
- `backend/src/dotmd/ingestion/chunker.py` still constructs `Chunk(` with `file_paths=[file_path]`.
- `backend/tests/ingestion/test_chunker.py` or `backend/tests/ingestion/test_source_filesystem.py` asserts chunk `text` remains equal before and after provenance-aware chunking for the same Markdown.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Route bulk pipeline discovery through the filesystem adapter</title>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/reader.py`
- `backend/tests/ingestion/test_incremental_pipeline.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Update `IndexingPipeline.index()` so filesystem Markdown discovery runs
through `FilesystemMarkdownSourceAdapter`, then maps adapter documents to the
existing `FileInfo`/chunking flow or to an equivalent source-document flow.

Concrete behavior:
- `pipeline.index(directory)` still accepts a `Path` directory and returns
  `IndexStats`.
- Discovered documents still correspond exactly to non-empty `.md` files.
- The chunk tracker receives objects/checksums equivalent to current
  `FileInfo` + `chunk_checksum(path)`.
- `data_dir` stats still use `str(directory)`.
- Force mode and incremental mode keep their current branch behavior.
- Do not add a source scheduler, source status table, retries, backpressure,
  or out-of-process adapter runtime.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` imports `FilesystemMarkdownSourceAdapter`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `discover_documents` or the chosen adapter method name.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `def index(self, directory: Path`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `data_dir_str = str(directory)`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `telegram`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `SourceAsset`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `ttl`.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Preserve metadata-only and body-change indexing paths</title>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_pipeline_metadata.py`
- `backend/src/dotmd/ingestion/reader.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Keep the two-fingerprint architecture working after adapter routing.

Concrete behavior:
- Body or `kind` changes continue to route through re-chunking.
- Title/tag-only changes continue to route through the metadata-only embedding
  path.
- The metadata-only path still performs exactly one `encode_batch` call for
  one changed file in steady-state, as asserted by
  `test_metadata_only_reindex_exactly_one_tei_call`.
- If adapter models carry fingerprints, they must expose both
  `content_fingerprint` and `metadata_fingerprint`; do not collapse them into
  one `fingerprint`.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_metadata_only_reindex.py::test_metadata_only_reindex_exactly_one_tei_call` still passes.
- `backend/tests/ingestion/test_source_filesystem.py` asserts body-only and metadata-only fingerprint behavior.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_chunk_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_meta_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_embed_existing_chunks`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `metadata-only`.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Verify adapter-routed chunks preserve current Markdown behavior</title>
<read_first>
- `backend/src/dotmd/ingestion/chunker.py`
- `backend/tests/ingestion/test_chunker.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-ARCHITECTURE-PANEL.md`
</read_first>
<files>
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_chunker.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md`
</files>
<action>
Add compatibility tests proving adapter-routed filesystem Markdown chunking
does not drift.

Required tests:
- A Markdown document with frontmatter and headings produces the same chunk
  `text`, `heading_hierarchy`, `level`, `chunk_index`, and `file_paths` as the
  old `chunk_file(path, content, kind=...)` call.
- A document with `kind: meeting_transcript` still uses the existing
  kind-aware content handler path.
- Adapter-routed chunks have non-empty provenance with
  `namespace=="filesystem"`, the adapter `document_ref`, and at least one
  deterministic source unit ref.
- Current `file_paths` remains a single-element list for normal filesystem
  chunks.

Run:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py -q
```

Write `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md`
with commands run and any unavoidable behavior changes. If chunk text changes,
mark the summary self-check failed unless the change is explicitly justified
against the architecture panel acceptance gate.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_filesystem.py` contains `heading_hierarchy`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `meeting_transcript`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `file_paths`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `provenance`.
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py -q` exits 0.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md` contains `chunk text compatibility`.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run focused verification:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py -q
cd backend && uv run pyright
```
</verification>

<success_criteria>
- Bulk filesystem Markdown indexing is adapter-backed.
- Chunk text and `file_paths` compatibility are preserved.
- Source-unit provenance is attached to chunks.
- Metadata-only changes still avoid full re-chunking and body re-embedding.
- No out-of-scope source implementation enters this phase.
</success_criteria>
