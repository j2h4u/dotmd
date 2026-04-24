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
    - "After migration, every chunks_<strategy> has no file_path, no chunk_index, and no char_offset columns."
    - "After migration, chunk_file_paths_<strategy> exists per strategy with PK (chunk_id, file_path, chunk_index) and an index on file_path."
    - "Migration performs shadow-column remap: new_chunk_id computed first, collisions collapsed BEFORE any PK UPDATE — no IntegrityError possible on the UPDATE step."
    - "Collision group canonical = MIN(old_chunk_id) identifies the row whose payload (text/heading_hierarchy/level) is kept; the FINAL chunk_id of every surviving row is the 64-hex blake3 value, never an old id."
    - "Before collapse, invariant assertion proves text, heading_hierarchy, and level are byte-equal across every member of a collision group; mismatches log WARN with both old chunk_ids and continue with canonical."
    - "Divergence warnings (cosine > 0.01 between canonical and discarded vectors) are logged but do not abort the migration (Decision #4)."
    - "migration_v15.run_migration_v15 is a logged no-op stub; needs_migration_v15 returns False."
    - "char_offset is absent from Chunk model, chunker output, and every chunks_* table."
    - "Re-running migration on a completed DB is a no-op (per-strategy state marker respected)."
    - "--dry-run acquires the advisory lock like a real run (prevents concurrent writes corrupting dry-run counts) and releases on rollback."
    - "New-id derivation reuses chunker._make_chunk_id — plan prose does not restate the hash recipe."
  artifacts:
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Resumable per-strategy migration (M2M creation, shadow-column blake3 remap, invariant + collision-group payload-equality assertion, collision collapse with canonical keep + cosine divergence WARN, char_offset drop, DROP COLUMN with rebuild fallback, migration_v16_state + migration_v16_lock, dry-run with lock)."
    - path: backend/src/dotmd/storage/metadata.py
      provides: "M2M DDL helpers, insert_chunk (INSERT OR IGNORE, no file_path/chunk_index/char_offset), add_file_path, get_file_paths_by_chunk_id (sorted lex), get_file_paths_for_chunk_ids (batch hydration), get_chunk_ids_by_file via M2M, delete_m2m_for_file, delete_orphan_chunks."
    - path: backend/src/dotmd/core/models.py
      provides: "Chunk model without char_offset; file_paths: list[Path] with single-element list at creation."
  key_links:
    - from: backend/src/dotmd/ingestion/migration_v16.py
      to: backend/src/dotmd/ingestion/chunker.py
      via: "reuses _make_chunk_id(body_checksum, chunk_index, strategy) for new-id derivation"
      pattern: "_make_chunk_id"
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
Land the core schema migration for Phase 16: introduce per-strategy M2M `chunk_file_paths_*` tables, remap to blake3 ids using a SHADOW-COLUMN flow that collapses collisions BEFORE any PK UPDATE, drop `file_path` / `chunk_index` / `char_offset` columns from `chunks_*`, and install `migration_v16_state` and `migration_v16_lock` sentinel tables. Also rewrite the metadata layer to speak M2M and reduce `migration_v15.py` to a no-op stub.

Purpose: This is the schema substrate that everything else in Phase 16 (ingest flow, purge, search API, ops modes, tests) depends on. No execution of the migration script in production — that's an operational step done after Phase 16 ships. This plan produces the runnable migration module and the new metadata layer, with the migration flow ordering CORRECTED per both cross-AI reviewers (codex + opencode): collision detection/collapse happens BEFORE the chunks_* PK UPDATE, not after.

Output: `migration_v16.py` runnable offline with correct flow ordering, metadata layer updated, core models updated, `migration_v15.py` stubbed.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-REVIEWS.md
@backend/src/dotmd/ingestion/migration_v15.py
@backend/src/dotmd/ingestion/chunker.py
@backend/src/dotmd/storage/metadata.py
@backend/src/dotmd/storage/sqlite_vec.py
@backend/src/dotmd/core/models.py
@backend/src/dotmd/search/fts5.py
@backend/CLAUDE.md
@CLAUDE.md

