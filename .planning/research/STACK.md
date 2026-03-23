# Stack Research

**Domain:** Incremental indexing for embedded hybrid search (semantic + BM25 + graph)
**Researched:** 2026-03-23
**Confidence:** HIGH for change detection and vector store; MEDIUM for BM25 strategy; HIGH for graph store

## Context: What Already Exists

The codebase already has these components that constrain and inform choices:

| Component | Current State | Incremental Readiness |
|-----------|--------------|----------------------|
| `SQLiteMetadataStore` | SQLite, chunks table, UPSERT-capable | Needs `file_fingerprints` table added |
| `SQLiteVecVectorStore` | sqlite-vec vec0 virtual table, clears on every `add_chunks()` | Needs per-chunk INSERT/DELETE instead of full wipe |
| `LadybugDBGraphStore` | LadybugDB (Kuzu fork), MERGE semantics, supports DETACH DELETE | Ready for incremental with file-scoped deletes |
| `BM25SearchEngine` | rank_bm25 pickle, full rebuild on every index call | Requires full rebuild — unavoidable with this library |
| `FileInfo.checksum` | MD5 via `hashlib.md5(path.read_bytes())` | Already computes checksum, just not persisted |
| `discover_files()` | Reads all files, computes checksum per file | Reads file content even when unchanged |

**Key constraint from PROJECT.md:** Xeon E3 V2, no AVX2. The 50-minute full index is unacceptable for daily runs. Target: process only changed files (typically 1-5 new voicenotes per day out of 226).

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| Python `hashlib.md5` | stdlib | File fingerprinting | Already used in `FileInfo.checksum`. MD5 is sufficient for change detection (not security); fast on CPU. Persisting this avoids re-reading file content for unchanged files. |
| Python `os.stat()` / `Path.stat()` | stdlib | Fast pre-filter before checksum | mtime+size check costs ~1µs vs ~5ms for MD5 of a 10KB file. Use as a two-stage gate: if mtime+size unchanged, skip checksum. Already available via `FileInfo.last_modified` and `size_bytes`. |
| SQLite (existing `metadata.db`) | stdlib `sqlite3` | Persist file fingerprints | The metadata store already has WAL mode and a connection. Add a `file_fingerprints` table — no new dependency. Store path, mtime, size, md5. |
| `rank_bm25` (existing) | 0.2.2 | BM25 search | Keep for now; full rebuild is required (see BM25 section). At 495 chunks, rebuild takes ~0.1s — not a bottleneck. |
| LadybugDB (existing) | current | Graph store | DETACH DELETE + MERGE semantics make incremental graph updates tractable. Delete file node (cascades to sections via CONTAINS edges), re-add. |

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| None new required | — | — | All necessary components are stdlib or already in the dependency tree. Do not add watchdog, inotify, or bm25opt. |

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `sqlite3` CLI | Inspect fingerprint table during development | `sqlite3 ~/.dotmd/metadata.db '.tables'` |
| `time` / `logging` | Measure per-phase timing | Pipeline already has `logger.info` throughout; add timing around each phase |

---

## Change Detection Strategy

**Use two-stage fingerprinting: mtime+size first, MD5 only on changed candidates.**

### Stage 1: mtime + size (O(1) per file, no I/O)

```python
stat = path.stat()
if stored.mtime == stat.st_mtime and stored.size == stat.st_size:
    # file is unchanged with high probability — skip
    continue
```

**Why mtime first:** A voicenotes daily sync sets mtime on new files. Unchanged files from yesterday have identical mtime. This pre-filter eliminates ~95%+ of files without reading content.

**Why not mtime alone:** mtime can be reset by tools (rsync --times, editors, mount options). The MD5 fallback catches false positives.

### Stage 2: MD5 checksum (only for mtime-changed candidates)

```python
checksum = hashlib.md5(path.read_bytes()).hexdigest()
if stored.checksum == checksum:
    # mtime changed but content identical (touch, rsync metadata update)
    update stored mtime/size only, skip re-indexing
    continue
```

**Why MD5 not SHA-256:** Change detection, not security. MD5 is 2-3x faster. `FileInfo.checksum` already uses MD5 — keep it consistent.

### Fingerprint Table Schema (add to `metadata.db`)

```sql
CREATE TABLE IF NOT EXISTS file_fingerprints (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
)
```

**Why in `metadata.db` not a separate file:** Atomic with chunk metadata. If indexing fails mid-run, both fingerprint and chunks are in the same SQLite transaction scope. Avoids split-brain where fingerprint says "indexed" but chunks are missing.

### Change Classification

