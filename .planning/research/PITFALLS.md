# Domain Pitfalls

**Domain:** FalkorDB graph store migration + BM25 hybrid search fix for existing knowledgebase search system
**Researched:** 2026-03-26
**Confidence:** HIGH -- based on direct codebase analysis, FalkorDB docs, and cross-encoder documentation

---

## Critical Pitfalls

### Pitfall 1: FalkorDB Cypher Dialect Differences Silently Return Wrong Results

**What goes wrong:**
The existing LadybugDB adapter uses `label(b)` (singular) in the `get_neighbors` query (graph.py line 220) to get node labels. FalkorDB's function is `labels(b)` (plural) and returns a **list** not a string. The query `RETURN DISTINCT b.id, label(b)` will fail or return unexpected results. Additionally, LadybugDB uses `CREATE NODE TABLE` / `CREATE REL TABLE` statements for schema -- FalkorDB is schema-free and does not have these commands at all.

**Why it happens:**
LadybugDB is a Kuzu fork with its own Cypher dialect. FalkorDB implements openCypher but with its own subset. Developers assume "both speak Cypher" means identical syntax. The differences are subtle enough that some queries work and others silently produce wrong results.

**Specific dialect differences found:**

| Feature | LadybugDB (current) | FalkorDB | Action needed |
|---------|---------------------|----------|---------------|
| Schema DDL | `CREATE NODE TABLE IF NOT EXISTS File(...)` | Not needed -- schema-free, nodes have labels | Remove all `_SCHEMA_INIT` statements |
| Node label function | `label(n)` (returns string) | `labels(n)` (returns list of strings) | Change to `labels(n)[0]` or iterate |
| Relationship tables | `CREATE REL TABLE FILE_SECTION(FROM File TO Section, ...)` | Not needed -- relationships are just `[:REL_TYPE]` | Simplify edge creation |
| `_REL_TABLE_MAP` lookup | Required -- edges must use named rel tables | Not needed -- `MERGE (a)-[:HAS_SECTION]->(b)` works directly | Eliminate the lookup entirely |
| `_find_node_label` | Iterates 4 node tables to find which table has an ID | Query any node by ID: `MATCH (n {id: $id}) RETURN labels(n)` | Single query replaces 4 |
| Parameters | `parameters={"id": value}` | `params={"id": value}` in falkordb-py client | Check API signature |
| Variable-length paths | `[r* 1..N]` | `[*1..N]` (same syntax, confirmed in docs) | Works as-is |
| MERGE | Supported | Supported with same semantics | Works as-is |
| DETACH DELETE | Supported | Supported (auto-cascading) | Works as-is |

**Consequences:**
Schema init fails on first connection. Queries using `label()` return errors. Edge creation via `_REL_TABLE_MAP` fails because those table names don't exist in FalkorDB. The adapter appears broken on every single write and most reads.

**Prevention:**
Write the FalkorDB adapter from scratch using the Protocol interface rather than adapting the LadybugDB code. The schema-free nature of FalkorDB means **half of the existing adapter code is unnecessary** -- no schema init, no `_REL_TABLE_MAP`, no `_find_node_label` 4-query scan. Test every Cypher query against the actual FalkorDB instance before considering the adapter done.

**Detection:**
Any call to `add_file_node`, `add_edge`, or `get_neighbors` will raise immediately if dialect issues exist. Run the full graph population on a small test set (3 files) before attempting a 227-file re-index.

**Phase to address:** Phase 1 -- FalkorDB adapter. This is the core of the migration.

---

### Pitfall 2: BM25 Results Vanish After Reranker -- Score Threshold Kills Keyword Matches

**What goes wrong:**
BM25 results appear in `engine_results["bm25"]` and survive RRF fusion, but disappear from final output. The cross-encoder `ms-marco-MiniLM-L-6-v2` outputs raw logits, not probabilities. Its score range is approximately -11 to +10, with most irrelevant pairs scoring around -8 to -10. The current `score_threshold` of -8.0 (reranker.py line 44, config.py line 63) filters out results that the cross-encoder considers marginal -- but BM25 keyword matches are often **exactly the kind of result** that cross-encoders undervalue. A query for a specific technical term (e.g., "LadybugDB") matches perfectly via BM25 but may score -7.5 on the cross-encoder because the surrounding context doesn't read like a natural question-answer pair.

**Root cause analysis from code:**

