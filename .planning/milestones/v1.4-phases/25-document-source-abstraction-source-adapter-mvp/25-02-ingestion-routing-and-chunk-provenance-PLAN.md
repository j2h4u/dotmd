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
    - "D-02: Chunks carry source document provenance in addition to existing compatibility file_paths; filesystem Markdown source_unit_refs are explicitly [] in Phase 25"
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
| Source-unit provenance is too vague for future non-filesystem source work | MEDIUM | Phase 25 stores chunk-level source document provenance and explicitly sets filesystem Markdown `source_unit_refs=[]`; no runtime source-unit emission or raw unit storage is added. |
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
- Update `chunk_file()` to accept one optional provenance input:
  - `provenance: ChunkProvenance | None = None`
- Default behavior is now fixed for non-adapter callers: if `provenance` is
  omitted, every returned `Chunk.provenance` is `None`. `chunk_file()` must not
  synthesize filesystem provenance, infer `document_ref` from `file_path`, or
  create default `source_unit_refs` for tests, direct utility calls, or legacy
  callers. This preserves the current function as a pure Markdown chunker plus
  optional caller-owned annotation.
- Caller-owned provenance is preferred: `chunk_file()` should attach the
  explicit `ChunkProvenance` it receives, while `IndexingPipeline` supplies
  filesystem provenance from the adapter document. Do not make `chunk_file()`
  discover files or normalize paths independently.
- For adapter-routed filesystem Markdown in Phase 25, the explicit
  `ChunkProvenance` passed by the pipeline must be:
  - `namespace="filesystem"`
  - `document_ref=str(path.resolve())`
  - `ref=f"filesystem:{document_ref}"`
  - `parser_name="markdown"`
  - `source_unit_refs=[]`
- `source_unit_refs=[]` is intentional for filesystem Markdown in Phase 25.
  `SourceUnit` is model scaffolding from Plan 01 only; no adapter emits units
  yet, and no deterministic pseudo-unit IDs should be invented here.
- Do not change `_make_chunk_id()` formula unless a test explicitly proves
  existing content-addressed IDs remain stable for unchanged content.
Addresses review concern: Plan 25-02 now specifies `chunk_file()` default
provenance behavior for non-adapter callers.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `ChunkProvenance`.
- `backend/src/dotmd/core/models.py` contains `provenance`.
- `backend/src/dotmd/ingestion/chunker.py` still contains `_make_chunk_id(body_checksum, chunk_index, chunk_strategy)`.
- `backend/src/dotmd/ingestion/chunker.py` still constructs `Chunk(` with `file_paths=[file_path]`.
- `backend/tests/ingestion/test_chunker.py` asserts calling `chunk_file(path)` without provenance returns chunks whose `provenance is None`.
- `backend/tests/ingestion/test_chunker.py` asserts passing an explicit `ChunkProvenance` attaches that same value to returned chunks.
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
- Mapping ownership is explicit: `documents_by_path` is local to the indexing
  call and must be passed as a parameter through the chunk/save call chain. Do
  not store it as mutable pipeline instance state, and do not recover provenance
  from `chunk.file_paths[0]` inside the storage layer.
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
- `backend/src/dotmd/ingestion/pipeline.py` contains `documents_by_path` or the chosen explicit provenance mapping parameter name.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `def index(self, directory: Path`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `data_dir_str = str(directory)`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `telegram`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `SourceAsset`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `ttl`.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Prepare common adapter bridge helpers before touching index_file()</title>
<name>Prepare common adapter bridge helpers before touching index_file()</name>
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
Keep the two-fingerprint architecture working after adapter routing, and add
small helper boundaries before modifying the 244-line `index_file()` trickle
method.

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
- Add narrowly scoped private helpers in `IndexingPipeline` before changing
  `index_file()`:
  - `_source_document_for_file_info(file_info: FileInfo) -> SourceDocument`
    or equivalent. It builds the filesystem `SourceDocument` for an already
    normalized `FileInfo`, verifies the bridged `FileInfo` remains equivalent,
    and does not perform tracker diffing or persistence.
  - `_file_info_and_source_document(file_info_or_path: FileInfo | Path) -> tuple[FileInfo, SourceDocument]`
    or equivalent. It centralizes the current Path-to-FileInfo normalization,
    including stat/frontmatter read failure handling, then returns both objects.
  - `_filesystem_chunk_provenance(source_document: SourceDocument) -> ChunkProvenance`
    or equivalent. It returns the fixed Phase 25 provenance:
    `namespace="filesystem"`, `document_ref`, `ref`, `parser_name="markdown"`,
    and `source_unit_refs=[]`.
  - `_assert_filesystem_document_ref(file_info, source_document)` or equivalent,
    asserting `source_document.document_ref == self._meta_entity_id(file_info.path)`.
