# Pitfalls Research

**Domain:** Incremental indexing for a multi-store search system (sqlite-vec + LadybugDB + SQLite metadata + BM25 pickle)
**Researched:** 2026-03-23
**Confidence:** HIGH — based on direct codebase analysis; pitfalls derived from concrete code paths, not generic advice

---

## Critical Pitfalls

### Pitfall 1: BM25 Index Rebuilt From Scratch Every Incremental Run

**What goes wrong:**
`build_index()` in `bm25.py` takes a `list[Chunk]` and replaces the entire in-memory index. For incremental indexing the naive approach passes only the changed chunks, producing a BM25 index over a fraction of the corpus. Searches then silently miss everything in unchanged files — no error, just wrong results.

**Why it happens:**
BM25Okapi (rank_bm25) requires the full corpus at construction time to compute IDF. There is no `add_document()` API. Developers see the incremental pipeline writing only new/changed chunks to vector and metadata stores, and mirror that pattern to BM25 without realising BM25 is statistically global.

**How to avoid:**
Always rebuild BM25 from the full chunk set after any incremental run. Load existing chunks from `SQLiteMetadataStore.get_all_chunks()`, merge with newly indexed chunks, then call `build_index()` with the merged list. The BM25 rebuild cost is cheap (pure CPU, no embedding calls) — ~226 files × 2 chunks average = ~450 chunks, negligible.

**Warning signs:**
- BM25 results disappear or shrink drastically after first incremental run
- `bd search --mode bm25` returns fewer hits than `dotmd search` before incremental was added
- `len(self._data.chunk_ids)` after an incremental run is smaller than the full chunk count in `metadata.db`

**Phase to address:**
Phase 1 — core diff detection. The incremental pipeline's "write new chunks" step must be followed immediately by "rebuild BM25 from all chunks". Must be a deliberate step in the pipeline design, not an afterthought.

---

### Pitfall 2: Chunk ID Instability Breaks Cross-Store Consistency

**What goes wrong:**
`_make_chunk_id()` in `chunker.py` uses `md5(f"{file_path}:{chunk_index}")`. Chunk index is a sequential counter over sections within a file. If a file gains or loses a heading, every chunk from that section onward gets a new `chunk_index` and therefore a new `chunk_id`. Incremental indexing detects the file as "changed", re-chunks it, and inserts new chunk IDs — but the old IDs remain in the vector store (sqlite-vec `vec_meta` table), the graph (Section nodes), and the BM25 index mapping. Searches return the old chunk IDs, which either resolve to stale content or produce orphaned results.

**Why it happens:**
The ID scheme is positional, not content-addressed. Structural changes in a file shift all subsequent positions. Incremental code that only inserts new chunks without deleting old ones for modified files leaves dangling references across all four stores.

**How to avoid:**
For any modified file, delete all existing data for that file before reinserting: remove chunks by `file_path` from metadata, delete corresponding rows from `vec_meta`/`vec_chunks` by chunk_id, delete Section nodes and their edges from LadybugDB, then re-chunk and reinsert. Treat a modified file the same as delete + add. The metadata store needs a `get_chunks_by_file(file_path)` query to support this; that query does not currently exist.

**Warning signs:**
- `vec_meta` row count drifts upward across incremental runs while file count stays constant
- Graph Section node count exceeds expected chunks-per-file ratio
- Search returns results pointing to stale content (text no longer in the file)
- `dotmd stats` shows more chunks than `SELECT COUNT(*) FROM chunks WHERE file_path = ?` would suggest for a file's current content

**Phase to address:**
Phase 1 — diff detection design must include a "delete stale data for modified file" step before re-ingestion. The metadata store Protocol should gain `get_chunks_by_file(file_path: str) -> list[Chunk]` and `delete_chunks_by_file(file_path: str) -> None` in this phase.

---

### Pitfall 3: LadybugDB Single-Connection Constraint Breaks Concurrent or Re-entrant Indexing

**What goes wrong:**
`LadybugDBGraphStore.__init__` opens one `lb.Connection` at construction time. Incremental indexing triggered while a search request is in-flight (or if the pipeline is invoked twice) causes the second accessor to either block, raise, or silently corrupt the graph. LadybugDB (Kuzu fork) does not support concurrent write connections to the same database directory.

