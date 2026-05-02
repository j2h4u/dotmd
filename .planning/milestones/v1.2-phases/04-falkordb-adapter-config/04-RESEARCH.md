# Phase 4: FalkorDB Adapter + Config - Research

**Researched:** 2026-03-26
**Domain:** FalkorDB graph database Python client, Cypher dialect, storage protocol implementation, config-driven backend selection
**Confidence:** HIGH

## Summary

Phase 4 introduces a FalkorDB graph store adapter that implements the existing `GraphStoreProtocol` and adds config-driven backend selection so users can switch between LadybugDB (embedded, current default) and FalkorDB (Redis-protocol, network-accessible) via a single environment variable.

FalkorDB is already running on this server as `graphiti-falkordb-1` on `graphiti_default` network (port 6379, Redis protocol). It hosts a `knowledgebase` graph for Graphiti; dotmd will create a separate `dotmd` graph on the same instance. The Python client (`falkordb` v1.6.0, MIT, production-stable) provides a clean API: `FalkorDB(host, port)` -> `db.select_graph("dotmd")` -> `graph.query("CYPHER ...", params={...})`. FalkorDB is schema-less (unlike LadybugDB which requires `CREATE NODE TABLE`), so the adapter is structurally simpler -- nodes and edges are created via MERGE with labels and properties directly.

Key architectural difference from LadybugDB: FalkorDB does not require explicit relationship table declarations. LadybugDB needed 7 `CREATE REL TABLE` statements mapping specific FROM/TO node types. FalkorDB uses Neo4j-style relationships where any node can connect to any other node with any relationship type. This eliminates the `_REL_TABLE_MAP` lookup and `_find_node_label` helper entirely -- edges are created by matching source and target nodes directly and MERGEing the relationship.

**Primary recommendation:** Write `FalkorDBGraphStore` from scratch (not by porting LadybugDB code). Use MERGE for all upserts, `$param` syntax for parameterized queries, and `labels()` (plural, returns list) instead of LadybugDB's `label()`. Add `graph_backend`, `falkordb_url`, `falkordb_graph_name` to Settings. Add `_create_graph_store()` factory in pipeline.py following the existing `_create_vector_store()` pattern.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRAPH-01 | FalkorDB adapter implementing GraphStoreProtocol (new storage/falkordb_graph.py, written from scratch) | FalkorDB Python client v1.6.0 provides `graph.query()` with `params` dict. Schema-less design means no table declarations needed. All 12 protocol methods can be implemented with parameterized Cypher MERGE/MATCH/DELETE. See Code Examples section. |
| GRAPH-02 | Config settings for graph backend selection (`graph_backend`, `falkordb_url`, `falkordb_graph_name`) | Add to `Settings` class as `graph_backend: Literal["ladybugdb", "falkordb"]`, `falkordb_url: str = "redis://localhost:6379"`, `falkordb_graph_name: str = "dotmd"`. Follow existing `vector_backend` pattern. |
| GRAPH-03 | Pipeline factory selects graph backend based on config (follow existing `_create_vector_store` pattern) | Add `_create_graph_store(settings)` function in pipeline.py. Change `graph_store` property return type from `LadybugDBGraphStore` to `GraphStoreProtocol`. Add `get_graph_data()` to protocol. |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- **SOLID principles**: Protocol-based abstractions for storage. New adapter MUST implement `GraphStoreProtocol` from `storage/base.py`.
- **UI-agnostic API**: All public APIs go through `api/service.py` -- never expose internals directly. Backend selection is config-driven, transparent to CLI/API callers.
- **Never reload indexes per-request**: FalkorDB connection must be established once at init and reused. No per-query `FalkorDB()` instantiation.
- **New storage backends**: Implement the Protocol from `storage/base.py`.
- **Python 3.12+**, **Pydantic v2**, **src layout**, **hatchling build**.
- **Containers first**: FalkorDB runs in Docker. Python client connects over network (Redis protocol), no host installation needed.

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| falkordb | 1.6.0 | FalkorDB Python client (sync API) | Official client, MIT, production-stable. Uses Redis protocol under the hood. `graph.query()` with `params` dict for parameterized Cypher. |
| pydantic-settings | >=2.0 | Config with env vars | Already used. New settings (`graph_backend`, `falkordb_url`, `falkordb_graph_name`) added to existing `Settings` class. |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| redis | (transitive) | Connection transport | Pulled in by `falkordb` automatically. Provides connection pooling, retry, keepalive. |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| falkordb (sync) | falkordb.asyncio | Async API exists but entire dotmd pipeline is synchronous. Mixing async adds complexity for no benefit. |
| falkordb | falkordblite | Embedded zero-config option, BUT defeats the purpose of migration -- LadybugDB lock issues are because of embedded DB. Network FalkorDB allows concurrent CLI + API access. |
| falkordb | redis-py raw commands | Lower level, would need to build Cypher query handling manually. Official client handles GRAPH.QUERY protocol. |

