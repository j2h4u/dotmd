# Stack Research

**Domain:** FalkorDB graph store migration + BM25 hybrid search fix
**Researched:** 2026-03-26
**Confidence:** HIGH for FalkorDB client; HIGH for Cypher mapping; MEDIUM for BM25 hybrid diagnosis

## Context: What Already Exists

Components relevant to this milestone -- what changes and what stays:

| Component | Current State | v1.2 Change |
|-----------|--------------|-------------|
| `LadybugDBGraphStore` | Kuzu-fork, embedded, file-lock issues | **Replace** with FalkorDB adapter |
| `GraphStoreProtocol` | 11-method protocol in `storage/base.py` | No change -- FalkorDB adapter implements this |
| `GraphSearchEngine` | Traverses via `get_neighbors()`, filters by metadata | No change -- protocol-decoupled |
| `BM25SearchEngine` | rank_bm25, returns `(chunk_id, score)` pairs | No change -- but investigate hybrid fusion path |
| `Reranker` | Cross-encoder with length penalty + score threshold | **Investigate** -- may be filtering BM25 results |
| `fuse_results()` | RRF with engine_weights, k=60 | **Investigate** -- BM25 results may not reach fusion |
| `DotMDService.search()` | Blends reranker (0.6) with fusion (0.4) | **Investigate** -- blending may suppress BM25-only hits |
| `Settings` | `vector_backend` pattern exists | **Add** `graph_backend`, `falkordb_url` |
| `IndexingPipeline` | Hardcoded `LadybugDBGraphStore` | **Update** to use factory pattern like vector store |
| Docker networking | `default` + `embeddings_default` | **Add** `graphiti_default` for FalkorDB access |

**Infrastructure already in place:**
- FalkorDB server: `graphiti-falkordb-1` on `graphiti_default` network, port 6379, module v4.16.3 (Redis 8.2.3)
- FalkorDB supports multiple named graphs -- use `"dotmd"` graph (no conflict with `"knowledgebase"` used by Graphiti MCP)

---

## Recommended Stack

### Core Technologies

| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `falkordb` (Python client) | 1.6.0 | FalkorDB graph operations | Official Python client, MIT license, Production/Stable status. Uses Redis wire protocol under the hood. Supports sync and async APIs. Params via `graph.query(cypher, params=dict)` -- maps directly to current `conn.execute(cypher, parameters=dict)` pattern. |
| FalkorDB server | 4.16.3 (existing) | Graph database | Already deployed at `graphiti-falkordb-1`. GraphBLAS-backed sparse matrix engine. Schema-free (no CREATE NODE/REL TABLE needed -- major simplification over LadybugDB). Supports MERGE, DETACH DELETE, variable-length paths `[*1..N]`, `labels()` function -- all features used by current graph store. |

### What Changes in Dependencies

**Add to `pyproject.toml`:**

```toml
dependencies = [
    # ... existing ...
    "falkordb>=1.5,<2.0",
]
```

**Remove (eventually, after migration validated):**

```toml
# Move to optional dependency group, then remove entirely
[project.optional-dependencies]
ladybug = ["real_ladybug>=0.1"]
```

**Why `>=1.5,<2.0`:** The 1.6.0 client introduced stability fixes. Pin to 1.x to avoid breaking changes in a hypothetical 2.0 (the client is relatively young). The `graph.query(q, params=dict)` API has been stable since 1.0.

### Supporting Libraries

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `redis` (transitive) | pulled by falkordb | Redis wire protocol | Not imported directly; falkordb handles connection pooling. Aware of it for debugging connectivity. |

No other new libraries needed. The BM25 hybrid fix is a logic/tuning issue in existing code, not a library issue.

### Development Tools

| Tool | Purpose | Notes |
|------|---------|-------|
| `redis-cli` (via docker exec) | Test FalkorDB queries directly | `docker exec graphiti-falkordb-1 redis-cli GRAPH.QUERY dotmd "MATCH (n) RETURN count(n)"` |
| `falkordb` Python REPL | Validate Cypher queries interactively | `from falkordb import FalkorDB; db = FalkorDB(host='localhost', port=6379); g = db.select_graph('dotmd')` |

---

## FalkorDB Cypher Mapping (from LadybugDB)

The current LadybugDB implementation uses Kuzu-dialect Cypher. FalkorDB uses openCypher. Key translation points:

### Schema: Eliminated

LadybugDB requires explicit table definitions:

```cypher
-- LadybugDB: REQUIRED before any data
CREATE NODE TABLE IF NOT EXISTS File(id STRING, title STRING, checksum STRING, PRIMARY KEY (id))
CREATE REL TABLE IF NOT EXISTS FILE_SECTION(FROM File TO Section, rel_type STRING, weight DOUBLE)
```