1. `service.py` line 188: `if bm25_hits:` -- this check is correct, BM25 hits enter fusion
2. `service.py` line 195: `fuse_results()` -- RRF merges correctly, BM25-only results get score `1/(60+rank)`
3. `service.py` line 203: `chunk_ids = [cid for cid, _ in fused[:pool_size]]` -- pool_size=20, so top 20 fused results go to reranker
4. `reranker.py` line 128-132: `if score >= self._score_threshold` -- **HERE** -- results scoring below -8.0 are dropped entirely
5. `service.py` line 212: `if reranked:` -- if the reranker drops BM25-only results, they vanish from the blended output
6. `service.py` line 227: `blended.append((cid, 0.4 * norm_f + 0.6 * norm_re))` -- blending uses only reranked results, not the full fused set

**The kill chain:**
BM25 finds chunk X (exact keyword match, high BM25 score). RRF ranks X in the top 20. Reranker scores X at -8.5 (below threshold). X is dropped from `reranked` list. Blending loop only iterates over `reranked`, so X is gone. Final `fused[:top_k]` at line 233 uses the `blended` list, not the original fusion. X never appears in results.

**Why it happens:**
The ms-marco model was trained on natural language question-passage pairs from MS MARCO. Technical documentation, code snippets, and bilingual RU/EN voicenote transcripts don't match this distribution. Cross-encoder scores for these texts are systematically lower than for clean English prose. The -8.0 threshold was set without testing against the actual corpus.

**Prevention:**
Three fixes, apply all:
1. **Lower or remove the score threshold.** Set `rerank_score_threshold` to -11.0 or remove filtering entirely. The reranker's job is to **reorder**, not to **filter**. Let RRF handle relevance gating.
2. **Preserve non-reranked results as fallback.** After reranking, if a chunk from the fused top-K was dropped by the reranker, append it to the blended list with its original RRF score (penalized) rather than discarding it entirely.
3. **Log per-engine attribution.** Add debug logging showing which engine found each result and whether the reranker kept or dropped it. Without this, the "BM25 results missing" symptom is nearly impossible to diagnose.

**Detection:**
Run `dotmd search "LadybugDB" --mode bm25` and `dotmd search "LadybugDB" --mode hybrid`. If BM25-only mode returns results but hybrid mode drops them, the reranker threshold is the cause. Check reranker scores in debug logs.

**Phase to address:** Phase 2 -- BM25 hybrid fix. This is the primary search quality issue.

---

### Pitfall 3: Shared FalkorDB Instance -- Graph Name Collision With "knowledgebase"

**What goes wrong:**
FalkorDB on this server (`graphiti-falkordb-1`) already contains a graph named `knowledgebase` (used by the Graphiti knowledge graph service). If the adapter accidentally uses the wrong graph name, or if a query is sent without specifying the graph name, it operates on the `knowledgebase` graph -- corrupting the Graphiti data or returning wrong results for dotMD.

**Why it happens:**
FalkorDB uses Redis protocol. The `falkordb-py` client's `select_graph("dotmd")` must be called to scope queries. But if the adapter is written using raw Redis commands (`GRAPH.QUERY graphname "..."`) and the graph name is misconfigured, or if a developer hardcodes `"knowledgebase"` while testing, the wrong graph is mutated. There is no namespace isolation beyond the graph name string.

**Consequences:**
- **Mild:** dotMD searches return Graphiti knowledge graph nodes (different schema, meaningless results)
- **Severe:** dotMD's `delete_all()` runs `MATCH (n) DETACH DELETE n` on the `knowledgebase` graph, destroying Graphiti's data
- **Subtle:** Both graphs have entity nodes with similar names (e.g., "Python", "Docker") -- cross-contamination produces plausible-looking but wrong graph traversals

**Prevention:**
- Make graph name a **required** config parameter (`DOTMD_FALKORDB_GRAPH`), not a default
- Add a startup assertion that verifies the graph name is `"dotmd"` and is NOT `"knowledgebase"`
- Never use `GRAPH.LIST` results to auto-select a graph
- Integration test: after indexing, verify `GRAPH.LIST` shows exactly `["knowledgebase", "dotmd"]` -- not fewer, not more

**Detection:**
`docker exec graphiti-falkordb-1 redis-cli GRAPH.LIST` should always show both graphs. If only one appears after a dotMD operation, something was written to the wrong graph.

**Phase to address:** Phase 1 -- adapter configuration. The graph name must be set before any queries are written.

