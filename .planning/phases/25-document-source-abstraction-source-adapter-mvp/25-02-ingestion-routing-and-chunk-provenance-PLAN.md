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
    - "Filesystem document_ref matches the existing metadata identity: document_ref == IndexingPipeline._meta_entity_id(file_info.path) == str(Path(path).resolve())"
---

# Phase 25 Plan 02: Route Ingestion Through Source Documents and Preserve Chunk Behavior

<objective>
Route current filesystem Markdown indexing through the source-aware document
and unit path created in Plan 01, while preserving current chunk text, chunk
IDs, frontmatter behavior, metadata-only reindexing, and compatibility
`file_paths`.

The pipeline must keep `FileTracker.diff()` on `list[FileInfo]`: adapter
documents are converted through `source_document_to_file_info()` before tracker
diffing, while a parallel `documents_by_path: dict[Path, SourceDocument]` or
equivalent mapping carries provenance into chunking and save calls. No tracker
call should receive `SourceDocument` directly.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Adapter routing changes chunk text and search quality | HIGH | Add tests comparing adapter-routed chunks against existing `chunk_file()` output for representative Markdown. |
| Metadata-only changes re-enter full chunk path | HIGH | Preserve split fingerprint flow and keep encode-call-count tests green. |
| File path compatibility is lost during the internal ref migration | HIGH | Keep `Chunk.file_paths` populated for filesystem chunks in every chunking path. |
| `index_file()` trickle path bypasses adapter provenance | HIGH | Route both bulk `index()` and single-file `index_file()` through the same filesystem adapter/document-ref bridge. |
| `FileTracker.diff()` receives the wrong object type | HIGH | Convert `SourceDocument` to `FileInfo` before `_chunk_tracker.diff()` and `_meta_tracker.diff()`. |
| Source-unit provenance is too vague for future non-filesystem source work | MEDIUM | Attach deterministic `source_unit_refs` and `document_ref` to chunks, but keep raw unit storage out of scope. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Attach chunk provenance without changing chunk payload semantics</title>
<name>Attach chunk provenance without changing chunk payload semantics</name>
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
- Caller-owned provenance is preferred: `chunk_file()` should attach the
  explicit `ChunkProvenance` or parameters it receives, while
  `IndexingPipeline` supplies `namespace`, `document_ref`, `source_unit_refs`,
  and `parser_name` from the adapter document. Do not make `chunk_file()`
  discover files or normalize paths independently.
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
<name>Route bulk pipeline discovery through the filesystem adapter</name>
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
existing `FileInfo`/chunking flow through the explicit bridge from Plan 01.

Concrete behavior:
- `pipeline.index(directory)` still accepts a `Path` directory and returns
  `IndexStats`.
- Bulk discovery uses `FilesystemMarkdownSourceAdapter.discover(directory)` for
  the single-directory path.
- Multi-root discovery used by service/config paths uses
  `FilesystemMarkdownSourceAdapter.discover_multi(paths, exclude)` so
  `discover_files_multi()` is not a permanent bypass around source documents.
- Convert every `SourceDocument` to `FileInfo` with
  `source_document_to_file_info(document)` before calling
  `_chunk_tracker.diff(files)` or `_meta_tracker.diff(files)`.
- Maintain a deterministic mapping such as
  `documents_by_path[Path(file_info.path)] = source_document` and pass it into
  `_chunk_files(...)`, `_save_and_embed_chunks(...)`, or an equivalent internal
  method so chunk provenance is derived from the adapter document, not from a
  second path-normalization branch.
- For filesystem Markdown, assert
  `source_document.document_ref == self._meta_entity_id(file_info.path)` before
  diffing or saving. This aligns document refs with VecComponentStore metadata
  entity IDs.
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
- `backend/src/dotmd/ingestion/pipeline.py` imports `source_document_to_file_info`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `discover_documents` or the chosen adapter method name.
- `backend/src/dotmd/ingestion/pipeline.py` contains `discover_multi` if the index path accepts multiple roots.
- `backend/src/dotmd/ingestion/pipeline.py` still calls `_chunk_tracker.diff(files)` with `files` derived from `FileInfo`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `_meta_entity_id(file_info.path)` or equivalent assertion tying `document_ref` to `_meta_entity_id`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `def index(self, directory: Path`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `data_dir_str = str(directory)`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `telegram`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `SourceAsset`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `ttl`.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Preserve metadata-only, body-change, and trickle indexing paths</title>
<name>Preserve metadata-only, body-change, and trickle indexing paths</name>
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
- Update `IndexingPipeline.index_file(file_info: FileInfo | Path)` so the
  trickle/single-file path cannot bypass adapter provenance:
  - If given a `Path`, construct or discover exactly one filesystem
    `SourceDocument` through `FilesystemMarkdownSourceAdapter`.
  - If given a `FileInfo`, build the matching filesystem `SourceDocument`
    through a `document_from_file_info(file_info)` helper or by rediscovering
    the path, then verify the bridged `FileInfo` is equivalent.
  - Call `_chunk_tracker.diff([file_info])` and `_meta_tracker.diff([file_info])`
    with `FileInfo`, never `SourceDocument`.
  - Pass the same `SourceDocument` into chunk provenance and provenance
    persistence so trickle-indexed files get identical `namespace`,
    `document_ref`, `ref`, `parser_name`, and `source_unit_refs` as bulk
    indexed files.
- `index_file()` must assert
  `source_document.document_ref == self._meta_entity_id(file_info.path)`.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_metadata_only_reindex.py::test_metadata_only_reindex_exactly_one_tei_call` still passes.
- `backend/tests/ingestion/test_source_filesystem.py` asserts body-only and metadata-only fingerprint behavior.
- `backend/tests/ingestion/test_source_filesystem.py` or a pipeline test asserts `index_file(Path(...))` writes chunks with the same filesystem provenance as bulk `index(directory)`.
- `backend/tests/ingestion/test_source_filesystem.py` or a pipeline test asserts `_chunk_tracker.diff` and `_meta_tracker.diff` still receive `FileInfo`-compatible objects.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_chunk_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_meta_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_embed_existing_chunks`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `metadata-only`.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Verify adapter-routed chunks preserve current Markdown behavior</title>
<name>Verify adapter-routed chunks preserve current Markdown behavior</name>
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
- Bulk `index(directory)` and trickle `index_file(path)` produce identical
  provenance for the same Markdown path:
  `namespace=="filesystem"`,
  `document_ref==str(path.resolve())`,
  `ref==f"filesystem:{document_ref}"`,
  `parser_name=="markdown"`, and non-empty `source_unit_refs`.
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
- `backend/tests/ingestion/test_source_filesystem.py` contains `index_file`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `str(path.resolve())`.
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
