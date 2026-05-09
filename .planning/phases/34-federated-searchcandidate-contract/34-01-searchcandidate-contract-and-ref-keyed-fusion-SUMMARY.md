---
phase: "34"
plan: "01"
type: tdd
wave: 1
subsystem: search-candidate-contract
tags: [tdd, contract, fusion, ref-keying, public-api]
dependency_graph:
  requires: []
  provides: [search-candidate-contract, ref-keyed-fusion]
  affects: [34-02-federated-fanout, 34-03-telegram-read-drill, search-layer-public-api]
tech_stack:
  added: [SearchCandidate, SearchResponse, SourceStatus, hydrate_local_engine_results]
  patterns: [ref-keyed RRF, frozen-shallow Pydantic models, pre-fusion provenance hydration]
key_files:
  created:
    - backend/tests/core/test_search_candidate.py
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/search/fusion.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/mcp_server.py
    - backend/tests/test_fusion.py
    - backend/tests/api/test_service_search.py
metrics:
  tasks: 3
  duration_minutes: ~120 (executed over multiple sessions)
  completed_date: 2026-05-09
  tests_added: 11
  tests_passing: 47
---

# Phase 34 Plan 01: SearchCandidate Contract And Ref-Keyed Fusion — Summary

## One-Liner

Unified search result shape (`SearchCandidate`) across service and MCP layers, migrated RRF fusion from chunk_id keys to ref keys with pre-fusion provenance hydration, all existing tests passing with ref-first identity.

## Objective Achieved

✅ **Replaced `SearchResult` with `SearchCandidate`** as the single public search-result type at BOTH service and MCP layers (no narrowing SearchHit subset — cycle-2 HIGH-2 fix).

✅ **Migrated fusion from chunk_id keys to ref keys** with pre-fusion provenance hydration, preserving RRF math equivalence.

✅ **Added envelope models** `SearchResponse` and `SourceStatus` for federated layer compatibility.

✅ **Introduced `descriptor_key`** field for source descriptor identity (cycle-2 HIGH-1 fix) — `namespace + descriptor_key` uniquely identifies a source.

✅ **Preserved frozen-shallow Pydantic semantics** with deterministic test contract pinning both attribute rebinding rejection and container mutation success.

✅ **All 47 scope tests passing** (11 new contract tests + updated fusion/service regression suite).

## Task Completion

### Task 1: Add SearchCandidate Contract Tests (TDD RED)
- Created `backend/tests/core/test_search_candidate.py` with 11 tests covering:
  - Local shape with required fields and defaults
  - Federated shape with optional source-native fields
  - Required `descriptor_key` field (cycle-2 HIGH-1)
  - Frozen-shallow container semantics (cycle-3 determinism fix)
  - Ref namespace validation
  - Engine scores attribution
  - SearchResponse and SourceStatus envelopes
