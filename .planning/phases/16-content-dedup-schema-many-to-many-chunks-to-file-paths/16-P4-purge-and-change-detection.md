---
phase: 16-content-dedup-schema
plan: 4
type: execute
wave: 3
depends_on: [16-P1]
files_modified:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/trickle.py
autonomous: true
requirements: [DEDUP-08]
must_haves:
  truths:
    - "Deleting a file removes ONLY its (chunk_id, file_path, chunk_index) rows from chunk_file_paths_*."
    - "A chunk_id loses its chunks_*/vec_meta_*/vec0_*/chunks_fts_* rows only after its holder count reaches 0."
    - "Editing a file so its content changes: old orphaned chunks cascade-delete; new chunks INSERT OR IGNORE; new M2M rows added. Chunks still held by another file survive."
    - "`purge_orphaned_files` scans chunk_file_paths_* for file_paths no longer on disk and purges per file via the decrement-cascade helper."
    - "The entire per-file purge runs inside a single sqlite3 transaction (BEGIN/COMMIT/ROLLBACK)."
  artifacts:
    - path: backend/src/dotmd/ingestion/pipeline.py
      provides: "_purge_file rewritten as decrement-then-cascade across all strategies; purge_orphaned_files updated to scan M2M."
  key_links:
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/metadata.py
      via: "delete_m2m_for_file returns orphan chunk_ids; delete_orphan_chunks finalises"
      pattern: "delete_m2m_for_file|delete_orphan_chunks"
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/sqlite_vec.py
      via: "delete_by_chunk_ids cascades vec_meta_* + vec0_*"
      pattern: "delete_by_chunk_ids"
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/search/fts5.py
      via: "remove_chunks cascades FTS5"
      pattern: "remove_chunks"
---

