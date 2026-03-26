---
phase: 02-incremental-pipeline-diff-based-indexing
verified: 2026-03-23T12:10:00Z
status: passed
score: 10/10 must-haves verified
---

# Phase 02: Incremental Pipeline Verification Report

**Phase Goal:** `index()` only processes changed files. Full re-index available via `--force`.
**Verified:** 2026-03-23T12:10:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Modified files have old data purged from all 3 stores before re-ingestion | VERIFIED | `_purge_file` calls get_chunk_ids_by_file, delete_vectors_by_chunk_ids, delete_chunks_by_file, delete_file_subgraph in order (pipeline.py:289-303). Test `test_modified_file_purges_then_reingests` passes. |
| 2 | New files are ingested normally into all stores | VERIFIED | `_incremental_index` collects new+modified paths, passes to `_ingest_and_finalize` (pipeline.py:187-194). Test `test_new_file_ingested_existing_untouched` passes. |
| 3 | Deleted files are purged from all 3 stores and have fingerprints removed | VERIFIED | `_incremental_index` calls `_purge_file` then `remove_fingerprint` for each deleted path (pipeline.py:177-180). Test `test_deleted_file_purges_and_removes_fingerprint` verifies fingerprint row removed from DB. |
| 4 | BM25 index is rebuilt from all chunks after every incremental run | VERIFIED | `_ingest_and_finalize` always calls `get_all_chunks` then `build_index` (pipeline.py:240-242). Test `test_bm25_rebuilt_on_delete` verifies BM25 rebuild even on delete-only runs. |
| 5 | Unchanged files are not re-read, re-embedded, or re-extracted | VERIFIED | When `diff` has no changes, `index()` returns early with cached stats (pipeline.py:143-146). Test `test_unchanged_files_skip_embedding` asserts zero calls to read_file, chunk_file, and encode_batch. |
| 6 | Fingerprints are saved AFTER successful ingestion, not before | VERIFIED | `_update_fingerprints` called at line 261, after chunk save (226-227), embedding (230-237), BM25 rebuild (240-242), and extraction (245-248). Test `test_fingerprints_saved_after_ingestion` verifies call ordering. |
| 7 | add_chunks with overwrite=False appends without wiping existing vectors | VERIFIED | `if overwrite:` guard around DELETE statements (sqlite_vec.py:132-135). Test `test_add_chunks_overwrite_false_appends` asserts count goes from 3 to 5. |
| 8 | DotMDService.index() accepts force parameter and passes it to pipeline | VERIFIED | `service.py:83`: `def index(self, directory: Path, *, force: bool = False)`. Line 102: `return self._pipeline.index(directory, force=force)`. 3 tests in test_service_force.py verify threading. |
| 9 | CLI `dotmd index --force` triggers full re-index via service | VERIFIED | cli.py:43-47: `@click.option("--force", "-f", is_flag=True, ...)`. Line 57: `service.index(directory, force=force)`. `--help` output confirms flag present. |
| 10 | CLI `dotmd index` without --force uses incremental mode | VERIFIED | cli.py:48: `force: bool` parameter with `default=False`. Line 55: mode_label shows "incremental" when force is False. |

