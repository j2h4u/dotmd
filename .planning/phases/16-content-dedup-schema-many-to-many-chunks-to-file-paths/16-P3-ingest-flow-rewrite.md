---
phase: 16-content-dedup-schema
plan: 3
type: execute
wave: 3
depends_on: [16-P1]
files_modified:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/trickle.py
autonomous: true
requirements: [DEDUP-05, DEDUP-07]
must_haves:
  truths:
    - "`IndexingPipeline._index_file` uses INSERT OR IGNORE on chunks_* and INSERT OR IGNORE on chunk_file_paths_*; never UPDATEs on conflict."
    - "Trickle refuses to start while `migration_v16_lock` sentinel row is present; exits with non-zero code and a clear log line."
    - "Re-indexing the same file twice is a no-op on chunks_* content; M2M associations remain correct."
    - "Indexing a file whose chunks already exist from another file adds M2M associations without touching the existing chunks_* rows."
  artifacts:
    - path: backend/src/dotmd/ingestion/pipeline.py
      provides: "Rewritten _index_file that writes via the new metadata M2M surface."
    - path: backend/src/dotmd/ingestion/trickle.py
      provides: "Startup advisory-lock check that blocks while migration_v16_lock is held."
  key_links:
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/metadata.py
      via: "insert_chunk (OR IGNORE) + add_file_path (OR IGNORE)"
      pattern: "insert_chunk|add_file_path"
    - from: backend/src/dotmd/ingestion/trickle.py
      to: backend/src/dotmd/ingestion/migration_v16.py
      via: "lock-sentinel check at startup"
      pattern: "migration_v16_lock"
---

