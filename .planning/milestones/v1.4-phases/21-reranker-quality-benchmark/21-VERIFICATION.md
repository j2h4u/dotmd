---
phase: 21-reranker-quality-benchmark
verified: 2026-05-06T19:56:26+05:00
status: passed
score: 92
---

# Phase 21 Verification: Reranker Quality Benchmark

## Goal Achievement

**Goal:** Compare the three latency-surviving rerankers on relevance quality against the live dotMD document index and decide which model is worth using as the production default.

**Result:** PASSED.

The phase produced a canonical live-index quality benchmark using 30 approved Russian and mixed-language queries, one shared retrieval/fusion candidate pool per query, rank-based metrics, and explicit pool-miss reporting. The benchmark recommended keeping `mmarco-minilm` as the production default.

## Observable Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| Benchmark used live dotMD index without forced reindexing | VERIFIED | `21-01-quality-benchmark-SUMMARY.md` records use of the running `dotmd` container and `/dotmd-index/index.db`; no `dotmd index --force` command is recorded. |
| Canonical comparison covered `msmarco-minilm`, `mmarco-minilm`, and `mxbai-xsmall-v1` | VERIFIED | `21-BENCHMARKS.md` and `results/2026-05-02-rerank-quality.jsonl` contain all three model names. |
| `msmarco-minilm` was a negative historical control | VERIFIED | `21-01-quality-benchmark-SUMMARY.md` and `21-BENCHMARKS.md` explicitly identify it as the negative historical control. |
| Each query used one shared retrieval/fusion pool across rerankers | VERIFIED | `DotMDService.compare_rerankers()` builds one candidate pool before iterating rerankers in `backend/src/dotmd/api/service.py:471`; benchmark rows persist `shared_pool_size` and `candidate_pool_chunk_ids` in `backend/devtools/reranker_quality_bench.py:248` and `backend/devtools/reranker_quality_bench.py:265`. |
| Quality metrics are rank-based | VERIFIED | `backend/devtools/reranker_quality_bench.py:271` through `backend/devtools/reranker_quality_bench.py:275` calculate Hit@1, Hit@3, Hit@5, MRR@10, and nDCG@10. |
| Raw cross-encoder scores are not cross-model quality metrics | VERIFIED | `backend/devtools/reranker_quality_bench.py:325` sorts summaries by nDCG@10, MRR@10, Hit@3, p95 rerank latency, and model name, not raw scores. |
| Hot `rerank_ms` is a guardrail, not the primary quality sort | VERIFIED | `21-BENCHMARKS.md` reports p50/p95 rerank while the recommendation is based on nDCG/MRR/Hit metrics with latency as a guardrail. |
| Human label review was required before canonical scoring | VERIFIED | `21-LABELS-REVIEW.md` records `Status: APPROVED` before the canonical benchmark output. |
| Pool-miss queries are separated from per-model averages | VERIFIED | `backend/devtools/reranker_quality_bench.py:252` detects pool misses from the shared candidate pool; `backend/devtools/reranker_quality_bench.py:297` excludes pool misses from model averages. |

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| Benchmark runner | VERIFIED | `backend/devtools/reranker_quality_bench.py` exists and contains the Phase 21 benchmark runner. Current production defaults were later narrowed to `mmarco-minilm`; the canonical three-model comparison is preserved in the result artifacts. |
| Human label set | VERIFIED | `21-LABELS.jsonl` contains 30 query rows with `relevant` labels. |
| Human label review | VERIFIED | `21-LABELS-REVIEW.md` contains `Status: APPROVED`, reviewer metadata, and query count. |
| Benchmark summary | VERIFIED | `21-BENCHMARKS.md` reports Hit@1/3/5, MRR@10, nDCG@10, pool misses, negative control, and the recommendation. |
| Raw benchmark rows | VERIFIED | `results/2026-05-02-rerank-quality.jsonl` contains 90 rows across the three compared models. |
| Plan summary traceability | VERIFIED | `21-01-quality-benchmark-SUMMARY.md` now records `requirements-completed` for all Phase 21 requirement IDs. |

## Key Link Verification

`backend/devtools/reranker_quality_bench.py:430` calls `DotMDService.compare_rerankers()` for each query. `backend/src/dotmd/api/service.py:471` collects one shared pool, `backend/src/dotmd/api/service.py:481` iterates the candidate rerankers over that pool, and `backend/src/dotmd/api/service.py:554` returns `shared_pool_size` plus `candidate_pool_chunk_ids`. The benchmark then writes those pool fields into every result row.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| RERANK-QUALITY-01 | SATISFIED | Live index and human-approved label set recorded in `21-01-quality-benchmark-SUMMARY.md`, `21-LABELS.jsonl`, and `21-LABELS-REVIEW.md`. |
| RERANK-QUALITY-02 | SATISFIED | Shared candidate-pool flow verified through `DotMDService.compare_rerankers()` and benchmark result rows. |
| RERANK-QUALITY-03 | SATISFIED | `21-BENCHMARKS.md` reports Hit@1/3/5, MRR@10, nDCG@10, pool misses, errors, and p50/p95 hot rerank latency. |

## Anti-Patterns Checked

| Anti-pattern | Result |
|--------------|--------|
| Verification only checks that files exist | ABSENT; implementation, result contents, and test behavior were checked. |
| Per-model independent retrieval pools | ABSENT; the service builds one candidate pool and reuses it across rerankers. |
| Cross-model ranking by raw reranker scores | ABSENT; benchmark summary sorts by normalized rank metrics. |
| Pool misses hidden inside model averages | ABSENT; pool misses are reported separately and excluded from averages. |

## Human Verification Required

None for phase closure. The original human-label review requirement is already satisfied by `21-LABELS-REVIEW.md`.

## Gaps Summary

No blocking gaps remain. One historical nuance is recorded: the benchmark runner's current `DEFAULT_RERANKERS` list is now production-narrowed to `mmarco-minilm` after the phase recommendation, while the canonical three-model comparison remains preserved in the Phase 21 result artifacts.

## Verification Metadata

- Verification type: goal-backward phase verification
- Evidence checked: plan, summary, labels, benchmark outputs, service code, benchmark code, security report, validation report, UAT report, focused tests
- Current checks run:
  - PASS: `cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py tests/api/test_service_search.py -q` (`31 passed`)
  - PASS: label/result validation (`labels=30 rows=90 models=['mmarco-minilm', 'msmarco-minilm', 'mxbai-xsmall-v1'] pool_misses=27`)
- Security status: `21-SECURITY.md` reports 0 open threats
- Validation status: `21-VALIDATION.md` is satisfied
- UAT status: `21-UAT.md` reports 5/5 passed
