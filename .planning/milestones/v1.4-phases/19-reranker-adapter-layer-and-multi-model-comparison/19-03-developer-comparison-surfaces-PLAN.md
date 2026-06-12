---
phase: "19"
plan: "03-developer-comparison-surfaces"
type: execute
wave: 3
depends_on:
  - "02-shared-candidate-pool"
files_modified:
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/api/server.py
  - backend/src/dotmd/cli.py
  - backend/tests/api/test_service_search.py
  - backend/tests/test_cli.py
autonomous: true
requirements:
  - RERANK-SELECT-04
  - RERANK-COMPARE-01
  - RERANK-LATENCY-01
requirements_addressed: [RERANK-SELECT-04, RERANK-COMPARE-01, RERANK-LATENCY-01]
must_haves:
  truths:
    - "Developer comparison runs retrieval/fusion once and reuses one shared candidate pool"
    - "Comparison reports per-reranker latency, returned count, ordered top chunk IDs, score diagnostics, and overlap"
    - "One failed reranker appears as an error in comparison output and does not abort other rerankers"
    - "Overlap uses the first successful reranker as the reference and reports that reference explicitly"
    - "API response construction uses explicit validation/mapping, not fragile ** unpacking between service TypedDict and Pydantic models"
    - "CLI and FastAPI expose runtime reranker selection by name"
    - "CLI and FastAPI expose developer-only comparison; MCP remains unchanged"
  artifacts:
    - path: "backend/src/dotmd/api/service.py"
      provides: "compare_rerankers service method"
      contains: "def compare_rerankers"
    - path: "backend/src/dotmd/api/server.py"
      provides: "HTTP comparison route"
      contains: "/rerank/compare"
    - path: "backend/src/dotmd/cli.py"
      provides: "CLI comparison command"
      contains: "compare"
  key_links:
    - from: "shared candidate pool"
      to: "each comparison reranker"
      via: "compare_rerankers"
      pattern: "_collect_candidate_pool"
---

# Phase 19 Plan 03: Developer Comparison Service, API, and CLI Surfaces

<objective>
Add the developer-only comparison path over one shared retrieval/fusion candidate pool and expose it through service, FastAPI, and CLI.

The comparison is diagnostic output only. It does not replace the production single-reranker search path and does not persist results.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Comparison reruns retrieval per reranker and invalidates results | HIGH | Service test counts engine calls and requires each engine to run once for a multi-reranker comparison. |
| Slow Qwen comparison blocks all diagnostics without context | HIGH | Report `elapsed_ms` per reranker and preserve partial results when one candidate errors. |
| TypedDict and Pydantic comparison schemas drift silently | HIGH | Route constructs `RerankerComparisonResponse` via `model_validate` or explicit field mapping, never `**comparison_dict` unpacking. |
| Developer-only comparison leaks into MCP user search | MEDIUM | Do not alter MCP search tool schema in this phase. |
| API response shape is untyped ad hoc JSON | MEDIUM | Use explicit Pydantic response models in `api/server.py`. |
</threat_model>

<tasks>
<task id="1" type="auto" tdd="true">
<name>Task 1: Add compare_rerankers service method</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/reranker.py`
- `backend/tests/test_hybrid_bm25.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
</files>
<behavior>
- Test 1: `compare_rerankers("q", ["qwen3-0.6b", "msmarco-minilm"])` calls `_collect_candidate_pool` once.
- Test 2: two mocked rerankers receive identical `chunk_ids` in identical order.
- Test 3: comparison result includes `elapsed_ms` for every reranker.
- Test 4: one reranker raising an exception produces a per-reranker `error` value while the other result is still returned.
- Test 5: overlap is computed from top chunk IDs, not scores.
</behavior>
<action>
In `backend/src/dotmd/api/service.py`, add comparison TypedDicts or small dataclasses near `ReadPayload`:

```python
class RerankerRunComparison(TypedDict):
    name: str
    model_name: str
    elapsed_ms: float
    returned_count: int
    top_chunk_ids: list[str]
    scores: list[float]
    error: str | None

class RerankerComparison(TypedDict):
    query: str
    search_query: str
    shared_pool_size: int
    rerankers: list[RerankerRunComparison]
    overlap_reference: str | None
    overlap: dict[str, int]
```

Add:

```python
def compare_rerankers(
    self,
    query: str,
    reranker_names: list[str] | None = None,
    top_k: int = 10,
    mode: SearchMode | str = SearchMode.HYBRID,
    expand: bool = True,
) -> RerankerComparison:
```