<interfaces>
Key invariants and contracts from RESEARCH.md, CONTEXT.md, and REVIEWS.md:

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
    divergence_warnings INTEGER NOT NULL DEFAULT 0,
    payload_mismatch_warnings INTEGER NOT NULL DEFAULT 0
)

migration_v16_lock (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    locked_at TEXT NOT NULL,
    pid INTEGER NOT NULL,
    host TEXT NOT NULL,
    mode TEXT NOT NULL  -- 'run' | 'dry-run' | 'verify-only'
)
```

New-id derivation: IMPORTANT — reuse Phase 15's chunker helper, do NOT restate the recipe.

```python
# From backend/src/dotmd/ingestion/chunker.py (line 23):
# def _make_chunk_id(body_checksum: str, chunk_index: int, chunk_strategy: str) -> str:
#     payload = f"{body_checksum}:{chunk_index}:{chunk_strategy}"
#     return _blake3.blake3(payload.encode()).hexdigest()  # 64-char
#
# body_checksum is the per-CHUNK body hash: blake3(kind + "\n" + body)
# where body = chunks_*.text and kind = "text" (chunker.py line 178).

from dotmd.ingestion.chunker import _make_chunk_id
import blake3 as _blake3

def _compute_body_checksum(text: str, kind: str = "text") -> str:
    return _blake3.blake3(f"{kind}\n{text}".encode()).hexdigest()

def _compute_new_id_for_row(text: str, chunk_index: int, strategy: str) -> str:
    body_checksum = _compute_body_checksum(text)
    return _make_chunk_id(body_checksum, chunk_index, strategy)