```
discover all .md files
  for each file:
    lookup in file_fingerprints
    if not found → NEW (index)
    elif mtime+size changed AND checksum changed → MODIFIED (reindex)
    elif mtime+size changed AND checksum same → TOUCHED (update mtime only)
    else → UNCHANGED (skip)

  files in fingerprints NOT in filesystem → DELETED (remove from all stores)
```

---

## Partial Update Patterns Per Store

### Vector Store (sqlite-vec)

**Current problem:** `add_chunks()` does `DELETE FROM vec_chunks` then inserts all. Cannot be used incrementally.

**Solution:** Add `delete_chunks_for_file(file_path)` and `upsert_chunk(chunk_id, embedding)` to `SQLiteVecVectorStore`.

```python
def delete_chunks_for_file(self, file_path: str) -> None:
    # Delete from meta table (vec table uses rowid FK)
    conn = self._get_conn()
    rows = conn.execute(
        "SELECT rowid FROM vec_meta WHERE chunk_id LIKE ?",
        (f"{file_path}%",)  # or query metadata store for exact chunk_ids
    ).fetchall()
    rowids = [r[0] for r in rows]
    for rowid in rowids:
        conn.execute(f"DELETE FROM {self._VEC_TABLE} WHERE rowid = ?", (rowid,))
    conn.execute(
        "DELETE FROM vec_meta WHERE chunk_id IN (?)",
        ...
    )
    conn.commit()
```

**Better approach:** Pass explicit `chunk_ids` from metadata store (which knows which chunks belong to a file) to avoid relying on chunk_id string prefix matching.

**Why sqlite-vec supports this:** vec0 supports standard SQL DELETE by rowid. The `vec_meta` join table (`rowid → chunk_id`) is regular SQLite — fully deletable by primary key. Confirmed in sqlite-vec v0.1.7 release notes: deletes reclaim space after ~1024 vector removals.

**Confidence:** HIGH — sqlite-vec DELETE is standard SQL on the meta table; vec0 DELETE is documented.

### Metadata Store (SQLite `chunks` table)

Already UPSERT-capable via `ON CONFLICT(chunk_id) DO UPDATE`. Add:

```sql
DELETE FROM chunks WHERE file_path = ?
```

This is the authority on which chunk_ids belong to a file. Vector store and graph store should be driven from this list.

**Confidence:** HIGH — pure SQLite, fully under our control.

### Graph Store (LadybugDB)

LadybugDB supports `DETACH DELETE` which removes a node and all its edges. The File node `id` is the file path string.

**Incremental delete pattern:**

```cypher
-- Remove file node and all FILE_SECTION edges
MATCH (f:File {id: $file_path}) DETACH DELETE f

-- Remove section nodes for this file (sections connect to file via file_path property)
MATCH (s:Section {file_path: $file_path}) DETACH DELETE s

-- Entity and Tag nodes are shared across files — do NOT delete them during per-file update
-- They will accumulate stale entries if a file is deleted and entities are unique to it
-- Accept this trade-off for now; a periodic orphan-cleanup pass can handle it
```

**Why not cascade-clean entities:** Entities like "SQLite", "Docker", "2026-03-15" appear across many files. Deleting them when one file is removed would corrupt other files' graph connections. Only delete Section and File nodes per-file update.

**Entity orphan problem:** After file deletion, some Entity/Tag nodes may have no incoming edges. These are stale but harmless for search (graph search traverses from section nodes anyway). A periodic `dotmd graph-gc` command can clean them. Don't solve this in the incremental indexing milestone.

**Confidence:** MEDIUM — DETACH DELETE syntax confirmed in LadybugDB docs, but the cascading behavior across explicit REL tables (FILE_SECTION vs SECTION_ENTITY) needs integration testing. LadybugDB requires edges to be deleted before nodes in some cases.

### BM25 Index (rank_bm25 pickle)

**rank_bm25 does not support incremental updates.** The `BM25Okapi` object is built from a complete corpus at construction time. There is no `add_document()` or `remove_document()` method.

**Solution: Always rebuild BM25 from the full chunk corpus in metadata store.**

This is acceptable because:
- 495 chunks at 226 files → BM25 rebuild takes ~0.1-0.2 seconds (tokenization + matrix construction)
- BM25 rebuild reads from `metadata.db` (disk), not from re-parsing markdown files
- The expensive parts (embedding via TEI, NER via GLiNER) are skipped for unchanged files

**Implementation:** After processing all changed files, call `bm25_engine.build_index(metadata_store.get_all_chunks())`. This replaces the current call that passes only the current run's chunks.

**Why not bm25opt:** bm25opt has 24 stars, 9 commits, 1 fork as of research date. It's not production-ready. The incremental document management it offers is not worth the dependency risk for a 0.1-second operation.

