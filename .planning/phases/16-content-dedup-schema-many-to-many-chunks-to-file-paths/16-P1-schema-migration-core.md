---
phase: 16-content-dedup-schema
plan: 1
type: execute
wave: 2
depends_on: [16-P6]
files_modified:
  - backend/src/dotmd/ingestion/migration_v16.py
  - backend/src/dotmd/ingestion/migration_v15.py
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/storage/sqlite_vec.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/chunker.py
autonomous: true
requirements: [DEDUP-01, DEDUP-02, DEDUP-03, DEDUP-04, DEDUP-11]
must_haves:
  truths:
    - "After migration, every chunks_<strategy> has no file_path and no chunk_index columns."
    - "After migration, chunk_file_paths_<strategy> exists per strategy with PK (chunk_id, file_path, chunk_index) and an index on file_path."
    - "Collision groups collapse to the MIN(old chunk_id) canonical row in chunks_*, vec_meta_*, vec0_*, chunks_fts_*."
    - "Divergence warnings (cosine > 0.01) are logged but do not abort the migration."
    - "migration_v15.run_migration_v15 is a logged no-op stub; needs_migration_v15 returns False."
    - "char_offset is absent from Chunk model, chunker output, and every chunks_* table."
    - "Re-running migration on a completed DB is a no-op (per-strategy state marker respected)."
  artifacts:
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Resumable per-strategy migration (M2M creation, blake3 remap, collision collapse, divergence check, char_offset drop, DROP COLUMN with rebuild fallback, migration_v16_state + migration_v16_lock)."
    - path: backend/src/dotmd/storage/metadata.py
      provides: "M2M DDL helpers, upsert_chunk rewrite (no file_path/chunk_index/char_offset), add_file_path_for_chunk, get_file_paths_by_chunk_id, get_chunk_ids_by_file via M2M, delete_m2m_for_file, delete_orphan_chunks."
    - path: backend/src/dotmd/core/models.py
      provides: "Chunk model without char_offset; file_paths: list[Path] (or equivalent per Open Q #3)."
  key_links:
    - from: backend/src/dotmd/ingestion/migration_v16.py
      to: backend/src/dotmd/storage/metadata.py
      via: "M2M DDL templates + orphan query helpers"
      pattern: "chunk_file_paths_"
    - from: backend/src/dotmd/ingestion/migration_v16.py
      to: backend/src/dotmd/storage/sqlite_vec.py
      via: "vector fetch for divergence check + delete_by_chunk_ids for collapse"
      pattern: "_cosine|divergence"
---

<objective>
Land the core schema migration for Phase 16: introduce per-strategy M2M `chunk_file_paths_*` tables, remap to blake3 ids, collapse collision groups to the MIN canonical chunk_id (with cosine divergence WARN > 0.01), drop `file_path` / `chunk_index` / `char_offset` columns from `chunks_*`, and install `migration_v16_state` and `migration_v16_lock` sentinel tables. Also rewrite the metadata layer to speak M2M and reduce `migration_v15.py` to a no-op stub.

Purpose: This is the schema substrate that everything else in Phase 16 (ingest flow, purge, search API, ops modes, tests) depends on. No execution of the migration script in production — that's an operational step done after Phase 16 ships. This plan produces the runnable migration module and the new metadata layer.

Output: `migration_v16.py` runnable offline, metadata layer updated, core models updated, `migration_v15.py` stubbed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@backend/src/dotmd/ingestion/migration_v15.py
@backend/src/dotmd/storage/metadata.py
@backend/src/dotmd/storage/sqlite_vec.py
@backend/src/dotmd/core/models.py
@backend/src/dotmd/ingestion/chunker.py
@backend/src/dotmd/search/fts5.py
@backend/CLAUDE.md
@CLAUDE.md

<interfaces>
Key invariants from RESEARCH.md and CONTEXT.md:

```sql
-- Target schema per strategy
chunks_<strategy> (
    chunk_id TEXT PRIMARY KEY,        -- 64-char blake3
    heading_hierarchy TEXT,
    text TEXT,
    level INTEGER
    -- file_path, chunk_index, char_offset ALL REMOVED
)

chunk_file_paths_<strategy> (
    chunk_id    TEXT NOT NULL,
    file_path   TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)

CREATE INDEX idx_chunk_file_paths_<strategy>_file_path
    ON chunk_file_paths_<strategy>(file_path);

migration_v16_state (
    strategy TEXT PRIMARY KEY,
    completed_at TEXT NOT NULL,
    collisions_collapsed INTEGER NOT NULL DEFAULT 0,
    divergence_warnings INTEGER NOT NULL DEFAULT 0
)

migration_v16_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    host TEXT NOT NULL
)
```

