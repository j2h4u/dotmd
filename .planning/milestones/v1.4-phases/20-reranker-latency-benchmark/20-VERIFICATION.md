---
phase: 20-reranker-latency-benchmark
verified: 2026-05-06T19:56:26+05:00
status: passed
score: 94
---

# Phase 20 Verification: Reranker Latency Benchmark

## Goal Achievement

**Goal:** Establish a reproducible latency benchmark protocol for rerankers and select the models worth comparing for quality.

**Result:** PASSED.

Phase 20 produced a canonical latency protocol, raw JSONL benchmark rows, generated summary, benchmark ledger, and a shortlist of `msmarco-minilm`, `mmarco-minilm`, and `mxbai-xsmall-v1` for later Phase 21 quality testing. It made no relevance-quality judgment and did not change the production default.

## Observable Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| Benchmark protocol has a fixed query set | VERIFIED | `backend/devtools/reranker_latency_bench.py:24` defines `QUERY_SET_V1`; `20-BENCHMARKS.md` records 10 queries. |
| Runtime constants are explicit | VERIFIED | `backend/devtools/reranker_latency_bench.py:59` through `backend/devtools/reranker_latency_bench.py:61` define hot passes and timeouts; `20-BENCHMARKS.md` records `shared_pool_size=20`, `top_n=3`, `model_wall_timeout_s=900`, and `hot_query_timeout_s=120`. |
| Latency metric is hot `rerank_ms` | VERIFIED | `backend/devtools/reranker_latency_bench.py:276` computes p95 from hot values; benchmark summaries sort by hot p95. |
| Timeout/error models are classified unusable | VERIFIED | `backend/devtools/reranker_latency_bench.py:86` through `backend/devtools/reranker_latency_bench.py:94` assigns bands; `20-BENCHMARKS.md` records timeout/DNF decisions. |
| Raw output and generated summary exist | VERIFIED | `results/2026-05-01-rerank-latency.jsonl` and `results/2026-05-01-rerank-latency-summary.md` are present. |
| Shortlist flows into Phase 21 quality testing | VERIFIED | Phase 20 summary names the three latency survivors; Phase 21 benchmark uses those three models. |

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| Runner | VERIFIED | `backend/devtools/reranker_latency_bench.py` exists and current unit tests pass. |
| Ledger | VERIFIED | `20-BENCHMARKS.md` records protocol constants, canonical results, shortlist rationale, and rejected/deferred models. |
| Raw JSONL | VERIFIED | `results/2026-05-01-rerank-latency.jsonl` exists. |
| Generated summary | VERIFIED | `results/2026-05-01-rerank-latency-summary.md` exists and reports latency bands/metrics. |
| Plan summary | VERIFIED | `20-01-latency-benchmark-protocol-SUMMARY.md` records outcome and `requirements_addressed`. |

## Key Link Verification

The benchmark runner defines the candidate set and query set, runs each model with cold and hot passes, records `rerank_ms`, summarizes p50/p95/max hot latency, applies timeout/error handling, and writes both raw JSONL and markdown summaries. The Phase 20 shortlist then becomes the candidate pool for Phase 21 quality benchmarking.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| RERANK-LATENCY-02 | SATISFIED | Canonical hot latency measurements, p50/p95/max, timeouts, and bands are recorded in the benchmark outputs. |
| RERANK-BENCH-01 | SATISFIED | The reproducible benchmark protocol and raw/summary artifacts exist. |

## Anti-Patterns Checked

| Anti-pattern | Result |
|--------------|--------|
| Quality decision made from latency alone | ABSENT; summary explicitly defers quality to Phase 21. |
| Cold load time confused with hot rerank latency | ABSENT; cold load and hot rerank are reported separately. |
| Slow models silently omitted | ABSENT; DNF/timeouts are recorded as unusable. |
| Benchmark constants hidden in prose only | ABSENT; constants exist in runner code and benchmark ledger. |

## Human Verification Required

None for phase closure.

## Gaps Summary

No blocking gaps remain.

## Verification Metadata

- Verification type: retroactive goal-backward phase verification
- Evidence checked: Phase 20 summary, benchmark ledger, raw/generated results, current runner code, runner tests
- Current checks run:
  - PASS: `cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py -q` (`7 passed`)

