---
phase: 16-content-dedup-schema
plan: 03
type: execute
wave: 3
depends_on: [16-01]
files_modified:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/trickle.py
  - backend/src/dotmd/storage/lock_constants.py
  - backend/src/dotmd/ingestion/migration_v16.py
  - backend/src/dotmd/storage/metadata.py
autonomous: true
requirements: [DEDUP-05, DEDUP-07]
must_haves:
  truths:
    - "`IndexingPipeline._index_file` uses INSERT OR IGNORE on chunks_* and INSERT OR IGNORE on chunk_file_paths_*; never UPDATEs on conflict."
    - "Trickle refuses to start while `migration_v16_lock` sentinel row is present; exits with non-zero code and a clear log line."
    - "Re-indexing the same file twice is a no-op on chunks_* content; M2M associations remain correct."
    - "Indexing a file whose chunks already exist from another file adds M2M associations without touching the existing chunks_* rows."
    - "Lock table name constant lives in `storage/lock_constants.py` — trickle does NOT import from migration_v16 (addresses Review-LOW from opencode about avoiding migration-module dependency in runtime ingestion)."
    - "On chunk_id conflict during ingest, the new payload (text, heading_hierarchy, level) is compared to the existing stored row; mismatch is WARN-logged (addresses Review-HIGH from codex about 'INSERT OR IGNORE silently preserving arbitrary metadata')."
    - "`migration_v16.py` and `metadata.py` are listed in files_modified because this plan edits both: migration_v16.py switches to `from dotmd.storage.lock_constants import LOCK_TABLE` (cross-wave, depends-on satisfied by P1), and metadata.py gains `get_stored_payload` if P1 did not ship it — per cycle-2 NEW-MED-3 hygiene."
  artifacts:
    - path: backend/src/dotmd/ingestion/pipeline.py
      provides: "Rewritten _index_file that writes via the new metadata M2M surface with payload-consistency assertion on conflict."
    - path: backend/src/dotmd/ingestion/trickle.py
      provides: "Startup advisory-lock check that blocks while migration_v16_lock is held."
    - path: backend/src/dotmd/storage/lock_constants.py
      provides: "Shared `LOCK_TABLE = 'migration_v16_lock'` constant — imported by both migration_v16 and trickle to avoid cross-module runtime dependency."
    - path: backend/src/dotmd/ingestion/migration_v16.py
      provides: "Updated import: replaces any module-local LOCK_TABLE constant with `from dotmd.storage.lock_constants import LOCK_TABLE`."
    - path: backend/src/dotmd/storage/metadata.py
      provides: "`get_stored_payload(strategy, chunk_id) -> dict | None` helper for P3's conflict-check path — only modified here if P1 Task 1 did not already ship it (P1 commits to shipping it; this entry is defensive declaration for the executor's change-tracker)."
  key_links:
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/metadata.py
      via: "insert_chunk (OR IGNORE) + add_file_path (OR IGNORE) + get_stored_payload (for conflict-check)"
      pattern: "insert_chunk|add_file_path|get_stored_payload"
    - from: backend/src/dotmd/ingestion/trickle.py
      to: backend/src/dotmd/storage/lock_constants.py
      via: "LOCK_TABLE constant for startup sentinel check"
      pattern: "LOCK_TABLE|migration_v16_lock"
    - from: backend/src/dotmd/ingestion/migration_v16.py
      to: backend/src/dotmd/storage/lock_constants.py
      via: "LOCK_TABLE constant (moved out of migration_v16.py to break cross-module runtime dependency)"
      pattern: "from dotmd.storage.lock_constants import LOCK_TABLE"
---