```

Decisions referenced:
- D-01: file_paths returned as list sorted lex.
- D-03: chunk_index in M2M PK, NOT in chunks_*.
- D-04: canonical = MIN(old_chunk_id) — meaning the ROW whose payload is kept; final id is blake3. Cosine > 0.01 ⇒ WARN (don't abort).
- D-06: per-strategy tx + advisory lock + prefer ALTER TABLE DROP COLUMN.
- D-07: INSERT OR IGNORE semantics.
- D-08: char_offset dropped everywhere.
- D-09: migration_v15.py kept as stub; beads-fz6 tracks removal for v1.5+1.

Review concerns landed here (HIGH from REVIEWS.md):
- [Review-HIGH-1] Migration flow ordering fixed — shadow column + collapse-before-update. See Task 2 step list.
- [Review-HIGH-2] Collision-group payload invariant assertion added. See Task 2 step 5.
- [Review-HIGH-3] Body_checksum / new-id derivation reuses chunker._make_chunk_id import. See <interfaces> above.
- [Review-HIGH-4] MIN(old chunk_id) labelled as "payload source row" — final id is always blake3.
- [Review-MED-6] Dry-run acquires advisory lock (mode='dry-run') like a real run.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite metadata layer for M2M (drop file_path/chunk_index/char_offset from chunks_*)</name>
  <files>backend/src/dotmd/storage/metadata.py, backend/src/dotmd/core/models.py, backend/src/dotmd/ingestion/chunker.py</files>
  <behavior>
    - `Chunk` model no longer exposes `char_offset`; chunker does not emit it (D-08).
    - `Chunk.file_paths: list[Path]` (single-element list when emitted by the chunker — see Research Open Q #3: one model, wrap-in-list at creation).
    - `SQLiteMetadataStore` creates `chunks_<strategy>` with columns only for chunk_id (PK), heading_hierarchy, text, level — no file_path, chunk_index, or char_offset.
    - New: `SQLiteMetadataStore.ensure_m2m_table(strategy)` creates `chunk_file_paths_<strategy>` plus `idx_chunk_file_paths_<strategy>_file_path`.
    - `insert_chunk` (replacing `upsert_chunk`) uses `INSERT OR IGNORE` on chunks_* — never UPDATEs on conflict (Research Pitfall 1 / D-07).
    - New: `add_file_path(strategy, chunk_id, file_path, chunk_index)` uses `INSERT OR IGNORE` on the M2M table.
    - New: `get_file_paths_by_chunk_id(strategy, chunk_id) -> list[str]` returns distinct paths sorted lexicographically (D-01). Implementation uses `ORDER BY file_path`.
    - New: `get_file_paths_for_chunk_ids(strategy, chunk_ids: Sequence[str]) -> dict[str, list[str]]` — batch hydration helper. Implements single `SELECT chunk_id, file_path FROM chunk_file_paths_<strategy> WHERE chunk_id IN (?, ?, …) ORDER BY chunk_id, file_path` to avoid O(K) round-trips (addresses [Review-LOW-12] batch hydration). P5 consumes this.
    - Rewrite: `get_chunk_ids_by_file(strategy, file_path)` queries the M2M table, not chunks_*.
    - New: `delete_m2m_for_file(strategy, file_path) -> list[str]` returns chunk_ids whose holder count dropped to 0 (orphans). This helper MUST use the caller-supplied connection (no internal tx/commit) so the pipeline (P4) can wrap the full per-file cascade in one transaction. Document explicitly in the docstring: "Callers must wrap this in BEGIN/COMMIT."
    - New: `delete_orphan_chunks(strategy, chunk_ids, *, conn=None)` deletes from chunks_* only; uses supplied conn.
    - The old `delete_chunks_by_file` helper is removed (caller sites updated in P3/P4).
    - Test 1 (test_metadata_m2m.py): insert_chunk twice with same chunk_id is no-op on chunks_* content (Pitfall 1 regression guard — also addresses [Review-HIGH-P3] "same chunk_id must imply identical payload" surfaced through ingest assertion in P3).
    - Test 2: add_file_path is idempotent on (chunk_id, file_path, chunk_index).
    - Test 3: get_file_paths_by_chunk_id returns sorted lex order.
    - Test 4: delete_m2m_for_file returns exactly the chunk_ids that lost their last holder.
    - Test 5: Chunk model rejects char_offset kwarg (field no longer exists).
    - Test 6 (new): get_file_paths_for_chunk_ids returns correct dict[str, list[str]] with sorted lex lists, using a single SELECT (assert via recorded cursor call count ≤ 1).
  </behavior>
  <action>
    Implement the rewrite per D-01 (search result shape ⇒ file_paths list), D-03 (chunk_index moves to M2M), D-07 (INSERT OR IGNORE), D-08 (char_offset dropped).

    Maintain the project convention of f-stringing the table name (strategy) and `?`-parameterising the values (Research §Security Domain). Do NOT introduce ORM layer.

    Protocol-based abstractions (backend/CLAUDE.md): keep the Protocol in `storage/base.py` aligned with the new surface; only the SQLite implementation changes in this plan.

    Chunker: emit `Chunk(file_paths=[source_path], chunk_index=..., text=..., heading_hierarchy=..., level=...)`. No `char_offset`.

    Transaction ownership: `delete_m2m_for_file` and `delete_orphan_chunks` both accept an open `sqlite3.Connection` and do NOT call `commit()`. This is a deliberate contract change versus earlier drafts (addresses [Review-MED-P4-8] atomicity). The pipeline (P4) owns the transaction boundary.

    Grep audit (must return zero hits in production code after this task, strip header comments):
      grep -rn --include='*.py' "char_offset" backend/src/dotmd/ | grep -v '^\s*#'
      grep -rn "file_path\b" backend/src/dotmd/storage/metadata.py | grep -v file_paths | grep -v '^\s*#'
      grep -rn "upsert_chunk\|INSERT.*ON CONFLICT" backend/src/dotmd/storage/metadata.py | grep -v '^\s*#'
  </action>
  <verify>
    <automated>cd backend && pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_chunker.py -x --tb=short</automated>
  </verify>
  <done>
    - Chunk model has no char_offset field; chunker output verified clean.
    - metadata.py exposes the new surface (insert_chunk, add_file_path, get_file_paths_by_chunk_id, get_file_paths_for_chunk_ids, get_chunk_ids_by_file via M2M, delete_m2m_for_file, delete_orphan_chunks).
    - `delete_m2m_for_file` / `delete_orphan_chunks` docstrings document the "caller owns transaction" contract.
    - All six behavior tests green; grep audits empty.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Implement migration_v16.py with CORRECTED shadow-column flow (collapse before PK update)</name>
  <files>backend/src/dotmd/ingestion/migration_v16.py, backend/src/dotmd/storage/sqlite_vec.py</files>
  <behavior>
    Core entry points (matching Research §Component Responsibilities):
    - `needs_migration_v16(index_db: Path) -> bool` — true iff any `chunks_<strategy>` still has `file_path` column OR any chunk_id is not 64-hex OR `migration_v16_state` row missing for any present strategy.
    - `run_migration_v16(index_db: Path, *, dry_run=False, verify_only=False) -> MigrationReport` — orchestrator.
    - `status(index_db: Path) -> StatusReport` — reads `migration_v16_state` + lock state.

    Pre-flight (all modes):
      - Acquire `migration_v16_lock` sentinel (INSERT with CHECK id=1, mode field set to 'run'|'dry-run'|'verify-only'). Dry-run uses 'dry-run' mode; if lock already held, raise with operator hint (manually DELETE stale lock). [Addresses Review-MED-6]
      - shutil.copy2(index.db → index.db.v16-backup). SKIP for --dry-run and --verify-only (no persistent mutation).

    Per-strategy flow — CORRECTED ORDER (addresses Review-HIGH-1 from BOTH reviewers):

    ```
    BEGIN TRANSACTION
    # --- Step 1: M2M table + backfill ---
    1. Ensure chunk_file_paths_<strategy> exists + idx_file_path index (metadata helper from Task 1).
    2. Backfill M2M from current chunks_<strategy>:
         INSERT INTO chunk_file_paths_<strategy> (chunk_id, file_path, chunk_index)
         SELECT chunk_id, file_path, chunk_index FROM chunks_<strategy>;
       (These rows still carry OLD chunk_ids at this point — we rewrite them in step 8.)

    # --- Step 2: Shadow column + new-id computation ---
    3. ALTER TABLE chunks_<strategy> ADD COLUMN new_chunk_id TEXT.
    4. For every row in chunks_<strategy>:
         new_id = _make_chunk_id(
             body_checksum=_compute_body_checksum(row.text),
             chunk_index=row.chunk_index,
             chunk_strategy=strategy
         )
         UPDATE chunks_<strategy> SET new_chunk_id = :new_id WHERE chunk_id = :old_id;
       This is the only place the recipe is invoked. Imported from chunker. No PK conflict because new_chunk_id is a plain column, not PK.

    # --- Step 3: Detect collision groups ---
    5. Collision detection:
         SELECT new_chunk_id, GROUP_CONCAT(chunk_id) AS old_ids, COUNT(*) AS n
         FROM chunks_<strategy>
         GROUP BY new_chunk_id HAVING n > 1;
       For each collision group:
         a. payload_invariant_check — fetch text, heading_hierarchy, level for every member:
              SELECT chunk_id, text, heading_hierarchy, level FROM chunks_<strategy>
              WHERE chunk_id IN (<old_ids>);
            If not all text/heading_hierarchy/level equal across the group → log WARN
              "payload_mismatch new_id=<…> old_ids=<a,b,c> fields_diverged=<text|heading|level>"
            Counter `payload_mismatch_warnings += 1`. DO NOT abort — continue with canonical per D-04 behaviour.
            [Addresses Review-HIGH-2]

         b. canonical_old_id = MIN(group.old_ids)   # "payload-source row", NOT final id
            [Addresses Review-HIGH-4 — canonical semantics explicit]

         c. Vector divergence assertion (Decision #4): for each discarded_old_id in group except canonical:
              v_canon  = sqlite_vec.fetch_vector(strategy, canonical_old_id)
              v_other  = sqlite_vec.fetch_vector(strategy, discarded_old_id)
              distance = 1 - cosine_similarity(v_canon, v_other)
              if distance > 0.01: log WARN and divergence_warnings += 1

         d. Collapse (DELETE non-canonical old rows from chunks_*/vec_meta_*/vec0_*/chunks_fts_*):
              DELETE FROM chunks_<strategy>       WHERE chunk_id IN (<non_canonical_old_ids>);
              DELETE FROM vec_meta_<strategy>     WHERE chunk_id IN (<non_canonical_old_ids>);
              DELETE FROM vec0_<strategy>         WHERE rowid IN (<non_canonical_rowids>);
              DELETE FROM chunks_fts_<strategy>   WHERE chunk_id IN (<non_canonical_old_ids>);
            (The M2M row backfill from step 2 already carries every (chunk_id, file_path, chunk_index) pair — it doesn't need deletion here. It does need remapping in step 7.)

    # --- Step 4: Remap (safe now — every surviving new_chunk_id is unique) ---
    6. (Sanity) SELECT COUNT(*) FROM (
             SELECT new_chunk_id FROM chunks_<strategy> GROUP BY new_chunk_id HAVING COUNT(*) > 1
         );
         # Must be 0. If not, raise RuntimeError — collision collapse is incomplete.

    7. Remap M2M references to new ids (do this BEFORE chunks_* PK update so both tables stay consistent):
         UPDATE chunk_file_paths_<strategy>
         SET chunk_id = (
             SELECT new_chunk_id FROM chunks_<strategy> c
             WHERE c.chunk_id = chunk_file_paths_<strategy>.chunk_id
         )
         WHERE chunk_id IN (SELECT chunk_id FROM chunks_<strategy>);
       Remap vec_meta_<strategy> + chunks_fts_<strategy> similarly (same pattern; FTS5 has no PK, so it's a plain UPDATE).
       For vec0_<strategy> there is no chunk_id column — it is keyed on rowid which we preserve.

    8. Now safe — no duplicates exist — PK UPDATE succeeds:
         UPDATE chunks_<strategy> SET chunk_id = new_chunk_id;

    # --- Step 5: Drop shadow column + legacy columns ---
    9. Try DROP COLUMN (SQLite ≥3.35):
         ALTER TABLE chunks_<strategy> DROP COLUMN new_chunk_id;
         ALTER TABLE chunks_<strategy> DROP COLUMN file_path;
         ALTER TABLE chunks_<strategy> DROP COLUMN chunk_index;
         ALTER TABLE chunks_<strategy> DROP COLUMN char_offset;
       On sqlite3.OperationalError → rebuild fallback (CREATE chunks_<strategy>_new with target schema, INSERT SELECT, DROP old, RENAME).

    # --- Step 6: State marker ---
    10. INSERT INTO migration_v16_state (strategy, completed_at, collisions_collapsed, divergence_warnings, payload_mismatch_warnings) VALUES (?, ?, ?, ?, ?);

    COMMIT  (or ROLLBACK if dry_run or verify_only)
    ```

    Dry-run semantics (revised — addresses Review-MED-6):
      - Acquires lock with mode='dry-run' (same contention check as real run).
      - Runs steps 1–10 inside a transaction then ROLLBACK.
      - Backup file NOT created.
      - Emits structured `mode=dry-run` summary: collisions, divergence warnings, payload_mismatch warnings, rows_before, rows_after_estimate, disk_delta_estimate = rows_collapsed * avg_row_size.
      - Releases lock regardless of outcome (try/finally).

    Verify-only semantics:
      - Acquires lock with mode='verify-only'.
      - Runs invariant checks via shared helper `run_invariants(conn) -> InvariantReport` (single source of truth — both --verify-only and P6 tests import this helper; no duplicated invariant logic). Checks: all chunk_ids 64-char hex; no orphan rows in vec_meta_*/FTS; UNIQUE(file_path, chunk_index) per strategy; chunk_file_paths_* exists when chunks_* has no file_path column.
      - Returns non-zero result when invariant fails (CLI translates to exit 1).
      - NEVER writes. Releases lock.

    Post-flight:
      - Release lock (DELETE FROM migration_v16_lock WHERE id = 1).
      - Emit summary log (per-strategy: rows_before, rows_after, collisions, divergence_warnings, payload_mismatch_warnings).

    Test cases (tests/ingestion/test_migration_v16.py — RED skeletons provided by P6):
    - test_creates_m2m_table_and_index
    - test_drops_file_path_chunk_index_char_offset
    - test_shadow_column_flow_no_pk_violation (NEW — regression guard for Review-HIGH-1: fixture with 2+ rows that collide must not raise IntegrityError on step 8).
    - test_collision_canonical_is_min_old_id_for_payload_but_final_id_is_blake3 (NEW — regression guard for Review-HIGH-4).
    - test_collision_group_payload_invariant_mismatch_logs_warn (NEW — regression guard for Review-HIGH-2: rows with equal text+strategy+index but different heading_hierarchy → WARN logged).
    - test_uses_chunker_make_chunk_id_helper (NEW — regression guard for Review-HIGH-3: monkeypatch `_make_chunk_id` and assert the migration called it. Prevents recipe drift.)
    - test_divergence_warn_emitted_above_threshold
    - test_divergence_warn_not_emitted_below_threshold
    - test_resume_after_crash_skips_completed_strategy
    - test_empty_strategy_no_op
    - test_dry_run_leaves_db_untouched
    - test_dry_run_acquires_and_releases_lock (NEW — regression guard for Review-MED-6).
    - test_lock_acquired_and_released
    - test_rebuild_fallback_when_drop_column_fails (mock)
    - test_run_invariants_helper_exists_and_callable (NEW — P2 verify-only + P6 import from same helper).
  </behavior>
  <action>
    Model the structure on `migration_v15.py` (Research §Code Examples §Pattern 1). Single-threaded per-strategy.

    IMPORT the new-id helper — do not restate the recipe:
      from dotmd.ingestion.chunker import _make_chunk_id
    [Addresses Review-HIGH-3]

    Use stdlib math for cosine (Research §Don't Hand-Roll): `math.fsum(x*y for x,y in zip(a,b, strict=True)) / (math.sqrt(...) * math.sqrt(...))`. Threshold 0.01 (Decision #4).

    Logger: create module-level `logger = logging.getLogger("dotmd-migrate")`. All progress lines use this logger so journald `SyslogIdentifier=dotmd-migrate` catches them (structured tag per Decision #7).

    Expose `run_invariants(conn) -> InvariantReport` as a public helper — SINGLE source of truth for invariant logic (addresses Review-MED from codex "avoid two sources of truth with P6"). P2 calls this; P6 tests call this; no duplication.

    Add `sqlite_vec.fetch_vector(strategy, chunk_id) -> list[float] | None` helper (read from vec0_* via JOIN vec_meta_*). Add `sqlite_vec.delete_by_chunk_ids(strategy, chunk_ids, *, conn)` helper that handles both vec_meta_* and vec0_* consistently and uses the caller's connection. Research §Component Responsibilities explicitly asks for these helpers.

    Per D-04, log WARN but continue (never abort on divergence).

    Per D-06 rebuild fallback: CREATE+INSERT SELECT+DROP+RENAME pattern (https://www.sqlite.org/lang_altertable.html#otheralter).

    Parameterise every value; f-string only the table name (sourced from validated strategy set — re-use whatever strategy registry is already in use by metadata.py).

    Explicit NON-goal: do not optimise for "one round trip" — correctness first. Bulk remap UPDATEs are acceptable; row-by-row `_make_chunk_id` is required because the helper is pure Python (not SQL-expressible).
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v16.py -x --tb=short</automated>
  </verify>
  <done>
    - migration_v16.py importable, `needs_migration_v16`, `run_migration_v16`, `status`, `run_invariants` exposed.
    - Shadow-column flow implemented — no UPDATE chunks_*.chunk_id before collision collapse.
    - All fifteen test cases green including the six NEW regression guards for Review-HIGH-1..4 and Review-MED-6.
    - Backup file created for real runs, not for dry runs or verify-only.
    - Lock sentinel lifecycle proven by tests for all three modes.
    - Rebuild fallback reachable by injected failure.
    - `_make_chunk_id` import verified by monkeypatch test.
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
    - Test: module docstring contains the word "Superseded" (brittle log-string assertions avoided — assert on module attribute `__doc__` per Review-LOW-10).
  </behavior>
  <action>
    Replace body with stub. Preserve the old module-level import surface (function names) so any straggling caller degrades gracefully.

    Grep gate (end of task, strip header comments and blank lines):
      grep -v '^\s*#' backend/src/dotmd/ingestion/migration_v15.py | grep -v '^\s*$' | grep -cE "blake3|UPDATE chunks_|CREATE TABLE"
    Expected: 0 (all real migration logic removed). Using `grep -cE` with filter-first to avoid self-invalidating-grep-gate issue.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_migration_v15_superseded.py -x --tb=short && [ "$(grep -v '^\s*#' backend/src/dotmd/ingestion/migration_v15.py | grep -v '^\s*$' | grep -cE 'blake3|UPDATE chunks_|CREATE TABLE')" = "0" ]</automated>
  </verify>
  <done>
    - v15 module reduced to stub.
    - Test proves both entry points are safe no-ops (asserts on function return values, not log strings).
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
| T-16-02 | Denial of service | concurrent trickle + migration | mitigate | `migration_v16_lock` sentinel row acquired (incl. dry-run) before any work; P3 wires trickle startup check |
| T-16-03 | Data loss | partial migration after crash | mitigate | pre-run `shutil.copy2` backup; per-strategy transaction + `migration_v16_state` resume marker |
| T-16-04 | Data integrity | silent collapse of genuinely different vectors | mitigate | cosine divergence WARN at 0.01 before discard (Decision #4) |
| T-16-05 | Repudiation | no audit trail of which rows were collapsed | accept | `migration_v16_state.collisions_collapsed` + `divergence_warnings` + `payload_mismatch_warnings` counters sufficient for single-operator localhost |
| T-16-19 | Data integrity | hash recipe drift between chunker and migration | mitigate | migration IMPORTS `_make_chunk_id` from chunker (Review-HIGH-3) |
| T-16-20 | Data integrity | genuinely-different content silently merged due to hash collision | mitigate | payload invariant check on text/heading_hierarchy/level across collision group (Review-HIGH-2) |
</threat_model>

<verification>
- `pytest tests/ingestion/test_migration_v16.py tests/ingestion/test_migration_v15_superseded.py tests/storage/test_metadata_m2m.py tests/ingestion/test_chunker.py -x` green.
- Grep gates:
  - `grep -rn --include='*.py' "char_offset" backend/src/dotmd/ | grep -v '^\s*#'` → 0 lines.
  - `grep -rn "upsert_chunk\|ON CONFLICT.*DO UPDATE" backend/src/dotmd/storage/metadata.py | grep -v '^\s*#'` → 0 lines.
- Lock sentinel acquired-then-released proven by test for all three modes.
- Shadow-column flow regression test proves no IntegrityError on collision groups.
</verification>

<success_criteria>
- needs_migration_v16 returns True against a Phase-15-era index fixture, False after run.
- Collision fixture (two files identical content) collapses to one canonical row whose FINAL chunk_id is 64-hex blake3. Canonical-old-id-as-payload-source is the selection rule; final id is always blake3.
- chunks_* has no file_path / chunk_index / char_offset columns after run.
- Payload invariant violations log WARN, increment counter, continue.
- migration_v15.py is a stub; all downstream call sites still import safely.
- All Task 1–3 tests pass including the Review-concern regression guards.
</success_criteria>

<output>
After completion, create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md` covering:
- Shadow-column flow diagram (the CORRECTED version — collapse before PK update).
- Exact sequence of SQL statements executed per strategy.
- Canonical-vs-final-id terminology clarification.
- Payload invariant check outcome format in logs.
- Divergence log format.
- How P3/P4/P5 should consume the new metadata helpers (insert_chunk, add_file_path, get_file_paths_by_chunk_id, get_file_paths_for_chunk_ids, delete_m2m_for_file, delete_orphan_chunks, run_invariants).
- Confirmation that `_make_chunk_id` is imported from chunker (no recipe restatement).
</output>
</content>
</invoke>