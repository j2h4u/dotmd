# Feature Research

**Domain:** Incremental indexing for a hybrid search system (semantic + BM25 + knowledge graph)
**Researched:** 2026-03-23
**Confidence:** HIGH (code inspected directly; research confirms patterns)

---

## Context: What the Codebase Currently Does

Before categorizing features, the relevant gaps in the current code:

- `metadata.py` chunks table has no `file_hash` or `mtime` column — no way to detect unchanged files
- `FileInfo.checksum` is a `@computed_field` that calls `path.read_bytes()` on every access — no caching
- `reader.py` `discover_files()` reads every file's content just to extract a title — full corpus read on every run
- `BM25SearchEngine.build_index()` takes the full corpus; `rank_bm25` has no incremental add/remove API
- `SQLiteMetadataStore` has no `delete_chunks_by_file()` — only `delete_all()`
- `LadybugDBGraphStore` has no delete-by-file-path method — orphan nodes accumulate silently
- Graph `File` node stores `checksum` but nothing reads it back for comparison

The 50-minute full index breaks down as: ~25 min embedding (TEI, CPU) + ~18 min NER (GLiNER, CPU) + ~10 min graph. The embedding and NER costs are per-chunk, not per-file — meaning any file with changes re-runs both.

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features an incremental indexer must have to be correct and usable. Missing any of these means the index silently diverges from disk.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **File change detection via content hash** | Without it, "incremental" is just "skip nothing" | LOW | MD5 or SHA-1 of file bytes. Already computed in `FileInfo.checksum` but never persisted to metadata DB. Add `file_hash` column to chunks table; compare on next run. |
| **Persist hash/mtime to metadata store** | Change detection requires a stored baseline | LOW | Add `file_hash TEXT` and `mtime REAL` to the `chunks` table (or a separate `files` table). Mtime as fast pre-filter; hash as authoritative diff. |
| **Skip unchanged files** | The whole point — avoid re-embedding files that haven't changed | LOW | After hash comparison, bypass chunking/embedding/NER/graph update for unchanged files. Expected speedup: proportional to fraction of unchanged files. |
| **Delete stale chunks on file change** | If a file's chunk count changes, old chunks linger in all stores | MEDIUM | On file change: delete old chunks from metadata store, vector store, and BM25 corpus before re-indexing. Requires `delete_chunks_by_file(path)` on all three stores. |
| **Handle deleted files** | Files removed from disk must be removed from the index | MEDIUM | `discover_files()` gives current set. Diff against stored file paths. Delete all chunks/vectors/graph nodes for missing files. |
| **BM25 full rebuild on corpus change** | `rank_bm25` has no incremental API — rebuild is the only correct path | LOW | After all file changes are applied to metadata, rebuild BM25 from `get_all_chunks()`. This is cheap (~1s for 500 chunks) compared to embedding. |
| **Atomic per-file update** | Partial failure mid-file leaves index inconsistent | MEDIUM | Wrap each file's update (delete old + insert new) in a SQLite transaction. If embedding or NER fails, roll back that file — don't corrupt the rest. |
| **Progress reporting to stdout** | Long-running CLI command must show what it's doing | LOW | Log counts: "X files unchanged, Y modified, Z new, W deleted. Processing Y+Z files..." Already using `logger.info` — add structured progress lines. |

### Differentiators (Competitive Advantage)