**Installation:**
```bash
pip install FalkorDB>=1.6.0
```

**Version verification:** FalkorDB 1.6.0 released 2026-02-21 (confirmed via PyPI). Python >=3.10 required (project uses 3.12+, compatible).

## Architecture Patterns

### Recommended Project Structure

```
backend/src/dotmd/
├── storage/
│   ├── base.py              # GraphStoreProtocol (add get_graph_data)
│   ├── graph.py              # LadybugDBGraphStore (unchanged)
│   ├── falkordb_graph.py     # NEW: FalkorDBGraphStore
│   ├── ...
├── core/
│   ├── config.py             # Settings (add graph_backend, falkordb_url, falkordb_graph_name)
├── ingestion/
│   ├── pipeline.py           # Add _create_graph_store() factory, change type annotation
├── api/
│   ├── service.py            # No changes (uses protocol, transparent)
```

### Pattern 1: Config-Driven Factory (follow `_create_vector_store`)

**What:** A module-level factory function that instantiates the correct backend based on config.
**When to use:** When multiple backends implement the same protocol.
**Example:**
```python
# Source: existing pattern in pipeline.py lines 56-65
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

### Pattern 2: Parameterized Cypher with $params

**What:** FalkorDB uses `$param_name` syntax in Cypher, with params passed as dict to `graph.query()`.
**When to use:** All graph mutations and queries -- never use f-strings for values.
**Example:**
```python
# Source: FalkorDB Python client docs + falkordb-py source
from falkordb import FalkorDB

db = FalkorDB(host="falkordb", port=6379)
graph = db.select_graph("dotmd")

# MERGE with params (upsert)
graph.query(
    "MERGE (f:File {id: $id}) SET f.title = $title, f.checksum = $checksum",
    params={"id": "/path/to/file.md", "title": "My File", "checksum": "abc123"},
)

# Read query
result = graph.ro_query(
    "MATCH (s:Section {file_path: $fp}) RETURN s.id, s.heading",
    params={"fp": "/path/to/file.md"},
)
for row in result.result_set:
    print(row[0], row[1])
```

### Pattern 3: Schema-Less Node/Edge Creation (vs LadybugDB)

**What:** FalkorDB does not need `CREATE NODE TABLE` or `CREATE REL TABLE`. Nodes with labels and relationships are created on the fly via MERGE/CREATE.
**When to use:** Eliminates the entire `_SCHEMA_INIT` + `_REL_TABLE_MAP` + `_find_node_label` pattern from LadybugDB.
**Example:**
```python
# LadybugDB (old) -- requires explicit table declarations
_SCHEMA_INIT = [
    "CREATE NODE TABLE IF NOT EXISTS File(id STRING, ...)",
    "CREATE REL TABLE IF NOT EXISTS FILE_SECTION(FROM File TO Section, ...)",
]

