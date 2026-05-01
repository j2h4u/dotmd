---
phase: "19"
plan: "02-shared-candidate-pool"
type: execute
wave: 2
depends_on:
  - "01-reranker-protocol-registry"
files_modified:
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/search/reranker.py
  - backend/tests/test_hybrid_bm25.py
  - backend/tests/api/test_service_search.py
autonomous: true
requirements:
  - RERANK-ADAPTER-01
  - RERANK-SELECT-04
  - RERANK-COMPARE-01
must_haves:
  truths:
    - "Normal search still runs at most one reranker per request"
    - "Runtime search can select a reranker by name"
    - "Retrieval, graph-direct, RRF fusion, and graph enrichment can be executed once and represented as a reusable candidate pool"
    - "Empty or failed reranker output still falls back to fused ranking"
    - "No index is reloaded per request"
  artifacts:
    - path: "backend/src/dotmd/api/service.py"
      provides: "candidate pool helper and factory-backed single-reranker search"
      contains: "class RerankCandidatePool"
    - path: "backend/tests/test_hybrid_bm25.py"
      provides: "single-reranker behavior regression tests"
      contains: "reranker_name"
  key_links:
    - from: "runtime reranker_name"
      to: "RerankerFactory.get"
      via: "DotMDService.search"
      pattern: "reranker_name"
---

# Phase 19 Plan 02: Shared Candidate Pool and Single-Reranker Search Wiring

<objective>
Refactor `DotMDService` so the retrieval/fusion candidate pool is explicit and reusable, then wire normal search through the `RerankerFactory`.

This plan preserves production behavior: one configured reranker runs by default, and empty/failed reranker output keeps the fused ranking. It also adds runtime selection by name for service callers.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Refactor changes ranking semantics before comparison exists | HIGH | Existing hybrid/rerank tests must still pass, including keyword survival and fused fallback. |
| Runtime override instantiates a new model on every request | HIGH | Use the factory cache created in Plan 01. |
| Candidate pool helper reloads FTS/vector indexes per request | HIGH | Helper only calls existing search engines; no `load_index()` calls are added. |
| Unknown runtime reranker falls back silently | HIGH | Let factory `ValueError` propagate to CLI/API in later plans. |
</threat_model>

<tasks>
<task id="1" type="auto" tdd="true">
<name>Task 1: Add reusable candidate pool data structure</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_hybrid_bm25.py`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/test_hybrid_bm25.py`
</files>
<behavior>
- Test 1: a hybrid search with semantic and keyword mocks still returns the same final chunk IDs before and after pool extraction.
- Test 2: `_collect_candidate_pool` or equivalent calls each engine exactly once for one search request.
- Test 3: no test requires a real vector index, graph DB, or model.
</behavior>
<action>
In `backend/src/dotmd/api/service.py`, add a private data structure near `ReadPayload`:

```python
class RerankCandidatePool(TypedDict):
    search_query: str
    original_query: str
    fused: list[tuple[str, float]]
    engine_results: dict[str, list[tuple[str, float]]]
    semantic_hits: list[tuple[str, float]]
    keyword_hits: list[tuple[str, float]]
    graph_direct_hits: list[tuple[str, float]]
    pool_size: int
```

Extract the retrieval/fusion/graph-enrichment part of `_execute_search` into a private helper:

```python
def _collect_candidate_pool(
    self,
    *,
    search_query: str,
    original_query: str,
    mode: SearchMode | str,
    pool_size: int,
) -> RerankCandidatePool:
    ...
```

The helper must:
- run semantic, keyword, and graph-direct engines with existing conditions;
- return an empty `fused` list if no primary engines return hits;
- call `fuse_results` once;
- run graph enrichment exactly as current code does;
- not call `load_index()` or instantiate reranker models.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_hybrid_bm25.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `class RerankCandidatePool`.
- `backend/src/dotmd/api/service.py` contains `def _collect_candidate_pool`.
- `backend/src/dotmd/api/service.py` contains no new `load_index(` call inside `_collect_candidate_pool`.
- Existing tests in `backend/tests/test_hybrid_bm25.py` pass.
</acceptance_criteria>
<done>
Retrieval/fusion candidate pool exists as one reusable helper with behavior-preserving tests.
</done>
</task>

