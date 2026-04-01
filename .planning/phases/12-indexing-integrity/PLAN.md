# Phase 12: Indexing Integrity Rework

## Goal

Eliminate orphaned data, prevent parallel indexing corruption, enable safe
multi-model and multi-strategy experimentation without data loss.

## Established Facts

- chunk_id = `md5(file_path:chunk_index)` -- deterministic, NOT UUID
- Multi-model already works: E5 and Qwen3 vec tables reference same chunk_ids
- 241K chunks in metadata, ~3K valid, ~238K orphans from old indexing_paths
- Full indexing = tens of hours at 600% CPU (Xeon E3 V2, no AVX2)
- Indexes = data (not cache). Loss = hours of recompute.
- Single user/developer, Docker, no backward compat obligations
- Context-aware encoding = dead code, not used

## Architecture: Two-Dimensional Table Naming

Everything keyed by `(chunk_strategy, embedding_model)`:

```
index.db (single unified SQLite database):
  chunks_{strategy}                          -- chunk text + metadata
  chunks_fts_{strategy}                      -- FTS5 keyword index
  chunk_fingerprints_{strategy}              -- "file has been chunked?"
  embed_fingerprints_{strategy}_{model}      -- "file has been embedded?"
  vec_chunks_{strategy}_{model}              -- vec0 virtual table
  vec_meta_{strategy}_{model}                -- chunk_id + text_hash column
  vec_config_{strategy}_{model}              -- model name, distance metric
  stats                                      -- shared, strategy-independent

graphdb_{strategy}   -- separate file (LadybugDB/FalkorDB)
indexing.lock        -- flock, process-level exclusive lock
```

### Key Design Decisions

1. **Unified database**: metadata.db + vec.db merged into index.db.
   One WAL, one transaction scope, simple JOINs for text_hash lookup.
   sqlite-vec extension loaded always (search needs it).

2. **Chunks are strategy-specific, NOT shared**. Different strategies produce
   different chunk boundaries. Each strategy gets its own chunks table.
   chunk_id stays `md5(file_path:chunk_index)` -- strategy encoded in TABLE NAME.

3. **Vec tables are (strategy, model)-specific**. Prevents collision when
   two strategies share one model (same chunk_index, different text).

4. **Graph is per-strategy**. Section nodes reference chunk_ids which are
   strategy-specific. Shared graph would accumulate nodes from multiple strategies.

5. **No reset_all()**. Cannot destroy all data in one operation.
   Only per-model and per-strategy granular drops.

6. **Two FileTrackers** per pipeline instance:
   - `chunk_tracker` on `chunk_fingerprints_{strategy}` -- "file chunked?"
   - `embed_tracker` on `embed_fingerprints_{strategy}_{model}` -- "file embedded?"
   Enables: change model → skip chunking (hours). Change strategy → re-chunk + re-embed.

7. **Embedding reuse via text_hash** column in vec_meta. When switching strategy,
   lookup by content hash before encoding. Same text + same model = reuse vector.
   Assumption: flat encoding only (context-aware code removed).

---

## Phase 0: Lock Module

**New file**: `backend/src/dotmd/ingestion/lock.py`

```python
@contextmanager
def indexing_lock(index_dir: Path):
    lock_path = index_dir / "indexing.lock"
    fd = None
    try:
        fd = open(lock_path, "w")
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        if fd is not None:
            fd.close()
        raise IndexingLockError("Indexing already in progress. Stop the server first.")
    try:
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        fd.close()
```

- `IndexingLockError` in `core/exceptions.py`
- Lock on: `TrickleIndexer.run()` (entire session), `pipeline.index()`,
  `reindex_*()`, `drop_vectors()`, `drop_chunks()`

---

## Phase 1: Data Model

### 1.1: Unified Database

Merge metadata.db + vec.db → index.db.

**Changes:**
- `SQLiteVecVectorStore.__init__`: accept connection instead of path, or accept
  same path as metadata store
- `SQLiteMetadataStore.__init__`: load sqlite-vec extension on shared connection
- `Settings`: remove `sqlite_vec_path` property, `sqlite_path` → `index_db_path`
- All stores share one `sqlite3.Connection`

**Benefits:** one WAL, one VACUUM, simple JOINs, atomic transactions across stores.

### 1.2: Chunk Versioning

