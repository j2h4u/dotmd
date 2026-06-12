# Phase 19: Reranker Adapter Layer and Multi-Model Comparison - Pattern Map

**Mapped:** 2026-05-01
**Files analyzed:** 8
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/dotmd/search/reranker.py` | search adapter/provider | request-response transform | itself + `backend/src/dotmd/search/semantic.py` | exact |
| `backend/src/dotmd/core/config.py` | config | env/TOML settings | itself | exact |
| `backend/src/dotmd/api/service.py` | service facade | retrieval/fusion/rerank orchestration | itself | exact |
| `backend/src/dotmd/api/server.py` | FastAPI route | HTTP request-response | existing `GET /search` route | exact |
| `backend/src/dotmd/cli.py` | CLI commands | Click command invocation | existing `search` command and `reset` group | exact |
| `backend/tests/test_reranker.py` | unit tests | mocked provider scoring | itself | exact |
| `backend/tests/test_hybrid_bm25.py` | service integration tests | mocked engines + reranker | itself | exact |
| `backend/tests/api/test_service_search.py` | service facade tests | patched service methods | itself | role-match |

## Pattern Assignments

### `backend/src/dotmd/search/reranker.py` (adapter/provider)

**Analog:** itself.

**Current lazy provider pattern:**

```python
def _load_model(self) -> Any:
    if self._model is None:
        from sentence_transformers import CrossEncoder
        logger.info("Loading cross-encoder model: %s", self._model_name)
        self._model = CrossEncoder(self._model_name)
    return self._model
```

**Apply to Phase 19:**

- Keep lazy provider loading.
- Rename or wrap the concrete class as `CrossEncoderReranker`.
- Preserve a compatibility alias if needed: `Reranker = CrossEncoderReranker`.
- Add `RerankerProtocol`, registry metadata, and factory functions in this module unless the file becomes too large.

**Current error fallback pattern:**

```python
except Exception:
    logger.warning(
        "Reranker provider failed for model %s; returning no reranked candidates",
        self._model_name,
        exc_info=True,
    )
    return []
```

**Apply to Phase 19:** comparison should record per-reranker error diagnostics, while normal search can keep the existing `[]` fallback behavior.

### `backend/src/dotmd/search/semantic.py` (external-provider analog)

**Analog role:** remote/local provider switch and non-fatal HTTP metadata fetch.

**Pattern to copy:**

- Store settings-derived provider fields on the instance.
- Lazy load or lazily query the provider.
- Cache provider metadata after the first successful call.
- Keep external provider errors non-fatal where the search pipeline can continue.

Use this pattern if Phase 19 adds a future HTTP/TEI reranker adapter shell.

### `backend/src/dotmd/core/config.py` (config)

**Analog:** itself.

**Existing reranker fields:**

```python
reranker_backend: Literal["cross_encoder"] = "cross_encoder"
reranker_url: str | None = None
reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
reranker_relevance_floor: float | None = None
reranker_length_penalty: bool = True
reranker_min_length: int = 50
```

**Apply to Phase 19:**

- Add name-based settings without deleting model/floor fields:
  - `reranker_name: str = "qwen3-0.6b"`
  - `reranker_compare_names: str = "qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual"`
  - optional `reranker_timeout_seconds: float = 60.0` if HTTP adapters are added.
- Preserve existing env prefix behavior; `DOTMD_RERANKER_NAME` and `DOTMD_RERANKER_COMPARE_NAMES` should work automatically.

### `backend/src/dotmd/api/service.py` (service facade)

**Analog:** itself.

**Current single-reranker construction pattern:**

```python
self._reranker = Reranker(
    model_name=self._settings.reranker_model,
    length_penalty=self._settings.reranker_length_penalty,
    min_length=self._settings.reranker_min_length,
    relevance_floor=self._settings.reranker_relevance_floor,
)
```

**Apply to Phase 19:**

- Replace direct construction with a factory/cache, e.g. `self._rerankers = RerankerFactory(self._settings)`.
- `search()` should call `self._rerankers.get(reranker_name)` once per request, not instantiate a model directly.
- `compare_rerankers()` should resolve multiple names from the same factory/cache.

**Current retrieval/fusion sequence to preserve:**

1. Expand query.
2. Calculate `pool_size`.
3. Run semantic/keyword/graph-direct.
4. RRF fuse results.
5. Graph enrichment appends post-fusion hits.
6. Rerank fused[:pool_size].
7. Build `SearchResult`.

**Apply to Phase 19:** extract steps 3-5 into an internal helper that returns the shared candidate pool. Do not reload indexes in that helper.

### `backend/src/dotmd/api/server.py` (FastAPI route)

**Analog:** existing `GET /search`.

**Current route pattern:**

```python
@app.get("/search", response_model=SearchResponse)
async def search(...):
    results = _get_service().search(...)
    return SearchResponse(query=q, results=results, count=len(results))