---

### Pitfall 4: Docker Networking -- dotMD Container Can't Reach FalkorDB

**What goes wrong:**
The dotMD container is on `default` and `embeddings_default` networks. FalkorDB is on `graphiti_default` network. They cannot reach each other. The adapter connects to `falkordb:6379` and gets a connection refused or timeout.

**Current network topology:**
```
dotmd-api-1:       [dotmd_default, embeddings_default]
graphiti-falkordb-1: [graphiti_default]
```

These networks are isolated. DNS resolution of `falkordb` from the dotMD container fails.

**Why it happens:**
Docker Compose creates per-project networks. Services on different networks can only communicate if they share an external network. The dotMD compose already does this for embeddings (`embeddings_default` as external). The same pattern must be applied for `graphiti_default`.

**Prevention:**
Add to dotMD's production `docker-compose.yml`:
```yaml
networks:
  graphiti:
    external: true
    name: graphiti_default
```
And add `graphiti` to the `api` service's `networks` list. The FalkorDB container's DNS alias is `falkordb` on the `graphiti_default` network (confirmed via `docker inspect`).

Set `DOTMD_FALKORDB_URL=redis://falkordb:6379` in the environment.

**Detection:**
From inside the dotMD container: `python -c "import socket; socket.create_connection(('falkordb', 6379), timeout=3)"`. If this times out, networking is not configured.

**Phase to address:** Phase 1 -- infrastructure setup, before adapter testing.

---

## Moderate Pitfalls

### Pitfall 5: Reranker Score Blending Erases Per-Engine Score Attribution

**What goes wrong:**
After reranking, `service.py` lines 212-229 replace the `fused` list with `blended` -- a new list of `(chunk_id, blended_score)`. But `build_search_results()` at line 232 receives `fused[:top_k]` (the blended list) and `per_engine=engine_results` (original per-engine scores). The `SearchResult.fused_score` field now contains the blended score, but `matched_engines` and individual `semantic_score`/`bm25_score`/`graph_score` fields still reflect the pre-rerank engine results. This is technically correct but confusing -- a result can show `bm25_score=4.5` but have been dropped from the blended list if the reranker killed it, yet it appears in results if it survived because a different code path kept it.

More importantly: if the reranker drops a result, that result's per-engine scores are **never surfaced to the user**, making it invisible that BM25 found relevant content.

**Prevention:**
When fixing the BM25 hybrid issue, add a `reranker_score` field to `SearchResult` and populate it from the reranker output. Also add a `dropped_by_reranker: bool` field (or equivalent) so the UI/CLI can show "BM25 found this but reranker disagreed".

**Phase to address:** Phase 2 -- alongside the BM25 fix.

---

### Pitfall 6: FalkorDB Connection Not Resilient -- No Retry on Redis Timeout

