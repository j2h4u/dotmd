# Phase 42: Surreal-native retrieval implementation - Pattern Map

**Mapped:** 2026-06-14
**Files analyzed:** 7
**Analogs found:** 7 / 7

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/dotmd/search/surreal_fts.py` | service | request-response | `backend/src/dotmd/search/fts5.py` | exact |
| `backend/src/dotmd/search/surreal_vector.py` | service | request-response | `backend/src/dotmd/search/semantic.py` | role-match |
| `backend/src/dotmd/search/surreal_graph.py` | service | request-response | `backend/src/dotmd/search/graph_direct.py` | exact |
| `backend/src/dotmd/api/service.py` | service | request-response | `backend/src/dotmd/api/service.py` | exact |
| `backend/src/dotmd/storage/surreal.py` | service | request-response | `backend/src/dotmd/storage/surreal.py` | exact |
| `backend/tests/search/test_surreal_native_retrieval.py` | test | request-response | `backend/tests/search/test_surreal_retrieval_parity.py` | role-match |
| `backend/tests/api/test_service_search.py` | test | request-response | `backend/tests/api/test_service_search.py` | exact |

## Pattern Assignments

### `backend/src/dotmd/search/surreal_fts.py` (service, request-response)

**Analog:** `backend/src/dotmd/search/fts5.py`

**Imports pattern** ([backend/src/dotmd/search/fts5.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fts5.py:7)):
```python
from __future__ import annotations

import logging
import re
import sqlite3

from dotmd.core.models import Chunk
```

Copy the small-module shape: stdlib imports first, then project imports, module logger near the top.

**Query sanitization pattern** ([backend/src/dotmd/search/fts5.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fts5.py:57)):
```python
def _sanitize_fts5_query(query: str) -> str:
    cleaned = re.sub(r'["\(\)\*:]', "", query)
    words = cleaned.split()
    if not words:
        return ""
    return " ".join(f"{w}*" for w in words)
```

Use the same helper-style preprocessing boundary in the Surreal FTS engine before issuing SurrealQL.

**Engine class pattern** ([backend/src/dotmd/search/fts5.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fts5.py:74)):
```python
class FTS5SearchEngine:
    def __init__(self, conn: sqlite3.Connection, table_name: str = "chunks_fts") -> None:
        self._conn = conn
        self._table = table_name
        self._ensure_fts5_schema()
```

Mirror this with a constructor that owns only the already-open Surreal connection/helper plus any field-weight config. Do not reload or reconnect per search.

**Search method pattern** ([backend/src/dotmd/search/fts5.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fts5.py:273)):
```python
def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
    sanitized = _sanitize_fts5_query(query)
    if not sanitized:
        return []

    try:
        cur = self._conn.execute(...)
        return [(row[0], row[1]) for row in cur.fetchall()]
    except sqlite3.OperationalError as exc:
        logger.warning(...)
        return []
```

Keep the same fail-soft contract: empty query returns `[]`; operational/query errors log and return `[]` instead of breaking the whole search pipeline.

**Surreal schema/index source to copy from** ([backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:299)):
```python
_table(
    "chunks",
    "Content-addressed chunk payloads and source-preserving identifiers.",
    fields=(
        _field("schema_version", "string"),
        _field("original_chunk_id", "string"),
        _field("chunk_id", "string"),
        _field("chunk_strategy", "string"),
        _field("document_ref", "string"),
        _field("ref", "string"),
        _field("text", "string"),
        _field("metadata", "object", required=False, flexible_json=True),
    ),
    indexes=(
        _index("chunks_chunk_id_idx", "chunk_id", unique=True),
        _index("chunks_ref_idx", "ref"),
    ),
)
```

Phase 42 should query these existing imported tables/fields, not invent parallel record shapes.

### `backend/src/dotmd/search/surreal_vector.py` (service, request-response)

**Analog:** `backend/src/dotmd/search/semantic.py`

**Imports + ownership pattern** ([backend/src/dotmd/search/semantic.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/semantic.py:11)):
```python
import logging
from typing import TYPE_CHECKING

import httpx

from dotmd.storage.base import VectorStoreProtocol
```

Keep query-embedding generation in the engine module, but replace the backend search call target from `VectorStoreProtocol` to the Surreal retrieval helper.

**Constructor pattern** ([backend/src/dotmd/search/semantic.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/semantic.py:51)):
```python
def __init__(
    self,
    vector_store: VectorStoreProtocol,
    model_name: str = _DEFAULT_MODEL,
    score_floor: float = 0.0,
    embedding_url: str | None = None,
    tei_batch_size: int = 32,
    use_prefix: bool = True,
    query_instruction: str = "",
) -> None:
```

Use the same parameter split: query embedding concerns belong here; retrieval execution belongs in the injected Surreal-facing dependency.

**Query encoding pattern** ([backend/src/dotmd/search/semantic.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/semantic.py:232)):
```python
def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
    if self._query_instruction:
        encoded_query = f"{self._query_instruction}\nQuery: {query}"
    elif self._use_prefix:
        encoded_query = f"query: {query}"
    else:
        encoded_query = query
    query_embedding = self.encode(encoded_query)
    results = self._vector_store.search(query_embedding, top_k=top_k)
