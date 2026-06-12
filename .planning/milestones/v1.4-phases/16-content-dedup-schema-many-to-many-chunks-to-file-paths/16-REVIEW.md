---
phase: 16-content-dedup-schema-many-to-many-chunks-to-file-paths
reviewed: 2026-04-25T00:00:00Z
depth: standard
files_reviewed: 13
files_reviewed_list:
  - backend/src/dotmd/ingestion/migration_v16.py
  - backend/src/dotmd/ingestion/migration_v15.py
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/storage/sqlite_vec.py
  - backend/src/dotmd/storage/falkordb_graph.py
  - backend/src/dotmd/storage/lock_constants.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/trickle.py
  - backend/src/dotmd/ingestion/chunker.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/search/fts5.py
  - backend/src/dotmd/cli.py
findings:
  critical: 1
  warning: 5
  info: 2
  total: 8
status: issues_found
---

# Phase 16: Code Review Report

**Reviewed:** 2026-04-25
**Depth:** standard
**Files Reviewed:** 13 (14 listed — cli.py included despite not being in explicit scope)
**Status:** issues_found

## Summary

Phase 16 is a substantial, well-structured migration. The shadow-column flow, M2M backfill, collision collapse, fail-closed divergence gate, advisory lock, and per-strategy transaction boundaries are all correctly designed. The operational guardrails (trickle startup check, lock contention detection, dry-run/verify-only modes) are sound.

One BLOCKER stands out: the migration computes new `chunk_id` values using a different `body_checksum` formula than the chunker. This means chunk IDs produced by the migration will diverge from IDs produced by a subsequent `dotmd index` run on the same files — silently defeating content-deduplication for any file touched after migration. This needs to be resolved before declaring Phase 16 shippable.

The remaining findings are warnings and informational items; none affect the migration's internal consistency.

| # | Severity | Location | Short description |
|---|----------|----------|-------------------|
| CR-01 | BLOCKER | `migration_v16.py:125-137` | `body_checksum` formula mismatch vs chunker — post-migration IDs diverge from fresh-index IDs |
| WR-01 | WARNING | `migration_v16.py:1112-1157` | Spurious `_release_lock` + ProgrammingError on closed connection in `PayloadDivergenceBlocked` path |
| WR-02 | WARNING | `migration_v16.py:208,215` | Unquoted strategy name in `PRAGMA table_info({table})` and `SELECT … FROM {table}` |
| WR-03 | WARNING | `pipeline.py:1030-1042` | `index_file` write path has no wrapping transaction — chunk orphan possible on crash |
| WR-04 | WARNING | `metadata.py:537-542` | `delete_chunks_by_file` (legacy) calls helpers that require `BEGIN/COMMIT` but provides none |
| WR-05 | WARNING | `migration_v16.py:681-695` | Step 5d vector divergence check is dead code — `_fetch_vector_for_divergence_check` always returns `None` |
| IN-01 | INFO | `migration_v16.py:913` | `run_invariants` result discarded in `verify_only` path; CLI re-runs it redundantly |
| IN-02 | INFO | `migration_v16.py:935` | `from collections import defaultdict` inside `verify_only` branch |

---

## Critical Issues

### CR-01: `body_checksum` formula in migration differs from chunker — post-migration IDs will not match fresh-index IDs

**File:** `backend/src/dotmd/ingestion/migration_v16.py:125-137`

**Issue:**

`_compute_body_checksum` hashes `chunk.text` (the split-out chunk text) with a hardcoded kind of `"text"`:

```python
def _compute_body_checksum(text: str, kind: str = "text") -> str:
    return _blake3.blake3(f"{kind}\n{text}".encode()).hexdigest()
```

`_compute_new_id_for_row` calls it with only the chunk text from the `text` column:

```python
body_checksum = _compute_body_checksum(text)
return _chunker_module._make_chunk_id(body_checksum, chunk_index, strategy)
```

The chunker (`chunker.py:180-182`) uses a completely different formula:

