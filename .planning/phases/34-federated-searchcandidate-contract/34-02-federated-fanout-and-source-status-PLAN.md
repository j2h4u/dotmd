---
phase: "34"
plan: "02"
type: tdd
wave: 2
depends_on: ["34-01"]
files_modified:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/search/federated.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/search/test_federated.py
  - backend/tests/api/test_service_search.py
  - backend/tests/mcp/test_mcp_search_envelope.py
  - backend/tests/search/conftest.py
autonomous: true
requirements: ["SEARCH-01", "SEARCH-03"]
requirements_addressed: ["SEARCH-01", "SEARCH-03"]
must_haves:
  truths:
    - "D-06: Federated providers participate in the same RRF as local engines. Engine names are namespaced (e.g. tg:fts). Per-engine weights remain. Fusion stays rank-only."
    - "D-07: Cross-encoder reranker is unchanged. Federated candidates without snippet text skip reranking and keep RRF score."
    - "D-08: Federated fan-out is always-on by default. Every service.search() queries all local engines plus all sources whose descriptor declares FEDERATED_SEARCH and whose lifecycle bundle is constructible."
    - "D-09: Per-source soft timeout (3-5s default, config-tunable). Failure detection only — not throughput shaping."
    - "D-10: MCP-level source filter parameters are deferred. Always-on fan-out at the MCP surface."
    - "D-11: Soft-skip per source on error/timeout. service.search() returns SearchResponse{candidates, source_status}. Local engines report through the same status surface."
    - "D-12: No fail-fast."
    - "D-18: Adding a second federated provider in a later phase requires no Phase 34 contract edits."
---

# Phase 34 Plan 02: Federated Fan-out, Soft Timeout, And SearchResponse Envelope

