---
phase: 01-storage-layer-file-tracking-delete-methods
plan: 01
subsystem: storage
tags: [sqlite, file-tracking, incremental-indexing, metadata, fingerprints]

# Dependency graph
requires: []
provides:
  - "FileTracker class with two-stage mtime+size then MD5 change detection"
  - "FileDiff dataclass (new/modified/deleted/unchanged file lists)"
  - "MetadataStoreProtocol extended with get_chunk_ids_by_file, delete_chunks_by_file"
  - "VectorStoreProtocol extended with delete_vectors_by_chunk_ids"
  - "GraphStoreProtocol extended with delete_file_subgraph"
  - "SQLiteMetadataStore implements per-file chunk query and deletion"
  - "idx_chunks_file_path index for efficient file-scoped queries"
  - "Pytest infrastructure (conftest.py, fixtures)"
affects: [01-02, 02-incremental-pipeline]

# Tech tracking
tech-stack:
  added: ["pytest>=8.0"]
  patterns: ["two-stage file change detection (mtime+size fast path, MD5 slow path)", "Protocol-first design with delete method extensions"]

key-files:
  created:
    - backend/src/dotmd/ingestion/file_tracker.py
    - backend/tests/__init__.py
    - backend/tests/conftest.py
    - backend/tests/test_file_tracker.py
    - backend/tests/test_metadata_delete.py
  modified:
    - backend/pyproject.toml
    - backend/src/dotmd/storage/base.py
    - backend/src/dotmd/storage/metadata.py

key-decisions:
  - "FileTracker uses explicit hashlib.md5() instead of FileInfo.checksum computed_field to avoid unnecessary file reads"
  - "file_fingerprints table shares the same SQLite database as metadata.db (via shared connection)"
  - "Added .venv/ to .gitignore for local test environment"

patterns-established:
  - "TDD workflow: RED (failing tests) -> GREEN (implementation) -> commit sequence"
  - "Test fixtures in conftest.py: tmp_dir, metadata_store, sqlite_conn"
  - "Two-stage file change detection: mtime+size match skips I/O entirely"

requirements-completed: [FT-01, FT-02, FT-03, SC-01]

# Metrics
duration: 5min
completed: 2026-03-23
---

# Phase 01 Plan 01: File Tracking + Metadata Delete Summary

**FileTracker with two-stage mtime+size/MD5 change detection, per-file chunk deletion methods, and extended storage protocols for incremental indexing**

## Performance

- **Duration:** 5 min
- **Started:** 2026-03-23T09:45:36Z
- **Completed:** 2026-03-23T09:50:15Z
- **Tasks:** 1
- **Files modified:** 8

## Accomplishments
- FileTracker class persists fingerprints in SQLite, classifies files as new/modified/deleted/unchanged
- Two-stage detection: mtime+size fast path avoids reading file bytes; MD5 checksum only on mismatch
- All three storage protocols extended with delete method signatures for incremental indexing
- SQLiteMetadataStore implements get_chunk_ids_by_file() and delete_chunks_by_file() with file_path index
- Pytest infrastructure bootstrapped with shared fixtures

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Failing tests** - `13e5f7c` (test)
2. **Task 1 GREEN: Implementation** - `6e34b00` (feat)

## Files Created/Modified
- `backend/src/dotmd/ingestion/file_tracker.py` - FileTracker class + FileDiff dataclass (155 lines)
- `backend/src/dotmd/storage/base.py` - Extended protocols with delete_chunks_by_file, delete_vectors_by_chunk_ids, delete_file_subgraph, get_chunk_ids_by_file
- `backend/src/dotmd/storage/metadata.py` - Implemented get_chunk_ids_by_file, delete_chunks_by_file, added idx_chunks_file_path index
- `backend/pyproject.toml` - Added pytest>=8.0 to dev optional-dependencies
- `backend/tests/conftest.py` - Shared fixtures: tmp_dir, metadata_store, sqlite_conn
- `backend/tests/test_file_tracker.py` - 8 tests covering diff classification and persistence
- `backend/tests/test_metadata_delete.py` - 5 tests covering per-file chunk operations and index existence
- `.gitignore` - Added .venv/

## Decisions Made
- Used explicit `hashlib.md5(path.read_bytes())` instead of `FileInfo.checksum` computed_field to avoid reading file bytes when not needed (the computed_field reads on every access)
- FileTracker shares the same SQLite connection/database as metadata store, creating its own `file_fingerprints` table via `CREATE TABLE IF NOT EXISTS`
- Added `.venv/` to `.gitignore` for local test environment created during execution

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Installed python3.13-venv system package**
- **Found during:** Task 1 (test execution)
- **Issue:** python3-venv not installed on system, preventing virtual environment creation for pytest
- **Fix:** `sudo apt install python3.13-venv`, then created .venv with minimal deps
- **Files modified:** none (system package)
- **Verification:** venv created, pytest runs successfully

**2. [Rule 2 - Missing Critical] Added .venv/ to .gitignore**
- **Found during:** Task 1 (after test environment setup)
- **Issue:** Generated .venv directory would be tracked by git
- **Fix:** Added `.venv/` entry to `.gitignore`
- **Files modified:** `.gitignore`
- **Verification:** `git status` shows no untracked .venv files

---

**Total deviations:** 2 auto-fixed (1 blocking, 1 missing critical)
**Impact on plan:** Both necessary for test execution environment. No scope creep.

## Issues Encountered
- No `pip` available on system (Docker-based project). Resolved by creating a lightweight venv with only pytest + pydantic for running unit tests locally.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all code is fully functional with no placeholder implementations.

## Next Phase Readiness
- FileTracker and metadata delete methods ready for Plan 02 (sqlite-vec delete methods)
- Phase 2 (incremental pipeline) can use FileTracker.diff() and delete_chunks_by_file()/get_chunk_ids_by_file()
- All storage protocols have delete signatures ready for concrete implementation

## Self-Check: PASSED

All 8 claimed files verified present. Both commit hashes (13e5f7c, 6e34b00) confirmed in git log. SUMMARY.md exists at expected path.

---
*Phase: 01-storage-layer-file-tracking-delete-methods*
*Completed: 2026-03-23*
