---
phase: 15-content-addressed-caching
plan: "03"
subsystem: ingestion/storage
tags: [blake3, chunk-id, content-addressed, migration, path-independent]
dependency_graph:
  requires: [15-01, 15-02]
  provides: [migration_v15.run_migration_v15, migration_v15.needs_migration_v15, chunker._make_chunk_id]
  affects:
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/ingestion/migration_v15.py
    - backend/pyproject.toml
tech_stack:
  added: [blake3>=1.0]
  patterns:
    - content-addressed-id
    - state-marker-resume
    - collision-guard-before-mutation
    - per-strategy-transaction
key_files:
  created:
    - backend/src/dotmd/ingestion/migration_v15.py
  modified:
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/pyproject.toml
decisions:
  - "blake3(body_checksum:chunk_index:chunk_strategy) — 64-char hexdigest, path-independent, strategy-scoped"
  - "body_checksum computed inside chunk_file() as blake2b(kind+newline+body) — same formula as chunk_fingerprints_{strategy}.checksum"
  - "chunk_strategy param added to chunk_file() with default heading_512_50 for backward compat"
  - "migration_v15_state table tracks per-strategy status (pending/collision_checked/complete) — resume skips done strategies"
  - "Collision check aborts before any UPDATE if COUNT(new_ids) != COUNT(DISTINCT new_ids)"
  - "FTS5 plain UPDATE safe — chunk_id is UNINDEXED in chunks_fts_* (confirmed by OpenCode, overrides CONTEXT.md D-21)"
  - "Backup refuses to overwrite existing .bak — operator must remove manually to get fresh backup"
metrics:
  duration: ~20 min
  completed: "2026-04-24 (checkpoint reached — awaiting human verification)"
  tasks: 2 of 3 (Task 3 is checkpoint:human-verify)
  files: 4
---

# Phase 15 Plan 03: Content-Addressed Chunk IDs Summary

**One-liner:** blake3(body_checksum:chunk_index:chunk_strategy) replaces path-based blake2b chunk_ids — migration script with state marker and collision guard; checkpoint pending operator verification.

**Status: CHECKPOINT REACHED** — Tasks 1 and 2 committed; Task 3 (human-verify) awaits operator.

## What Was Built

### Task 1 — chunker.py + pyproject.toml (commit bf484f0)

`_make_chunk_id()` signature changed from `(file_path, chunk_index)` to `(body_checksum, chunk_index, chunk_strategy)`. The new formula is:

```python
_blake3.blake3(f"{body_checksum}:{chunk_index}:{chunk_strategy}".encode()).hexdigest()
```

Returns a 64-char hexdigest (down from 128-char blake2b). The `body_checksum` is computed inside `chunk_file()` as `blake2b(kind + "\n" + body)` — the same formula used by `chunk_fingerprints_{strategy}.checksum`, so the migration script can JOIN on it directly.

`chunk_file()` gains a `chunk_strategy: str = "heading_512_50"` parameter. Both call sites in `pipeline.py` (`_chunk_files()` and `index_file()`) now pass `chunk_strategy=self._strategy`.

`blake3>=1.0` added to `pyproject.toml` dependencies. The blake3 package requires a Rust build chain — the Docker image must be rebuilt (not just restarted) after deployment.

### Task 2 — migration_v15.py (commit 7c597d8)

Standalone script at `backend/src/dotmd/ingestion/migration_v15.py` that migrates all existing chunk_ids in `index.db` from the old path-based blake2b format (128-char) to the new content-addressed blake3 format (64-char).

Key design properties:

- **needs_migration_v15()** — checks ALL chunks tables (not just a sample) for 128-char IDs, correctly detecting partial migration state.
- **Backup** — creates `index.db.bak` before any mutation; refuses to overwrite an existing backup.
- **State marker** — `migration_v15_state` table with `(strategy, status, completed_at)`. Status progression: pending → collision_checked → complete. Rerunning skips strategies already in `complete` state.
- **id_map construction** — JOINs `chunks_{strategy}` with `chunk_fingerprints_{strategy}` on `file_path` to get `(old_id, checksum, chunk_index)` tuples, then computes new IDs using the same blake3 formula as the new chunker.
- **Collision check** — before any UPDATE, asserts `len(new_ids) == len(set(new_ids))`. Aborts with a descriptive error if duplicate files produce colliding new IDs.
- **Atomic per-strategy transaction** — updates `chunks_*`, `chunks_fts_*`, and all `vec_meta_*` tables in a single `with conn:` block; marks strategy complete atomically.
- **FTS5 safety** — plain UPDATE used throughout (chunk_id is UNINDEXED in FTS5 tables).
- **_verify_v15()** — four checks: orphan count (chunks not in vec_meta), uniqueness (COUNT != COUNT DISTINCT), FTS row parity, and no remaining 128-char IDs.
- **Post-migration instructions** — printed to stdout after success, including the `should_invalidate` warm-cache verification step.

## Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Switch chunk_id to blake3 formula + add blake3 dep | bf484f0 | chunker.py, pipeline.py, pyproject.toml |
| 2 | Add migration_v15.py with state marker + collision guard | 7c597d8 | migration_v15.py |
| 3 | (checkpoint — pending) | — | — |

## Deviations from Plan

None — Tasks 1 and 2 executed exactly as written.

## Checkpoint Details (Task 3)

Task 3 is `type="checkpoint:human-verify" gate="blocking"`. The operator must:

1. Rebuild Docker image (`docker compose build` — blake3 is a compiled dep)
2. Start container and run Steps 1–4 verification commands
3. Stop container, run migration script outside container
4. Confirm migration state, chunk ID format (64-char), and strategy completion
5. Start container, run `reindex_graph()`, confirm GLiNER did NOT load

See full verification steps in 15-03-PLAN.md Task 3 `<how-to-verify>` section.

## Threat Model Coverage

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-15-03-01 | Container stopped before migration; .bak created before any mutation | Implemented |
| T-15-03-02 | Migration script designed to run after `docker compose stop`; checkpoint enforces order | Implemented |
| T-15-03-03 | Collision check aborts migration before any UPDATE if new IDs not all distinct | Implemented |
| T-15-03-04 | .bak intentional recovery artifact — accepted (single-user localhost) | Accepted |
| T-15-03-05 | migration_v15_state per-strategy state marker; _verify_v15 scans for remaining 128-char IDs | Implemented |

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, or schema changes beyond what is described in the plan's threat model.

## Self-Check: PASSED

- `backend/src/dotmd/ingestion/chunker.py` contains `def _make_chunk_id(body_checksum`: FOUND
- `backend/src/dotmd/ingestion/chunker.py` contains `blake3`: FOUND (3 occurrences)
- `backend/src/dotmd/ingestion/pipeline.py` contains `chunk_strategy=self._strategy`: FOUND (2 occurrences)
- `backend/pyproject.toml` contains `blake3>=1.0`: FOUND
- `backend/src/dotmd/ingestion/migration_v15.py` created: FOUND
- `migration_v15.py` contains `run_migration_v15`, `needs_migration_v15`, `.bak`, `blake3`, `_verify_v15`, `migration_v15_state`, `collision`, `length(chunk_id) = 128`, `COUNT(DISTINCT chunk_id)`, `FTS PARITY`, `should_invalidate`: ALL FOUND
- Commit bf484f0 exists: FOUND
- Commit 7c597d8 exists: FOUND
- Both files parse as valid Python: CONFIRMED