<objective>
Add federated fan-out infrastructure: optional `search_native` protocol on
the lifecycle bundle, parallel `asyncio.gather` with per-source soft
timeout, `SourceStatus` collection for every fanned-out engine, the
`SearchResponse` envelope return shape on `DotMDService.search`, and the
MCP `search` tool envelope. Drives the contract end-to-end with a stub
federated provider — Telegram wiring is owned by Plan 03.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| One stuck federated source blocks the entire response | HIGH | Per-source `asyncio.wait_for(coro, timeout=N)` with config-driven timeout; total wall-time test pins behavior. |
| Federated source error breaks the query (fail-fast regression) | HIGH | Test stub raises; assert local results survive; `source_status` reports the error. |
| Provider-native scores leak into RRF as direct comparisons | HIGH | Federated stubs return absurd `source_native_score`; assert RRF rank-only — local hit at rank 1 still beats federated hit at rank 5 regardless of raw scores. |
| Lifecycle bundle rebuilt per request | HIGH | Service builds bundles once at init; mock asserts `factory.build_if_configured` called only at init. |
| Reranker called on candidates without snippet → CrossEncoder error | MEDIUM | Skip reranker for candidates whose snippet is empty; assertion test asserts they retain RRF score. |
| MCP envelope schema regression breaks Claude Code | MEDIUM | Integration test through `mcp.server.fastmcp` test harness; pins schema keys. |
| Source filter params slip in early | MEDIUM | MCP search tool keeps signature `(query, top_k)`; test pins absence of `sources`/`exclude_sources` params. |
| `tg:fts` namespacing collides with engine names ("semantic", "keyword", "graph_direct") | MEDIUM | Engine name registry prevents collisions; test asserts federated engines use namespace prefix. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add federated fan-out and source-status tests first</name>
<title>Add federated fan-out and source-status tests first</title>
<read_first>
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-RESEARCH.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-PATTERNS.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/source_provider.py`
</read_first>
<files>
- `backend/tests/search/test_federated.py`
- `backend/tests/search/conftest.py`
</files>
<action>
Create `backend/tests/search/conftest.py` (or extend if it exists) with
fixtures:

- `StubFederatedProvider` — minimal class implementing
  `FederatedSearchProviderProtocol` (will be added in task 2). Methods:
  - `search_native(query: str, limit: int) -> list[SearchCandidate]` — sync
    method (the executor wraps it via `asyncio.to_thread`).
  - Configurable behavior via constructor: `(candidates, sleep_seconds=0,
    raises=None)`. When `sleep_seconds > 0`, the call sleeps before
    returning. When `raises` is set, the call raises the given exception.
- `slow_federated_provider(seconds)` factory.
- `failing_federated_provider(exc)` factory.
- `make_federated_bundle(name="stub", capabilities=None, provider=None)`
  factory that returns a fake `SourceRuntimeBundle` whose
  `supports_federated_search` is True (set
  `descriptor.capabilities=[SourceCapability.FEDERATED_SEARCH]` and attach
  the stub provider).

Create `backend/tests/search/test_federated.py` with failing tests:

- `test_engine_outcome_ok_carries_candidates_and_elapsed` — runs
  `_run_one("stub", coro_returning(2 candidates), timeout=5.0)` and asserts
  `outcome.status == "ok"`, `len(outcome.candidates) == 2`,
  `outcome.elapsed_ms is not None`.
- `test_engine_outcome_timeout_yields_skipped_with_reason_timeout` — uses
  `slow_federated_provider(seconds=10)` with `timeout=0.1`. Asserts
  `outcome.status == "skipped"`, `outcome.reason == "timeout"`,
  `outcome.candidates == []`, `outcome.elapsed_ms < 1000`.
- `test_engine_outcome_exception_yields_error_with_reason_message` — uses
  `failing_federated_provider(RuntimeError("daemon down"))`. Asserts
  `outcome.status == "error"`, `"daemon down" in outcome.reason`,
  `outcome.candidates == []`.
- `test_fanout_runs_in_parallel` — three federated providers each sleep 1s
  with timeout 5s; total fan-out wall time < 1.5s (parallel proof).
- `test_fanout_collects_source_status_for_every_engine_including_local` —
  given two local outcomes (`semantic` ok, `keyword` ok) and one federated
  outcome (`stub:fts` error), assert returned `list[SourceStatus]` has
  three entries with names `semantic`, `keyword`, `stub:fts`.
- `test_soft_timeout_does_not_block_response` — combines a fast local
  semantic outcome with a slow federated provider exceeding timeout;
  assert total wall time < `local_engine_time + timeout + 200ms slack`.
- `test_source_error_soft_skip_does_not_break_query` — federated provider
  raises, semantic returns 5 candidates; `service.search("foo")` returns
  `SearchResponse` with the 5 local candidates and a
  `SourceStatus(status="error")` for the federated source. No exception
  propagates.
- `test_source_status_attributes_each_engine` — every fanned-out engine
  produces exactly one `SourceStatus`. No duplicate entries even when an
  engine returns 0 candidates.

Tests must fail before task 2.
</action>
<acceptance_criteria>
- `backend/tests/search/conftest.py` contains `StubFederatedProvider`,
  `slow_federated_provider`, `failing_federated_provider`,
  `make_federated_bundle`.
- `backend/tests/search/test_federated.py` contains the eight tests named
  above.
- `cd backend && uv run pytest tests/search/test_federated.py -q` exits
  non-zero before task 2 (federated module/protocol does not exist).
- Tests reference `_run_one`, `EngineOutcome`, `SearchResponse`,
  `SourceStatus`, `FederatedSearchProviderProtocol`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py -q` fails
before task 2 because the federated module symbols do not exist yet.
</verify>
<done>
Federated fan-out tests exist and fail only for missing implementation.
</done>
</task>

<task id="2" type="tdd">
<name>Implement federated fan-out helper, protocol, and lifecycle bundle capability</name>
<title>Implement federated fan-out helper, protocol, and lifecycle bundle capability</title>
<read_first>
- `backend/tests/search/test_federated.py`
- `backend/tests/search/conftest.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/src/dotmd/search/federated.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/core/config.py`
</files>
<action>
Create `backend/src/dotmd/search/federated.py`:

- Define `@dataclass(frozen=True) class EngineOutcome` with fields:
  - `name: str`
  - `status: Literal["ok", "skipped", "error"]`
  - `candidates: list[SearchCandidate]`
  - `reason: str | None`
  - `elapsed_ms: float`
- Define `async def _run_one(name: str, fn: Callable[[], Awaitable[list[SearchCandidate]]] | Callable[[], list[SearchCandidate]], timeout: float) -> EngineOutcome`:
  - Detect whether `fn()` returns a coroutine; if not, wrap with
    `asyncio.to_thread`.
  - Apply `asyncio.wait_for(coro, timeout=timeout)`.
  - On `asyncio.TimeoutError`: return `EngineOutcome(name, "skipped", [], "timeout", elapsed_ms)`.
  - On any other `Exception`: log warning with `exc_info=True`, return
    `EngineOutcome(name, "error", [], str(exc), elapsed_ms)`.
  - On success: return `EngineOutcome(name, "ok", result, None, elapsed_ms)`.
