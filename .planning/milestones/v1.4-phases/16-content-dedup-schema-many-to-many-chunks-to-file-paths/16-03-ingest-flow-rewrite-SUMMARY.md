---
phase: 16-content-dedup-schema
plan: 03
subsystem: ingestion/storage
tags: [m2m, insert-or-ignore, advisory-lock, trickle, idempotent-ingest, payload-consistency]

dependency_graph:
  requires:
    - phase: 16-01
      provides: "M2M metadata layer: insert_chunk, add_file_path, get_stored_payload, ensure_m2m_table; Chunk model with file_paths list"
  provides:
    - "pipeline._index_file writes via INSERT OR IGNORE on chunks_* and chunk_file_paths_*"
    - "payload-consistency WARN on chunk_id conflict without overwriting first-writer row"
    - "storage/lock_constants.py: LOCK_TABLE shared constant"
    - "migration_v16.py imports LOCK_TABLE from lock_constants (no module-local duplicate)"
    - "TrickleIndexer startup advisory-lock check refuses to start while migration is running"
  affects: [16-04, 16-05, 16-06]

tech-stack:
  added: []
  patterns:
    - "INSERT OR IGNORE on content-addressed tables (chunks_*, chunk_file_paths_*, vec_meta_*)"
    - "module-reference import (import module as _m; _m.fn()) for monkeypatch testability"
    - "advisory-lock read-only sentinel check at trickle startup"
    - "settings-first TrickleIndexer constructor (pipeline optional)"
    - "autouse conftest fixtures for env + semantic engine stubbing"

key-files:
  created:
    - backend/src/dotmd/storage/lock_constants.py
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/ingestion/trickle.py
    - backend/src/dotmd/ingestion/migration_v16.py
    - backend/src/dotmd/storage/sqlite_vec.py
    - backend/src/dotmd/search/fts5.py
    - backend/tests/conftest.py

key-decisions:
  - "chunk_file imported as module reference (_chunker_module.chunk_file) so patch.object(_chunker, 'chunk_file') works in tests"
  - "TrickleIndexer constructor takes (settings, pipeline=None) — pipeline is optional so tests can check the lock guard without constructing a full pipeline"
  - "_run_index_loop() extracted from _run_locked() as a patchable hook for test isolation"
  - "sqlite_vec INSERT OR IGNORE on vec_meta_*: idempotent for identical-content chunks from different files"
  - "Trickle lock check is guardrail not mutex: documented in _check_migration_lock docstring"
  - "conftest autouse fixtures _dotmd_test_env + _mock_semantic_engine prevent network calls in all P3/P6 pipeline tests"

patterns-established:
  - "Rule 1 - Bug: Chunk.file_path → file_paths[0] pattern for primary-path graph/FTS5 lookups"
  - "Rule 1 - Bug: purge_orphaned_files + _purge_file_all_strategies query M2M table with legacy fallback"

requirements-completed: [DEDUP-05, DEDUP-07]

duration: ~35min
completed: 2026-04-25
---

# Phase 16 Plan 03: Ingest Flow Rewrite Summary

**INSERT OR IGNORE M2M write path in IndexingPipeline + advisory-lock startup guard in TrickleIndexer with shared lock_constants module**

## Performance

- **Duration:** ~35 min
- **Started:** 2026-04-25T07:05Z
- **Completed:** 2026-04-25T07:40Z
- **Tasks:** 2
- **Files modified:** 7 (1 created, 6 modified)

## Accomplishments

- `_index_file` now writes to `chunks_*` and `chunk_file_paths_*` via INSERT OR IGNORE only — the UPSERT-DO-UPDATE path that silently overwrote content-addressed rows is gone
- Payload-consistency check: on chunk_id conflict, existing row is compared to incoming payload; diverged fields are WARN-logged, first-writer's row is preserved (Review-HIGH-P3)
- `TrickleIndexer.__init__` checks `migration_v16_lock` read-only at startup; raises `RuntimeError` and logs error if lock is held in any mode (run or dry-run)
- `storage/lock_constants.py` ships the shared `LOCK_TABLE` constant; `migration_v16.py` now imports from it; `trickle.py` also imports from it — no cross-module runtime dependency on migration module
- 28/28 P3 + P1 Wave-1 tests green

## New Ingest Pseudocode

