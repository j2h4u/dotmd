# Architecture Research

**Domain:** Incremental indexing for a multi-store search pipeline
**Researched:** 2026-03-23
**Confidence:** HIGH (based on direct codebase analysis + MEDIUM from ecosystem patterns)

## Standard Architecture

### System Overview — Current (Full Reindex)

```
dotmd index <dir>
    │
    ▼
IndexingPipeline.index()
    │
    ├── discover_files() ──────────────────── all .md files, no change filter
    │
    ├── chunk_file() × N ──────────────────── every file, every time
    │
    ├── metadata_store.save_chunks() ─────── SQLite upsert (already idempotent)
    │
    ├── semantic_engine.encode_batch() ───── TEI HTTP, ~25 min for 495 chunks
    │
    ├── vector_store.add_chunks() ────────── DELETE all, INSERT all (overwrite)
    │
    ├── bm25_engine.build_index() ────────── tokenize all, full pickle rebuild
    │
    ├── structural_extractor.extract() ───── all chunks
    ├── ner_extractor.extract() ──────────── all chunks (~18 min)
    ├── keyterm_extractor.extract() ──────── all chunks
    │
    └── graph_store.{add_*,add_edge}() ───── MERGE (idempotent nodes/edges)
```

### System Overview — Target (Incremental)

```
dotmd index <dir> [--incremental]
    │
    ▼
FileTracker.diff(directory)
    │
    ├── new[]     ── files not in tracking table
    ├── modified[] ── files where checksum differs from stored
    └── deleted[]  ── files in tracking table but not on disk
    │
    ▼
IncrementalIndexingPipeline.update(new, modified, deleted)
    │
    ├── [deleted + modified] → PurgeStep
    │   ├── metadata_store.delete_chunks_by_file()
    │   ├── vector_store.delete_by_chunk_ids()
    │   ├── bm25_engine: mark stale (rebuild needed)
    │   └── graph_store.delete_file_subgraph()
    │
    ├── [new + modified] → IngestStep (existing pipeline, scoped to changed files)
    │   ├── chunk_file() × changed_files only
    │   ├── metadata_store.save_chunks()
    │   ├── semantic_engine.encode_batch() ── only new chunks
    │   └── vector_store.upsert_chunks()
    │
    ├── BM25RebuildStep
    │   └── bm25_engine.build_index(all_chunks_from_metadata)
    │
    ├── ExtractionStep (changed files only)
    │   ├── structural_extractor.extract(new_chunks)
    │   ├── ner_extractor.extract(new_chunks)   ← scoped, major speedup
    │   └── keyterm_extractor.extract(new_chunks)
    │
    ├── GraphUpdateStep
    │   └── graph_store.{add_*,add_edge}() ── new nodes/edges only
    │
    └── FileTracker.commit(new, modified, deleted)
        └── update file_index table with new checksums/mtimes
```

### Component Responsibilities

| Component | Responsibility | Change Required |
|-----------|----------------|-----------------|
| `FileTracker` | Persist file checksums/mtimes; compute new/modified/deleted diff | **New** — lives in `ingestion/` |
| `SQLiteMetadataStore` | Chunk persistence | **Extend** — add `delete_chunks_by_file()`, `get_chunk_ids_by_file()` |
| `SQLiteVecVectorStore` | Vector similarity search | **Extend** — add `delete_by_chunk_ids()` and upsert semantics (remove DELETE-all in `add_chunks`) |
| `LadybugDBGraphStore` | Knowledge graph | **Extend** — add `delete_file_subgraph(file_path)` — delete Section nodes + edges for a file |
| `BM25SearchEngine` | Sparse keyword search | **Accept rebuild** — BM25Okapi has no incremental API; rebuild from metadata store after each run |
| `IndexingPipeline` | Full reindex orchestration | **Preserve unchanged** — incremental is a separate code path |
| `IncrementalIndexingPipeline` | Incremental orchestration | **New** — wraps existing pipeline steps, calls FileTracker, sequences purge→ingest→rebuild |
| `DotMDService` | Public facade | **Extend** — expose `index(incremental=False)` param; route to correct pipeline |

## Recommended Project Structure

