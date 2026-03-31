---
phase: 01-storage-layer-file-tracking-delete-methods
verified: 2026-03-23T10:15:00Z
status: passed
score: 13/13 must-haves verified
re_verification: false
---

# Phase 01: Storage Layer -- File Tracking + Delete Methods Verification Report

**Phase Goal:** All stores can track file fingerprints and delete data by file path.
**Verified:** 2026-03-23T10:15:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | File fingerprints (path, mtime, size, checksum) persist in metadata.db across process restarts | VERIFIED | `file_tracker.py` CREATE TABLE (L30-37), `test_save_fingerprint_persists_and_survives_reconnect` passes |
| 2 | FileTracker.diff() classifies files as new/modified/deleted/unchanged | VERIFIED | `diff()` method (L80-138), 5 classification tests pass |
| 3 | Unchanged files (same mtime+size) skip checksum computation entirely | VERIFIED | Fast path (L112-115) returns without reading bytes; no `FileInfo.checksum` access in file |
| 4 | Modified files with same content but different mtime are classified as unchanged (mtime updated silently) | VERIFIED | Slow path checksum match (L120-129), `test_mtime_changed_content_same` passes, DB mtime updated |
| 5 | delete_chunks_by_file() removes all chunks for a given file_path from metadata store | VERIFIED | `metadata.py` DELETE FROM chunks WHERE file_path (L154-161), test passes |
| 6 | get_chunk_ids_by_file() returns chunk_id list before deletion | VERIFIED | `metadata.py` SELECT chunk_id FROM chunks WHERE file_path (L146-152), test passes |
| 7 | delete_vectors_by_chunk_ids() removes vectors and meta rows for given chunk IDs from sqlite-vec store | VERIFIED | `sqlite_vec.py` (L147-177) deletes from both vec_chunks and vec_meta, test passes |
| 8 | delete_vectors_by_chunk_ids([]) is a no-op returning 0 | VERIFIED | Early return at L149, `test_delete_empty_list_returns_zero` passes |
| 9 | Deleted vectors do not appear in search results | VERIFIED | `test_deleted_vectors_not_in_search_results` passes |
| 10 | delete_file_subgraph() removes Section nodes and their edges for a given file_path | VERIFIED | `graph.py` MATCH (s:Section {file_path: $fp}) DETACH DELETE s (L246), `test_removes_all_sections_for_file` passes |
| 11 | delete_file_subgraph() removes the File node and its edges for a given file_path | VERIFIED | `graph.py` MATCH (f:File {id: $fp}) DETACH DELETE f (L252), `test_removes_file_node` passes |
| 12 | delete_file_subgraph() preserves Entity and Tag nodes (shared across files) | VERIFIED | `test_preserves_entity_and_tag_nodes` passes (Entity=1, Tag=1 after delete) |
| 13 | DETACH DELETE cascade works across all 7 REL tables in the project schema | VERIFIED | 5 spike tests validate cascade across SECTION_ENTITY, SECTION_TAG, SECTION_SECTION, FILE_SECTION, FILE_TAG, FILE_ENTITY |