```python
# Per chunk from chunker:
existing = metadata.get_stored_payload(strategy, c.chunk_id)
if existing is not None:
    diverged = [f for f, (a, b) in {
        "text": (existing["text"], c.text),
        "heading_hierarchy": (existing["heading_hierarchy"], c.heading_hierarchy),
        "level": (existing["level"], c.level),
    }.items() if a != b]
    if diverged:
        logger.warning("ingest_payload_mismatch chunk_id=%s file=%s diverged_fields=%s",
                       c.chunk_id, path_str, diverged)
    # Fall through to INSERT OR IGNORE — first-writer wins

metadata.insert_chunk(strategy, c.chunk_id, c.heading_hierarchy, c.level, c.text)
metadata.add_file_path(strategy, c.chunk_id, path_str, c.chunk_index)
```

## Trickle Startup Lock Check

Placed in `TrickleIndexer.__init__` via `_check_migration_lock(settings.index_db_path)`.

**Why `__init__` (not `run()`):** The lock check must happen before any work starts, including before the fcntl file lock is acquired. If trickle blocked on the file lock while migration held the advisory lock, a retry loop could create a deadlock scenario.

**Implementation:** Opens `index.db` with `?mode=ro` URI (never writes). Checks `sqlite_master` for the lock table (absent = fresh DB = proceed). If table exists, checks for `id=1` row. If held, logs error and raises `RuntimeError`.

**This is a guardrail, not full mutual exclusion.** If trickle is already running when migration begins, migration's lock INSERT will see no prior row and the race is possible. The operational runbook (P2 SUMMARY) instructs operators to stop the trickle service (`systemctl stop dotmd-trickle`) before running `dotmd migrate run`.

## Interaction with Phase 15 Embedding Cache

The `_embed_chunks` path is unchanged. The embedding cache (`EmbeddingCache`) deduplicates by `text_hash` — content-identical chunks from different files produce the same `text_hash`, so the second file's chunks get cache hits and no new TEI calls are made. The `vec_meta_*` write path now uses `INSERT OR IGNORE` in `sqlite_vec.py` so duplicate `chunk_id` rows from re-indexing are no-ops.

## Operational Runbook (stop trickle before migration)

```bash
# 1. Stop the trickle indexer (prevents advisory-lock race)
systemctl stop dotmd-trickle  # or: docker compose stop (if running in container)

# 2. Verify trickle is stopped
systemctl status dotmd-trickle

# 3. Run migration
dotmd migrate run /path/to/index.db

# 4. Restart trickle (after migration completes successfully)
systemctl start dotmd-trickle
```

If the migration was interrupted and the lock is stuck:
```bash
sqlite3 ~/.dotmd/index.db "DELETE FROM migration_v16_lock WHERE id = 1;"
```

## migration_v16.py LOCK_TABLE Import Swap

`migration_v16.py` previously defined `migration_v16_lock` as a string literal directly in SQL. This plan adds `from dotmd.storage.lock_constants import LOCK_TABLE` at the top of `migration_v16.py`. All in-module SQL references (`INSERT INTO migration_v16_lock`, `DELETE FROM migration_v16_lock`, etc.) continue to use the string literal directly in SQL — which is correct since SQL table names are not Python constants. The import is purely for `trickle.py` to share the same value without importing the migration module.

## Task Commits

1. **Task 1: lock_constants + pipeline M2M write path + payload-consistency check** — `4a80fe9`
2. **Task 2: TrickleIndexer startup advisory-lock check** — `50dbd3e`

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Chunk.file_path → file_paths (P1 model change not propagated)**
- **Found during:** Task 1 (running test_pipeline_m2m_insert)
- **Issue:** After P1 renamed `Chunk.file_path: Path` to `Chunk.file_paths: list[Path]`, several callers in pipeline.py, fts5.py, and reindex_graph were still using `c.file_path`
- **Fix:** Updated all callers to use `c.file_paths[0]` (primary path) or `{p for c in chunks for p in c.file_paths}` (full set)
- **Files modified:** `pipeline.py`, `fts5.py`
- **Committed in:** 4a80fe9

**2. [Rule 1 - Bug] get_chunk_ids_by_file called without strategy arg**
- **Found during:** Task 1
- **Issue:** P1 added `strategy` as first positional arg to `get_chunk_ids_by_file(strategy, file_path)`. Three call sites in pipeline.py were still passing only `file_path`
- **Fix:** Added `self._strategy` as first arg at all three call sites (_index_file, _purge_file, _embed_existing_chunks)
- **Files modified:** `pipeline.py`
- **Committed in:** 4a80fe9

