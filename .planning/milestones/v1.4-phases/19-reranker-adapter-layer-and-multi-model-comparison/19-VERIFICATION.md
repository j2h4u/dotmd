---
phase: 19-reranker-adapter-layer-and-multi-model-comparison
verified: 2026-05-01T12:55:10Z
status: passed
score: 13/13 must-haves verified
overrides_applied: 0
---

# Phase 19: Reranker Adapter Layer and Multi-Model Comparison Verification Report

**Phase Goal:** Refactor reranking into a provider/adapter layer so dotMD can switch rerankers by name and run developer-only comparisons across multiple candidate rerankers using one shared retrieval candidate pool.
**Verified:** 2026-05-01T12:55:10Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | Rerankers are selected by stable short name and unknown names fail clearly with available names | VERIFIED | `Settings.reranker_name = "qwen3-0.6b"` in `backend/src/dotmd/core/config.py:55`; `BUILTIN_RERANKERS` and `available_rerankers()` in `backend/src/dotmd/search/reranker.py:54`; `create_reranker()` raises `Unknown reranker ... available:` at `reranker.py:259`. Spot-check produced the expected default, available names, adapter metadata, and error text. |
| 2 | DotMDService obtains rerankers through a protocol/factory boundary, not direct concrete construction | VERIFIED | `RerankerProtocol` exists in `backend/src/dotmd/search/reranker.py:21`; `RerankerFactory` caches protocol instances at `reranker.py:287`; `DotMDService.__init__` constructs only `RerankerFactory` at `backend/src/dotmd/api/service.py:116`; no `Reranker(` construction exists in service code. |
| 3 | Production default remains one configured reranker, `qwen3-0.6b`, while alias compatibility remains | VERIFIED | Default config is single-name `qwen3-0.6b` at `config.py:55`; factory default resolves `name or settings.reranker_name` at `reranker.py:296`; compatibility alias `Reranker = CrossEncoderReranker` remains at `reranker.py:302`. |
| 4 | CrossEncoder adapter exposes `warmup()` through the protocol and delegates to lazy model loading | VERIFIED | Protocol includes `warmup()` at `reranker.py:27`; concrete warmup calls `_load_model()` at `reranker.py:148`; test asserts warmup loads CrossEncoder without prediction in `backend/tests/test_reranker.py:345`. |
| 5 | Service warmup handles reranker provider failure without aborting other warmup work | VERIFIED | `DotMDService.warmup()` catches reranker warmup exceptions at `backend/src/dotmd/api/service.py:133` and continues to keyword/graph warmup; regression test covers this at `backend/tests/api/test_service_search.py:318`. |
| 6 | Normal search runs at most one reranker per request and supports runtime selection by name | VERIFIED | `search(..., reranker_name=None)` is exposed at `service.py:225`; `_execute_search()` calls exactly one `self._reranker_factory.get(reranker_name)` inside the rerank branch at `service.py:335`; tests cover explicit/default factory calls and `rerank=False` skipping factory lookup in `backend/tests/test_hybrid_bm25.py:271`, `:313`, and `:348`. |
| 7 | Retrieval, graph-direct, RRF fusion, and graph enrichment execute once into a reusable post-enrichment candidate pool | VERIFIED | `RerankCandidatePool` at `service.py:35`; `_collect_candidate_pool()` at `service.py:505`; graph enrichment appends to `fused` and records `engine_results["graph"]` at `service.py:557`; tests assert graph-appended candidates and one engine call each at `backend/tests/test_hybrid_bm25.py:120` and `:134`. |
| 8 | No per-request index reload is introduced in the search/candidate-pool path | VERIFIED | The only `load_index()` match in `backend/src/dotmd/api/service.py` is warmup at line 140; `_collect_candidate_pool()` uses existing engines and contains no `load_index(` call. |
| 9 | Empty or failed reranker output falls back to fused ranking and search logging records reranked only when scores applied | VERIFIED | Empty reranker output logs fallback and keeps fused candidates at `service.py:342`; `reranked_applied` is set only when reranked output exists at `service.py:349`; tests cover fallback and logging at `backend/tests/test_hybrid_bm25.py:224` and `:430`. |
| 10 | Developer comparison runs retrieval/fusion once and sends the same candidate pool to multiple rerankers | VERIFIED | `compare_rerankers()` calls `_collect_candidate_pool()` once at `service.py:439`, builds one `chunk_ids` list at `service.py:445`, and iterates rerankers over that list at `service.py:449`; tests assert `_collect_candidate_pool` once and identical IDs at `backend/tests/api/test_service_search.py:83`. |
| 11 | Comparison reports latency, returned counts, ordered IDs, scores, errors, and overlap using the first successful reranker | VERIFIED | Comparison run payload is built with `elapsed_ms`, `returned_count`, `top_chunk_ids`, `scores`, and `error` at `service.py:461`; failures become per-reranker error rows at `service.py:472`; first-success overlap reference is computed at `service.py:486`; tests cover latency/cardinality/errors/overlap/all-failures at `backend/tests/api/test_service_search.py:123`, `:237`, and `:276`. |
| 12 | CLI and FastAPI expose runtime reranker selection and developer comparison; MCP remains unchanged | VERIFIED | FastAPI `/search` accepts `reranker` and maps `ValueError` to HTTP 400 at `backend/src/dotmd/api/server.py:134`; `/rerank/compare` uses typed response validation and HTTP 400 mapping at `server.py:158`; CLI `search --reranker` and `rerank compare` map `ValueError` to `ClickException` at `backend/src/dotmd/cli.py:102` and `:162`. `backend/src/dotmd/mcp_server.py` contains no comparison route/tool changes. |
| 13 | Latency docs/config/summary exist and focused Phase 19 checks pass | VERIFIED | README documents `dotmd rerank compare`, `elapsed_ms`, and no production restart at `README.md:114`; architecture docs describe `RerankerProtocol`, shared pool, and no per-request index reload at `docs/architecture.md:122`; `.env.example` contains reranker defaults at `.env.example:41`; summary records Qwen CPU latency and skipped live smoke at `19-04-latency-docs-verification-SUMMARY.md:96`. Current checks: `53 passed, 33 warnings`; ruff clean. |