<objective>
Rewrite the per-file purge from "blind DELETE by file_path from chunks_*" to "decrement M2M then cascade-delete only chunks that lost their last holder" (Decision #6 + Research Pitfall 2). Update `purge_orphaned_files` to scan the M2M table (previously scanned chunks_*.file_path — that column is gone). Works across all chunk strategies (preserving commit bb79455's multi-strategy orphan sweep).

Purpose: Under M2M semantics, deleting a file must not obliterate a chunk that another file still references. The old purge was 1-to-1 and unsafe. This plan makes purge holder-aware.

Output: Updated `_purge_file` and `purge_orphaned_files` with transactional correctness and full cascade coverage.
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
@backend/src/dotmd/storage/sqlite_vec.py
@backend/src/dotmd/search/fts5.py

<interfaces>
From P1 metadata layer:
- `metadata.delete_m2m_for_file(strategy, file_path) -> list[str]` — returns chunk_ids that lost their last holder. Transactional inside metadata.
- `metadata.delete_orphan_chunks(strategy, chunk_ids)` — removes from chunks_* only.

From P1 sqlite_vec helper (added in P1 Task 2):
- `sqlite_vec.delete_by_chunk_ids(strategy, chunk_ids)` — removes from vec_meta_* + vec0_*.

From existing FTS5:
- `fts5.remove_chunks(strategy, chunk_ids)` — DELETE FROM chunks_fts_<strategy> WHERE chunk_id IN (...).

Graph store keeps `delete_file_subgraph(file_path)` unchanged per Decision #5 (zero FalkorDB changes).
Fingerprint trackers: `chunk_tracker.remove_fingerprint(file_path)`, `embed_tracker.remove_fingerprint(file_path)` — unchanged.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Rewrite _purge_file as decrement + cascade across strategies</name>
  <files>backend/src/dotmd/ingestion/pipeline.py</files>
  <behavior>
    New logic per file_path:
      for strategy in settings.all_strategies_present_in_db:
          orphans = metadata.delete_m2m_for_file(strategy, file_path)
          if orphans:
              metadata.delete_orphan_chunks(strategy, orphans)
              vector_store.delete_by_chunk_ids(strategy, orphans)
              keyword_engine.remove_chunks(strategy, orphans)  # FTS5
      graph_store.delete_file_subgraph(file_path)  # UNCHANGED per Decision #5
      chunk_tracker.remove_fingerprint(file_path)
      embed_tracker.remove_fingerprint(file_path)

    Transaction discipline (Pitfall 2): the M2M delete + orphan cascade for a given strategy share one BEGIN/COMMIT. metadata.delete_m2m_for_file already owns a transaction internally; if that's sufficient, keep it. Otherwise wrap the three-step cascade inside pipeline in an explicit transaction.

    Strategy discovery: re-use whatever "list all present strategies" helper the codebase already has (commit bb79455 established a cross-strategy scan; reuse that iterator, do not hand-roll).

    Tests (tests/ingestion/test_pipeline_purge.py):
    - test_purge_single_holder_cascades_chunk: file A is sole holder of chunk X; deleting A removes X from chunks_*, vec_meta_*, vec0_*, chunks_fts_*.
    - test_purge_shared_holder_preserves_chunk: files A and B both hold chunk X; deleting A removes only the (X, A, ...) M2M row; X survives in chunks_*; X still reachable via file_path=B.
    - test_purge_mixed_orphans_and_shared: file A holds X (solo) and Y (shared with B); deleting A cascades X only.
    - test_purge_is_transactional_on_failure: inject failure after M2M delete, before orphan cascade; verify rollback (no dangling state).
    - test_purge_runs_across_all_strategies: a file with chunks in two strategies — both strategies' tables are cleaned.
  </behavior>
  <action>
    Read existing `_purge_file` (pipeline.py:~1053) carefully. Preserve its call order for graph/fingerprint operations — M2M cascade is inserted AHEAD of those (graph + fingerprints remain per-file operations).

    Per Research Open Q #1: orchestration stays in pipeline.py; helpers live in metadata/sqlite_vec/fts5. This plan confirms that shape.

    Anti-pattern check (Research): no DB-level CASCADE triggers. Cascade is explicit Python code so migration semantics remain readable.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_purge.py -x --tb=short</automated>
  </verify>
  <done>
    - _purge_file uses decrement-cascade pattern.
    - All five test cases green.
    - Multi-strategy cascade covered.
    - Transaction rollback on mid-cascade failure verified.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Rewrite purge_orphaned_files to scan chunk_file_paths_*</name>
  <files>backend/src/dotmd/ingestion/pipeline.py, backend/src/dotmd/ingestion/trickle.py</files>
  <behavior>
    - `purge_orphaned_files` now queries each chunk_file_paths_<strategy> for distinct file_paths, compares to disk reality, and calls the rewritten `_purge_file` on any path that no longer exists.
    - Preserves commit bb79455's behaviour of scanning ALL strategies (not just the active one) so strategy switches don't leak.
    - Produces a summary log: files_discovered=N, files_missing=M, paths_purged=K.

    Tests (extend tests/ingestion/test_pipeline_purge.py or new file test_pipeline_orphan_sweep.py):
    - test_orphan_sweep_finds_missing_files: M2M contains a file_path that doesn't exist on disk; sweep calls _purge_file for exactly that path.
    - test_orphan_sweep_ignores_present_files: no purge calls when all paths exist.
    - test_orphan_sweep_multi_strategy: stale paths in strategy A and strategy B — both purged.
  </behavior>
  <action>
    Replace the old `SELECT DISTINCT file_path FROM chunks_<strategy>` query with `SELECT DISTINCT file_path FROM chunk_file_paths_<strategy>`. The rest of the function (existence check via Path.exists / stat) is unchanged.

    If trickle invokes `purge_orphaned_files` at startup (post-lock-check), ensure the call path still works — this is usually a no-change, but verify by reading trickle.py.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_orphan_sweep.py -x --tb=short</automated>
  </verify>
  <done>
    - Orphan sweep queries the M2M table.
    - Multi-strategy sweep proven by test.
    - Summary log line emitted.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| trickle file-delete event → pipeline._purge_file | single-process; input is a file_path string from the local filesystem scan |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-12 | Data integrity | cascade deletes a shared chunk | mitigate | holder-count check — orphan list only contains chunk_ids whose last M2M row was just removed |
| T-16-13 | Data integrity | partial cascade leaves chunks_* without vec_meta_* or vice versa | mitigate | transaction boundary around M2M delete + orphan cascade |
| T-16-14 | Denial of service | orphan sweep query degrades on large M2M tables | accept | idx_chunk_file_paths_<strategy>_file_path (from P1) keeps the distinct scan cheap; knowledgebase size is small-single-user |
</threat_model>

<verification>
- `pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -x` green.
- Grep: `grep -rn "DELETE FROM chunks_.*WHERE file_path" backend/src/dotmd/` → 0 lines (column no longer exists; any residual query is a bug).
</verification>

<success_criteria>
- Shared-holder survival proven by test.
- Multi-strategy cascade coverage verified.
- Orphan sweep operates over M2M table.
- Transaction rollback on mid-cascade failure proven.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-04-SUMMARY.md` with the new purge flow diagram and the grep audits that passed.
</output>