<objective>
Rewrite the ingest write path to match the content-addressed schema: INSERT OR IGNORE on `chunks_*` and `chunk_file_paths_*` (replacing the legacy UPSERT that overwrites data — Research Pitfall 1). Add a startup check to `TrickleIndexer` that refuses to run while `migration_v16_lock` is held (Decision #6 advisory lock). Extract the lock-table name to a shared constants module so trickle does not import from migration_v16 at runtime.

Purpose: The current UPSERT-DO-UPDATE path silently corrupts data under content-addressed ids; trickle must also refuse to race with a running migration. INSERT OR IGNORE could also silently preserve stale metadata when a buggy chunker produces inconsistent text for the same chunk_id — this plan adds a payload-consistency assertion to surface that case.

Output: Updated `_index_file` + trickle startup guard + shared `lock_constants.py` + one-line import update in `migration_v16.py`.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-REVIEWS.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@backend/src/dotmd/ingestion/pipeline.py
@backend/src/dotmd/ingestion/trickle.py
@backend/src/dotmd/storage/metadata.py

<interfaces>
From P1:
- `metadata.insert_chunk(strategy, chunk_id, heading_hierarchy, level, text) -> None` (INSERT OR IGNORE)
- `metadata.add_file_path(strategy, chunk_id, file_path, chunk_index) -> None` (INSERT OR IGNORE)
- `metadata.get_stored_payload(strategy, chunk_id) -> dict | None` — P1 ships this per the cycle-3 P1 update. If for any reason it is absent when this plan lands, add it in this plan's Task 1 (single SELECT by chunk_id, two-line implementation).

Lock constant (new, shared module):
- `dotmd.storage.lock_constants.LOCK_TABLE = "migration_v16_lock"`

Chunker emits: `Chunk(chunk_id, text, heading_hierarchy, level, file_paths=[src], chunk_index)` — no char_offset.

Wave sequencing: This plan is Wave 3, depends on P1 only. P4 follows in Wave 4 and will modify pipeline.py and trickle.py AFTER this plan lands.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Extract lock-table constant + rewrite IndexingPipeline._index_file for M2M write path with payload-consistency check</name>
  <files>backend/src/dotmd/storage/lock_constants.py, backend/src/dotmd/ingestion/pipeline.py, backend/src/dotmd/ingestion/migration_v16.py, backend/src/dotmd/storage/metadata.py</files>
  <behavior>
    New tiny module `backend/src/dotmd/storage/lock_constants.py`:
      LOCK_TABLE: str = "migration_v16_lock"

    Update migration_v16.py to import LOCK_TABLE from this module (P1 used a module-local constant; replace it with the shared import). This is a small one-line edit to migration_v16 — acceptable because it's Wave 3 after P1 and P1 is listed in `depends_on`. `migration_v16.py` is now declared in `files_modified` per cycle-2 NEW-MED-3 hygiene.

    Defensive metadata edit: if P1 Task 1 did not ship `get_stored_payload`, add it here first (single SELECT by chunk_id returning `{"text","heading_hierarchy","level"} | None`). P1's cycle-3 update commits to shipping this helper; this plan lists `metadata.py` in `files_modified` defensively so the executor's change-tracker is accurate in either case.

    Rewrite `_index_file`:

    - For each chunk produced by the chunker for a file:
        existing = metadata.get_stored_payload(strategy, c.chunk_id)
        if existing is not None:
            # Content-addressed id means same id => same content. If the stored
            # payload disagrees, surface it — that's either a chunker bug or a
            # real hash collision. [Addresses Review-HIGH from codex on P3]
            if (existing["text"] != c.text
                or existing["heading_hierarchy"] != json.dumps(c.heading_hierarchy)
                or existing["level"] != c.level):
                logger.warning(
                    "ingest_payload_mismatch chunk_id=%s file=%s diverged_fields=%s",
                    c.chunk_id, file_path, <list of diverged field names>,
                )
                # Continue with INSERT OR IGNORE — DO NOT overwrite stored row.
        metadata.insert_chunk(strategy, c.chunk_id, c.heading_hierarchy, c.level, c.text)
        metadata.add_file_path(strategy, c.chunk_id, str(file_path), c.chunk_index)

    - Vector write: unchanged logic except it must skip when `embedding_cache` already has an entry for the chunk's text_hash (Phase 15 cache). If vec_meta_<strategy> already has the chunk_id, skip vec write (idempotent).
    - FTS write: `INSERT OR REPLACE INTO chunks_fts_<strategy> (chunk_id, text, title, tags) VALUES (...)` — idempotent on chunk_id (Research §Component Responsibilities).
    - Graph write (MENTIONS): unchanged — already content-keyed.
    - No call anywhere in pipeline.py to `delete_chunks_by_file`; that symbol is removed in P1.

    Tests (tests/ingestion/test_pipeline_m2m_insert.py — RED skeletons from P6):
    - test_insert_or_ignore_on_repeat: Index same file twice → chunks_* row count unchanged after second pass; chunks_* `text` unchanged between passes (Pitfall 1 regression).
    - test_two_files_identical_content_share_chunk: Two files with identical content → one chunks_* row, two M2M rows.
    - test_repeated_heading_in_same_file_creates_two_m2m_rows: File with repeated identical heading+body twice at different chunk_index → two M2M rows sharing chunk_id (PK includes chunk_index, Decision #3).
    - test_vec_meta_not_rewritten_on_reindex: vec_meta_* row count does not grow on re-index of already-embedded chunks (Phase 15 cache still honoured).
    - test_payload_mismatch_logs_warn_without_overwriting (Review-HIGH-P3): fixture two files produce a "same chunk_id" collision via monkeypatched chunker emitting different text for the same id; ingest logs WARN; stored row retains first-writer's text.
  </behavior>
  <action>
    Audit current `_index_file` carefully. Research §Component Responsibilities flags this as the main mutation point. Preserve the DI shape (metadata, vector_store, keyword_engine, graph_store injected at construction).

    If P1 did not ship `get_stored_payload`, add it as a tiny metadata helper first inside this task (single SELECT by chunk_id — two-line implementation). Trickle/P4 do not need it; it is internal to ingest.

    Remove any residual `char_offset` parameters flowing from chunker → pipeline (Decision #8 — closed already in P1 for the chunker; assert it stays gone here).

    Update migration_v16.py's LOCK_TABLE constant: replace any `LOCK_TABLE = "migration_v16_lock"` module-level line with `from dotmd.storage.lock_constants import LOCK_TABLE` near the top of the file. All in-module usages continue to work because the name resolves identically. Run migration_v16's test suite to confirm no regression.

    Grep gate (strip comments/blank to avoid self-invalidation):
      grep -n "upsert_chunk\|ON CONFLICT.*DO UPDATE" backend/src/dotmd/ingestion/pipeline.py | grep -v '^\s*#'
    Expected: 0 lines.

    Additional grep verifying the import swap:
      grep -c "from dotmd.storage.lock_constants import LOCK_TABLE" backend/src/dotmd/ingestion/migration_v16.py
    Expected: ≥ 1.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_m2m_insert.py tests/ingestion/test_migration_v16.py -x --tb=short</automated>
  </verify>
  <done>
    - `lock_constants.py` shipped.
    - migration_v16.py imports LOCK_TABLE from the shared module (one-line swap; P1's other logic untouched).
    - metadata.py carries `get_stored_payload` (either from P1 or added defensively here).
    - _index_file writes via insert_chunk + add_file_path only; payload mismatch on conflict WARN-logged without overwrite.
    - All five behavior tests green; P1's own test suite still green after the import swap.
    - Grep audit clean.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Advisory lock check in TrickleIndexer startup</name>
  <files>backend/src/dotmd/ingestion/trickle.py</files>
  <behavior>
    - On `TrickleIndexer.start()` (or equivalent init path before the fcntl file lock is claimed): open `index.db` read-only (`mode=ro` URI), check whether `migration_v16_lock` row with `id=1` exists.
    - If lock held:
        - log error: `trickle refused to start: migration_v16_lock held since {locked_at} by pid {pid}@{host} mode={mode}`
        - exit with non-zero (sys.exit(2) or raise — use whatever the existing trickle lifecycle expects for a clean refusal)
    - If lock absent OR table does not exist at all (fresh DB): proceed.
    - Graceful handling: if `migration_v16_lock` table is absent (pre-migration DB), treat as clear — do not error.

    Documentation in this task's SUMMARY: the startup check is a GUARDRAIL against operator forgetting to stop trickle before `migrate run`. It is NOT full mutual exclusion — if trickle is already running when migration begins, migration's lock INSERT will see no prior row and race is possible. The operational runbook (P2 SUMMARY) instructs operators to stop the trickle service before running migration. [Addresses Review-MED from codex about "not full mutual exclusion".]

    Tests (tests/ingestion/test_trickle_lock.py — RED skeletons from P6):
    - test_refuses_while_locked: insert lock row; start trickle; assert non-zero exit + error log with pid/host/mode.
    - test_starts_when_lock_cleared: no lock row; trickle starts normally.
    - test_starts_when_lock_table_absent: brand-new DB with no migration tables; trickle starts.
    - test_refuses_on_dry_run_lock: lock row with mode='dry-run' also blocks trickle (dry-run still holds the lock per P1 Review-MED-6 fix).
  </behavior>
  <action>
    Read the current trickle lifecycle to pick the exact hook point; likely `TrickleIndexer.__init__` end or `start()` top. Import LOCK_TABLE from `dotmd.storage.lock_constants` — do NOT import from migration_v16 (addresses Review-LOW about cross-module dependency).

    Use a short-lived sqlite connection (`sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=1)`). Close immediately after the check.

    Table-existence guard:
      SELECT 1 FROM sqlite_master WHERE type='table' AND name=?

    Do NOT take the trickle fcntl file lock before this check — if we did, we'd create a deadlock risk for the operator who runs `migrate run` while trickle sits in a retry loop.

    Add a docstring block at the top of the lock-check function: "Startup guardrail ONLY; not full mutex. Operator must stop trickle before running migration. See 16-03-SUMMARY.md for operational runbook."
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_trickle_lock.py -x --tb=short</automated>
  </verify>
  <done>
    - All four test cases green.
    - Trickle importable; no circular import introduced.
    - Trickle imports `LOCK_TABLE` from `storage.lock_constants` (grep assertion: `grep -c "from dotmd.storage.lock_constants import" backend/src/dotmd/ingestion/trickle.py` ≥ 1; and `grep -c "from dotmd.ingestion.migration_v16 import" backend/src/dotmd/ingestion/trickle.py` = 0).
    - Error log format matches the Research §Pattern 2 example.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| trickle indexer → index.db | same-process long-lived writer; must not overlap migration DDL |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-09 | Data integrity | trickle racing migration | mitigate | advisory lock sentinel check at trickle startup + operator runbook |
| T-16-10 | Data integrity | UPSERT-DO-UPDATE clobber on content-addressed ids | mitigate | replace with INSERT OR IGNORE on chunks_* (Pitfall 1) |
| T-16-11 | Denial of service | stale lock prevents trickle startup indefinitely | accept | operator runbook in P2 status output explains manual `DELETE FROM migration_v16_lock` |
| T-16-21 | Data integrity | chunker bug or hash collision produces divergent payload for same chunk_id | mitigate | payload-consistency check at ingest conflict; WARN log + retain first writer |
</threat_model>

<verification>
- `pytest tests/ingestion/test_pipeline_m2m_insert.py tests/ingestion/test_trickle_lock.py tests/ingestion/test_migration_v16.py -x` green (migration_v16 still green after the LOCK_TABLE import swap).
- Grep: `grep -rn "ON CONFLICT.*DO UPDATE\|upsert_chunk" backend/src/dotmd/ | grep -v '^\s*#'` → 0 lines.
- Grep: `grep -c "from dotmd.ingestion.migration_v16" backend/src/dotmd/ingestion/trickle.py` = 0 (runtime must not depend on migration module).
- Grep: `grep -c "LOCK_TABLE" backend/src/dotmd/storage/lock_constants.py` ≥ 1.
- Grep: `grep -c "from dotmd.storage.lock_constants import LOCK_TABLE" backend/src/dotmd/ingestion/migration_v16.py` ≥ 1.
</verification>

<success_criteria>
- Ingest re-indexing is idempotent on content rows.
- Identical-content files share one chunks_* row.
- Payload-mismatch on chunk_id conflict is WARN-logged without overwriting.
- Trickle refuses to start while migration lock is held (any mode); starts cleanly when lock absent or pre-migration.
- trickle.py does not import from migration_v16.py at runtime.
- migration_v16.py uses the shared `lock_constants.LOCK_TABLE` (cycle-2 NEW-MED-3 declared cleanly).
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-03-SUMMARY.md` covering: new ingest pseudocode, payload-consistency check format, trickle startup check placement, operational runbook (stop trickle before `migrate run`), interaction with Phase 15 embedding_cache, clarification that lock-check is guardrail not full mutex, confirmation of the migration_v16 LOCK_TABLE import swap.
</output>
</content>
</invoke>