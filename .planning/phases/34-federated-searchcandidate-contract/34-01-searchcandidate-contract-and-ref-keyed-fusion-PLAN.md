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
    - "D-01: SearchCandidate is the single public search-result type at BOTH service and MCP layers. SearchResult is removed (clean break, no compat alias). MCP returns SearchCandidate directly — no narrowing SearchHit subset model. (cycle-2 HIGH-2 fix)"
    - "D-02: Per-engine debug scores collapse into engine_scores: dict[str, float] | None. Federated candidates leave it None."
    - "D-03: Federated-only fields live in provider_metadata: dict[str, Any] | None catch-all."
    - "D-04: SearchCandidate carries ref, namespace, descriptor_key (source descriptor identity), source_kind, retrieval_kind, title, snippet, fused_score, can_read, can_materialize, optional chunk_id/heading_path/matched_engines/provenance, optional source_native_score/rank, optional engine_scores, optional provider_metadata. descriptor_key uniquely identifies the source descriptor (e.g. 'telegram' for the Telegram descriptor, 'filesystem-mnt' for a filesystem descriptor); namespace + descriptor_key together form the source identity required by SEARCH-02. (cycle-2 HIGH-1 fix)"
    - "D-05: Fusion key migrates from chunk_id to ref. Local engines hydrate chunk → ref through provenance BEFORE fusion."
    - "D-06: Per-engine weights remain available, default 1.0. Fusion stays rank-only."
    - "D-14: can_materialize=False for all Phase 34 candidates."
    - "D-18: Contract is generic enough that future federated providers add no new fields to SearchCandidate."
    - "D-IMM: Mutability of container fields (matched_engines list, engine_scores dict, provider_metadata dict) is 'frozen-shallow' — Pydantic frozen=True rejects top-level rebinding but does NOT freeze container contents. Tests deterministically pin BOTH halves: rebinding raises ValidationError; container mutation (.append, key assignment) succeeds without raising. The model docstring documents this as a contract: callers must not mutate container fields. Deep immutability via tuple/MappingProxyType was rejected — too much coercion at construction sites for no compile-time benefit. (cycle-2 MEDIUM fold-in; cycle-3 MEDIUM determinism fix)"
    - "D-REF-COLLAPSE: When multiple local chunks map to the same ref during pre-fusion collapse, the candidate with the highest fused_score wins; ties broken by lowest chunk_id; the resulting SearchCandidate.chunk_id and snippet come from the winning chunk. (cycle-2 MEDIUM fold-in)"
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
| MCP narrowing reintroduces SearchHit subset (cycle-2 HIGH-2 regression) | HIGH | MCP `search` tool returns `SearchCandidate` directly (or a `SearchResponse` envelope containing full `SearchCandidate` records); no `SearchHit` model exists. Test asserts MCP response includes `can_read`, `can_materialize`, `source_native_score`, `source_native_rank`, `descriptor_key` when the field is set on the underlying candidate. |
| `descriptor_key` missing or conflated with `source_kind` (cycle-2 HIGH-1) | HIGH | `SearchCandidate.descriptor_key: str` is required (no default). Test pins that two candidates with identical `namespace` + `source_kind` but different `descriptor_key` are distinguishable. `rg -n 'descriptor_key' backend/src/dotmd/core/models.py` returns the field declaration. |
| Multiple local chunks collapse to one ref losing snippet/metadata | MEDIUM | Deterministic tie-break: highest fused_score wins, ties broken by lowest chunk_id. Test pins exact winning chunk_id when two chunks share a ref. |
| Frozen=True misrepresents deep immutability of list/dict fields | MEDIUM | Tests pin BOTH halves of the shallow-freeze contract deterministically (cycle-3 MEDIUM determinism fix): (1) attribute rebinding raises ValidationError for every field including container fields; (2) container mutation (`.append`, key assignment) succeeds without raising. Model docstring documents shallow-freeze as a contract. Deep immutability via tuple/MappingProxyType was considered and rejected — see D-IMM rationale. |
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

Concrete tests (eleven total — each addresses a contract surface; **the eight
foundational tests plus the three cycle-2 review additions for descriptor_key
and frozen-shallow semantics**):

- `test_search_candidate_required_fields_pin_local_shape` constructs a
  `SearchCandidate` with only the locally-required fields (`ref`,
  `namespace`, `descriptor_key="filesystem-mnt"`, `source_kind`,
  `retrieval_kind="semantic"`, `snippet`, `fused_score`, `can_read=True`)
  and asserts:
  - `can_materialize is False` by default.
  - `engine_scores is None` by default.
  - `provider_metadata is None` by default.
  - `source_native_score is None` and `source_native_rank is None` by default.
  - `matched_engines == []`.
- `test_search_candidate_required_fields_pin_federated_shape` constructs a
  federated candidate with `ref="telegram:dialog:1:message:7"`,
  `namespace="telegram"`, `descriptor_key="telegram"`, `source_kind="chat"`,
  `retrieval_kind="tg:fts"`, `snippet`, `fused_score`, `can_read=True`,
  `source_native_score=0.93`, `source_native_rank=0`,
  `provider_metadata={"dialog_id": 1}`. Assert:
  - `chunk_id is None`.
  - `provenance is None`.
  - `heading_path is None`.
  - `engine_scores is None`.
