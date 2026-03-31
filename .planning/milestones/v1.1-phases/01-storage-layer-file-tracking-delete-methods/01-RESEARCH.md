# Phase 1: Storage Layer -- File Tracking + Delete Methods - Research

**Researched:** 2026-03-23
**Domain:** SQLite file fingerprinting, per-file deletion across sqlite-vec / LadybugDB / SQLite metadata stores
**Confidence:** HIGH

## Summary

Phase 1 builds the foundation for incremental indexing: the ability to know what changed and to surgically remove stale data from each store. There are two distinct workstreams: (1) a `FileTracker` class backed by a new `file_fingerprints` table in `metadata.db`, and (2) per-file delete methods on all three storage backends.

The codebase is well-prepared for this. `SQLiteMetadataStore` already stores `file_path` on every chunk row, making `DELETE FROM chunks WHERE file_path = ?` trivial. `SQLiteVecVectorStore` has a `vec_meta` join table mapping `rowid -> chunk_id`, which enables targeted deletion via a JOIN query against chunk IDs obtained from the metadata store. LadybugDB stores `file_path` as a property on Section nodes, enabling scoped Cypher `MATCH ... DETACH DELETE`.

The highest-risk item is LadybugDB `DETACH DELETE` cascade behavior across explicit REL tables. Research confirms that `DETACH DELETE` removes ALL connected relationships regardless of relationship table type -- but this has not been tested against the project's specific 7-table schema. A spike test is warranted before writing production code.

**Primary recommendation:** Build FileTracker first (standalone, no dependencies), then implement delete methods on each store independently. Spike the LadybugDB DETACH DELETE behavior as the very first task to retire risk early.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| FT-01 | Persist file fingerprints (path, mtime, size, checksum) in metadata.db | `file_fingerprints` table schema defined in Stack Research; co-located with existing `metadata.db` for atomicity |
| FT-02 | Classify files as new/modified/deleted/unchanged on each index run | Two-stage detection (mtime+size pre-filter, then MD5 checksum) documented in Architecture Research; `FileDiff` dataclass pattern |
| FT-03 | Skip unchanged files entirely (no re-read, no re-embed, no re-extract) | Falls out of FT-02 classification -- unchanged files are simply not in the `new` or `modified` sets |
| SC-01 | Delete chunks by file_path from metadata store | `DELETE FROM chunks WHERE file_path = ?` -- trivial SQL, `file_path` column already exists and is indexed implicitly via the existing queries |
| SC-02 | Delete vectors by file_path from sqlite-vec store | Two-step: query chunk_ids from metadata, then `DELETE FROM vec_meta WHERE chunk_id IN (?)` + `DELETE FROM vec_chunks WHERE rowid IN (?)`. sqlite-vec v0.1.7 confirms proper DELETE support |
| SC-03 | Delete Section nodes and edges by file_path from graph store (preserve Entity/Tag nodes) | `MATCH (s:Section {file_path: $fp}) DETACH DELETE s` removes Section nodes + all edges (FILE_SECTION, SECTION_SECTION, SECTION_ENTITY, SECTION_TAG). Entity/Tag nodes are untouched. Also delete File node: `MATCH (f:File {id: $fp}) DETACH DELETE f` |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **SOLID principles**: Protocol-based abstractions. New delete methods must be added to the Protocol interfaces in `storage/base.py`, not just the concrete implementations.
- **UI-agnostic API**: All public APIs go through `api/service.py` -- never expose internals directly. FileTracker is internal to the ingestion layer.
- **Never reload indexes per-request**: BM25, vector, and graph indexes must be loaded once at startup and reused. The new delete methods must work on the existing connection, not create new ones.
- **Storage backends**: Implement Protocol from `storage/base.py`. New storage backends (or extensions) follow the same pattern.
- **Python 3.12+**, **Pydantic v2**, **src layout**.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python `sqlite3` | stdlib | `file_fingerprints` table, chunk deletion | Already used for `metadata.db`. No new dependency. Co-locating fingerprints with chunk metadata ensures atomicity. |
| Python `hashlib.md5` | stdlib | File content checksumming | Already used in `FileInfo.checksum`. MD5 is fast on CPU (~5ms for 10KB), sufficient for change detection. |
| Python `os.stat` / `Path.stat()` | stdlib | mtime + size pre-filter | ~1us per file. Already used in `discover_files()` via `FileInfo.last_modified` and `size_bytes`. |
| sqlite-vec | >=0.1.6 (v0.1.7 current) | Vector deletion by rowid | v0.1.7 added proper DELETE support with space reclamation. Existing dependency, pinned in pyproject.toml. |
| real_ladybug | >=0.1 (v0.15.2 current) | Graph node/edge deletion via DETACH DELETE | Existing dependency. Cypher `DETACH DELETE` removes a node and ALL connected relationships across ALL rel tables. |