```

Preserve this exact query-normalization behavior so Surreal vector retrieval stays comparable to the current semantic engine and Phase 40 eval expectations.

**Anti-pattern to replace** ([backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:458)):
```python
def search(self, query_embedding: list[float], top_k: int = 10) -> list[tuple[str, float]]:
    scored: list[tuple[str, float]] = []
    for row in self._connection.scan_table("embeddings"):
        embedding = [float(value) for value in row.get("embedding", [])]
        if not embedding:
            continue
        score = _cosine_similarity(query_embedding, embedding)
        scored.append((str(row["chunk_id"]), score))
    scored.sort(key=lambda item: item[1], reverse=True)
    return scored[:top_k]
```

Phase 42 should explicitly replace this O(n) table-scan pattern with a Surreal indexed vector query helper, but keep the public return shape `list[tuple[str, float]]`.

**Embedding storage seam** ([backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:380)):
```python
_table(
    "embeddings",
    "Stored sqlite-vec rows preserved without TEI recomputation.",
    fields=(
        _field("schema_version", "string"),
        _field("chunk_id", "string"),
        _field("embedding_model", "string"),
        _field("text_hash", "string"),
        _field("vector_rowid", "int"),
        _field("embedding", "array<float>", required=False),
        _field("metadata", "object", required=False, flexible_json=True),
    ),
```

Use these fields as the Surreal vector query source. Do not introduce re-embedding or storage cutover work here.

### `backend/src/dotmd/search/surreal_graph.py` (service, request-response)

**Analog:** `backend/src/dotmd/search/graph_direct.py`

**Imports pattern** ([backend/src/dotmd/search/graph_direct.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/graph_direct.py:10)):
```python
from __future__ import annotations

import logging
import re

from dotmd.storage.base import GraphStoreProtocol
```

Keep graph query/token matching logic local to the engine and inject a graph-capable store/helper.

**Catalog-loading pattern** ([backend/src/dotmd/search/graph_direct.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/graph_direct.py:37)):
```python
def load_catalog(self) -> None:
    try:
        entities = self._graph_store.get_all_entity_names()
        self._entity_catalog = {name.lower(): name for name in entities}
        self._loaded = True
        logger.info("Graph entity catalog loaded: %d entities", len(self._entity_catalog))
    except (RuntimeError, ValueError):
        logger.warning("Failed to load entity catalog", exc_info=True)
        self._entity_catalog = {}
        self._loaded = True
```

Reuse this load-once behavior if the Surreal graph engine needs entity-name preloading. Do not scan relation rows on every search.

**Search loop pattern** ([backend/src/dotmd/search/graph_direct.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/graph_direct.py:52)):
```python
def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
    if not self._loaded:
        self.load_catalog()
    if not self._entity_catalog:
        return []
    matched = self._match_entities(query)
    if not matched:
        return []
```

Keep the same fast-exit behavior and result type, even if Surreal-native graph retrieval replaces the store internals.

**Anti-pattern to replace** ([backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:678)):
```python
def get_all_entity_names(self) -> list[str]:
    names = [str(row.get("name")) for row in self._connection.scan_table("entities")]
    return sorted(name for name in names if name)

def get_chunks_by_entity(self, entity_name: str) -> list[str]:
    chunk_ids = [
        str(row["source_id"])
        for row in self._connection.scan_table("relations")
        if row.get("target_id") == entity_name and row.get("relation_type") == "MENTIONS"
    ]
    return sorted(chunk_ids)
```

Phase 42 should keep these behaviors as semantic intent, but move the retrieval path to Surreal relation queries/traversals instead of Python-side full-table scans.

**Relation-table seam** ([backend/src/dotmd/storage/surreal_schema.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal_schema.py:460)):
```python
_table(
    "relations",
    "Metadata-carrying relation records preserving canonical rel_type and endpoint hints.",
    fields=(
        _field("schema_version", "string"),
        _field("rel_type", "string"),
        _field("weight", "number"),
        _field("source_id", "string"),
        _field("target_id", "string"),
        _field("source_table", "string"),
        _field("target_table", "string"),
        _field("properties", "object", required=False, flexible_json=True),
        _field("metadata", "object", required=False, flexible_json=True),
    ),
    indexes=(
        _index("relations_rel_type_idx", "rel_type"),
        _index("relations_source_target_idx", "source_id", "target_id"),
    ),
    schema_mode="RELATION",
)
```

This is the Phase 41 source of truth for graph retrieval fields and relation metadata.

### `backend/src/dotmd/api/service.py` (service, request-response)

**Analog:** `backend/src/dotmd/api/service.py`

**Engine wiring pattern** ([backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:252)):
```python
self._semantic_engine = SemanticSearchEngine(...)
self._keyword_engine = self._pipeline.keyword_engine
self._graph_engine = GraphSearchEngine(...)
self._graph_direct_engine = GraphDirectEngine(...)
```

Phase 42 should preserve this orchestration shape. Swap concrete engine implementations behind the same local attributes or equivalent new Surreal-specific attributes without changing public service behavior.

**Primary retrieval + fusion pattern** ([backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1325)):
```python
semantic_hits: list[tuple[str, float]] = []
keyword_hits: list[tuple[str, float]] = []
graph_direct_hits: list[tuple[str, float]] = []

if mode in (...):
    semantic_hits = self._semantic_engine.search(search_query, top_k=pool_size)
if mode in (...):
    keyword_hits = self._keyword_engine.search(search_query, top_k=pool_size)
if mode in (...):
    graph_direct_hits = self._graph_direct_engine.search(original_query, top_k=pool_size)

engine_results: dict[str, list[tuple[str, float]]] = {}
...
fused = fuse_results(engine_results, k=self._settings.fusion_k)
```

Keep this exact Python-side fusion boundary. Research explicitly says Phase 42 should not move hybrid fusion into Surreal runtime helpers.

**Post-fusion graph enrichment pattern** ([backend/src/dotmd/api/service.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/api/service.py:1378)):
```python
if mode in (SearchMode.GRAPH, SearchMode.HYBRID) and fused:
    seed_ids = [cid for cid, _ in fused[:pool_size]]
    try:
        graph_hits = self._graph_engine.search(...)
    except (RuntimeError, ValueError):
        logger.warning(...)
        graph_hits = []
    if graph_hits:
        fused_floor = fused[-1][1] if fused else 0.0
        ...
        engine_results["graph"] = graph_hits
```

Do not collapse graph-direct and graph-enrichment semantics together. Phase 42 is about replacing the peer retrieval surfaces, not rewriting this later enrichment stage.

### `backend/src/dotmd/storage/surreal.py` (service, request-response)

**Analog:** `backend/src/dotmd/storage/surreal.py`

**Connection wrapper pattern** ([backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:118)):
```python
class SurrealConnection:
    def __init__(self, config: SurrealStoreConfig) -> None:
        self.config = config
        self._db = cast(Any, Surreal(config.url))
        self._db.connect()
        self._db.use(config.namespace, config.database)
```

Any new retrieval helper should depend on this existing connection owner. Do not create one-off Surreal clients inside each search call.

**Normalized query/query_raw seam** ([backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:140)):
```python
def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
    return self._db.query(statement, variables)

def query_raw(self, statement: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    return self._db.query_raw(statement, variables)
```

Phase 42 retrieval helpers should be thin adapters over these methods, keeping SurrealQL close to storage and result-shaping in the engine layer.

**Schema inspection pattern** ([backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:169)):
```python
def inspect_schema(self) -> dict[str, Any]:
    meta_rows = self.scan_table("schema_meta")
    ...
    db_info = self.query_raw("INFO FOR DB;")
    ...
    return {"schema_version": schema_version, "table_modes": table_modes}
```

If Phase 42 needs feature guards or smoke assertions around indexes/tables, follow this best-effort inspection pattern rather than hard-failing on introspection noise.

### `backend/tests/search/test_surreal_native_retrieval.py` (test, request-response)

**Analog:** `backend/tests/search/test_surreal_retrieval_parity.py`

**Fixture helper pattern** ([backend/tests/search/test_surreal_retrieval_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_retrieval_parity.py:21)):
```python
def _make_case(
    *,
    name: str,
    retrieval_kind: str,
    query: str = "surreal search",
    top_k: int = 10,
    blocking: bool = True,
    metadata: dict[str, object] | None = None,
) -> RetrievalParityCase:
```

Use small, explicit fixture builders for query/retrieval cases instead of large integration setup in every test.

**Behavior-first assertion style** ([backend/tests/search/test_surreal_retrieval_parity.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_retrieval_parity.py:43)):
```python
result = compare_fts_results(case, current_results, surreal_results)

assert result.passed is True
assert result.top_result_match is True
assert result.top_k_overlap == 1.0
```

Follow this pattern for Surreal-native engine tests: assert user-visible retrieval behavior first, then classification/diagnostic fields.

**Eval harness shape to reuse** ([backend/tests/search/test_surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/search/test_surreal_eval.py:22)):
```python
def _query(... ) -> GoldenQuery: ...
def _result(... ) -> EvalResult: ...
```

If Phase 42 adds eval-oriented tests or fixtures, reuse the existing `GoldenQuery` / `EvalResult` vocabulary so later Phase 43 shadow-run work can consume the same shapes.

### `backend/tests/api/test_service_search.py` (test, request-response)

**Analog:** `backend/tests/api/test_service_search.py`

**Service bootstrap pattern** ([backend/tests/api/test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:17)):
```python
def _get_service(tmp_path: Path):
    from dotmd.api.service import DotMDService
    from dotmd.core.config import Settings

    settings = Settings(
        index_dir=tmp_path, embedding_url="http://localhost:8088", telegram_daemon_socket=None
    )
    return DotMDService(settings)
```

Use this test entrypoint for any service-level wiring changes in Phase 42.

**Patch-and-assert orchestration pattern** ([backend/tests/api/test_service_search.py](/home/j2h4u/repos/j2h4u/dotmd/backend/tests/api/test_service_search.py:99)):
```python
with patch.object(service, "_execute_search", return_value=[stub_result]) as execute_search:
    response = service.search("test query", top_k=5, rerank=False, expand=False)

execute_search.assert_called_once_with(...)
```

Keep service tests focused on orchestration and argument flow, not full backend execution.

## Shared Patterns

### Search Engine Protocol
**Source:** [backend/src/dotmd/search/base.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/base.py:13)
**Apply to:** All new Surreal-native engine modules
```python
@runtime_checkable
class SearchEngineProtocol(Protocol):
    def search(self, query: str, top_k: int = 10) -> list[tuple[str, float]]:
        ...
```

### Python-Side Fusion And Attribution
**Source:** [backend/src/dotmd/search/fusion.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fusion.py:189)
**Apply to:** `backend/src/dotmd/api/service.py`, Phase 42 engine outputs, later eval capture
```python
def fuse_results(
    ranked_lists: dict[str, list[tuple[str, float]]],
    k: int = 60,
    engine_weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]:
    weights = engine_weights or {}
    rrf_scores: dict[str, float] = {}

    for engine, results in ranked_lists.items():
        w = weights.get(engine, 1.0)
        for rank_0, (chunk_id, _score) in enumerate(results):
            rank = rank_0 + 1
            rrf_scores[chunk_id] = rrf_scores.get(chunk_id, 0.0) + w / (k + rank)

    return sorted(rrf_scores.items(), key=lambda x: x[1], reverse=True)
```

### Candidate Hydration Contract
**Source:** [backend/src/dotmd/search/fusion.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/fusion.py:275)
**Apply to:** Any Phase 42 wiring that changes engine names or result sources
```python
def build_candidates(
    fused: list[tuple[str, float]],
    per_engine: dict[str, list[tuple[str, float]]],
    metadata_store: MetadataStoreProtocol,
    query: str = "",
    ...
) -> list[SearchCandidate]:
```

The engine output contract remains chunk-id keyed tuples until this hydration layer.

### Surreal Connection Reuse
**Source:** [backend/src/dotmd/storage/surreal.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/surreal.py:118)
**Apply to:** All Phase 42 storage/query helpers
```python
class SurrealConnection:
    def query(self, statement: str, variables: dict[str, Any] | None = None) -> Any:
        return self._db.query(statement, variables)
```

Do not create per-request connections or hidden runtime reloads.

### Eval Vocabulary
**Source:** [backend/src/dotmd/search/surreal_contract.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_contract.py:14), [backend/src/dotmd/search/surreal_eval.py](/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/surreal_eval.py:21)
**Apply to:** Any new eval fixtures, diff rows, or acceptance tests in Phase 42
```python
class RetrievalSurface(StrEnum):
    WEIGHTED_FULL_TEXT = "weighted_full_text"
    VECTOR = "vector"
    GRAPH_ENTITY = "graph_entity"
    HYBRID_FUSION = "hybrid_fusion"
    RERANKER_INPUT = "reranker_input"
```

```python
class GoldenQueryCategory(StrEnum):
    TITLE_HEAVY = "title-heavy"
    TAG_HEAVY = "tag-heavy"
    BODY_HEAVY = "body-heavy"
    SEMANTIC = "semantic"
    GRAPH_ENTITY = "graph-entity"
    HYBRID = "hybrid"
    SOURCE_REF = "source-ref"
    MIXED_RU_EN = "mixed-ru-en"
```

## No Analog Found

None. Phase 42 can stay inside existing search/service/storage/test patterns.

## Metadata

**Analog search scope:** `backend/src/dotmd/search`, `backend/src/dotmd/api`, `backend/src/dotmd/storage`, `backend/tests/search`, `backend/tests/api`, `.planning/phases/39-*`, `.planning/phases/40-*`, `.planning/phases/41-*`
**Files scanned:** 17
**Pattern extraction date:** 2026-06-14