```
src/dotmd/
├── ingestion/
│   ├── pipeline.py          # existing full reindex — unchanged
│   ├── incremental.py       # NEW: IncrementalIndexingPipeline
│   ├── file_tracker.py      # NEW: FileTracker with SQLite backing
│   ├── reader.py            # existing — no change
│   └── chunker.py           # existing — no change
├── storage/
│   ├── metadata.py          # extend: delete_chunks_by_file(), get_chunk_ids_by_file()
│   ├── sqlite_vec.py        # extend: delete_by_chunk_ids(), remove delete-all from add_chunks
│   ├── graph.py             # extend: delete_file_subgraph()
│   └── base.py              # extend protocols: add delete-by-file methods
└── api/
    └── service.py           # extend: incremental flag on index()
```

### Structure Rationale

- **`file_tracker.py` in `ingestion/`**: File tracking is an ingestion concern — it answers "what needs to be ingested?" It does not belong in `storage/` (which persists search data) or `core/` (domain models only).
- **`incremental.py` separate from `pipeline.py`**: The two code paths differ enough in sequencing (purge before ingest, BM25 rebuild from metadata rather than from discovered files) that merging them would produce a tangle of conditionals. Keep them separate; share the underlying step implementations.
- **Protocols extended, not replaced**: `VectorStoreProtocol` and `MetadataStoreProtocol` grow new optional-ish methods. Existing implementations stay valid for full reindex.

## Architectural Patterns

### Pattern 1: File Tracking Table (source of truth for change detection)

**What:** A dedicated SQLite table (`file_index`) stores `file_path`, `checksum` (MD5), `mtime`, `indexed_at` for every file that has been successfully indexed. On each incremental run, `discover_files()` output is diffed against this table to produce three sets: new, modified, deleted.

**When to use:** Any pipeline where the inputs are files on disk and outputs are derived indexes. This is the standard pattern — used by Elasticsearch's file system watcher, Azure Cognitive Search indexers, and RAG pipelines like CocoIndex.

**Why checksum over mtime alone:** `mtime` can be reset by `rsync`, `git checkout`, or volume mounts (the voicenotes sync case). MD5 of content is reliable. Cost: one `read_bytes()` per file per run, which is fast compared to embedding.

**Example:**
```python
# ingestion/file_tracker.py

_CREATE_FILE_INDEX = """
CREATE TABLE IF NOT EXISTS file_index (
    file_path   TEXT PRIMARY KEY,
    checksum    TEXT NOT NULL,
    mtime       REAL NOT NULL,
    indexed_at  TEXT NOT NULL
)
"""

@dataclass
class FileDiff:
    new: list[FileInfo]
    modified: list[FileInfo]
    deleted: list[str]  # file paths

class FileTracker:
    def __init__(self, db_path: Path) -> None: ...

    def diff(self, discovered: list[FileInfo]) -> FileDiff:
        """Compare discovered files against stored index."""
        stored = {row[0]: row[1] for row in self._conn.execute(
            "SELECT file_path, checksum FROM file_index"
        )}
        discovered_paths = {str(f.path) for f in discovered}

        new, modified = [], []
        for f in discovered:
            key = str(f.path)
            if key not in stored:
                new.append(f)
            elif stored[key] != f.checksum:
                modified.append(f)

        deleted = [p for p in stored if p not in discovered_paths]
        return FileDiff(new=new, modified=modified, deleted=deleted)

    def commit(self, diff: FileDiff, files: list[FileInfo]) -> None:
        """Record successful index of the given files; remove deleted."""
        ...
```

**Trade-offs:** One extra SQLite file (or a table in existing `metadata.db`). Adds a full-corpus `read_bytes()` pass on every run — acceptable since file I/O is negligible vs. TEI embedding time.

### Pattern 2: Purge-Before-Ingest for Modified Files

**What:** A modified file is treated as delete + re-add, not as an in-place update. Before processing new chunks for a changed file, all old chunks (and their vectors, graph nodes, edges) are removed. This avoids ghost chunks from files that shrank or were restructured.

**When to use:** Always, for any store where chunk IDs are derived from file content/structure. Because `chunk_id` in dotMD encodes `file_path` + `chunk_index`, a restructured file will produce chunk IDs that no longer exist — old IDs become orphans if not purged first.