FalkorDB: **No schema needed.** Nodes and relationships are created on first use. Labels are implicit. This eliminates the entire `_SCHEMA_INIT` list and `_REL_TABLE_MAP` dictionary.

**Confidence:** HIGH -- verified in FalkorDB docs and confirmed by Graphiti MCP deployment on same server.

### Node Operations: Nearly Identical

| Operation | LadybugDB (current) | FalkorDB (target) | Difference |
|-----------|---------------------|-------------------|------------|
| Create/update node | `MERGE (f:File {id: $id}) SET f.title = $title` | `MERGE (f:File {id: $id}) SET f.title = $title` | **Identical Cypher** |
| Parameter passing | `conn.execute(cypher, parameters={"id": val})` | `graph.query(cypher, params={"id": val})` | Kwarg name: `parameters` -> `params` |
| Delete node + edges | `MATCH (f:File {id: $fp}) DETACH DELETE f` | `MATCH (f:File {id: $fp}) DETACH DELETE f` | **Identical Cypher** |

### Edge Operations: Simplified

LadybugDB requires typed relationship tables and a lookup to determine which table to use:

```python
# LadybugDB: Must find node labels, then lookup rel table name
src_label = self._find_node_label(source_id, conn)  # 4 queries!
tgt_label = self._find_node_label(target_id, conn)  # 4 more queries!
rel_table = _REL_TABLE_MAP.get((src_label, tgt_label))
conn.execute(f"MATCH (a:{src_label} ...) MERGE (a)-[r:{rel_table}]->(b) ...")
```

FalkorDB: Relationship types are just labels, no pre-declared tables:

```python
# FalkorDB: Direct relationship creation
graph.query(
    "MATCH (a {id: $src}), (b {id: $tgt}) "
    "MERGE (a)-[r:RELATED {rel_type: $rel_type}]->(b) "
    "SET r.weight = $weight",
    params={"src": source_id, "tgt": target_id, "rel_type": relation_type, "weight": weight}
)
```

**Key simplification:** The `_find_node_label()` helper (which runs 4 sequential queries per node to check File/Section/Entity/Tag) can be eliminated entirely. FalkorDB MATCH without a label matches any node. This turns 8+1 queries per edge into 1 query.

**Alternative:** Keep typed relationships for query specificity. Use the relation_type as the actual FalkorDB relationship type instead of a property:

```python
# Option B: Typed relationships (cleaner graph semantics)
graph.query(
    f"MATCH (a {{id: $src}}), (b {{id: $tgt}}) "
    f"MERGE (a)-[r:{relation_type}]->(b) "
    "SET r.weight = $weight",
    params={"src": source_id, "tgt": target_id, "weight": weight}
)
```

**Recommendation:** Use Option B (typed relationships). It makes graph traversal queries more expressive and aligns with how FalkorDB is designed to be used. The `relation_type` values are already controlled strings like "CONTAINS", "HAS_ENTITY", "MENTIONS_TAG".

### Graph Traversal: Minor Syntax Difference

LadybugDB:
```cypher
MATCH (a:Section {id: $id})-[r* 1..2]-(b)
RETURN DISTINCT b.id, label(b)
```

FalkorDB:
```cypher
MATCH (a:Section {id: $id})-[*1..2]-(b)
RETURN DISTINCT b.id, labels(b)
```

Differences:
1. **`label(b)` -> `labels(b)`**: FalkorDB uses `labels()` (plural, returns a list). LadybugDB uses `label()` (singular). This is a confirmed difference -- FalkorDB docs explicitly document `labels()` returning a list of strings.
2. **Variable-length path binding**: FalkorDB doesn't require naming the relationship variable in variable-length paths. `[*1..2]` works without `[r*1..2]`.
3. **Undirected matching**: Both support `-[]-` (no arrow) for bidirectional traversal. Confirmed in FalkorDB MATCH docs.

**Confidence:** HIGH -- verified `labels()` function and variable-length path syntax against FalkorDB official docs.

### Result Handling: Different API

LadybugDB returns a Kuzu-style result:
```python
result = conn.execute(cypher, parameters=params)
df = result.get_as_df()  # Returns pandas DataFrame
for _, row in df.iterrows():
    value = row["column_name"]
```

FalkorDB returns a result set:
```python
result = graph.query(cypher, params=params)
for row in result.result_set:
    value = row[0]  # Positional access
```

**Impact:** Every method that reads results needs updating. The FalkorDB result set is a list of tuples (positional), not a DataFrame (named columns). This is actually simpler -- eliminates the pandas dependency for graph operations.