**Score:** 13/13 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/src/dotmd/search/reranker.py` | Protocol, registry specs, factory/cache, CrossEncoder adapter | VERIFIED | SDK artifact check passed; manual evidence at lines 21, 54, 88, 259, 287. |
| `backend/src/dotmd/core/config.py` | Name-based default and comparison settings | VERIFIED | SDK artifact check passed; defaults and parser at lines 55 and 242. |
| `backend/src/dotmd/api/service.py` | Candidate pool, factory-backed search, comparison method | VERIFIED | SDK artifact check passed; core evidence at lines 35, 116, 225, 420, 505. |
| `backend/src/dotmd/api/server.py` | HTTP selection and comparison route | VERIFIED | SDK artifact check passed; `/search` and `/rerank/compare` evidence at lines 134 and 158. |
| `backend/src/dotmd/cli.py` | CLI selection and comparison command | VERIFIED | SDK artifact check passed; `--reranker` and `rerank compare` evidence at lines 102 and 162. |
| `backend/tests/test_reranker.py` | Registry/factory/warmup coverage | VERIFIED | Tests cover settings, registry, factory, warmup, and alias behavior. |
| `backend/tests/test_hybrid_bm25.py` | Single-reranker and candidate-pool regressions | VERIFIED | Tests cover graph-enriched pool, factory calls, fallback, and `rerank=False`. |
| `backend/tests/api/test_service_search.py` | Comparison/API/warmup regressions | VERIFIED | Tests cover shared pool, errors, overlap, typed API, and HTTP 400 mapping. |
| `backend/tests/test_cli.py` | CLI selection/comparison regressions | VERIFIED | Tests cover `--reranker`, diagnostics output, and Click errors. |
| `README.md`, `docs/architecture.md`, `.env.example` | Runtime selection, comparison workflow, adapter docs, env defaults | VERIFIED | Documentation spot-check found required strings. |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `Settings.reranker_name` | `create_reranker` / factory lookup | Stable registry name | WIRED | `RerankerFactory.get()` resolves `name or settings.reranker_name`; `create_reranker()` validates registry name and returns adapter. |
| Runtime `reranker_name` | `RerankerFactory.get` | `DotMDService.search` | WIRED | `search()` passes `reranker_name` into `_execute_search`; `_execute_search()` calls `get(reranker_name)`. |
| Shared candidate pool | Each comparison reranker | `compare_rerankers` | WIRED | One `_collect_candidate_pool()` call, then shared `chunk_ids` list passed to each reranker. |
| Comparison `elapsed_ms` | Qwen CPU latency concern | Docs and summary | WIRED | Service records `elapsed_ms`; README and summary explicitly call out Qwen CPU latency visibility. |

Note: `gsd-sdk query verify.key-links` returned `Source file not found` for semantic `from:` values in PLAN frontmatter. Manual code tracing above verifies the links.

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|----------|---------------|--------|--------------------|--------|
| `DotMDService.search` | `fused` / final `SearchResult` list | `_collect_candidate_pool()` from semantic, FTS5, graph-direct, graph enrichment; optional one factory reranker | Yes | VERIFIED |
| `DotMDService.compare_rerankers` | `RerankerComparison.rerankers` | Shared `pool["fused"]` chunk IDs plus each `RerankerFactory.get(name).rerank(...)` result | Yes | VERIFIED |
| `GET /rerank/compare` | `RerankerComparisonResponse` | `DotMDService.compare_rerankers()` with Pydantic `model_validate` | Yes | VERIFIED |
| `dotmd rerank compare` | CLI diagnostic rows | `DotMDService.compare_rerankers()` output | Yes | VERIFIED |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| Focused Phase 19 test set | `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py -q` | `53 passed, 33 warnings in 7.94s` | PASS |
| Ruff over touched source/tests | `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py` | `All checks passed!` | PASS |
| Factory/default smoke | Inline Python importing `Settings`, `available_rerankers`, `create_reranker`, `RerankerFactory` | Printed default `qwen3-0.6b`, comparison names, available names, Qwen adapter metadata, and unknown-name error | PASS |
| Docs/config spot-check | `rg --no-heading "dotmd rerank compare|RerankerProtocol|DOTMD_RERANKER_NAME|elapsed_ms|shared candidate pool" README.md docs/architecture.md .env.example` | Required docs/config strings found | PASS |

### Requirements Coverage

`.planning/REQUIREMENTS.md` does not define the Phase 19 `RERANK-*` IDs; it still contains only older v1.4 requirements. The IDs are present in `.planning/ROADMAP.md` and PLAN frontmatter, and their implementation evidence is verified below. This is a traceability warning, not an implementation blocker.

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|-------------|-------------|--------|----------|
| `RERANK-ADAPTER-01` | Plans 01, 02 | Reranker provider/adapter boundary | SATISFIED; missing from `REQUIREMENTS.md` | `RerankerProtocol`, registry, factory, service wiring verified. |
| `RERANK-SELECT-04` | Plans 01, 02, 03 | Runtime selection by stable name | SATISFIED; missing from `REQUIREMENTS.md` | Settings default, factory lookup, service/API/CLI runtime selection verified. |
| `RERANK-COMPARE-01` | Plans 02, 03, 04 | Developer comparison over one shared pool | SATISFIED; missing from `REQUIREMENTS.md` | `compare_rerankers()`, one-pool tests, API/CLI surfaces verified. |
| `RERANK-LATENCY-01` | Plans 03, 04 | Latency diagnostics for candidate rerankers/Qwen concern | SATISFIED; missing from `REQUIREMENTS.md` | `elapsed_ms` per reranker, docs, summary, and tests verified. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| `.planning/REQUIREMENTS.md` | n/a | Phase 19 requirement IDs absent | WARNING | Traceability file is stale; implementation evidence is verified through ROADMAP/PLAN/code/tests. |

Stub-pattern grep found empty lists/dicts in tests and normal initial/fallback state in implementation; no user-visible placeholder or hollow implementation was found.

### Human Verification Required

None. The optional live CPU smoke was intentionally skipped in the phase summary unless explicitly requested; the phase goal requires comparison capability and latency visibility, both verified through code paths, tests, and CLI/API output shape.

### Gaps Summary

No blocking gaps found. The phase goal is achieved in code: reranking has a protocol/registry/factory boundary, runtime reranker selection is wired through service/API/CLI, comparison uses one shared candidate pool, latency/error/overlap diagnostics are exposed, and production search remains single-reranker by default.

---

_Verified: 2026-05-01T12:55:10Z_
_Verifier: the agent (gsd-verifier)_