**Example — purge sequence for a modified/deleted file:**
```python
# 1. Get old chunk IDs for the file
old_chunk_ids = metadata_store.get_chunk_ids_by_file(file_path)

# 2. Remove from vector store
vector_store.delete_by_chunk_ids(old_chunk_ids)

# 3. Remove from graph (Section nodes + their edges; leave Entity/Tag nodes —
#    they may be referenced by other files)
graph_store.delete_file_subgraph(file_path)

# 4. Remove from metadata
metadata_store.delete_chunks_by_file(file_path)

# FileTracker entry removed at commit time
```

**Trade-offs:** Entity and Tag nodes are intentionally left orphaned in the graph after a file deletion if no other file references them. Clean-up of truly orphaned entities is a separate, optional step (run after all purges complete). This avoids cascade-deleting an entity that appears in 20 files just because one file changed.

### Pattern 3: BM25 Always Rebuilds from Metadata

**What:** `rank_bm25.BM25Okapi` computes IDF weights over the full corpus at construction time. There is no supported incremental add/remove API. After any incremental update, BM25 must be rebuilt — but only from chunks already in the metadata store (no re-reading files from disk, no re-chunking).

**When to use:** Every incremental run that changes any chunk. The rebuild cost is tokenization of all stored chunks + `BM25Okapi()` construction. For 495 chunks this is sub-second on the Ivy Bridge hardware. It is not a bottleneck.

**Example:**
```python
# After purge + ingest:
all_chunks = metadata_store.get_all_chunks()
bm25_engine.build_index(all_chunks)
```

**Trade-offs:** If corpus grows to tens of thousands of chunks, BM25 rebuild becomes measurable (seconds, not minutes). At that scale, switch to a database-native BM25 (SQLite FTS5, PostgreSQL `pg_textsearch`). Not a concern at 226–500 file scale.

### Pattern 4: Extraction Scoped to Changed Files Only

**What:** NER (18 min) and structural extraction run only on chunks from new/modified files. Existing chunks already have their entities in the graph via MERGE — re-extracting them would produce duplicate edges (MERGE prevents duplicate nodes but edge semantics in LadybugDB need testing).

**When to use:** Always in incremental mode. This is the primary speedup: a daily sync of 2–5 new voicenote files means NER runs on those files only, dropping from 18 min to ~1 min.

**Trade-offs:** If entity extraction model changes (new GLiNER version, different entity types), old chunks will have stale extractions. Mitigation: add `--reextract` flag that re-runs extraction on all chunks without rebuilding embeddings.

## Data Flow

### Incremental Update Flow

```
[daily voicenotes-sync adds 3 new .md files]
    │
    ▼
dotmd index /srv/knowledgebase/ --incremental
    │
    ▼
FileTracker.diff()
    │
    ├── new:      [file_a.md, file_b.md, file_c.md]
    ├── modified: []
    └── deleted:  []
    │
    ▼
PurgeStep (skipped — no modified/deleted)
    │
    ▼
IngestStep (3 files only)
    ├── chunk_file() × 3 → ~12 new chunks
    ├── metadata_store.save_chunks(12 chunks)
    ├── semantic_engine.encode_batch(12 texts) → TEI HTTP → ~3 min
    └── vector_store.upsert_chunks(12 chunks, embeddings)
    │
    ▼
BM25RebuildStep
    └── metadata_store.get_all_chunks() → 507 chunks
        └── bm25_engine.build_index(507 chunks) → ~0.5s
    │
    ▼
ExtractionStep (12 new chunks only)
    ├── structural_extractor.extract(12 chunks) → ~instant
    ├── ner_extractor.extract(12 chunks)         → ~1 min (vs 18 min full)
    └── keyterm_extractor.extract(12 chunks)     → ~instant
    │
    ▼
GraphUpdateStep (new entities/edges only)
    └── graph_store.{add_*,add_edge}() via MERGE → idempotent
    │
    ▼
FileTracker.commit(new=[a,b,c], modified=[], deleted=[])
    └── INSERT INTO file_index (file_path, checksum, mtime, indexed_at)
```

### File Modification Flow (cascading update)

