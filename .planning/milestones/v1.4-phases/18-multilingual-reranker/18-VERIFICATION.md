---
phase: 18-multilingual-reranker
verified: 2026-05-01T09:07:24Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
---

# Phase 18: Multilingual Reranker Verification Report

**Phase Goal:** Replace or rework the English-oriented reranker so Russian and multilingual queries are not degraded by noisy cross-encoder scores.  
**Verified:** 2026-05-01T09:07:24Z  
**Status:** passed  
**Re-verification:** No — initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | No local quality benchmark harness, eval-set preparation, or model bake-off is implemented | VERIFIED | No repo-local benchmark/eval/bake-off files found outside `.venv`; `18-RESEARCH.md` explicitly marks local eval harness and model bake-off out of scope. |
| 2 | Publication month/year has been considered before selecting the first implementation candidate | VERIFIED | `18-RESEARCH.md` ranks candidates with published dates and age at May 2026, and docs mention publication-age rationale. |
| 3 | Alibaba-NLP/gte-multilingual-reranker-base is fallback-only because it is too old for default reranker selection as of May 2026 | VERIFIED | `18-RESEARCH.md` ranks GTE as fallback-only at ~22 months old; README and architecture docs repeat older GTE/BGE fallback-only rationale. |
| 4 | Qwen/Qwen3-Reranker-0.6B is the selected first implementation target | VERIFIED | `Settings.reranker_model` defaults to `Qwen/Qwen3-Reranker-0.6B`; README and architecture docs identify it as the selected provider. |
| 5 | ContextualAI rerank-v2 and Jina v3 remain real alternates if Qwen integration or latency fails | VERIFIED | Research ranks both as top alternates; README and architecture docs keep them as alternates if Qwen integration or latency fails. |
| 6 | Qwen/Qwen3-VL-Reranker-2B is fresher but receives no multimodality bonus and is mildly penalized for unnecessary VL stack | VERIFIED | Research scoring rules give multimodality bonus 0 and mild VL-stack penalty; Qwen3-VL is ranked fresh but overkill for text-only dotMD. |
| 7 | If reranker filtering or service failure yields no candidates, search falls back to fused ranking instead of returning an empty list | VERIFIED | `Reranker.rerank()` returns `[]` on provider failure; `DotMDService._execute_search()` logs fallback and leaves `fused` intact; regression test asserts non-empty results when reranker returns `[]`. |
| 8 | Tests mock provider/CrossEncoder boundaries and do not download real model weights | VERIFIED | `test_reranker.py` patches `sentence_transformers.CrossEncoder`; focused pytest run passed without model download or live service. |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/core/config.py` | Qwen3 reranker settings and optional floor | VERIFIED | Lines 52-55 define `reranker_backend`, `reranker_url`, Qwen3 default model, and `reranker_relevance_floor: float \| None = None`; lines 138-144 parse empty floor env as `None`. |
| `backend/src/dotmd/search/reranker.py` | Local CrossEncoder provider boundary, score mapping, optional filtering, non-fatal failure | VERIFIED | Lines 65-68 lazy-load `CrossEncoder(self._model_name)`; lines 113-131 preserve chunk-id/text order and score pairs; lines 132-138 return `[]` on provider failure; lines 153-157 make raw-score filtering opt-in. |
| `backend/src/dotmd/api/service.py` | Startup-configured reranker and fused fallback | VERIFIED | Lines 79-90 read settings and construct one `Reranker`; lines 337-347 handle empty reranker output without replacing `fused`; lines 392-420 build and return fused results. |
| `backend/tests/test_reranker.py` | Mocked provider tests for ordering, mapping, floor behavior | VERIFIED | Tests patch `CrossEncoder` and cover candidate order, score mapping, no-floor negative scores, configured floor, and Qwen3 defaults. |
| `backend/tests/test_hybrid_bm25.py` | Regression for empty rerank preserving fused results | VERIFIED | Lines 176-198 mock `rerank.return_value = []`, assert results are non-empty, and assert `reranked=False` is logged. |
| `.env.example` | Reranker env examples | VERIFIED | Lines 41-43 define `DOTMD_RERANKER_BACKEND`, `DOTMD_RERANKER_MODEL`, and empty `DOTMD_RERANKER_RELEVANCE_FLOOR`. |
| `README.md` | Selected reranker decision and fallback behavior | VERIFIED | Lines 9-15 document Qwen3 selection and alternates; lines 184-186 document config; lines 208-210 document fused fallback and `--no-rerank`. |
| `docs/architecture.md` | Architecture-level selected provider and fallback | VERIFIED | Lines 122-133 document Qwen3 CrossEncoder boundary, publication-age rationale, alternates, and non-fatal fused fallback. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `Settings` | `DotMDService` | `self._settings.reranker_*` | WIRED | Service reads backend, URL, model, length penalty, min length, and relevance floor during initialization. |
| `DotMDService` | `Reranker` | Constructor call in `__init__` | WIRED | One configured `Reranker` is constructed at startup; no per-request model reload path added. |
| `Reranker` | `sentence_transformers.CrossEncoder` | Lazy `_load_model()` | WIRED | Configured model name flows into `CrossEncoder(self._model_name)`. |
| Reranker output | Fused ranking | `_execute_search()` rerank block | WIRED | Non-empty reranker scores are blended; empty reranker output leaves fused ranking intact. |
| Docs/env | Runtime config | `DOTMD_RERANKER_*` settings | WIRED | `.env.example`, README config table, and `Settings` names match. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `backend/src/dotmd/api/service.py` | `self._settings.reranker_model` | `Settings` default/env/TOML | Yes | FLOWING |
| `backend/src/dotmd/search/reranker.py` | `chunk_ids` and chunk text | `metadata_store.get_chunks(chunk_ids)` | Yes, from active metadata store | FLOWING |
| `backend/src/dotmd/api/service.py` | `fused` ranking | `fuse_results(engine_results)` from semantic/FTS5/graph-direct hits | Yes | FLOWING |
| `backend/src/dotmd/api/service.py` | `results` | `build_search_results(fused[:top_k], metadata_store=...)` | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused Python lint gate | `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_reranker.py tests/test_hybrid_bm25.py` | `All checks passed!` | PASS |
| Reranker and hybrid fallback tests | `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q` | `14 passed, 6 warnings in 6.54s` | PASS |
| Local benchmark harness absence | `find backend -path 'backend/.venv' -prune -o -type f \( -path 'backend/eval/*' -o -iname '*benchmark*' -o -iname '*eval*' -o -iname '*bake*' \) -print` | No project files returned | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| RERANK-SELECT-01 | `18-01-PLAN.md` | Phase-local reranker selection from public multilingual/Russian benchmark evidence | SATISFIED | Research includes dated candidate matrix and Qwen3 default selection; docs carry the rationale. Not present in global `REQUIREMENTS.md`, so treated as phase-local roadmap requirement. |
| RERANK-SELECT-02 | `18-01-PLAN.md` | Phase-local no-local-benchmark boundary | SATISFIED | No benchmark harness/eval-set/model bake-off code exists in project files; research and plan explicitly keep this out of scope. Not present in global `REQUIREMENTS.md`. |
| RERANK-SELECT-03 | `18-01-PLAN.md` | Phase-local alternates/fallback selection policy | SATISFIED | ContextualAI and Jina remain alternates; GTE/BGE are fallback-only; Qwen3-VL is documented as fresh but overkill. Not present in global `REQUIREMENTS.md`. |
| SCORE-01 | `18-01-PLAN.md`, `.planning/REQUIREMENTS.md` | Global wording: cross-encoder relevance threshold calibrated on real corpus queries | SATISFIED FOR PHASE 18 | The old global requirement is marked Phase 12 complete. Phase 18 intentionally does not recalibrate a threshold; it removes the default raw-score floor (`None`) and makes empty/failed reranker output non-fatal, directly satisfying the Phase 18 score-floor risk. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| None | - | - | - | No blocker or warning anti-patterns found in Phase 18 files. Empty list returns in reranker/service are legitimate fallback/control results and covered by tests. |

### Human Verification Required

None. The phase goal is code/config/docs/test-verifiable, and the optional provider smoke was only required if an HTTP rerank service was introduced. This phase kept the local CrossEncoder boundary.

### Gaps Summary

No gaps found. Phase 18 replaces the English-oriented default model with the configured Qwen3 multilingual CrossEncoder path, makes raw-score filtering opt-in, preserves fused results when reranking fails or filters everything, documents the selection rationale and fallback policy, and verifies the behavior through mocked provider tests.

---

_Verified: 2026-05-01T09:07:24Z_  
_Verifier: the agent (gsd-verifier)_