**New setting:**
```toml
chunk_strategy = "heading_512_50"
```

**Tables:** `chunks_{strategy}`, `chunks_fts_{strategy}`

**Code changes:**
- `Settings`: add `chunk_strategy: str = "heading_512_50"`
- `IndexingPipeline.__init__`: derive chunk table names from strategy
- `SQLiteMetadataStore`: accept table name parameter (currently hardcoded `chunks`)
- `FTS5SearchEngine.__init__`: accept table name parameter (currently hardcoded `chunks_fts`)
- `SQLiteMetadataStore.delete_all()`: use parameterized table name (currently hardcodes `chunks_fts`)
- chunk_id = `md5(file_path:chunk_index)` -- NO CHANGE

### 1.3: Two-Dimensional Vec + Fingerprints

**Vec tables:** `vec_chunks_{strategy}_{model}`, `vec_meta_{strategy}_{model}`, `vec_config_{strategy}_{model}`

**Fingerprints split -- two FileTracker instances:**
- `chunk_tracker = FileTracker(conn, table_name=f"chunk_fingerprints_{strategy}")`
- `embed_tracker = FileTracker(conn, table_name=f"embed_fingerprints_{strategy}_{model}")`

**Pipeline flow (updated):**
```
For each file:
  1. chunk_diff = chunk_tracker.diff(files)
     → new/modified:
       a. purge old data (FTS5, graph, current vec — but NOT chunks yet)
       b. re-chunk → save_chunks (UPSERT — overwrites old chunks with same IDs)
       c. add to FTS5 + graph
       d. save chunk_fingerprint  ← saved HERE, before embed (crash-safe split point)
       e. text_hash lookup → encode → save to vec
       f. save embed_fingerprint
     → unchanged in chunk_diff:
       g. embed_diff = embed_tracker.diff(files)
       → new/modified → fetch chunks from DB → text_hash lookup → encode → save to vec
       → save embed_fingerprint
```

**Key ordering:** embedding happens INSIDE the chunk step (after save_chunks),
not as a separate pass. This ensures chunks exist in DB when embed phase reads them.

**Crash recovery:** If crash after save_chunks but before embed:
chunk_fp saved → chunk_diff says "unchanged". embed_fp NOT saved → embed_diff
says "new" → only embedding runs (step f). Correct behavior.

### 1.4: Suffix Fix

In `_model_to_table_suffix()`:
- Delete `_LEGACY_MODELS` set
- Do NOT strip version/size suffix (fix collision: `Qwen3-0.6B` vs `Qwen3-1.5B`)
- All models get a suffix, no exceptions
- **Verify migration consistency:** new function must produce `_multilingual_e5_large`
  for `intfloat/multilingual-e5-large` and `_qwen3_embedding` for Qwen3-Embedding
  (matching existing table names). Add unit test asserting known model→suffix mappings.

### 1.5: Reset (No reset_all)

**`pipeline.drop_vectors(strategy, model)`:**
- DROP vec_chunks_{strategy}_{model} + vec_meta + vec_config
- DELETE FROM embed_fingerprints_{strategy}_{model}

**`pipeline.drop_chunks(strategy)`:**
- DROP chunks_{strategy}, chunks_fts_{strategy}
- DELETE FROM chunk_fingerprints_{strategy}
- **CASCADE**: also drop ALL vec_*_{strategy}_* tables and embed_fp_{strategy}_* tables
  (iterate sqlite_master WHERE name LIKE pattern)
- DELETE graphdb_{strategy} file
- Log: "Dropped strategy {strategy}: N vec tables, M chunks"

**`_full_index` (--force):**
- `drop_vectors(current_strategy, current_model)`
- `chunk_tracker.clear()` (fingerprints only, chunks stay for UPSERT)
- `embed_tracker.clear()` (must also clear — otherwise embed_diff says "unchanged" after vec drop)
- Rebuild FTS5: `DELETE FROM chunks_fts_{strategy}` before re-indexing.
  NOTE: verify at implementation whether current `INSERT OR REPLACE` in fts5.py
  actually prevents duplicates for FTS5 content tables. If it does, this DELETE
  is redundant but harmless. If not, it's required.
- Run incremental → all files appear as "new" in both diffs → re-chunk (UPSERT) + FTS5 INSERT + re-embed