```
[voicenote re-transcribed → file modified]
    │
    ▼
FileTracker.diff() → modified: [file_x.md]
    │
    ▼
PurgeStep for file_x
    ├── metadata_store.get_chunk_ids_by_file("file_x.md") → [chunk_x_0, chunk_x_1]
    ├── vector_store.delete_by_chunk_ids([chunk_x_0, chunk_x_1])
    ├── graph_store.delete_file_subgraph("file_x.md")
    │       └── DELETE Section nodes where file_path = "file_x.md"
    │           DELETE edges attached to those Section nodes
    │           (Entity/Tag nodes preserved — may be shared)
    └── metadata_store.delete_chunks_by_file("file_x.md")
    │
    ▼
IngestStep (file_x.md only) → new chunks → embed → upsert vectors
    │
    ▼
BM25RebuildStep → all chunks from metadata store
    │
    ▼
ExtractionStep (new chunks for file_x only)
    │
    ▼
GraphUpdateStep → MERGE new nodes/edges
    │
    ▼
FileTracker.commit(modified=[file_x])
    └── UPDATE file_index SET checksum=..., indexed_at=... WHERE file_path="file_x.md"
```

### State Management

- **FileTracker state**: `file_index` table — stored in `metadata.db` (same SQLite file, new table). No new file dependency.
- **Purge atomicity**: Purge + ingest for a single file should be wrapped in a try/except. If ingest fails after purge, the file is absent from the index but not in the tracker — on next run it will be treated as "new" and re-indexed. This is safe (self-healing).
- **BM25 rebuild timing**: Always after purge+ingest, before returning. If process is killed between ingest and BM25 rebuild, the pickle is stale but metadata is correct — next run will rebuild BM25 correctly.

## Scaling Considerations

| Scale | Architecture Adjustments |
|-------|--------------------------|
| ~200-500 files (current) | Single-pass diff, in-process BM25 rebuild, no parallelism needed |
| 1k-5k files | Parallel chunk embedding (batching already exists); consider async TEI requests |
| 5k+ files | SQLite FTS5 instead of BM25 pickle (incremental, no full rebuild); vector store sharding |

### Scaling Priorities

1. **First bottleneck (current):** TEI embedding for new chunks — already batched, already fast for small diffs. No change needed.
2. **Second bottleneck (future):** BM25 rebuild at large corpus — switch to SQLite FTS5 which supports incremental `INSERT`/`DELETE` without full rebuild. FTS5 is in Python stdlib via `sqlite3`; no new dependency.

## Anti-Patterns

### Anti-Pattern 1: Upsert Without Purge for Modified Files

**What people do:** On file change, just re-run `save_chunks()` (upsert) and `add_chunks()` (upsert vectors) without deleting old chunks first.

**Why it's wrong:** If a file had 3 chunks and is re-chunked into 2, chunk ID `file_x_chunk_2` still exists in metadata, vectors, and graph. It becomes a ghost — returned in search, pointing to content that no longer exists. The `heading_hierarchy` and `text` fields are stale.

**Do this instead:** Always purge old chunk IDs for the file before ingesting new chunks. Purge is cheap (indexed DELETE by file_path); ingest only touches changed files.

### Anti-Pattern 2: Storing FileTracker State in Memory Only

**What people do:** Track seen files in a dict during a single process run, using mtime only.

**Why it's wrong:** Process restart loses state; mtime is reset by rsync/git/volume remount. On next run, all files appear "new" and trigger full reindex — defeating the purpose of incremental.

**Do this instead:** Persist `file_index` in SQLite with content checksum. Survives restarts, Docker container recreation, and file system operations that reset mtime.

### Anti-Pattern 3: Deleting Shared Entity Nodes When a File is Purged

**What people do:** When a file is deleted, cascade-delete all its Section nodes, all Entity nodes linked to those sections, and all edges.

**Why it's wrong:** Entity nodes are shared across files. "Алматы" appearing in 50 voicenotes is one Entity node with 50 edges. Deleting it when one file is removed corrupts graph traversal for the other 49 files.

**Do this instead:** Delete only Section nodes (scoped to the file via `file_path` property) and their edges. Leave Entity and Tag nodes. Run a separate orphan-cleanup step if needed (query for entities with zero connected sections).

### Anti-Pattern 4: Running NER on All Chunks Every Incremental Run

**What people do:** Simplify by always passing `all_chunks` to extractors regardless of incremental mode.

