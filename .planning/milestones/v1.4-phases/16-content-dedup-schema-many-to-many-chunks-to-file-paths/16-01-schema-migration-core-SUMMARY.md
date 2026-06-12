---
phase: 16-content-dedup-schema
plan: 01
subsystem: storage/ingestion
tags: [migration, m2m, schema, blake3, dedup, shadow-column, fail-closed]
dependency_graph:
  requires: [16-06]
  provides: [migration_v16, m2m-metadata-layer, migration_v15-stub]
  affects: [16-02, 16-03, 16-04, 16-05]
tech_stack:
  added: []
  patterns:
    - shadow-column flow (ADD COLUMN → compute → collapse → PK UPDATE → DROP COLUMN)
    - M2M redirect-before-delete (cycle-2 NEW-HIGH-1 pattern)
    - fail-closed divergence gate with explicit override flag (Decision #10)
    - INSERT OR IGNORE for content-immutable chunk tables (D-07)
    - caller-owned transaction contract for delete helpers (D-06)
    - _ConnProxy wrapper enabling test spy on sqlite3 connection methods
    - module-level hook (_attempt_drop_column) enabling monkeypatching of C extension
key_files:
  created:
    - backend/src/dotmd/ingestion/migration_v16.py
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/storage/metadata.py
    - backend/src/dotmd/ingestion/migration_v15.py
    - backend/tests/conftest.py
    - backend/tests/ingestion/test_migration_v16.py
decisions:
  - "Chunk model uses ConfigDict(extra='forbid') to reject char_offset and any unknown fields"
  - "_ConnProxy wraps sqlite3.Connection in metadata.py to allow test spy on execute"
  - "chunk_file() content param made optional (reads from disk if None)"
  - "_attempt_drop_column module-level hook enables monkeypatching without C extension issues"
  - "migration_v16 pre-flight creates infrastructure tables via _ensure_state_table before wrapping BEGIN"
  - "conftest.py tmp_index_db fixture pre-creates migration_v16 tables for stable before-hash baseline"
  - "dry-run/verify-only use wrapping BEGIN+ROLLBACK (no WAL pragma) to leave DB byte-identical"
metrics:
  duration: "~45m"
  completed: "2026-04-25"
  tasks: 3
  files_created: 1
  files_modified: 6
---

# Phase 16 Plan 01: Schema Migration Core Summary

Delivered the Phase 16 schema migration substrate: per-strategy M2M `chunk_file_paths_*` tables, blake3 id remap via shadow-column flow with collision collapse, fail-closed payload divergence policy, and `migration_v15.py` stubbed out.

## Shadow-Column Flow (Corrected Order)

The migration executes the following SQL steps per strategy inside a transaction:

```
BEGIN

-- Step 1: M2M table + index
CREATE TABLE IF NOT EXISTS chunk_file_paths_<strategy> (
    chunk_id TEXT NOT NULL, file_path TEXT NOT NULL, chunk_index INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)
CREATE INDEX IF NOT EXISTS idx_chunk_file_paths_<strategy>_file_path ON chunk_file_paths_<strategy>(file_path)

-- Step 2: Backfill M2M from current chunks_* (still has old file_path / chunk_index)
INSERT OR IGNORE INTO chunk_file_paths_<strategy> (chunk_id, file_path, chunk_index)
SELECT chunk_id, file_path, chunk_index FROM chunks_<strategy>

-- Step 3: Add shadow column (no PK conflict — not a PK column)
ALTER TABLE chunks_<strategy> ADD COLUMN new_chunk_id TEXT

-- Step 4: Compute new blake3 id per row (calls chunker._make_chunk_id via module ref)
UPDATE chunks_<strategy> SET new_chunk_id = :new_id WHERE chunk_id = :old_id  -- (per row)

-- Step 5: Detect collision groups (new_chunk_id duplicates)
SELECT new_chunk_id, GROUP_CONCAT(chunk_id, '|'), COUNT(*) FROM chunks_<strategy>
GROUP BY new_chunk_id HAVING COUNT(*) > 1

  -- 5a: payload_invariant_check (text MUST match — hard abort if not)
  -- 5b: canonical_old_id = MIN(old_ids) — payload-source row
  -- 5c: [cycle-2 NEW-HIGH-1 fix] M2M redirect BEFORE delete:
  UPDATE chunk_file_paths_<strategy> SET chunk_id = :canonical_old_id
  WHERE chunk_id IN (<non_canonical>)
  -- 5d: vector divergence WARN if cosine > 0.01 (Decision #4, no abort)
  -- 5e: Collapse DELETE non-canonical rows from chunks_* / vec_meta_* / chunks_fts_*
  DELETE FROM chunks_<strategy> WHERE chunk_id IN (<non_canonical>)

-- Step 5f: [cycle-2 NEW-HIGH-2 fix] Fail-closed divergence gate
-- If heading_hierarchy or level diverges in ANY collision group:
--   without flag: write divergence_report.txt, update state, ROLLBACK, raise PayloadDivergenceBlocked
--   with flag: log WARN per group, increment payload_mismatch_warnings, continue

-- Step 6: Sanity — zero remaining new_chunk_id duplicates
SELECT COUNT(*) FROM (SELECT new_chunk_id FROM chunks_<strategy> GROUP BY new_chunk_id HAVING COUNT(*) > 1)

-- Step 7: Remap M2M / vec_meta / chunks_fts to new_chunk_ids (BEFORE PK update)
UPDATE chunk_file_paths_<strategy> SET chunk_id = (
    SELECT new_chunk_id FROM chunks_<strategy> c WHERE c.chunk_id = chunk_file_paths_<strategy>.chunk_id
) WHERE chunk_id IN (SELECT chunk_id FROM chunks_<strategy>)

-- Step 8: PK update (safe now — uniqueness guaranteed)
UPDATE chunks_<strategy> SET chunk_id = new_chunk_id

-- Step 9: Drop shadow + legacy columns (ALTER TABLE DROP COLUMN, fallback to rebuild)
ALTER TABLE chunks_<strategy> DROP COLUMN new_chunk_id
ALTER TABLE chunks_<strategy> DROP COLUMN file_path
ALTER TABLE chunks_<strategy> DROP COLUMN chunk_index
ALTER TABLE chunks_<strategy> DROP COLUMN char_offset

-- Step 10: State marker
INSERT OR REPLACE INTO migration_v16_state (strategy, status, completed_at, ...) VALUES (...)

COMMIT  -- or ROLLBACK for dry_run
```

## Canonical-vs-Final-ID Terminology

- **canonical_old_id** = `MIN(old_chunk_ids in collision group)` — the row whose `heading_hierarchy` and `level` values are kept when a collision group collapses.
- **final chunk_id** = 64-hex blake3 value derived from `_make_chunk_id(body_checksum, chunk_index, strategy)`. The final id is NEVER an old id — it is always computed from content.
- The canonical old row is the one that survives the `DELETE` in step 5e. After step 8 (`SET chunk_id = new_chunk_id`), its chunk_id becomes the blake3 value.

## Payload Invariant Check Outcome Format

```
HARD ERROR (exit 5, rollback):
  RuntimeError: "HARD ERROR: strategy=<s> new_chunk_id=<id> has N members with DIFFERENT text values"

Soft divergence (heading_hierarchy or level differ):
  divergence_record = {
      "strategy": "heading_512_50",
      "new_chunk_id": "<64-hex>",
      "old_ids": ["old_id_aaa", "old_id_bbb"],
      "diverged_fields": ["heading_hierarchy"],
      "chosen_canonical_old_id": "old_id_aaa",
      "payloads": {
          "old_id_aaa": {"heading_hierarchy": '["Context A"]', "level": 1},
          "old_id_bbb": {"heading_hierarchy": '["Context B"]', "level": 2},
      }
  }
```

## Fail-Closed Divergence Policy (Decision #10)

**Default (no flag):**
- Migration writes `<run_dir>/divergence_report.txt`
- Updates `migration_v16_state` with `status='payload_divergence_blocked'` and `payload_divergences` JSON
- ROLLBACKs the per-strategy transaction (DB unchanged)
- Raises `PayloadDivergenceBlocked` — CLI translates to exit code 4

**Override (`allow_payload_divergence=True`):**
- Logs `payload_mismatch_override` WARN per divergent group (structured, not string)
- Increments `payload_mismatch_warnings` counter
- Persists `allow_payload_divergence=1` + full `payload_divergences` JSON to `migration_v16_state`
- Migration continues to completion

**`--verify-only` preview:**
- Computes divergence count read-only (no mutation)
- `report.payload_divergence_preview = {"count": N, "example_paths": [...]}`
- Returns exit 4 hint if count > 0 and flag not set

**`divergence_report.txt` format:**
```
strategy=<s> new_id=<id> old_ids=<csv> diverged_fields=<csv> canonical=<id>
  <old_id_1>: heading_hierarchy=... level=...
  <old_id_2>: heading_hierarchy=... level=...
```

## Cycle-2 NEW-HIGH-1 Fix: M2M Redirect-Before-Delete

Step 5c is the sole fix for cycle-2 NEW-HIGH-1 (non-canonical M2M rows orphaned after collapse DELETE).

Before step 5e deletes non-canonical chunk rows, step 5c UPDATEs every `chunk_file_paths_<strategy>` row pointing to a non-canonical old_id to point to the canonical_old_id instead. After this redirect, ALL M2M rows in the group point to the canonical old_id which will survive the DELETE. Step 7 then remaps them to the final blake3 id.

Result: a 3-file collision group yields 1 `chunks_*` row + 3 `chunk_file_paths_*` rows post-migration, with zero orphan M2M rows.

## Cycle-2 NEW-HIGH-2 Fix: Fail-Closed Divergence

Step 5f is the sole fix for cycle-2 NEW-HIGH-2 (heading/level divergence was silently overwritten by canonical-keep without operator knowledge). See "Fail-Closed Divergence Policy" above.

## How P3/P4/P5 Should Consume the New Metadata Helpers

| Helper | Usage |
|--------|-------|
| `insert_chunk(strategy, chunk_id, heading_hierarchy, level, text)` | INSERT OR IGNORE — call once per content address; on conflict the row is left unchanged |
| `add_file_path(strategy, chunk_id, file_path, chunk_index)` | INSERT OR IGNORE — idempotent; call for every (chunk, file) association |
| `get_file_paths_by_chunk_id(strategy, chunk_id) -> list[str]` | Returns distinct paths sorted lex (D-01) |
| `get_file_paths_for_chunk_ids(strategy, chunk_ids) -> dict[str, list[str]]` | Batch hydration — single SELECT IN (...); use for search result rendering (P5) |
| `get_stored_payload(strategy, chunk_id) -> dict | None` | P3 conflict check: verify text/heading/level on INSERT OR IGNORE collision |
| `delete_m2m_for_file(strategy, file_path, *, conn) -> list[str]` | P4 purge: returns orphan chunk_ids. **Caller must wrap in BEGIN/COMMIT.** |
| `delete_orphan_chunks(strategy, chunk_ids, *, conn)` | P4 purge: deletes from chunks_*. **Caller must wrap in BEGIN/COMMIT.** |
| `run_invariants(conn) -> InvariantReport` | P2 --verify-only + P6 tests: single source of truth for invariant checks |

**Transaction ownership for delete helpers**: `delete_m2m_for_file` and `delete_orphan_chunks` accept a caller-supplied `sqlite3.Connection` and do NOT call `commit()`. The pipeline (P4) must wrap the full per-file cascade in `BEGIN/COMMIT` for atomicity.

## _make_chunk_id Import Confirmation

`migration_v16.py` imports the chunker module as `import dotmd.ingestion.chunker as _chunker_module` and calls `_chunker_module._make_chunk_id(body_checksum, chunk_index, strategy)` in `_compute_new_id_for_row()`. The module-reference pattern (rather than `from dotmd.ingestion.chunker import _make_chunk_id`) ensures monkeypatching in `test_uses_chunker_make_chunk_id_helper` works correctly.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed `fts_exists` UnboundLocalError in `_migrate_strategy`**
- **Found during:** Task 2 test run — `test_collision_group_payload_invariant_mismatch_logs_warn` failed
- **Issue:** `fts_exists` was checked inside the collision loop (step 5e) before it was assigned (it was later assigned in step 7 context). 
- **Fix:** Moved `fts_exists` lookup to before the collision loop.
- **Files modified:** `migration_v16.py`

**2. [Rule 1 - Bug] PRAGMA journal_mode=WAL changes DB bytes — broke dry-run byte-equality test**
- **Found during:** Task 2 `test_dry_run_leaves_db_untouched`
- **Issue:** `conn.execute("PRAGMA journal_mode=WAL")` modifies the DB file header bytes unconditionally, breaking the before/after hash comparison.
- **Fix:** Skip WAL pragma for dry-run and verify-only runs (`is_no_persist` flag).
- **Files modified:** `migration_v16.py`

**3. [Rule 1 - Bug] `sqlite3.Connection.execute` is a C extension attribute — cannot monkeypatch**
- **Found during:** Task 2 `test_rebuild_fallback_when_drop_column_fails`
- **Issue:** `monkeypatch.setattr(sqlite3.Connection, "execute", ...)` raises `TypeError: cannot set 'execute' attribute of immutable type 'sqlite3.Connection'` because sqlite3.Connection is a C extension type.
- **Fix:** Added module-level `_attempt_drop_column(conn, table, col)` hook in migration_v16.py; updated the test to patch `_m16._attempt_drop_column` instead.
- **Files modified:** `migration_v16.py`, `tests/ingestion/test_migration_v16.py`

**4. [Rule 2 - Missing Infrastructure] conftest.py `tmp_index_db` fixture did not pre-create migration_v16 tables**
- **Found during:** Task 2 `test_dry_run_acquires_and_releases_lock` — `migration_v16_lock` table didn't exist after dry-run (all DDL rolled back), causing OperationalError
- **Issue:** The dry-run ROLLBACK correctly undoes all DDL (keeps DB byte-identical), but the lock test then queries `migration_v16_lock` which no longer exists.
- **Fix:** Added pre-creation of `migration_v16_state` + `migration_v16_lock` tables in `tmp_index_db` fixture. This makes the fixture include the infrastructure tables in the `before` hash, so dry-run leaves them empty (correct — lock row rolled back) and byte-equal (tables were already there).
- **Files modified:** `tests/conftest.py`

**5. [Rule 1 - Bug] `chunk_file()` required `content` parameter — broke `test_chunker_emits_file_paths_as_single_element_list`**
- **Found during:** Task 1 test run
- **Issue:** Test calls `chunk_file(md_file)` with just a path; the function signature required `content` as a positional argument.
- **Fix:** Made `content` optional (`content: str | None = None`); added auto-read from disk when `None`.
- **Files modified:** `backend/src/dotmd/ingestion/chunker.py`

**6. [Rule 2 - Missing functionality] `_ConnProxy` wrapper needed for test spy on sqlite3.Connection.execute**
- **Found during:** Task 1 `test_get_file_paths_for_chunk_ids_single_query` — test assigns `store._conn.execute = counting_execute` but sqlite3.Connection C type doesn't allow attribute assignment
- **Fix:** Added `_ConnProxy` class to `metadata.py` that wraps sqlite3.Connection and allows `execute` to be re-assigned (Python-level wrapper).
- **Files modified:** `backend/src/dotmd/storage/metadata.py`

## Known Stubs

None. All production code is implemented. The `migration_v15.py` stub is intentional (Decision #9) and tracked as GSD backlog 999.7.

## Threat Flags

No new security-relevant surface introduced beyond the plan's threat model. All threat mitigations from the plan's STRIDE register are implemented: strategy-name f-string sourced from validated set, advisory lock prevents concurrent trickle, per-strategy transaction + backup for crash recovery, cosine divergence WARN, payload_divergences JSON audit trail, _make_chunk_id imported (not re-stated).

## Self-Check: PASSED

**Files created:**
- `backend/src/dotmd/ingestion/migration_v16.py` — EXISTS

**Files modified:**
- `backend/src/dotmd/core/models.py` — EXISTS
- `backend/src/dotmd/ingestion/chunker.py` — EXISTS
- `backend/src/dotmd/storage/metadata.py` — EXISTS
- `backend/src/dotmd/ingestion/migration_v15.py` — EXISTS
- `backend/tests/conftest.py` — EXISTS
- `backend/tests/ingestion/test_migration_v16.py` — EXISTS

**Commits:**
- `fad3363` — feat(16-01): Task 1: EXISTS
- `91fa403` — feat(16-01): Task 2: EXISTS
- `4032d3f` — feat(16-01): Task 3: EXISTS

**Test results:** 37/37 Wave-1 P1 tests GREEN