- `test_search_candidate_descriptor_key_is_required` (**cycle-2 HIGH-1 fix**)
  asserts that constructing a `SearchCandidate` without `descriptor_key`
  raises `ValidationError` (no default value); explicitly pins that
  `descriptor_key` and `source_kind` are independent fields — two candidates
  may share `namespace="filesystem"` and `source_kind="markdown"` while
  having different `descriptor_key` values (e.g. `"filesystem-mnt"` vs
  `"filesystem-srv"`) and remain distinguishable. Construct two candidates
  with identical `namespace`, `source_kind`, and `ref` namespace prefix but
  different `descriptor_key` values; assert they are NOT equal.
- `test_search_candidate_rejects_extra_fields` asserts
  `SearchCandidate(...extra_field="x")` raises Pydantic `ValidationError`
  containing `extra forbidden` or `extra_forbidden`.
- `test_search_candidate_is_frozen_after_construction` asserts attribute
  assignment after construction raises `ValidationError` (frozen=True for
  scalar attribute rebinding).
- `test_search_candidate_frozen_is_shallow_for_container_fields` (**cycle-2
  MEDIUM fold-in; cycle-3 MEDIUM determinism fix**) constructs a candidate
  with `matched_engines=["semantic"]`, `engine_scores={"semantic": 0.9}`,
  and `provider_metadata={"k": "v"}`. **Pins ONE contract — Pydantic
  shallow-freeze, mutation-succeeds — deterministically** (cycle-3 review
  flagged the previous "either succeeds OR raises" test as
  non-deterministic). Asserts BOTH halves of the contract:
  - **Top-level rebinding is rejected (frozen=True for scalar attribute
    rebinding):** `with pytest.raises(ValidationError): candidate.snippet
    = "x"`. Same for `candidate.matched_engines = ["other"]`,
    `candidate.engine_scores = {}`, `candidate.provider_metadata = None`
    — every container field rejects rebinding.
  - **Container content mutation succeeds (Pydantic frozen is shallow —
    documented behavior, not a bug):**
    `candidate.matched_engines.append("keyword")` succeeds and the list
    is `["semantic", "keyword"]` afterward. Same for
    `candidate.engine_scores["keyword"] = 0.5` and
    `candidate.provider_metadata["new"] = "z"` — both succeed and the
    dicts contain the new keys. **Why succeed-and-document instead of
    deep-freeze:** SearchCandidate is constructed once per search and
    consumed downstream by RRF/rerank/MCP serialization. None of those
    consumers needs to mutate it, but wrapping `matched_engines` in
    `tuple` and `engine_scores`/`provider_metadata` in
    `MappingProxyType` would force every existing call site that builds
    a candidate (fusion.build_candidates, federated provider
    constructors) to coerce types and would not catch genuine misuse
    (callers that *do* try to mutate would fail at runtime, not at
    type-check time). The contract is therefore documented in the model
    docstring: "container fields are shallow-frozen; do not mutate after
    construction" — and this test pins the actual Pydantic behavior so
    downstream Plan 02/03 work cannot accidentally rely on deep
    immutability.
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
- `backend/tests/core/test_search_candidate.py` contains all eleven tests
  named above (eight foundational + three cycle-2 review additions for
  descriptor_key required-ness, descriptor_key disambiguation, and
  frozen-shallow container semantics).