**CLI:**
- `dotmd reset --model <name>` → calls drop_vectors for current strategy + named model
- `dotmd reset --strategy <name>` → calls drop_chunks (with cascade)
- Both: `click.confirm("This will delete ... Continue?")` before execution
- Remove `dotmd clear` command entirely

**REST API:** remove `/clear` endpoint.

### 1.6: Embedding Reuse via text_hash

**vec_meta_{strategy}_{model}** gets new column: `text_hash TEXT`

**Flow in pipeline._embed_chunks():**
```python
# 1. Compute text_hash for each chunk
hashes = {chunk.chunk_id: md5(chunk.text) for chunk in chunks}

# 2. Lookup existing embeddings (same model, ANY strategy)
# Dynamic UNION: discover all vec_meta_*_{model} tables via sqlite_master,
# then UNION ALL their (text_hash, embedding) pairs.
# Helper: _find_vec_meta_tables(conn, model_suffix) -> list[str]
tables = _find_vec_meta_tables(conn, model_suffix)
existing = UNION ALL: SELECT text_hash, embedding FROM {t} WHERE text_hash IN (?)
           for t in tables

# 3. Split: hits (reuse) vs misses (compute)
# 4. encode_batch(misses)
# 5. Merge and save all to vec_meta_{current_strategy}_{model}
```

**Note:** `_find_vec_meta_tables()` queries `sqlite_master WHERE name LIKE
'vec_meta_%_{model_suffix}'`. This is the same introspection pattern used by
`drop_chunks()` cascade and `dotmd status --verbose`.

**Metrics (logged per batch):**
```
[run_id] embed: 3000 chunks, 2400 cache hits (80.0%), 600 computed,
         estimated ~18.2h saved, cache entries: 3200
```

**Assumption:** flat encoding only (context-aware code removed in 1.7).
Comment in code documenting this.

**Eviction:** `drop_vectors(strategy, model)` drops the vec_meta table →
embeddings for that (strategy, model) pair gone. Embeddings in other
strategy's vec_meta remain as potential reuse source.

### 1.7: Remove Dead Context-Aware Code

Delete from codebase:
- `context_embedding_model` from `Settings` (config.py)
- `encode_batch_context()` from `SemanticSearchEngine` (semantic.py)
- `has_context_model` property (semantic.py)
- `unload_context_model()` (semantic.py) + all call sites in pipeline.py
- `_group_chunks_by_file()` helper (pipeline.py)
- Context branch in `_embed_chunks()` (pipeline.py)

After cleanup:
```python
def _embed_chunks(self, chunks):
    return self._semantic_engine.encode_batch([c.text for c in chunks])
```

---

## Phase 2: Orphan Cleanup (Trickle Startup)

**Order in `TrickleIndexer.run()`:**
1. Acquire lock
2. `PRAGMA integrity_check` (early corruption detection)
3. Orphan cleanup:
   a. Discover files (indexing_paths + indexing_exclude)
   b. `SELECT DISTINCT file_path FROM chunks_{strategy}`
   c. orphans = stored_paths - discovered_paths
   d. For each orphan file_path batch (100 per txn):
      - Get chunk_ids → DELETE from chunks_fts_{strategy}
      - DELETE vectors: for each vec_meta_*_{model} table (via sqlite_master),
        DELETE WHERE chunk_id IN (orphan chunk_ids). Prevents dangling vectors
        for files that no longer exist.
      - DELETE from chunks_{strategy}
      - DELETE graph subgraph via graphdb_{strategy}
   e. Log: "Orphan cleanup: removed N files (M chunks, V vectors)"
4. Process backlog (existing logic)
5. Watch mode

**VACUUM at idle:** if cleanup deleted anything → `_needs_vacuum = True` →
first idle poll in watch mode → VACUUM → reset flag.

**Watchdog `on_deleted` handler:**
Add `on_deleted` to `_MarkdownEventHandler`. When a .md file is deleted:
1. Enqueue path to `_file_queue` with a `deleted=True` flag (or separate queue)
2. In watch mode loop: detect deleted paths → call `_purge_file(path)`
3. Same debounce (2s) as created/modified events
4. `_purge_file` handles all stores: chunks, FTS5, graph, vec, fingerprints

---

## Phase 3: Safety Wiring