- Define `async def fanout_search(engine_calls: dict[str, Callable[[], Awaitable[list[SearchCandidate]] | list[SearchCandidate]]], timeout: float) -> list[EngineOutcome]`:
  - `outcomes = await asyncio.gather(*[_run_one(name, fn, timeout) for name, fn in engine_calls.items()])`.
  - Return outcomes in **input dict iteration order** (Python 3.12+ dicts
    preserve insertion order). Pin order with a test.
- Define `def outcomes_to_source_status(outcomes: Sequence[EngineOutcome]) -> list[SourceStatus]`:
  - Map each outcome to `SourceStatus(name, status, reason, candidate_count=len(candidates), elapsed_ms)`.

Update `backend/src/dotmd/ingestion/source_provider.py`:

- Add `class FederatedSearchProviderProtocol(Protocol)`:
  ```python
  class FederatedSearchProviderProtocol(Protocol):
      def search_native(self, query: str, limit: int) -> list[SearchCandidate]: ...
  ```
- Do NOT extend `ApplicationSourceProviderProtocol` (Phase 28 surface
  stays untouched).

Update `backend/src/dotmd/ingestion/source_lifecycle.py`:

- Add a `supports_federated_search` `@property` to `SourceRuntimeBundle`:
  ```python
  @property
  def supports_federated_search(self) -> bool:
      if SourceCapability.FEDERATED_SEARCH not in self.descriptor.capabilities:
          return False
      provider = self.provider
      if provider is None:
          return False
      return callable(getattr(provider, "search_native", None))
  ```
- No constructor changes required.

Update `backend/src/dotmd/core/config.py`:

- Add a `federated_timeout_seconds: float = 4.0` setting (between 3.0 and
  5.0 per D-09 default range; pick 4.0). Mark as tunable through env var
  `DOTMD_FEDERATED_TIMEOUT_SECONDS`.
- Add a `federated_engine_weights: dict[str, float] = Field(default_factory=dict)`
  setting (parsed from env if convenient; no env wiring required if
  costly — leave config-only for Phase 34, env wiring is a deferred task).
</action>
<acceptance_criteria>
- `backend/src/dotmd/search/federated.py` contains
  `class EngineOutcome`, `async def _run_one`, `async def fanout_search`,
  `def outcomes_to_source_status`.