Implementation requirements:
- Expand query once using the same `QueryExpander` logic as `search()`.
- Use `pool_size = self._settings.rerank_pool_size`.
- Call `_collect_candidate_pool(...)` exactly once.
- Use `reranker_names or self._settings.parsed_reranker_compare_names`.
- For each name, resolve `self._reranker_factory.get(name)`.
- Time only the reranker call with `time.perf_counter()`.
- Pass the same `chunk_ids = [cid for cid, _ in pool["fused"][:pool_size]]` to each reranker.
- Record `scores` in the returned reranker order.
- Compute overlap counts between each candidate's top IDs and the first successful reranker's top IDs using `set`.
- Set `overlap_reference` to the first successful reranker name. If all rerankers fail, set `overlap_reference` to `None` and return `overlap == {}` with per-reranker errors.
- Do not call `build_search_results`; this is a diagnostic, not user search output.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `def compare_rerankers`.
- `backend/src/dotmd/api/service.py` contains `time.perf_counter`.
- `backend/src/dotmd/api/service.py` contains `shared_pool_size`.
- `backend/src/dotmd/api/service.py` contains `overlap_reference`.
- `backend/tests/api/test_service_search.py` tests that the shared candidate pool is collected once for multiple rerankers.
- `backend/tests/api/test_service_search.py` tests per-reranker error isolation.
- `backend/tests/api/test_service_search.py` tests that overlap uses the first successful reranker when the first configured reranker errors.
- `backend/tests/api/test_service_search.py` tests that all-reranker failure returns per-reranker errors and an empty overlap map instead of misleading zero-overlap values.
- `cd backend && uv run pytest tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
<done>
Service-level comparison exists and proves all rerankers share one candidate pool.
</done>
</task>

<task id="2" type="auto" tdd="true">
<name>Task 2: Expose runtime selection and comparison through FastAPI</name>
<read_first>
- `backend/src/dotmd/api/server.py`
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/server.py`
- `backend/tests/api/test_service_search.py`
</files>
<behavior>
- Test 1: `GET /search` accepts optional `reranker` and passes it to `DotMDService.search(..., reranker_name=...)`.
- Test 2: `GET /rerank/compare` parses comma-separated rerankers and calls `compare_rerankers`.
- Test 3: response includes `shared_pool_size` and per-reranker `elapsed_ms`.
- Test 4: unknown reranker names produce HTTP 400 with the factory's available-name message, not HTTP 500.
- Test 5: API response construction rejects or surfaces schema drift via Pydantic validation instead of silently dropping fields.
</behavior>
<action>
Update `backend/src/dotmd/api/server.py`:

- Add `reranker: str | None = Query(None)` to `GET /search`.
- Pass `reranker_name=reranker` into `_get_service().search(...)`.
- Add Pydantic response models:

```python
class RerankerRunComparisonResponse(BaseModel):
    name: str
    model_name: str
    elapsed_ms: float
    returned_count: int
    top_chunk_ids: list[str]
    scores: list[float]
    error: str | None = None

class RerankerComparisonResponse(BaseModel):
    query: str
    search_query: str
    shared_pool_size: int
    rerankers: list[RerankerRunComparisonResponse]
    overlap_reference: str | None = None
    overlap: dict[str, int]
```

- Add route:

```python
@app.get("/rerank/compare", response_model=RerankerComparisonResponse)
async def compare_rerankers(
    q: str = Query(..., description="Search query"),
    rerankers: str | None = Query(None, description="Comma-separated reranker names"),
    top_k: int = Query(10, ge=1, le=100),
    mode: SearchMode = Query(SearchMode.HYBRID),
    expand: bool = Query(True),
) -> RerankerComparisonResponse:
    names = [name.strip() for name in rerankers.split(",") if name.strip()] if rerankers else None
    comparison = _get_service().compare_rerankers(...)
    return RerankerComparisonResponse.model_validate(comparison)
```

Do not use `RerankerComparisonResponse(**comparison)` or other raw `**` unpacking between the service result and API model. If the executor chooses explicit mapping instead of `model_validate`, the mapping must list every response field by name: `query`, `search_query`, `shared_pool_size`, `rerankers`, `overlap_reference`, and `overlap`.

Wrap the service call so `ValueError` from unknown reranker names becomes:

```python
raise HTTPException(status_code=400, detail=str(exc)) from exc
```

This is a developer route. Do not add authentication, persistence, or a production scheduling layer in this phase.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/api/server.py` contains `reranker: str | None = Query(None`.
- `backend/src/dotmd/api/server.py` contains `/rerank/compare`.
- `backend/src/dotmd/api/server.py` contains `RerankerComparisonResponse`.
- `backend/src/dotmd/api/server.py` contains `RerankerComparisonResponse.model_validate` or explicit field-by-field response mapping.
- `backend/src/dotmd/api/server.py` does not contain `RerankerComparisonResponse(**`.
- `backend/src/dotmd/api/server.py` contains `HTTPException(status_code=400`.
- API tests cover the new parameter and route.
- API tests cover unknown reranker names returning 400.
- `cd backend && uv run pytest tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
<done>
FastAPI exposes both runtime selection and developer comparison with typed responses.
</done>
</task>

<task id="3" type="auto" tdd="true">
<name>Task 3: Expose runtime selection and comparison through CLI</name>
<read_first>
- `backend/src/dotmd/cli.py`
- `backend/tests/test_cli.py`
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/src/dotmd/cli.py`
- `backend/tests/test_cli.py`
</files>
<behavior>
- Test 1: `dotmd search QUERY --reranker msmarco-minilm` passes `reranker_name="msmarco-minilm"`.
- Test 2: `dotmd rerank compare QUERY --rerankers qwen3-0.6b,msmarco-minilm` calls `compare_rerankers`.
- Test 3: CLI output contains `elapsed_ms`, `shared_pool_size`, and both reranker names.
</behavior>
<action>
Update `backend/src/dotmd/cli.py`:

- Add to existing `search` command:

```python
@click.option("--reranker", default=None, help="Reranker name to use.")
```

and pass `reranker_name=reranker` to `service.search(...)`.

- Add a developer-only command group:

```python
@main.group("rerank")
def rerank_group() -> None:
    """Developer reranker diagnostics."""
```

- Add:

```python
@rerank_group.command("compare")
@click.argument("query")
@click.option("--rerankers", default=None, help="Comma-separated reranker names.")
@click.option("--top", "-n", default=10, help="Number of candidates to report.")
@click.option("--mode", type=click.Choice([m.value for m in SearchMode]), default="hybrid")
@click.option("--no-expand", is_flag=True, help="Skip query expansion.")
@click.pass_context
def compare(ctx: click.Context, query: str, rerankers: str | None, top: int, mode: str, no_expand: bool) -> None:
    ...
```

Output requirements:
- Print `Shared pool: N candidates`.
- For each reranker, print `name`, `model_name`, `elapsed_ms` formatted to one decimal, `returned_count`, and comma-separated top chunk IDs.
- Print `Overlap reference: <name>` before the overlap dict, using `none` if every reranker failed.
- Print overlap dict after the per-reranker rows.
- If a reranker has `error`, print `ERROR: <message>` on that row.
- Translate `ValueError` from unknown reranker names into a Click-friendly error (`raise click.ClickException(str(exc))`) instead of a traceback.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_cli.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/cli.py` contains `--reranker`.
- `backend/src/dotmd/cli.py` contains `@main.group("rerank")`.
- `backend/src/dotmd/cli.py` contains `@rerank_group.command("compare")`.
- CLI tests cover `--reranker`.
- CLI tests cover `rerank compare`.
- CLI tests cover unknown reranker names as a non-zero Click error with `Unknown reranker` in output.
- `cd backend && uv run pytest tests/test_cli.py -q` exits 0.
</acceptance_criteria>
<done>
CLI exposes the developer comparison and runtime selection paths.
</done>
</task>
</tasks>

<verification>
```bash
cd backend && uv run pytest tests/api/test_service_search.py tests/test_cli.py -q
cd backend && uv run ruff check src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/api/test_service_search.py tests/test_cli.py
```
</verification>

<success_criteria>
- Service comparison reuses one candidate pool across multiple rerankers.
- FastAPI has runtime selection and comparison endpoints.
- CLI has runtime selection and comparison commands.
- Comparison output includes latency, score diagnostics, ordered top IDs, overlap, and per-reranker errors.
- Unknown reranker names return HTTP 400 and CLI-friendly errors.
- API response validation/mapping is explicit enough to catch service/API schema drift.
- MCP search schema is not changed.
</success_criteria>
