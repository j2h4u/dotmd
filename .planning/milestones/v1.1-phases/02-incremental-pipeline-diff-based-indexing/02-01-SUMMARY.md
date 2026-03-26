---
phase: 02-incremental-pipeline-diff-based-indexing
plan: 01
subsystem: ingestion
tags: [incremental-indexing, file-tracker, sqlite-vec, bm25, pipeline]

# Dependency graph
requires:
  - phase: 01-storage-layer-file-tracking-delete-methods
    provides: FileTracker, delete_vectors_by_chunk_ids, delete_chunks_by_file, delete_file_subgraph
provides:
  - Incremental indexing via IndexingPipeline.index() with diff-based file processing
  - _purge_file() for clean removal from all 3 stores in correct order
  - add_chunks overwrite parameter for append-mode vector insertion
  - force=True for full re-index with fingerprint clearing
affects: [02-02-PLAN, cli, api-service]

# Tech tracking
tech-stack:
  added: []
  patterns: [incremental-pipeline, purge-before-reingest, fingerprint-after-ingest]

key-files:
  created:
    - backend/tests/test_incremental_pipeline.py
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/storage/base.py
    - backend/src/dotmd/storage/sqlite_vec.py
    - backend/tests/test_vector_delete.py
    - backend/tests/conftest.py

key-decisions:
  - "overwrite_vectors parameter routes through _ingest_and_finalize to add_chunks, keeping full/incremental logic DRY"
  - "_ExtractionBundle dataclass bundles extraction results to simplify _ingest_and_finalize signature"
  - "vector_store property type changed from LanceDBVectorStore to VectorStoreProtocol for correctness"

patterns-established:
  - "Purge-before-reingest: always get_chunk_ids BEFORE delete_chunks (metadata lookup precedes metadata delete)"
  - "Fingerprint-after-ingest: save fingerprints only after successful embedding/storage (crash-safe)"
  - "Full BM25 rebuild: always rebuild from all chunks regardless of incremental vs full mode"

requirements-completed: [IP-01, IP-02, IP-03, IP-04]

# Metrics
duration: 6min
completed: 2026-03-23
---

# Phase 02 Plan 01: Incremental Pipeline Summary

**Diff-based incremental indexing via FileTracker integration -- modified/deleted files purged from all 3 stores, new files appended, unchanged files skipped entirely**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-23T11:37:39Z
- **Completed:** 2026-03-23T11:44:20Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- IndexingPipeline.index() defaults to incremental mode, processing only changed files
- Modified files have old data purged from all 3 stores (vector, metadata, graph) before re-ingestion
- Deleted files purged and fingerprints removed; new files appended without touching existing data
- BM25 index always fully rebuilt from all chunks after every run (IP-04)
- add_chunks gains overwrite parameter for append-mode vector insertion
- force=True clears all stores + fingerprints for full re-index

## Task Commits

Each task was committed atomically (TDD: RED then GREEN):

1. **Task 1: Add overwrite parameter to add_chunks**
   - `22087b9` (test) - RED: 3 failing tests for overwrite behavior
   - `0ca4957` (feat) - GREEN: overwrite parameter in Protocol + SQLiteVecVectorStore
2. **Task 2: Refactor IndexingPipeline for incremental indexing**
   - `98a39a3` (test) - RED: 10 failing tests for incremental pipeline behavior
   - `47dcdbf` (feat) - GREEN: full pipeline refactor with _purge_file, _incremental_index, _full_index

## Files Created/Modified
- `backend/src/dotmd/storage/base.py` - VectorStoreProtocol.add_chunks gains `overwrite: bool = True`
- `backend/src/dotmd/storage/sqlite_vec.py` - SQLiteVecVectorStore.add_chunks wraps DELETE in `if overwrite:` guard
- `backend/src/dotmd/ingestion/pipeline.py` - Full refactor: _purge_file, _incremental_index, _full_index, _ingest_and_finalize, _run_extraction, _populate_graph, FileTracker integration
- `backend/tests/test_vector_delete.py` - 3 new tests for overwrite parameter (8 total)
- `backend/tests/test_incremental_pipeline.py` - 10 tests for incremental pipeline behavior
- `backend/tests/conftest.py` - file_tracker fixture added

## Decisions Made
- Used `overwrite_vectors` as internal parameter name in `_ingest_and_finalize` to distinguish from the `overwrite` kwarg on `add_chunks` -- reduces ambiguity
- Extracted `_ExtractionBundle` dataclass to bundle extraction results instead of passing multiple return values
- Changed `vector_store` property return type from `LanceDBVectorStore` to `VectorStoreProtocol` -- the old type annotation was incorrect for sqlite-vec backend

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed mock side_effect not cleared by reset_mock()**
- **Found during:** Task 2 (test implementation)
- **Issue:** `mock.reset_mock()` doesn't clear `side_effect`, causing `StopIteration` when tests set `return_value` after previously using `side_effect` with a list
- **Fix:** Added `mock_chunk_file.side_effect = None` after `reset_mock()` in 3 test methods
- **Files modified:** backend/tests/test_incremental_pipeline.py
- **Verification:** All 10 tests pass
- **Committed in:** 47dcdbf (Task 2 GREEN commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test code)
**Impact on plan:** Test-only fix, no impact on production code.

## Issues Encountered
None

## Known Stubs
None -- all data flows are wired end-to-end.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Incremental pipeline ready for CLI/API integration (Plan 02)
- `index(force=True)` available for CLI `--force` flag
- All 42 tests pass (29 existing + 13 new)

## Self-Check: PASSED

All 6 files verified present. All 4 commit hashes verified in git log.

---
*Phase: 02-incremental-pipeline-diff-based-indexing*
*Completed: 2026-03-23*
