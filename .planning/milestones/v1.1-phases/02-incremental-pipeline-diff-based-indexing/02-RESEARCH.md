# Phase 2: Incremental Pipeline -- Diff-Based Indexing - Research

**Researched:** 2026-03-23
**Domain:** Python indexing pipeline refactoring, incremental update orchestration
**Confidence:** HIGH

## Summary

Phase 2 wires together the Phase 1 primitives (FileTracker, per-file delete methods) into a diff-based indexing flow inside `IndexingPipeline`. The existing `index()` method is a monolithic 170-line function that always processes all files. The refactor splits it into: discover -> diff -> purge stale -> ingest changed -> rebuild BM25 -> update fingerprints.

All building blocks already exist. FileTracker produces a `FileDiff` with new/modified/deleted/unchanged lists. All three stores have per-file delete methods. The pipeline already has the full ingest logic (read, chunk, embed, extract, graph-populate). The task is orchestration, not new capability.

The critical subtlety is the sqlite-vec `add_chunks` method, which currently does a full wipe (`DELETE FROM vec_chunks` + `DELETE FROM vec_meta`) before inserting. Incremental mode needs to bypass this and instead use the existing `delete_vectors_by_chunk_ids` for targeted removal followed by row-level inserts.

**Primary recommendation:** Refactor `IndexingPipeline.index()` to accept a `force: bool = False` parameter. When `force=False`, use FileTracker.diff() to classify files, purge stale data per-file, ingest only new/modified files, and rebuild BM25 from all chunks. Preserve the current full-index logic as a private `_full_index()` path invoked when `force=True`.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| IP-01 | Modified files: purge old data from all stores, then re-ingest | Purge sequence: get_chunk_ids_by_file -> delete_vectors_by_chunk_ids -> delete_chunks_by_file -> delete_file_subgraph. Then re-ingest per file. |
| IP-02 | New files: ingest normally (embed + NER + graph) | Same ingest path as current pipeline, but scoped to only new files. No purge needed. |
| IP-03 | Deleted files: purge from all stores | Same purge sequence as IP-01 but without re-ingest. Also remove_fingerprint(). |
| IP-04 | BM25 index rebuilt from all chunks after diff applied (~0.1s) | metadata_store.get_all_chunks() -> bm25_engine.build_index(). Always full rebuild. |
| IP-05 | `--force` flag to bypass fingerprints and do full re-index | Pipeline.index(force=True) skips FileTracker.diff(), processes all files. Thread through Service and CLI. |
</phase_requirements>

## Architecture Patterns

### Current Pipeline Flow (to be refactored)

The existing `IndexingPipeline.index()` at `backend/src/dotmd/ingestion/pipeline.py` follows this sequence:

```
discover_files(directory)
  -> for each file: read_file() + chunk_file()
  -> metadata_store.save_chunks(all_chunks)
  -> semantic_engine.encode_batch(all texts) -> vector_store.add_chunks()
  -> bm25_engine.build_index(all_chunks)
  -> structural_extractor.extract(all_chunks)
  -> ner_extractor.extract(all_chunks)       [optional]
  -> keyterm_extractor.extract(all_chunks)
  -> graph: add entities, add file nodes, add section nodes, add edges
  -> extract_acronyms_from_chunks()
  -> metadata_store.save_stats()
```

### Target Pipeline Flow (incremental)

```
discover_files(directory)
  -> file_tracker.diff(discovered_files)     [unless force=True]
  -> PURGE phase:
       for each deleted file:   purge_file_data(path) + remove_fingerprint(path)
       for each modified file:  purge_file_data(path)
  -> INGEST phase (new + modified files only):
       for each file: read_file() + chunk_file()
       metadata_store.save_chunks(new_chunks)
       semantic_engine.encode_batch() -> vector_store.add_chunks_incremental()
       structural/ner/keyterm extraction on new_chunks only
       graph: add entities, file nodes, section nodes, edges
  -> BM25 REBUILD:
       metadata_store.get_all_chunks() -> bm25_engine.build_index()
  -> FINGERPRINT UPDATE:
       for each new/modified file: save_fingerprint()
  -> acronyms rebuild + save_stats()
```

### Key Design Decisions

**1. Purge-before-ingest (not upsert)**

Chunk IDs are positional: `md5(file_path:chunk_index)`. When a file is modified, chunk boundaries shift and the number of chunks may change. Old chunk IDs become orphaned. Therefore: purge ALL data for a modified file first, then re-ingest from scratch. This is the only safe approach with positional IDs.

**2. Per-file purge sequence (ordering matters)**

