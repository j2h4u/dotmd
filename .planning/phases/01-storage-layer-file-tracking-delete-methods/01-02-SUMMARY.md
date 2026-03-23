---
phase: 01-storage-layer-file-tracking-delete-methods
plan: 02
subsystem: storage
tags: [sqlite-vec, ladybugdb, vector-delete, graph-delete, detach-delete, cypher]

# Dependency graph
requires:
  - phase: 01-01
    provides: "Extended storage protocols with delete method signatures, conftest.py fixtures"
provides:
  - "delete_vectors_by_chunk_ids() on SQLiteVecVectorStore - removes vectors by chunk ID"
  - "delete_file_subgraph() on LadybugDBGraphStore - removes File+Section nodes preserving Entity/Tag"
  - "DETACH DELETE cascade validated across all 7 REL tables via spike tests"
affects: [02-incremental-pipeline]

# Tech tracking
tech-stack:
  added: []
  patterns: ["DETACH DELETE cascade for graph node cleanup (Sections first, then File)", "rowid-based vec0 virtual table deletion via meta table lookup"]

key-files:
  created:
    - backend/tests/test_vector_delete.py
    - backend/tests/test_graph_delete.py
  modified:
    - backend/src/dotmd/storage/sqlite_vec.py
    - backend/src/dotmd/storage/graph.py
    - backend/tests/conftest.py

key-decisions:
  - "DETACH DELETE order: Sections first, then File - ensures FILE_SECTION edges are cleaned by Section deletion before File node removal"
  - "Vector delete uses rowid lookup from vec_meta table, then deletes from both vec_chunks (vec0 virtual table) and vec_meta"

patterns-established:
  - "Graph delete pattern: delete owned nodes (Section) before owner (File) to let DETACH DELETE cascade handle edges"
  - "Spike tests: validate database engine behavior before building on assumptions"

requirements-completed: [SC-02, SC-03]

# Metrics
duration: 6min
completed: 2026-03-23
---

# Phase 01 Plan 02: Vector + Graph Delete Methods Summary

**Per-file vector and graph delete methods with LadybugDB DETACH DELETE cascade validation across all 7 REL tables**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-23T09:54:39Z
- **Completed:** 2026-03-23T10:00:29Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments
- delete_vectors_by_chunk_ids() removes vectors from both vec_chunks (vec0) and vec_meta tables using rowid lookup, with graceful handling of empty/unknown inputs
- delete_file_subgraph() removes Section and File nodes via DETACH DELETE, preserving shared Entity and Tag nodes
- LadybugDB DETACH DELETE cascade behavior validated across all 7 REL tables (FILE_SECTION, SECTION_SECTION, SECTION_ENTITY, SECTION_TAG, FILE_TAG, FILE_ENTITY, ENTITY_ENTITY)
- All three storage backends now have complete delete methods for incremental indexing

## Task Commits

Each task was committed atomically:

1. **Task 1 RED: Vector delete tests** - `6f5072c` (test)
2. **Task 1 GREEN: Vector delete implementation** - `d9d750b` (feat)
3. **Task 2 RED: Graph delete + spike tests** - `ed09775` (test)
4. **Task 2 GREEN: Graph delete implementation** - `9471878` (feat)

_TDD: RED (failing tests) -> GREEN (implementation) for each task_

## Files Created/Modified
- `backend/src/dotmd/storage/sqlite_vec.py` - Added delete_vectors_by_chunk_ids() method (32 lines)
- `backend/src/dotmd/storage/graph.py` - Added delete_file_subgraph() method (21 lines)
- `backend/tests/test_vector_delete.py` - 5 tests: valid delete, empty list, unknown IDs, search exclusion, partial match
- `backend/tests/test_graph_delete.py` - 11 tests: 5 spike (DETACH DELETE cascade) + 6 functional (delete_file_subgraph)
- `backend/tests/conftest.py` - Added vector_store and graph_store fixtures

## Decisions Made
- DETACH DELETE order: Sections first, then File. This ensures FILE_SECTION edges are already cleaned by Section cascade before the File node is removed, avoiding orphaned edges.
- Vector delete uses rowid lookup from vec_meta (which maps chunk_id to rowid), then deletes from both vec0 virtual table and vec_meta. This is needed because vec0 only supports rowid-based deletion.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Cherry-picked Plan 01 commits for dependencies**
- **Found during:** Task 1 (setup)
- **Issue:** This worktree was created from an early commit (020c405) before Plan 01's changes. Missing: conftest.py, extended base.py protocols, metadata.py changes.
- **Fix:** Cherry-picked commits 13e5f7c, 6e34b00, 1b96864 from worktree-agent-a6c2f2d5
- **Files modified:** none (used existing commits)
- **Verification:** All 13 Plan 01 tests pass after cherry-pick

**2. [Rule 3 - Blocking] Extracted sqlite_vec.py from feature branch**
- **Found during:** Task 1 (setup)
- **Issue:** sqlite_vec.py exists on feat/sqlite-vec-backend but not in this worktree's history (added by commit a29e727 before worktree diverged)
- **Fix:** `git show feat/sqlite-vec-backend:backend/src/dotmd/storage/sqlite_vec.py` into worktree, committed with Task 1 RED
- **Files modified:** backend/src/dotmd/storage/sqlite_vec.py
- **Verification:** Import succeeds, tests can instantiate SQLiteVecVectorStore

**3. [Rule 3 - Blocking] Created test venv for worktree**
- **Found during:** Task 1 (test execution)
- **Issue:** No .venv in this worktree (each worktree needs its own)
- **Fix:** Created .venv with pytest, pydantic, sqlite-vec, real-ladybug, pandas
- **Files modified:** none (venv is gitignored)
- **Verification:** All tests execute successfully

---

**Total deviations:** 3 auto-fixed (all blocking - parallel worktree setup)
**Impact on plan:** All necessary for test execution in parallel worktree. No scope creep.

## Issues Encountered
None - plan executed smoothly once worktree dependencies were resolved.

## User Setup Required
None - no external service configuration required.

## Known Stubs
None - all code is fully functional with no placeholder implementations.

## Next Phase Readiness
- All three stores now have per-file delete methods: metadata (Plan 01), vector (this plan), graph (this plan)
- Phase 2 can implement the full purge sequence: get_chunk_ids_by_file -> delete_vectors_by_chunk_ids -> delete_file_subgraph -> delete_chunks_by_file
- 29 tests across 4 test files provide regression safety for incremental pipeline development

## Self-Check: PASSED

All 5 claimed files verified present. All 4 commit hashes (6f5072c, d9d750b, ed09775, 9471878) confirmed in git log. Test file line counts: test_vector_delete.py=86 (min 30), test_graph_delete.py=259 (min 50). SUMMARY.md exists at expected path.

---
*Phase: 01-storage-layer-file-tracking-delete-methods*
*Completed: 2026-03-23*