<task id="2" type="auto" tdd="true">
<name>Task 2: Wire normal search through RerankerFactory with runtime name override</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/reranker.py`
- `backend/src/dotmd/core/config.py`
- `backend/tests/test_hybrid_bm25.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/test_hybrid_bm25.py`
- `backend/tests/api/test_service_search.py`
</files>
<behavior>
- Test 1: `service.search(..., reranker_name="msmarco-minilm")` calls factory `.get("msmarco-minilm")`.
- Test 2: `service.search(..., reranker_name=None)` calls factory `.get(None)` or default equivalent.
- Test 3: mocked reranker returning `[]` still preserves fused results.
- Test 4: `service.search(..., rerank=False, reranker_name="msmarco-minilm")` does not call the factory.
</behavior>
<action>
In `DotMDService.__init__`:
- Replace direct `Reranker(...)` construction with `self._reranker_factory = RerankerFactory(self._settings)`.
- Do not load a model during `__init__`.

In `warmup()`:
- Replace `self._reranker._load_model()` with `self._reranker_factory.get().warmup()`.

Update `search()` signature:

```python
def search(
    self,
    query: str,
    top_k: int = 10,
    mode: SearchMode | str = SearchMode.HYBRID,
    rerank: bool = True,
    expand: bool = True,
    reranker_name: str | None = None,
) -> list[SearchResult]:
```

Update `_execute_search()` signature to accept `reranker_name: str | None`.

Inside `_execute_search()`:
- call `_collect_candidate_pool(...)`;
- return `[]` if `pool["fused"]` is empty;
- if `rerank and pool["fused"]`, use `reranker = self._reranker_factory.get(reranker_name)`;
- call `reranker.rerank(...)`;
- preserve existing blend and merge-back logic;
- keep the log text `reranker returned no candidates; falling back to fused ranking`;
- set `reranked_applied = True` only when scored reranker candidates exist.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_hybrid_bm25.py tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` imports `RerankerFactory`.
- `backend/src/dotmd/api/service.py` contains `reranker_name: str | None = None` in `search`.
- `backend/src/dotmd/api/service.py` contains `self._reranker_factory.get(reranker_name)`.
- `backend/src/dotmd/api/service.py` no longer constructs `Reranker(` directly in `DotMDService.__init__`.
- Tests prove `rerank=False` skips factory lookup.
- `cd backend && uv run pytest tests/test_hybrid_bm25.py tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
<done>
Normal search uses the adapter factory and supports runtime reranker selection without changing default single-reranker behavior.
</done>
</task>

<task id="3" type="auto" tdd="true">
<name>Task 3: Preserve search result and logging contracts after refactor</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/tests/test_hybrid_bm25.py`
- `backend/tests/smoke/test_search_engines.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/test_hybrid_bm25.py`
</files>
<behavior>
- Test 1: `log_search(..., reranked=True)` is used only when reranker scores were applied.
- Test 2: empty reranker output logs/records `reranked=False`.
- Test 3: candidates beyond rerank pool are still merged back.
</behavior>
<action>
After refactoring to candidate pools, re-check these exact behaviors:
- `engine_results` passed to `build_search_results` includes semantic, keyword, graph-direct, and graph enrichment as before.
- candidates not returned by the reranker are merged back with fusion-only scores;
- `top_k` truncation still happens after rerank/fusion merge-back;
- `self._pipeline.log_search(... reranked=reranked_applied)` remains non-fatal and uses the final results.

If tests need to inspect internals, follow the existing `patch.object(svc_module, "build_search_results", side_effect=capture_build)` pattern in `backend/tests/test_hybrid_bm25.py`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_hybrid_bm25.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/test_hybrid_bm25.py` still contains `test_candidates_beyond_pool_size_preserved`.
- `backend/tests/test_hybrid_bm25.py` still contains `test_keyword_only_candidate_survives_low_reranker_score`.
- `backend/tests/test_hybrid_bm25.py` has an assertion covering `reranked=False` when reranker returns `[]` or equivalent log/search-log behavior.
- `cd backend && uv run pytest tests/test_hybrid_bm25.py -q` exits 0.
</acceptance_criteria>
<done>
The extraction does not regress fused fallback, keyword survival, merge-back, or search logging semantics.
</done>
</task>
</tasks>

<verification>
```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py -q
cd backend && uv run ruff check src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_hybrid_bm25.py tests/api/test_service_search.py
```
</verification>

<success_criteria>
- Search can select a reranker by name.
- Production default still uses one reranker.
- Retrieval/fusion candidate pool is explicit and reusable.
- No per-request index reloads are introduced.
- Existing fallback and keyword-survival tests remain green.
</success_criteria>