**Why it's wrong:** NER is the dominant cost at 18 min for 495 chunks. Re-running it on unchanged chunks on every daily sync eliminates the entire benefit of incremental indexing.

**Do this instead:** Pass only `new_chunks` (from new/modified files) to extractors. Existing entities for unchanged files are already in the graph.

## Integration Points

### Internal Boundaries

| Boundary | Communication | Notes |
|----------|---------------|-------|
| `FileTracker` ↔ `IncrementalIndexingPipeline` | Direct method call — `diff()` returns `FileDiff` dataclass | FileTracker is stateless between calls; pipeline owns the `commit()` timing |
| `IncrementalIndexingPipeline` ↔ existing storage backends | Same protocol methods + new delete-by-file methods | Full reindex path is unaffected |
| `DotMDService` ↔ both pipelines | Conditional instantiation based on `incremental` flag | Service facade hides which pipeline is active |
| `metadata_store` ↔ `file_tracker` | Share the same `metadata.db` file, separate tables | Avoids an extra file; both are SQLite so safe to colocate |

### Protocol Extensions Required

`VectorStoreProtocol` needs one new method:
```python
def delete_by_chunk_ids(self, chunk_ids: list[str]) -> None: ...
```

`MetadataStoreProtocol` needs two new methods:
```python
def delete_chunks_by_file(self, file_path: str) -> None: ...
def get_chunk_ids_by_file(self, file_path: str) -> list[str]: ...
```

`GraphStoreProtocol` needs one new method:
```python
def delete_file_subgraph(self, file_path: str) -> None:
    """Delete all Section nodes where file_path=X and their attached edges.
    Leave Entity and Tag nodes intact."""
    ...
```

`SQLiteVecVectorStore.add_chunks()` must be modified: remove the `DELETE FROM vec_chunks` + `DELETE FROM vec_meta` lines. Upsert semantics (delete-by-id + insert) replace the current overwrite-all approach.

## Suggested Build Order

Build order is driven by dependencies — each step can only be built when its dependencies are ready.

```
1. FileTracker (file_tracker.py)
   Depends on: nothing new (SQLite already in use)
   Deliverable: diff(), commit(), FileDiff dataclass

2. Storage protocol extensions
   Depends on: FileTracker (need to know what delete-by-file means)
   Deliverable:
     - metadata_store.delete_chunks_by_file(), get_chunk_ids_by_file()
     - sqlite_vec.delete_by_chunk_ids(), remove delete-all from add_chunks()
     - graph_store.delete_file_subgraph()
     - base.py protocol additions

3. IncrementalIndexingPipeline (incremental.py)
   Depends on: FileTracker + extended storage backends
   Deliverable: update(diff) orchestration — purge → ingest → BM25 rebuild → extract → graph

4. DotMDService extension
   Depends on: IncrementalIndexingPipeline
   Deliverable: index(incremental=True/False) routing

5. CLI extension
   Depends on: DotMDService
   Deliverable: dotmd index --incremental flag
```

Step 2 (storage extensions) can be parallelized — each store is independent. Steps 1 and 2 can also be parallelized since FileTracker is standalone.

## Sources

- Direct codebase analysis: `ingestion/pipeline.py`, `storage/*.py`, `core/models.py`, `search/bm25.py`
- [Microsoft GraphRAG incremental indexing discussion](https://github.com/microsoft/graphrag/issues/741) — confirms append-first, delete-later approach; MEDIUM confidence
- [CocoIndex: lineage-based incremental indexing](https://medium.com/@cocoindex.io/building-a-real-time-data-substrate-for-ai-agents-the-architecture-behind-cocoindex-729981f0f3a4) — checksum + lineage tracking pattern; MEDIUM confidence
- [Building a Production-Ready RAG System with Incremental Indexing](https://dev.to/guptaaayush8/building-a-production-ready-rag-system-with-incremental-indexing-4bme) — file tracking table pattern; MEDIUM confidence
- [rank-bm25 PyPI](https://pypi.org/project/rank-bm25/) — confirmed: no incremental add/remove API in BM25Okapi; HIGH confidence (official source)

---
*Architecture research for: dotMD incremental indexing*
*Researched: 2026-03-23*