### Supporting

No new libraries required. All functionality is achievable with stdlib + existing dependencies.

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| MD5 checksum | SHA-256 | 2-3x slower, no benefit for change detection (not security). Keep MD5 for consistency with existing `FileInfo.checksum`. |
| Separate fingerprint file (JSON/pickle) | SQLite table in metadata.db | No atomicity with chunk data. SQLite co-location means fingerprint and chunk state are always consistent. |
| mtime-only detection | mtime + size + checksum | mtime resets on rsync/git/mount. Two-stage approach catches false positives without reading file content unnecessarily. |

## Architecture Patterns

### Recommended Project Structure

```
src/dotmd/
  ingestion/
    file_tracker.py      # NEW: FileTracker class + FileDiff dataclass
    pipeline.py           # unchanged (full reindex path)
    reader.py             # unchanged
    chunker.py            # unchanged
  storage/
    base.py               # EXTEND: add delete_by_file methods to protocols
    metadata.py           # EXTEND: delete_chunks_by_file(), get_chunk_ids_by_file()
    sqlite_vec.py         # EXTEND: delete_vectors_by_chunk_ids()
    graph.py              # EXTEND: delete_file_subgraph()
  core/
    models.py             # EXTEND: FileFingerprint model (optional, could be plain tuples)
```

### Pattern 1: Two-Stage File Change Detection

**What:** Compare filesystem state against stored fingerprints in two stages: (1) mtime+size for fast elimination of unchanged files, (2) MD5 checksum only for candidates that passed stage 1.

**When to use:** Every `dotmd index` invocation.

**Example:**
```python
# ingestion/file_tracker.py
from dataclasses import dataclass
from pathlib import Path

@dataclass
class FileDiff:
    new: list[str]        # file paths
    modified: list[str]   # file paths
    deleted: list[str]    # file paths
    unchanged: list[str]  # file paths

class FileTracker:
    """Tracks file fingerprints for incremental indexing."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_CREATE_FINGERPRINTS)
        self._conn.commit()

    def diff(self, discovered: list[FileInfo]) -> FileDiff:
        """Compare discovered files against stored fingerprints."""
        stored = self._load_all()  # dict[str, (mtime, size, checksum)]
        discovered_paths = set()
        new, modified, unchanged = [], [], []

        for f in discovered:
            key = str(f.path)
            discovered_paths.add(key)
            if key not in stored:
                new.append(key)
            else:
                s_mtime, s_size, s_checksum = stored[key]
                stat = f.path.stat()
                if stat.st_mtime == s_mtime and stat.st_size == s_size:
                    unchanged.append(key)  # fast path: skip checksum
                elif f.checksum == s_checksum:
                    unchanged.append(key)  # mtime changed but content same
                    self._update_mtime(key, stat.st_mtime, stat.st_size)
                else:
                    modified.append(key)

        deleted = [p for p in stored if p not in discovered_paths]
        return FileDiff(new=new, modified=modified, deleted=deleted, unchanged=unchanged)
```

### Pattern 2: Purge-Before-Ingest for Modified/Deleted Files

**What:** When a file is modified, delete ALL its old data from ALL stores before re-ingesting. This avoids ghost chunks from changed chunk boundaries.

**When to use:** Always for modified and deleted files. Never try to "update in place."

**Example purge sequence:**
```python
def purge_file(file_path: str, metadata_store, vector_store, graph_store) -> None:
    # 1. Get old chunk IDs from metadata (the authority)
    old_chunk_ids = metadata_store.get_chunk_ids_by_file(file_path)

    # 2. Delete vectors (must happen before metadata deletion)
    if old_chunk_ids:
        vector_store.delete_vectors_by_chunk_ids(old_chunk_ids)

    # 3. Delete graph subgraph (Section nodes + File node + their edges)
    graph_store.delete_file_subgraph(file_path)

    # 4. Delete chunks from metadata (last, since others depend on chunk_ids)
    metadata_store.delete_chunks_by_file(file_path)
```

### Pattern 3: Metadata Store as Chunk-ID Authority

**What:** The `chunks` table in `metadata.db` is the single source of truth for which chunk_ids belong to a file. Vector store and graph store deletions are driven by chunk_id lists obtained from metadata.

