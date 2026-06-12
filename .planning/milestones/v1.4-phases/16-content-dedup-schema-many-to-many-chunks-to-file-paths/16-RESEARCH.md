# Phase 16: Content-dedup schema — Research

**Researched:** 2026-04-24
**Domain:** Storage schema migration + many-to-many chunk↔file_path refactor across SQLite metadata, sqlite-vec, FTS5, FalkorDB graph, and the search API surface.
**Confidence:** HIGH — CONTEXT.md locks decisions #1–#7 with full rationales; all schema/consumer touchpoints have been verified against the live codebase; no unknown frameworks involved (stdlib `sqlite3` + existing project conventions).

## Summary

Phase 16 introduces a junction table `chunk_file_paths_<strategy>(chunk_id, file_path, chunk_index)` with composite PK, drops `file_path` and `chunk_index` from `chunks_<strategy>`, remaps chunk_ids to blake3 content-addressed form (finishing what Phase 15 started), and collapses cross-file content duplicates into a single canonical row per stored artifact (chunk row, vector row, FTS5 row). The migration runs per-strategy with resumable state (`migration_v16_state`) and an advisory lock sentinel that blocks the trickle indexer for the duration. `SearchResult.file_path: Path` becomes `file_paths: list[Path]` (sorted lexicographically) as a clean break — no aliases — propagating through `api/service.py`, `cli.py`, and `mcp_server.py`.

All architectural decisions are locked in CONTEXT.md. Research scope is therefore: verify the locked schema/migration strategy against the actual codebase, enumerate every touchpoint the planner must cover, and flag the small set of mechanical risks (trigger ordering, `INSERT OR IGNORE` vs current `INSERT ... ON CONFLICT UPDATE`, `_purge_file` semantic change).

**Primary recommendation:** Execute the P1–P6 plan breakdown already sketched in CONTEXT.md. Research adds: (a) exhaustive touchpoint list per plan, (b) verified environment facts (sqlite 3.46 — `ALTER TABLE DROP COLUMN` supported), (c) a concrete "consumer audit" inventory for P5's clean-break API change, (d) guardrails around resurrecting `migration_v15` as a superseded no-op rather than deleting it mid-flight.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

1. **Search result shape — LOCKED** — return all file_paths as a list; no "primary/canonical" path.
   Rationale (user): identical content has no canonical holder. API exposes `file_paths: list[str]` (stable ordering: sorted lexicographically for reproducibility, not semantics). UI/caller decides what to render.

2. **API contract — LOCKED: clean break.**
   `file_path: str` is replaced by `file_paths: list[str]` in `SearchResult` and anywhere a chunk surfaces. No `also_at` alias, no deprecation window (per global rule: no backward-compat obligations).

3. **chunk_index placement — LOCKED: M2M table only; PK includes chunk_index.**
   `chunks_*` drops `chunk_index`; it lives in `chunk_file_paths_*(chunk_id, file_path, chunk_index)` with `PRIMARY KEY (chunk_id, file_path, chunk_index)`. Rationale: identical content can legitimately appear multiple times in one file (repeated headings, boilerplate), so `(chunk_id, file_path)` alone is not unique. JOIN cost is negligible with the `(file_path)` index.

4. **Vec collision during migration — LOCKED: keep canonical, discard others, assert divergence.**
   When N old chunks collapse to one new blake3 id, pick canonical = MIN(old chunk_id) for `vec_meta_*` + `vec0_*` + `chunks_fts_*`. Drop the other vectors. Before discard, compute cosine(canonical, discarded) for each pair in the collision group; log WARN if any pair exceeds 0.01 distance (catches unexpected non-determinism or hash collisions on genuinely different content). Do not abort on divergence — migration continues; operator reviews log post-run. TEI non-determinism on identical text is below retrieval noise floor; averaging adds complexity with zero measurable benefit; recomputing defeats the cache-reuse win that motivated Phase 15.

5. **FalkorDB semantics — LOCKED: zero graph changes in Phase 16.**
   - `MENTIONS(chunk_id → entity)` stays unchanged (already content-keyed — correct).
   - `CO_OCCURS(entity → entity)` stays unchanged.
   - `File` nodes stay as-is (no new `HOLDS` edges). No current query or feature needs `File → chunk_id` traversal. Deferred to backlog item 16.1 if and when a consumer demands it. Rationale (Kaizen): building edge infrastructure with no consumer is gold-plating; `HOLDS` duplication on heavily-mirrored content (e.g., `~/.agents/` copies) would inflate graph size for unused queries.

6. **Transaction strategy — LOCKED: per-strategy checkpoints + advisory lock; no VACUUM in v1.**
   Reuse the `migration_v15_state` pattern (renamed `migration_v16_state`). Each strategy migrates in its own transaction with a resume marker. Additionally:
   - **Advisory lock** — migration writes `locked_at` sentinel row on start, clears on success. Trickle checks this row on startup and refuses to run while set. Migration must NOT run concurrently with trickle (DDL vs long-lived connection = deadlock/partial write).
   - **Skip VACUUM** — VACUUM requires 2× disk and holds write lock for the duration. Document as manual post-migration step, not chained into the run.
   - **Prefer `ALTER TABLE DROP COLUMN`** (SQLite ≥3.35) over full CREATE+SELECT+DROP+RENAME rebuild where the only schema change is dropping `file_path`/`chunk_index`. Falls back to rebuild only if DROP COLUMN fails.

7. **Test coverage — LOCKED: full edge-case suite + observability + dry-run.**
   **Data correctness:** modify-one-of-dup-pair, delete-one-of-dup-pair, merge-into-existing, empty-strategy no-op, empty-knowledgebase migration.
   **Operational:** mid-strategy crash + resume (state marker correctness), trickle-refuses-to-run while lock held, trickle-resumes-correctly post-migration (NOT concurrent *during* DDL).
   **Invariants:** pre/post row-count deltas match expected collision-collapse, no orphan chunk_ids in vec_meta_* or FTS, all chunk_ids are 64-char blake3, `UNIQUE(file_path, chunk_index)` holds per strategy.
   **Quality:** vector-divergence assertion during collapse (WARN threshold 0.01 cosine), round-trip top-K property test (fixed query set returns same results pre- vs post-migration for non-collision chunks), `file_paths` list returned in sorted order.
   **Ops modes:**
   - `--dry-run` — writes nothing; reports collision counts, divergence stats, disk delta estimate.
   - `--verify-only` — runs all invariant checks on live DB without mutation.
   - `migrate status` CLI — reports current state marker, per-strategy progress.
   - Structured progress logs: rows/sec, ETA, collision count per strategy, tagged `dotmd-migrate` for journald filtering.

### Claude's Discretion

