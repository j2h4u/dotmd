---
phase: 18-multilingual-reranker
slug: multilingual-reranker
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06T20:35:58+05:00
validation_state: reconstructed-from-summaries
gaps_found: 0
gaps_resolved: 0
manual_only: 0
---

# Phase 18 - Validation Strategy

> Retroactive Nyquist validation for the completed multilingual reranker selection phase.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q` |
| Full phase command | `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q` |
| Lint command | `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_reranker.py tests/test_hybrid_bm25.py` |
| Estimated runtime | about 10 seconds |

## Discovery

Phase 18 had no pre-existing `18-VALIDATION.md`, so this file reconstructs the validation contract from:

- `18-01-PLAN.md` and `18-01-SUMMARY.md`
- `18-RESEARCH.md`
- `18-VERIFICATION.md`
- Current reranker, service, config, and hybrid-search regression tests

Phase 18 was a selection and safety-boundary phase. It did not implement a local quality benchmark or final production bake-off. Later Phases 20 and 21 added latency and quality benchmarking and superseded the final production reranker decision.

## Gap Analysis

No Nyquist validation gaps remain. Phase 18's automated scope is the reranker boundary and scoring behavior; candidate selection, freshness rules, and fallback policy are research/document evidence rather than executable model-quality tests.

| Requirement | Coverage |
|-------------|----------|
| RERANK-SELECT-01 | `18-RESEARCH.md` records public benchmark and model-card research, including publication dates, multilingual/Russian evidence, and Qwen3 0.6B as the first implementation target at that point in the milestone. |
| RERANK-SELECT-02 | The phase explicitly avoided a local benchmark/eval/model bake-off. Current repo inspection found no Phase 18 local benchmark harness added under `backend/`. |
| RERANK-SELECT-03 | `18-RESEARCH.md` records ContextualAI rerank-v2, Jina v3, Qwen3-VL, GTE, and BGE as alternates/fallback/comparison evidence with the freshness policy. |
| SCORE-01 | `tests/test_reranker.py` and `tests/test_hybrid_bm25.py` cover disabled raw-score filtering by default, configured relevance floors, provider failure returning no reranked candidates, keyword-only candidate survival, and empty reranker output falling back to fused ranking. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| 18-01-01 | 01 | 1 | RERANK-SELECT-01 | Public benchmark/model-card research chooses the first target by freshness, multilingual evidence, and operational fit rather than legacy English defaults. | research evidence | n/a | yes | green |
| 18-01-02 | 01 | 1 | RERANK-SELECT-02 | Phase 18 does not create a local dotMD quality benchmark, curated eval set, or bake-off harness. | repo inspection | `find backend -path 'backend/.venv' -prune -o -type f \( -path 'backend/eval/*' -o -iname '*benchmark*' -o -iname '*eval*' -o -iname '*bake*' \) -print` | yes | green |
| 18-01-03 | 01 | 1 | RERANK-SELECT-03 | Alternates and fallback policy are documented, including Qwen3-VL/ContextualAI/Jina as serious alternates and GTE/BGE as old fallback/comparison evidence. | research evidence | n/a | yes | green |
| 18-01-04 | 01 | 1 | SCORE-01 | Raw reranker score filtering is disabled by default; explicit relevance floors still filter when configured. | unit | `cd backend && uv run pytest tests/test_reranker.py -q` | yes | green |
| 18-01-05 | 01 | 1 | SCORE-01 | Empty or failed reranker output does not erase otherwise valid fused results. | integration-style unit | `cd backend && uv run pytest tests/test_hybrid_bm25.py -q` | yes | green |
| 18-01-06 | 01 | 1 | SCORE-01 | Reranker provider/CrossEncoder boundaries are mocked in tests; validation does not download or execute real models. | unit | `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q` | yes | green |

## Wave 0 Requirements

Existing pytest infrastructure covers all executable Phase 18 behavior. Research-only selection claims are validated through preserved phase research and verification artifacts, not through new code tests.

## Manual-Only Verifications

All current Phase 18 closure behavior has automated verification or preserved research evidence.

The optional provider smoke from the plan remains non-blocking because Phase 18 did not add a live HTTP reranker service. Later benchmark phases own real latency/quality execution.

## Commands Run

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q` | PASS: 36 passed, 20 warnings |
| `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_reranker.py tests/test_hybrid_bm25.py` | PASS |
| `find backend -path 'backend/.venv' -prune -o -type f \( -path 'backend/eval/*' -o -iname '*benchmark*' -o -iname '*eval*' -o -iname '*bake*' \) -print` | PASS: no Phase 18 local benchmark harness found |

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or preserved research evidence
- [x] Sampling continuity restored retroactively
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 10 seconds for the focused phase suite
- [x] `nyquist_compliant: true` set in frontmatter

Approval: approved 2026-05-06