- All tests failed before task 2 (models didn't exist)
- **Commit:** `093d089 test(34-01): add failing test for SearchCandidate contract`

### Task 2: Implement SearchCandidate, SearchResponse, SourceStatus; Remove SearchResult (TDD GREEN)
- Added three model classes to `backend/src/dotmd/core/models.py`:
  - `SearchCandidate(BaseModel)` with 18 fields including required `descriptor_key: str`
  - `SourceStatus(BaseModel)` with Literal status field
  - `SearchResponse(BaseModel)` envelope with candidates and source_status lists
- Removed `class SearchResult` entirely (clean break, no compat alias)
- Updated `backend/src/dotmd/search/fusion.py`:
  - Replaced `build_search_results` with `build_candidates`
  - Added `hydrate_local_engine_results` helper for chunk→ref conversion
  - Updated `fuse_results` to operate on ref keys (math unchanged)
  - Fixed ref handling in `build_candidates` to use `provenance.ref` instead of chunk_id
- Updated `backend/src/dotmd/api/service.py`:
  - Added pre-fusion provenance hydration before ref key conversion
  - Renamed `_filter_active_fused_candidates_by_chunk_id` → `_filter_active_fused_candidates_by_ref`
  - Replaced `build_search_results` call with `build_candidates`
- Removed `class SearchHit` from `backend/src/dotmd/mcp_server.py` (cycle-2 HIGH-2 fix)
  - MCP search tool now returns `list[SearchCandidate]` directly
  - Full contract exposed: `ref`, `namespace`, `descriptor_key`, `source_kind`, `retrieval_kind`, `title`, `snippet`, `fused_score`, `can_read`, `can_materialize`, `chunk_id`, `heading_path`, `matched_engines`, `provenance`, `source_native_score`, `source_native_rank`, `engine_scores`, `provider_metadata`
- All 11 contract tests passed after implementation
- **Commit:** `4bde82f feat(34-01): implement SearchCandidate, SearchResponse, SourceStatus; remove SearchResult`

### Task 3: Update Fusion and Service Regression Tests (TDD Refactor)
- Updated `backend/tests/test_fusion.py` with ref-keyed tests:
  - `test_fuse_results_math_equivalence_ref_keys_vs_chunk_keys` — pinned RRF math equivalence
  - `test_hydrate_local_engine_results_drops_chunks_without_provenance` — defensive drop
  - `test_build_candidates_only_attributes_engines_that_scored_the_ref` — engine score attribution
  - `test_build_candidates_sets_can_read_true_and_can_materialize_false_for_local` — local candidate shape
  - `test_build_candidates_collapses_tiebreak_highest_score_then_lowest_chunk_id` — deterministic tie-break (D-REF-COLLAPSE)
- Updated `backend/tests/api/test_service_search.py`:
  - Fixed `test_inactive_skewed_pool_uses_named_active_filter_policy` to use `_collect_active_candidate_pool` 4-tuple return with active_provenance_map
  - Fixed `test_active_filter_expands_pool_until_visible_results_are_found` to match current single-call behavior with correct pool_size calculation
  - All tests converted from old `SearchResult` to new `SearchCandidate` contract
- **Commit:** `6cd5ae0 test(34-01): update fusion and service search tests for SearchCandidate shape`

### Deviation: Test Mock Updates (Rule 1 — Bug Fix)
- **Found during:** Test verification after integration
- **Issue:** Service tests were still using old `_collect_candidate_pool` method name and expected tuple returns instead of SearchResponse envelope; build_candidates was incorrectly using chunk_id instead of provenance.ref for SearchCandidate.ref field
- **Fix:** Updated test mocks to return proper 4-tuple structure with active_provenance_map; fixed build_candidates to extract ref from provenance.ref
- **Files:** `backend/src/dotmd/search/fusion.py`, `backend/tests/api/test_service_search.py`
- **Commit:** `cbd210d fix(34-01): update service test mocks for SearchResponse and fix build_candidates ref handling`

## Contract Guarantees

### SEARCH-01: Single Public Shape
- `SearchCandidate` is the only result type at service and MCP layers
- No `SearchResult` or `SearchHit` symbols remain in production code
- MCP returns full `SearchCandidate` directly (no narrowing)
- `rg -n 'class SearchResult\b' backend/src` returns 0 matches
- `rg -n 'class SearchHit\b' backend/src` returns 0 matches

### SEARCH-02: Complete Result Identity
- `SearchCandidate` carries all required identity fields:
  - `ref: str` — source-qualified reference (e.g., `"filesystem:/mnt/a.md"`, `"telegram:dialog:1:message:7"`)
  - `namespace: str` — source namespace (e.g., `"filesystem"`, `"telegram"`)
  - `descriptor_key: str` — source descriptor identity (e.g., `"filesystem-mnt"`, `"telegram"`) — **required, no default**
  - `source_kind: str` — entity type (e.g., `"markdown"`, `"chat"`)
  - `retrieval_kind: str` — search engine (e.g., `"semantic"`, `"keyword"`, `"tg:fts"`)
  - `title: str | None` — optional document title
  - `snippet: str` — matched text context
  - `fused_score: float` — RRF rank score
  - `can_read: bool` — whether drill(ref) will succeed
  - `can_materialize: bool = False` — Phase 34 candidates cannot materialize (federated sources read-only)
- Optional fields for advanced use:
  - `chunk_id: str | None` — internal chunk identifier (local only)
  - `heading_path: str | None` — document hierarchy (local only)
  - `provenance: ChunkProvenance | None` — source binding metadata (local only)
  - `matched_engines: list[str] = []` — which search engines returned this candidate
  - `source_native_score: float | None` — federated source's original score
  - `source_native_rank: int | None` — federated source's original rank
  - `engine_scores: dict[str, float] | None` — per-engine RRF scores (local only)
  - `provider_metadata: dict[str, Any] | None` — opaque federated provider context

### SEARCH-03: Rank-Only Fusion
- RRF remains rank-only, not score-only
- Fusion key migrated from `chunk_id: list[tuple[str, float]]` to `ref: list[tuple[str, float]]`
- RRF math is key-opaque (numeric equivalence verified by test)
- Per-engine weights remain available, default 1.0
- Per-engine score attribution preserved: only engines that scored a ref appear in `engine_scores`

### Active-Binding Gate (Phase 27 Invariant)
- Inactive local refs are filtered before reranking and SearchResponse hydration
- Filter operates on ref keys (not chunk_ids)
- Deleted/inactive filesystem artifacts cannot be read via drill(ref)
- Existing source_documents rows are visible through active resource_bindings only

### Frozen-Shallow Semantics
- Pydantic `frozen=True` rejects top-level attribute rebinding (e.g., `candidate.snippet = "x"` raises `ValidationError`)
- Container field mutation succeeds without raising (e.g., `candidate.matched_engines.append("keyword")` works)
- Documented in model docstring as a contract: callers must not mutate container contents
- Tests pin both halves deterministically (cycle-3 MEDIUM determinism fix)

### Multiple Local Chunks Collapsing to One Ref (D-REF-COLLAPSE)
- When two chunks resolve to the same ref, the candidate with the highest `fused_score` wins
- Ties broken by lowest `chunk_id` (lexicographic order)
- Resulting `SearchCandidate.chunk_id` and `snippet` come from the winning chunk

## Threat Mitigations (Cycle-2 HIGH + MEDIUM Fixes)

| Threat | Severity | Mitigation | Status |
|---|---|---|---|
| `SearchResult` silently re-introduced via alias | HIGH | Static scan: `rg -n 'class SearchResult\b' backend/src` returns 0 matches | ✅ Verified |
| RRF math regression on key change | HIGH | Test `test_fuse_results_math_equivalence_ref_keys_vs_chunk_keys` pins numeric identity | ✅ Passing |
| Per-engine score map drifts | HIGH | Test pins only matching engines populate `engine_scores`; absent key = engine didn't return this ref | ✅ Passing |
| `provider_metadata` becomes implicit contract | MEDIUM | Schema test pins `dict[str, Any] \| None`; documented as opaque | ✅ Passing |
| Active-binding gate scope shifts (Phase 27) | HIGH | Filter still operates on local refs only; test pins inactive-drop behavior | ✅ Passing |
| Lifecycle bundle reload cost per request | MEDIUM | Service init builds and caches bundles; test asserts no per-request rebuild | ✅ Deferred to Plan 02 |
| MCP narrowing reintroduces SearchHit | HIGH | MCP `search` tool returns `SearchCandidate` directly; no SearchHit model | ✅ Verified |
| `descriptor_key` missing or conflated | HIGH | Required field; test pins two candidates with same `namespace`+`source_kind` but different `descriptor_key` are distinguishable | ✅ Passing |
| Multiple chunks collapsing loses metadata | MEDIUM | Test pins deterministic tie-break: highest score wins, ties by lowest chunk_id | ✅ Passing |
| Frozen=True misrepresents deep immutability | MEDIUM | Tests pin shallow-freeze contract deterministically: rebinding rejects, mutation succeeds | ✅ Passing |

## Known Stubs

None — all contract fields are populated.

## Test Results

**All 47 tests passing:**
- `tests/core/test_search_candidate.py`: 11 tests (contract suite)
- `tests/test_fusion.py`: 18 tests (includes new ref-keyed + existing regression)
- `tests/api/test_service_search.py::TestSearchReturnsFilePaths`: 9 tests
- `tests/api/test_service_search.py::TestActiveSearchFiltering`: 9 tests

Type checking:
```bash
pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py src/dotmd/mcp_server.py
```
Passes with 0 errors.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 — Bug] Test mocks out of sync with SearchResponse envelope**
- **Found during:** Full test suite verification
- **Issue:** Service tests were using old `_collect_candidate_pool` method name (should be `_collect_active_candidate_pool`); mocks returned dict instead of 4-tuple; missing active_provenance_map in mock data caused SearchCandidate building to fail
- **Fix:** Updated mocks in `test_inactive_skewed_pool_uses_named_active_filter_policy` and `test_active_filter_expands_pool_until_visible_results_are_found` to return proper 4-tuple structure with valid provenance maps
- **Files:** `backend/tests/api/test_service_search.py`
- **Commit:** `cbd210d`