# FalkorDB (new) -- just MERGE directly
graph.query(
    "MERGE (f:File {id: $id}) SET f.title = $title",
    params={"id": path, "title": title},
)
# Edges: match both endpoints, MERGE the relationship
graph.query(
    "MATCH (f:File {id: $src}), (s:Section {id: $tgt}) "
    "MERGE (f)-[r:CONTAINS]->(s) SET r.weight = $weight",
    params={"src": file_path, "tgt": chunk_id, "weight": 1.0},
)
```

### Pattern 4: Robust add_edge Without _find_node_label

**What:** LadybugDB requires looking up which table a node belongs to before creating an edge (because REL TABLEs have explicit FROM/TO types). FalkorDB has no such constraint -- but we still need to know which labels to MATCH for the edge endpoints.
**When to use:** The `add_edge` method, which receives generic `source_id` and `target_id` strings.
**Example:**
```python
# Strategy: try each label combination. FalkorDB's MERGE on a MATCH
# that finds 0 rows simply does nothing (no error).
# But more efficient: use label-agnostic MATCH with WHERE.
graph.query(
    "MATCH (a {id: $src}), (b {id: $tgt}) "
    "MERGE (a)-[r:REL {rel_type: $rel_type}]->(b) "
    "SET r.weight = $weight",
    params={"src": source_id, "tgt": target_id, "rel_type": relation_type, "weight": weight},
)
```
**Performance note:** Label-less MATCH scans all nodes. For the dotmd graph (~3.5K entities, ~20K edges) this is acceptable. If performance degrades, add indexes on `id` properties per label (see Pitfall 3).

### Anti-Patterns to Avoid

- **F-string Cypher queries:** Never `f"MERGE (f:File {{id: '{path}'}})"`. Always use `params={}` -- prevents injection and enables query plan caching.
- **Per-query connection:** Never `FalkorDB(host, port)` inside each method call. The connection is established once in `__init__` and the graph object is reused.
- **Porting LadybugDB code:** The adapter MUST be written from scratch (per REQUIREMENTS.md decision). LadybugDB's schema-heavy Cypher dialect, `_REL_TABLE_MAP`, `get_as_df()`, and pandas dependency do not apply to FalkorDB.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Redis connection management | Custom socket/retry logic | `falkordb` client (wraps `redis-py`) | Handles reconnection, connection pooling, health checks automatically |
| Cypher parameter escaping | String interpolation/escaping | `graph.query(q, params={})` | Built-in parameterization with `$param` syntax, query plan caching |
| Graph schema migration | DDL scripts, migration tool | Nothing -- FalkorDB is schema-less | Nodes and edges are created on the fly; no CREATE TABLE needed |
| Connection health check | Ping/retry wrapper | `redis-py` `retry_on_timeout=True` | Built into the transport layer |

## Common Pitfalls

### Pitfall 1: labels() vs label() Function

**What goes wrong:** LadybugDB's `get_neighbors` uses `label(b)` (singular) which returns a string. FalkorDB uses `labels(b)` (plural) which returns a **list** of strings.
**Why it happens:** Different Cypher dialect -- FalkorDB follows Neo4j convention.
**How to avoid:** Always use `labels(b)` and take `[0]` if you need a single label string. Or better: return `b.id` and the label is implicit from the node type you matched.
**Warning signs:** `Unknown function: label` error at runtime.

### Pitfall 2: MERGE on Relationships Requires Both Endpoints to Exist

**What goes wrong:** `MERGE (a:File {id: $src})-[r:CONTAINS]->(b:Section {id: $tgt})` will CREATE new nodes if either endpoint is missing, leading to duplicate nodes without all properties.
**Why it happens:** MERGE on a full path creates the entire path if any part doesn't match.
**How to avoid:** Always split into MATCH + MERGE: `MATCH (a:File {id: $src}), (b:Section {id: $tgt}) MERGE (a)-[r:CONTAINS]->(b)`. If MATCH finds nothing, the entire query is a no-op (safe).
**Warning signs:** Duplicate nodes with only the `id` property, missing `title`/`heading` etc.

### Pitfall 3: Label-Less MATCH Performance on Large Graphs

**What goes wrong:** `MATCH (a {id: $src})` without a label scans ALL nodes. For ~3.5K nodes this is fast (~ms). For larger graphs, it degrades linearly.
**Why it happens:** FalkorDB can only use indexes when a label is specified in the MATCH pattern.
**How to avoid:** Create range indexes on each node label's `id` property: `CREATE INDEX FOR (f:File) ON (f.id)`, etc. For the current dataset size, this is optimization -- not blocking.
**Warning signs:** `get_neighbors` or `add_edge` taking >100ms per call.

### Pitfall 4: FalkorDB Deletes All Relationships on Node Delete

**What goes wrong:** Unlike Neo4j which requires explicit `DETACH DELETE`, FalkorDB's `DELETE` automatically removes all connected relationships. Both `DELETE` and `DETACH DELETE` work the same way.
**Why it happens:** FalkorDB docs: "Deleting a node automatically deletes all of its incoming and outgoing relationships."
**How to avoid:** This is actually convenient for `delete_file_subgraph` -- just `MATCH (s:Section {file_path: $fp}) DELETE s` works. Use `DETACH DELETE` anyway for clarity and forward compatibility.
**Warning signs:** None -- this is a simplification, not a problem.

### Pitfall 5: Separate Graph Name from Graphiti

**What goes wrong:** Both dotmd and Graphiti use the same FalkorDB instance. If they use the same graph name, data collides.
**Why it happens:** Default graph name collision.
**How to avoid:** dotmd uses `falkordb_graph_name = "dotmd"` (configurable). Graphiti uses `knowledgebase`. Verify graph names are different in config. Document the convention.
**Warning signs:** Unexpected nodes/edges appearing in search results.

### Pitfall 6: get_graph_data() Not in Protocol

**What goes wrong:** `DotMDService.graph_data()` calls `self._pipeline.graph_store.get_graph_data()` but this method is NOT defined in `GraphStoreProtocol`. If the pipeline returns the protocol type, mypy/pyright will flag this.
**Why it happens:** `get_graph_data()` was added to LadybugDB implementation without updating the protocol.
**How to avoid:** Add `get_graph_data() -> dict` to `GraphStoreProtocol`. Both LadybugDB and FalkorDB must implement it.
**Warning signs:** Type checker errors, AttributeError at runtime.

### Pitfall 7: Connection Failure on Init

**What goes wrong:** If FalkorDB is unreachable when dotmd starts (container not running, network issue), `FalkorDB(host, port)` raises `ConnectionError` immediately, crashing the entire service.
**Why it happens:** `graph_backend=falkordb` but container is down.
**How to avoid:** Catch `ConnectionError` in the factory, log a clear error message including the URL that was attempted. Do not silently fall back to LadybugDB -- that would cause data inconsistency. Fail fast with actionable error.
**Warning signs:** "Connection refused" on `dotmd index`, `dotmd search`, or `dotmd serve` startup.

## Code Examples

Verified patterns from FalkorDB Python client docs and source code:

### Connection and Graph Selection
```python
# Source: https://github.com/FalkorDB/falkordb-py README + source
from falkordb import FalkorDB

