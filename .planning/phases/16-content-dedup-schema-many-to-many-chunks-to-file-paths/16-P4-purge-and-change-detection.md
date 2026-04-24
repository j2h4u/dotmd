---
phase: 16-content-dedup-schema
plan: 4
type: execute
wave: 4
depends_on: [16-P1, 16-P3]
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
    - "The entire per-file purge (M2M delete + orphan cascade across chunks_*, vec_meta_*, vec0_*, chunks_fts_*) runs inside ONE sqlite3 transaction; rollback restores pre-purge state exactly."
    - "`graph_store.delete_file_subgraph(file_path)` is called ONLY after DB commit AND only when the file is confirmed gone. Audit of the current implementation is a hard prerequisite in Task 1 — if it removes content-keyed MENTIONS edges, the plan routes through a holder-aware alternative instead."
  artifacts:
    - path: backend/src/dotmd/ingestion/pipeline.py
      provides: "_purge_file rewritten as transactional decrement-then-cascade across all strategies; purge_orphaned_files updated to scan M2M."
  key_links:
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/metadata.py
      via: "delete_m2m_for_file returns orphan chunk_ids; delete_orphan_chunks finalises (both use caller's connection)"
      pattern: "delete_m2m_for_file|delete_orphan_chunks"
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/storage/sqlite_vec.py
      via: "delete_by_chunk_ids cascades vec_meta_* + vec0_* (uses caller's connection)"
      pattern: "delete_by_chunk_ids"
    - from: backend/src/dotmd/ingestion/pipeline.py
      to: backend/src/dotmd/search/fts5.py
      via: "remove_chunks cascades FTS5 (uses caller's connection)"
      pattern: "remove_chunks"
---

