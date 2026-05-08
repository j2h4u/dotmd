---
phase: "34"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/core/test_search_candidate.py
  - backend/tests/search/test_fusion.py
  - backend/tests/api/test_service_search.py
autonomous: true
requirements: ["SEARCH-01", "SEARCH-02", "SEARCH-03"]
requirements_addressed: ["SEARCH-01", "SEARCH-02", "SEARCH-03"]
must_haves:
  truths:
    - "D-01: SearchCandidate is the single public search-result type. SearchResult is removed (clean break, no compat alias)."
    - "D-02: Per-engine debug scores collapse into engine_scores: dict[str, float] | None. Federated candidates leave it None."
    - "D-03: Federated-only fields live in provider_metadata: dict[str, Any] | None catch-all."
    - "D-04: SearchCandidate carries ref, namespace, source_kind, retrieval_kind, title, snippet, fused_score, can_read, can_materialize, optional chunk_id/heading_path/matched_engines/provenance, optional source_native_score/rank, optional engine_scores, optional provider_metadata."
    - "D-05: Fusion key migrates from chunk_id to ref. Local engines hydrate chunk → ref through provenance BEFORE fusion."
    - "D-06: Per-engine weights remain available, default 1.0. Fusion stays rank-only."
    - "D-14: can_materialize=False for all Phase 34 candidates."
    - "D-18: Contract is generic enough that future federated providers add no new fields to SearchCandidate."
---

# Phase 34 Plan 01: SearchCandidate Contract And Ref-Keyed Local Fusion