- Keep this task helper-first: do not restructure the purge, graph, FTS5,
  extraction, beacon, or embed branches inside `index_file()` in this task.
Addresses review concern: Plan 25-02 no longer treats `index_file()` as a
single underestimated refactor; it adds helper seams and tests first.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_metadata_only_reindex.py::test_metadata_only_reindex_exactly_one_tei_call` still passes.
- `backend/tests/ingestion/test_source_filesystem.py` asserts body-only and metadata-only fingerprint behavior.
- `backend/tests/ingestion/test_source_filesystem.py` asserts the helper-created filesystem chunk provenance has `source_unit_refs == []`.
- `backend/tests/ingestion/test_source_filesystem.py` asserts the helper-created filesystem chunk provenance has `document_ref == str(path.resolve())` and `ref == f"filesystem:{document_ref}"`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_chunk_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_meta_tracker`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_embed_existing_chunks`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `metadata-only`.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Refactor index_file() through the common adapter bridge in small steps</title>
<name>Refactor index_file() through the common adapter bridge in small steps</name>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_pipeline_m2m_insert.py`
- `backend/tests/ingestion/test_pipeline_reindex_shared_chunk.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
</files>
<action>
Update `IndexingPipeline.index_file(file_info: FileInfo | Path)` so the
trickle/single-file path cannot bypass adapter provenance, while preserving
the current method's branch behavior.

Concrete behavior:
- Start `index_file()` by calling the helper from Task 3 to normalize
  `FileInfo | Path` into `(file_info, source_document)`. Preserve current
  missing-file behavior: stat/read failure for a `Path` logs and returns `0`
  where the existing method returns `0`.
- Keep `_beacon`, timing accumulators, holder-aware purge transaction, graph
  cleanup fallback, FTS5 write, extraction, graph population,
  `_save_chunk_fingerprint`, `_index_file_embed`, metadata-only FTS/graph
  refresh, and final logging in the same order unless a test forces a local
  move.
- Call `_chunk_tracker.diff([file_info])` and `_meta_tracker.diff([file_info])`
  with `FileInfo`, never `SourceDocument`.
- When chunking, call `chunk_file(..., provenance=_filesystem_chunk_provenance(source_document))`
  or the equivalent explicit argument. The resulting chunks must have:
  `namespace=="filesystem"`, `document_ref==str(path.resolve())`,
  `ref==f"filesystem:{document_ref}"`, `parser_name=="markdown"`, and
  `source_unit_refs==[]`.
- Pass the same `SourceDocument`/chunk provenance into provenance persistence
  in Plan 03. In Plan 02, it is acceptable for persistence tables not to exist
  yet, but chunks must already carry the data Plan 03 will write.
- Add tests that exercise the real `index_file(Path(...))` path and a
  `FileInfo` input path, not only direct helper calls.
- Do not use `chunk.file_paths[0]` as a provenance source; it remains the
  compatibility file-path holder only.
Addresses review concern: Plan 25-02 isolates the high-risk 244-line
`index_file()` change into a dedicated task with branch-preservation and
single-file tests.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_filesystem.py` or a pipeline test asserts `index_file(Path(...))` writes chunks with the same filesystem provenance as bulk `index(directory)`.
- `backend/tests/ingestion/test_source_filesystem.py` or a pipeline test asserts `index_file(FileInfo(...))` writes chunks with the same filesystem provenance as `index_file(Path(...))`.
- `backend/tests/ingestion/test_source_filesystem.py` or a pipeline test asserts `_chunk_tracker.diff` and `_meta_tracker.diff` still receive `FileInfo`-compatible objects.
- `backend/tests/ingestion/test_metadata_only_reindex.py::test_metadata_only_reindex_exactly_one_tei_call` still passes.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_beacon("purge")`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_beacon("embed")`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `_index_file_embed`.
</acceptance_criteria>
</task>

<task id="5" type="execute">
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
  `namespace=="filesystem"`, the adapter `document_ref`, and
  `source_unit_refs==[]`.
- Bulk `index(directory)` and trickle `index_file(path)` produce identical
  provenance for the same Markdown path:
  `namespace=="filesystem"`,
  `document_ref==str(path.resolve())`,
  `ref==f"filesystem:{document_ref}"`,
  `parser_name=="markdown"`, and `source_unit_refs==[]`.
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
- `backend/tests/ingestion/test_source_filesystem.py` contains `source_unit_refs == []` or an equivalent assertion.
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
- Chunk source-document provenance is attached to adapter-routed chunks, with
  filesystem `source_unit_refs` explicitly empty in Phase 25.
- Metadata-only changes still avoid full re-chunking and body re-embedding.
- No out-of-scope source implementation enters this phase.
</success_criteria>