**Why it happens:**
The current full-index flow is single-shot: start, index, done. Incremental indexing is designed to run on a schedule (daily voicenotes sync) — but the MCP server and search queries may be running simultaneously. The single connection held open in write mode by the `IndexingPipeline` will conflict with any read-only connection opened by the search service.

**How to avoid:**
The indexing pipeline and the search service must not hold simultaneous open connections to LadybugDB. Two strategies: (a) stop the search service during indexing (heavy, undesirable), or (b) serialize graph access via a lock file and ensure the search service opens read-only connections only when no writer is active. The `read_only=True` path in `LadybugDBGraphStore` already exists — enforce it on the search side. Add a write lock (a simple file lock via `fcntl` or a SQLite-based flag) before graph mutation and check it on the search path.

**Warning signs:**
- LadybugDB raises `RuntimeError` or segfault during indexing when MCP/search is running
- Graph search returns no results immediately after an incremental run
- Log shows "Schema statement skipped" during indexing for tables that should exist

**Phase to address:**
Phase 2 — graph store update. Before implementing graph delta updates, define the connection lifecycle and mutual exclusion strategy. Do not assume "it works in practice" because daily scheduling means low concurrency — the risk is real when re-indexing is triggered manually mid-session.

---

### Pitfall 4: sqlite-vec `add_chunks` Does Full Delete-and-Replace

**What goes wrong:**
`SQLiteVecVectorStore.add_chunks()` (line 131-132) executes `DELETE FROM vec_chunks` and `DELETE FROM vec_meta` before inserting. This matches the original "overwrite everything" design. For incremental indexing, calling `add_chunks()` with only the new/changed chunks destroys all existing vectors.

**Why it happens:**
The comment on line 131 explicitly says "Clear existing data (matches LanceDB's mode='overwrite')". Developers may call `add_chunks()` on the delta thinking it is additive, without reading the implementation.

**How to avoid:**
Add `add_chunks_incremental(chunks, embeddings)` to `SQLiteVecVectorStore` that does per-rowid upserts instead of full clear. The `vec0` virtual table supports individual row inserts. Delete old rows for a specific file's chunk IDs before inserting new ones. Alternatively, add `delete_chunks(chunk_ids: list[str]) -> None` to the Protocol and use it explicitly in the pipeline before calling the existing `add_chunks`. The Protocol in `base.py` needs updating regardless.

**Warning signs:**
- Vector store count drops to only the latest incremental batch's chunk count after a run
- Semantic search misses content from unchanged files after first incremental run
- Log shows "Indexed N chunks" where N is much smaller than total corpus size

**Phase to address:**
Phase 1 — alongside BM25 fix. Both stores share the same failure mode (incremental write destroys existing data). Fix the vector store Protocol and sqlite-vec implementation together.

---

### Pitfall 5: File Deletion Not Propagated to Any Store

**What goes wrong:**
If a voicenotes file is deleted from disk (transcript corrected and replaced, or removed), incremental indexing detects "file no longer exists" but has no mechanism to remove its data from any of the four stores. The deleted file's chunks remain in metadata, vectors remain in sqlite-vec, Section/File nodes and their edges remain in LadybugDB, and BM25 continues scoring those chunks. Search results return hits pointing to non-existent files.

**Why it happens:**
The current `pipeline.index()` operates only in "discover and write" mode. There is no concept of a "remove" operation. Incremental work focuses on "what's new/changed" and neglects the delete case, which is less common but causes permanent index contamination.

**How to avoid:**
The diff detection step must compute three sets: `added`, `modified`, `deleted`. For `deleted`, execute the full cleanup: `delete_chunks_by_file()` on metadata, delete corresponding vectors, delete File node + all attached Section nodes + all their edges from LadybugDB. The checksum tracking table (needed for diff detection anyway) provides the "was indexed" reference set.

**Warning signs:**
- `dotmd search` returns results with file paths that return 404 or don't open
- Graph node count grows monotonically across index runs even when files are deleted
- `total_files` in stats decreases but `total_chunks` stays the same

