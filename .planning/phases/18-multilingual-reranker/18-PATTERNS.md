# Phase 18: Multilingual Reranker - Pattern Map

**Created:** 2026-05-01  
**Scope:** Implement GTE TEI reranker from external benchmark research. No local quality eval harness.

## Files To Modify

| File | Role | Closest analog | Notes |
|---|---|---|---|
| `backend/src/dotmd/core/config.py` | Reranker backend/model/url config | Existing `Settings` fields around embedding URL/model and reranker model | Add only the minimum config surface: backend, URL/model if needed, floor behavior. |
| `backend/src/dotmd/search/reranker.py` | Reranker provider boundary | Existing `Reranker` class | Keep lazy CrossEncoder support if retained; add TEI HTTP provider or split into small classes if clearer. |
| `backend/src/dotmd/api/service.py` | Reranker construction and fallback behavior | Existing `_reranker` construction and `_search_core` rerank block | Construct selected provider once at service startup; never reload per request. |
| `backend/tests/test_reranker.py` | Unit coverage for provider/floor behavior | Existing mocked CrossEncoder tests | Mock HTTP and CrossEncoder; no real model downloads. |
| `backend/tests/test_hybrid_bm25.py` or `backend/tests/api/test_service_search.py` | Unit coverage for empty-rerank fallback | Existing service tests with mocked reranker | Assert fused candidates survive if reranker returns no candidates. |
| `.env.example` | Config documentation | Existing DOTMD_* examples | Add reranker backend/URL variables if code adds them. |
| `README.md` / `docs/architecture.md` | User-facing behavior | Existing search pipeline docs | Mention external TEI reranker and fused fallback. |

## Existing Code Anchors

### Service startup boundary

`backend/src/dotmd/api/service.py` currently constructs `Reranker` once in `DotMDService.__init__`. Preserve this startup-loading pattern. Do not create a reranker client per request.

### Search fallback

`backend/src/dotmd/api/service.py` currently returns `[]` if reranker output is empty. That must change: if TEI or floor behavior produces no reranked candidates, keep the pre-rerank fused list and log a diagnostic.

### TEI style

`backend/src/dotmd/search/semantic.py` already uses an HTTP embedding server. Reranker TEI code should follow the same practical style:

- configured base URL;
- bounded request timeout;
- explicit error logging;
- no per-request model discovery unless needed;
- non-fatal fallback where possible.

### Tests

Keep tests local and mocked:

- mock TEI `/rerank` responses with a fake transport or monkeypatched HTTP client;
- mock CrossEncoder if legacy path remains;
- assert request payload shape: `query`, `texts`, `raw_scores`, `return_text`, `truncate`;
- assert returned TEI scores map back to original chunk IDs.

## Risk Notes

- GTE local model card mentions `trust_remote_code`, but TEI serving is the preferred path for this phase.
- TEI service configuration may live outside this repo under `/opt/docker/dotmd`; execution should document exact deployment change but batch production restart.
- If TEI GTE cannot start or cannot serve `/rerank`, execution should stop and promote BGE fallback rather than silently switching to Qwen.