# Parse redis:// URL or use host/port
db = FalkorDB(host="localhost", port=6379)
graph = db.select_graph("dotmd")
```

### MERGE Node (Upsert)
```python
# Source: https://docs.falkordb.com/cypher/merge.html
graph.query(
    "MERGE (f:File {id: $id}) SET f.title = $title, f.checksum = $checksum",
    params={"id": file_path, "title": title, "checksum": checksum},
)
```

### MERGE Edge (Match + Merge Pattern)
```python
# Source: FalkorDB MERGE docs -- MATCH endpoints first, then MERGE rel
graph.query(
    "MATCH (a {id: $src}), (b {id: $tgt}) "
    "MERGE (a)-[r:REL]->(b) "
    "SET r.rel_type = $rel_type, r.weight = $weight",
    params={
        "src": source_id,
        "tgt": target_id,
        "rel_type": relation_type,
        "weight": weight,
    },
)
```

### get_neighbors (Variable-Length Path)
```python
# Source: https://docs.falkordb.com/cypher/match.html (variable-length paths)
result = graph.ro_query(
    "MATCH (a {id: $id})-[*1..2]-(b) "
    "RETURN DISTINCT b.id, labels(b)[0]",
    params={"id": node_id},
)
neighbors = []
for row in result.result_set:
    if row[0] != node_id:
        neighbors.append((str(row[0]), "", 1.0))