### 3.1: Lock on All Write Paths

| Method | Lock scope |
|--------|-----------|
| `TrickleIndexer.run()` | Entire session |
| `IndexingPipeline.index()` | Duration of index |
| `IndexingPipeline.reindex_*()` | Duration of reindex |
| `IndexingPipeline.drop_vectors()` | Duration of drop |
| `IndexingPipeline.drop_chunks()` | Duration of drop |

CLI catches `IndexingLockError` → `"Indexing already in progress. Stop the server first."` + exit(1).

**Tradeoff (documented):** Trickle holds lock for entire session → CLI
`dotmd index/reindex/reset` cannot run while server is running. This is
intentional: to run --force or reset, stop the container first. Document
in CLI --help text.

### 3.2: CLI Changes

```
dotmd index <dir> [--force] [--extract-depth ner|structural]
dotmd search <query> [--top N] [--mode hybrid|semantic|keyword|graph]
dotmd status [--verbose]           # --verbose: show models, strategies, table sizes
dotmd reindex {vectors,fts5,graph,all}
dotmd reset --model <name>         # drop vectors + embed_fp for current strategy + named model
dotmd reset --strategy <name>      # drop chunks + FTS5 + graph + ALL vec for named strategy
dotmd serve [--host] [--port]
dotmd mcp
```

Removed: `dotmd clear`

**`status()` change detection:** uses `chunk_tracker` (not embed_tracker) for
file diff in `DotMDService.status()`. Chunk tracker reflects whether files
have been processed at all, which is the user-facing question.

**Discovery:** `dotmd status --verbose` queries `sqlite_master` for all
`chunks_*`, `vec_chunks_*`, `embed_fingerprints_*` tables and shows:
```
Strategies:
  heading_512_50: 2990 chunks, 440 files, graph: 16MB

Models per strategy:
  heading_512_50 / multilingual_e5_large: 2990 vectors, text_hash: 100%
  heading_512_50 / qwen3_embedding: 2971 vectors, text_hash: 100%
```

### 3.3: REST API

Remove `/clear` endpoint. All other endpoints unchanged.
`/index` with `force=True` still works (goes through pipeline with lock).

---

## Phase 4: One-Time Migration

**Detection:** if table `chunks` (no suffix) exists in metadata.db → run migration.
If not → skip (already migrated or fresh install).

### Step 1: Orphan Cleanup (in old schema)
```sql
-- metadata.db
DELETE FROM chunks WHERE file_path NOT IN ({discovered_files})
```

### Step 2: Create Unified index.db
```python
# Create new index.db with sqlite-vec extension loaded
conn = sqlite3.connect(index_dir / "index.db")
conn.enable_load_extension(True)
conn.load_extension("vec0")  # or however sqlite-vec is loaded
```

### Step 3: Copy Metadata Tables to index.db
```sql
ATTACH '{metadata_db_path}' AS meta_old;

-- Regular tables: copy + rename
CREATE TABLE chunks_heading_512_50 AS SELECT * FROM meta_old.chunks;
-- chunk_fingerprints: derive from ACTUAL chunked files, not model-specific fp.
-- Any file that has chunks in the table HAS been chunked.
CREATE TABLE chunk_fingerprints_heading_512_50 (
    file_path TEXT PRIMARY KEY, mtime REAL NOT NULL,
    size_bytes INTEGER NOT NULL, checksum TEXT NOT NULL, indexed_at TEXT NOT NULL
);
INSERT INTO chunk_fingerprints_heading_512_50
    SELECT DISTINCT c.file_path,
        COALESCE(e5.mtime, q3.mtime) AS mtime,
        COALESCE(e5.size_bytes, q3.size_bytes) AS size_bytes,
        COALESCE(e5.checksum, q3.checksum) AS checksum,
        COALESCE(e5.indexed_at, q3.indexed_at) AS indexed_at
    FROM meta_old.chunks c
    LEFT JOIN meta_old.file_fingerprints_multilingual_e5_large e5
        ON c.file_path = e5.file_path
    LEFT JOIN meta_old.file_fingerprints_qwen3_embedding q3
        ON c.file_path = q3.file_path
    WHERE e5.file_path IS NOT NULL OR q3.file_path IS NOT NULL;
-- COALESCE across ALL model fingerprint tables maximizes coverage:
-- files indexed by Qwen3 but not E5 still get chunk_fingerprints.
-- Files in chunks but NOT in ANY fingerprint table (e.g., mid-run crash)
-- will have no chunk_fingerprint → trickle re-processes on next run.
-- Safe: UPSERT for chunks, re-embed for vec.
CREATE TABLE embed_fingerprints_heading_512_50_multilingual_e5_large AS
    SELECT * FROM meta_old.file_fingerprints_multilingual_e5_large;
CREATE TABLE stats AS SELECT * FROM meta_old.stats;

-- FTS5: create new + populate
CREATE VIRTUAL TABLE chunks_fts_heading_512_50 USING fts5(
    chunk_id UNINDEXED, text, tokenize = 'unicode61'
);
INSERT INTO chunks_fts_heading_512_50(chunk_id, text)
    SELECT chunk_id, text FROM meta_old.chunks_fts;

DETACH meta_old;
```