**Confidence:** HIGH -- verified via falkordb-py source code (`graph.query()` returns `QueryResult` with `.result_set` attribute).

---

## BM25 Hybrid Search Investigation

This is a logic debugging task, not a library issue. The problem: BM25 results go missing in hybrid mode.

### Diagnosis Path (no new libraries needed)

The search pipeline in `DotMDService.search()` follows this flow:

```
1. Query expansion
2. Run engines: semantic(pool_size), bm25(pool_size), graph(seeds from 1+2)
3. Fuse via RRF (k=60, graph_weight=1.5)
4. Rerank top pool_size candidates (cross-encoder)
5. Blend: 0.4*normalized_fusion + 0.6*normalized_reranker
6. Build SearchResult with per-engine score attribution
```

**Suspected failure points (in order of likelihood):**

1. **Reranker score threshold (-8.0) filtering BM25 hits:** The cross-encoder scores BM25-only hits (which match on keywords but may be semantically less relevant) low. If the score is below -8.0, the chunk is dropped entirely (line 132 in reranker.py: `if score >= self._score_threshold`). BM25 keyword matches that are topically adjacent but not semantically similar to the query would score poorly on a cross-encoder trained for semantic relevance.

2. **Blending ratio (0.6 reranker, 0.4 fusion) suppresses BM25-only hits:** Even if BM25 results survive the threshold, the 60% reranker weight means the cross-encoder dominates the final ranking. BM25-only hits that the cross-encoder scores low get pushed below top_k.

3. **RRF k=60 dilutes BM25 contribution:** With k=60, a result at rank 1 in BM25 gets score 1/61 = 0.0164. If that same result is NOT in the semantic top-20, it only gets the BM25 contribution. Meanwhile, a result at rank 1 in semantic gets 1/61 = 0.0164 PLUS whatever graph score. The RRF constant may be too high for a 3-engine fusion where engines have very different recall characteristics.

**Debugging approach (no stack changes):**
- Add logging in `search()` to emit per-engine result counts and score ranges before/after fusion
- Log which chunk_ids survive reranking vs which are filtered by threshold
- Test with `rerank=False` to isolate whether fusion or reranking causes the loss
- Test with `mode="bm25"` to confirm BM25 engine itself returns results

**Potential fixes (config tuning, no new code):**
- Lower `rerank_score_threshold` (e.g., -12.0) to let more BM25 hits through
- Adjust blending ratio (e.g., 0.5/0.5 or 0.45/0.55)
- Lower `fusion_k` (e.g., 30) to give higher RRF scores to top-ranked results from any engine
- Add BM25 weight in `engine_weights` (currently only graph has a weight)

**Confidence:** MEDIUM -- root cause is suspected but not confirmed. The diagnosis path is well-defined; the fix will emerge from instrumented testing.

---

## Installation

```bash
# In backend/
# Add to pyproject.toml dependencies, then:
pip install -e .

# Or directly for testing:
pip install "falkordb>=1.5,<2.0"
```

No system-level changes needed. FalkorDB server is already running.

### Docker Networking Change

```yaml
# In /opt/docker/dotmd/docker-compose.yml, add:
networks:
  embeddings:
    external: true
    name: embeddings_default
  graphiti:          # NEW
    external: true
    name: graphiti_default

services:
  api:
    networks:
      - default
      - embeddings
      - graphiti    # NEW -- enables DNS resolution of "falkordb" hostname
    environment:
      - DOTMD_GRAPH_BACKEND=falkordb          # NEW
      - DOTMD_FALKORDB_URL=redis://falkordb:6379  # NEW -- uses Docker DNS
```

The `falkordb` hostname resolves because the FalkorDB container has alias `falkordb` on the `graphiti_default` network (confirmed via `docker inspect`).

---

## Alternatives Considered

| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `falkordb` (Python client) | `redis-py` with raw `GRAPH.QUERY` commands | Never for this project. The falkordb client wraps Redis protocol and handles result parsing, graph selection, and parameter serialization. Raw redis-py would mean reimplementing all of that. |
| `falkordb` (Python client) | `falkordblite` (embedded FalkorDB) | If the server constraint changes and you want zero-network-dependency. falkordblite is embedded like LadybugDB but with FalkorDB's engine. However, it's very new (v0.0.x) and would defeat the purpose of migrating away from embedded single-connection issues. |
| FalkorDB server (existing) | Neo4j | Never for this project. Neo4j is overkill, requires Java, and has restrictive licensing (AGPL/commercial). FalkorDB is already deployed, Redis-compatible, and purpose-built for graph RAG workloads. |
| FalkorDB server (existing) | Keep LadybugDB with workarounds | Only if FalkorDB migration proves unexpectedly complex. The LadybugDB lock issue was hit 3 times in v1.1 and the single-global-service workaround is fragile. Migration is the right call. |

