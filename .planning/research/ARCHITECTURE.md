# Architecture Research: FalkorDB Migration & BM25 Hybrid Fix

**Domain:** Graph store backend swap + hybrid search scoring fix for existing multi-store search pipeline
**Researched:** 2026-03-26
**Confidence:** HIGH (direct codebase analysis + verified FalkorDB docs + existing infrastructure inspection)

## Current Architecture (Relevant Components)

```
DotMDService (api/service.py)
    |
    +-- IndexingPipeline (ingestion/pipeline.py)
    |       |
    |       +-- _create_vector_store()  <-- factory pattern, config-driven
    |       +-- LadybugDBGraphStore     <-- hardcoded, no factory
    |       +-- SQLiteMetadataStore
    |       +-- SemanticSearchEngine, BM25SearchEngine
    |       +-- Extractors (structural, NER, keyterms)
    |
    +-- SemanticSearchEngine  (reuses pipeline's vector_store)
    +-- BM25SearchEngine      (standalone, pickle-backed)
    +-- GraphSearchEngine     (reuses pipeline's graph_store)
    +-- QueryExpander
    +-- Reranker (cross-encoder)
```

### Key Observation: Vector Backend Has the Pattern, Graph Does Not

The vector store already has a config-driven factory:

```python
# pipeline.py, line 56-65
def _create_vector_store(settings: Settings) -> VectorStoreProtocol:
    if settings.vector_backend == "sqlite-vec":
        from dotmd.storage.sqlite_vec import SQLiteVecVectorStore
        return SQLiteVecVectorStore(settings.sqlite_vec_path)
    from dotmd.storage.vector import LanceDBVectorStore
    return LanceDBVectorStore(settings.lancedb_path)
```

The graph store is hardcoded:

```python
# pipeline.py, line 87-89
self._graph_store = LadybugDBGraphStore(
    settings.graph_db_path, read_only=settings.read_only,
)
```

The FalkorDB adapter follows the exact same pattern as the sqlite-vec migration.

---

## Component 1: FalkorDBGraphStore Adapter

### What It Is

A new `storage/falkordb_graph.py` implementing `GraphStoreProtocol`. Connects to an external FalkorDB server (Redis protocol) instead of an embedded file-based LadybugDB.

### Interface Mapping (Protocol -> FalkorDB)

Every method in `GraphStoreProtocol` maps cleanly to FalkorDB Cypher. The mapping is nearly 1:1 because both LadybugDB and FalkorDB speak openCypher.

| Protocol Method | LadybugDB Current | FalkorDB Equivalent | Notes |
|-----------------|-------------------|---------------------|-------|
| `add_file_node()` | `MERGE (f:File {id: $id}) SET ...` | Same Cypher | Params via `{'id': val}` dict |
| `add_section_node()` | `MERGE (s:Section {id: $id}) SET ...` | Same Cypher | No schema pre-definition needed |
| `add_entity_node()` | `MERGE (e:Entity {id: $id}) SET ...` | Same Cypher | |
| `add_tag_node()` | `MERGE (t:Tag {id: $id})` | Same Cypher | |
| `add_edge()` | Lookup labels, find rel table, `MERGE (a)-[r:REL_TABLE]->(b)` | `MERGE (a)-[r:REL_TYPE]->(b)` | **Major simplification** -- no rel table map |
| `get_neighbors()` | `MATCH (a:{label})-[r*1..{N}]-(b)` | Same Cypher | FalkorDB supports `[*1..N]` variable-length paths |
| `delete_file_subgraph()` | `MATCH (s:Section {file_path: $fp}) DETACH DELETE s` | Same Cypher | FalkorDB `DELETE` = `DETACH DELETE` by default |
| `delete_all()` | Complex: iterate rel tables, then node labels | `MATCH (n) DELETE n` | FalkorDB auto-deletes edges |
| `node_count()` | Loop over 4 labels, sum count | `MATCH (n) RETURN count(n)` | Single query |
| `edge_count()` | Loop over 7 rel tables, sum count | `MATCH ()-[r]->() RETURN count(r)` | Single query |
| `get_graph_data()` | Complex multi-query with pandas | Simplified Cypher | See below |

### Critical Differences from LadybugDB

**1. Schemaless (no `CREATE NODE TABLE` / `CREATE REL TABLE`)**