Features that make this incremental indexer genuinely good, not just correct.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Separate files table with per-file metadata** | Enables O(1) "is this file changed?" without touching chunks | LOW | Dedicated `files` table with `(path, hash, mtime, chunk_count, last_indexed)`. Mtime check first (cheap), hash check only if mtime differs. Avoids reading file bytes for truly unchanged files. |
| **Selective NER skip for unchanged files** | NER is 18 min of the 50-min budget — skipping it for unchanged files is the biggest win | LOW | NER cost is per-chunk. If a file is unchanged, its chunks are unchanged, so NER output is identical. Store NER results per-chunk or simply skip NER for unchanged files' chunks. |
| **Graph pruning: delete-by-file-path** | Without this, deleted/modified files leave orphan nodes in the graph indefinitely | MEDIUM | LadybugDB supports Cypher DELETE. Add `delete_file_subgraph(path)` that removes File node, its Section nodes, and any Entity nodes that have no remaining MENTIONS edges (the orphaned entity problem documented in Graphiti issue #1083). |
| **Dry-run mode** | Confidence before committing a long run | LOW | `dotmd index --dry-run` — discovers files, computes diff (new/modified/deleted counts), prints what would happen, exits. No writes. Useful for verifying cron job logic. |
| **Stats delta in output** | Show what changed, not just final state | LOW | `IndexStats` currently shows totals. For incremental runs, report: `+12 files, -3 files, 47 chunks added, 23 chunks removed, 0 entities changed`. |
| **Idempotent re-runs** | Running `dotmd index` twice with no file changes must produce no writes | LOW | Falls out of correct hash-based detection. Important for cron safety — a failed run followed by retry should not double-write. |
| **`--force` flag to bypass diff** | Escape hatch for when you suspect index corruption | LOW | `dotmd index --force` ignores stored hashes, re-indexes everything. Equivalent to current behavior. |

### Anti-Features (Commonly Requested, Often Problematic)

Features that seem useful but should not be built in v1.

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| **File watcher / daemon mode** | "Index automatically when files change" | Adds persistent process, inotify limit issues on large directories, Docker container lifecycle complexity, event coalescing needed (burst writes trigger many re-indexes). Not needed for a cron-driven workflow. | Cron + `dotmd index` is simpler and sufficient for daily voicenotes sync. Add watcher in v2 if needed. |
| **Partial BM25 update (document-level)** | Avoid full BM25 rebuild on each run | `rank_bm25` has no incremental API. `BM25opt` fork exists but adds a dependency and diverges from upstream. BM25 rebuild from 500 chunks takes ~0.1s — not worth the complexity. | Full BM25 rebuild from metadata store after each incremental run. Fast enough. |
| **Embedding model version migration** | Re-embed only chunks that used an older model version | Adds model versioning to every chunk record, complex migration logic, risk of mixed-model indexes giving inconsistent scores. | On model change, do a full `dotmd index --force`. Embedding model changes are rare for this use case. |
| **Real-time index consistency during search** | Serve search queries while indexing is running | Requires locking or copy-on-write semantics across SQLite + sqlite-vec + LadybugDB. Three separate stores make atomic cross-store consistency hard. | Index offline (cron job), search always reads a stable snapshot. The 50-min window becomes 2-5 min for incremental — acceptable for daily sync. |
| **Conflict resolution / merge strategies** | Handle concurrent indexing from multiple processes | Single-process, single-server deployment. No concurrency requirement. Adding this is pure complexity. | Document that `dotmd index` must not run concurrently. Use a lockfile if paranoid. |
| **Index corruption auto-repair** | Detect and heal inconsistencies between stores | Detecting cross-store inconsistency (e.g., vector exists but metadata row missing) requires full cross-joins across all stores. Complex and slow. | Provide `dotmd index --force` as the recovery path. For SQLite, WAL mode (already enabled) handles crash recovery. Document recovery procedure. |

---

## Feature Dependencies

```
[Persist hash/mtime to metadata store]
    └──required by──> [File change detection via content hash]
                          └──required by──> [Skip unchanged files]
                          └──required by──> [Selective NER skip]
                          └──required by──> [Idempotent re-runs]
                          └──required by──> [Dry-run mode]

[Delete stale chunks on file change]
    └──required by──> [Graph pruning: delete-by-file-path]
    └──required by──> [Handle deleted files]

[Skip unchanged files] ──enables──> [Stats delta in output]

[BM25 full rebuild on corpus change]
    └──runs after──> [Delete stale chunks] + [Skip unchanged files]
    (corpus = all current chunks from metadata store after diff applied)

[Atomic per-file update] ──wraps──> [Delete stale chunks] + [embedding + NER]
```

### Dependency Notes

- **Hash persistence is the foundation.** Everything else — skip, delete, dry-run, NER skip — requires a stored baseline hash. This is the first thing to build.
- **Delete before insert.** When a file changes, old chunks must be removed from all stores before new chunks are added. Otherwise chunk IDs from different chunking runs coexist.
- **BM25 rebuild is always last.** It reads the final state of the metadata store after all adds/deletes are committed.
- **Graph pruning depends on stale chunk deletion.** You can only identify orphaned entities after all stale Section nodes are removed.
- **NER skip depends on file-level skipping.** If a file is skipped entirely, its chunks are never re-processed, so NER is implicitly skipped too.

---

## MVP Definition

### Launch With (v1 — "incremental indexing works correctly")

These are the minimum features for the daily cron to use incremental instead of full:

- [ ] **Persist hash/mtime** — add `files` table to metadata store with `(path, hash, mtime, last_indexed)`
- [ ] **File change detection** — on `dotmd index`, diff current files against stored hashes
- [ ] **Skip unchanged files** — bypass chunking/embedding/NER for hash-matched files
- [ ] **Delete stale chunks** — `delete_chunks_by_file(path)` on metadata + vector store before re-indexing changed files
- [ ] **Handle deleted files** — diff discovered paths against stored paths, delete removed files from all stores
- [ ] **BM25 rebuild from current corpus** — always rebuild BM25 at end of incremental run (fast, correct)
- [ ] **Progress reporting** — log diff summary at start, per-file progress during embedding phase
- [ ] **`--force` flag** — bypass diff for full re-index (recovery path)

### Add After Validation (v1.x)

- [ ] **Graph pruning / orphan entity cleanup** — add after v1 is stable and we can measure orphan accumulation
- [ ] **Dry-run mode** — add once incremental is battle-tested and we want cron verification
- [ ] **Separate files table** (if the chunk-level approach proves awkward) — may be needed anyway for graph pruning to work cleanly
- [ ] **Stats delta reporting** — add once the diff logic is in place (trivial then)

### Future Consideration (v2+)

- [ ] **File watcher daemon** — only if cron granularity becomes insufficient (e.g., live search over active note-taking)
- [ ] **Selective NER per-chunk caching** — only if NER cost dominates after incremental is running (currently NER is skipped implicitly for unchanged files)

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| Persist hash/mtime | HIGH | LOW | P1 |
| Skip unchanged files | HIGH | LOW | P1 |
| Delete stale chunks (all stores) | HIGH | MEDIUM | P1 |
| Handle deleted files | HIGH | MEDIUM | P1 |
| BM25 rebuild from corpus | HIGH | LOW | P1 |
| Progress reporting | MEDIUM | LOW | P1 |
| `--force` flag | MEDIUM | LOW | P1 |
| Atomic per-file update | MEDIUM | MEDIUM | P1 |
| Graph pruning / orphan cleanup | MEDIUM | MEDIUM | P2 |
| Dry-run mode | LOW | LOW | P2 |
| Stats delta in output | LOW | LOW | P2 |
| File watcher daemon | LOW | HIGH | P3 |
| Partial BM25 update | LOW | HIGH | P3 (anti-feature) |

---

## Codebase-Specific Implementation Notes

These are not generic features — they're gaps in the current code that the feature list above requires:

| Gap | Current State | What's Needed |
|-----|---------------|---------------|
| `FileInfo.checksum` | Computed on every access, reads file bytes each time | Cache the value; or move hash computation to `discover_files()` explicitly |
| `metadata.py` chunks table | No `file_hash`, no `mtime`, no file-level record | Add `files` table or at minimum `file_hash` + `mtime` columns on chunks |
| `SQLiteMetadataStore` | Only `delete_all()` | Add `delete_chunks_by_file(path: Path)`, `get_indexed_files() -> dict[str, str]` (path → hash) |
| `SQLiteVecVectorStore` | Unknown delete API | Need `delete_by_file(path)` or `delete_by_chunk_ids(ids)` |
| `LadybugDBGraphStore` | No delete methods | Need `delete_file_subgraph(path)` via Cypher |
| `BM25SearchEngine` | `build_index(chunks)` only | No change needed — full rebuild from metadata store is the right approach |
| `IndexingPipeline.index()` | Processes all discovered files unconditionally | Needs diff phase before processing loop |

---

## Sources

- Code inspection: `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/` (ingestion/pipeline.py, storage/metadata.py, search/bm25.py, ingestion/reader.py, core/models.py, storage/graph.py)
- [CocoIndex incremental processing architecture](https://cocoindex.io/blogs/incremental-processing) — lineage tracking, hash-based change detection patterns
- [Graphiti issue #1083: orphaned entities not cleaned up during episode deletion](https://github.com/getzep/graphiti/issues/1083) — real-world graph orphan problem
- [How to Update RAG Knowledge Base Without Rebuilding Everything](https://particula.tech/blog/update-rag-knowledge-without-rebuilding) — versioned deletion + re-insertion pattern
- [rank_bm25 GitHub](https://github.com/dorianbrown/rank_bm25) — confirmed no incremental add/remove API
- [Incremental Updates in RAG Systems](https://dasroot.net/posts/2026/01/incremental-updates-rag-dynamic-documents/) — delta indexing, 70% processing time reduction
- [Milvus: handling incremental updates in vector databases](https://milvus.io/ai-quick-reference/how-do-you-handle-incremental-updates-in-a-vector-database)
- [Azure AI Search: incremental enrichment](https://learn.microsoft.com/en-us/azure/search/cognitive-search-incremental-indexing-conceptual) — dependency graph recomputation patterns

---
*Feature research for: dotMD incremental indexing milestone*
*Researched: 2026-03-23*