**Why:** The `vec_meta` table only stores `(rowid, chunk_id)` -- no `file_path`. Graph Section nodes have `file_path` as a property but querying the graph to get chunk IDs would couple deletion to graph startup. The metadata store is always available (pure SQLite, no extensions needed).

### Anti-Patterns to Avoid

- **Chunk ID prefix matching for file association**: Do not use `WHERE chunk_id LIKE 'file_path%'` to find chunks belonging to a file. Chunk IDs are MD5 hashes of `file_path:chunk_index` -- they have no exploitable prefix. Always query `WHERE file_path = ?` on the chunks table.
- **Upsert without purge for modified files**: If a file shrinks from 3 chunks to 2, the old chunk_id #3 becomes an orphan in all stores. Always purge old data before inserting new.
- **Deleting Entity/Tag nodes on file purge**: Entity and Tag nodes are shared across files. Deleting them when one file changes corrupts other files' graph connections. Only delete Section and File nodes.
- **Storing fingerprints separately from metadata.db**: Leads to split-brain when indexing crashes mid-run. Keep everything in one SQLite database.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File change detection | Custom inotify/watchdog watcher | Two-stage mtime+size+MD5 comparison against SQLite table | Batch polling is simpler, more reliable, and sufficient for daily cron |
| Atomic file writes | Manual temp-file + rename logic | SQLite WAL transactions | Fingerprints and chunks are in the same SQLite DB; transactions give atomicity for free |
| Cross-store transaction | Custom 2-phase commit protocol | Purge-then-ingest ordering + crash recovery via re-classification | True cross-store transactions are impossible across SQLite + sqlite-vec + LadybugDB. Self-healing on next run is sufficient |

## Common Pitfalls

### Pitfall 1: vec_meta Has No file_path Column

**What goes wrong:** Developer tries `DELETE FROM vec_meta WHERE file_path = ?` and gets a SQL error. The `vec_meta` table only has `(rowid, chunk_id)`.

**Why it happens:** The metadata store has `file_path` on chunks, so it's natural to assume the vector store does too. It does not -- the vector store is intentionally minimal.

**How to avoid:** Always get chunk_ids from the metadata store first, then pass them to the vector store's delete method. The metadata store is the authority for file-to-chunk mapping.

**Warning signs:** SQL errors during vector deletion; temptation to add `file_path` to `vec_meta` (unnecessary coupling).

### Pitfall 2: LadybugDB DETACH DELETE Also Removes the File Node

**What goes wrong:** Developer writes `MATCH (s:Section {file_path: $fp}) DETACH DELETE s` and thinks the job is done. But the File node itself (which has `id = file_path`) still exists with dangling edges to now-deleted Section nodes.

**Why it happens:** Section nodes have a `file_path` property, but the File node has `id = file_path`. These are separate queries. The FILE_SECTION edges from File to Section are removed when Section nodes are DETACH DELETEd, but the File node itself persists.

**How to avoid:** Delete both: (1) `MATCH (s:Section {file_path: $fp}) DETACH DELETE s` to remove sections and their edges, then (2) `MATCH (f:File {id: $fp}) DETACH DELETE f` to remove the file node and any remaining edges (FILE_TAG, FILE_ENTITY).

**Warning signs:** File node count grows monotonically across incremental runs even when files are deleted.

### Pitfall 3: Deleting Metadata Chunks Before Querying Chunk IDs

**What goes wrong:** Code deletes chunks from metadata store first, then tries to get chunk_ids to delete from vector store -- but they're already gone.

**Why it happens:** Natural "clean up as you go" impulse. The metadata store is the most accessible store, so it gets cleaned first.

**How to avoid:** Strict ordering: (1) query chunk_ids from metadata, (2) delete vectors, (3) delete graph, (4) delete metadata chunks. Metadata deletion must be last because others depend on the chunk_id list.

**Warning signs:** Vector store or graph retains stale data after what appears to be a successful purge.

### Pitfall 4: FileInfo.checksum Reads File Bytes on Every Access

**What goes wrong:** `FileInfo.checksum` is a `@computed_field` that calls `path.read_bytes()` every time it's accessed. If `diff()` accesses `f.checksum` for all 226 files, it reads every file from disk even for the "fast path" where mtime+size already indicate no change.

**Why it happens:** Pydantic computed fields are re-evaluated on each access unless cached.