**Phase to address:**
Phase 1 — diff detection. The `deleted` set must be a first-class output of the diff algorithm, not an afterthought. Add a test with file deletion in the test matrix.

---

### Pitfall 6: No Atomic Commit Across Stores — Partial Failure Leaves Inconsistent State

**What goes wrong:**
The pipeline writes to four stores in sequence: metadata (SQLite) → vectors (sqlite-vec) → BM25 (pickle) → graph (LadybugDB). If any step fails mid-run (TEI server timeout during embedding, LadybugDB write error, disk full), the stores are left in partially updated states. Metadata has new chunks, vectors do not. Or vectors have new data but BM25 still reflects the old corpus. Subsequent searches return mixed results from different index generations.

**Why it happens:**
There is no transaction spanning across stores. SQLite WAL and LadybugDB transactions are independent. The pickle write is not transactional at all. Error handling in the current pipeline does not roll back previous store writes if a later one fails.

**How to avoid:**
For a single-user home server with ~226 files, the pragmatic mitigation is: (a) write to a staging path for BM25 pickle and atomically rename it on success; (b) track an "index generation ID" in the metadata stats table — only commit stats after all stores succeed; (c) treat an inconsistent state as "run full index on next startup" by checking for the presence of a generation ID mismatch. Full cross-store transactions are not feasible; defense-in-depth with a generation marker is the practical approach.

**Warning signs:**
- Index run terminated mid-way (OOM, SIGKILL, network timeout to TEI)
- Chunk count in metadata differs from vector store count
- BM25 returns results for chunk IDs that no longer exist in metadata

**Phase to address:**
Phase 2 — robustness. The generation ID / dirty flag mechanism should be designed in Phase 1 but implemented with the full incremental pipeline. At minimum, write the BM25 pickle atomically (write to `.tmp`, rename).

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Rebuild BM25 from all chunks every incremental run | No BM25-specific delta logic needed | ~450 chunks rebuild takes <1s, trivial | Always acceptable at this scale |
| Delete-all per modified file, then reinsert | No upsert logic per store | Re-embeds all chunks of a changed file (TEI call cost) | Acceptable — a changed voicenote transcript is small; embedding 5-10 chunks costs ~1 batch call |
| File-based lock for LadybugDB write exclusion | Simple, no extra deps | No timeout/retry — hung indexer holds lock forever | Acceptable with watchdog timer |
| Skip graph delta, delete all nodes for file and reinsert | No subgraph diff logic | Re-traverses entity lookup for each edge (currently N²) | Acceptable at 226 files; revisit at 2000+ |
| Pickle for BM25 (no rollback) | Zero extra deps | Corrupt pickle on crash requires full rebuild | Never acceptable without atomic rename |

---

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| TEI embedding server (port 8088) | Calling embed on the full new+changed corpus in one batch | The current `encode_batch` splits into sub-batches already; respect that for incremental too — don't hand it 500 chunks at once if only 5 changed |
| sqlite-vec `vec0` virtual table | Trying to `UPDATE` a vec0 row — not supported | Delete by rowid and reinsert; `vec0` is append-and-delete only |
| LadybugDB MERGE semantics | MERGE updates properties but does not remove old edges | Old Section→Entity edges from a now-deleted entity mention remain after file update; must explicitly delete stale edges before MERGE |
| BM25 pickle across Python versions | Pickle protocol mismatch if Python version changes in Docker rebuild | Always use `pickle.HIGHEST_PROTOCOL` on write (already done); add version tag to `_BM25Data` for forward compatibility |
| `FileInfo.checksum` (used in graph node) | Checksum is stored on File node but not in metadata SQLite | For diff detection, the checksum source of truth must be a single place — either add it to `metadata.db` (a `files` table) or always recompute from disk. Storing only in graph requires opening LadybugDB for diff computation, coupling ingestion to graph startup. |