### Step 4: Copy Vec Tables to index.db (via shadow tables)
```sql
ATTACH '{vec_db_path}' AS vec_old;

-- For each model (E5, Qwen3):
-- 1. Create new vec_meta with text_hash column
CREATE TABLE vec_meta_heading_512_50_multilingual_e5_large (
    rowid INTEGER PRIMARY KEY AUTOINCREMENT,
    chunk_id TEXT NOT NULL,
    text_hash TEXT
);
INSERT INTO vec_meta_heading_512_50_multilingual_e5_large(rowid, chunk_id)
    SELECT rowid, chunk_id FROM vec_old.vec_meta_multilingual_e5_large;

-- 2. Populate text_hash from chunks (md5 not built into SQLite — use Python)
-- Register UDF: conn.create_function("md5_hash", 1, lambda t: hashlib.md5(t.encode()).hexdigest())
-- Then:
UPDATE vec_meta_heading_512_50_multilingual_e5_large SET text_hash = (
    SELECT md5_hash(text) FROM chunks_heading_512_50
    WHERE chunk_id = vec_meta_heading_512_50_multilingual_e5_large.chunk_id
);

-- 3. Copy vec0 shadow tables (rowids, vector data)
-- NOTE: vec0 virtual tables use backing tables: _info, _chunks, _rowids, _vector_chunks00
-- Create new vec0 table, then INSERT from shadow tables
CREATE VIRTUAL TABLE vec_chunks_heading_512_50_multilingual_e5_large
    USING vec0(embedding float[{dim}]);
-- Copy vector data via shadow tables
INSERT INTO vec_chunks_heading_512_50_multilingual_e5_large(rowid, embedding)
    SELECT rowid, embedding
    FROM vec_old.vec_chunks_multilingual_e5_large_rowids r
    JOIN vec_old.vec_chunks_multilingual_e5_large_vector_chunks00 v ON ...;
-- NOTE: vec0 shadow table access needs SPIKE before implementation.
-- sqlite-vec shadow tables (_rowids, _vector_chunks00, _info, _chunks)
-- are internal implementation details and may not support direct SELECT.
-- SPIKE: verify with `SELECT rowid, embedding FROM vec_chunks_*` on current DB.
--
-- FALLBACK STRATEGY (if shadow tables inaccessible):
--   1. Create new vec0 table with correct name
--   2. For each chunk in chunks_{strategy}: encode via TEI → insert into new vec
--   3. TEI must be running during migration (container up)
--   4. For ~3000 chunks this is ~40 minutes on CPU TEI, not hours
--   5. Migration code: try shadow path first, catch exception → fallback
--
-- Implementation:
-- try:
--     copy_vec_via_shadow_tables(old_table, new_table)
-- except Exception:
--     logger.warning("Shadow table copy failed, falling back to re-embed")
--     re_embed_from_chunks(chunks_table, new_vec_table, model)

-- 4. Copy vec_config
CREATE TABLE vec_config_heading_512_50_multilingual_e5_large AS
    SELECT * FROM vec_old.vec_config_multilingual_e5_large;

-- Repeat for Qwen3

DETACH vec_old;
```

### Step 5: Graph Rename
```bash
mv {index_dir}/graphdb {index_dir}/graphdb_heading_512_50
```

### Step 6: Cleanup
```bash
rm {index_dir}/metadata.db metadata.db-wal metadata.db-shm
rm {index_dir}/vec.db vec.db-wal vec.db-shm
```