<objective>
Rewrite the per-file purge from "blind DELETE by file_path from chunks_*" to "decrement M2M then cascade-delete only chunks that lost their last holder" (Decision #6 + Research Pitfall 2). The M2M delete + orphan cascade for a given file run inside ONE explicit transaction owned by the pipeline (addresses Review-HIGH/MEDIUM from both reviewers about atomicity). Update `purge_orphaned_files` to scan the M2M table. Audit `graph_store.delete_file_subgraph` for content-vs-file boundary correctness before calling it (addresses Review-MEDIUM from opencode).

Purpose: Under M2M semantics, deleting a file must not obliterate a chunk that another file still references. The old purge was 1-to-1 and unsafe. This plan makes purge holder-aware AND atomic.

Output: Updated `_purge_file` and `purge_orphaned_files` with transactional correctness and full cascade coverage; graph_store call sites audited and guarded.
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
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-03-SUMMARY.md
@backend/src/dotmd/ingestion/pipeline.py
@backend/src/dotmd/ingestion/trickle.py
@backend/src/dotmd/storage/metadata.py
@backend/src/dotmd/storage/sqlite_vec.py
@backend/src/dotmd/search/fts5.py

<interfaces>
From P1 metadata layer (transaction contract: caller owns BEGIN/COMMIT):
- `metadata.delete_m2m_for_file(strategy, file_path, *, conn) -> list[str]` — returns chunk_ids that lost their last holder. Uses supplied conn; does NOT commit.
- `metadata.delete_orphan_chunks(strategy, chunk_ids, *, conn)` — removes from chunks_* only; uses supplied conn.

From P1 sqlite_vec helper:
- `sqlite_vec.delete_by_chunk_ids(strategy, chunk_ids, *, conn)` — removes from vec_meta_* + vec0_*.

From existing FTS5 (may need a small signature tweak to accept conn):
- `fts5.remove_chunks(strategy, chunk_ids, *, conn)` — DELETE FROM chunks_fts_<strategy> WHERE chunk_id IN (...).

Graph store contract (Decision #5: no Phase 16 schema change):
- `graph_store.delete_file_subgraph(file_path)` — MUST be audited in Task 1 before calling. See audit checklist.

Fingerprint trackers: `chunk_tracker.remove_fingerprint(file_path)`, `embed_tracker.remove_fingerprint(file_path)` — unchanged.

Wave sequencing: P3 is Wave 3, must land first (both modify pipeline.py and trickle.py). P4 is Wave 4.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Audit graph_store.delete_file_subgraph + rewrite _purge_file as single-transaction decrement + cascade</name>
  <files>backend/src/dotmd/ingestion/pipeline.py</files>
  <behavior>
    STEP 1 — Audit (mandatory first step, addresses Review-MEDIUM from opencode):
      Read the current `delete_file_subgraph` implementation in `backend/src/dotmd/storage/falkordb_graph.py` (or wherever it lives). Document in the task SUMMARY:
        - What entities/edges it removes (File nodes, MENTIONS edges, CO_OCCURS edges?).
        - Whether MENTIONS edges are keyed on (file_path, chunk_id) or on chunk_id alone.

      Decision tree:
        (a) If delete_file_subgraph ONLY removes `File(file_path=X)` node + its direct `HAS_CHUNK` / similar edges: SAFE under M2M — call unchanged.
        (b) If it removes MENTIONS edges keyed on chunk_id (content-level): NOT SAFE — it would strip MENTIONS for chunks still held by other files. Route through a HOLDER-AWARE alternative: pass in the `orphans` list (chunks whose holder count reached 0) and call a narrower helper `graph_store.delete_chunks_from_graph(orphans) + graph_store.delete_file_node(file_path)` instead of `delete_file_subgraph`.

      Decision #5 says "zero graph changes"; that means NO SCHEMA change. Adding a narrower call site if audit demands it is a call-site change, not a schema change, and is required for correctness.

    STEP 2 — New _purge_file logic per file_path (transactional):

    ```python
    conn = metadata.connection()  # or whatever helper surfaces the shared SQLite conn
    try:
        conn.execute("BEGIN")
        all_orphans_by_strategy: dict[str, list[str]] = {}
        for strategy in _present_strategies(conn):
            orphans = metadata.delete_m2m_for_file(strategy, file_path, conn=conn)
            if orphans:
                metadata.delete_orphan_chunks(strategy, orphans, conn=conn)
                vector_store.delete_by_chunk_ids(strategy, orphans, conn=conn)
                keyword_engine.remove_chunks(strategy, orphans, conn=conn)  # FTS5
                all_orphans_by_strategy[strategy] = orphans
        conn.execute("COMMIT")
    except Exception:
        conn.execute("ROLLBACK")
        raise

    # --- Post-commit, best-effort external state ---
    # Graph + fingerprints are outside the sqlite transaction (external state).
    # Order is deliberate: DB commit first; if graph/fingerprint cleanup
    # fails, DB state is authoritative and reconcilable on next purge_orphaned_files.
    try:
        if _graph_delete_file_subgraph_is_safe():  # audit result baked in
            graph_store.delete_file_subgraph(file_path)
        else:
            # Holder-aware path — only delete chunk-keyed graph artefacts
            # for chunks confirmed orphan across ALL strategies
            for strategy, orphans in all_orphans_by_strategy.items():
                graph_store.delete_chunks_from_graph(orphans)
            graph_store.delete_file_node(file_path)
    except Exception as e:
        logger.warning("graph cleanup failed after DB commit: %s (file=%s)", e, file_path)
    try:
        chunk_tracker.remove_fingerprint(file_path)
        embed_tracker.remove_fingerprint(file_path)
    except Exception as e:
        logger.warning("fingerprint cleanup failed after DB commit: %s (file=%s)", e, file_path)
    ```

    The key invariants (addresses Review-HIGH codex on atomicity + Review-MED opencode on transaction boundary):
    1. ONE sqlite `BEGIN` / `COMMIT` covers ALL strategies × {M2M delete, orphan cascade, vec cascade, FTS cascade}.
    2. On ANY exception inside the BEGIN block, ROLLBACK restores pre-purge state across every table.
    3. Graph + fingerprint cleanup run AFTER commit (external state, not rollback-able). Failures are logged but do not undo the DB purge — a subsequent `purge_orphaned_files` sweep reconciles.

    Strategy discovery: use `_present_strategies(conn)` helper — if the codebase already exposes a "list all chunks_<strategy> tables" iterator (commit bb79455 established this), reuse it. Otherwise add a small helper that does `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'chunks_%' AND name NOT LIKE 'chunks_fts_%'`.

    Tests (tests/ingestion/test_pipeline_purge.py — RED skeletons from P6):
    - test_purge_single_holder_cascades_chunk: file A is sole holder of chunk X; deleting A removes X from chunks_*, vec_meta_*, vec0_*, chunks_fts_*.
    - test_purge_shared_holder_preserves_chunk: files A and B both hold chunk X; deleting A removes only the (X, A, ...) M2M row; X survives in chunks_*; X still reachable via file_path=B.
    - test_purge_mixed_orphans_and_shared: file A holds X (solo) and Y (shared with B); deleting A cascades X only.
    - test_purge_is_transactional_on_failure: inject failure in vector_store.delete_by_chunk_ids (monkeypatch to raise mid-call); assert (a) conn.rollback executed, (b) chunks_*/M2M/vec_meta_*/FTS all restored to pre-purge row counts, (c) file_path still present in M2M afterward.
    - test_purge_runs_across_all_strategies: a file with chunks in two strategies — both strategies' tables are cleaned in the same transaction.
    - test_graph_cleanup_failure_does_not_rollback_db (NEW): monkeypatch `graph_store.delete_file_subgraph` to raise after DB commit; assert DB purge persisted and graph failure logged.
    - test_graph_holder_aware_path_when_audit_flags_unsafe (NEW): if audit found (b) above, verify that shared chunks' MENTIONS edges survive.
  </behavior>
  <action>
    Read existing `_purge_file` (pipeline.py:~1053) carefully. Preserve its call-order for graph/fingerprint operations but move them OUTSIDE the DB transaction per the new spec.

    DO the audit in Step 1 before writing any code. Record the audit outcome (branch (a) or (b)) in the task SUMMARY. This is a hard prerequisite per Review-MED from opencode. If the result is (b), add `graph_store.delete_chunks_from_graph(chunk_ids)` + `graph_store.delete_file_node(file_path)` to `falkordb_graph.py` as narrow call-site helpers. Decision #5 permits call-site additions; it only forbids schema changes.

    Per Research Open Q #1: orchestration stays in pipeline.py; helpers live in metadata/sqlite_vec/fts5. This plan confirms that shape.

    Anti-pattern check (Research): no DB-level CASCADE triggers. Cascade is explicit Python code so migration semantics remain readable.

    Signature change compatibility: if `fts5.remove_chunks` currently doesn't accept `conn=`, extend its signature. Back-compat not required (phase-internal change; rewritten during Phase 16).
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_purge.py -x --tb=short</automated>
  </verify>
  <done>
    - Audit of `delete_file_subgraph` documented in SUMMARY with branch outcome.
    - _purge_file uses single-transaction decrement-cascade pattern with rollback on failure.
    - Graph + fingerprint cleanup run post-commit, best-effort, failures logged.
    - All seven test cases green (five original + two new review-driven).
    - Multi-strategy cascade covered.
    - Transaction rollback on mid-cascade failure verified by row-count deltas.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Rewrite purge_orphaned_files to scan chunk_file_paths_*</name>
  <files>backend/src/dotmd/ingestion/pipeline.py, backend/src/dotmd/ingestion/trickle.py</files>
  <behavior>
    - `purge_orphaned_files` now queries each chunk_file_paths_<strategy> for distinct file_paths, compares to disk reality, and calls the rewritten `_purge_file` on any path that no longer exists.
    - Preserves commit bb79455's behaviour of scanning ALL strategies (not just the active one) so strategy switches don't leak.
    - Produces a summary log: files_discovered=N, files_missing=M, paths_purged=K.
    - Runs as a startup-only operation in trickle (after lock check, before first index pass) — addresses Review-MED from opencode suggesting "consider as startup-only". Verify trickle call site invokes it at startup and not concurrently with indexing.

    Tests (tests/ingestion/test_pipeline_orphan_sweep.py — RED skeletons from P6):
    - test_orphan_sweep_finds_missing_files: M2M contains a file_path that doesn't exist on disk; sweep calls _purge_file for exactly that path.
    - test_orphan_sweep_ignores_present_files: no purge calls when all paths exist.
    - test_orphan_sweep_multi_strategy: stale paths in strategy A and strategy B — both purged in the same per-file transaction.
  </behavior>
  <action>
    Replace the old `SELECT DISTINCT file_path FROM chunks_<strategy>` query with `SELECT DISTINCT file_path FROM chunk_file_paths_<strategy>`. The rest of the function (existence check via Path.exists / stat) is unchanged.

    Verify by reading trickle.py that `purge_orphaned_files` runs AT STARTUP (post-lock-check, pre-index-loop). If it currently runs concurrently or on a timer, move it to startup-only.
  </action>
  <verify>
    <automated>cd backend && pytest tests/ingestion/test_pipeline_orphan_sweep.py -x --tb=short</automated>
  </verify>
  <done>
    - Orphan sweep queries the M2M table.
    - Multi-strategy sweep proven by test.
    - Summary log line emitted.
    - Trickle calls orphan sweep at startup only.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| trickle file-delete event → pipeline._purge_file | single-process; input is a file_path string from the local filesystem scan |
| pipeline → graph_store (external DB) | post-commit best-effort; failure logged, not rolled back |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-12 | Data integrity | cascade deletes a shared chunk | mitigate | holder-count check — orphan list only contains chunk_ids whose last M2M row was just removed |
| T-16-13 | Data integrity | partial cascade leaves chunks_* without vec_meta_* or vice versa | mitigate | single transaction owned by pipeline across M2M delete + orphan cascade + vec/FTS delete; explicit rollback |
| T-16-14 | Denial of service | orphan sweep query degrades on large M2M tables | accept | idx_chunk_file_paths_<strategy>_file_path (from P1) keeps the distinct scan cheap |
| T-16-22 | Data integrity | graph_store.delete_file_subgraph strips MENTIONS edges for shared chunks | mitigate | Task 1 audit decides branch (a) vs (b); holder-aware path used if (b) |
| T-16-23 | Repudiation | graph/fingerprint state drifts from DB after post-commit failure | accept | failure WARN-logged; next orphan sweep reconciles; DB state is authoritative |
</threat_model>

<verification>
- `pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -x` green.
- Grep: `grep -rn "DELETE FROM chunks_.*WHERE file_path" backend/src/dotmd/ | grep -v '^\s*#'` → 0 lines (column no longer exists).
- Audit note for `delete_file_subgraph` captured in 16-04-SUMMARY.md.
</verification>

<success_criteria>
- Shared-holder survival proven by test.
- Multi-strategy cascade coverage verified.
- Orphan sweep operates over M2M table.
- Single-transaction atomicity proven: failure injection mid-cascade leaves DB exactly as pre-purge.
- Graph cleanup correctly scoped (audit branch (a) or (b) documented and tested).
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-04-SUMMARY.md` with:
- The new purge flow diagram (single-transaction boundary highlighted).
- Graph audit result (branch (a) or (b)) and rationale.
- The grep audits that passed.
- Post-commit external-state failure handling policy.
</output>
</content>
</invoke>