```python
body_checksum = _blake3.blake3(f"{kind}\n{body}".encode()).hexdigest()
```

where:
- `kind` is the document kind (e.g. `"document"`, `"meeting_transcript"`) — **not** `"text"`
- `body` is the **entire file body** after frontmatter strip — **not** the individual chunk text. This single checksum is shared by all chunks from the same file; `chunk_index` is the differentiator.

Consequence: after migration, the `chunk_id` for every existing chunk is set to a value that no future `chunk_file()` call on the same content would ever produce. When trickle re-indexes a modified file (or a fresh `dotmd index --force` is run), the same chunk content produces a different ID → INSERT OR IGNORE creates a second row rather than recognising the duplicate → content-deduplication never fires → M2M dedup goal of Phase 16 is silently defeated for any file touched post-migration.

**Fix:**

`_compute_new_id_for_row` must receive the full file body and the document kind, not the chunk text. Because the migration only stores chunk text (not the original file body or per-file kind), the migration cannot reconstruct the exact chunker formula without reading files from disk.

Two options:

1. **Re-read files from disk during migration** (accurate but requires source files to be present):
```python
def _compute_new_id_for_row_from_file(
    file_path: str, kind: str, chunk_index: int, strategy: str
) -> str:
    from dotmd.ingestion.reader import parse_frontmatter, read_file
    content = read_file(Path(file_path))
    _, body = parse_frontmatter(content)
    body_checksum = _blake3.blake3(f"{kind}\n{body}".encode()).hexdigest()
    return _chunker_module._make_chunk_id(body_checksum, chunk_index, strategy)
```
The migration would then pass a canonical `file_path` from the M2M table and the `kind` from the `chunks_*` table.

2. **Accept the formula difference and follow migration with a mandatory full reindex** — document explicitly that `dotmd index --force` must be run after `dotmd migrate run` to rebuild chunk IDs using the canonical formula. This is operationally simpler but every chunk gets deleted and re-created, negating any incremental benefits.

Option 1 is preferred for correctness.

---

## Warnings

### WR-01: `PayloadDivergenceBlocked` handler closes connection, then `finally` attempts `_release_lock` on closed connection

**File:** `backend/src/dotmd/ingestion/migration_v16.py:1112-1157`

**Issue:**

In the real-run `PayloadDivergenceBlocked` handler (lines 1112-1134), `conn.close()` is called explicitly after `_release_lock(conn)`. The exception then propagates to the `finally` block (lines 1148-1157). Because `is_no_persist=False` for a real run, `finally` calls `_release_lock(conn)` again on the already-closed connection. Inside `_release_lock`, `conn.execute(...)` raises `sqlite3.ProgrammingError: Cannot operate on a closed database.` which is swallowed by `except Exception`, but only after logging a spurious `WARNING: Failed to release migration_v16_lock`. The subsequent `conn.close()` in `finally` is a no-op (safe).

The lock is already released; the warning is misleading noise in logs.

**Fix:**

Use a guard flag to avoid double-release:

```python
_lock_released = False
try:
    ...
    except PayloadDivergenceBlocked as exc:
        if not dry_run:
            ...
            _release_lock(conn)
            _lock_released = True
            conn.close()
        raise exc from None
    ...
finally:
    if is_no_persist:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
    elif not _lock_released:
        _release_lock(conn)
    conn.close()
```

---

### WR-02: Unquoted strategy/table name in `PRAGMA` and `SELECT` statements throughout migration

**File:** `backend/src/dotmd/ingestion/migration_v16.py:208,215` (also `_migrate_strategy` lines 530, 557, 598, etc.)

**Issue:**

Strategy names are interpolated directly into SQL without quoting:

```python
table = f"chunks_{strategy}"
pragma = conn.execute(f"PRAGMA table_info({table})").fetchall()
...
count = conn.execute(
    f"SELECT COUNT(*) FROM {table} WHERE length(chunk_id) != 64"
).fetchone()[0]
```