## What NOT to Use

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `falkordblite` | v0.0.x, too immature for production. Same embedded single-process model as LadybugDB -- would re-introduce the lock problem. | `falkordb` client connecting to existing server |
| `neo4j` Python driver | Different wire protocol, licensing issues, Java dependency | `falkordb` -- already deployed, Redis-based |
| `networkx` for graph operations | In-memory only, no persistence, doesn't scale | FalkorDB for storage + query; protocol pattern for abstraction |
| `pandas` for FalkorDB results | FalkorDB returns list-of-tuples, not DataFrames. Current LadybugDB code uses `.get_as_df()` which drags in pandas for graph ops. | Direct iteration over `result.result_set` |
| Any new BM25 library | The hybrid issue is not a BM25 engine problem -- rank_bm25 returns results correctly in isolation. The issue is in the fusion/reranking pipeline. | Debug existing fusion + reranker logic |

---

## Config Settings to Add

```python
# In Settings class:
graph_backend: Literal["ladybug", "falkordb"] = "falkordb"
falkordb_url: str = "redis://localhost:6379"
falkordb_graph: str = "dotmd"
```

**Why `falkordb_url` as string, not separate host/port:** Follows the same pattern as `embedding_url`. A single URL is easier to configure in Docker environment variables. The falkordb Python client can accept `host` and `port` separately, so the adapter parses the URL.

**Why `falkordb_graph` configurable:** The server hosts multiple graphs (`knowledgebase` for Graphiti, `dotmd` for us). Hardcoding would be fragile.

---

## Version Compatibility

| Package | Version | Compatible With | Notes |
|---------|---------|-----------------|-------|
| `falkordb` (Python) | 1.6.0 | FalkorDB server 4.x, Python 3.10-3.14 | Tested with Redis 8.x wire protocol. Uses `redis-py` internally. |
| `falkordb` (Python) | 1.6.0 | PyTorch <2.5 (existing constraint) | No conflict -- falkordb has no ML dependencies |
| FalkorDB server | 4.16.3 | `falkordb` Python 1.x | Already deployed and tested with Graphiti MCP |
| `rank_bm25` | 0.2.2 | No change | BM25 issue is in fusion pipeline, not the engine |
| `real_ladybug` | current | Will become optional dep | Keep as optional during transition; remove after migration validated |

---

## Sources

- [FalkorDB Python client (PyPI)](https://pypi.org/project/FalkorDB/) -- v1.6.0, Feb 2026, Python >=3.10, MIT license -- HIGH confidence
- [falkordb-py GitHub](https://github.com/FalkorDB/falkordb-py) -- `graph.query(q, params=dict)` API, async support, result_set handling -- HIGH confidence
- [falkordb-py source: graph.py](https://github.com/FalkorDB/falkordb-py/blob/main/falkordb/graph.py) -- `_build_params_header()` uses CYPHER prefix for parameters -- HIGH confidence
- [FalkorDB MERGE docs](https://docs.falkordb.com/cypher/merge.html) -- MERGE + ON CREATE SET + ON MATCH SET confirmed -- HIGH confidence
- [FalkorDB Cypher coverage](https://docs.falkordb.com/cypher/cypher-support.html) -- DETACH DELETE, patterns fully supported -- HIGH confidence
- [FalkorDB MATCH docs](https://docs.falkordb.com/cypher/match.html) -- Variable-length paths `[*min..max]`, undirected matching confirmed -- HIGH confidence
- [FalkorDB Functions docs](https://docs.falkordb.com/cypher/functions.html) -- `labels()` (plural, returns list), `count()`, `type()` confirmed -- HIGH confidence
- [FalkorDB Getting Started](https://docs.falkordb.com/getting-started/) -- `FalkorDB(host, port)`, `db.select_graph(name)` pattern -- HIGH confidence
- Server inspection: `docker inspect graphiti-falkordb-1` -- network `graphiti_default`, alias `falkordb`, Redis 8.2.3, FalkorDB module v4.16.3 -- HIGH confidence
- Codebase inspection: `storage/graph.py`, `storage/base.py`, `search/fusion.py`, `search/reranker.py`, `search/bm25.py`, `api/service.py`, `core/config.py`, `ingestion/pipeline.py` -- PRIMARY source for current architecture -- HIGH confidence

---

*Stack research for: dotMD v1.2 FalkorDB migration + BM25 hybrid fix*
*Researched: 2026-03-26*