- `cd backend && uv run pytest tests/core/test_search_candidate.py -q` exits
  non-zero before task 2 (model symbols don't exist yet) and exits 0 after
  task 2.
- Tests reference `SearchCandidate`, `SearchResponse`, `SourceStatus`,
  `descriptor_key`.
- `rg -n 'descriptor_key' backend/tests/core/test_search_candidate.py`
  returns at least one match (cycle-2 HIGH-1 marker).
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
  - `descriptor_key: str` — **required, no default** (cycle-2 HIGH-1 fix).
    Identifies the source descriptor uniquely within and across namespaces
    (e.g. `"telegram"`, `"filesystem-mnt"`). Together with `namespace` this
    forms the source identity required by SEARCH-02 / D-04.
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

Update `backend/src/dotmd/mcp_server.py` (cycle-2 HIGH-2 fix — MCP exposes
the full `SearchCandidate` contract; no `SearchHit` narrowing model):

- **Remove** `class SearchHit(BaseModel)` from `mcp_server.py`. The MCP
  `search` tool returns `SearchCandidate` records directly (the full envelope
  shape, including `SearchResponse`, lands in Plan 34-02 task 4 — Plan 34-01
  ships the change at the per-result level so SearchHit removal is finished
  here).
- The MCP `search` tool's existing return type adapter switches from
  `list[SearchHit]` to `list[SearchCandidate]`. The schema exposed to MCP
  clients includes every public field of `SearchCandidate`: `ref`,
  `namespace`, `descriptor_key`, `source_kind`, `retrieval_kind`, `title`,
  `snippet`, `fused_score`, `can_read`, `can_materialize`, `chunk_id`
  (nullable), `heading_path` (nullable), `matched_engines`, `provenance`
  (nullable), `source_native_score` (nullable), `source_native_rank`
  (nullable), `engine_scores` (nullable), `provider_metadata` (nullable).
- The previous helper `_format_result(r) -> SearchHit` is removed; its
  responsibilities (`heading` derivation, score rounding, snippet whitespace
  cleanup) move into `SearchCandidate` field-level validators where
  appropriate (`fused_score` rounding stays in the rendering layer because
  the canonical model preserves full precision; the MCP tool wraps with a
  thin renderer that calls `model_dump()` and rounds `fused_score` in the
  serialized payload only).
- If a transport projection is required for MCP wire-format (e.g. to
  collapse `null` fields via the existing `_collapse_null`
  `json_schema_extra` pattern), the projection MUST be **lossless**: every
  public `SearchCandidate` field appears in the projection (possibly
  collapsed when `None`), and a serialization round-trip from
  `SearchCandidate` → projection → JSON → projection → `SearchCandidate`
  yields a value `== original`. A round-trip test in task 2 (or task 3)
  pins this; if the implementer cannot ship a lossless projection, the
  fallback is to expose `SearchCandidate.model_dump()` directly and
  rely on Pydantic's default JSON encoder.

Critical no-narrowing rules:
- `rg -n 'class SearchHit\b' backend/src/dotmd` returns no matches.
- `rg -n 'SearchHit\b' backend/src/dotmd` returns no matches outside
  comments referencing the removal.
- The MCP search tool MUST emit `can_read`, `can_materialize`,
  `source_native_score`, `source_native_rank`, `descriptor_key` whenever
  those fields are set on the underlying candidate.

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
- `backend/src/dotmd/core/models.py` `SearchCandidate` declares
  `descriptor_key: str` (no default) — `rg -n 'descriptor_key:\s*str'
  backend/src/dotmd/core/models.py` returns at least one match. (cycle-2
  HIGH-1 marker)
- `backend/src/dotmd/search/fusion.py` contains `def build_candidates`.
- `backend/src/dotmd/search/fusion.py` contains `def hydrate_local_engine_results`.
- `backend/src/dotmd/search/fusion.py` does NOT contain `def build_search_results`.
- `backend/src/dotmd/api/service.py` does NOT contain `SearchResult`.
- `backend/src/dotmd/mcp_server.py` does NOT contain `class SearchHit`
  (cycle-2 HIGH-2 fix). `rg -n 'class SearchHit\b' backend/src/dotmd`
  returns no matches.
- `backend/src/dotmd/mcp_server.py` MCP search tool returns
  `list[SearchCandidate]` (or `SearchResponse` per Plan 34-02 task 4) —
  the per-result type annotation is `SearchCandidate` not `SearchHit`.
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
- Add `test_build_candidates_collapse_tiebreak_highest_score_then_lowest_chunk_id`
  (**cycle-2 MEDIUM fold-in**). Set up two local chunks both resolving to
  ref `"filesystem:/tmp/a.md"`:
  - chunk_id=`"c-1"`, semantic_score=0.9, snippet=`"alpha"`.
  - chunk_id=`"c-2"`, semantic_score=0.8, snippet=`"bravo"`.
  Assert the resulting `SearchCandidate.chunk_id == "c-1"` and
  `snippet == "alpha"` (higher score wins). Then flip to equal scores and
  assert lowest chunk_id wins (`chunk_id == "c-1"`, `snippet == "alpha"`
  still). Then run with chunk_id=`"c-3"` and `"c-1"` at equal score; assert
  `chunk_id == "c-1"` (lowest lexicographic). Documents the deterministic
  tie-break (D-REF-COLLAPSE).

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
- SEARCH-01 has a single public `SearchCandidate` shape covering local hits,
  exposed at BOTH service and MCP layers (no `SearchHit` narrowing model —
  cycle-2 HIGH-2).
- SEARCH-02 has all required fields including `descriptor_key` for source
  identity (cycle-2 HIGH-1): `ref`, `namespace`, `descriptor_key`,
  `source_kind`, `retrieval_kind`, `title`, `snippet`, `fused_score`,
  `can_read`, `can_materialize`, optional `chunk_id`/`heading_path`/
  `provenance`/`matched_engines`, optional `source_native_score`/
  `source_native_rank`, optional `engine_scores`, optional
  `provider_metadata`.
- SEARCH-03 has rank-only RRF; key migrated from chunk_id to ref;
  per-engine attribution preserved.
- `SearchResult` is gone from production code; no compat alias.
- `SearchHit` is gone from MCP server; MCP returns `SearchCandidate` directly.
- Active-binding gate continues to filter inactive local refs (Phase 27
  invariant preserved).
- Federated fan-out is NOT yet integrated; that work is owned by Plan 02.
- Multiple chunks collapsing to one ref use deterministic tie-break
  (highest fused_score, then lowest chunk_id).
</success_criteria>