- `backend/src/dotmd/ingestion/source_provider.py` contains
  `class FederatedSearchProviderProtocol(Protocol)` with `search_native`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` `SourceRuntimeBundle`
  has a `supports_federated_search` property.
- `backend/src/dotmd/core/config.py` contains
  `federated_timeout_seconds: float = 4.0` (verify with `rg`).
- `cd backend && uv run pytest tests/search/test_federated.py -q` exits 0
  for the three `_run_one`-shape tests and the parallel-fanout test (the
  service-level tests are wired in task 3).
- `cd backend && uv run pyright src/dotmd/search/federated.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/core/config.py tests/search/test_federated.py tests/search/conftest.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py -q -k 'engine_outcome or fanout_runs_in_parallel'`
`cd backend && uv run pyright src/dotmd/search/federated.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/core/config.py tests/search/test_federated.py tests/search/conftest.py`
</verify>
<done>
Fan-out helper, federated protocol, and lifecycle capability discovery
exist and are typed/test-pinned at the helper level.
</done>
</task>

<task id="3" type="tdd">
<name>Wire federated fan-out into DotMDService.search and switch return shape to SearchResponse</name>
<title>Wire federated fan-out into DotMDService.search and switch return shape to SearchResponse</title>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/federated.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/tests/search/test_federated.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Add lifecycle-bundle caching and fan-out orchestration to `DotMDService`.

In `DotMDService.__init__`:

- Build a `SourceRuntimeFactory` and call `build_if_configured(namespace)`
  for every namespace registered in `self._registry` (from the existing
  Phase 32-33 plumbing). Cache results in
  `self._lifecycle_bundles: dict[str, SourceRuntimeBundle]`. Skip
  namespaces returning `None`.
- Compute `self._federated_bundles: list[SourceRuntimeBundle]` once at
  init by filtering `bundle.supports_federated_search`.

Refactor `DotMDService.search` (currently sync) to support async fan-out
without changing the public sync contract:

- Public `def search(self, query, ...) -> SearchResponse` — runs
  `asyncio.run(self._search_async(query, ...))` if no event loop is
  running, otherwise schedules onto the existing loop using a guarded
  helper. Document the sync wrapper.
- New `async def _search_async(self, query, top_k, mode, rerank, expand,
  reranker_name) -> SearchResponse`:
  - Stage 1 — compose engine call dict:
    ```python
    engine_calls: dict[str, Callable] = {}
    engine_calls["semantic"] = lambda: self._semantic_engine.search(query, top_k=pool_size)
    engine_calls["keyword"]  = lambda: self._keyword_engine.search(query, top_k=pool_size)
    engine_calls["graph_direct"] = lambda: self._graph_direct_engine.search(query, top_k=pool_size)
    for bundle in self._federated_bundles:
        name = self._federated_engine_name(bundle)  # e.g. "tg:fts"
        engine_calls[name] = lambda b=bundle: b.provider.search_native(query, limit=pool_size)
    ```
  - Stage 2 — fan out:
    ```python
    outcomes = await fanout_search(engine_calls, timeout=self._settings.federated_timeout_seconds)
    ```
  - Stage 3 — split outcomes into local-engine ranked lists (chunk-keyed)
    and federated `SearchCandidate` lists.
  - Stage 4 — hydrate local lists chunk_id → ref via the existing batch
    provenance call (`hydrate_local_engine_results` from Plan 01).
  - Stage 5 — convert federated `list[SearchCandidate]` to ref-keyed
    ranked list `[(c.ref, c.source_native_score or 1.0)]` (rank-only RRF
    means the score value is just a sentinel; rank position is what
    matters).
  - Stage 6 — `fuse_results(per_engine_ref, k=settings.fusion_k,
    engine_weights=settings.federated_engine_weights | local_weights)`.
  - Stage 7 — apply active-binding filter to fused results: federated-only
    refs (no entry in `provenance_map`) bypass the filter; local refs
    follow the existing inactive drop logic.
  - Stage 8 — build candidates: `build_candidates_with_federated(fused,
    per_engine_ref, ref_to_local_metadata, ref_to_federated_candidate,
    query, top_k)` (extend `build_candidates` from Plan 01 to accept a
    `federated_candidates_by_ref: dict[str, SearchCandidate]` and merge
    per-engine score attribution from federated engine names).
  - Stage 9 — optional reranker: pass through candidates whose
    `chunk_id is None` AS-IS (skip rerank), keep their RRF score.
  - Stage 10 — assemble `SearchResponse(candidates=top_k_candidates,
    source_status=outcomes_to_source_status(outcomes))`.

- Helper `def _federated_engine_name(self, bundle: SourceRuntimeBundle) -> str`:
  - For `telegram` namespace: return `"tg:fts"`.
  - General fallback: `f"{bundle.descriptor.namespace}:fts"`.

In `backend/tests/api/test_service_search.py`:

- Update `test_local_only_search_returns_searchcandidate` (from Plan 01)
  to assert `service.search("foo")` returns a `SearchResponse`.
- Add `test_lifecycle_bundles_built_once` — mock `SourceRuntimeFactory`;
  assert `build_if_configured` is called only during `DotMDService.__init__`
  and not during search.
- Add `test_search_response_envelope_has_local_source_status` — service
  with no federated providers; assert `response.source_status` has at
  least entries for local engines (`semantic`, `keyword`, `graph_direct`).
- Add `test_search_response_includes_federated_source_status_when_bundle_present`
  — service with a stub federated bundle; assert `source_status` includes
  the bundle's engine name.
- Add `test_federated_only_ref_bypasses_active_binding_filter` — stub
  federated provider returns one ref unknown to local store; assert it
  appears in `response.candidates` (not dropped by inactive filter).
- Add `test_provider_native_score_does_not_outrank_local_via_raw_score`
  — stub federated provider returns a candidate with
  `source_native_score=1e6` at rank 5; semantic returns a hit at rank 1;
  assert local hit's RRF score > federated hit's RRF score.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` `DotMDService.__init__` builds and
  caches lifecycle bundles. (`rg -n 'self\._lifecycle_bundles' backend/src/dotmd/api/service.py` returns matches.)
- `backend/src/dotmd/api/service.py` defines `_search_async` and
  `_federated_engine_name`.
- `DotMDService.search` returns `SearchResponse` (verified by type
  annotation and tests).
- `cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/api/service.py src/dotmd/search/federated.py tests/search/test_federated.py tests/api/test_service_search.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py -q`
`cd backend && uv run pyright src/dotmd/api/service.py src/dotmd/search/federated.py tests/search/test_federated.py tests/api/test_service_search.py`
</verify>
<done>
`DotMDService.search` returns `SearchResponse`, fans out across local
engines plus stub federated providers, applies per-source soft timeout,
and reports per-engine status.
</done>
</task>