**What goes wrong:**
The falkordb-py client uses the Redis protocol. If FalkorDB is temporarily unavailable (container restart, OOM kill, slow GC pause), every graph operation fails with a `ConnectionError` or `TimeoutError`. The current LadybugDB adapter has no retry logic (it's embedded, so connection failures mean disk errors). Carrying this pattern to FalkorDB means a single FalkorDB hiccup during a 59-minute re-index kills the entire run.

**Why it happens:**
Network services fail transiently. Redis connections drop. FalkorDB may be processing a heavy query from Graphiti while dotMD tries to connect. Without retry logic, the first failure is fatal.

**Prevention:**
- Use `BlockingConnectionPool` with `max_connections=4`, `timeout=10`, `socket_keepalive=True`
- Wrap graph store methods in a retry decorator (3 attempts, exponential backoff: 1s, 2s, 4s)
- On connection failure during indexing, log a warning and continue with remaining stores -- a failed graph write is recoverable via re-index, not worth aborting the entire pipeline

**Phase to address:** Phase 1 -- adapter implementation. Build retry into the adapter from the start.

---

### Pitfall 7: `get_neighbors` Performance -- FalkorDB Variable-Length Paths Without Indexes

**What goes wrong:**
The `get_neighbors` query uses `MATCH (a {id: $id})-[*1..2]-(b)` -- an untyped, undirected, variable-length path pattern. In FalkorDB this traverses **all** relationship types in **both** directions for up to 2 hops. On the current graph (19,667 edges), this is a full graph scan from the starting node. FalkorDB uses GraphBLAS sparse matrices, which are efficient for this, but without an index on the `id` property, finding node `a` requires a sequential scan of all nodes first.

**Why it happens:**
LadybugDB (Kuzu) automatically creates primary key indexes. FalkorDB requires explicit `CREATE INDEX` statements. The schema-free nature means no automatic indexing.

**Prevention:**
After creating the graph, run:
```cypher
CREATE INDEX FOR (n:File) ON (n.id)
CREATE INDEX FOR (n:Section) ON (n.id)
CREATE INDEX FOR (n:Entity) ON (n.id)
CREATE INDEX FOR (n:Tag) ON (n.id)
```
These must be created once and persist across container restarts (FalkorDB persists indexes). Add index creation to the adapter's `__init__` or a dedicated `ensure_indexes()` method.

**Detection:**
Time `get_neighbors` calls. Without indexes: O(N) where N is total nodes. With indexes: O(degree * hops). On 3,456 entities, the difference is measurable.

**Phase to address:** Phase 1 -- adapter implementation. Create indexes at adapter initialization.

---

### Pitfall 8: `_find_node_label` Pattern Must Be Redesigned, Not Ported

**What goes wrong:**
The LadybugDB adapter's `add_edge` method calls `_find_node_label()` which runs 4 sequential queries (one per node type) to determine what label a node has. This was necessary because LadybugDB requires knowing the source/target table names for `CREATE REL TABLE`. FalkorDB doesn't need this -- edges are just `MERGE (a)-[:TYPE]->(b)` regardless of node labels. But a naive port copies this expensive pattern.

**Consequences at scale:**
During the initial graph population of 227 files with 19,667 edges, `add_edge` is called ~20,000 times. If `_find_node_label` is ported, that's 160,000 queries to FalkorDB over the network (vs. in-process for LadybugDB). At 1ms per Redis round-trip, that's 160 seconds of pure latency -- vs. ~10 minutes total for the current embedded implementation.

**Prevention:**
In the FalkorDB adapter, `add_edge` should MERGE by matching nodes directly:
```cypher
MATCH (a {id: $src}), (b {id: $tgt})
MERGE (a)-[r:RELATES]->(b)
SET r.rel_type = $rel_type, r.weight = $weight
```
No label lookup needed. FalkorDB matches by `id` property across all labels. If `a` or `b` doesn't exist, the MATCH returns empty and no edge is created (same behavior as current adapter's `if src_label is None` guard).

**Phase to address:** Phase 1 -- adapter implementation. Design the adapter around FalkorDB's strengths, not LadybugDB's constraints.

---

### Pitfall 9: Pipeline Hardcodes `LadybugDBGraphStore` -- No Backend Abstraction

**What goes wrong:**
`pipeline.py` line 87 directly instantiates `LadybugDBGraphStore`. The `graph_store` property (line 469) returns type `LadybugDBGraphStore`, not `GraphStoreProtocol`. The `DotMDService` constructs `GraphSearchEngine` with the pipeline's graph store, which works via duck typing, but there is no configuration switch like `vector_backend` to select between graph backends.

Adding FalkorDB as an option requires:
1. A `graph_backend` config setting (like `vector_backend`)
2. A factory function in `pipeline.py` (like `_create_vector_store`)
3. Changing the `graph_store` property return type to `GraphStoreProtocol`
4. FalkorDB-specific config: URL, graph name, optional password

**Why it's a pitfall:**
If you write the FalkorDB adapter but forget to update the pipeline factory, it's never used. If you update the factory but the property type annotation still says `LadybugDBGraphStore`, type checkers flag downstream code. If you add config but docker-compose doesn't set it, the default falls back to LadybugDB silently.

**Prevention:**
Follow the exact pattern established for `vector_backend`:
- Add `graph_backend: Literal["ladybugdb", "falkordb"] = "ladybugdb"` to Settings
- Add `falkordb_url: str = "redis://localhost:6379"` and `falkordb_graph: str = "dotmd"` to Settings
- Write `_create_graph_store(settings) -> GraphStoreProtocol` factory
- Update `graph_store` property return type to `GraphStoreProtocol`
- Update docker-compose with `DOTMD_GRAPH_BACKEND=falkordb` and `DOTMD_FALKORDB_URL`

**Phase to address:** Phase 1 -- config and pipeline integration.

---

### Pitfall 10: Re-Index Required But 59 Minutes on This Hardware