For each file being purged:
```python
chunk_ids = metadata_store.get_chunk_ids_by_file(file_path)  # MUST come first
vector_store.delete_vectors_by_chunk_ids(chunk_ids)           # needs chunk_ids
metadata_store.delete_chunks_by_file(file_path)               # can now delete
graph_store.delete_file_subgraph(file_path)                   # independent
```

The metadata lookup MUST happen before the metadata delete, because vector delete needs the chunk_ids.

**3. sqlite-vec add_chunks needs modification**

Current `SQLiteVecVectorStore.add_chunks()` (line 130-131 of sqlite_vec.py) does:
```python
conn.execute(f"DELETE FROM {self._VEC_TABLE}")
conn.execute(f"DELETE FROM {self._META_TABLE}")
```

This wipes ALL vectors before inserting. For incremental mode, we need to either:
- (a) Add an `append=False` parameter that skips the wipe when True, or
- (b) Rename current method to `_replace_all_chunks()` and add a separate `add_chunks()` that appends.

**Recommendation:** Option (a) -- add an `overwrite: bool = True` parameter to `add_chunks()`. When `overwrite=False`, skip the DELETE statements. This is backward-compatible: existing callers (full index) still get the wipe behavior. Incremental path passes `overwrite=False` after the per-file purge has already cleaned the specific vectors.

**4. FileTracker integration**

FileTracker requires a `sqlite3.Connection`. The metadata store already opens one. FileTracker should share the metadata store's connection (same pattern as Phase 1 -- `file_fingerprints` table lives in metadata.db).

The pipeline's `__init__` should create a FileTracker:
```python
self._file_tracker = FileTracker(self._metadata_store._conn)
```

**5. Graph re-ingestion is idempotent**

Entity and Tag nodes use MERGE (upsert). When re-ingesting a modified file, any entities that still exist are harmlessly re-merged. Entity nodes from deleted files become orphans but are deliberately preserved (shared across files, per SC-03 / REQUIREMENTS.md "preserve Entity/Tag nodes"). Orphan cleanup is deferred to v2 (GM-01).

**6. BM25 always full rebuild**

BM25 build takes ~0.1s for 500 chunks (per REQUIREMENTS.md). After purge + ingest, call `metadata_store.get_all_chunks()` and rebuild from the full corpus. No incremental BM25 needed.

**7. Acronym dictionary always full rebuild**

Same as BM25 -- `extract_acronyms_from_chunks(all_chunks)` is fast and simpler to rebuild fully.

**8. `--force` flag threading**

```
CLI: index(directory, force=False)
  -> DotMDService.index(directory, force=False)
    -> IndexingPipeline.index(directory, force=False)
      -> if force: _full_index(directory)
         else: _incremental_index(directory)
```

When `force=True`, clear all stores first (or just skip the diff and treat all files as new). The cleaner approach: clear all stores, then process all files normally. This matches the current behavior.

### Recommended Refactored Structure

```python
class IndexingPipeline:
    def index(self, directory: Path, *, force: bool = False) -> IndexStats:
        """Main entry point. Incremental by default, full with force=True."""
        files = discover_files(directory)

        if force:
            return self._full_index(files, directory)

        diff = self._file_tracker.diff(files)
        if not diff.new and not diff.modified and not diff.deleted:
            # Nothing changed
            return self._metadata_store.get_stats() or IndexStats()

        return self._incremental_index(files, diff)

    def _full_index(self, files, directory) -> IndexStats:
        """Current index() logic: process everything."""
        self.clear()
        # ... existing logic ...

    def _incremental_index(self, files, diff) -> IndexStats:
        """Process only changed files."""
        # 1. Purge deleted + modified
        for path in diff.deleted + diff.modified:
            self._purge_file(path)

        # 2. Remove fingerprints for deleted files
        for path in diff.deleted:
            self._file_tracker.remove_fingerprint(path)

        # 3. Ingest new + modified
        changed_files = {str(f.path): f for f in files
                        if str(f.path) in diff.new + diff.modified}
        new_chunks = self._ingest_files(changed_files.values())

        # 4. BM25 full rebuild
        all_chunks = self._metadata_store.get_all_chunks()
        self._bm25_engine.build_index(all_chunks)

        # 5. Update fingerprints for new + modified
        for path_str, fi in changed_files.items():
            stat = fi.path.stat()
            checksum = hashlib.md5(fi.path.read_bytes()).hexdigest()
            self._file_tracker.save_fingerprint(
                path_str, stat.st_mtime, stat.st_size, checksum
            )

        # 6. Acronyms + stats
        ...

    def _purge_file(self, file_path: str) -> None:
        """Remove all data for a single file from all stores."""
        chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)
        self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)
        self._metadata_store.delete_chunks_by_file(file_path)
        self._graph_store.delete_file_subgraph(file_path)

    def _ingest_files(self, files) -> list[Chunk]:
        """Read, chunk, embed, extract, and graph-populate for given files."""
        # Reuses existing pipeline logic but scoped to specific files
        ...
```

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File change detection | Custom mtime comparison | FileTracker.diff() | Already built in Phase 1 with two-stage detection |
| Per-file data purge | Manual SQL across stores | Compose existing delete methods | Phase 1 tested each method independently |
| BM25 incremental update | Custom add/remove from BM25 | Full rebuild from get_all_chunks() | 0.1s for 500 chunks, not worth incremental complexity |
| Chunk ID generation | Content-based hashing | Existing _make_chunk_id(path, index) | Changing ID strategy is out of scope for this phase |