<task id="4" type="tdd">
<name>Update MCP search tool envelope</name>
<title>Update MCP search tool envelope</title>
<read_first>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/` (existing)
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/test_mcp_search_envelope.py`
</files>
<action>
Update the MCP `search` tool to return the new envelope.

`backend/src/dotmd/mcp_server.py`:

- Define `class SearchEnvelope(BaseModel)`:
  ```python
  class SearchEnvelope(BaseModel):
      results: list[SearchHit]
      source_status: list[dict[str, Any]]
  ```
- `SearchHit` (from Plan 01) keeps its current fields plus the optional
  new ones (namespace, retrieval_kind, provider_metadata).
- Update `@mcp.tool(name="search", ...)` `async def search(query: str,
  top_k: int = 10) -> SearchEnvelope`:
  ```python
  response = await asyncio.to_thread(service.search, query, top_k=top_k)
  return SearchEnvelope(
      results=[_format_result(c) for c in response.candidates],
      source_status=[s.model_dump() for s in response.source_status],
  )
  ```
- Tool docstring: add a short paragraph explaining `source_status`:
  > The `source_status` array reports which engines participated in this
  > query and whether each one returned results, was skipped (e.g.
  > timeout), or errored. Use it to understand why a query may have
  > returned fewer results than expected.
- Do NOT add `sources` or `exclude_sources` parameters (D-10).

`backend/tests/mcp/test_mcp_search_envelope.py`:

- Add an integration test that loads the MCP server, calls the `search`
  tool with `query="foo"` against a service whose lifecycle has a stub
  federated bundle, and asserts:
  - response shape is `{"results": [...], "source_status": [...]}`.
  - each item in `results` has `ref`, `snippet`, `score` and the optional
    `namespace` and `retrieval_kind` fields when set.
  - `source_status` contains entries for `semantic`, `keyword`,
    `graph_direct`, plus the stub federated engine name.
- Add `test_mcp_search_signature_does_not_include_source_filters` —
  asserts the tool's input schema does not include `sources` or
  `exclude_sources` parameters (defense against accidental D-10 violation).
</action>
<acceptance_criteria>
- `backend/src/dotmd/mcp_server.py` contains `class SearchEnvelope(BaseModel)`.
- `backend/src/dotmd/mcp_server.py` `search` tool returns `SearchEnvelope`.
- `backend/tests/mcp/test_mcp_search_envelope.py` contains the integration
  test plus `test_mcp_search_signature_does_not_include_source_filters`.
- `cd backend && uv run pytest tests/mcp/test_mcp_search_envelope.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/mcp_server.py tests/mcp/test_mcp_search_envelope.py` exits 0.
- `rg -n '"sources"' backend/src/dotmd/mcp_server.py` returns no matches in the `search` tool definition.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/mcp/test_mcp_search_envelope.py -q`
`cd backend && uv run pyright src/dotmd/mcp_server.py tests/mcp/test_mcp_search_envelope.py`
`rg -n 'sources\s*:.*Annotated' backend/src/dotmd/mcp_server.py`
</verify>
<done>
MCP `search` tool returns `SearchEnvelope` with `source_status`; no source
filter parameters present.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/search/test_federated.py tests/api/test_service_search.py tests/mcp/test_mcp_search_envelope.py tests/core/test_search_candidate.py tests/search/test_fusion.py -q`
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/config.py src/dotmd/search/fusion.py src/dotmd/search/federated.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/mcp/test_mcp_search_envelope.py`
- `rg -n 'FederatedSearchError' backend/src/dotmd/search backend/src/dotmd/api` returns no matches (fail-fast pattern explicitly rejected).
- `rg -n 'sources\s*:\s*Annotated' backend/src/dotmd/mcp_server.py` returns no matches in the `search` tool definition.
</verification>

<success_criteria>
- SEARCH-01 has a federated-aware service surface that emits one
  `SearchResponse` envelope.
- SEARCH-03 has rank-only RRF in which provider-native scores cannot
  outrank local hits via raw score.
- D-08, D-09, D-11, D-12 behaviors are pinned: always-on fan-out,
  configurable per-source timeout, soft-skip with reason attribution, no
  fail-fast.
- D-10 is preserved at the MCP surface (no source filter parameters).
- D-18 generic-enough check: adding a second federated provider in Plan 03
  requires NO Phase 34 contract or fan-out edits — only a new lifecycle
  bundle with `search_native`. (Plan 03 is the proof.)
</success_criteria>