**Score:** 10/10 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/src/dotmd/storage/sqlite_vec.py` | add_chunks with overwrite parameter | VERIFIED | `overwrite: bool = True` on line 123, `if overwrite:` guard on line 132 |
| `backend/src/dotmd/storage/base.py` | Updated VectorStoreProtocol with overwrite param | VERIFIED | `overwrite: bool = True` on line 35, docstring documents behavior |
| `backend/src/dotmd/ingestion/pipeline.py` | Incremental indexing flow with _purge_file, _incremental_index, _full_index | VERIFIED | 431 lines. All three methods present. FileTracker on line 90. _ExtractionBundle dataclass. |
| `backend/tests/test_incremental_pipeline.py` | Tests for incremental pipeline behavior (min 80 lines) | VERIFIED | 544 lines, 10 test methods across 8 test classes |
| `backend/src/dotmd/api/service.py` | force parameter threaded through service | VERIFIED | `force: bool = False` on line 83, `force=force` on line 102 |
| `backend/src/dotmd/cli.py` | --force CLI flag | VERIFIED | `--force` / `-f` Click option on lines 43-47, `force: bool` in signature on line 48 |
| `backend/tests/test_service_force.py` | Tests for force parameter threading (min 30 lines) | VERIFIED | 43 lines, 3 test methods |
| `backend/tests/test_vector_delete.py` | Tests for overwrite parameter | VERIFIED | 138 lines total, 3 overwrite tests (lines 89-137) alongside 5 delete tests |
| `backend/tests/conftest.py` | file_tracker fixture | VERIFIED | Lines 45-48: fixture shares metadata_store._conn |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pipeline.py::_purge_file | metadata/vector/graph stores | ordered method calls | WIRED | Lines 296-303: get_chunk_ids -> delete_vectors -> delete_chunks -> delete_file_subgraph |
| pipeline.py::_incremental_index | file_tracker.diff | self._file_tracker instance | WIRED | Line 137: `diff = self._file_tracker.diff(files)` |
| pipeline.py::_incremental_index | vector_store.add_chunks | overwrite=False via _ingest_and_finalize | WIRED | Line 193: `overwrite_vectors=False` -> line 235: `overwrite=overwrite_vectors` |
| cli.py::index | service.index(force=force) | Click option passed to service | WIRED | Line 57: `service.index(directory, force=force)` |
| service.py::index | pipeline.index(force=force) | Service delegates to pipeline | WIRED | Line 102: `self._pipeline.index(directory, force=force)` |

### Data-Flow Trace (Level 4)

Not applicable -- pipeline.py is an orchestrator (not a UI component rendering dynamic data). Data flows through stores verified via key links and tests.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 45 tests pass | `pytest -x -v` | 45 passed in 2.63s | PASS |
| Phase 02 tests pass | `pytest tests/test_incremental_pipeline.py tests/test_vector_delete.py tests/test_service_force.py -x -v` | 21 passed in 1.34s | PASS |
| CLI --force flag present | `CliRunner().invoke(main, ['index', '--help'])` | Output contains `-f, --force` with description | PASS |
| 7 commit hashes exist | `git log --oneline <hash> -1` for each | All 7 resolved to correct messages | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| IP-01 | 02-01-PLAN | Modified files: purge old data from all stores, then re-ingest | SATISFIED | `_purge_file` + `_incremental_index` re-ingestion flow. Test: `test_modified_file_purges_then_reingests` |
| IP-02 | 02-01-PLAN | New files: ingest normally (embed + NER + graph) | SATISFIED | `_incremental_index` collects diff.new into files_to_ingest. Test: `test_new_file_ingested_existing_untouched` |
| IP-03 | 02-01-PLAN | Deleted files: purge from all stores | SATISFIED | `_purge_file` + `remove_fingerprint` for each deleted path. Test: `test_deleted_file_purges_and_removes_fingerprint` |
| IP-04 | 02-01-PLAN | BM25 index rebuilt from all chunks after diff applied | SATISFIED | `_ingest_and_finalize` always does full BM25 rebuild (line 242). Test: `test_bm25_rebuilt_on_delete` |
| IP-05 | 02-02-PLAN | --force flag to bypass fingerprints and do full re-index | SATISFIED | CLI `--force` -> service.index(force=True) -> pipeline.index(force=True) -> `_full_index`. Tests: `test_force_processes_all_files`, `test_force_clears_fingerprints`, `test_force_*_passed_through` |

No orphaned requirements found. REQUIREMENTS.md maps IP-01..IP-05 to Phase 2, all accounted for in plans.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| None | - | - | - | No anti-patterns detected |

No TODOs, FIXMEs, placeholders, empty returns, or stub implementations found in any modified file.

### Human Verification Required

### 1. End-to-End Incremental Timing

**Test:** Run `dotmd index /mnt/voicenotes` twice -- first full, then with 1 file changed.
**Expected:** Second run completes in seconds (not minutes), processing only the changed file.
**Why human:** Requires real data directory and timing measurement against the 226-file corpus.

### 2. Force Mode Full Re-Index

**Test:** Run `dotmd index /mnt/voicenotes --force` after an incremental run.
**Expected:** All files re-indexed, no stale data from previous runs.
**Why human:** Requires real data and visual inspection of stats output.

### Gaps Summary

No gaps found. All 10 observable truths verified, all 9 artifacts substantive and wired, all 5 key links confirmed, all 5 requirements satisfied, no anti-patterns detected, all 45 tests pass.

---

_Verified: 2026-03-23T12:10:00Z_
_Verifier: Claude (gsd-verifier)_
