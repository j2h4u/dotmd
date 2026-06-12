---
phase: 25-document-source-abstraction-source-adapter-mvp
plan: 03
subsystem: storage
tags: [source-adapter, provenance, sqlite, search-compatibility, mcp]

requires:
  - phase: 25-document-source-abstraction-source-adapter-mvp
    provides: SourceDocument, ChunkProvenance, and adapter-routed filesystem chunks from Plans 25-01 and 25-02
provides:
  - Global source_documents persistence keyed by filesystem document_ref
  - Strategy-scoped chunk_source_provenance persistence keyed by chunk provenance
  - Bulk and index_file provenance writes without replacing chunk_file_paths
  - Holder-aware purge cleanup for source documents and chunk provenance
  - SearchResult, MCP search, and MCP read path compatibility verification
affects: [storage, ingestion, purge, source-adapter, search, mcp, phase-25]

tech-stack:
  added: []
  patterns:
    - Global source document metadata with strategy-scoped chunk provenance
    - Caller-owned SQLite transactions for provenance write/delete helpers
    - Additive provenance alongside chunk_file_paths compatibility tables

key-files:
  created:
    - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md
  modified:
    - backend/src/dotmd/storage/metadata.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/tests/storage/test_metadata_m2m.py
    - backend/tests/ingestion/test_source_filesystem.py
    - backend/tests/ingestion/test_pipeline_purge.py

key-decisions:
  - "source_documents is global and keyed by (namespace, document_ref); filesystem document_ref is str(Path(file_path).resolve())."
  - "chunk_source_provenance_<strategy> is strategy-scoped; filesystem source_unit_refs persist as JSON [] in Phase 25."
  - "chunk_file_paths_<strategy> remains the authoritative compatibility path for search hydration and read(file_path)."
  - "Purge deletes document-specific provenance for removed files and deletes all chunk provenance only when chunk IDs become orphaned."

patterns-established:
  - "Provenance write helpers require explicit conn when participating in pipeline transactions."
  - "Legacy rows without provenance are left untouched by reindex_vectors; only newly indexed chunks receive provenance through save paths."
  - "Missing additive provenance tables are treated as no-ops during purge for migration compatibility."

requirements-completed: []

duration: 7min
completed: 2026-05-05
---

# Phase 25 Plan 03: Provenance Persistence and Read/Search Compatibility Summary

**Filesystem source provenance now persists in SQLite without changing file_paths-based search hydration or MCP read(file_path) behavior.**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-05T20:48:26Z
- **Completed:** 2026-05-05T20:55:44Z
- **Tasks:** 4
- **Files modified:** 6

## Accomplishments

- Added global `source_documents` persistence and strategy-scoped `chunk_source_provenance_<strategy>` tables.
- Wrote filesystem source documents and chunk provenance from both bulk `_save_and_embed_chunks()` and single-file `index_file()` save paths.
- Preserved `chunk_file_paths_<strategy>` as the compatibility source for `SearchResult.file_paths`, MCP `SearchHit.file_paths`, and `read(file_path)`.
- Extended holder-aware purge to delete source document rows, document-specific provenance rows, and orphan chunk provenance rows.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add additive SQLite provenance tables** - `e16e735` (feat)
2. **Task 2: Write provenance during chunk save without changing file path hydration** - `9bae1f4` (feat)
3. **Task 3: Preserve search and MCP read compatibility with additive refs only** - `4fa8e4a` (test, empty verification commit)
4. **Task 4: Extend delete cleanup to source provenance** - `025ddf1` (fix)

## Files Created/Modified