---

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| `_find_node_label()` does 4 sequential queries per edge add | Slow graph population at scale | Cache label per node_id in a dict during bulk insert; the current full-index run hits this for 21k edges | Already slow at 21k edges; incremental adds only a few, so not critical for incremental — but fix before adding more entity types |
| Loading all chunks via `get_all_chunks()` for BM25 rebuild | Reads all chunk text into RAM | At 495 chunks × avg 300 chars = ~150KB — not an issue; load freely | Breaks at ~100k chunks (~30MB text in RAM) |
| Re-embedding unchanged chunks on modified file | Full TEI batch call for a file where only metadata changed | Content-hash each chunk text, not just file mtime — if chunk content is identical, skip embedding | Wasted TEI calls, not a correctness issue |
| Graph `delete_all()` iterates all relation tables and node labels with try/except | 12+ Cypher queries on every clear | Not relevant for incremental (clear is not called); fine as-is | N/A for incremental |

---

## "Looks Done But Isn't" Checklist

- [ ] **Incremental add:** After adding N new files, verify `vector_store.count()` equals `len(metadata.get_all_chunks())` — not just "N chunks added" in the log
- [ ] **Incremental modify:** After modifying a file, search for content from the OLD version — it must not appear in results
- [ ] **Incremental delete:** After deleting a file from disk and re-running, verify the File node no longer exists in the graph and its chunks are gone from vec_meta
- [ ] **BM25 completeness:** After any incremental run, `len(bm25._data.chunk_ids)` must equal total chunk count in metadata, not just the batch size
- [ ] **Concurrent search:** Run a search query during an incremental index run — it must not raise or return corrupt data
- [ ] **Crash recovery:** Kill the indexer mid-run (SIGKILL), restart, verify search still works (returns pre-crash results, not mixed state)
- [ ] **Stats accuracy:** `dotmd stats` must reflect actual counts from each store, not just what the last pipeline run wrote to the stats table

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Stale BM25 (wrong chunk set) | LOW | Delete `bm25_index.pkl`, run full index |
| Orphaned vectors in sqlite-vec | LOW | Delete `sqlite_vec.db`, run full index (or targeted delete by chunk_id list) |
| Orphaned graph nodes (LadybugDB) | MEDIUM | `graph_store.delete_all()` + re-run full index; no partial graph repair without custom Cypher |
| Partial failure mid-incremental | LOW | Check generation ID mismatch, fall back to full index automatically |
| Corrupt BM25 pickle (crash during write) | LOW | Delete pickle file; will be rebuilt on next index run |
| sqlite-vec dimension mismatch (embedding model changed) | LOW | Already handled — `_create_vec_table()` drops and recreates on dim change |

---

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| BM25 built from delta only | Phase 1: diff detection + pipeline design | After incremental add, `len(bm25_data.chunk_ids) == total_chunks_in_metadata` |
| Chunk ID instability / stale data | Phase 1: add `delete_chunks_by_file()` to stores | After modifying a file, old chunk IDs absent from all stores |
| LadybugDB concurrent access | Phase 2: graph delta implementation | Run search during indexing — no exception, no hang |
| sqlite-vec full-replace on incremental | Phase 1: add `delete_chunks()` / incremental insert | `vector_store.count()` matches metadata count after partial run |
| File deletion not propagated | Phase 1: deleted set in diff algorithm | Delete a file, re-run, search for its content — no results |
| No atomic commit across stores | Phase 2: generation ID + atomic BM25 rename | SIGKILL mid-run, restart — search returns coherent pre-run results |

---

## Sources

- Direct analysis of `backend/src/dotmd/storage/sqlite_vec.py` — `add_chunks()` full-clear behavior (lines 131-132)
- Direct analysis of `backend/src/dotmd/ingestion/chunker.py` — `_make_chunk_id()` positional ID scheme
- Direct analysis of `backend/src/dotmd/search/bm25.py` — `build_index()` full-corpus requirement
- Direct analysis of `backend/src/dotmd/storage/graph.py` — single connection constraint, `_find_node_label()` N-query pattern
- Direct analysis of `backend/src/dotmd/ingestion/pipeline.py` — sequential store writes, no cross-store rollback
- `PROJECT.md` — performance baseline (50 min full index), LadybugDB single-connection constraint noted as known, NER cost flagged for revisit on incremental

---
*Pitfalls research for: dotMD incremental indexing milestone*
*Researched: 2026-03-23*