```

**Apply to Phase 19:**

- Add optional `reranker: str | None = Query(None)` to `GET /search`.
- Add a developer comparison route such as `GET /rerank/compare` with query params `q`, `rerankers`, `top_k`, `mode`, `expand`.
- Keep response models explicit Pydantic classes.

### `backend/src/dotmd/cli.py` (Click CLI)

**Analog:** existing `search` command and nested `reset` group.

**Current option style:**

```python
@click.option("--no-rerank", is_flag=True, help="Skip cross-encoder reranking.")
@click.option("--no-expand", is_flag=True, help="Skip query expansion.")
```

**Apply to Phase 19:**

- Add `@click.option("--reranker", default=None, help="Reranker name to use.")`.
- Add a new nested command group or command:
  - `dotmd rerank compare QUERY --rerankers qwen3-0.6b,msmarco-minilm,mmarco-minilm`
- Print compact tables: name, elapsed_ms, returned_count, top chunk IDs, overlap.

### `backend/tests/test_reranker.py` (unit tests)

**Analog:** existing mocked `CrossEncoder` tests.

**Pattern to copy:**

```python
@patch("sentence_transformers.CrossEncoder", autospec=True)
def test_scores_map_back_to_original_chunk_ids(self, MockCE: MagicMock) -> None:
    mock_model = MagicMock()
    mock_model.predict.return_value = np.array([0.2, 9.0, 1.5])
    MockCE.return_value = mock_model
```

**Apply to Phase 19:** factory/registry tests should mock the class path and should not download model weights.

### `backend/tests/test_hybrid_bm25.py` (service pipeline tests)

**Analog:** mocked engines plus service search.

**Pattern to copy:**

- Construct `DotMDService(Settings(...))`.
- Replace `_semantic_engine`, `_keyword_engine`, `_graph_engine`, `_graph_direct_engine`, `_query_expander`, and `_reranker` with mocks.
- Patch `build_search_results` if the test needs to inspect fused order before final truncation.

**Apply to Phase 19:** comparison tests can count engine invocations and assert each engine was called once even when comparing three rerankers.

## Shared Patterns

### Protocols

Use the same import discipline as the rest of the codebase:

```python
from typing import TYPE_CHECKING, Any, Protocol
```

Guard `MetadataStoreProtocol` import under `TYPE_CHECKING` in `reranker.py`.

### Config validators

If adding comma-separated names, follow the existing `embedding_weights` validator style: normalize, validate, and return the raw string or expose a parsed property. Prefer a parsed property if the raw env value is useful for display.

### Errors

Unknown reranker errors must include available names:

```python
raise ValueError(
    f"Unknown reranker {name!r}; available: {', '.join(available_rerankers())}"
)
```

### Tests

Focused verification should use:

```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py -q
```

and ruff over touched files.

## No Analog Found

- There is no existing multi-provider comparison API in dotMD. Implement it as a service-level developer diagnostic, not as a persisted benchmark subsystem.
