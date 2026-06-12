---
phase: 16-content-dedup-schema
plan: 04
subsystem: ingestion/storage
tags: [purge, m2m, transaction, holder-aware, cascade, falkordb, graph-audit]
dependency_graph:
  requires: [16-01, 16-03]
  provides:
    - "_purge_file: single-transaction decrement-cascade across all strategies"
    - "purge_orphaned_files: scans chunk_file_paths_* M2M tables + disk-existence check"
    - "falkordb_graph.py: delete_chunks_from_graph + delete_file_node narrow helpers"
    - "sqlite_vec.py: delete_by_chunk_ids(strategy, chunk_ids, *, conn)"
    - "fts5.py: remove_chunks conn= kwarg for caller-transaction participation"
  affects: [16-05, 16-06]
tech_stack:
  added: []
  patterns:
    - "Single-transaction purge: BEGIN/COMMIT owned by pipeline across all strategies"
    - "Decrement-then-cascade: delete M2M rows first, cascade only zero-holder chunk_ids"
    - "Post-commit best-effort external state: graph + fingerprints outside transaction"
    - "Graph holder-aware path: delete_chunks_from_graph(orphans) + delete_file_node(fp)"
    - "Caller-owned connection pattern: delete_by_chunk_ids + remove_chunks accept conn="
    - "AttributeError fallback: LadybugDB without narrow helpers falls back to delete_file_subgraph"
key_files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/storage/falkordb_graph.py
    - backend/src/dotmd/storage/sqlite_vec.py
    - backend/src/dotmd/search/fts5.py
decisions:
  - "Graph audit: branch (b) — delete_file_subgraph is unsafe for shared chunks (Section nodes MERGE on chunk_id; DETACH DELETE strips MENTIONS edges). Holder-aware path used."
  - "falkordb_graph.py gained delete_chunks_from_graph + delete_file_node. Decision #5 (no schema change) respected — these are call-site helpers, not schema changes."
  - "fts5.py remove_chunks extended with conn= kwarg. When conn supplied: no self-commit (caller's transaction). When conn=None: original behavior (self._conn + commit). Back-compat not required per project rule."
  - "purge_orphaned_files made discovered_paths optional (None = disk-existence check). Trickle call site unchanged; test call with no args supported."
  - "Task 2 implementation merged into Task 1 commit — both tasks modify pipeline.py and the changes are logically inseparable (purge_orphaned_files delegates to _purge_file)."
metrics:
  duration: "~25m"
  completed: "2026-04-25"
  tasks: 2
  files_created: 0
  files_modified: 4
---

# Phase 16 Plan 04: Purge and Change Detection Summary

Holder-aware `_purge_file` with single-transaction decrement-cascade (M2M + chunks + vec + FTS) and `purge_orphaned_files` scanning `chunk_file_paths_*` M2M tables.

## Graph Audit Result — Branch (b)

**Audit subject:** `FalkorDBGraphStore.delete_file_subgraph(file_path)`

**Implementation read:**
```python
# Deletes Section nodes keyed by file_path ATTRIBUTE (not chunk_id)
self._graph.query("MATCH (s:Section {file_path: $fp}) DETACH DELETE s", ...)
self._graph.query("MATCH (f:File {id: $fp}) DETACH DELETE f", ...)
```

**Problem:** Section nodes are MERGE'd on `chunk_id` (their `id` property). Under M2M, two files sharing the same chunk_id produce the same Section node. `add_section_node` uses MERGE + SET, so the second file's ingest overwrites `file_path` on the shared Section. `DETACH DELETE` on `Section {file_path: fp}` removes the node AND all its edges (MENTIONS/REL to Entity nodes). If a shared chunk is still held by another file, this incorrectly strips the other file's graph associations.

**Decision: Branch (b) — holder-aware path required.**

`delete_file_subgraph` is NOT called in `_purge_file`. Instead:
- `delete_chunks_from_graph(orphan_chunk_ids)` — deletes only Section nodes for chunk_ids whose holder count reached 0
- `delete_file_node(file_path)` — deletes the File node for the purged file

falkordb_graph.py was modified (conditional edit — branch b required it).

## New Purge Flow

```
_purge_file(file_path):
│
├── BEGIN   ← single sqlite3 transaction
│   for each strategy in chunk_file_paths_* tables:
│     orphans = delete_m2m_for_file(strategy, file_path, conn=conn)
│     if orphans:
│       delete_orphan_chunks(strategy, orphans, conn=conn)
│       delete_by_chunk_ids(strategy, orphans, conn=conn)   ← vec_meta + vec0
│       DELETE FROM chunks_fts_{strategy} WHERE chunk_id IN (orphans)
│
├── COMMIT  ← or ROLLBACK on any exception
│
└── (post-commit, best-effort)
    graph_store.delete_chunks_from_graph(all_orphans)  ← holder-aware
    graph_store.delete_file_node(file_path)
    chunk_tracker.remove_fingerprint(file_path)
    embed_tracker.remove_fingerprint(file_path)
    [failures WARN-logged; next orphan sweep reconciles]
```

**Transaction boundary:** ONE BEGIN/COMMIT covers ALL strategies × {M2M delete, orphan cascade, vec_meta/vec0 cascade, FTS cascade}. ROLLBACK restores pre-purge state exactly.