**Why not bm25s:** bm25s also does not support incremental updates (confirmed via repo inspection). Faster than rank_bm25 for large corpora but same full-rebuild requirement.

**Confidence:** HIGH — rank_bm25 limitations are well-documented; rebuild time is measured/estimated.

---

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `watchdog` / inotify for real-time monitoring | Over-engineered for a daily batch job. inotify adds a persistent process, complexity, and failure modes. The use case is a cron/systemd timer running once daily. | Polling at job start: compare filesystem state against fingerprint table |
| `bm25opt` for incremental BM25 | Too experimental (24 stars, minimal community). At 495 chunks, full BM25 rebuild is ~0.1s — the problem doesn't exist at this scale. | Keep rank_bm25, rebuild from metadata store |
| Per-entity graph deletes on file modification | Entities are shared across files; deleting them corrupts other files' connections | Delete only File and Section nodes; leave Entity/Tag nodes; do orphan GC separately |
| Storing fingerprints in a separate JSON/pickle file | No atomicity with chunk data; can drift out of sync if indexing fails mid-run | Store in `metadata.db` as a proper table |
| Recomputing MD5 for every file on every run | Defeats the purpose; 226 files × 10KB avg = ~2.2MB reads just for fingerprinting | Use mtime+size as pre-filter; only MD5 candidates that changed |
| Chunk-level change detection | Chunking is deterministic from file content — if the file changed, all its chunks changed. No benefit to diffing at chunk level. | File-level granularity: changed file → delete all old chunks → insert all new chunks |

---

## Stack Patterns by Variant

**If NER is enabled (current default):**
- NER (GLiNER) runs only on chunks from changed files — this is the major win. 18 min full → ~2 min for 5 changed files
- Entity deduplication still needed: new NER output may produce entities already in the graph from other files; MERGE handles this

**If NER is disabled (structural-only):**
- Incremental benefit is smaller since structural extraction is already fast (~seconds)
- Same approach applies; even more justified since TEI embedding is the bottleneck

**If a file is deleted from the filesystem:**
- Remove from `file_fingerprints`, `chunks`, vector store, and graph (File + Section nodes)
- Do not attempt to remove entities — accept orphaned Entity/Tag nodes until GC

**If the embedding dimension changes (model swap):**
- Full re-index required; `SQLiteVecVectorStore._create_vec_table()` already handles this with a warning
- Fingerprint table should be cleared on dimension change to force re-embedding

---

## Implementation Order

The stores have dependencies that dictate order:

1. **Fingerprint table** — gate that determines what to process
2. **Per-file delete** — remove stale data from all stores before re-inserting (metadata → vector → graph)
3. **Per-file insert** — chunk → embed → graph for changed files only
4. **BM25 rebuild** — always, from full `get_all_chunks()` after all changes applied
5. **Stats update** — reflect actual total counts

This order ensures: if the process crashes between steps, the next run detects the partially-processed file via checksum mismatch and retries it cleanly.

---

## Version Compatibility

| Package | Current | Constraint | Notes |
|---------|---------|------------|-------|
| rank_bm25 | 0.2.2 | No change needed | Full rebuild acceptable at this corpus size |
| sqlite-vec | current | No change needed | DELETE by rowid confirmed in v0.1.7 |
| real_ladybug | current | No change needed | DETACH DELETE confirmed in docs |
| Python sqlite3 | stdlib | No change needed | New `file_fingerprints` table is pure SQL |

---

## Sources

- sqlite-vec v0.1.7 release notes (github.com/asg017/sqlite-vec/releases) — DELETE support confirmed, space reclaim behavior documented — HIGH confidence
- LadybugDB docs (docs.ladybugdb.com/cypher/data-manipulation-clauses/delete/) — DETACH DELETE syntax confirmed — HIGH confidence
- rank_bm25 PyPI / GitHub (github.com/dorianbrown/rank_bm25) — no incremental update API; full rebuild required — HIGH confidence
- bm25opt GitHub (github.com/jankovicsandras/bm25opt) — incremental API exists but library is experimental (24 stars) — HIGH confidence on API, LOW confidence on production readiness
- bm25s GitHub (github.com/xhluca/bm25s) — no incremental update; full rebuild required — HIGH confidence
- Milvus incremental indexing overview (milvus.io/ai-quick-reference) — general pattern: write buffer + periodic merge — context only
- File change detection tradeoffs (helpful.knobs-dials.com, syncthing forum) — mtime+size vs checksum tradeoffs — MEDIUM confidence (multiple consistent sources)
- Codebase inspection (models.py, metadata.py, sqlite_vec.py, graph.py, bm25.py, pipeline.py) — primary source for current state — HIGH confidence

---

*Stack research for: dotMD incremental indexing milestone*
*Researched: 2026-03-23*