The CONTEXT.md "Decisions" section is explicit; discretion is limited to implementation mechanics not covered above:
- Exact SQL used for the DROP COLUMN vs rebuild fallback detection.
- Internal helper organisation inside `migration_v16.py` (free functions vs class).
- Whether divergence WARN emission uses `logger.warning` or a dedicated `migration_divergence` logger tag.
- Whether the `_purge_file_m2m` rewrite lives in-place in `pipeline.py` or a new helper module (see Open Questions #1).
- Exactly which `cli.py` subcommand verb names map to the ops modes (`dotmd migrate run / --dry-run / --verify-only / status` vs flat `dotmd migrate-status`).

### Deferred Ideas (OUT OF SCOPE)

- `HOLDS(File → chunk_id)` edges in FalkorDB — deferred to backlog item 16.1 if a consumer demands it.
- VACUUM as part of the migration run — documented as a manual post-migration step.
- Any optimisation of the trickle indexer itself (999.2 pipeline parallelism remains in the backlog).
- On-demand `dotmd cleanup` CLI and periodic scheduling (999.3 items still open, not Phase 16's problem).
- Config separation / indexing_exclude audit (999.6 — separate phase).

</user_constraints>

<phase_requirements>
## Phase Requirements

No formal `REQ-*` IDs are defined in REQUIREMENTS.md for Phase 16 (REQUIREMENTS.md is still pinned to v1.4 Phases 11–12 requirements from 2026-03-30 and has not been updated for Phase 15/16). The requirements below are derived from the phase Goal and CONTEXT.md Decisions; the planner should adopt these IDs or confirm with `/gsd:discuss-phase 16` revision before creating PLAN.md files.

| ID | Description | Research Support |
|----|-------------|------------------|
| DEDUP-01 | Introduce `chunk_file_paths_<strategy>(chunk_id, file_path, chunk_index)` junction table with PK `(chunk_id, file_path, chunk_index)` per chunk strategy | §Standard Stack, §Architecture Patterns, CONTEXT Decision #3 |
| DEDUP-02 | Drop `file_path` and `chunk_index` columns from `chunks_<strategy>`; change PK semantics so chunk_id uniquely identifies content | §Architecture Patterns (schema diff), CONTEXT Decision #6 |
| DEDUP-03 | Collapse collision groups into a canonical chunk + vector + FTS row (MIN(old_chunk_id) canonical); assert cosine divergence ≤ 0.01, WARN otherwise | CONTEXT Decision #4, §Code Examples (divergence check) |
| DEDUP-04 | Per-strategy resumable migration with `migration_v16_state` table and `migration_v16_lock` advisory sentinel | CONTEXT Decision #6, §Code Examples (migration_v15 precedent) |
| DEDUP-05 | Trickle indexer refuses to start while advisory lock is held | CONTEXT Decision #6, §Common Pitfalls (concurrent DDL) |
| DEDUP-06 | `--dry-run`, `--verify-only`, `migrate status` CLI modes with structured logs tagged `dotmd-migrate` | CONTEXT Decision #7, §Architecture Patterns |
| DEDUP-07 | Ingest writes via `INSERT OR IGNORE INTO chunks_*` + `INSERT OR IGNORE INTO chunk_file_paths_*` (no more UPSERT-replace semantics) | §Common Pitfalls (UPSERT vs OR IGNORE) |
| DEDUP-08 | `_purge_file` rewritten as "decrement holder then cascade-delete if zero holders"; applies across chunks, chunks_fts, vec_meta, vec0, fingerprints | §Architecture Patterns (new purge flow), §Code Examples |
| DEDUP-09 | `SearchResult.file_path: Path` replaced with `file_paths: list[Path]` (sorted lexicographically); CLI, MCP, and any API consumer updated in the same commit | CONTEXT Decisions #1, #2; §Don't Hand-Roll (no alias layer) |
| DEDUP-10 | Full edge-case test suite: modify-one, delete-one, merge-into-existing, empty-strategy, crash+resume, lock conflict, row-count invariants, 64-char blake3 assertion, `UNIQUE(file_path, chunk_index)` invariant, round-trip top-K parity | CONTEXT Decision #7 |
| DEDUP-11 | Supersede `migration_v15.py` — keep as a no-op shim that logs "handled by migration_v16" or delete after v16 deploys; `needs_migration_v15` is satisfied as a side-effect of v16 | §Open Questions #2 |

</phase_requirements>

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Schema migration (DDL, row remap, collision collapse) | Storage / SQLite | — | Pure data-layer operation; no service-layer logic involved. Implemented in `backend/src/dotmd/ingestion/migration_v16.py`, modelled on `migration_v15.py`. |
| Advisory lock (migration ↔ trickle mutex) | Storage / SQLite (`migration_v16_lock` row) | Ingestion / trickle startup check | Lock is a row in `index.db`, checked by trickle before claiming the fcntl file lock. |
| Ingest-time dedup (`INSERT OR IGNORE` on chunks + M2M) | Ingestion / pipeline | Storage / metadata.py | Pipeline generates blake3 chunk_ids; metadata store exposes the new M2M upsert primitive. |
| Per-file purge with holder counting | Ingestion / pipeline (`_purge_file`) | Storage / metadata, storage / sqlite_vec, search / fts5 | Logic lives in pipeline; storage layers expose `delete_m2m_rows_for_file`, `delete_orphan_chunks`. |
| Trickle change-detection with M2M semantics | Ingestion / trickle | Ingestion / pipeline | Trickle discovers file changes; pipeline handles the purge/insert mechanics. |
| Search result construction with file_paths list | Search / fusion (hydration) | Storage / metadata (new `get_file_paths_by_chunk_id` query) | `fusion.py::_hydrate_results` JOINs M2M to produce the sorted list. |
| Public API surface (`SearchResult.file_paths`) | API / service + core / models | CLI, MCP, fusion | Pydantic model change propagates through service.search() callers. |
| Graph semantics | Storage / falkordb_graph | — | Decision #5: no changes in this phase. |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| stdlib `sqlite3` | Python 3.12 / SQLite 3.46.1 [VERIFIED: `python3 -c "import sqlite3; sqlite3.sqlite_version"`] | DDL, row remap, transactions, advisory lock row | Already the project's metadata driver; no new dependency needed. 3.46 ≫ 3.35, so `ALTER TABLE DROP COLUMN` is guaranteed available. [CITED: https://www.sqlite.org/lang_altertable.html#otheralter — DROP COLUMN added in 3.35.0] |
| `sqlite-vec` (loaded as extension) | as deployed | Vector meta/data tables (`vec_meta_*`, `vec0_*`) — read cosine for divergence check, delete rows on collapse | Existing project integration in `storage/sqlite_vec.py`. |
| `blake3` | as deployed in Phase 15 | Chunk id generation (`blake3(body_checksum:chunk_index:strategy)`) | Already chosen and deployed. 64-hex-char output is the schema invariant. |
| `pydantic` v2 | as deployed | `SearchResult` / `Chunk` models — update `file_path: Path` → `file_paths: list[Path]` | Existing project convention. |
| `click` | as deployed | CLI ops subcommands (`dotmd migrate run`, `--dry-run`, `--verify-only`, `migrate status`) | Existing project convention. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| stdlib `logging` | 3.12 | Structured progress logs with journald tag `dotmd-migrate` | All migration output. Use `logger.info` with a consistent prefix/extra; journald tag configured via systemd unit or `SyslogIdentifier=`. |
| stdlib `shutil` | 3.12 | Pre-migration backup of `index.db` to `index.db.v16-backup` | Opening bytes of `run_migration()` — same pattern as `migration_v15.py`. |
| stdlib `math` | 3.12 | Cosine similarity for divergence assertion (vectors are small; no numpy needed) | Only inside the migration divergence check. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Junction table `chunk_file_paths_*` | JSON array column `file_paths` on `chunks_*` | Rejected: loses the `(file_path)` index, breaks per-file purge cost, and CONTEXT Decision #3 already requires `chunk_index` be per-association — can't store that in a flat array without a nested structure. |
| `ALTER TABLE DROP COLUMN` | Full rebuild via CREATE+INSERT+DROP+RENAME | Fallback only. Decision #6 locks DROP COLUMN as primary. Rebuild path kept for defensive fallback if a future SQLite deploy regresses or if DROP COLUMN fails for an unexpected reason (e.g., the column referenced by an index or trigger). |
| numpy for cosine | stdlib `math.fsum` + zip | Rejected: single comparison per collision group, no hot-path. Avoids adding numpy to the migration script's import graph. |
| Separate `migration_v16.py` | Extending `migration_v15.py` in place | Rejected: CONTEXT Decision #6 explicitly forks (`migration_v16_state` is a new table). Also, Phase 15 migration stays in history for reproducibility; superseding it cleanly is Decision-#6-aligned. |

**Installation:** No new packages. All tools are already in the deployed backend.

**Version verification:** N/A — no new library selection. Existing dependencies verified against deployed container via the Phase 15 deployment logs.

## Architecture Patterns

### System Architecture Diagram

```
                     ┌──────────────────────────────────────────┐
                     │  dotmd migrate run  (offline / container │
                     │                       stopped)           │
                     └───────────────────┬──────────────────────┘
                                         │
                                         ▼
                         [backup index.db → index.db.v16-backup]
                                         │
                                         ▼
          [acquire advisory lock: INSERT migration_v16_lock(locked_at=now)]
                                         │
                                         ▼
                    ┌────────────  for each chunk_strategy ─────┐
                    │                                           │
                    │  ┌────────────────────────────────────┐   │
                    │  │ skip if state row says 'done'      │   │
                    │  └─────────────┬──────────────────────┘   │
                    │                ▼                          │
                    │  BEGIN TRANSACTION                        │
                    │  1. CREATE chunk_file_paths_<strategy>    │
                    │  2. INSERT INTO chunk_file_paths          │
                    │        SELECT chunk_id, file_path,        │
                    │               chunk_index FROM chunks_*   │
                    │  3. for each row in chunks_*:             │
                    │       new_id = blake3(body_cksum:idx:str) │
                    │       UPDATE chunks_* SET chunk_id=new_id │
                    │       UPDATE chunk_file_paths SET chunk_id│
                    │       UPDATE vec_meta_*, chunks_fts_*     │
                    │  4. detect collisions → collapse group    │
                    │        canonical = MIN(old_chunk_id)      │
                    │        divergence_check(canonical,others) │
                    │        DELETE non-canonical from          │
                    │            chunks_*, vec_meta_*, vec0_*,  │
                    │            chunks_fts_*                   │
                    │  5. ALTER TABLE chunks_*                  │
                    │        DROP COLUMN file_path              │
                    │        DROP COLUMN chunk_index            │
                    │  6. CREATE INDEX idx_chunk_file_paths_    │
                    │        <strategy>_file_path               │
                    │  7. UPDATE migration_v16_state SET done=1 │
                    │  COMMIT                                   │
                    │                                           │
                    └───────────────────────────────────────────┘
                                         │
                                         ▼
                     [release advisory lock: DELETE migration_v16_lock]
                                         │
                                         ▼
                            emit summary: collisions, WARNs,
                            row-count deltas, ETA actual vs estimate


          ── Runtime (post-migration, trickle re-enabled) ──

  file on disk  ──►  chunker (blake3 id) ──►  pipeline._index_file
                                                     │
                                                     ├── INSERT OR IGNORE
                                                     │      chunks_*
                                                     │
                                                     ├── INSERT OR IGNORE
                                                     │      chunk_file_paths_*
                                                     │
                                                     ├── vec_meta_* + vec0_*
                                                     │      (skip if text_hash
                                                     │       already embedded
                                                     │       — Phase 15 cache)
                                                     │
                                                     └── chunks_fts_*
                                                            (INSERT OR REPLACE
                                                             by chunk_id)

  file deleted ──►  trickle._handle_deleted ──►  pipeline._purge_file
                                                     │
                                                     ├── DELETE chunk_file_paths
                                                     │      WHERE file_path=?
                                                     │
                                                     ├── for each orphaned
                                                     │   chunk_id (holder=0):
                                                     │      cascade DELETE
                                                     │      chunks_*, vec_*,
                                                     │      fts_*
                                                     │
                                                     └── remove fingerprints

  search query ──►  engines return chunk_ids ──►  fusion._hydrate
                                                     │
                                                     └── for each chunk_id:
                                                         SELECT file_path
                                                         FROM chunk_file_paths
                                                         WHERE chunk_id=?
                                                         ORDER BY file_path
                                                         → file_paths: list
```

### Component Responsibilities

| Component | File | Responsibility |
|-----------|------|----------------|
| `migration_v16.py` | `backend/src/dotmd/ingestion/migration_v16.py` (NEW) | Resumable schema migration, collision collapse, divergence check, ops modes (--dry-run / --verify-only / status). |
| `migration_v15.py` | `backend/src/dotmd/ingestion/migration_v15.py` | Becomes superseded; either deleted or kept as a stub that defers to v16. See Open Questions #2. |
| `SQLiteMetadataStore` | `backend/src/dotmd/storage/metadata.py` | Adds: M2M table DDL, `upsert_chunk` without `file_path`/`chunk_index`, `add_file_path_for_chunk`, `get_file_paths_by_chunk_id`, `get_chunk_ids_by_file` (now queries the M2M table), `delete_file_path_associations`, `get_orphan_chunk_ids`. |
| `SQLiteVecStore` | `backend/src/dotmd/storage/sqlite_vec.py` | No schema change (already keyed on `chunk_id UNIQUE`). Adds: helper to fetch vectors for a list of chunk_ids for divergence check. |
| `FTS5SearchEngine` | `backend/src/dotmd/search/fts5.py` | No schema change. Existing `INSERT OR REPLACE ... (chunk_id, text, title, tags)` is idempotent on chunk_id — correct for content dedup. |
| `IndexingPipeline` | `backend/src/dotmd/ingestion/pipeline.py` | Rewrites `_index_file` to INSERT OR IGNORE on chunks + M2M. Rewrites `_purge_file` to decrement-and-cascade. Updates `purge_orphaned_files` similarly. |
| `TrickleIndexer` | `backend/src/dotmd/ingestion/trickle.py` | Adds advisory-lock check at startup: if `migration_v16_lock` row is present, log and exit; otherwise proceed as today. |
| `DotMDService.search` | `backend/src/dotmd/api/service.py` | No logic change — but `SearchResult` shape changes; consumers see `file_paths`. |
| `fusion.py::_hydrate_results` | `backend/src/dotmd/search/fusion.py` | JOINs M2M table to fill `file_paths`. Sort order enforced here. |
| `cli.py` | `backend/src/dotmd/cli.py` | (1) Update result printer at line 112 (`r.file_path` → `r.file_paths`). (2) Update `status` at line 161 (`COUNT(DISTINCT file_path) FROM chunks_*` → `COUNT(DISTINCT file_path) FROM chunk_file_paths_*`). (3) Add `dotmd migrate` subcommand group. |
| `mcp_server.py` | `backend/src/dotmd/mcp_server.py` | Line 118 update: `"file_path": str(r.file_path)` → `"file_paths": [str(p) for p in r.file_paths]`. Docstring line 44 update. |
| Core models | `backend/src/dotmd/core/models.py` | `SearchResult.file_path: Path` → `file_paths: list[Path]`. `Chunk.file_path: Path` → `file_paths: list[Path]` (populated by JOIN when the service hydrates). |

### Recommended Project Structure

No structural changes — follow existing layout:

```
backend/src/dotmd/
├── ingestion/
│   ├── migration_v15.py        # superseded — see Open Q #2
│   ├── migration_v16.py        # NEW — this phase's core
│   ├── pipeline.py             # _purge_file + _index_file rewrite
│   └── trickle.py              # advisory lock startup check
├── storage/
│   ├── metadata.py             # M2M DDL + new queries
│   └── sqlite_vec.py           # +helper to read vectors for collapse
├── search/
│   └── fusion.py               # _hydrate_results JOINs M2M
├── api/service.py              # unchanged except SearchResult shape
├── core/models.py              # file_path → file_paths
├── cli.py                      # migrate subcommand + output update
└── mcp_server.py               # output shape update
```

### Pattern 1: Resumable migration with state table

**What:** Per-strategy checkpoint row that lets a crashed migration resume from the next strategy rather than restarting.

**When to use:** Any multi-strategy DDL/remap operation where a single transaction would be too long or risky.

**Example (follows `migration_v15.py` precedent — verified in code):**

```python
# Source: backend/src/dotmd/ingestion/migration_v15.py (line 24–48)
_STATE_TABLE = "migration_v16_state"

def _ensure_state_table(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_STATE_TABLE} (
            strategy TEXT PRIMARY KEY,
            completed_at TEXT NOT NULL,
            collisions_collapsed INTEGER NOT NULL DEFAULT 0,
            divergence_warnings INTEGER NOT NULL DEFAULT 0
        )
    """)
    conn.commit()

def _is_strategy_done(conn: sqlite3.Connection, strategy: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {_STATE_TABLE} WHERE strategy = ?", (strategy,)
    ).fetchone()
    return row is not None

def _mark_strategy_done(
    conn: sqlite3.Connection, strategy: str,
    collisions: int, warnings: int,
) -> None:
    conn.execute(
        f"INSERT INTO {_STATE_TABLE} (strategy, completed_at, "
        f"collisions_collapsed, divergence_warnings) VALUES (?, ?, ?, ?)",
        (strategy, datetime.utcnow().isoformat(), collisions, warnings),
    )
    conn.commit()
```

### Pattern 2: Advisory lock via sentinel row

**What:** A single-row table (`migration_v16_lock`) written at migration start, deleted at success. Trickle refuses to start while the row exists.

**When to use:** Whenever DDL-heavy offline work must not overlap with a long-lived writer.

**Example:**

```python
# Pattern (no equivalent exists in current codebase — this is new)
_LOCK_TABLE = "migration_v16_lock"

def _acquire_lock(conn: sqlite3.Connection) -> None:
    conn.execute(f"""
        CREATE TABLE IF NOT EXISTS {_LOCK_TABLE} (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            locked_at TEXT NOT NULL,
            pid INTEGER NOT NULL,
            host TEXT NOT NULL
        )
    """)
    try:
        conn.execute(
            f"INSERT INTO {_LOCK_TABLE} (id, locked_at, pid, host) "
            f"VALUES (1, ?, ?, ?)",
            (datetime.utcnow().isoformat(), os.getpid(), socket.gethostname()),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise RuntimeError(
            "Migration lock held — another migration is in progress or "
            "a previous run did not release the lock. Inspect "
            f"{_LOCK_TABLE} row and delete manually if stale."
        )

def _release_lock(conn: sqlite3.Connection) -> None:
    conn.execute(f"DELETE FROM {_LOCK_TABLE} WHERE id = 1")
    conn.commit()

# In TrickleIndexer.start():
lock_row = conn.execute(
    f"SELECT locked_at, pid FROM {_LOCK_TABLE} WHERE id = 1"
).fetchone() if _table_exists(conn, _LOCK_TABLE) else None
if lock_row:
    logger.error(
        "migration_v16 lock held since %s (pid %d) — refusing to start",
        lock_row[0], lock_row[1],
    )
    sys.exit(2)
```

### Pattern 3: INSERT OR IGNORE for content-addressed dedup

**What:** Replace the existing `INSERT ... ON CONFLICT DO UPDATE` UPSERT with `INSERT OR IGNORE` on both the chunks table and the M2M association table.

**Why the change matters:** Current code (metadata.py lines 44–54) *overwrites* `file_path`, `text`, `heading_hierarchy` etc. on conflict. In a content-addressed world this UPSERT-UPDATE is wrong — the same `chunk_id` genuinely means the same content, so overwriting is a no-op at best and data-corrupting at worst if a buggy chunker produced inconsistent text for the same id. `INSERT OR IGNORE` cleanly expresses "if this chunk already exists, leave it alone; a new association is the only thing that may be new."

**Example:**

```python
# For chunks_* — content is immutable once written:
conn.execute(
    f"INSERT OR IGNORE INTO {chunks_table} "
    f"(chunk_id, heading_hierarchy, level, text, char_offset) "
    f"VALUES (?, ?, ?, ?, ?)",
    (chunk.chunk_id, heading_json, chunk.level, chunk.text, chunk.char_offset),
)

# For chunk_file_paths_* — (chunk_id, file_path, chunk_index) PK,
# duplicate inserts within one run are no-ops:
conn.execute(
    f"INSERT OR IGNORE INTO chunk_file_paths_{strategy} "
    f"(chunk_id, file_path, chunk_index) VALUES (?, ?, ?)",
    (chunk.chunk_id, str(chunk.file_path), chunk.chunk_index),
)
```

### Anti-Patterns to Avoid

- **Cascading DELETE via triggers:** Don't use `CREATE TRIGGER ... AFTER DELETE` to cascade chunk_file_paths → chunks. Triggers hide the cascade from readers, complicate migration, and interact poorly with bulk deletes. Keep the logic explicit in `_purge_file`.
- **`INSERT OR REPLACE` on chunks_*:** Would delete and re-insert the row, invalidating any foreign key (even logical) references and tripping ordering assumptions in the M2M table. Use `INSERT OR IGNORE`.
- **Single giant transaction across strategies:** Rejected by CONTEXT Decision #6. Per-strategy is resumable; one big transaction locks the DB for the full run.
- **VACUUM inside the migration transaction:** SQLite cannot VACUUM inside a transaction. Even outside one, it requires 2× disk and blocks writes. Out of scope (Decision #6).
- **Silent collision collapse:** Always log a WARN when cosine divergence exceeds 0.01. Silent collapse hides bugs in blake3-id derivation or genuine hash collisions.
- **Deleting `migration_v15.py` in the same commit as v16 ships:** Operators rolling back need v15 to exist. See Open Questions #2.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Backward-compat alias (`file_path` ↔ `file_paths`) | Pydantic `@computed_field` that returns `file_paths[0]` as `file_path`, or a dual-field Pydantic model | Clean break per CONTEXT Decision #2 | Global rule "no legacy compat obligations" + explicit lock. Aliases double the maintenance surface and create new bugs when callers rely on the alias in ways the new field can't support (e.g., iterating all holders). |
| Schema version tracking | A custom `schema_version` table with integer stepping | The `migration_v16_state` + `migration_v16_lock` tables, plus the `length(chunk_id) = 64` invariant | Two tiny sentinel tables are simpler than a versioning framework and match the project's existing Phase 15 pattern. |
| Cosine similarity | Numpy | stdlib `math.fsum` | ≤ O(N*dim) comparisons per collision group, ≤ 429 groups × ≤ handful each × 1024 dims. Dot products are trivial; no numpy import justified for a migration script. |
| Progress/ETA calculation | tqdm | Plain `logger.info` with rows-processed/elapsed math | tqdm outputs escape codes to journald which muddles log aggregation; Decision #7 wants journald-clean structured lines. |
| Concurrency control | multiprocessing / threading | Single-threaded per-strategy with `migration_v16_lock` + existing trickle `fcntl.flock` | Migration is one-shot; concurrency only adds risk. |

**Key insight:** Every "don't hand-roll" entry above is motivated by the small, one-shot nature of this migration and the lock on a "no backward-compat" posture. The temptation to soften the API break or to parallelise the migration is load-bearing — both resist.

## Runtime State Inventory

> Phase 16 is a schema refactor migration. This section enumerates runtime state that survives a pure code/DDL change. Many categories are genuinely empty because Phase 16 is self-contained to one SQLite database.

| Category | Items Found | Action Required |
|----------|-------------|------------------|
| Stored data | `index.db` — all `chunks_*`, `vec_meta_*`, `vec0_*`, `chunks_fts_*`, `chunk_fingerprints`, `embed_fingerprints_*`, `_embedding_cache`, `_extraction_cache` tables. Location: `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` per Phase 15 deploy notes [CITED: backend/src/dotmd/ingestion/migration_v15.py header comment]. | Data migration — the core of Phase 16. Backup before run; run `migration_v16.py` offline. |
| Stored data (secondary) | `_embedding_cache(text_hash, model_name)` and `_extraction_cache(content_hash, model_signature)` — keyed on content, not chunk_id. | No change — already content-keyed (CONTEXT Decisions §6 edge cases). Cache survives the migration transparently. |
| Stored data (FalkorDB) | `graphdb` — `MENTIONS(chunk_id → entity)`, `CO_OCCURS`, `File` nodes. | No change per CONTEXT Decision #5. `MENTIONS.chunk_id` continues to reference blake3 ids (unchanged from Phase 15). Collision collapse is safe because MENTIONS is keyed by chunk_id and the *canonical* chunk_id is kept. |
| Live service config | dotmd Docker Compose on port 8321 (per `dotmd_deployment.md` memory). No external config that embeds the schema. | Stop container before migration (Decision #6 implied — same as Phase 15). Start after migration + verify trickle reconciles. |
| OS-registered state | None — dotmd is a Docker service, no systemd unit names encoding schema, no task scheduler entries, no pm2 registrations. | None — verified by search for dotmd-specific systemd units in recent grep of `/etc/systemd`. |
| Secrets / env vars | None touched — `DOTMD_*` env vars (DATA_DIR, INDEX_DIR, EMBEDDING_MODEL, etc.) are path/name bindings unaffected by the schema change. | None. |
| Build artifacts / installed packages | `pip install -e backend/` installed package in the container. No name changes, no entry-point renames, no `.egg-info` that would go stale. | None. Container rebuild not required unless code ships new dependencies (and it does not). |
| BM25 pickle (`bm25_index.pkl`) | Legacy from pre-Phase-12 era, per backend/CLAUDE.md the current BM25 engine is FTS5-based inside `index.db`. Need to confirm no stale pickle remains at `~/.dotmd/bm25_index.pkl`. | **Verify during P6 test suite:** check `list(INDEX_DIR.iterdir())` on a representative deployment. If the pickle still exists as dead weight, document removal as a side cleanup; do NOT include it in the migration. |

## Common Pitfalls

### Pitfall 1: Current UPSERT semantics conflict with content-addressed IDs

**What goes wrong:** metadata.py today uses `INSERT ... ON CONFLICT(chunk_id) DO UPDATE SET file_path = excluded.file_path, text = excluded.text, ...` (lines 44–54). After Phase 15 made `chunk_id` content-addressed, an UPSERT that overwrites `file_path` on conflict is logically wrong: two files with identical content have *different* `file_path`s, and neither should win. The current code actively clobbers the first-write with whichever file_path happened to be indexed later.

**Why it happens:** Legacy assumption from pre-Phase-15 that `chunk_id` was path-based, so a conflict could only mean "re-index same file."

**How to avoid:** Rewrite `upsert_chunk` → `insert_chunk_if_absent` that uses `INSERT OR IGNORE` on `chunks_*` and a separate `INSERT OR IGNORE` on `chunk_file_paths_*`. Text/heading/level/char_offset on the `chunks_*` row are frozen once the canonical row exists.

**Warning signs:** During migration testing, if you see the same chunk_id's `text` or `heading_hierarchy` changing between passes, the UPSERT has not been properly replaced with OR IGNORE.

### Pitfall 2: `_purge_file` decrement must be all-or-nothing per file

**What goes wrong:** If `_purge_file('A.md')` deletes association rows for chunk_id X but crashes before checking X's holder count, X's storage rows leak.

**Why it happens:** The decrement-then-orphan-check is a two-step logical operation; without a transaction it can partially execute.

**How to avoid:** Wrap `_purge_file` in an explicit `conn.execute('BEGIN')` / `conn.commit()`. Delete M2M rows first, then in the same transaction query `SELECT chunk_id FROM chunks_* LEFT JOIN chunk_file_paths_* USING (chunk_id) WHERE chunk_file_paths_*.chunk_id IS NULL` and delete those orphans from chunks_*, vec_meta_*, vec0_*, chunks_fts_*.

**Warning signs:** Post-test invariant checks report chunks_* rows with no matching chunk_file_paths_* row.

### Pitfall 3: Trickle + migration concurrent run deadlocks or silently corrupts

**What goes wrong:** If trickle is running and a user fires `dotmd migrate run` against the same `index.db`, the DDL (ALTER TABLE DROP COLUMN, CREATE INDEX, etc.) contends with trickle's long-lived writer connection. SQLite will return `SQLITE_BUSY` on the DDL side or, worse, the trickle writer may hold an open schema-version snapshot that invalidates.

**Why it happens:** Migration was designed assuming offline (container stopped), but nothing mechanically enforces that.

**How to avoid:** The advisory lock (Pattern 2). Trickle checks `migration_v16_lock` row at startup; if present, exit with non-zero code. Migration acquires the lock before any DDL and releases only on success. Document the "if migration crashed, `DELETE FROM migration_v16_lock WHERE id = 1` manually after reviewing state" operator runbook.

**Warning signs:** `SQLITE_BUSY` in logs during migration; trickle crash logs mentioning schema changes mid-query.

### Pitfall 4: Cosine divergence false-positive from vector normalisation drift

**What goes wrong:** Two vectors for identical text may have cosine distance slightly > 0 due to TEI server non-determinism (FMA ordering, Flash Attention non-determinism). WARN threshold of 0.01 is chosen to be well above that noise floor but below genuine content mismatch.

**Why it happens:** TEI is not bitwise reproducible on GPU (project is on CPU though — see memory: "CPU Xeon E3 V2 has AVX but NOT AVX2, PyTorch <2.5"). CPU TEI should be more deterministic than GPU, so 0.01 is conservative.

**How to avoid:** WARN, do not abort. Operator reviews logs. If WARN rate is > 1% of collision groups, investigate — it's a likely code bug (e.g., the body checksum calculation treating trailing whitespace differently).

**Warning signs:** Hundreds of divergence WARNs in a single run — means either (a) chunk_id derivation has non-determinism bleeding in, or (b) TEI is drifting. Both warrant investigation before declaring migration clean.

### Pitfall 5: `chunks_fts_*` collapse requires DELETE-by-chunk_id, not by rowid

**What goes wrong:** FTS5 virtual tables expose a `rowid`; collapsing is usually done by rowid for speed. But `chunks_fts_*` has `chunk_id UNINDEXED` as a content column, not as PK (FTS5 has no PK). Deleting "the non-canonical FTS5 row" means `DELETE FROM chunks_fts_* WHERE chunk_id = ?` for each collapsed id.

**Why it happens:** Easy to confuse FTS5 rowid with chunk_id mapping.

**How to avoid:** Explicit `DELETE FROM chunks_fts_{strategy} WHERE chunk_id IN (?, ?, ?)` for the non-canonical set. Verified by existing code at `fts5.py:170` which already uses this pattern.

### Pitfall 6: Search path printing assumes a single Path

**What goes wrong:** `cli.py:112` prints `f"[{i}] {r.file_path}"`. After Decision #2, `r.file_paths` is a list — naively printing it yields `[PosixPath('a'), PosixPath('b')]`. CLI users deserve a readable format.

**Why it happens:** Clean-break API changes every surface that touched the field.

**How to avoid:** Decide a display rule in the CLI (join by comma? first path with "+N more" suffix?). This is a CLI polish decision inside Claude's discretion; pick one and document in the plan. MCP server (`mcp_server.py:118`) should emit the JSON list directly — downstream tooling handles rendering.

### Pitfall 7: `chunks_*.chunk_index` removal breaks existing queries

**What goes wrong:** Any unaudited `SELECT chunk_index FROM chunks_*` becomes a hard error after DROP COLUMN.

**Why it happens:** grep-audit misses dynamic SQL or string-formatted queries.

**How to avoid:** Full audit of both `chunk_index` and `file_path` literals in SQL:

```bash
grep -rn "chunk_index\|file_path" backend/src/dotmd/ --include='*.py' | grep -i "select\|insert\|update\|delete"
```

Every hit must be classified as (a) references the M2M table (OK), (b) references `chunks_*` and must move to M2M (FIX), or (c) references something else entirely (document).

## Code Examples

Verified patterns from existing code or standard SQLite idioms:

### Divergence check during collision collapse

```python
# Pattern: stdlib-only cosine similarity for small collision groups.
# Source: standard cosine definition; no existing code to cite.
import math
import sqlite3

def _cosine(a: list[float], b: list[float]) -> float:
    dot = math.fsum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(math.fsum(x * x for x in a))
    nb = math.sqrt(math.fsum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)

def _check_divergence(
    conn: sqlite3.Connection,
    meta_table: str,
    vec_table: str,
    canonical_id: str,
    discarded_ids: list[str],
    threshold: float = 0.01,
) -> int:
    """Return count of WARN-emitted divergences for this collision group."""
    # Load canonical vector
    canon_row = conn.execute(
        f"SELECT v.embedding FROM {vec_table} v "
        f"JOIN {meta_table} m ON v.rowid = m.rowid "
        f"WHERE m.chunk_id = ?",
        (canonical_id,),
    ).fetchone()
    if canon_row is None:
        return 0
    canonical_vec = list(canon_row[0])
    warnings = 0
    for did in discarded_ids:
        row = conn.execute(
            f"SELECT v.embedding FROM {vec_table} v "
            f"JOIN {meta_table} m ON v.rowid = m.rowid "
            f"WHERE m.chunk_id = ?",
            (did,),
        ).fetchone()
        if row is None:
            continue
        dist = 1.0 - _cosine(canonical_vec, list(row[0]))
        if dist > threshold:
            logger.warning(
                "migration_v16 divergence: canonical=%s discarded=%s "
                "cosine_dist=%.4f (threshold=%.2f)",
                canonical_id, did, dist, threshold,
            )
            warnings += 1
    return warnings
```

### M2M table DDL with index

```python
# Source: CONTEXT.md schema sketch (lines 34–43); verified SQL.
_CREATE_CHUNK_FILE_PATHS_TPL = """
CREATE TABLE IF NOT EXISTS chunk_file_paths_{strategy} (
    chunk_id     TEXT    NOT NULL,
    file_path    TEXT    NOT NULL,
    chunk_index  INTEGER NOT NULL,
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)
"""

_CREATE_CHUNK_FILE_PATHS_INDEX_TPL = """
CREATE INDEX IF NOT EXISTS idx_chunk_file_paths_{strategy}_file_path
    ON chunk_file_paths_{strategy}(file_path)
"""
```

### Per-file purge with holder count

```python
# NEW pattern — replaces current metadata.delete_chunks_by_file().
# Source: CONTEXT.md edge case #2; no existing code to cite.
def purge_file(
    conn: sqlite3.Connection, strategy: str, file_path: str,
) -> list[str]:
    """Remove M2M associations for this file; return chunk_ids that became orphans."""
    chunks_table = f"chunks_{strategy}"
    m2m_table = f"chunk_file_paths_{strategy}"
    conn.execute("BEGIN")
    try:
        # 1. Snapshot the chunk_ids this file had referenced
        rows = conn.execute(
            f"SELECT DISTINCT chunk_id FROM {m2m_table} WHERE file_path = ?",
            (file_path,),
        ).fetchall()
        affected = [r[0] for r in rows]
        # 2. Delete the associations
        conn.execute(
            f"DELETE FROM {m2m_table} WHERE file_path = ?", (file_path,),
        )
        # 3. For each affected chunk_id, check if it still has any holder
        orphans = []
        for cid in affected:
            still_held = conn.execute(
                f"SELECT 1 FROM {m2m_table} WHERE chunk_id = ? LIMIT 1", (cid,),
            ).fetchone()
            if still_held is None:
                orphans.append(cid)
        conn.commit()
        return orphans  # Caller cascades: chunks_*, vec_meta_*, vec0_*, fts_*
    except Exception:
        conn.rollback()
        raise
```

### Hydrating `SearchResult.file_paths` via JOIN

```python
# NEW pattern — replaces the current file_path lookup in fusion._hydrate_results.
# Source: Standard JOIN idiom.
def _get_file_paths_for_chunk(
    conn: sqlite3.Connection, strategy: str, chunk_id: str,
) -> list[str]:
    rows = conn.execute(
        f"SELECT DISTINCT file_path FROM chunk_file_paths_{strategy} "
        f"WHERE chunk_id = ? ORDER BY file_path",  # sorted lexicographic
        (chunk_id,),
    ).fetchall()
    return [r[0] for r in rows]
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Path-based chunk_ids (`blake2b(file_path + chunk_index)`) | Content-addressed blake3 (`blake3(body_checksum:chunk_index:strategy)`) | Phase 15 (2026-04-24) | File moves no longer invalidate cache. Phase 16 finishes the wiring by letting multiple paths point to one row. |
| `chunks_*` 1:1 with file_path | Junction table; `chunks_*` stores content only | Phase 16 (this phase) | Enables true dedup. Storage reduction + search-quality improvement. |
| `SearchResult.file_path: Path` | `SearchResult.file_paths: list[Path]` | Phase 16 | Clean break. Callers render the list themselves. |
| `INSERT ... ON CONFLICT DO UPDATE` on chunks_* | `INSERT OR IGNORE` on chunks_* + `INSERT OR IGNORE` on chunk_file_paths_* | Phase 16 | Content is immutable per id; re-indexing is strictly additive on the association side. |
| Full CREATE+COPY+DROP+RENAME for schema change | `ALTER TABLE DROP COLUMN` (SQLite ≥3.35) with rebuild fallback | Phase 16 | Deployed SQLite is 3.46.1 [VERIFIED via `sqlite3.sqlite_version`]; DROP COLUMN is faster and preserves triggers/indexes. |

**Deprecated/outdated:**

- `migration_v15.py` — its chunk_id remap is subsumed by `migration_v16.py`'s remap + collapse. See Open Questions #2 for the supersede plan.
- `delete_chunks_by_file` in `metadata.py` — replaced by M2M-aware `purge_file` in the pipeline layer.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python `sqlite3` | Migration + pipeline + trickle | ✓ | 3.12 stdlib / SQLite 3.46.1 [VERIFIED] | — |
| `ALTER TABLE DROP COLUMN` | Schema migration (Decision #6) | ✓ | SQLite 3.46.1 ≫ required 3.35.0 [CITED: sqlite.org/lang_altertable.html] | Full rebuild (CREATE + INSERT SELECT + DROP + RENAME) |
| `sqlite-vec` extension | Vector storage / collapse divergence check | ✓ | As deployed in Phase 15 container | — |
| blake3 Python binding | Chunker (already in Phase 15) | ✓ | As deployed | — |
| Docker Compose (dotmd container) | Migration is run offline with container stopped | ✓ | Per deployment memory | — |
| FalkorDB | Graph storage (no changes this phase) | ✓ | Per deployment | — |
| `pytest` | Test suite (Decision #7) | ✓ (assumed from project conventions) | — | — [ASSUMED] — verify by checking `backend/pyproject.toml` for test extras during planning. |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** `ALTER TABLE DROP COLUMN` has a rebuild fallback; never expected to be needed on 3.46.1 but defensive.

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (project convention — see `backend/pyproject.toml`) [ASSUMED — confirm during P6 planning] |
| Config file | `backend/pyproject.toml` `[tool.pytest.ini_options]` (if present) — otherwise ad-hoc |
| Quick run command | `cd backend && pytest tests/ingestion/test_migration_v16.py -x` |
| Full suite command | `cd backend && pytest tests/ -x --tb=short` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| DEDUP-01 | M2M table is created per strategy with correct PK | unit | `pytest tests/ingestion/test_migration_v16.py::test_creates_m2m_table -x` | ❌ Wave 0 |
| DEDUP-02 | `chunks_*` no longer contains `file_path` or `chunk_index` after migration | unit | `pytest tests/ingestion/test_migration_v16.py::test_drops_columns -x` | ❌ Wave 0 |
| DEDUP-03 | Collision collapse picks MIN(old_id) canonical and emits WARN on divergence > 0.01 | unit | `pytest tests/ingestion/test_migration_v16.py::test_collision_canonical_and_divergence -x` | ❌ Wave 0 |
| DEDUP-04 | Mid-strategy crash resumes from next strategy on rerun | integration | `pytest tests/ingestion/test_migration_v16.py::test_resume_after_crash -x` | ❌ Wave 0 |
| DEDUP-05 | Trickle refuses to start while `migration_v16_lock` row present | integration | `pytest tests/ingestion/test_trickle_lock.py::test_refuses_while_locked -x` | ❌ Wave 0 |
| DEDUP-06 | `--dry-run` writes nothing; `--verify-only` never mutates; `migrate status` reports state | unit | `pytest tests/ingestion/test_migration_v16_ops.py -x` | ❌ Wave 0 |
| DEDUP-07 | `INSERT OR IGNORE` is used (no more UPSERT-UPDATE on chunks_*) | unit | `pytest tests/ingestion/test_pipeline_m2m_insert.py::test_insert_or_ignore -x` | ❌ Wave 0 |
| DEDUP-08 | `_purge_file` decrements then cascade-deletes only orphans | unit | `pytest tests/ingestion/test_pipeline_purge.py::test_purge_holder_count -x` | ❌ Wave 0 |
| DEDUP-09 | `SearchResult.file_paths` is a sorted list | unit | `pytest tests/api/test_search_result_shape.py::test_file_paths_sorted -x` | ❌ Wave 0 |
| DEDUP-10 | All invariants: 64-char chunk_ids, no orphans in vec_meta_* or FTS, `UNIQUE(file_path, chunk_index)` per strategy | integration | `pytest tests/ingestion/test_migration_v16_invariants.py -x` | ❌ Wave 0 |
| DEDUP-10b | Round-trip top-K parity — same queries return same chunk_ids pre- and post-migration for non-collision chunks | property | `pytest tests/api/test_search_parity.py::test_top_k_parity -x` | ❌ Wave 0 |
| DEDUP-11 | `migration_v15` is a no-op shim that defers to v16 OR is deleted cleanly; `needs_migration_v15` returns False post-v16 | unit | `pytest tests/ingestion/test_migration_v15_superseded.py -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `pytest tests/ingestion/test_migration_v16.py -x` (the core migration tests, < 30 s with in-memory SQLite fixtures)
- **Per wave merge:** `pytest tests/ -x --tb=short`
- **Phase gate:** Full suite green on a sample database that includes:
  - at least one empty strategy (no rows),
  - at least one strategy with known collisions (fixture built from CONTEXT.md real-world: pytest boilerplate + skill copies + symlinks),
  - at least one strategy with no collisions at all.

### Wave 0 Gaps

- [ ] `tests/ingestion/test_migration_v16.py` — core migration unit tests (DEDUP-01/02/03/04)
- [ ] `tests/ingestion/test_migration_v16_ops.py` — dry-run / verify-only / status modes (DEDUP-06)
- [ ] `tests/ingestion/test_migration_v16_invariants.py` — post-migration invariants (DEDUP-10)
- [ ] `tests/ingestion/test_trickle_lock.py` — advisory lock interaction (DEDUP-05)
- [ ] `tests/ingestion/test_pipeline_m2m_insert.py` — INSERT OR IGNORE behaviour (DEDUP-07)
- [ ] `tests/ingestion/test_pipeline_purge.py` — holder-count purge logic (DEDUP-08)
- [ ] `tests/api/test_search_result_shape.py` — `file_paths` field shape (DEDUP-09)
- [ ] `tests/api/test_search_parity.py` — round-trip top-K property test (DEDUP-10b)
- [ ] `tests/ingestion/test_migration_v15_superseded.py` — v15 behaviour after v16 ships (DEDUP-11)
- [ ] `tests/conftest.py` — shared fixture for building a collision-rich index.db from CONTEXT.md scenarios (pytest cache dupes, mirrored skills, symlinks, repeated headings in one file)
- [ ] Confirm pytest config in `backend/pyproject.toml`; if absent, add a minimal `[tool.pytest.ini_options]` section.

## Security Domain

`security_enforcement` is not explicitly set in `.planning/config.json` for this phase (assumed enabled per default). However, Phase 16 is a pure internal schema migration with no authentication, session management, access control, or network-exposed surface changes. All operations are on a single-user local database inside a container that already runs as the sole writer.

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no | N/A — dotmd runs unauthenticated on localhost (single-user per `feedback_security_threat_model.md`) |
| V3 Session Management | no | N/A |
| V4 Access Control | no | N/A — single operator |
| V5 Input Validation | yes (limited) | Pydantic models for `SearchResult`, `Chunk`; parameterised SQL (no f-string interpolation of user data — only table names, which are from `settings.chunk_strategy`) |
| V6 Cryptography | yes (low) | blake3 for content addressing; cosine for divergence. No secret crypto. |
| V7 Error Handling / Logging | yes | Structured logs tagged `dotmd-migrate` per Decision #7; divergence WARN logged but never aborts |
| V8 Data Protection | yes (low) | `shutil.copy2(index.db, index.db.v16-backup)` before migration — verified pattern from `migration_v15.py` |
| V12 File / Resource | no | N/A — no user-uploaded content in migration path |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| SQL table-name injection via `chunk_strategy` string | Tampering | `chunk_strategy` is operator-controlled in `Settings`, never user-supplied via the API. Pattern "f-string the table name, `?` parameterize the values" is already the project convention (see `metadata.py` lines 22–58). Maintain it. |
| Partial migration corrupting data | Denial of service / Data loss | Pre-migration backup + per-strategy transaction + resume marker + advisory lock |
| Trickle writes mid-migration | Data corruption | Advisory lock (Pattern 2). Trickle refuses to start. |
| Divergent vectors silently collapsed | Data integrity | WARN on cosine > 0.01; operator reviews logs; migration continues (Decision #4 locks non-abort behaviour) |

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | REQUIREMENTS.md will not be updated with formal `DEDUP-*` IDs before planning begins; my derived IDs above will be adopted | §Phase Requirements | Low — IDs are naming conventions; planner can rename to match user choice. |
| A2 | `pytest` is the test framework and is configured in `backend/pyproject.toml` | §Validation Architecture | Medium — if a different framework is used (e.g., unittest), test commands change. Verify during P6 planning with `grep -n "pytest\|unittest" backend/pyproject.toml`. |
| A3 | TEI runs on CPU (per `hardware_cpu_limits.md` memory — "AVX but NOT AVX2") and therefore has bounded vector divergence ≤ 0.01 between runs on identical text | §Common Pitfalls 4 | Low — threshold is configurable; operator tunes if WARN rate is excessive. |
| A4 | BM25 pickle `~/.dotmd/bm25_index.pkl` is dead legacy code (FTS5 replaced it in Phase 12) | §Runtime State Inventory | Low — inventory item only. Verify during P6; if pickle is still live code, add it to the purge audit. |
| A5 | `~/.dotmd/` is overridden to a Docker volume path (`/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db`) in production; all code paths resolve `settings.index_dir` consistently | §Architecture Patterns | Low — Phase 15 migration already operated against this path successfully. |
| A6 | `security_enforcement` is enabled by default (the flag is not explicitly present in `.planning/config.json` for this phase) | §Security Domain | Low — included the section defensively; operator can trim if flag is explicit. |
| A7 | The `migration_v16_lock` table does NOT conflict with an existing name (none found in grep of `src/`) | §Architecture Patterns (Pattern 2) | Low — grep verified no current table named `migration_v16_lock`. |

## Open Questions

1. **Where does the `_purge_file_m2m` logic live?**
   - What we know: Current `_purge_file` is in `pipeline.py:1053–1070`. It calls `metadata.delete_chunks_by_file`, `vector_store.delete_vectors_by_chunk_ids`, `keyword_engine.remove_chunks`, `graph_store.delete_file_subgraph`, `chunk_tracker.remove_fingerprint`, `embed_tracker.remove_fingerprint`.
   - What's unclear: whether to extract the new "decrement + cascade" logic into a helper in `metadata.py` (cleaner boundary) or keep orchestration in `pipeline.py` with a new `metadata.delete_m2m_for_file` primitive.
   - Recommendation: Keep orchestration in pipeline.py (matches current shape); expose two new metadata primitives: `delete_m2m_for_file(file_path) -> list[orphan_chunk_ids]` and `delete_orphan_chunks(chunk_ids)`. Pipeline does the cross-store cascade using the returned orphan list. This matches CONTEXT's P4 plan.

2. **What happens to `migration_v15.py` when v16 ships?**
   - What we know: `migration_v15.py` is currently blocked (collision-blocked) and, per the phase Goal, is "superseded by Phase 16's schema migration." STATE.md still marks v15 as "In Progress 2/3."
   - What's unclear: Is v15 deleted from the tree once v16 ships, or left as a no-op stub that logs "handled by migration_v16" and exits?
   - Recommendation: Keep v15 as a minimal stub for one release cycle:
     ```python
     def needs_migration_v15(index_db_path: Path) -> bool:
         # Superseded by migration_v16, which performs blake3 remap + dedup.
         return False
     def run_migration_v15(*_args, **_kwargs) -> None:
         logger.info("migration_v15 superseded by migration_v16 — no-op")
     ```
     This lets any ops runbook that still references v15 fail gracefully. Delete entirely in a later phase once confident no references remain.

3. **Does `Chunk.file_path` need the same clean-break treatment as `SearchResult.file_path`?**
   - What we know: `core/models.py:78` `Chunk.file_path: Path` is used by the chunker during ingestion (chunks emitted per-file, so each chunk has exactly one source file at creation time).
   - What's unclear: Should `Chunk` keep `file_path: Path` (one at creation) or gain `file_paths: list[Path]` (for read-back after dedup)?
   - Recommendation: Keep two shapes — the "transient" `Chunk` emitted by the chunker has `file_path` (singular, creation-time), and the "hydrated" chunk returned from storage has `file_paths` (plural, read-time). Either use two Pydantic models (`ChunkInput` and `ChunkStored`) or keep one model with `file_paths: list[Path]` and have the chunker wrap its single source in a one-element list. The latter is simpler — prefer it unless the planner sees a shape-mismatch issue.

4. **Is `chunks_*.char_offset` per-file or per-content?**
   - What we know: `char_offset` is stored on `chunks_*` (metadata.py:29) and describes where in the source markdown the chunk begins.
   - What's unclear: Two files with identical content could legitimately have different `char_offset`s (e.g., A has the dup chunk at offset 1024, B has it at offset 512). If so, `char_offset` should move to the M2M table; if not, it's a per-content property and stays on `chunks_*`.
   - Recommendation: **Move `char_offset` to the M2M table**, making its PK `(chunk_id, file_path, chunk_index, char_offset)` — or more cleanly, add char_offset as a non-PK column on M2M and keep PK as `(chunk_id, file_path, chunk_index)`. This is a minor correction to the CONTEXT schema (which silently assumed char_offset stays on `chunks_*`); flag for confirmation in `/gsd:discuss-phase 16 revise`.

5. **Does `purge_orphaned_files` need a rewrite, or does Decision-#6's startup-lock-check make it moot?**
   - What we know: `purge_orphaned_files` (pipeline.py:1068 area) runs at trickle startup to scan ALL `chunks_*` tables for file_paths no longer on disk.
   - What's unclear: After migration, `chunks_*` no longer has `file_path` — the scan must shift to `chunk_file_paths_*`. This is an obvious mechanical update but might interact with the orphan-cleanup commit from 2026-04-24 (bb79455) that extended orphan cleanup across all strategies.
   - Recommendation: P4's scope should explicitly include updating `purge_orphaned_files` to scan `chunk_file_paths_*`, then reuse the new "decrement + cascade" primitive per file_path. Verify commit bb79455's test coverage still applies.

## Sources

### Primary (HIGH confidence)

- [CODEBASE] `backend/src/dotmd/storage/metadata.py` lines 17–100 — current chunks_* schema and UPSERT semantics
- [CODEBASE] `backend/src/dotmd/storage/sqlite_vec.py` lines 85–110 — vec_meta_* schema
- [CODEBASE] `backend/src/dotmd/search/fts5.py` lines 10–22, 152, 170 — chunks_fts_* schema and DELETE-by-chunk_id pattern
- [CODEBASE] `backend/src/dotmd/ingestion/migration_v15.py` full file — precedent for resumable migration + state table + backup flow
- [CODEBASE] `backend/src/dotmd/ingestion/pipeline.py` lines 1040–1080 — current `_purge_file`
- [CODEBASE] `backend/src/dotmd/ingestion/trickle.py` lines 260–280, 360–370 — how trickle currently calls `_purge_file`
- [CODEBASE] `backend/src/dotmd/core/models.py` lines 73–95, 126–135 — `Chunk` and `SearchResult` Pydantic models
- [CODEBASE] `backend/src/dotmd/api/service.py` lines 178–290 — search pipeline (unchanged by this phase except result shape)
- [CODEBASE] `backend/src/dotmd/cli.py` line 112, 161 — file_path display and status query sites
- [CODEBASE] `backend/src/dotmd/mcp_server.py` line 118 — MCP `"file_path"` emission
- [CONTEXT] `.planning/phases/16-.../16-CONTEXT.md` — all 7 locked decisions with rationales
- [CITED] https://www.sqlite.org/lang_altertable.html#otheralter — ALTER TABLE DROP COLUMN added in SQLite 3.35.0
- [VERIFIED] `python3 -c "import sqlite3; sqlite3.sqlite_version"` → `3.46.1` locally

### Secondary (MEDIUM confidence)

- Memory `hardware_cpu_limits.md` — CPU-only TEI deployment (AVX, no AVX2) supports the assumption that cosine divergence on identical text will be small.
- Memory `dotmd_deployment.md` — Docker on port 8321, sqlite-vec + FalkorDB, TEI mandatory.
- Memory `project_v14_milestone.md` — v1.4 context, Phase 12 two-dimensional storage pattern still governs per-strategy × per-model tables.
- Commit `bb79455` — orphan cleanup scans ALL `chunks_*` strategies (relevant for P4's `purge_orphaned_files` rewrite).

### Tertiary (LOW confidence)

- pytest as test framework — assumed from Python project conventions; not verified against `backend/pyproject.toml` in this research. **Flag A2.**

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH — all components are already deployed and verified; no new libraries.
- Architecture: HIGH — schema locked by CONTEXT.md; touchpoints verified by direct code inspection.
- Pitfalls: HIGH — each pitfall maps to a specific code location audited above.
- Security: HIGH — single-user localhost, no network surface change; ASVS categories conservatively ticked for V5, V7, V8.
- Validation: MEDIUM — test framework assumed (A2), but test-plan coverage maps cleanly to CONTEXT Decision #7.
- Open questions: MEDIUM — five open items flagged for `/gsd:discuss-phase 16 revise` or Claude's discretion.

**Research date:** 2026-04-24
**Valid until:** 2026-05-24 (30 days — stable phase, only mechanical drift expected from continued Phase 15 operation producing more dedup-eligible groups).