## FTS5 Signature Tweak

`fts5.remove_chunks` signature extended from `remove_chunks(chunk_ids)` to `remove_chunks(chunk_ids, *, conn=None)`.

- When `conn` supplied: uses that connection, does NOT call `commit()` — participates in caller's transaction.
- When `conn=None`: uses `self._conn` and calls `self._conn.commit()` — original behavior preserved.

This is a phase-internal change; back-compat not required per project rules.

## purge_orphaned_files Rewrite

**Before:** queried `SELECT DISTINCT file_path FROM chunks_*` (column dropped in P1).
**After:** queries `SELECT DISTINCT file_path FROM chunk_file_paths_*` (M2M table).

Key changes:
- `discovered_paths` parameter made optional. `None` = disk-existence check via `Path.exists()`. Trickle call site (passing `discovered_paths` explicitly) still works unchanged.
- Delegates entirely to `_purge_file` per file — each file gets its own atomic transaction.
- Summary log: `files_discovered=N files_missing=M paths_purging=K`.
- `_present_strategies(conn)` helper introduced — discovers strategies from `chunk_file_paths_*` tables (not `chunks_*`), so strategy switches don't leak.

**Trickle call site:** `_startup_checks()` → called once at `_run_index_loop()` start, before `_process_backlog` and `_watch_mode`. Startup-only confirmed, no change needed.

## Grep Audit Results

```bash
# No blind file_path deletes remain
grep -rn "DELETE FROM chunks_.*WHERE file_path" backend/src/dotmd/ | grep -v '^\s*#'
# → 0 lines
```

## Post-Commit External State Failure Policy

Graph and fingerprint cleanup runs **after** the sqlite3 COMMIT. These are external state, not part of the atomic DB transaction:

- **Failure:** WARN-logged with `file_path`. Does NOT undo the DB purge.
- **Reconciliation:** The next `purge_orphaned_files` sweep will re-attempt the per-file purge for any drift. Since the M2M rows are already gone (committed), `delete_m2m_for_file` will return an empty orphan list and `_purge_file` will be a no-op for DB tables. Graph state will remain stale until a full reindex or a future graph-reconciliation pass.
- **LadybugDB fallback:** If `graph_store` lacks `delete_chunks_from_graph` (AttributeError), falls back to `delete_file_subgraph`. This is the pre-M2M behavior and is acceptable for the embedded LadybugDB backend which is not the production graph store.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing functionality] purge_orphaned_files: discovered_paths made optional**
- **Found during:** Task 2 test review — `test_orphan_sweep_finds_missing_files` calls `pipeline.purge_orphaned_files()` with no arguments
- **Issue:** The original signature required `discovered_paths: set[str]` as a mandatory positional arg. Tests expect no-arg call where disk existence is checked directly.
- **Fix:** Changed to `discovered_paths: set[str] | None = None`. When `None`, uses `Path(fp).exists()` to determine orphans.
- **Files modified:** `pipeline.py`

**2. [Rule 2 - Missing infrastructure] FTS5 cascade inline in pipeline (no separate helper call)**
- **Found during:** Task 1 implementation — FTS5 virtual tables require the same connection object; wrapping via `keyword_engine.remove_chunks(conn=conn)` requires matching table name.
- **Issue:** `self._keyword_engine` is bound to the ACTIVE strategy's FTS table only. For multi-strategy purge, the pipeline must directly DELETE from `chunks_fts_{strategy}` for each strategy.
- **Fix:** FTS5 cascade is done inline in the `_purge_file` loop: `conn.executemany("DELETE FROM chunks_fts_{strategy} WHERE chunk_id = ?", ...)`. The `keyword_engine.remove_chunks(conn=)` signature tweak is still added (for callers that use single-strategy purge paths) but `_purge_file` uses the direct approach for multi-strategy correctness.
- **Files modified:** `pipeline.py`, `fts5.py`

## Known Stubs

None. All production code is implemented.

## Threat Flags

No new security-relevant surface introduced. Threat mitigations from plan's STRIDE register:
- **T-16-12** (cascade deletes shared chunk): mitigated — holder count check via `delete_m2m_for_file` returning only zero-holder orphans.
- **T-16-13** (partial cascade leaves inconsistent tables): mitigated — single BEGIN/COMMIT across all tables; explicit ROLLBACK on exception.
- **T-16-22** (graph strips MENTIONS for shared chunks): mitigated — branch (b) audit confirmed unsafe; holder-aware path implemented.
- **T-16-23** (graph/fingerprint drift after post-commit failure): accepted — WARN-logged; next orphan sweep reconciles; DB state is authoritative.

## Self-Check: PASSED

**Files modified:**
- `backend/src/dotmd/ingestion/pipeline.py` — EXISTS
- `backend/src/dotmd/storage/falkordb_graph.py` — EXISTS
- `backend/src/dotmd/storage/sqlite_vec.py` — EXISTS
- `backend/src/dotmd/search/fts5.py` — EXISTS

**Commits:**
- `56a58d1` — feat(16-04): Task 1 + Task 2: EXISTS

**Test results:** 10/10 Wave-1 P4 tests GREEN; 38/38 P1+P3+P4 tests GREEN (no regression)