**How to avoid:** In the FileTracker, only compute checksum when the mtime+size pre-filter indicates a potential change. Never access `FileInfo.checksum` in the fast path. Compute MD5 explicitly: `hashlib.md5(path.read_bytes()).hexdigest()`.

**Warning signs:** Incremental index takes unexpectedly long on the "diff" phase despite most files being unchanged.

### Pitfall 5: sqlite-vec DELETE Space Reclamation Threshold

**What goes wrong:** After deleting a few vectors, disk usage doesn't decrease. Developer suspects DELETE isn't working.

**Why it happens:** sqlite-vec v0.1.7 reclaims space only when enough deletions clear out a full "chunk" (~1024 vectors). Below that threshold, deleted slots are zero-filled but the physical space isn't released.

**How to avoid:** This is expected behavior, not a bug. For correctness, the vectors are logically deleted (won't appear in search results). Space is reclaimed eventually. At dotMD's scale (~500 vectors), this means space is reclaimed after deleting roughly half the corpus. Not a practical concern.

**Warning signs:** None -- this is purely a disk space observation, not a correctness issue.

## Code Examples

### file_fingerprints Table Schema

```sql
-- Source: Stack Research + codebase analysis
CREATE TABLE IF NOT EXISTS file_fingerprints (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
)
```

**Why `mtime` is REAL:** `os.stat().st_mtime` returns a float (seconds since epoch with sub-second precision). Storing as REAL preserves precision without string conversion overhead.

**Why `indexed_at` is TEXT:** ISO-8601 string, consistent with the existing `stats` table pattern. Used for diagnostics, not for change detection.

### SQLiteMetadataStore.delete_chunks_by_file()

```python
# Source: codebase analysis of metadata.py
def delete_chunks_by_file(self, file_path: str) -> int:
    """Delete all chunks belonging to a file. Returns count deleted."""
    cur = self._conn.execute(
        "DELETE FROM chunks WHERE file_path = ?",
        (file_path,),
    )
    self._conn.commit()
    return cur.rowcount

def get_chunk_ids_by_file(self, file_path: str) -> list[str]:
    """Return all chunk_ids for a given file."""
    cur = self._conn.execute(
        "SELECT chunk_id FROM chunks WHERE file_path = ?",
        (file_path,),
    )
    return [row[0] for row in cur.fetchall()]
```

### SQLiteVecVectorStore.delete_vectors_by_chunk_ids()

```python
# Source: codebase analysis of sqlite_vec.py + sqlite-vec v0.1.7 DELETE support
def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
    """Delete vectors for the given chunk IDs. Returns count deleted."""
    if not chunk_ids:
        return 0
    conn = self._get_conn()
    placeholders = ",".join("?" for _ in chunk_ids)

    # Get rowids from meta table
    rows = conn.execute(
        f"SELECT rowid FROM {self._META_TABLE} WHERE chunk_id IN ({placeholders})",
        chunk_ids,
    ).fetchall()
    rowids = [r[0] for r in rows]

    if rowids:
        rowid_placeholders = ",".join("?" for _ in rowids)
        # Delete from vec0 virtual table by rowid
        conn.execute(
            f"DELETE FROM {self._VEC_TABLE} WHERE rowid IN ({rowid_placeholders})",
            rowids,
        )
        # Delete from meta table
        conn.execute(
            f"DELETE FROM {self._META_TABLE} WHERE chunk_id IN ({placeholders})",
            chunk_ids,
        )
        conn.commit()

    return len(rowids)
```

### LadybugDBGraphStore.delete_file_subgraph()

```python
# Source: LadybugDB docs + codebase analysis of graph.py
def delete_file_subgraph(self, file_path: str) -> None:
    """Delete all Section nodes for a file and the File node itself.

    Entity and Tag nodes are preserved (shared across files).
    DETACH DELETE removes the node AND all its connected edges
    across all relationship tables.
    """
    with self._connection() as conn:
        # 1. Delete Section nodes (+ edges: SECTION_ENTITY, SECTION_TAG,
        #    SECTION_SECTION, and the FILE_SECTION edge from the parent File)
        conn.execute(
            "MATCH (s:Section {file_path: $fp}) DETACH DELETE s",
            parameters={"fp": file_path},
        )
        # 2. Delete File node (+ edges: FILE_TAG, FILE_ENTITY,
        #    any remaining FILE_SECTION edges)
        conn.execute(
            "MATCH (f:File {id: $fp}) DETACH DELETE f",
            parameters={"fp": file_path},
        )
```

### FileTracker Class (complete pattern)

```python
# Source: Architecture Research + Stack Research
import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from dotmd.core.models import FileInfo

_CREATE_FINGERPRINTS = """
CREATE TABLE IF NOT EXISTS file_fingerprints (
    file_path   TEXT PRIMARY KEY,
    mtime       REAL NOT NULL,
    size_bytes  INTEGER NOT NULL,
    checksum    TEXT NOT NULL,
    indexed_at  TEXT NOT NULL
)
"""

@dataclass
class FileDiff:
    """Result of comparing filesystem state against stored fingerprints."""
    new: list[str] = field(default_factory=list)
    modified: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)
    unchanged: list[str] = field(default_factory=list)

class FileTracker:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn
        self._conn.execute(_CREATE_FINGERPRINTS)
        self._conn.commit()

    def diff(self, discovered: list[FileInfo]) -> FileDiff:
        stored = {
            row[0]: (row[1], row[2], row[3])
            for row in self._conn.execute(
                "SELECT file_path, mtime, size_bytes, checksum FROM file_fingerprints"
            )
        }
        discovered_paths: set[str] = set()
        result = FileDiff()

        for f in discovered:
            key = str(f.path)
            discovered_paths.add(key)
            if key not in stored:
                result.new.append(key)
                continue
            s_mtime, s_size, s_checksum = stored[key]
            stat = f.path.stat()
            if stat.st_mtime == s_mtime and stat.st_size == s_size:
                result.unchanged.append(key)
            else:
                checksum = hashlib.md5(f.path.read_bytes()).hexdigest()
                if checksum == s_checksum:
                    result.unchanged.append(key)
                    # Update mtime/size to avoid re-checking next run
                    self._conn.execute(
                        "UPDATE file_fingerprints SET mtime = ?, size_bytes = ? WHERE file_path = ?",
                        (stat.st_mtime, stat.st_size, key),
                    )
                    self._conn.commit()
                else:
                    result.modified.append(key)

        result.deleted = [p for p in stored if p not in discovered_paths]
        return result

    def save_fingerprint(self, file_path: str, mtime: float, size: int, checksum: str) -> None:
        now = datetime.now(tz=timezone.utc).isoformat()
        self._conn.execute(
            "INSERT OR REPLACE INTO file_fingerprints (file_path, mtime, size_bytes, checksum, indexed_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (file_path, mtime, size, checksum, now),
        )
        self._conn.commit()

    def remove_fingerprint(self, file_path: str) -> None:
        self._conn.execute("DELETE FROM file_fingerprints WHERE file_path = ?", (file_path,))
        self._conn.commit()

    def clear(self) -> None:
        self._conn.execute("DELETE FROM file_fingerprints")
        self._conn.commit()
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| sqlite-vec DELETE left garbage | sqlite-vec v0.1.7 proper DELETE with space reclaim | March 2026 | DELETE by rowid now works correctly; space reclaimed after ~1024 deletions per chunk |
| LadybugDB (Kuzu fork) single delete | DETACH DELETE removes node + ALL connected edges | Inherited from Kuzu | Simplifies graph cleanup -- one statement per node type, no manual edge deletion |

**Deprecated/outdated:**
- LanceDB is still available as an alternative vector backend but sqlite-vec is the default (set in `config.py`). Delete methods should be implemented for sqlite-vec only (the active backend).

## Open Questions

1. **LadybugDB DETACH DELETE across explicit REL tables -- verified in docs but untested in this schema**
   - What we know: LadybugDB documentation confirms DETACH DELETE "deletes a node and all of its relationships with a single clause." The Adam example shows relationship count decreasing correctly.
   - What's unclear: The dotMD schema has 7 explicit REL tables (FILE_SECTION, SECTION_ENTITY, etc.). DETACH DELETE on a Section node should remove edges from SECTION_ENTITY, SECTION_TAG, SECTION_SECTION, and FILE_SECTION. This specific combination is untested.
   - Recommendation: Spike test FIRST. Create a minimal graph with the project's schema, insert sample data, run DETACH DELETE on a Section node, verify all expected edges are removed and Entity/Tag nodes survive.

2. **Performance of `get_chunk_ids_by_file()` without an index on `chunks.file_path`**
   - What we know: The `chunks` table has `chunk_id TEXT PRIMARY KEY` but no explicit index on `file_path`.
   - What's unclear: At 500 chunks this is a non-issue (full table scan is instant). At 5000+ chunks it could matter.
   - Recommendation: Add `CREATE INDEX IF NOT EXISTS idx_chunks_file_path ON chunks(file_path)` in the schema init. Zero-cost at current scale, prevents future slowdown.

## Protocol Extension Design

The storage protocols in `base.py` need new methods. These should be added carefully to maintain backward compatibility with the LanceDB vector store implementation (which exists but is not the default).

### VectorStoreProtocol additions

```python
def delete_vectors_by_chunk_ids(self, chunk_ids: list[str]) -> int:
    """Delete vectors for the given chunk IDs. Returns count deleted."""
    ...
```

### MetadataStoreProtocol additions

```python
def delete_chunks_by_file(self, file_path: str) -> int:
    """Delete all chunks belonging to a file. Returns count deleted."""
    ...

def get_chunk_ids_by_file(self, file_path: str) -> list[str]:
    """Return all chunk_ids for a given file path."""
    ...
```

### GraphStoreProtocol additions

```python
def delete_file_subgraph(self, file_path: str) -> None:
    """Delete File and Section nodes for a file path, preserving Entity/Tag nodes."""
    ...
```

**Note on LanceDB:** The LanceDB vector store is not the default backend. Implementing `delete_vectors_by_chunk_ids` on LanceDBVectorStore is NOT in scope for this phase -- focus on sqlite-vec only. If LanceDB users need incremental indexing later, they can implement the method then.

## Deletion Order Constraint

The delete methods have a strict ordering requirement driven by data dependencies:

```
1. metadata_store.get_chunk_ids_by_file(path)  -- READ chunk_ids (must happen first)
2. vector_store.delete_vectors_by_chunk_ids(ids) -- DELETE using chunk_ids
3. graph_store.delete_file_subgraph(path)        -- DELETE using file_path property
4. metadata_store.delete_chunks_by_file(path)    -- DELETE the source of truth (must happen last)
```

Steps 2 and 3 can run in either order (they are independent). But step 1 must precede step 2, and step 4 must follow all others.

## sqlite-vec add_chunks() Modification

The current `add_chunks()` method (lines 131-132 of `sqlite_vec.py`) does `DELETE FROM vec_chunks` and `DELETE FROM vec_meta` before inserting -- a full wipe. This is correct for the full-reindex pipeline (Phase 2 will call it differently), but for Phase 1, the delete methods should be independent of `add_chunks()`.

**Decision for Phase 1:** Do NOT modify `add_chunks()` in this phase. The full-reindex path must continue to work as-is. Phase 1 only adds the new `delete_vectors_by_chunk_ids()` method. Phase 2 will refactor `add_chunks()` to support incremental inserts.

## Sources

### Primary (HIGH confidence)
- Codebase inspection: `storage/metadata.py`, `storage/sqlite_vec.py`, `storage/graph.py`, `storage/base.py`, `core/models.py`, `core/config.py`, `ingestion/pipeline.py`, `ingestion/reader.py`, `ingestion/chunker.py`, `api/service.py`
- [LadybugDB DELETE documentation](https://docs.ladybugdb.com/cypher/data-manipulation-clauses/delete/) -- DETACH DELETE syntax and behavior confirmed
- [sqlite-vec v0.1.7 release notes](https://github.com/asg017/sqlite-vec/releases) -- proper DELETE support with space reclamation
- [sqlite-vec PR #243](https://github.com/asg017/sqlite-vec/pull/243) -- DELETE cleanup implementation details
- [real-ladybug v0.15.2 on PyPI](https://pypi.org/project/real-ladybug/) -- current version confirmed

### Secondary (MEDIUM confidence)
- Existing project research: `.planning/research/STACK.md`, `ARCHITECTURE.md`, `PITFALLS.md`, `FEATURES.md` -- comprehensive prior analysis of incremental indexing patterns
- [sqlite-vec documentation](https://alexgarcia.xyz/sqlite-vec/) -- vec0 virtual table operations

### Tertiary (LOW confidence)
- LadybugDB DETACH DELETE across 7 explicit REL tables in dotMD's schema -- documented behavior matches expectations, but not integration-tested against this specific schema. **Spike required.**

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all libraries are already in use, no new dependencies
- Architecture: HIGH -- patterns directly follow from existing codebase structure and prior research
- Pitfalls: HIGH -- derived from concrete code analysis, not generic advice
- LadybugDB DETACH DELETE specifics: MEDIUM -- documented behavior is clear, but untested against this schema's 7 REL tables

**Research date:** 2026-03-23
**Valid until:** 2026-04-23 (stable domain, no fast-moving dependencies)
