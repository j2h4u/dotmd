---
phase: 03-cli-api-polish
verified: 2026-03-23T13:15:00Z
status: passed
score: 8/8 must-haves verified
re_verification: false
---

# Phase 03: CLI & API Polish Verification Report

**Phase Goal:** Clean user-facing interface with progress reporting.
**Verified:** 2026-03-23T13:15:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | After indexing, CLI shows diff summary line: N new, N modified, N deleted, N unchanged | VERIFIED | cli.py:59-62 formats `stats.new_files`, `stats.modified_files`, `stats.deleted_files`, `stats.unchanged_files` |
| 2 | After indexing, CLI shows totals line: N files, N chunks, N entities, N edges | VERIFIED | cli.py:63-66 formats `stats.total_files`, `stats.total_chunks`, `stats.total_entities`, `stats.total_edges` |
| 3 | In verbose mode (-v), individual file operations appear in log output before the summary | VERIFIED | Pipeline logs file operations at INFO level (pipeline.py:196,201); setup_logging(verbose=True) enables INFO output |
| 4 | dotmd status shows pending changes when files have been added/modified since last index | VERIFIED | cli.py:120-127 checks `stats.data_dir` then shows "Pending:" or "No changes detected"; service.py:258-271 runs live diff via `file_tracker.diff()` |
| 5 | POST /index returns IndexStats JSON with diff fields (new_files, modified_files, deleted_files, unchanged_files) | VERIFIED | server.py:85-92 returns IndexStats; models.py:99-103 defines all diff fields; IndexStats JSON keys confirmed via behavioral spot-check |
| 6 | POST /index accepts force parameter | VERIFIED | server.py:52 `force: bool = False` on IndexRequest; server.py:92 passes `force=req.force` to service |
| 7 | Force mode reports all files as new_files in the diff summary | VERIFIED | pipeline.py:183 passes `"new": len(files)` in diff_counts for _full_index; test_force_index_all_new confirms assertion |
| 8 | No-changes short-circuit returns zeroed diff counts, not stale ones from previous run | VERIFIED | pipeline.py:149-154 explicitly zeros new/modified/deleted and sets unchanged=len(diff.unchanged); test_no_changes_fresh_counts confirms |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/src/dotmd/core/models.py` | IndexStats with diff fields and data_dir | VERIFIED | Lines 99-103: new_files, modified_files, deleted_files, unchanged_files (int=0), data_dir (str|None=None) |
| `backend/src/dotmd/storage/metadata.py` | Stats table schema migration + save/get for new columns | VERIFIED | Lines 98-112: idempotent ALTER TABLE for 5 new columns; lines 58-73: updated _UPSERT_STATS; lines 185-251: save_stats/get_stats handle new fields |
| `backend/src/dotmd/ingestion/pipeline.py` | Diff counts threaded into IndexStats | VERIFIED | Lines 223-314: _ingest_and_finalize accepts diff_counts param; lines 175-185: _full_index passes all-new counts; lines 187-217: _incremental_index passes real diff counts; lines 144-155: no-changes short-circuit returns fresh counts |
| `backend/src/dotmd/cli.py` | Diff summary output + status change detection | VERIFIED | Lines 48-49: @click.pass_context + ctx param; lines 59-66: diff summary + totals output; lines 120-127: pending changes display in status |
| `backend/src/dotmd/api/server.py` | force parameter on IndexRequest | VERIFIED | Line 52: `force: bool = False`; line 92: `force=req.force` |
| `backend/tests/test_diff_reporting.py` | Tests for diff count threading and edge cases | VERIFIED | 12 tests across 7 classes; all pass |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| pipeline.py | models.py | IndexStats construction with diff fields | WIRED | pipeline.py:300-310 uses `_dc.get("new", 0)` etc. in IndexStats() constructor |
| metadata.py | models.py | save_stats/get_stats reads and writes diff fields | WIRED | metadata.py:198-202 passes diff fields to SQL; metadata.py:246-250 reads them back into IndexStats |
| cli.py | service.py | service.index() returns IndexStats with diff fields | WIRED | cli.py:58 calls `service.index()`; cli.py:60 accesses `stats.new_files` |
| service.py | pipeline.py | status() runs file_tracker.diff() for change detection | WIRED | service.py:265 calls `self._pipeline.file_tracker.diff(files)` |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| cli.py (index) | stats | service.index() -> pipeline.index() -> diff counts from FileTracker.diff() | Yes -- real file system diff | FLOWING |
| cli.py (status) | stats | service.status() -> metadata_store.get_stats() + live file_tracker.diff() | Yes -- real DB query + live diff | FLOWING |
| server.py (index) | IndexStats | service.index() -> pipeline.index() | Yes -- same flow as CLI | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| IndexStats model has diff fields | `python -c "from dotmd.core.models import IndexStats; ..."` | "3 new, 1 modified, 0 deleted, 222 unchanged" + all 10 JSON keys | PASS |
| IndexRequest accepts force param | `python -c "from dotmd.api.server import IndexRequest; ..."` | force=True when set, force=False by default | PASS |
| CLI --help shows --force | `CliRunner().invoke(main, ['index', '--help'])` | Shows `-f, --force` with description | PASS |
| Test suite passes | `pytest tests/ -v` | 57 passed in 2.74s | PASS |
| Diff reporting tests pass | `pytest tests/test_diff_reporting.py -v` | 12 passed in 0.70s | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| CA-01 | 03-01-PLAN | `dotmd index` uses incremental by default | SATISFIED | pipeline.py:111 `force: bool = False`; pipeline.py:138 runs diff by default; CLI does not set force=True by default |
| CA-02 | 03-01-PLAN | `dotmd index --force` does full re-index | SATISFIED | cli.py:42-47 defines `--force/-f` flag; pipeline.py:135-136 routes to `_full_index` when force=True |
| CA-03 | 03-01-PLAN | Progress reporting: "3 new, 1 modified, 0 deleted, 222 unchanged" | SATISFIED | cli.py:59-62 prints diff summary; pipeline.py threads diff counts from FileDiff through IndexStats; 12 tests verify the flow |

No orphaned requirements found (REQUIREMENTS.md maps exactly CA-01, CA-02, CA-03 to Phase 3).

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| -- | -- | None found | -- | -- |

No TODOs, FIXMEs, placeholders, empty returns, or stub implementations found in any modified file.

### Human Verification Required

### 1. CLI Output Format

**Test:** Run `dotmd index ../data/` on real data and verify the output format.
**Expected:** Two lines after "Indexing...": (1) "N new, N modified, N deleted, N unchanged" and (2) "Done. N files, N chunks, N entities, N edges."
**Why human:** Requires running the full indexing pipeline with models loaded against real data.

### 2. Status Change Detection

**Test:** Run `dotmd index ../data/`, modify a file in `../data/`, then run `dotmd status`.
**Expected:** Status output shows "Pending: 0 new, 1 modified, 0 deleted since last index".
**Why human:** Requires full service initialization and actual file system mutations.

### 3. Verbose Mode Output

**Test:** Run `dotmd -v index ../data/` and verify individual file operations appear in log output.
**Expected:** Log lines showing per-file purge/ingest operations before the summary lines.
**Why human:** Requires running with real data to see logging output interleaved with Click output.

### Gaps Summary

No gaps found. All 8 observable truths verified. All 6 artifacts pass existence, substantive, and wiring checks. All 4 key links wired. All 3 requirements satisfied. No anti-patterns detected. 57 tests pass (12 new). All 3 commits verified in git history.

---

_Verified: 2026-03-23T13:15:00Z_
_Verifier: Claude (gsd-verifier)_
