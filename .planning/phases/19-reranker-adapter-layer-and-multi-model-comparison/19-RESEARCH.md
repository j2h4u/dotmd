# Phase 19: Reranker Adapter Layer and Multi-Model Comparison - Research

**Researched:** 2026-05-01
**Mode:** Research-first planning with no Phase 19 CONTEXT.md; user-supplied phase boundary treated as workflow context.
**Confidence:** HIGH for current codebase shape; MEDIUM-HIGH for model/runtime constraints until CPU smoke is executed.

## User Constraints

No Phase 19 `CONTEXT.md` exists. Constraints are taken from the invocation and ROADMAP Phase 19.

- Production search behavior must remain single-reranker by default. Multi-reranker serving is developer-only.
- Add a clean `RerankerProtocol`/registry/factory boundary so new rerankers can be added without changing `DotMDService` internals.
- Runtime selection by name must work for dev/CLI/API calls.
- Comparison must run retrieval/fusion once, then apply multiple rerankers to the same candidate pool.
- Comparison output must report latency, ordering, score diagnostics, and overlap.
- Qwen CPU latency is a first-class concern.
- Compare Qwen against MiniLM and the top 3-4 Phase 18 candidate models before settling on production defaults.
- Respect dotMD project constraints: work on `dev`, use public APIs through `api/service.py`, never reload indexes per request, never run `dotmd index --force` while the container is running, and batch production restarts.

## Project Constraints from AGENTS.md

- dotMD is an independent, heavily modified fork; upstream behavior is reference-only.
- Production index uses a unified `index.db` and current search is semantic + FTS5 + graph-direct + RRF + rerank.
- Public APIs go through `backend/src/dotmd/api/service.py`; internal storage/search types should not leak directly to surfaces.
- Indexes must be loaded once at startup and reused. The adapter layer must not add per-request `load_index()` calls.
- Production default remains a single reranker.
- Container/runtime changes are deployed in batches, not restarted for every small edit.

## Current Codebase State

- `backend/src/dotmd/search/reranker.py` defines one concrete `Reranker` class around `sentence_transformers.CrossEncoder`. It returns `list[tuple[str, float]]` and already handles provider exceptions by returning `[]`. [VERIFIED: checkout]
- `backend/src/dotmd/api/service.py` constructs `Reranker` directly in `DotMDService.__init__`, validates `reranker_backend == "cross_encoder"` inline, and calls `self._reranker.rerank(...)` in `_execute_search`. [VERIFIED: checkout]
- `DotMDService.search()` currently accepts `query`, `top_k`, `mode`, `rerank`, and `expand`, but no runtime reranker name. [VERIFIED: checkout]
- FastAPI `GET /search` exposes `rerank` and `expand`, but no reranker selector or comparison endpoint. [VERIFIED: checkout]
- CLI `dotmd search` exposes `--no-rerank` and `--no-expand`, but no `--reranker` or comparison command. [VERIFIED: checkout]
- MCP `search` intentionally remains a simple knowledgebase search tool. It should not become the developer comparison surface unless a later phase explicitly asks for that. [VERIFIED: checkout]
- Phase 18 selected `Qwen/Qwen3-Reranker-0.6B` as the default and recorded a live CPU concern: `DOTMD_RERANK_POOL_SIZE=3` took about 20.8s for one batch. [VERIFIED: `.planning/STATE.md`, Phase 18 summary]

## Standard Stack

- Keep `sentence_transformers.CrossEncoder` as the first concrete local adapter path because Qwen's model card documents `CrossEncoder("Qwen/Qwen3-Reranker-0.6B")`, and the project already uses this wrapper. [CITED: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B]
- Use `typing.Protocol` for `RerankerProtocol`, matching dotMD's existing Protocol style in `storage/base.py` and extractor/search protocol conventions. [VERIFIED: checkout]
- Use `time.perf_counter()` for per-reranker elapsed milliseconds. It is sufficient for developer diagnostics and avoids new dependencies. [ASSUMED]
- Keep comparison data in Python/Pydantic-friendly dicts or dataclasses inside `api/service.py`/`search/reranker.py`; avoid introducing a database table or persistence layer in this phase. [ASSUMED]

## Architecture Patterns

### Adapter Boundary

Recommended shape:

```python
class RerankerProtocol(Protocol):
    name: str
    model_name: str

    def warmup(self) -> None: ...

    def rerank(
        self,
        query: str,
        chunk_ids: list[str],
        metadata_store: MetadataStoreProtocol,
        top_k: int,
    ) -> list[tuple[str, float]]: ...
```

Keep the method compatible with the existing service call so the refactor is mostly boundary extraction, not a scoring rewrite.

### Registry and Factory

Define built-in specs by stable short name, not by raw Hugging Face string:

| Name | Model | Adapter Kind | Role |
|---|---|---|---|
| `qwen3-0.6b` | `Qwen/Qwen3-Reranker-0.6B` | `cross_encoder` | production default and latency concern |
| `msmarco-minilm` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | `cross_encoder` | legacy English baseline |
| `mmarco-minilm` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | `cross_encoder` | low-risk multilingual MiniLM baseline |
| `gte-multilingual` | `Alibaba-NLP/gte-multilingual-reranker-base` | `cross_encoder` or future HTTP/TEI adapter | older fallback evidence |
| `bge-v2-m3` | `BAAI/bge-reranker-v2-m3` | `cross_encoder` or future custom adapter | older Russian-evidence fallback |