**Score:** 13/13 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/src/dotmd/ingestion/file_tracker.py` | FileTracker class + FileDiff dataclass, min 80 lines | VERIFIED | 175 lines, exports FileTracker + FileDiff, CREATE TABLE, hashlib.md5, no FileInfo.checksum access |
| `backend/src/dotmd/storage/base.py` | Extended protocols with delete methods | VERIFIED | delete_chunks_by_file, get_chunk_ids_by_file, delete_vectors_by_chunk_ids, delete_file_subgraph all present |
| `backend/src/dotmd/storage/metadata.py` | delete_chunks_by_file + get_chunk_ids_by_file + file_path index | VERIFIED | Both methods implemented, idx_chunks_file_path index created at init |
| `backend/src/dotmd/storage/sqlite_vec.py` | delete_vectors_by_chunk_ids implementation | VERIFIED | Method at L147-177, deletes from both vec_chunks and vec_meta via rowid lookup |
| `backend/src/dotmd/storage/graph.py` | delete_file_subgraph implementation | VERIFIED | Method at L235-253, DETACH DELETE Sections then File, preserves Entity/Tag |
| `backend/tests/test_file_tracker.py` | FileTracker unit tests, min 40 lines | VERIFIED | 178 lines, 8 tests (5 diff + 3 persistence) |
| `backend/tests/test_metadata_delete.py` | Metadata delete method tests, min 20 lines | VERIFIED | 96 lines, 5 tests (2 get_chunk_ids + 2 delete_chunks + 1 index) |
| `backend/tests/test_vector_delete.py` | Vector delete method tests, min 30 lines | VERIFIED | 86 lines, 5 tests (delete, empty, unknown, search exclusion, partial) |
| `backend/tests/test_graph_delete.py` | Graph delete + DETACH DELETE spike tests, min 50 lines | VERIFIED | 259 lines, 11 tests (5 spike + 6 functional) |
| `backend/tests/conftest.py` | Shared fixtures | VERIFIED | 5 fixtures: tmp_dir, metadata_store, sqlite_conn, vector_store, graph_store |
| `backend/pyproject.toml` | pytest in dev dependencies | VERIFIED | `dev = ["pytest>=8.0"]` in optional-dependencies |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `file_tracker.py` | metadata.db file_fingerprints table | sqlite3.Connection passed to __init__ | WIRED | CREATE TABLE IF NOT EXISTS file_fingerprints (L31), conn used for all SQL ops |
| `metadata.py` | chunks table | DELETE FROM chunks WHERE file_path | WIRED | L157: `DELETE FROM chunks WHERE file_path = ?`, commit on L160, returns rowcount |
| `sqlite_vec.py` | vec_meta + vec_chunks tables | DELETE via rowid lookup | WIRED | L156: SELECT rowid from vec_meta, L167: DELETE FROM vec_chunks, L172: DELETE FROM vec_meta |
| `graph.py` | Section and File node tables | DETACH DELETE Cypher | WIRED | L246: MATCH Section DETACH DELETE, L252: MATCH File DETACH DELETE |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All phase 1 tests pass | `.venv/bin/python -m pytest tests/ -v` | 29 passed in 1.75s | PASS |
| FileTracker importable | `.venv/bin/python -c "from dotmd.ingestion.file_tracker import FileTracker, FileDiff"` | OK | PASS |
| Protocol methods exist on concrete classes | `.venv/bin/python -c "hasattr checks"` | All 4 True | PASS |
| No FileInfo.checksum in FileTracker | `grep f.checksum/fi.checksum/file_info.checksum` | No matches | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| FT-01 | 01-01 | Persist file fingerprints (path, mtime, size, checksum) in metadata.db | SATISFIED | file_fingerprints table with all 4 fields + indexed_at, persistence test passes |
| FT-02 | 01-01 | Classify files as new/modified/deleted/unchanged on each index run | SATISFIED | FileDiff dataclass + diff() method, 5 classification tests |
| FT-03 | 01-01 | Skip unchanged files entirely (no re-read, no re-embed, no re-extract) | SATISFIED | Fast path skips checksum; no FileInfo.checksum (computed_field) access |
| SC-01 | 01-01 | Delete chunks by file_path from metadata store | SATISFIED | delete_chunks_by_file + get_chunk_ids_by_file, file_path index |
| SC-02 | 01-02 | Delete vectors by file_path from sqlite-vec store | SATISFIED | delete_vectors_by_chunk_ids via rowid lookup from vec_meta |
| SC-03 | 01-02 | Delete Section nodes and edges by file_path from graph store (preserve Entity/Tag nodes) | SATISFIED | delete_file_subgraph with DETACH DELETE cascade, spike tests validate |

**Orphaned requirements:** None. All 6 Phase 1 requirements (FT-01..03, SC-01..03) are claimed and satisfied.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| (none) | - | - | - | No anti-patterns detected |

No TODO/FIXME/PLACEHOLDER comments. No stub implementations. No hardcoded empty returns. No console.log-only handlers.

### Human Verification Required

None. All phase 1 deliverables are backend logic with full test coverage. No UI, no external service integration, no visual behavior to verify.

### Gaps Summary

No gaps found. All 13 observable truths verified. All 11 artifacts exist, are substantive, and are wired. All 4 key links confirmed. All 6 requirements satisfied. 29 tests pass. No anti-patterns detected.

---

_Verified: 2026-03-23T10:15:00Z_
_Verifier: Claude (gsd-verifier)_