### Step 7: VACUUM (deferred to idle)

Migration is idempotent: if `chunks` table without suffix doesn't exist → skip.

---

## Updated _purge_file Cascade

```python
def _purge_file(self, file_path: str) -> None:
    # 1. Get chunk_ids from chunks_{strategy}
    chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)

    # 2. Delete from FTS5 (must be before chunk deletion — needs chunk_ids)
    if chunk_ids:
        self._keyword_engine.remove_chunks(chunk_ids)

    # 3. Delete from current model's vec (must be before chunk deletion — needs chunk_ids)
    if chunk_ids:
        self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)

    # 4. Delete from chunks (metadata)
    self._metadata_store.delete_chunks_by_file(file_path)

    # 5. Delete from graph
    self._graph_store.delete_file_subgraph(file_path)

    # 6. Delete from chunk_fingerprints (current strategy)
    self._chunk_tracker.remove_fingerprint(file_path)

    # 7. Delete from embed_fingerprints (current strategy+model ONLY)
    #    Other models' embed_fp not touched — they'll see "new/modified"
    #    on their next embed_diff and re-embed. This is correct:
    #    purge runs under one (strategy, model) pair, other pairs
    #    self-heal on next pipeline run.
    self._embed_tracker.remove_fingerprint(file_path)
```

**Design choice (purge scope):** `_purge_file` only cleans the CURRENT
(strategy, model) pair's vec + fingerprints. Other models' data for this file
becomes stale but is NOT deleted — it self-heals when that model's pipeline
runs next (embed_diff detects "modified" → re-embed). This avoids needing to
discover all model tables during every purge.

**Asymmetry with orphan cleanup (intentional):** Startup orphan cleanup
(Phase 2) is MORE thorough — it iterates ALL vec_meta tables and deletes
orphan chunk_ids across all models. This is correct: orphan cleanup runs once
at startup (cheap to iterate), while `_purge_file` runs per-file during
indexing (must be fast). Files deleted via watchdog `on_deleted` get
current-model cleanup immediately; other models' stale vectors survive until
next trickle restart. Acceptable tradeoff for single-user system.

---

## Updated Pipeline Flow

```
index_file(file_info):
  chunk_diff = chunk_tracker.diff([file_info])
  needs_embed = False

  if file in chunk_diff.new or chunk_diff.modified:
      # --- Chunk phase ---
      # Purge old derived data (FTS5, graph, current vec) but NOT chunks
      # (chunks overwritten by UPSERT with same deterministic IDs)
      old_chunk_ids = metadata.get_chunk_ids_by_file(file_path)
      if old_chunk_ids:
          fts5.remove_chunks(old_chunk_ids)
          vector_store.delete_vectors_by_chunk_ids(old_chunk_ids)
          graph.delete_file_subgraph(file_path)

      chunks = chunk_file(...)
      save_chunks(chunks)          # UPSERT — safe with deterministic IDs
      fts5.add_chunks(chunks)
      populate_graph(chunks)
      chunk_tracker.save_fingerprint(file_path)
      needs_embed = True           # new chunks → must embed

  if not needs_embed:
      # File not re-chunked. Check if embedding needed (e.g., new model).
      embed_diff = embed_tracker.diff([file_info])
      needs_embed = file in embed_diff.new or embed_diff.modified

  if needs_embed:
      # --- Embed phase ---
      # Chunks guaranteed to exist in DB (saved above, or from previous run)
      chunks = metadata.get_chunks_by_file(file_path)
      text_hashes = {c.chunk_id: md5(c.text) for c in chunks}
      existing = lookup_text_hash_embeddings(text_hashes, model)
      to_encode = [c for c in chunks if text_hashes[c.chunk_id] not in existing]
      new_embeddings = encode_batch(to_encode)
      save_all_vectors(chunks, merge(existing, new_embeddings), text_hashes)
      embed_tracker.save_fingerprint(file_path)
```

**Crash recovery (precise):**
- Crash after save_chunks + chunk_fp, before embed →
  next run: chunk_diff="unchanged", embed_diff="new" → only embed runs ✓
- Crash after save_chunks, before chunk_fp saved →
  next run: chunk_diff="new" → UPSERT re-chunks (idempotent, no data loss,
  just redundant work) + re-embed ✓