**What goes wrong:**
Switching from LadybugDB to FalkorDB requires rebuilding the graph from scratch (the data formats are incompatible). The current full re-index takes ~59 minutes (25min embedding + 18min NER + 10min graph + overhead). During this time, the search service is partially functional (semantic and BM25 work, graph search returns nothing until graph is populated).

**Why it matters:**
If the re-index fails at minute 45 (FalkorDB connection drops, OOM, etc.), 45 minutes of work is lost. The graph store is empty but metadata and vectors are populated. The system is in an inconsistent state.

**Prevention:**
- **Embedding and NER are already done** -- the current vectors and metadata are valid and don't need rebuilding. Only the graph needs repopulation.
- Write a **graph-only re-index** command that reads chunks from metadata, re-runs extraction, and populates the new FalkorDB graph without touching vectors or BM25. This reduces the re-index from 59 minutes to ~28 minutes (NER + graph population).
- Better yet: if extraction results are cached (they aren't currently), skip NER entirely and just repopulate the graph from stored entities/relations. This would take ~10 minutes.
- Run the re-index overnight with `nohup` or via a systemd timer.

**Phase to address:** Phase 1 -- migration planning. Decide the re-index strategy before writing the adapter.

---

## Minor Pitfalls

### Pitfall 11: `get_graph_data()` Is Not in the Protocol

**What goes wrong:**
`LadybugDBGraphStore.get_graph_data()` is called by `DotMDService.graph_data()` (service.py line 276) but `get_graph_data` is not part of `GraphStoreProtocol` in `base.py`. The FalkorDB adapter won't be required to implement it by the Protocol, but the service will crash at runtime when calling it.

**Prevention:**
Either add `get_graph_data()` to `GraphStoreProtocol` or handle it as an optional method with `hasattr()` check. Adding it to the Protocol is cleaner.

**Phase to address:** Phase 1 -- Protocol update.

---

### Pitfall 12: FalkorDB Memory on 16GB Shared Server

**What goes wrong:**
FalkorDB currently uses ~10MB RSS for the `knowledgebase` graph. The dotMD graph has 3,456 entities and 19,667 edges -- roughly 4x the knowledgebase graph. Expected memory: ~40-50MB additional. This is fine. But if the graph grows significantly (more files, denser NER extraction), FalkorDB and TEI (2.6GB) and the dotMD container together may pressure the 16GB limit.

**Prevention:**
Monitor `docker stats` after re-index. Set `maxmemory` on the FalkorDB Redis instance if needed. The current scale (227 files, ~20K edges) is well within limits.

**Phase to address:** Not blocking; monitor during Phase 1 testing.

---

## Phase-Specific Warnings

| Phase Topic | Likely Pitfall | Mitigation |
|-------------|---------------|------------|
| FalkorDB adapter implementation | Porting LadybugDB Cypher verbatim (Pitfall 1) | Write from scratch against Protocol, test each query |
| FalkorDB adapter implementation | Porting `_find_node_label` N-query pattern (Pitfall 8) | Use label-agnostic MATCH for edges |
| FalkorDB adapter implementation | No indexes on id property (Pitfall 7) | `CREATE INDEX` in adapter init |
| Config + pipeline integration | Pipeline hardcodes LadybugDB (Pitfall 9) | Follow vector_backend pattern exactly |
| Docker networking | Containers on different networks (Pitfall 4) | Add graphiti_default as external network |
| Graph name safety | Collision with knowledgebase graph (Pitfall 3) | Config validation, startup assertion |
| BM25 hybrid fix | Reranker threshold killing BM25 results (Pitfall 2) | Lower threshold, preserve dropped results |
| BM25 hybrid fix | Score attribution lost after blending (Pitfall 5) | Add reranker_score field to SearchResult |
| Migration re-index | 59-minute full re-index risk (Pitfall 10) | Graph-only re-index, run overnight |
| Connection resilience | No retry on Redis timeout (Pitfall 6) | Connection pool + retry decorator |

---

## "Looks Done But Isn't" Checklist (v1.2)

- [ ] **FalkorDB adapter:** After indexing 3 test files, `GRAPH.QUERY dotmd "MATCH (n) RETURN count(n)"` returns expected node count -- not zero, not in the knowledgebase graph
- [ ] **Graph name isolation:** `GRAPH.QUERY knowledgebase "MATCH (n) RETURN count(n)"` returns same count as before dotMD migration -- Graphiti data untouched
- [ ] **Neighbor traversal:** `get_neighbors("some_chunk_id")` returns Section nodes reachable via Entity nodes, not Entity/Tag/File nodes directly
- [ ] **Index creation:** `GRAPH.QUERY dotmd "CALL db.indexes()"` shows indexes on all node labels
- [ ] **BM25 in hybrid:** `dotmd search "specific_term" --mode hybrid` returns results that include `bm25` in `matched_engines`
- [ ] **Reranker preservation:** Results with `bm25_score` set but low reranker score still appear (with lower ranking, not absent)
- [ ] **Network connectivity:** `dotmd search` from Docker returns graph results, not just semantic+BM25
- [ ] **Concurrent access:** Run `POST /index` while `GET /search` is in-flight -- no connection errors, no data corruption
- [ ] **Container restart recovery:** Restart FalkorDB container, verify dotMD reconnects automatically on next query

---

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| Wrong graph name (wrote to knowledgebase) | HIGH | Restore Graphiti data from backup; drop dotmd graph if created; fix config; re-index |
| Reranker kills all BM25 results | LOW | Change `DOTMD_RERANK_SCORE_THRESHOLD=-11` in env; restart container |
| FalkorDB connection lost mid-index | MEDIUM | Graph partially populated; run graph-only re-index |
| No indexes, slow graph search | LOW | Run `CREATE INDEX` statements manually via redis-cli; adapter restart creates them |
| Docker networking not configured | LOW | Add network to docker-compose.yml; `docker compose up -d` |
| Pipeline still using LadybugDB | LOW | Set `DOTMD_GRAPH_BACKEND=falkordb` in env; restart; verify via graph_data endpoint |

---

## Sources

- Direct analysis of `backend/src/dotmd/storage/graph.py` -- LadybugDB adapter, `label()` usage, `_REL_TABLE_MAP`, `_find_node_label` pattern
- Direct analysis of `backend/src/dotmd/api/service.py` -- reranker blending logic, BM25 kill chain (lines 186-233)
- Direct analysis of `backend/src/dotmd/search/reranker.py` -- score threshold filtering (line 128-132)
- Direct analysis of `backend/src/dotmd/ingestion/pipeline.py` -- hardcoded `LadybugDBGraphStore` (line 87)
- Direct analysis of `backend/src/dotmd/core/config.py` -- missing graph_backend config
- [FalkorDB Cypher known limitations](https://docs.falkordb.com/cypher/known-limitations.html) -- LIMIT/eager ops, index limitations
- [FalkorDB MERGE docs](https://docs.falkordb.com/cypher/merge.html) -- full path matching, duplicate node creation risk
- [FalkorDB MATCH docs](https://docs.falkordb.com/cypher/match.html) -- variable-length path syntax confirmed
- [FalkorDB functions docs](https://docs.falkordb.com/cypher/functions.html) -- `labels()` (plural), not `label()`
- [FalkorDB Python client](https://github.com/FalkorDB/falkordb-py) -- `select_graph()`, `query()`, `ro_query()`, async support
- [FalkorDB Cypher coverage](https://docs.falkordb.com/cypher/cypher-support.html) -- subset of openCypher, parameterized queries
- [cross-encoder/ms-marco-MiniLM-L-6-v2 score range issue](https://github.com/huggingface/sentence-transformers/issues/1058) -- raw logits, negative scores normal, ranking-only not filtering
- [Hybrid search fusion best practices](https://ashutoshkumars1ngh.medium.com/hybrid-search-done-right-fixing-rag-retrieval-failures-using-bm25-hnsw-reciprocal-rank-fusion-a73596652d22) -- RRF over score combination
- Production docker-compose at `/opt/docker/dotmd/docker-compose.yml` -- network topology
- `docker inspect graphiti-falkordb-1` -- network aliases, IP, DNS names
- `docker exec graphiti-falkordb-1 redis-cli GRAPH.LIST` -- confirms `knowledgebase` graph exists
- `docker exec graphiti-falkordb-1 redis-cli INFO memory` -- 10MB RSS current usage
- `.planning/RETROSPECTIVE.md` -- LadybugDB lock hit 3 times in v1.1
- `.planning/todos/pending/2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` -- migration strategy notes

---
*Pitfalls research for: dotMD v1.2 FalkorDB migration + BM25 hybrid fix*
*Researched: 2026-03-26*