Strategy values come from `_discover_strategies`, which reads table names from `sqlite_master`. SQLite allows table names with SQL metacharacters via quoted identifiers (e.g. `CREATE TABLE "chunks_foo; DROP TABLE bar" ...`). If an attacker can place a crafted `index.db` in the user's `~/.dotmd/` directory, they can embed a table name that injects arbitrary SQL when the migration is run.

The same pattern exists in `metadata.py` (all M2M f-string table names), `sqlite_vec.py`, and `pipeline.py`. The immediate threat model is single-user localhost, which limits exploitability, but `dotmd migrate run` is designed to be run against a database file passed by path, widening the attack surface slightly.

**Fix:**

Quote all table names with double quotes. Alternatively, validate strategy names against a whitelist pattern before use:

```python
import re
_SAFE_NAME_RE = re.compile(r'^[a-zA-Z0-9_]+$')

def _validate_strategy(strategy: str) -> str:
    if not _SAFE_NAME_RE.fullmatch(strategy):
        raise ValueError(f"Invalid strategy name: {strategy!r}")
    return strategy
```

Apply in `_discover_strategies` before returning names, and in any public-facing path that accepts a strategy string.

---

### WR-03: `index_file` write path lacks a wrapping transaction — chunk orphan possible on crash

**File:** `backend/src/dotmd/ingestion/pipeline.py:1030-1042`

**Issue:**

The loop that writes chunk rows and M2M associations in `index_file` issues individual `commit()` calls per operation:

```python
for c in chunks:
    ...
    self._metadata_store.insert_chunk(...)   # commits inside
    self._metadata_store.add_file_path(...)  # commits inside
```

`insert_chunk` calls `self._conn.commit()` (metadata.py:244), then `add_file_path` calls `self._conn.commit()` (metadata.py:265). If the process crashes after `insert_chunk` commits but before `add_file_path` commits, the database contains a row in `chunks_{strategy}` with no corresponding `chunk_file_paths_{strategy}` entry.

This "orphan chunk" will not be returned by `get_chunk_ids_by_file` and therefore will not be cleaned up by `purge_orphaned_files` (which scans M2M tables, not `chunks_*` directly). It will persist indefinitely, consuming storage and leaking into `get_all_chunks()` results, which feeds FTS5 rebuild, graph rebuild, and acronym rebuild.

**Fix:**

Wrap the per-file write loop in a single transaction:

```python
conn = self._conn
conn.execute("BEGIN")
try:
    self._metadata_store.ensure_m2m_table(self._strategy)
    for c in chunks:
        # payload consistency check ...
        self._metadata_store.insert_chunk_no_commit(...)
        self._metadata_store.add_file_path_no_commit(...)
    conn.execute("COMMIT")
except Exception:
    conn.execute("ROLLBACK")
    raise
```

Or add `no_commit=True` kwargs to `insert_chunk`/`add_file_path` and wrap the loop with an explicit `BEGIN`/`COMMIT` in `index_file`.

---

### WR-04: `delete_chunks_by_file` (legacy path) calls helpers that mandate `BEGIN/COMMIT` but does not wrap them

**File:** `backend/src/dotmd/storage/metadata.py:537-542`

**Issue:**

```python
def delete_chunks_by_file(self, file_path: str) -> int:
    strategy = self._table.removeprefix("chunks_")
    conn = self._conn
    orphans = self.delete_m2m_for_file(strategy, file_path, conn=conn)
    self.delete_orphan_chunks(strategy, orphans, conn=conn)
    self._conn.commit()
    return len(orphans)
```

The docstrings for `delete_m2m_for_file` and `delete_orphan_chunks` explicitly state: **"Callers must wrap this in BEGIN/COMMIT."** `delete_chunks_by_file` does not issue `BEGIN` before calling them, then calls `commit()` after. In SQLite's autocommit mode, each statement from `delete_m2m_for_file` and `delete_orphan_chunks` may auto-commit independently before the final `commit()`. If the process crashes after the M2M DELETE commits but before the chunks DELETE commits, M2M rows are gone but the chunk content row remains — the inverse of an orphan chunk.