## Common Pitfalls

### Pitfall 1: Vector store full-wipe on add_chunks
**What goes wrong:** Calling `vector_store.add_chunks()` during incremental mode wipes ALL existing vectors, not just the ones for the changed files.
**Why it happens:** Current implementation deletes everything before inserting (line 131 of sqlite_vec.py).
**How to avoid:** Add `overwrite` parameter to `add_chunks()`. Incremental path passes `overwrite=False`.
**Warning signs:** After incremental index, search returns results only from recently-changed files.

### Pitfall 2: Metadata lookup after metadata delete
**What goes wrong:** Calling `delete_chunks_by_file()` before `get_chunk_ids_by_file()` means we can't get chunk IDs for vector deletion.
**Why it happens:** The purge sequence matters -- vector delete needs chunk_ids that live in metadata.
**How to avoid:** Always: get_chunk_ids -> delete_vectors -> delete_chunks -> delete_graph. Enforce this in `_purge_file()`.
**Warning signs:** Orphaned vectors in sqlite-vec that no longer have metadata entries.

### Pitfall 3: Fingerprint save timing
**What goes wrong:** Saving fingerprints before ingestion succeeds means a crash leaves stale fingerprints with no data.
**Why it happens:** If fingerprint is saved but ingestion fails midway, next run sees "unchanged" and skips the file.
**How to avoid:** Save fingerprints AFTER successful ingestion, as the last step.
**Warning signs:** Files that were partially indexed but never re-processed on retry.

### Pitfall 4: Forgetting to rebuild BM25 after incremental
**What goes wrong:** BM25 index still contains old chunk IDs for deleted/modified files.
**Why it happens:** BM25 is serialized to pickle -- it doesn't auto-update when metadata changes.
**How to avoid:** Always call `build_index(metadata_store.get_all_chunks())` at the end of incremental flow.
**Warning signs:** BM25 search returns chunk_ids that don't exist in metadata store.

### Pitfall 5: discover_files reads every file for title extraction
**What goes wrong:** Discovery reads every file (even unchanged ones) via `read_file()` for title extraction.
**Why it happens:** `discover_files()` calls `read_file(md_path)` then `_extract_title(content, md_path)` for each file.
**How to avoid:** This is acceptable for Phase 2 -- the expensive operations are embedding and NER, not file reads. Title extraction for 226 files is <0.1s. Optimization is a v2 concern if ever needed.
**Warning signs:** Not a concern for current scale (~226 files).

### Pitfall 6: Stats computation after incremental
**What goes wrong:** Stats show only the counts from the incremental batch, not the full index.
**Why it happens:** `IndexStats` is built from `len(files)` and `len(all_chunks)` which would be wrong if only counting the changed subset.
**How to avoid:** After incremental, compute stats from the full store: `metadata_store.get_all_chunks()` for chunk count, query all files from fingerprints for file count, graph counts from `node_count()`/`edge_count()`.
**Warning signs:** `dotmd status` shows 3 files instead of 226 after adding 3 new files.

### Pitfall 7: force=True should clear fingerprints too
**What goes wrong:** After `--force` re-index, fingerprints table still has old entries for files that may have been removed.
**Why it happens:** `clear()` method doesn't clear the fingerprints table (it was added later in Phase 1).
**How to avoid:** `_full_index()` should call `self._file_tracker.clear()` along with `self.clear()`.
**Warning signs:** Subsequent incremental run shows wrong diff (ghosts of old files).

## Code Examples

### Per-file purge (critical ordering)

```python
def _purge_file(self, file_path: str) -> None:
    """Remove all indexed data for a single file from all stores.

    ORDERING MATTERS: chunk_ids must be fetched from metadata BEFORE
    metadata rows are deleted, because vector deletion needs them.
    """
    # 1. Get chunk IDs (must be before metadata delete)
    chunk_ids = self._metadata_store.get_chunk_ids_by_file(file_path)

    # 2. Delete vectors (needs chunk_ids from step 1)
    if chunk_ids:
        self._vector_store.delete_vectors_by_chunk_ids(chunk_ids)

    # 3. Delete metadata chunks
    self._metadata_store.delete_chunks_by_file(file_path)

    # 4. Delete graph subgraph (independent, but logically last)
    self._graph_store.delete_file_subgraph(file_path)
```