<objective>
Rewrite the ingest write path to match the content-addressed schema: INSERT OR IGNORE on `chunks_*` and `chunk_file_paths_*` (replacing the legacy UPSERT that overwrites data — Research Pitfall 1). Add a startup check to `TrickleIndexer` that refuses to run while `migration_v16_lock` is held (Decision #6 advisory lock).

Purpose: The current UPSERT-DO-UPDATE path silently corrupts data under content-addressed ids; trickle must also refuse to race with a running migration. This plan closes both.

Output: Updated `_index_file` + trickle startup guard.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@backend/src/dotmd/ingestion/pipeline.py
@backend/src/dotmd/ingestion/trickle.py
@backend/src/dotmd/storage/metadata.py

<interfaces>
From P1:
- `metadata.insert_chunk(strategy, chunk_id, heading_hierarchy, level, text) -> None` (INSERT OR IGNORE)
- `metadata.add_file_path(strategy, chunk_id, file_path, chunk_index) -> None` (INSERT OR IGNORE)
- Lock table name constant shared via `migration_v16._LOCK_TABLE`

Chunker emits: `Chunk(chunk_id, text, heading_hierarchy, level, file_paths=[src], chunk_index)` — no char_offset.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite IndexingPipeline._index_file for M2M write path</name>
  <files>backend/src/dotmd/ingestion/pipeline.py</files>
  <behavior>
    - For each chunk produced by the chunker for a file:
        metadata.insert_chunk(strategy, c.chunk_id, c.heading_hierarchy, c.level, c.text)
        metadata.add_file_path(strategy, c.chunk_id, str(file_path), c.chunk_index)
    - Vector write: unchanged logic except it must skip when `embedding_cache` already has an entry for the chunk's text_hash (Phase 15 cache). If vec_meta_<strategy> already has the chunk_id, skip vec write (idempotent).
    - FTS write: `INSERT OR REPLACE INTO chunks_fts_<strategy> (chunk_id, text, title, tags) VALUES (...)` — idempotent on chunk_id (Research §Component Responsibilities).
    - Graph write (MENTIONS): unchanged — already content-keyed.
    - No call anywhere in pipeline.py to `delete_chunks_by_file`; that symbol is removed in P1.

    Tests (tests/ingestion/test_pipeline_m2m_insert.py):
    - Index same file twice → chunks_* row count unchanged after second pass; chunks_* `text` unchanged between passes (Pitfall 1 regression).
    - Two files with identical content → one chunks_* row, two M2M rows.
    - File with repeated identical heading+body twice at different chunk_index → two M2M rows sharing chunk_id (PK includes chunk_index, Decision #3).
    - vec_meta_* row count does not grow on re-index of already-embedded chunks (Phase 15 cache still honoured).
  </behavior>
  <action>
    Audit current `_index_file` carefully. Research §Component Responsibilities flags this as the main mutation point. Preserve the DI shape (metadata, vector_store, keyword_engine, graph_store injected at construction).

    Remove any residual `char_offset` parameters flowing from chunker → pipeline (Decision #8 — closed already in P1 for the chunker; assert it stays gone here).

    Grep gate:
      grep -n "upsert_chunk\|ON CONFLICT.*DO UPDATE" backend/src/dotmd/ingestion/pipeline.py
    Expected: 0 lines.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_m2m_insert.py -x --tb=short</automated>
  </verify>
  <done>
    - _index_file writes via insert_chunk + add_file_path only.
    - All four behavior tests green.
    - Grep audit clean.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Advisory lock check in TrickleIndexer startup</name>
  <files>backend/src/dotmd/ingestion/trickle.py</files>
  <behavior>
    - On `TrickleIndexer.start()` (or equivalent init path before the fcntl file lock is claimed): open `index.db` read-only, check whether `migration_v16_lock` row with `id=1` exists.
    - If lock held:
        - log error: `trickle refused to start: migration_v16_lock held since {locked_at} by pid {pid}@{host}`
        - exit with non-zero (sys.exit(2) or raise — use whatever the existing trickle lifecycle expects for a clean refusal)
    - If lock absent OR table does not exist at all (fresh DB): proceed.
    - Graceful handling: if `migration_v16_lock` table is absent (pre-migration DB), treat as clear — do not error.

    Tests (tests/ingestion/test_trickle_lock.py):
    - test_refuses_while_locked: insert lock row; start trickle; assert non-zero exit + error log.
    - test_starts_when_lock_cleared: no lock row; trickle starts normally.
    - test_starts_when_lock_table_absent: brand-new DB with no migration tables; trickle starts.
  </behavior>
  <action>
    Read the current trickle lifecycle to pick the exact hook point; likely `TrickleIndexer.__init__` end or `start()` top. Reuse the `_LOCK_TABLE` constant from migration_v16 (import it — do not duplicate the string).

    Use a short-lived sqlite connection (`sqlite3.connect(path, timeout=1)`), PRAGMA `query_only=1` for belt-and-suspenders. Close immediately after the check.

    Table-existence guard:
      SELECT 1 FROM sqlite_master WHERE type='table' AND name=?

    Do NOT take the trickle fcntl file lock before this check — if we did, we'd create a deadlock risk for the operator who runs `migrate run` while trickle sits in a retry loop.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_trickle_lock.py -x --tb=short</automated>
  </verify>
  <done>
    - All three test cases green.
    - Trickle importable; no circular import introduced by using `migration_v16._LOCK_TABLE`.
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
| T-16-09 | Data integrity | trickle racing migration | mitigate | advisory lock sentinel check at trickle startup |
| T-16-10 | Data integrity | UPSERT-DO-UPDATE clobber on content-addressed ids | mitigate | replace with INSERT OR IGNORE on chunks_* (Pitfall 1) |
| T-16-11 | Denial of service | stale lock prevents trickle startup indefinitely | accept | operator runbook in P2 status output explains manual `DELETE FROM migration_v16_lock` |
</threat_model>

<verification>
- `pytest tests/ingestion/test_pipeline_m2m_insert.py tests/ingestion/test_trickle_lock.py -x` green.
- Grep: `grep -rn "ON CONFLICT.*DO UPDATE\|upsert_chunk" backend/src/dotmd/` → 0 lines (P1 removed the helper, this plan removes any residual caller).
</verification>

<success_criteria>
- Ingest re-indexing is idempotent on content rows.
- Identical-content files share one chunks_* row.
- Trickle refuses to start while migration lock is held; starts cleanly when lock absent or pre-migration.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-03-SUMMARY.md` covering: new ingest pseudocode, trickle startup check placement, interaction with Phase 15 embedding_cache.
</output>