```

### delete_file_subgraph
```python
# Source: https://docs.falkordb.com/cypher/delete.html
graph.query(
    "MATCH (s:Section {file_path: $fp}) DETACH DELETE s",
    params={"fp": file_path},
)
graph.query(
    "MATCH (f:File {id: $fp}) DETACH DELETE f",
    params={"fp": file_path},
)
```

### delete_all
```python
# Source: FalkorDB docs -- DETACH DELETE all
graph.query("MATCH (n) DETACH DELETE n")
```

### node_count / edge_count
```python
# Source: Cypher standard + FalkorDB functions docs
result = graph.ro_query("MATCH (n) RETURN count(n)")
total_nodes = result.result_set[0][0]

result = graph.ro_query("MATCH ()-[r]->() RETURN count(r)")
total_edges = result.result_set[0][0]
```

### get_graph_data
```python
# Query all nodes by label, all edges
nodes = []
for label in ("File", "Section", "Entity", "Tag"):
    result = graph.ro_query(f"MATCH (n:{label}) RETURN n")
    for row in result.result_set:
        node = row[0]  # FalkorDB returns Node objects
        nodes.append({
            "id": node.properties.get("id", ""),
            "label": label,
            "properties": {k: v for k, v in node.properties.items() if k != "id"},
        })

edges = []
result = graph.ro_query("MATCH (a)-[r]->(b) RETURN a.id, b.id, r.rel_type, r.weight")
for row in result.result_set:
    edges.append({
        "source": str(row[0]),
        "target": str(row[1]),
        "relation_type": str(row[2]),
        "weight": float(row[3]),
    })
```

### Optional: Create Indexes for Performance
```python
# Source: https://docs.falkordb.com/cypher/indexing/range-index.html
# Run once at init -- idempotent
for label in ("File", "Section", "Entity", "Tag"):
    graph.query(f"CREATE INDEX FOR (n:{label}) ON (n.id)")
```

## Status Command Enhancement

GRAPH-03 success criterion #4: `dotmd status` reports graph store type and connection status. This requires:

1. Add `graph_backend` field to `IndexStats` model (or report separately in CLI).
2. In CLI `status` command, display: `Graph: falkordb @ redis://falkordb:6379/dotmd` or `Graph: ladybugdb @ ~/.dotmd/graphdb`.
3. Connection check: `graph.ro_query("RETURN 1")` succeeds = connected. Catch exception = report "disconnected".

## Protocol Changes Required

The `GraphStoreProtocol` in `storage/base.py` needs one addition:

```python
def get_graph_data(self) -> dict:
    """Return all nodes and edges for visualization.

    Returns
    -------
    dict
        A dictionary with 'nodes' and 'edges' keys.
    """
    ...
```

The `IndexingPipeline.graph_store` property return type must change from `LadybugDBGraphStore` to `GraphStoreProtocol`:

```python
@property
def graph_store(self) -> GraphStoreProtocol:  # was: LadybugDBGraphStore
    return self._graph_store
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LadybugDB embedded (Kuzu fork) | FalkorDB via Redis protocol | v1.2 (this phase) | Eliminates file lock issue, enables concurrent CLI + API access |
| Hardcoded graph backend | Config-driven `graph_backend` setting | v1.2 (this phase) | Both backends coexist, gradual migration possible |
| Schema-heavy Cypher (CREATE NODE TABLE) | Schema-less Cypher (MERGE directly) | FalkorDB is schema-less | Simpler adapter code, no migration scripts needed |
| pandas DataFrame result parsing | result_set list-of-lists | FalkorDB client | Removes pandas dependency for graph operations (pandas still needed for LadybugDB) |

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| FalkorDB server | Graph storage | Yes (Docker) | redis 8.2.3, FalkorDB module v4.16.3 | -- |
| graphiti_default network | Docker networking | Yes | -- | -- |
| falkordb Python package | Adapter code | No (not installed on host) | 1.6.0 on PyPI | pip install FalkorDB (add to pyproject.toml) |
| Python 3.12+ | Runtime | Yes | 3.12 (Docker image) | -- |

**Missing dependencies with no fallback:**
- `falkordb` Python package must be added to `pyproject.toml` dependencies

**Missing dependencies with fallback:**
- None -- all infrastructure is in place

## Open Questions

1. **FalkorDB Node object properties API**
   - What we know: `graph.query()` returns `QueryResult` with `result_set`. Rows contain Node objects when `RETURN n` is used.
   - What's unclear: Exact attribute access pattern for Node objects (is it `node.properties["id"]` or `node.id`?). The falkordb-py source suggests `node.properties` is a dict.
   - Recommendation: Verify with a quick REPL test in the first task. Use `RETURN n.id, n.title` style (explicit property access) as the safe pattern -- this returns plain values, not Node objects.

2. **FalkorDB `params` kwarg verified?**
   - What we know: Source code of falkordb-py confirms `def query(self, q: str, params: Optional[Dict[str, object]] = None, timeout: Optional[int] = None) -> QueryResult`.
   - What's unclear: STATE.md says "FalkorDB `params` kwarg API should be verified with quick REPL test before writing all adapter methods."
   - Recommendation: First task should include a connection spike test to confirm params work as documented. HIGH confidence based on source code review, but empirical confirmation is prudent.

3. **Index creation timing**
   - What we know: FalkorDB supports `CREATE INDEX FOR (n:Label) ON (n.property)`. Indexes speed up MATCH with label+property filter.
   - What's unclear: Whether to create indexes at init (every startup) or only once. FalkorDB may handle idempotent index creation, or may error on duplicate.
   - Recommendation: Create indexes in `__init__` wrapped in try/except. If it errors on duplicate, catch and ignore. This matches LadybugDB's `_init_schema` pattern.

## Sources

### Primary (HIGH confidence)
- [FalkorDB Python client source](https://github.com/FalkorDB/falkordb-py) - Graph.query() signature, params handling, QueryResult structure
- [FalkorDB MERGE docs](https://docs.falkordb.com/cypher/merge.html) - MERGE clause syntax, ON CREATE SET
- [FalkorDB Cypher coverage](https://docs.falkordb.com/cypher/cypher-support.html) - Supported clauses, limitations vs Neo4j
- [FalkorDB DELETE docs](https://docs.falkordb.com/cypher/delete.html) - DETACH DELETE behavior
- [FalkorDB MATCH docs](https://docs.falkordb.com/cypher/match.html) - Variable-length paths `[*1..N]`
- [FalkorDB functions](https://docs.falkordb.com/cypher/functions.html) - `labels()` (plural), `type()`, path functions
- [FalkorDB indexing](https://docs.falkordb.com/cypher/indexing/) - Range indexes, full-text indexes
- [FalkorDB known limitations](https://docs.falkordb.com/cypher/known-limitations.html) - LIMIT with eager ops, relationship uniqueness
- [PyPI FalkorDB](https://pypi.org/project/FalkorDB/) - v1.6.0, 2026-02-21, Python >=3.10

### Secondary (MEDIUM confidence)
- [FalkorDB getting started](https://docs.falkordb.com/getting-started/) - Connection examples, basic CRUD
- [FalkorDB GRAPH.QUERY command](https://docs.falkordb.com/commands/graph.query.html) - Parameter syntax: `CYPHER param=val query`

### Tertiary (LOW confidence)
- None -- all findings verified with official sources

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - falkordb-py v1.6.0 confirmed on PyPI, API verified from source code
- Architecture: HIGH - follows existing `_create_vector_store` pattern exactly, protocol is well-defined
- Pitfalls: HIGH - Cypher dialect differences verified against official FalkorDB docs, LadybugDB code reviewed line-by-line
- Code examples: MEDIUM - Cypher patterns verified in docs, but Node object property access needs empirical REPL test

**Research date:** 2026-03-26
**Valid until:** 2026-04-26 (stable -- FalkorDB API is production-stable, no breaking changes expected)