The docstring acknowledges this risk ("callers should prefer delete_m2m_for_file + delete_orphan_chunks for transactional safety") but the legacy method still ships with the gap.

**Fix:**

```python
def delete_chunks_by_file(self, file_path: str) -> int:
    strategy = self._table.removeprefix("chunks_")
    raw = object.__getattribute__(self._conn, "_real_conn")
    raw.execute("BEGIN")
    try:
        orphans = self.delete_m2m_for_file(strategy, file_path, conn=self._conn)
        self.delete_orphan_chunks(strategy, orphans, conn=self._conn)
        raw.execute("COMMIT")
    except Exception:
        raw.execute("ROLLBACK")
        raise
    return len(orphans)
```

Or, since this is a legacy shim, add a deprecation warning and direct all callers to the transactional pattern.

---

### WR-05: Step 5d vector divergence check is permanently dead code

**File:** `backend/src/dotmd/ingestion/migration_v16.py:681-695`

**Issue:**

`_fetch_vector_for_divergence_check` (lines 151-180) always returns `None`. The function's own comment explains it: "cannot read actual float vector without sqlite_vec". The sqlite_vec extension is not loaded on the migration connection (the migration opens its own `sqlite3.connect()` without loading any extensions). The guard at line 684:

```python
if v_canon is not None and v_other is not None:
```

is therefore always `False`. The body of this block — the only place where `divergence_warnings` is incremented for vector divergence — never executes. The `MigrationReport.divergence_warnings` field will always remain 0 regardless of actual vector differences.

This dead code is not wrong in the sense of causing data loss, but it silently promises a check that never runs, and it leaves `divergence_warnings` misleadingly reporting 0.

**Fix:**

Either:
1. Remove the dead vector divergence loop entirely and document in comments that vector divergence is not checked during migration (the canonical chunk's vector is kept by default in Step 5e's DELETE).
2. If the check is genuinely desired, load the sqlite_vec extension on the migration connection and implement actual float vector reading via the `vec0` table.

If removing, also remove `divergence_warnings` from `MigrationReport` or rename it to `payload_divergence_warnings` to avoid confusion.

---

## Info

### IN-01: `run_invariants` result discarded in `verify_only` path; CLI re-runs it redundantly

**File:** `backend/src/dotmd/ingestion/migration_v16.py:913`

**Issue:**

In `run_migration_v16` with `verify_only=True`, `run_invariants(conn)` is called at line 913 but the result is stored in `inv` and never inspected. The function returns early at line 983 (`return report`). The CLI's `migrate_run` command then opens a fresh connection and calls `run_invariants` again (cli.py:557-559) to obtain the actual pass/fail result for the exit code.

The first call is wasted I/O. Additionally, the first call runs inside the open wrapping transaction (which has `_ensure_state_table` DDL in it), so the DB state it sees differs slightly from what the second call sees (post-ROLLBACK), though for the invariant checks (which are all `SELECT`-only) this makes no practical difference.

**Fix:**

Store the result on `MigrationReport` and return it, so the CLI can use it without re-opening the DB:

```python
# In run_migration_v16:
report.invariant_report = run_invariants(conn)
```

Or simply remove the call inside `run_migration_v16` and rely solely on the CLI's post-ROLLBACK call, which is the authoritative one.

---

### IN-02: `from collections import defaultdict` inside `verify_only` branch

**File:** `backend/src/dotmd/ingestion/migration_v16.py:935`

**Issue:**

```python
from collections import defaultdict
groups: dict[str, list[str]] = defaultdict(list)
```

This import is buried inside the `verify_only` branch of `run_migration_v16`. `collections` is stdlib and always available; there is no reason to defer the import. It creates a misleading impression that the import is conditional or heavy, and makes the code harder to scan.

**Fix:**

Move to the module-level imports at the top of the file.

---

_Reviewed: 2026-04-25_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