The factory should raise a clear `ValueError` or project-specific exception for unknown names and include the available names in the message.

### Shared Candidate Pool

Refactor `_execute_search` so retrieval/fusion can be run once and reused:

1. Expand query once.
2. Run semantic, FTS5, and graph-direct engines once.
3. Run RRF fusion once.
4. Optionally append graph-enrichment hits once.
5. Store a candidate pool containing `fused`, `engine_results`, `search_query`, `original_query`, `pool_size`, and raw engine hit counts.
6. Single-reranker search consumes the pool and builds `SearchResult`.
7. Comparison consumes the same pool with N rerankers and returns diagnostics.

This prevents false comparisons where different rerankers see different candidate pools.

### Runtime Selection

- Production default: `Settings.reranker_name = "qwen3-0.6b"`.
- Runtime override: `DotMDService.search(..., reranker_name: str | None = None)`.
- CLI: `dotmd search --reranker qwen3-0.6b`.
- API: `GET /search?reranker=qwen3-0.6b`.
- MCP: leave unchanged for this phase, unless tests prove adding an optional parameter is harmless and useful.

### Developer Comparison

Add a service method such as:

```python
def compare_rerankers(
    self,
    query: str,
    reranker_names: list[str],
    top_k: int = 10,
    mode: SearchMode | str = SearchMode.HYBRID,
    expand: bool = True,
) -> RerankerComparison:
```

Required diagnostics:

- `shared_pool_size`: number of fused candidates seen by all rerankers.
- Per reranker: `name`, `model_name`, `elapsed_ms`, `returned_count`, `top_chunk_ids`, `scores`.
- Pairwise overlap: overlap of top-K chunk IDs against default or first reranker.
- Error field per reranker so one failed candidate does not abort the whole comparison.
- Include Qwen elapsed milliseconds directly in output because CPU latency is a phase-level concern.

## Don't Hand-Roll

- Do not implement custom transformer inference for Qwen/Jina/Contextual in this phase unless CrossEncoder cannot express a candidate. Use the existing CrossEncoder boundary first. [VERIFIED: checkout; CITED: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B]
- Do not add a local quality benchmark harness. Phase 18 explicitly excluded local eval harnesses; Phase 19 comparison is a developer diagnostic over live retrieval candidates, not a curated eval framework. [VERIFIED: Phase 18 context/research]
- Do not add persistence for comparison reports. Print/return diagnostics only.
- Do not change fusion weights or semantic score floors in this phase.

## Common Pitfalls

1. **Factory exists but service still imports concrete `Reranker` directly.** The phase goal requires `DotMDService` to depend on the factory/protocol, not a concrete class.
2. **Comparison reruns retrieval per model.** That invalidates the comparison; every reranker must receive the exact same candidate IDs in the same order.
3. **Unknown reranker silently falls back to default.** This hides operator mistakes. Unknown names must fail clearly.
4. **Qwen warmup happens for every request.** Rerankers must be cached by name at service startup or first use and reused.
5. **Developer comparison becomes production behavior.** The default `search()` path must still run one reranker only.
6. **Tests download model weights.** Mock CrossEncoder/factory boundaries; no network/model downloads in unit tests.
7. **MCP tool schema churn.** The MCP `search` tool is user-facing; adding comparison parameters there is unnecessary for the requested CLI/API developer path.

## Code Examples

### Factory Cache Pattern

```python
class RerankerFactory:
    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._instances: dict[str, RerankerProtocol] = {}

    def get(self, name: str | None = None) -> RerankerProtocol:
        resolved = name or self._settings.reranker_name
        if resolved not in self._instances:
            self._instances[resolved] = create_reranker(resolved, self._settings)
        return self._instances[resolved]
```

### Comparison Timing Pattern

```python
started = time.perf_counter()
try:
    reranked = reranker.rerank(search_query, chunk_ids, metadata_store, top_k=pool_size)
    error = None
except Exception as exc:
    reranked = []
    error = str(exc)
elapsed_ms = (time.perf_counter() - started) * 1000.0
```

## Validation Architecture

The planner should create tests before or alongside implementation:

- `backend/tests/test_reranker.py`: protocol/factory, registry names, unknown-name failure, no model downloads.
- `backend/tests/test_hybrid_bm25.py` or new service test: single-reranker search still preserves fused fallback.
- New service/API tests: runtime `reranker_name` routes to selected adapter and comparison runs retrieval/fusion once.
- CLI tests: `dotmd search --reranker NAME` and `dotmd rerank compare --rerankers a,b`.

Verification commands should stay focused:

```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py
```

## Sources

- Qwen/Qwen3-Reranker-0.6B model card: https://huggingface.co/Qwen/Qwen3-Reranker-0.6B
- SentenceTransformers CrossEncoder docs: https://sbert.net/docs/package_reference/cross_encoder/model.html
- Jina reranker v3 model card: https://huggingface.co/jinaai/jina-reranker-v3
- GTE multilingual reranker model card: https://huggingface.co/Alibaba-NLP/gte-multilingual-reranker-base
- ContextualAI rerank v2 multilingual 1B model card: https://huggingface.co/ContextualAI/ctxl-rerank-v2-instruct-multilingual-1b

## Research Complete

Phase 19 should be planned as four slices:

1. Adapter protocol/registry/factory and config naming.
2. Shared retrieval/fusion candidate pool extraction and single-reranker preservation.
3. Developer comparison service/API/CLI path over one shared pool.
4. Latency diagnostics, docs, and focused verification, with Qwen CPU timing explicitly surfaced.