- `backend/src/dotmd/storage/metadata.py` - Adds source document and chunk provenance DDL plus transaction-scoped helper methods.
- `backend/src/dotmd/ingestion/pipeline.py` - Persists provenance during bulk and trickle save paths; purges provenance during holder-aware cleanup.
- `backend/tests/storage/test_metadata_m2m.py` - Covers source document persistence, chunk provenance hydration, empty filesystem source_unit_refs, and file_paths compatibility.
- `backend/tests/ingestion/test_source_filesystem.py` - Covers `reindex_vectors()` preserving existing provenance and skipping legacy chunks without provenance.
- `backend/tests/ingestion/test_pipeline_purge.py` - Covers source document and chunk provenance cleanup during purge.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md` - Execution summary.

## Decisions Made

- Kept source document metadata strategy-independent in `source_documents`.
- Kept chunk provenance strategy-scoped because chunk IDs and source-unit refs belong to a chunking strategy.
- Stored filesystem `source_unit_refs` as `[]` only; no pseudo-unit identifier format was introduced.
- Did not add source assets, entity catalogs, TTL, Telegram runtime tables, raw source-unit mirrors, or second-source validation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `reindex_vectors()` FileInfo construction**
- **Found during:** Task 2 (`reindex_vectors()` provenance regression)
- **Issue:** `reindex_vectors()` rebuilt `FileInfo` with only `path` and `frontmatter`, which is invalid for the current Pydantic model.
- **Fix:** Hydrated title, kind, mtime, and size from disk when available, with safe fallback values for missing files.
- **Files modified:** `backend/src/dotmd/ingestion/pipeline.py`
- **Verification:** `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py -q` -> 26 passed.
- **Committed in:** `9bae1f4`

**2. [Rule 2 - Missing Critical] Made purge tolerant of absent additive provenance tables**
- **Found during:** Task 4 purge compatibility work
- **Issue:** Legacy databases may have `chunk_file_paths_*` without `chunk_source_provenance_*`; purge must remain additive and migration-safe.
- **Fix:** Provenance delete helpers treat missing strategy-scoped provenance tables as no-ops.
- **Files modified:** `backend/src/dotmd/storage/metadata.py`
- **Verification:** `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py -q` -> 17 passed.
- **Committed in:** `025ddf1`

---

**Total deviations:** 2 auto-fixed (1 bug, 1 missing critical compatibility guard)
**Impact on plan:** Both fixes were required for the planned persistence and purge behavior. No out-of-scope architecture was added.

## Issues Encountered

- `cd backend && uv run pyright` still fails with 75 pre-existing project-wide type errors in service protocol typing, graph storage typing, trickle optional access, and older tests. This matches the known Phase 25 pyright debt pattern documented by Plans 25-01 and 25-02 and is outside this plan's scope.

## Verification

- PASS: `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` -> 9 passed.
- PASS: `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py -q` -> 26 passed.
- PASS: `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` -> 8 passed.
- PASS: `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py -q` -> 17 passed.
- PASS: `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` -> 25 passed.
- PRE-EXISTING FAILURES: `cd backend && uv run pyright` -> 75 errors in existing service, pipeline, trickle, graph/storage, and older tests.

## Known Stubs

None. The stub-pattern scan found only intentional empty filesystem `source_unit_refs=[]`, existing placeholder-vector comments, and hydrated-later `file_paths=[]` comments.

## Threat Flags

None. New security-relevant storage surface was already included in the plan threat model and was implemented additively without raw source-unit text or new network/API boundaries.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 25-04 to run broader regression/docs/phase verification on the source adapter MVP. `file_paths` remains the public read/search contract while source provenance is now persisted for new filesystem chunks.

## Self-Check: PASSED

- Created summary exists: `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md`.
- Modified files exist: `backend/src/dotmd/storage/metadata.py`, `backend/src/dotmd/ingestion/pipeline.py`, `backend/tests/storage/test_metadata_m2m.py`, `backend/tests/ingestion/test_source_filesystem.py`, `backend/tests/ingestion/test_pipeline_purge.py`.
- Task commits exist: `e16e735`, `9bae1f4`, `4fa8e4a`, `025ddf1`.

---
*Phase: 25-document-source-abstraction-source-adapter-mvp*
*Completed: 2026-05-05*