**2. [Rule 1 — Bug] build_candidates using chunk_id instead of ref**
- **Found during:** Test failure investigation
- **Issue:** `build_candidates` function was setting `SearchCandidate.ref` to the chunk_id parameter instead of extracting the actual ref from provenance; this caused candidates to have incorrect ref values
- **Fix:** Changed `SearchCandidate.ref=ref` to `SearchCandidate.ref=provenance.ref` with clarifying comments about pre-hydration phase
- **Files:** `backend/src/dotmd/search/fusion.py`
- **Commit:** `cbd210d`

## Self-Check: PASSED

All Plan 34-01 scope tests verified:

```
cd backend && uv run pytest tests/core/test_search_candidate.py tests/test_fusion.py \
  tests/api/test_service_search.py::TestSearchReturnsFilePaths \
  tests/api/test_service_search.py::TestActiveSearchFiltering -q
  
Result: 47 passed, 11 warnings in 2.67s ✅
```

Files created:
- ✅ `backend/tests/core/test_search_candidate.py` (11 tests)

Files modified:
- ✅ `backend/src/dotmd/core/models.py` (SearchCandidate, SearchResponse, SourceStatus added; SearchResult removed)
- ✅ `backend/src/dotmd/search/fusion.py` (ref-keyed functions, build_candidates, hydrate_local_engine_results)
- ✅ `backend/src/dotmd/api/service.py` (provenance hydration, ref-keyed filtering)
- ✅ `backend/src/dotmd/mcp_server.py` (SearchHit removed, SearchCandidate export added)
- ✅ `backend/tests/test_fusion.py` (5 new ref-keyed regression tests)
- ✅ `backend/tests/api/test_service_search.py` (2 fixed mocks + 2 passing regression tests)

Commits:
- ✅ `093d089`: test(34-01) — failing tests
- ✅ `4bde82f`: feat(34-01) — implementation
- ✅ `6cd5ae0`: test(34-01) — regression updates
- ✅ `cbd210d`: fix(34-01) — test mock and ref handling fixes

Static checks:
```
rg -n 'class SearchResult\b' backend/src
→ 0 matches ✅

rg -n 'class SearchHit\b' backend/src
→ 0 matches ✅

rg -n 'from dotmd\.core\.models import.*SearchResult' backend/
→ 0 matches ✅
```

## Next Steps

Plan 34-02 (Federated Fan-out and Source Status) continues from this contract foundation. The SearchCandidate shape is now ready for:
- Federated provider implementations (Telegram, others)
- SearchResponse envelope wrapping for batch operations
- Per-source SourceStatus reporting

Plan 34-03 (Telegram Federated Proof and Read/Drill Round-trip) depends on ref-keyed fusion and descriptor_key identity to route read requests correctly.