- Crash before save_chunks → nothing saved → full re-process ✓

---

## Dependency Graph

```
Phase 0: Lock (independent, no prerequisites)

Phase 1.1: Unified DB        ─┐
Phase 1.2: Chunk versioning   │
Phase 1.3: 2D vec/fp          ├─ Code changes (parallelizable within phase)
Phase 1.4: Suffix fix         │
Phase 1.5: Reset commands      │
Phase 1.6: text_hash reuse    │
Phase 1.7: Dead code removal  ─┘

Phase 4: Migration (needs ALL of Phase 1 code in place)

Phase 2: Orphan cleanup (runs on migrated data, needs Phase 0 lock)

Phase 3: Safety wiring (needs Phase 0 + Phase 1.5)
```

---

## Files Changed (estimated)

| File | Changes |
|------|---------|
| `ingestion/lock.py` | NEW |
| `core/exceptions.py` | Add IndexingLockError |
| `core/config.py` | Add chunk_strategy, remove context_embedding_model, update paths |
| `core/models.py` | Add fields to IndexStats for verbose status |
| `ingestion/pipeline.py` | Major: two trackers, drop_vectors, drop_chunks, text_hash flow, remove context code |
| `ingestion/trickle.py` | Lock, orphan cleanup, VACUUM at idle, on_deleted handler |
| `ingestion/file_tracker.py` | No changes (already supports custom table_name) |
| `ingestion/chunker.py` | No changes |
| `storage/metadata.py` | Parameterize table names, update delete_all |
| `storage/sqlite_vec.py` | Accept shared connection, text_hash column, reuse lookup |
| `search/fts5.py` | Parameterize table name |
| `search/semantic.py` | Remove context methods, simplify |
| `api/service.py` | Two trackers, updated reset/status methods |
| `api/server.py` | Remove /clear, update lifespan |
| `cli.py` | Add reset, remove clear, add --verbose to status |
| `ingestion/migration.py` | NEW: one-time migration logic |

---

## Execution Strategy

### Recommended Order (sequential, each step testable)

**Wave 1: Foundation (no behavior change, purely additive)**
1. `lock.py` + `IndexingLockError` — test: flock works, double-acquire fails
2. Dead code removal (1.7) — test: existing tests still pass, context code gone
3. Suffix fix (1.4) — test: unit test for known model→suffix mappings

**Wave 2: Schema restructure (biggest change, do as one atomic wave)**
4. Unified DB (1.1) — merge metadata+vec stores to shared connection
5. Chunk versioning (1.2) — parameterize chunks/FTS5 table names
6. Two-dimensional vec/fp (1.3) — two FileTrackers, vec table naming
7. text_hash column (1.6) — add to vec_meta, implement reuse lookup

Test wave 2 as a unit: fresh index from scratch works with new schema.

**Wave 3: Operations**
8. Reset commands (1.5) — drop_vectors, drop_chunks with cascade
9. CLI changes (3.2) — reset --model/--strategy, remove clear, status --verbose
10. REST API (3.3) — remove /clear

**Wave 4: Runtime safety**
11. Lock wiring (3.1) — wrap all write paths
12. Orphan cleanup (2.1) — startup cleanup + vec cleanup + VACUUM at idle
13. Watchdog on_deleted (2.2) — file deletion handling

**Wave 5: Migration**
14. Spike: vec0 shadow table copy — verify if it works
15. migration.py — one-time migration with fallback
16. Test on production data copy (docker cp volume, run migration, verify)

### Why this order
- Wave 1 is safe (additive, no schema change) → quick wins, build confidence
- Wave 2 is the core — do it all at once because schema changes are interdependent
- Wave 3 builds on wave 2's schema
- Wave 4 is runtime behavior, needs wave 2 schema
- Wave 5 is last because migration operates on the OLD schema and produces wave 2 schema

---

## Verification Checklist

How we know implementation is complete. Each item is a concrete,
testable assertion — not "looks good" but "this specific thing works."

### V1: Lock
- [ ] `flock` acquired → second acquire raises `IndexingLockError`
- [ ] Process crash → lock released automatically (kernel cleanup)
- [ ] `dotmd index` while trickle running → "already in progress" + exit(1)