LadybugDB (Kuzu fork) requires explicit schema:
```cypher
CREATE NODE TABLE IF NOT EXISTS File(id STRING, title STRING, ...)
CREATE REL TABLE IF NOT EXISTS FILE_SECTION(FROM File TO Section, ...)
```

FalkorDB is schemaless. Nodes and relationships are created on-the-fly. The entire `_SCHEMA_INIT` list and `_REL_TABLE_MAP` dictionary in `graph.py` are eliminated.

**2. No typed relationship tables**

LadybugDB requires one relationship table per `(FROM_label, TO_label)` pair. The current `add_edge()` does a costly lookup dance:
1. `_find_node_label()` -- queries 4 node tables to find source label
2. `_find_node_label()` -- queries 4 node tables to find target label
3. Lookup `_REL_TABLE_MAP[(src_label, tgt_label)]` to get rel table name
4. Execute MERGE with the correct rel table

FalkorDB: just `MATCH (a {id: $src}), (b {id: $tgt}) MERGE (a)-[r:RELATION]->(b) SET r.rel_type = $type, r.weight = $weight`. No label lookups, no rel table map.

This eliminates the `_find_node_label()` method entirely -- which currently executes 4 queries per node per edge creation (8 queries per edge). For a full index with ~19,000 edges, that is ~152,000 unnecessary queries removed.

**3. `labels()` function available**

FalkorDB has `labels(node)` returning a list of strings. If needed for `get_graph_data()`, can do `RETURN n, labels(n)` instead of iterating per-label.

**4. Connection model: network client, not file lock**

LadybugDB: embedded, single file lock, one connection at a time. This is the root cause of the migration -- concurrent CLI + serve crashes.

FalkorDB: Redis protocol, connection pool, concurrent reads and writes. The `falkordb` Python package provides both sync and async clients with connection pooling.

### FalkorDB Adapter Structure

```python
# storage/falkordb_graph.py

from falkordb import FalkorDB

class FalkorDBGraphStore:
    """FalkorDB implementation of GraphStoreProtocol.

    Connects to an external FalkorDB server over Redis protocol.
    Uses a dedicated graph name to isolate dotMD data from other
    applications sharing the same FalkorDB instance.
    """

    def __init__(self, url: str, graph_name: str = "dotmd") -> None:
        # Parse redis://host:port from URL
        self._db = FalkorDB(host=host, port=port)
        self._graph = self._db.select_graph(graph_name)

    def add_file_node(self, file_path, title, checksum):
        self._graph.query(
            "MERGE (f:File {id: $id}) SET f.title = $title, f.checksum = $checksum",
            params={"id": file_path, "title": title, "checksum": checksum},
        )

    def add_edge(self, source_id, target_id, relation_type, weight=1.0):
        # No label lookup needed -- FalkorDB is schemaless
        self._graph.query(
            "MATCH (a {id: $src}), (b {id: $tgt}) "
            "MERGE (a)-[r:EDGE]->(b) "
            "SET r.rel_type = $rel_type, r.weight = $weight",
            params={"src": source_id, "tgt": target_id,
                    "rel_type": relation_type, "weight": weight},
        )

    def get_neighbors(self, node_id, max_hops=2):
        result = self._graph.query(
            f"MATCH (a {{id: $id}})-[*1..{int(max_hops)}]-(b) "
            "RETURN DISTINCT b.id",
            params={"id": node_id},
        )
        return [(str(row[0]), "", 1.0) for row in result.result_set
                if row[0] != node_id]

    def delete_all(self):
        # FalkorDB: delete graph entirely, then re-select
        self._graph.delete()
        self._graph = self._db.select_graph(self._graph_name)

    def node_count(self):
        result = self._graph.query("MATCH (n) RETURN count(n)")
        return int(result.result_set[0][0])

    def edge_count(self):
        result = self._graph.query("MATCH ()-[r]->() RETURN count(r)")
        return int(result.result_set[0][0])
```

### Graph Name Isolation

The existing FalkorDB instance (`graphiti-falkordb-1`) is used by the Graphiti MCP server with graph name `"knowledgebase"`. dotMD uses graph name `"dotmd"`. FalkorDB supports multiple named graphs per instance -- they are completely isolated.

Confidence: HIGH -- FalkorDB docs confirm `select_graph(name)` creates/selects independent graphs.

### Relationship Type Strategy

Two approaches for edge labels in FalkorDB:

**Option A: Single generic `EDGE` type with `rel_type` property** (recommended)
```cypher
MERGE (a)-[r:EDGE]->(b) SET r.rel_type = $type, r.weight = $weight
```
Simplest. Matches current LadybugDB pattern where `rel_type` is already a property. All graph traversal uses variable-length paths that ignore relationship type anyway.

**Option B: Dynamic relationship types from `relation_type` parameter**
```cypher
-- Not possible with parameterized Cypher: relationship types cannot be parameters
-- Would require f-string interpolation: f"MERGE (a)-[r:{relation_type}]->(b)"
```
More semantically correct, but requires string interpolation (injection risk) and the current `get_neighbors()` query doesn't filter by rel type. No benefit for current search patterns.

Use Option A. The `rel_type` property preserves the information for `get_graph_data()` visualization without complicating queries.

---

## Component 2: Config-Driven Backend Selection

### New Settings Fields

```python
# core/config.py additions

class Settings(BaseSettings):
    # ... existing fields ...

    # Graph backend: "ladybugdb" (default, embedded) or "falkordb" (external)
    graph_backend: Literal["ladybugdb", "falkordb"] = "ladybugdb"

    # FalkorDB connection URL (only used when graph_backend = "falkordb")
    falkordb_url: str = "redis://localhost:6379"

    # FalkorDB graph name (isolates dotMD data from other users of same instance)
    falkordb_graph_name: str = "dotmd"
```

Environment variables: `DOTMD_GRAPH_BACKEND`, `DOTMD_FALKORDB_URL`, `DOTMD_FALKORDB_GRAPH_NAME`.

### Graph Store Factory

Mirror the `_create_vector_store` pattern:

```python
# pipeline.py addition

def _create_graph_store(settings: Settings) -> GraphStoreProtocol:
    """Instantiate the configured graph store backend."""
    if settings.graph_backend == "falkordb":
        from dotmd.storage.falkordb_graph import FalkorDBGraphStore
        return FalkorDBGraphStore(
            url=settings.falkordb_url,
            graph_name=settings.falkordb_graph_name,
        )
    from dotmd.storage.graph import LadybugDBGraphStore
    return LadybugDBGraphStore(
        settings.graph_db_path, read_only=settings.read_only,
    )
```

### Pipeline Changes

Replace hardcoded instantiation in `IndexingPipeline.__init__()`:

```python
# Before (line 87-89):
self._graph_store = LadybugDBGraphStore(
    settings.graph_db_path, read_only=settings.read_only,
)

# After:
self._graph_store = _create_graph_store(settings)
```

### Pipeline Property Type Change

The `graph_store` property currently has return type `LadybugDBGraphStore`:

```python
@property
def graph_store(self) -> LadybugDBGraphStore:  # line 469
```

Change to `GraphStoreProtocol`:

```python
@property
def graph_store(self) -> GraphStoreProtocol:
```

This also affects `DotMDService.graph_data()` which calls `self._pipeline.graph_store.get_graph_data()`. The `get_graph_data()` method is NOT part of `GraphStoreProtocol` -- it is a LadybugDB-specific method. Two options:

1. Add `get_graph_data()` to `GraphStoreProtocol` (must implement in both backends)
2. Move graph visualization logic to a separate utility that works with any `GraphStoreProtocol`

Option 1 is simpler -- add to protocol, implement in both. The FalkorDB version is simpler (single query vs. multi-query).

### `real_ladybug` Dependency

With FalkorDB as default, `real_ladybug` becomes optional. Move to `[project.optional-dependencies]`:

```toml
[project.optional-dependencies]
ladybugdb = ["real_ladybug>=0.1", "pandas>=2.0"]
```

Add `falkordb` to core dependencies:

```toml
dependencies = [
    ...,
    "falkordb>=1.0",
]
```

Pandas is currently a core dependency but only used by `LadybugDBGraphStore.get_graph_data()` for `result.get_as_df()`. Moving it to optional would reduce image size. However, pandas might be used elsewhere -- verify before moving.

---

## Component 3: Docker Networking

### Current State

```
dotmd-api-1  -----> embeddings_default -----> embeddings (TEI, port 80)

graphiti-falkordb-1 ---> graphiti_default (isolated, port 6379)
```

`dotmd-api-1` is on `embeddings_default`. `graphiti-falkordb-1` is on `graphiti_default`. They cannot reach each other.

### Required Change

Add `graphiti_default` as an external network in dotmd's production docker-compose:

```yaml
# /opt/docker/dotmd/docker-compose.yml
services:
  api:
    # ... existing config ...
    networks:
      - default
      - embeddings
      - graphiti      # NEW
    environment:
      # ... existing env ...
      - DOTMD_GRAPH_BACKEND=falkordb
      - DOTMD_FALKORDB_URL=redis://graphiti-falkordb-1:6379  # container name as hostname
      - DOTMD_FALKORDB_GRAPH_NAME=dotmd

networks:
  embeddings:
    external: true
    name: embeddings_default
  graphiti:           # NEW
    external: true
    name: graphiti_default
```

The FalkorDB container is already named `graphiti-falkordb-1` and exposes port 6379 internally. From the `graphiti_default` network, dotmd reaches it as `graphiti-falkordb-1:6379`.

### Dev docker-compose (repo)

The repo's `docker-compose.yml` needs the same network addition for local testing. Alternatively, for development without the graphiti network, keep `graph_backend=ladybugdb` as default.

---

## Component 4: BM25 Hybrid Search Fix

### Problem Statement

BM25 results are missing in hybrid mode. The PROJECT.md says: "Fix BM25 results missing in hybrid mode (reranker/fusion issue?)".

### Root Cause Analysis

I traced the full search path in `DotMDService.search()` (service.py lines 104-241). Here is the data flow with potential failure points:

```
1. bm25_hits = self._bm25_engine.search(query, top_k=pool_size)
   |
   |  BM25 returns (chunk_id, score) pairs with score > 0.0
   |  Pool size = settings.rerank_pool_size = 20
   |
2. engine_results["bm25"] = bm25_hits   # Only added if bm25_hits is truthy
   |
3. fused = fuse_results(engine_results, k=60, weights={"graph": 1.5})
   |
   |  RRF: score = sum(weight / (k + rank)) for each engine
   |  BM25 weight = 1.0 (default), semantic weight = 1.0, graph weight = 1.5
   |  With k=60: rank 1 gives 1/61 = 0.0164, rank 20 gives 1/80 = 0.0125
   |
4. Reranking (service.py lines 202-229):
   |
   |  chunk_ids = [cid for cid, _ in fused[:pool_size]]  # top 20 from RRF
   |  reranked = self._reranker.rerank(query, chunk_ids, metadata_store, top_k=pool_size)
   |
   |  Reranker filters by score_threshold = -8.0
   |  Then: blended = 0.4 * norm_fusion + 0.6 * norm_reranker
   |
5. fused = blended  # replaces original fused list
```

### Likely Failure Point: BM25 Not Loaded at Query Time

The most probable cause: **BM25 index not loaded when the API server handles search requests**.

Evidence:
- `BM25SearchEngine.search()` returns `[]` if `self._data is None` (bm25.py line 124-126)
- `DotMDService.warmup()` calls `self._bm25_engine.load_index()` (service.py line 80)
- But: does the FastAPI server call `warmup()` on startup?

Check `api/server.py`:

```python
# If warmup() is not called, BM25 silently returns empty results
# The engine logs "BM25 index not loaded; returning empty results." at DEBUG level
# In hybrid mode, engine_results won't contain "bm25" key (line 189 guard)
```

If this is the cause, the fix is ensuring `warmup()` is called on server startup, or making BM25 auto-load on first search.

### Second Possible Cause: Reranker Eliminates BM25-only Hits

Even if BM25 produces results, the reranker might filter them out:

1. BM25 finds chunk X (keyword match, short text, low semantic similarity)
2. RRF fuses it -- chunk X has RRF score only from BM25 (1/(60+rank))
3. Reranker scores chunk X with cross-encoder -- short text + length penalty = low score
4. `score_threshold = -8.0` filters it, or blending demotes it below top-k

This is a design issue, not a bug. The reranker legitimately downgrades keyword-only matches that aren't semantically relevant. But if "missing" means "BM25 finds relevant results that disappear after reranking", the fix is in the blending weights or threshold.

### Third Possible Cause: Score Floor Suppression Chain

The semantic search has `score_floor=0.4` (config line 62). If a chunk's cosine similarity is below 0.4, it is excluded from semantic results. If BM25 finds it but semantic doesn't, the chunk enters fusion with only one engine's contribution, making its RRF score lower and more likely to be cut by reranking.

This is by design but worth investigating: are BM25-unique discoveries being systematically eliminated because they lack semantic corroboration?

### Investigation Strategy

The fix requires diagnosis before implementation. Suggested approach:

1. **Add logging to search path**: Log BM25 hit count, which chunks are BM25-only vs. BM25+semantic overlap, and how many survive reranking
2. **Test BM25 in isolation**: `dotmd search --mode bm25 "query"` -- does it return results?
3. **Test hybrid without rerank**: `dotmd search --mode hybrid --no-rerank "query"` -- do BM25 results appear in fusion output?
4. **Check warmup**: Verify `warmup()` is called in all entry points (CLI, API server, MCP)

### Likely Fixes (ordered by probability)

**Fix A: Ensure BM25 loads on startup** (if warmup is missing)
- Add `load_index()` call in server startup or make BM25SearchEngine auto-load on first search

**Fix B: Adjust blending weights** (if reranker suppresses BM25-only hits)
- Current: `0.4 * norm_fusion + 0.6 * norm_reranker`
- BM25-only hits have low norm_reranker (cross-encoder doesn't like keyword-only matches)
- Could increase fusion weight or add a "diversity bonus" for engine coverage

**Fix C: Lower or remove rerank_score_threshold** (if threshold too aggressive)
- Current: `-8.0` -- this is quite permissive for ms-marco-MiniLM cross-encoder scores
- But verify empirically with actual BM25-found chunks

---

## Component 5: `get_graph_data()` Method

### Current Implementation (LadybugDB)

The `get_graph_data()` method is LadybugDB-specific (not in protocol). It does:
1. Query section-entity relationships
2. Query all nodes per label (4 queries)
3. Query all edges per rel table (7 queries)
4. Return `{"nodes": [...], "edges": [...]}`

Used by `DotMDService.graph_data()` and exposed via the API for visualization.

### Protocol Addition

Add `get_graph_data()` to `GraphStoreProtocol`:

```python
def get_graph_data(self) -> dict:
    """Return all nodes and edges for visualization."""
    ...
```

### FalkorDB Implementation

Simpler than LadybugDB -- single queries suffice:

```python
def get_graph_data(self) -> dict:
    nodes = []
    # All nodes with their labels and properties
    result = self._graph.query(
        "MATCH (n) RETURN n.id, labels(n), properties(n)"
    )
    for row in result.result_set:
        node_id, lbls, props = row[0], row[1], row[2]
        nodes.append({"id": node_id, "label": lbls[0] if lbls else "", "properties": props})

    edges = []
    result = self._graph.query(
        "MATCH (a)-[r]->(b) RETURN a.id, b.id, r.rel_type, r.weight"
    )
    for row in result.result_set:
        edges.append({"source": row[0], "target": row[1],
                       "relation_type": row[2], "weight": row[3]})

    return {"nodes": nodes, "edges": edges}
```

---

## Integration Points Summary

### New Files

| File | Purpose |
|------|---------|
| `storage/falkordb_graph.py` | FalkorDBGraphStore implementing GraphStoreProtocol |

### Modified Files

| File | Change | Scope |
|------|--------|-------|
| `core/config.py` | Add `graph_backend`, `falkordb_url`, `falkordb_graph_name` settings | 3 new fields |
| `storage/base.py` | Add `get_graph_data()` to GraphStoreProtocol | 1 new method |
| `ingestion/pipeline.py` | Add `_create_graph_store()` factory, change hardcoded LadybugDB to factory call, change `graph_store` property return type | ~10 lines |
| `api/service.py` | BM25 fix (diagnosis-dependent), possible warmup changes | TBD |
| `pyproject.toml` | Add `falkordb` dependency, optionally move `real_ladybug` + `pandas` to extras | 2-3 lines |
| `docker-compose.yml` (repo) | Add FalkorDB service or network for dev | ~5 lines |
| `/opt/docker/dotmd/docker-compose.yml` (production) | Add `graphiti` network, env vars | ~8 lines |

### Unchanged Files

| File | Why Unchanged |
|------|---------------|
| `search/bm25.py` | BM25 engine itself is correct; issue is in loading/fusion |
| `search/fusion.py` | RRF fusion is correct |
| `search/graph_search.py` | Consumes GraphStoreProtocol -- works with any backend |
| `search/semantic.py` | Unrelated to graph or BM25 |
| `search/reranker.py` | May need threshold tuning but code is correct |
| `storage/graph.py` | LadybugDB adapter preserved as fallback |
| `storage/metadata.py` | Unrelated |
| `extraction/*` | Unrelated |
| `ingestion/reader.py`, `chunker.py`, `file_tracker.py` | Unrelated |

---

## Suggested Build Order

Dependencies drive the order. Each step is testable independently.

```
Phase 1: FalkorDB Adapter (foundation)
    1a. Add config fields (graph_backend, falkordb_url, falkordb_graph_name)
    1b. Implement FalkorDBGraphStore (all protocol methods)
    1c. Add get_graph_data() to GraphStoreProtocol + both implementations
    1d. Add _create_graph_store() factory in pipeline.py
    1e. Update pipeline property type to GraphStoreProtocol
    1f. Add falkordb to pyproject.toml dependencies

    Test: Unit test FalkorDBGraphStore against local FalkorDB
    Test: Integration test -- index with falkordb backend, verify graph populated

Phase 2: Docker Networking
    2a. Update production docker-compose with graphiti network + env vars
    2b. Update repo docker-compose for dev testing
    2c. Rebuild and deploy

    Test: dotmd-api-1 can reach graphiti-falkordb-1:6379 from inside container

Phase 3: BM25 Hybrid Fix (independent of Phase 1-2)
    3a. Diagnose: add logging, test BM25 isolation, test hybrid without rerank
    3b. Fix based on diagnosis (warmup? blending? threshold?)
    3c. Verify BM25 results appear in hybrid output

    Test: dotmd search --mode hybrid returns results from all 3 engines

Phase 4: Data Migration
    4a. Deploy with DOTMD_GRAPH_BACKEND=falkordb
    4b. Run dotmd index --force to rebuild graph in FalkorDB
    4c. Verify search quality matches pre-migration baseline

    Note: ~59 min full re-index. Schedule overnight or accept downtime.
```

**Phase 3 is independent** -- it can run in parallel with Phases 1-2. The BM25 issue exists regardless of which graph backend is active.

**Phase 4 is sequential** -- requires Phases 1 and 2 complete. The re-index strategy (force rebuild, ~59 min) was already identified as the preferred migration approach in the todo note.

---

## Scaling Considerations

| Concern | Current (LadybugDB) | After (FalkorDB) |
|---------|---------------------|-------------------|
| Concurrent access | Single file lock -- crashes on concurrent CLI + serve | Connection pool -- unlimited concurrent reads/writes |
| Memory | Embedded, loads into dotmd process | Separate container, ~50MB baseline for current dataset |
| Network latency | Zero (in-process) | ~1ms per query (local Docker network) |
| Graph size (3.4K nodes, 19.6K edges) | Comfortable | Trivial for FalkorDB |
| Query complexity | Cypher via Kuzu | Same Cypher, same patterns |
| Backup | File copy of `~/.dotmd/graphdb/` | FalkorDB persistence volume |
| Schema changes | Requires DDL statements | Schemaless -- just write |

The network latency trade-off is acceptable. Graph queries during search (`get_neighbors`) happen once per search with a handful of results. During indexing, batch operations (add_node, add_edge) are sequential but each is a single network round-trip -- for 19K edges at 1ms each = ~19 seconds, well within the 59-min full index.

---

## Sources

- FalkorDB Python client: [falkordb-py on GitHub](https://github.com/FalkorDB/falkordb-py) -- HIGH confidence
- FalkorDB Cypher support: [Cypher coverage docs](https://docs.falkordb.com/cypher/cypher-support.html) -- HIGH confidence
- FalkorDB MERGE syntax: [MERGE docs](https://docs.falkordb.com/cypher/merge.html) -- HIGH confidence
- FalkorDB MATCH variable-length paths: [MATCH docs](https://docs.falkordb.com/cypher/match.html) -- HIGH confidence
- FalkorDB functions (labels, count): [Functions docs](https://docs.falkordb.com/cypher/functions.html) -- HIGH confidence
- Direct codebase analysis: `storage/graph.py`, `storage/base.py`, `ingestion/pipeline.py`, `api/service.py`, `search/fusion.py`, `search/bm25.py`, `search/reranker.py` -- HIGH confidence
- Production infrastructure inspection: `docker ps`, `docker network inspect`, `/opt/docker/dotmd/docker-compose.yml`, `/opt/docker/graphiti/docker-compose.yml` -- HIGH confidence
- Existing migration notes: `.planning/todos/pending/2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` -- HIGH confidence

---
*Architecture research for: dotMD v1.2 FalkorDB Migration & BM25 Hybrid Fix*
*Researched: 2026-03-26*