### Modified add_chunks with overwrite parameter

```python
def add_chunks(
    self,
    chunks: list[Chunk],
    embeddings: list[list[float]],
    *,
    overwrite: bool = True,
) -> None:
    if not chunks:
        return

    dim = len(embeddings[0])
    self._create_vec_table(dim)
    conn = self._get_conn()

    if overwrite:
        # Full replace mode (existing behavior)
        conn.execute(f"DELETE FROM {self._VEC_TABLE}")
        conn.execute(f"DELETE FROM {self._META_TABLE}")

    for chunk, embedding in zip(chunks, embeddings):
        cur = conn.execute(
            f"INSERT INTO {self._META_TABLE} (chunk_id) VALUES (?)",
            (chunk.chunk_id,),
        )
        conn.execute(
            f"INSERT INTO {self._VEC_TABLE} (rowid, embedding) VALUES (?, ?)",
            (cur.lastrowid, _serialize_f32(embedding)),
        )

    conn.commit()
```

### Fingerprint update after successful ingestion

```python
def _update_fingerprints(
    self,
    file_paths: list[str],
    file_info_map: dict[str, FileInfo],
) -> None:
    """Save fingerprints for successfully ingested files."""
    for path_str in file_paths:
        fi = file_info_map[path_str]
        stat = fi.path.stat()
        checksum = hashlib.md5(fi.path.read_bytes()).hexdigest()
        self._file_tracker.save_fingerprint(
            path_str, stat.st_mtime, stat.st_size, checksum,
        )
```

### No-change early return

```python
if not diff.new and not diff.modified and not diff.deleted:
    logger.info(
        "No changes detected (%d files unchanged)", len(diff.unchanged)
    )
    stats = self._metadata_store.get_stats()
    return stats or IndexStats()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Full re-index every run | Diff-based incremental | This phase | 50min -> seconds for typical daily change |
| Monolithic index() method | Split into _full_index/_incremental_index | This phase | Clearer code, testable sub-flows |
| sqlite-vec add_chunks always wipes | Overwrite parameter | This phase | Enables incremental vector addition |

## Open Questions

1. **Stats accuracy in incremental mode**
   - What we know: Current stats are computed from in-memory lists during indexing. After incremental, we need to query stores for totals.
   - What's unclear: Should total_entities and total_edges be recomputed from graph_store.node_count()/edge_count(), or is an approximate count acceptable?
   - Recommendation: Use graph store counts for accuracy. They are fast (simple COUNT queries).

2. **Error recovery on partial incremental**
   - What we know: If ingestion crashes after purging but before fingerprint update, the data is lost but fingerprint still shows old state.
   - What's unclear: Should we implement transactional semantics (save fingerprint atomically with data)?
   - Recommendation: Accept the risk for v1. On next run, the file will be re-diffed as "modified" (checksum mismatch since data was purged but file wasn't re-indexed). A crash is self-healing on retry. No additional mechanism needed.

## Project Constraints (from CLAUDE.md)

- **SOLID principles**: Protocol-based abstractions. The `VectorStoreProtocol.add_chunks()` signature change needs to also update the Protocol definition in `storage/base.py`.
- **UI-agnostic API**: `DotMDService` is the public interface. The `force` parameter must be exposed through service, not just pipeline.
- **Never reload indexes per-request**: BM25 rebuild is an indexing operation, not a search operation. This constraint doesn't apply here.
- **All public APIs go through api/service.py**: The `force` parameter must be threaded: CLI -> Service -> Pipeline. Never expose pipeline directly.
- **Tech stack**: Python 3.12+, no new dependencies needed. All building blocks are from Phase 1.

## Sources

### Primary (HIGH confidence)
- Source code review of all 10 modules in `backend/src/dotmd/` -- direct code analysis
- Phase 1 deliverables: FileTracker, delete methods, test suite (29 passing tests)
- REQUIREMENTS.md, ROADMAP.md, STATE.md -- project documentation

### Secondary (MEDIUM confidence)
- BM25 rebuild timing estimate (0.1s for 500 chunks) from REQUIREMENTS.md -- not independently benchmarked

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - no new libraries, all existing code
- Architecture: HIGH - straightforward refactor, all primitives exist from Phase 1
- Pitfalls: HIGH - identified from direct code analysis of current implementations

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable -- internal refactoring, no external dependencies)
