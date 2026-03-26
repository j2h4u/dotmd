# Feature Landscape

**Domain:** FalkorDB graph store migration + BM25 hybrid search fix
**Researched:** 2026-03-26
**Confidence:** HIGH (direct codebase analysis + verified FalkorDB capability mapping)

---

## Table Stakes

Features that must work for v1.2 to be considered complete. Missing any = regression from v1.1.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **FalkorDB adapter implementing full GraphStoreProtocol** | Core deliverable -- replace LadybugDB | MEDIUM | 11 methods to implement. Most Cypher is identical. `add_edge` gets simpler (no label lookup). `get_graph_data` needs FalkorDB-native queries. |
| **Config-driven graph backend selection** | Must preserve LadybugDB as fallback during migration | LOW | 3 new Settings fields: `graph_backend`, `falkordb_url`, `falkordb_graph_name`. Follow existing `vector_backend` pattern. |
| **Pipeline factory for graph store** | Pipeline currently hardcodes LadybugDB | LOW | Add `_create_graph_store()` mirroring `_create_vector_store()`. ~10 lines. |
| **Docker networking to FalkorDB** | dotMD container must reach FalkorDB container | LOW | Add `graphiti_default` external network. Same pattern as existing `embeddings_default`. |
| **BM25 results visible in hybrid search** | v1.1 hybrid mode drops BM25 results -- users lose keyword search value | MEDIUM | Diagnosis needed first. Likely reranker threshold or blending weight issue. |
| **Graph name isolation** | Shared FalkorDB instance must not corrupt Graphiti's `knowledgebase` graph | LOW | Use separate named graph `"dotmd"`. Add startup validation. |
| **FalkorDB property indexes** | Without indexes, node lookup by `id` requires full graph scan | LOW | `CREATE INDEX FOR (n:Label) ON (n.id)` for File, Section, Entity, Tag at adapter init. |
| **Full re-index with new backend** | Graph data must be rebuilt in FalkorDB after migration | LOW (ops) | `dotmd index --force` with `DOTMD_GRAPH_BACKEND=falkordb`. ~59 min. Schedule overnight. |
| **Search quality parity** | Graph search results with FalkorDB must match LadybugDB quality | MEDIUM | Same Cypher queries, same traversal depth. Verify `get_neighbors` returns equivalent results. |
| **Concurrent CLI + serve** | The primary motivation for migration -- eliminate LadybugDB file lock | LOW | FalkorDB is a network service with connection pooling. Concurrent access works by default. |

## Differentiators

Features that improve the product beyond just replacing LadybugDB.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Simplified edge creation (no label lookup)** | 8x fewer queries per edge during indexing | LOW | FalkorDB allows `MATCH (a {id: $src}), (b {id: $tgt}) MERGE (a)-[r:EDGE]->(b)` without knowing source/target labels. Eliminates `_find_node_label()` entirely. |
| **Single-query node/edge counts** | `MATCH (n) RETURN count(n)` instead of 4+7 queries | LOW | FalkorDB is schemaless -- no need to iterate per-label/per-rel-table. |
| **Connection resilience (retry on timeout)** | FalkorDB is a network service -- transient failures should not kill 59-min index runs | LOW | `BlockingConnectionPool` + simple retry decorator. |
| **BM25 fallback preservation** | Reranker-dropped BM25 results retained with penalty instead of discarded | MEDIUM | Append dropped results at end of blended list with reduced score. Preserves keyword search diversity. |
| **Search diagnostics logging** | Per-engine result counts and reranker decisions visible in debug logs | LOW | Add `logger.debug` calls showing BM25/semantic/graph hit counts before and after reranking. Essential for future search tuning. |
| **Smaller Docker image** | Remove `real_ladybug` + `pandas` dependencies | LOW | `falkordb` is pure Python (~50KB). `real_ladybug` + `pandas` + `numpy` = ~150MB in Docker image. Net savings. |

## Anti-Features

