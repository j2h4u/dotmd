---
phase: 16-content-dedup-schema-many-to-many-chunks-to-file-paths
fixed_at: 2026-04-25T14:30:00Z
review_path: .planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-REVIEW.md
iteration: 1
findings_in_scope: 6
fixed: 6
skipped: 0
status: all_fixed
---

# Phase 16: Code Review Fix Report

**Fixed at:** 2026-04-25T14:30:00Z
**Source review:** 16-REVIEW.md
**Iteration:** 1

**Summary:**
- Findings in scope: 6 (CR-01 + WR-01 through WR-05; IN-01 and IN-02 excluded per non-`--all` scope)
- Fixed: 6
- Skipped: 0

All 155 tests pass (plus 1 expected xfail) after fixes. New CR-01 regression test added and passing.

---

## Fixed Issues

### CR-01: body_checksum formula mismatch — migrated chunk_ids diverged from fresh-index ids

**Files modified:** `backend/src/dotmd/ingestion/migration_v16.py`, `backend/tests/ingestion/test_migration_v16.py`, `backend/tests/conftest.py`
**Commit:** `793ba31`
**Applied fix:**

Replaced `_compute_body_checksum(text)` (using `blake3("text\n" + chunk_text)`) with a fingerprint-lookup approach:

- Added `_get_body_checksums_for_strategy(conn, strategy, file_paths)`: batch-fetches canonical checksums from `chunk_fingerprints_<strategy>` (which already stores `blake3(kind + "\n" + full_file_body)` — the exact same formula as `chunker.chunk_file`).
- Added `_compute_body_checksum_from_file(file_path, kind)`: disk-read fallback used when a file_path has no fingerprint row.
- `_compute_new_id_for_row` signature changed from `(text, chunk_index, strategy)` to `(body_checksum, chunk_index, strategy)` — it no longer computes the checksum internally.
- Step 4 in `_migrate_strategy` now: (1) collects all distinct file_paths, (2) batch-fetches checksums from fingerprints, (3) disk-reads any missing paths with a WARNING, (4) raises a clear `RuntimeError` with `dotmd index --force` guidance if a file is missing from both fingerprints and disk.
- `verify_only` divergence preview path updated with same fingerprint lookup (skips rows with missing fingerprints rather than aborting).

Test changes:
- Added `TestMigratedChunkIdMatchesChunker.test_migrated_chunk_id_matches_chunker_output`: writes a real markdown file, runs `chunker.chunk_file()` to get expected chunk_ids, seeds the DB with old-format ids and correct fingerprint row, runs migration, asserts migrated ids == chunker ids.
- Updated `collision_rich_db` fixture in `conftest.py` to populate `chunk_fingerprints_<strategy>` for all 6 test file paths.
- Updated 3 inline-DB tests (`TestPayloadInvariantMismatch`, `TestM2MRemapCoverage`, `TestPayloadDivergenceFailClosed._setup_divergent_db`) to insert fingerprint rows alongside chunk rows.
- Updated `_make_blake3_chunk_id` conftest helper to use `blake3(kind + "\n" + body)` (the correct formula).

Status: **fixed: requires human verification** (logic fix — tests confirm correctness but human should confirm the fingerprint table is always populated before migration is run in production).

---

### WR-01: Spurious _release_lock WARNING on closed connection in PayloadDivergenceBlocked path

**Files modified:** `backend/src/dotmd/ingestion/migration_v16.py`
**Commit:** `b5ed6d3`
**Applied fix:**

Added `_lock_released = False` guard variable before the `try:` block. In the `PayloadDivergenceBlocked` handler (real-run path), set `_lock_released = True` immediately after `_release_lock(conn)`. Updated `finally` block to check `elif not _lock_released:` before calling `_release_lock(conn)`, preventing the second release on an already-closed connection that produced the spurious `WARNING: Failed to release migration_v16_lock`.

---

### WR-02: Unquoted strategy name in PRAGMA and SELECT statements

**Files modified:** `backend/src/dotmd/ingestion/migration_v16.py`
**Commit:** `f7ad6ed`
**Applied fix:**

Added `import re` and:
- `_SAFE_STRATEGY_RE = re.compile(r"^[a-zA-Z0-9_]+$")` module-level constant.
- `_validate_strategy(strategy: str) -> str` helper that raises `ValueError` with a clear tampered-DB message if the name contains SQL-unsafe characters.
- Applied `_validate_strategy()` at the `_discover_strategies` return boundary — all strategy names are validated once at discovery, making every downstream f-string interpolation safe.

---

### WR-03: index_file write loop lacks wrapping transaction — orphan chunk possible on crash

**Files modified:** `backend/src/dotmd/storage/metadata.py`, `backend/src/dotmd/ingestion/pipeline.py`
**Commit:** `9fdac6f`
**Applied fix:**

- Added `_commit: bool = True` keyword-only parameter to `insert_chunk` and `add_file_path` in `metadata.py`. When `_commit=False`, the auto-commit is skipped so callers can batch inserts inside their own transaction. Default `True` preserves backward compatibility with all other call sites.
- In `pipeline.py:index_file`, wrapped the per-file chunk write loop with explicit `self._conn.execute("BEGIN")` / `COMMIT` / `ROLLBACK`, and called `insert_chunk(..., _commit=False)` and `add_file_path(..., _commit=False)` inside the loop. Both inserts now land atomically — a crash between the two cannot leave a `chunks_*` row without a `chunk_file_paths_*` entry.

---

### WR-04: delete_chunks_by_file calls helpers without BEGIN/COMMIT

**Files modified:** `backend/src/dotmd/storage/metadata.py`
**Commit:** `76577ea`
**Applied fix:**

Rewrote `delete_chunks_by_file` to wrap both helper calls in an explicit `BEGIN`/`COMMIT`/`ROLLBACK` using `object.__getattribute__(self._conn, "_real_conn")` to bypass the `_ConnProxy` wrapper. The M2M delete and orphan cascade are now atomic — a crash between them cannot leave M2M rows gone while chunk content rows persist (inverse orphan). Docstring updated to remove the suggestion to prefer the raw helpers and instead document the method's new atomicity guarantee.

---

### WR-05: Step 5d vector divergence check is permanently dead code

**Files modified:** `backend/src/dotmd/ingestion/migration_v16.py`
**Commit:** `ace3c7c`
**Applied fix:**

Removed the step 5d `for nc_id in non_canonical:` loop. `_fetch_vector_for_divergence_check` always returned `None` because the migration connection never loads the sqlite_vec extension, so the `if v_canon is not None and v_other is not None` guard never fired and `divergence_warnings` was never incremented. Replaced the loop with a concise comment explaining the removal rationale. The helper functions `_fetch_vector_for_divergence_check` and `_cosine_similarity` are retained (not removed) because existing tests patch `_fetch_vector_for_divergence_check` via `unittest.mock.patch`.

---

## Skipped Issues

None — all 6 in-scope findings were fixed.

---

_Fixed: 2026-04-25T14:30:00Z_
_Fixer: Claude (gsd-code-fixer)_
_Iteration: 1_