Decision #4: canonical chunk_id = MIN(old_chunk_id); cosine > 0.01 ⇒ WARN, not abort.
Decision #6: prefer ALTER TABLE DROP COLUMN (SQLite 3.46.1 available). Rebuild fallback only on failure.
Decision #8: char_offset dropped everywhere.
Decision #9: migration_v15.py kept as stub; beads-fz6 tracks removal for v1.5+1.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite metadata layer for M2M (drop file_path/chunk_index/char_offset from chunks_*)</name>
  <files>backend/src/dotmd/storage/metadata.py, backend/src/dotmd/core/models.py, backend/src/dotmd/ingestion/chunker.py</files>
  <behavior>
    - `Chunk` model no longer exposes `char_offset`; chunker does not emit it.
    - `Chunk.file_paths: list[Path]` (single-element list when emitted by the chunker; see Research Open Q #3 — one model, wrap-in-list at creation).
    - `SQLiteMetadataStore` creates `chunks_<strategy>` with columns only for chunk_id (PK), heading_hierarchy, text, level — no file_path, chunk_index, or char_offset.
    - New: `SQLiteMetadataStore.ensure_m2m_table(strategy)` creates `chunk_file_paths_<strategy>` and its index.
    - `insert_chunk` (replacing `upsert_chunk`) uses `INSERT OR IGNORE` on chunks_* — never UPDATEs on conflict (Research Pitfall 1).
    - New: `add_file_path(strategy, chunk_id, file_path, chunk_index)` uses `INSERT OR IGNORE` on the M2M table.
    - New: `get_file_paths_by_chunk_id(strategy, chunk_id) -> list[str]` returns distinct paths sorted lexicographically.
    - Rewrite: `get_chunk_ids_by_file(strategy, file_path)` queries the M2M table, not chunks_*.
    - New: `delete_m2m_for_file(strategy, file_path) -> list[str]` returns chunk_ids whose holder count dropped to 0 (orphans) — transactional (BEGIN / COMMIT / ROLLBACK).
    - New: `delete_orphan_chunks(strategy, chunk_ids)` deletes from chunks_* only.
    - The old `delete_chunks_by_file` helper is removed (caller sites updated in P4).
    - Test 1 (test_metadata_m2m.py): insert_chunk twice with same chunk_id is no-op on chunks_* content (Pitfall 1 regression guard).
    - Test 2: add_file_path is idempotent on (chunk_id, file_path, chunk_index).
    - Test 3: get_file_paths_by_chunk_id returns sorted lex order.
    - Test 4: delete_m2m_for_file returns exactly the chunk_ids that lost their last holder.
    - Test 5: Chunk model rejects char_offset kwarg (field no longer exists).
  </behavior>
  <action>
    Implement the rewrite per D-01 (search result shape ⇒ file_paths list), D-03 (chunk_index moves to M2M), D-07 (INSERT OR IGNORE), D-08 (char_offset dropped).

    Maintain the project convention of f-stringing the table name (strategy) and `?`-parameterising the values (Research §Security Domain). Do NOT introduce ORM layer.

    Protocol-based abstractions (backend/CLAUDE.md): keep the Protocol in `storage/base.py` aligned with the new surface; only the SQLite implementation changes in this plan.

    Chunker: emit `Chunk(file_paths=[source_path], chunk_index=..., text=..., heading_hierarchy=..., level=...)`. No `char_offset`.

    Grep audit (must return zero hits in production code after this task):
      grep -rn "char_offset" backend/src/dotmd/ --include='*.py'
      grep -rn "file_path\b" backend/src/dotmd/storage/metadata.py
      grep -rn "upsert_chunk\|INSERT.*ON CONFLICT" backend/src/dotmd/storage/metadata.py
  </action>
  <verify>
    <automated>cd backend && pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_chunker.py -x --tb=short</automated>
  </verify>
  <done>
    - Chunk model has no char_offset field; chunker output verified clean.
    - metadata.py exposes the new surface (insert_chunk, add_file_path, get_file_paths_by_chunk_id, get_chunk_ids_by_file via M2M, delete_m2m_for_file, delete_orphan_chunks).
    - All five behavior tests green; grep audits empty.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement migration_v16.py (remap + collapse + drop columns + state/lock)</name>
  <files>backend/src/dotmd/ingestion/migration_v16.py, backend/src/dotmd/storage/sqlite_vec.py</files>
  <behavior>
    Core entry points (matching Research §Component Responsibilities):
    - `needs_migration_v16(index_db: Path) -> bool` — true iff any `chunks_<strategy>` still has `file_path` column OR any chunk_id is not 64-hex.
    - `run_migration_v16(index_db: Path, *, dry_run=False, verify_only=False) -> MigrationReport` — orchestrator.
    - `status(index_db: Path) -> StatusReport` — reads `migration_v16_state` + lock state.

    Per-strategy flow (inside BEGIN/COMMIT, skip if state row present):
      1. Ensure `chunk_file_paths_<strategy>` + index (metadata helper from Task 1).
      2. Backfill M2M from existing chunks_<strategy> rows: `INSERT INTO chunk_file_paths_<strategy> SELECT chunk_id, file_path, chunk_index FROM chunks_<strategy>`.
      3. Compute new blake3 id per row: `blake3(body_checksum:chunk_index:strategy)` — body_checksum is the per-file content hash already on the fingerprints table (Phase 15).
      4. UPDATE chunks_<strategy>.chunk_id = new_id (temp table if needed to avoid PK clash during remap).
      5. UPDATE chunk_file_paths_<strategy>.chunk_id = new_id.
      6. UPDATE vec_meta_<strategy>.chunk_id = new_id.
      7. UPDATE chunks_fts_<strategy> — delete-by-old-id + insert-with-new-id (FTS5 has no PK; Pitfall 5).
      8. Detect collision groups (`SELECT new_id, COUNT(*) FROM ... GROUP BY new_id HAVING COUNT(*) > 1`).
      9. For each collision group: canonical = MIN(old chunk_id). For each discarded id compute cosine(canonical, discarded) via `sqlite_vec.fetch_vector(...)` helper; WARN if distance > 0.01. DELETE non-canonical rows from chunks_*, vec_meta_*, vec0_*, chunks_fts_*. M2M rows already point to canonical after step 5.
      10. DROP COLUMN file_path, chunk_index, char_offset from chunks_<strategy>. On exception → full rebuild fallback (CREATE NEW + INSERT SELECT + DROP + RENAME).
      11. Insert `migration_v16_state(strategy, completed_at, collisions_collapsed, divergence_warnings)`.

    Pre-flight:
      - shutil.copy2(index.db → index.db.v16-backup). Skip if `--dry-run`.
      - Acquire `migration_v16_lock` sentinel (INSERT with CHECK id=1). If IntegrityError: raise with operator hint (manually DELETE stale lock).

    Post-flight:
      - Release lock (DELETE FROM migration_v16_lock WHERE id = 1).
      - Emit summary log (collisions, warnings, rows_before, rows_after per strategy).

    DROP COLUMN probe: try `ALTER TABLE <t> DROP COLUMN <c>`. On sqlite3.OperationalError, call the rebuild fallback helper.

    Dry-run semantics: run steps 1–9 in a transaction then ROLLBACK; collect counts; do not touch backup file; do not write state row; do not acquire lock (or acquire+release immediately). Log "DRY RUN — no changes persisted".

    Verify-only semantics: run invariant checks (DEDUP-10 set — see P6) without any writes.

    Test cases (tests/ingestion/test_migration_v16.py):
    - test_creates_m2m_table_and_index
    - test_drops_file_path_chunk_index_char_offset
    - test_collision_canonical_is_min_old_id
    - test_divergence_warn_emitted_above_threshold
    - test_divergence_warn_not_emitted_below_threshold
    - test_resume_after_crash_skips_completed_strategy
    - test_empty_strategy_no_op
    - test_dry_run_leaves_db_untouched
    - test_lock_acquired_and_released
    - test_rebuild_fallback_when_drop_column_fails (mock)
  </behavior>
  <action>
    Model the structure on `migration_v15.py` (Research §Code Examples §Pattern 1). Single-threaded per-strategy.

    Use stdlib math for cosine (Research §Don't Hand-Roll): `math.fsum(x*y for x,y in zip(a,b, strict=True)) / (math.sqrt(...) * math.sqrt(...))`. Threshold 0.01 (Decision #4).

    Logger: create module-level `logger = logging.getLogger("dotmd-migrate")`. All progress lines use this logger so journald `SyslogIdentifier=dotmd-migrate` catches them (structured tag per Decision #7).

    Add `sqlite_vec.fetch_vector(strategy, chunk_id) -> list[float] | None` helper (read from vec0_* via JOIN vec_meta_*). Add `sqlite_vec.delete_by_chunk_ids(strategy, chunk_ids)` helper that handles both vec_meta_* and vec0_* consistently. Research §Component Responsibilities explicitly asks for these helpers.

    Per D-04, log WARN but continue (never abort on divergence).

    Per D-06 rebuild fallback: mirror the CREATE+INSERT SELECT+DROP+RENAME pattern from established SQLite migration cookbook (https://www.sqlite.org/lang_altertable.html#otheralter).

    Parameterise every value; f-string only the table name (sourced from validated strategy set — re-use whatever strategy registry is already in use by metadata.py).
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16.py -x --tb=short</automated>
  </verify>
  <done>
    - migration_v16.py importable, `needs_migration_v16`, `run_migration_v16`, `status` exposed.
    - All ten test cases green.
    - Backup file created for real runs, not for dry runs.
    - Lock sentinel lifecycle proven by tests.
    - Rebuild fallback reachable by injected failure.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 3: Stub migration_v15.py + sanity grep gates</name>
  <files>backend/src/dotmd/ingestion/migration_v15.py</files>
  <behavior>
    - `needs_migration_v15(index_db_path) -> bool` always returns False with INFO log "superseded by migration_v16 — run `dotmd migrate`".
    - `run_migration_v15(*a, **kw) -> None` logs the same message and returns.
    - Module docstring states: "Superseded by migration_v16 (Phase 16). Removal tracked by beads-fz6 for v1.5+1. Do NOT delete this file in Phase 16 (Decision #9)."
    - Test: calling either function does not touch the filesystem and does not raise.
  </behavior>
  <action>
    Replace body with stub. Preserve the old module-level import surface (function names) so any straggling caller degrades gracefully.

    Grep gate (end of task, no header comments counted — strip with `grep -v '^#'`):
      grep -v '^#' backend/src/dotmd/ingestion/migration_v15.py | grep -c "blake3\|UPDATE chunks_\|CREATE TABLE"
    Expected: 0 (all real migration logic removed).
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v15_superseded.py -x --tb=short && grep -v '^#' backend/src/dotmd/ingestion/migration_v15.py | grep -cE "blake3|UPDATE chunks_|CREATE TABLE" | grep -qx 0</automated>
  </verify>
  <done>
    - v15 module reduced to stub.
    - Test proves both entry points are safe no-ops.
    - Grep gate shows zero real migration logic remaining.
    - Deprecation banner present in module docstring referencing beads-fz6.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| operator → migration CLI | Operator runs `dotmd migrate` offline; no untrusted input crosses |
| strategy name → SQL table name | `chunk_strategy` is operator-configured in Settings, never user-supplied |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-01 | Tampering | table-name f-string in migration SQL | mitigate | strategy sourced from validated enum in Settings (same convention as metadata.py); values parameterised |
| T-16-02 | Denial of service | concurrent trickle + migration | mitigate | `migration_v16_lock` sentinel row acquired before any DDL; P3 wires trickle startup check |
| T-16-03 | Data loss | partial migration after crash | mitigate | pre-run `shutil.copy2` backup; per-strategy transaction + `migration_v16_state` resume marker |
| T-16-04 | Data integrity | silent collapse of genuinely different vectors | mitigate | cosine divergence WARN at 0.01 before discard (Decision #4) |
| T-16-05 | Repudiation | no audit trail of which rows were collapsed | accept | `migration_v16_state.collisions_collapsed` + `divergence_warnings` counters are sufficient for a single-operator localhost system |
</threat_model>

<verification>
- `pytest tests/ingestion/test_migration_v16.py tests/ingestion/test_migration_v15_superseded.py tests/storage/test_metadata_m2m.py tests/ingestion/test_chunker.py -x` green.
- Grep gates:
  - `grep -rn "char_offset" backend/src/dotmd/` → 0 lines.
  - `grep -rn "upsert_chunk\|ON CONFLICT.*DO UPDATE" backend/src/dotmd/storage/metadata.py` → 0 lines.
- Lock sentinel acquired-then-released proven by test.
</verification>

<success_criteria>
- needs_migration_v16 returns True against a Phase-15-era index fixture, False after run.
- Collision fixture (two files identical content) collapses to one canonical row with MIN(old_chunk_id); discarded rows cosine-checked.
- chunks_* has no file_path / chunk_index / char_offset columns after run.
- migration_v15.py is a stub; all downstream call sites still import safely.
- All Task 1–3 tests pass.
</success_criteria>

<output>
After completion, create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md` covering: schema delta summary, collision-handling pseudocode confirmed shipped, divergence log format, how P3/P4/P5 should consume the new metadata helpers.
</output>