**3. [Rule 1 - Bug] sqlite_vec.add_chunks used plain INSERT on vec_meta_* (UNIQUE violation)**
- **Found during:** Task 1 (test_two_files_identical_content_share_chunk)
- **Issue:** When two files share a chunk_id, the second file's vec write raised `sqlite3.IntegrityError: UNIQUE constraint failed` on `vec_meta_*.chunk_id`
- **Fix:** Changed `INSERT INTO vec_meta_*` to `INSERT OR IGNORE`; skip vec0 insert when `lastrowid == 0` (no-op)
- **Files modified:** `sqlite_vec.py`
- **Committed in:** 4a80fe9

**4. [Rule 1 - Bug] purge_orphaned_files queried file_path from chunks_* (column dropped in P1)**
- **Found during:** Task 1 code audit
- **Issue:** `purge_orphaned_files` and `_purge_file_all_strategies` still queried `SELECT DISTINCT file_path FROM chunks_*` — that column no longer exists post-P1 migration
- **Fix:** Both methods now query `chunk_file_paths_*` M2M table with legacy fallback to `chunks_*.file_path` for pre-migration DBs
- **Files modified:** `pipeline.py`
- **Committed in:** 4a80fe9

**5. [Rule 1 - Bug] chunk_file imported by-name so monkeypatch.object(_chunker, ...) had no effect**
- **Found during:** Task 1 (test_payload_mismatch_logs_warn_without_overwriting)
- **Issue:** `from dotmd.ingestion.chunker import chunk_file` binds the function directly; `patch.object(_chunker, 'chunk_file', ...)` patches the module attribute but the pipeline's local binding is unaffected
- **Fix:** Changed to `import dotmd.ingestion.chunker as _chunker_module` and called `_chunker_module.chunk_file()` — matches migration_v16.py pattern
- **Files modified:** `pipeline.py`
- **Committed in:** 4a80fe9

**6. [Rule 2 - Missing infrastructure] conftest missing autouse env + semantic engine mock**
- **Found during:** Task 1 (Settings constructor failed: embedding_url required; TEI HTTP call failed in tests)
- **Issue:** P6 RED test skeletons construct `Settings(index_dir=...)` without `embedding_url` (required field, no default). Pipeline also tried to call TEI for embeddings
- **Fix:** Added `_dotmd_test_env` autouse fixture (sets DOTMD_EMBEDDING_URL + DOTMD_EXTRACT_DEPTH=structural) and `_mock_semantic_engine` autouse fixture (stubs encode_batch + get_tei_model_id)
- **Files modified:** `tests/conftest.py`
- **Committed in:** 4a80fe9

---

**Total deviations:** 6 auto-fixed (4 Rule 1 bugs from P1 model changes not fully propagated, 1 Rule 1 import pattern, 1 Rule 2 test infrastructure)
**Impact on plan:** All fixes were consequences of P1 schema/model changes that pipeline.py hadn't fully caught up with. No scope creep.

## Known Stubs

None. All production code paths are fully implemented.

## Threat Flags

No new security-relevant surface beyond the plan's threat model. T-16-09 (trickle racing migration) mitigated by startup guard. T-16-10 (UPSERT clobber) mitigated by INSERT OR IGNORE. T-16-21 (payload mismatch) mitigated by conflict check + WARN log.

## Self-Check: PASSED

**Files created:**
- `backend/src/dotmd/storage/lock_constants.py` — EXISTS

**Files modified:**
- `backend/src/dotmd/ingestion/pipeline.py` — EXISTS
- `backend/src/dotmd/ingestion/trickle.py` — EXISTS
- `backend/src/dotmd/ingestion/migration_v16.py` — EXISTS
- `backend/src/dotmd/storage/sqlite_vec.py` — EXISTS
- `backend/src/dotmd/search/fts5.py` — EXISTS
- `backend/tests/conftest.py` — EXISTS

**Commits:**
- `4a80fe9` — feat(16-03): Task 1: EXISTS
- `50dbd3e` — feat(16-03): Task 2: EXISTS

**Test results:** 28/28 Wave-1 P3 + P1 tests GREEN