Features to explicitly NOT build in v1.2.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Data migration (export LadybugDB -> import FalkorDB)** | One-time operation, migration code is throwaway, schema differences may bite | Re-index with `--force` (~59 min). Simpler and guaranteed correct. Metadata + vectors are already valid -- only graph is rebuilt. |
| **FalkorDB schema enforcement** | FalkorDB is schemaless by design -- adding constraints would fight the DB | Rely on application-level validation in the adapter. Node labels and property names are already controlled by the Protocol methods. |
| **Async FalkorDB operations** | `falkordb` supports async, but the entire pipeline is synchronous | Keep sync. The pipeline processes files sequentially. Async would only help if multiple files were indexed in parallel, which adds complexity with no benefit at 227-file scale. |
| **Graph-only re-index command** | Useful but not MVP for v1.2 | Use existing `--force` flag. Graph-only re-index could save ~30 min but requires new pipeline logic. Defer to v1.3 if repeated migrations are needed. |
| **FalkorDB vector search** | FalkorDB supports `vecf32()` and `vec.cosineDistance()` -- could replace sqlite-vec | Two backend swaps in one milestone is too risky. sqlite-vec works correctly. Evaluate FalkorDB vectors separately if needed. |
| **Multiple graph backend support (3+ options)** | Only need LadybugDB (legacy) and FalkorDB (new) | Factory pattern supports adding more later, but don't over-engineer for hypothetical backends. |

---

## Feature Dependencies

```
[Config: graph_backend, falkordb_url, falkordb_graph_name]
    |
    +--required by--> [FalkorDB adapter implementation]
    |                      |
    |                      +--required by--> [Pipeline factory: _create_graph_store()]
    |                      |                      |
    |                      |                      +--required by--> [Search with FalkorDB]
    |                      |                      +--required by--> [Index with FalkorDB]
    |                      |
    |                      +--required by--> [Property indexes on id]
    |                      +--required by--> [Connection resilience / retry]
    |
    +--required by--> [Docker networking (graphiti_default)]
                           |
                           +--required by--> [Full re-index with FalkorDB]
                                                  |
                                                  +--required by--> [Search quality validation]

[BM25 hybrid fix] -- INDEPENDENT of FalkorDB migration
    |
    +-- [Diagnosis: identify root cause]
    |       |
    |       +--required by--> [Fix: threshold / blending / warmup]
    |                              |
    |                              +--required by--> [Search diagnostics logging]
    |                              +--required by--> [BM25 fallback preservation]
```

### Key Insight: BM25 fix is independent

The BM25 hybrid issue exists regardless of which graph backend is used. It can be worked on in parallel with the FalkorDB migration.

---

## MVP Recommendation

### Must Ship (v1.2 complete criteria)

1. **FalkorDB adapter** -- all 11+ Protocol methods implemented and tested
2. **Config settings** -- `graph_backend`, `falkordb_url`, `falkordb_graph_name`
3. **Pipeline factory** -- `_create_graph_store()` replacing hardcoded LadybugDB
4. **Property indexes** -- created at adapter init
5. **Docker networking** -- `graphiti_default` added to production compose
6. **Graph name isolation** -- startup validation
7. **Full re-index** -- completed with FalkorDB backend
8. **BM25 hybrid fix** -- diagnosed and fixed; BM25 results visible in hybrid mode
9. **Concurrent access verified** -- CLI + serve simultaneously without errors

### Defer to v1.3

- Graph-only re-index command (optimization, not needed if full re-index is acceptable)
- `real_ladybug` removal from core deps (keep as optional during v1.2 for rollback safety)
- Connection pool tuning (defaults are fine for current scale)
- FalkorDB vector search evaluation (separate investigation)
- `reranker_score` field on `SearchResult` (nice-to-have for diagnostics)

---

## Sources

- Direct codebase analysis: `storage/base.py` (11 GraphStoreProtocol methods), `storage/graph.py` (LadybugDB implementation patterns), `ingestion/pipeline.py` (hardcoded graph store, vector factory pattern), `api/service.py` (search blending logic), `search/reranker.py` (score threshold)
- [FalkorDB Python client](https://github.com/FalkorDB/falkordb-py) -- API compatibility
- [FalkorDB Cypher docs](https://docs.falkordb.com/cypher/) -- feature support matrix
- Production infrastructure: `/opt/docker/dotmd/docker-compose.yml`, `/opt/docker/graphiti/docker-compose.yml`
- `.planning/todos/pending/2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` -- migration rationale

---
*Feature research for: dotMD v1.2 FalkorDB Migration & BM25 Hybrid Fix*
*Researched: 2026-03-26*