### V2: Unified Database
- [ ] Single `index.db` file, no `metadata.db` or `vec.db`
- [ ] `sqlite_master` contains both `chunks_*` and `vec_chunks_*` tables
- [ ] text_hash JOIN works within single connection (no ATTACH)

### V3: Chunk Versioning
- [ ] `chunk_strategy` setting in config.toml works
- [ ] Tables created: `chunks_{strategy}`, `chunks_fts_{strategy}`
- [ ] Changing strategy → new tables created, old untouched
- [ ] `dotmd reset --strategy X` → drops chunks + FTS5 + graph + all vec for X

### V4: Two-Dimensional Vec/Fingerprints
- [ ] Two FileTracker instances: chunk_tracker + embed_tracker
- [ ] Vec tables named `vec_chunks_{strategy}_{model}`
- [ ] Change model only → chunks NOT re-processed (chunk_diff="unchanged")
- [ ] Change strategy → both chunks and embeddings re-processed

### V5: Suffix Fix
- [ ] No `_LEGACY_MODELS` in code
- [ ] `Qwen3-Embedding-0.6B` and `Qwen3-Embedding-1.5B` → different suffixes
- [ ] Unit test: known model names → expected suffixes

### V6: Reset Operations
- [ ] `dotmd reset --model X` → drops vec + embed_fp for (current_strategy, X)
- [ ] `dotmd reset --strategy X` → cascades: chunks + FTS5 + graph + ALL vec/fp for X
- [ ] `click.confirm()` before each destructive operation
- [ ] No `dotmd clear` command exists
- [ ] No `/clear` REST endpoint

### V7: text_hash Reuse
- [ ] vec_meta has `text_hash` column populated
- [ ] Switch strategy → embedding reuse logged with hit rate > 0%
- [ ] Metrics in log: "N cache hits (X%), M computed, estimated Yh saved"

### V8: Dead Code Removed
- [ ] No `context_embedding_model` in Settings
- [ ] No `encode_batch_context`, `has_context_model`, `unload_context_model`
- [ ] No `_group_chunks_by_file` in pipeline
- [ ] `_embed_chunks` is a one-liner

### V9: Orphan Cleanup
- [ ] Trickle startup: orphan files detected and deleted from all stores
- [ ] Orphan vec entries cleaned across ALL model tables
- [ ] Log: "Orphan cleanup: removed N files (M chunks, V vectors)"
- [ ] After cleanup: `SELECT COUNT(*) FROM chunks_{strategy}` = only valid files

### V10: VACUUM at Idle
- [ ] Flag set after cleanup → VACUUM runs on first idle poll
- [ ] VACUUM does not block serve (runs after healthcheck passes)
- [ ] index.db size drops significantly after orphan cleanup + VACUUM

### V11: Watchdog on_deleted
- [ ] Delete .md file → purged from all stores within debounce window
- [ ] `dotmd search` no longer returns results from deleted file

### V12: Pipeline Flow
- [ ] chunk_fp saved BEFORE embed phase (crash-safe split point)
- [ ] Kill process after chunking, before embedding → restart only re-embeds
- [ ] `--force` → FTS5 cleaned before re-insert (no duplicates)

### V13: Migration (production)
- [ ] Old metadata.db + vec.db → single index.db
- [ ] All tables renamed with strategy + model suffixes
- [ ] chunk_fingerprints derived from COALESCE of all model fp tables
- [ ] text_hash populated for all vec_meta rows
- [ ] graphdb renamed to graphdb_{strategy}
- [ ] Legacy tables (no suffix) gone
- [ ] `dotmd search "test query"` returns correct results after migration
- [ ] `dotmd status --verbose` shows strategies and models correctly

### V14: End-to-End Scenarios
- [ ] Fresh install → index → search → results correct
- [ ] Add file → trickle picks up → searchable
- [ ] Delete file → purged (watchdog or next poll)
- [ ] Switch model (config) → restart → new vec table → old vec untouched
- [ ] Switch strategy (config) → restart → new chunks table → text_hash reuse logged
- [ ] `--force` → clean re-index, no FTS5 duplicates, no orphans
- [ ] `reset --model` → vec gone, chunks remain, search still works (BM25+graph)
- [ ] `reset --strategy` → everything for that strategy gone
- [ ] Parallel `docker exec dotmd index` → blocked by lock
