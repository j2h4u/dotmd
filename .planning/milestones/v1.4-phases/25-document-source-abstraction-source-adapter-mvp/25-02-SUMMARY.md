---
phase: 25-document-source-abstraction-source-adapter-mvp
plan: 02
subsystem: ingestion
tags: [source-adapter, filesystem, chunk-provenance, incremental-indexing, markdown]

requires:
  - phase: 25-document-source-abstraction-source-adapter-mvp
    provides: SourceDocument, ChunkProvenance, and FilesystemMarkdownSourceAdapter from Plan 25-01
provides:
  - Adapter-backed bulk filesystem Markdown discovery for IndexingPipeline.index()
  - Adapter-backed single-file IndexingPipeline.index_file() normalization
  - Caller-owned Chunk.provenance annotation with filesystem document refs
  - Regression tests proving chunk text compatibility and metadata-only fast path preservation
affects: [ingestion, source-adapter, chunker, trickle-indexing, phase-25]

tech-stack:
  added: []
  patterns:
    - Local documents_by_path provenance mapping passed through ingestion calls
    - SourceDocument-to-FileInfo bridge before tracker diffing
    - Caller-owned chunk provenance attachment in chunk_file()

key-files:
  created:
    - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/tests/ingestion/test_chunker.py
    - backend/tests/ingestion/test_source_filesystem.py
    - .planning/phases/25-document-source-abstraction-source-adapter-mvp/deferred-items.md

key-decisions:
  - "chunk_file() remains a pure Markdown chunker: provenance is attached only when the caller passes it explicitly."
  - "Filesystem chunk provenance uses namespace=filesystem, document_ref=str(path.resolve()), ref=filesystem:<document_ref>, parser_name=markdown, and source_unit_refs=[]."
  - "FileTracker.diff() continues to receive FileInfo objects; SourceDocument is bridged before diffing."
  - "documents_by_path stays local to each indexing call and is passed through chunking instead of becoming mutable pipeline state."

patterns-established:
  - "Bulk and single-file ingestion both derive chunk provenance from SourceDocument."
  - "Filesystem SourceDocument refs are asserted against IndexingPipeline._meta_entity_id(file_info.path)."
  - "Adapter-routed chunk compatibility is tested by direct comparison against chunk_file()."

requirements-completed: []

duration: 7 min
completed: 2026-05-05
---

# Phase 25 Plan 02: Ingestion Routing and Chunk Provenance Summary

**Filesystem Markdown indexing now routes through source documents while preserving chunk text compatibility, file_paths, and metadata-only reindex behavior.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-05T20:38:02Z
- **Completed:** 2026-05-05T20:45:10Z
- **Tasks:** 5
- **Files modified:** 6

## Accomplishments

- Added optional `Chunk.provenance` and explicit caller-owned provenance support in `chunk_file()`.
- Routed `IndexingPipeline.index()` through `FilesystemMarkdownSourceAdapter` before converting to `FileInfo` for tracker diffing.
- Added source bridge helpers used by both bulk and `index_file()` paths.
- Routed `index_file(Path | FileInfo)` through the same filesystem source bridge and provenance builder.
- Added compatibility tests for chunk text compatibility, heading hierarchy, `meeting_transcript` kind handling, `file_paths`, provenance, bulk/index_file parity, and metadata-only TEI call behavior.

## Task Commits

Each task was committed atomically:

1. **Task 1: Attach chunk provenance without changing chunk payload semantics** - `fb0c0f4` (feat)
2. **Task 2: Route bulk pipeline discovery through the filesystem adapter** - `0d6aa48` (feat)
3. **Task 3: Prepare common adapter bridge helpers before touching index_file()** - `5d98371` (feat)
4. **Task 4: Refactor index_file() through the common adapter bridge in small steps** - `6f81777` (feat)
5. **Task 5: Verify adapter-routed chunks preserve current Markdown behavior** - `ff33861` (test)

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - Adds `Chunk.provenance` and `ChunkProvenance.ref`.
- `backend/src/dotmd/ingestion/chunker.py` - Accepts optional caller-owned provenance and attaches it without synthesizing defaults.
- `backend/src/dotmd/ingestion/pipeline.py` - Routes bulk and single-file ingestion through filesystem source documents and provenance helpers.
- `backend/tests/ingestion/test_chunker.py` - Covers default `None` provenance, explicit provenance attachment, and chunk text stability.
- `backend/tests/ingestion/test_source_filesystem.py` - Covers adapter routing, provenance fields, tracker input types, metadata fingerprints, and chunk payload compatibility.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/deferred-items.md` - Records remaining out-of-scope pyright failures.

## Decisions Made

- `chunk_file()` does not infer filesystem provenance; the pipeline owns source-aware annotation.
- Filesystem Markdown uses empty `source_unit_refs` in Phase 25 because no adapter emits runtime source units yet.
- `documents_by_path` remains local call state and is threaded through `_chunk_files()` instead of stored on the pipeline instance.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed new test typing errors from Settings extract_depth**
- **Found during:** Task 5 verification
- **Issue:** Targeted pyright reported new `extract_depth` literal type errors in `test_source_filesystem.py`.
- **Fix:** Used `ExtractDepth.STRUCTURAL` in the new Settings fixtures.
- **Files modified:** `backend/tests/ingestion/test_source_filesystem.py`
- **Verification:** `cd backend && uv run pyright tests/ingestion/test_source_filesystem.py` -> 0 errors.
- **Committed in:** `ff33861`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The fix was limited to the new tests and did not change runtime behavior.

## Issues Encountered

- The plan read-first list referenced `backend/tests/ingestion/test_incremental_pipeline.py`, which does not exist in the current tree. The available ingestion tests were listed and relevant current files were read instead.
- `cd backend && uv run pyright` still fails with 76 pre-existing project-wide type errors. These match the existing Plan 25-01 deferred category and remain out of scope for Plan 25-02.

## Verification

- PASS: `cd backend && uv run pytest tests/ingestion/test_chunker.py -q` -> 6 passed.
- PASS: `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py -q` -> 23 passed.
- PASS: `cd backend && uv run pyright tests/ingestion/test_source_filesystem.py` -> 0 errors.
- PRE-EXISTING FAILURES: `cd backend && uv run pyright` -> 76 errors in existing service, pipeline, trickle, graph/storage, and older tests.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 25-03 to persist source provenance additively while keeping `file_paths` and current search/read compatibility authoritative.

## Self-Check: PASSED

- Created summary exists: `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md`.
- Modified files exist: `backend/src/dotmd/core/models.py`, `backend/src/dotmd/ingestion/chunker.py`, `backend/src/dotmd/ingestion/pipeline.py`, `backend/tests/ingestion/test_chunker.py`, `backend/tests/ingestion/test_source_filesystem.py`.
- Task commits exist: `fb0c0f4`, `0d6aa48`, `5d98371`, `6f81777`, `ff33861`.

---
*Phase: 25-document-source-abstraction-source-adapter-mvp*
*Completed: 2026-05-05*