<objective>
Replace `SearchResult` with `SearchCandidate` as the single public search
result type, migrate fusion from `chunk_id` keys to `ref` keys with
pre-fusion provenance hydration, and update local search/MCP paths so all
existing tests pass on the new shape — without introducing federated
behavior yet.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| `SearchResult` shape silently re-introduced via alias / shim | HIGH | Static scan `rg -n 'class SearchResult\b' backend/src` returns no matches; no `SearchResult = SearchCandidate` aliases anywhere. |
| RRF math regression when key changes | HIGH | Pin equivalent ranked input → identical RRF score across the chunk_id-keyed and ref-keyed pipelines. |
| Per-engine score map drifts (engines that didn't score a ref appear in `engine_scores`) | HIGH | Test asserts only matching engines populate `engine_scores`; absent key = engine didn't return this ref. |
| `provider_metadata` accidentally becomes a contract that downstream agents depend on | MEDIUM | Schema test pins `provider_metadata: dict[str, Any] | None`; documented as opaque. |
| Active-binding gate scope shifts (Phase 27 invariant breaks) | HIGH | Filter still operates on local refs only; ref-keyed test pins existing inactive-drop behavior. |
| Lifecycle bundle reload cost on every search | MEDIUM | Service init builds and caches lifecycle bundles; test asserts no per-request rebuild (covered fully in Plan 02; Plan 01 keeps existing service init unchanged). |
| MCP `SearchHit` schema drift breaks Claude Code | MEDIUM | MCP `SearchHit` keeps stable subset of `SearchCandidate` fields; existing MCP `search` tool tests still pass. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add SearchCandidate contract tests first</name>
<title>Add SearchCandidate contract tests first</title>
<read_first>
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-RESEARCH.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-PATTERNS.md`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/search/fusion.py`
</read_first>
<files>
- `backend/tests/core/test_search_candidate.py`
</files>
<action>
Create `backend/tests/core/test_search_candidate.py` with failing tests for
the new contract.

Concrete tests:

- `test_search_candidate_required_fields_pin_local_shape` constructs a
  `SearchCandidate` with only the locally-required fields (`ref`,
  `namespace`, `source_kind`, `retrieval_kind="semantic"`, `snippet`,
  `fused_score`, `can_read=True`) and asserts:
  - `can_materialize is False` by default.
  - `engine_scores is None` by default.
  - `provider_metadata is None` by default.
  - `source_native_score is None` and `source_native_rank is None` by default.
  - `matched_engines == []`.
- `test_search_candidate_required_fields_pin_federated_shape` constructs a
  federated candidate with `ref="telegram:dialog:1:message:7"`,
  `namespace="telegram"`, `source_kind="chat"`, `retrieval_kind="tg:fts"`,
  `snippet`, `fused_score`, `can_read=True`, `source_native_score=0.93`,
  `source_native_rank=0`, `provider_metadata={"dialog_id": 1}`. Assert:
  - `chunk_id is None`.
  - `provenance is None`.
  - `heading_path is None`.
  - `engine_scores is None`.
- `test_search_candidate_rejects_extra_fields` asserts
  `SearchCandidate(...extra_field="x")` raises Pydantic `ValidationError`
  containing `extra forbidden` or `extra_forbidden`.
- `test_search_candidate_is_frozen_after_construction` asserts attribute
  assignment after construction raises `ValidationError` (frozen=True).
- `test_search_candidate_validates_ref_namespace_separator` asserts
  constructing with `ref="badref"` (no `:`) raises `ValueError` with
  `"ref must be formatted"` in the message (mirroring existing
  `_validate_ref` semantics on `SearchResult`).
- `test_engine_scores_only_populated_for_matching_engines` constructs a
  candidate with `engine_scores={"semantic": 0.9}` and asserts the dict
  contains exactly `{"semantic"}` keys; absent keys are not auto-filled
  with 0.0 or None.
- `test_search_response_envelope_has_candidates_and_source_status` asserts
  `SearchResponse` shape with `candidates: list[SearchCandidate]` and
  `source_status: list[SourceStatus]`; `extra="forbid"`; `frozen=True`;
  empty defaults are explicit empty lists, not `None`.
- `test_source_status_required_fields` asserts `SourceStatus(name="semantic",
  status="ok", candidate_count=3, elapsed_ms=12.5)` with `reason=None`
  default; `status` is a Literal restricted to `{"ok", "skipped", "error"}`;
  setting `status="weird"` raises `ValidationError`.
- `test_search_result_symbol_no_longer_exported` asserts
  `from dotmd.core.models import SearchResult` raises `ImportError`. Also
  asserts the source file does not contain `class SearchResult\b` at module
  level via direct file read (defense-in-depth against accidental local
  alias).

Tests must fail before task 2.
</action>
<acceptance_criteria>
- `backend/tests/core/test_search_candidate.py` contains all eight tests
  named above.
- `cd backend && uv run pytest tests/core/test_search_candidate.py -q` exits
  non-zero before task 2 (model symbols don't exist yet) and exits 0 after
  task 2.
- Tests reference `SearchCandidate`, `SearchResponse`, `SourceStatus`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/core/test_search_candidate.py -q` fails
before task 2 because the new symbols do not exist yet.
</verify>
<done>
Contract tests exist and fail only for missing implementation.
</done>
</task>

<task id="2" type="tdd">
<name>Implement SearchCandidate, SearchResponse, SourceStatus; remove SearchResult</name>
<title>Implement SearchCandidate, SearchResponse, SourceStatus; remove SearchResult</title>
<read_first>
- `backend/tests/core/test_search_candidate.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
</files>
<action>
Replace `SearchResult` with `SearchCandidate` and add envelope models in
`backend/src/dotmd/core/models.py`:

- Define `class SearchCandidate(BaseModel)` with
  `model_config = ConfigDict(extra="forbid", frozen=True)` and fields:
  - `ref: str` (validator mirrors current `_validate_ref` from
    `SearchResult`).
  - `namespace: str`.
  - `source_kind: str`.
  - `retrieval_kind: str` (e.g. `"semantic"`, `"keyword"`, `"graph_direct"`,
    or a federated engine name like `"tg:fts"`).
  - `title: str | None = None`.
  - `snippet: str`.
  - `fused_score: float`.
  - `can_read: bool`.
  - `can_materialize: bool = False`.
  - `chunk_id: str | None = None`.
  - `heading_path: str | None = None`.
  - `matched_engines: list[str] = Field(default_factory=list)`.
  - `provenance: ChunkProvenance | None = None`.
  - `source_native_score: float | None = None`.
  - `source_native_rank: int | None = None`.
  - `engine_scores: dict[str, float] | None = None`.
  - `provider_metadata: dict[str, Any] | None = None`.
- Define `class SourceStatus(BaseModel)` with
  `model_config = ConfigDict(extra="forbid", frozen=True)` and fields:
  - `name: str`
  - `status: Literal["ok", "skipped", "error"]`
  - `reason: str | None = None`
  - `candidate_count: int = 0`
  - `elapsed_ms: float | None = None`
- Define `class SearchResponse(BaseModel)` with
  `model_config = ConfigDict(extra="forbid", frozen=True)` and fields:
  - `candidates: list[SearchCandidate] = Field(default_factory=list)`
  - `source_status: list[SourceStatus] = Field(default_factory=list)`
- **Remove** `class SearchResult` and the `SearchResult` import wherever it
  appears in `dotmd/core/models.py`.

Update `backend/src/dotmd/search/fusion.py`:

- `fuse_results` keeps its signature shape but its dict values are now
  `list[tuple[ref, score]]`; rename internal docstring/comments from
  "chunk_id" to "ref". Math is unchanged.
- Replace `build_search_results` with a new function
  `build_candidates(fused, per_engine, metadata_store, query, ref_to_chunk,
  active_provenance_map, top_k, snippet_length) -> list[SearchCandidate]`:
  - Local refs: pull `chunk_id`, `heading_hierarchy`, `text` (for snippet
    extraction) from the chunk metadata via the pre-built `ref_to_chunk`
    map. Set `can_read=True`, `can_materialize=False`, populate
    `matched_engines`, `engine_scores`, `provenance`, `chunk_id`,
    `heading_path`.
  - Per-engine score attribution: only include keys for engines whose
    ref-keyed list contains this `ref`.
- Add helper `def hydrate_local_engine_results(per_engine_chunk: dict[str,
  list[tuple[str, float]]], provenance_map: dict[str, ChunkProvenance]) ->
  dict[str, list[tuple[str, float]]]` that converts every engine's
  chunk-keyed list to ref-keyed list using the existing public ref helper
  `_public_ref_for_provenance`. Drop entries whose `chunk_id` has no
  provenance entry (defense — should not occur after Plan 1 hydration is
  enforced, but be tolerant). Preserve order; for duplicate refs in the
  same engine list, keep the first occurrence (highest rank).

Update `backend/src/dotmd/api/service.py`:

- Update return type of `DotMDService.search` to
  `list[SearchCandidate]` (Plan 01 keeps the previous list-shape; Plan 02
  switches to `SearchResponse`).
- Inside `_execute_search`:
  - Add a pre-fusion provenance hydration step that batch-loads
    `provenance_map` for all chunk_ids returned by local engines.
  - Convert every `engine_results` entry from chunk-keyed to ref-keyed via
    `hydrate_local_engine_results(per_engine_chunk, provenance_map)`.
  - Update the active-binding filter to operate on ref keys: rename the
    helper to `_filter_active_fused_candidates_by_ref` and update its
    logic to inspect `provenance_map` keyed by ref (not chunk_id).
  - Replace the call to `build_search_results` with the new
    `build_candidates` helper.
  - Update reranker integration: rerank still consumes chunk_ids; before
    reranking, look up `chunk_id` from the candidate (`candidate.chunk_id`),
    skip candidates whose `chunk_id is None` (pre-empts federated case in
    Plan 02; in Plan 01 there are no federated candidates yet but the
    skip path keeps the code stable). After reranking, blend back into the
    `fused: list[tuple[ref, float]]` shape.
- All references to `SearchResult` inside `service.py` become
  `SearchCandidate`. The search log writer (`self._pipeline.log_search`)
  consumes `chunk_id` from `candidate.chunk_id` (previously
  `result.chunk_id`); when `chunk_id is None`, log the ref instead.

Update `backend/src/dotmd/mcp_server.py`:

- `_format_result(r)` typed as `SearchCandidate`. The MCP `SearchHit`
  output model gets new optional fields:
  - `namespace: str | None = None`
  - `retrieval_kind: str | None = None`
  - `provider_metadata: dict[str, Any] | None = None`
  - existing `ref`, `heading`, `snippet`, `score` retained.
- Population: from a `SearchCandidate`,
  `SearchHit(ref=c.ref, namespace=c.namespace, retrieval_kind=c.retrieval_kind,
  heading=c.heading_path or None, snippet=clean(c.snippet),
  score=round(c.fused_score, 3), provider_metadata=c.provider_metadata)`.
- Use existing `_collapse_null` json_schema_extra for new optional fields
  if surfaced in the schema (only those that are `Optional[T]` per
  existing pattern).

Cross-file cleanup:
- `rg -n 'SearchResult\b' backend/src/dotmd | grep -v test_` must return
  zero matches at the end of this task.
- `rg -n 'SearchResult\b' backend/src/dotmd/core/models.py` returns no
  matches.
- All imports that referenced `from dotmd.core.models import SearchResult`
  switch to `from dotmd.core.models import SearchCandidate`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class SearchCandidate(BaseModel)`.
- `backend/src/dotmd/core/models.py` contains `class SearchResponse(BaseModel)`.
- `backend/src/dotmd/core/models.py` contains `class SourceStatus(BaseModel)`.
- `backend/src/dotmd/core/models.py` does NOT contain `class SearchResult`.
- `backend/src/dotmd/search/fusion.py` contains `def build_candidates`.
- `backend/src/dotmd/search/fusion.py` contains `def hydrate_local_engine_results`.
- `backend/src/dotmd/search/fusion.py` does NOT contain `def build_search_results`.
- `backend/src/dotmd/api/service.py` does NOT contain `SearchResult`.
- `backend/src/dotmd/mcp_server.py` `SearchHit` includes `namespace` and `retrieval_kind` fields.
- `cd backend && uv run pytest tests/core/test_search_candidate.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py src/dotmd/mcp_server.py tests/core/test_search_candidate.py` exits 0.
- `rg -n 'class SearchResult\b' backend/src` returns no matches.
- `rg -n 'from dotmd\.core\.models import.*SearchResult' backend/` returns no matches.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/core/test_search_candidate.py -q`
`cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py src/dotmd/mcp_server.py tests/core/test_search_candidate.py`
`rg -n 'class SearchResult\b' backend/src`
`rg -n 'from dotmd\.core\.models import.*SearchResult' backend/`
</verify>
<done>
`SearchCandidate`, `SearchResponse`, `SourceStatus` exist; `SearchResult` is
gone from production code; type checks and Pydantic contract tests pass.
</done>
</task>

<task id="3" type="tdd">
<name>Update fusion regression and service search regression for ref-keyed shape</name>
<title>Update fusion regression and service search regression for ref-keyed shape</title>
<read_first>
- `backend/tests/search/test_fusion.py` (existing)
- `backend/tests/api/test_service_search.py` (existing)
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/api/service.py`
</read_first>
<files>
- `backend/tests/search/test_fusion.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Update existing fusion and service-search tests to assert ref-keyed
behavior and migrate the inactive-binding test to the new helper name.

`backend/tests/search/test_fusion.py`:
- Update `fuse_results` direct tests to use ref-shaped strings (e.g.
  `"filesystem:/tmp/a.md#0"`, `"filesystem:/tmp/b.md#0"`) instead of bare
  `chunk_id` placeholders. Math assertions unchanged.
- Add `test_fuse_results_math_equivalence_chunk_keys_vs_ref_keys` that
  asserts: given the same ranked input shape, fusion scores are numerically
  identical regardless of whether keys are arbitrary chunk_id strings or
  ref strings (RRF math is key-opaque).
- Add `test_hydrate_local_engine_results_drops_chunks_without_provenance`
  that asserts `hydrate_local_engine_results({"semantic": [("c1", 0.9)]},
  provenance_map={})` returns `{"semantic": []}` (defensive drop).
- Add `test_build_candidates_only_attributes_engines_that_scored_the_ref`
  that asserts `engine_scores` for a ref scored only by `semantic` contains
  exactly `{"semantic"}` and not `{"semantic", "keyword"}` even when
  `keyword` ranked other refs.
- Add `test_build_candidates_sets_can_read_true_and_can_materialize_false_for_local`.

`backend/tests/api/test_service_search.py`:
- Add `test_local_only_search_returns_searchcandidate` that asserts
  `service.search("foo")` returns `list[SearchCandidate]` (Plan 01 contract;
  Plan 02 swaps to `SearchResponse`).
- Add `test_active_binding_filter_drops_inactive_local_refs_only` covering
  the renamed `_filter_active_fused_candidates_by_ref` (preserves Phase 27
  behavior; federated-only refs are not in scope yet but the test pins the
  helper signature).
- Update any existing assertion that imported / instantiated `SearchResult`
  to use `SearchCandidate`.
</action>
<acceptance_criteria>
- `backend/tests/search/test_fusion.py` contains
  `test_fuse_results_math_equivalence_chunk_keys_vs_ref_keys`,
  `test_hydrate_local_engine_results_drops_chunks_without_provenance`,
  `test_build_candidates_only_attributes_engines_that_scored_the_ref`,
  `test_build_candidates_sets_can_read_true_and_can_materialize_false_for_local`.
- `backend/tests/api/test_service_search.py` contains
  `test_local_only_search_returns_searchcandidate` and
  `test_active_binding_filter_drops_inactive_local_refs_only`.
- `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/api/test_service_search.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py tests/search/test_fusion.py tests/api/test_service_search.py` exits 0.
- `rg -n 'SearchResult' backend/tests` returns matches only inside this
  task's commit referencing the removal (or zero matches if the test sweep
  is complete).
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/api/test_service_search.py -q`
`cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py tests/search/test_fusion.py tests/api/test_service_search.py`
`rg -n 'SearchResult' backend/tests`
</verify>
<done>
Fusion regression and service-search regression tests pin ref-keyed local
behavior; no `SearchResult` references remain anywhere in the repo (src or
tests) at this commit.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/api/test_service_search.py -q`
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py src/dotmd/mcp_server.py tests/core/test_search_candidate.py tests/search/test_fusion.py tests/api/test_service_search.py`
- `rg -n 'class SearchResult\b' backend/src`
- `rg -n 'from dotmd\.core\.models import.*SearchResult' backend/`
- `rg -n 'SearchResult' backend/tests`
</verification>

<success_criteria>
- SEARCH-01 has a single public `SearchCandidate` shape covering local hits.
- SEARCH-02 has all required fields (`ref`, source identity, title, snippet,
  retrieval kind, provenance, `can_read`, `can_materialize`, optional
  source-native score/rank, optional engine_scores, optional
  provider_metadata).
- SEARCH-03 has rank-only RRF; key migrated from chunk_id to ref;
  per-engine attribution preserved.
- `SearchResult` is gone from production code; no compat alias.
- Active-binding gate continues to filter inactive local refs (Phase 27
  invariant preserved).
- Federated fan-out is NOT yet integrated; that work is owned by Plan 02.
</success_criteria>
