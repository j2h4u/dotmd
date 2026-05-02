---
status: complete
phase: 21-reranker-quality-benchmark
source:
  - .planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md
  - .planning/phases/21-reranker-quality-benchmark/21-01-quality-benchmark-SUMMARY.md
started: 2026-05-02T09:59:46Z
updated: 2026-05-02T10:04:30Z
---

## Current Test

[testing complete]

## Tests

### 1. Canonical benchmark result is recorded
expected: Phase 21 has durable benchmark artifacts for the live-index quality run: `21-BENCHMARKS.md`, `results/2026-05-02-rerank-quality.jsonl`, and `results/2026-05-02-rerank-quality-summary.md`. The summary shows 30 Russian/mixed queries, shared_pool_size=20, top_n=10, Hit@1/Hit@3/Hit@5, MRR@10, nDCG@10, p50/p95 rerank time, and 9 pool_miss retrieval gaps.
result: pass

### 2. Production reranker registry is reduced to mmarco
expected: Live `dotmd` runtime exposes `reranker_name=mmarco-minilm`, `parsed_reranker_compare_names=['mmarco-minilm']`, and `available_rerankers() == ['mmarco-minilm']`; rejected `msmarco-minilm` and `mxbai-xsmall-v1` are no longer production candidates.
result: pass

### 3. Model cache cleanup leaves only active models
expected: The `dotmd` container Hugging Face cache keeps only active local runtime models: `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, `urchade/gliner_multi-v2.1` dependencies, and no cached `msmarco`, `mxbai`, or `pplx` model. The `embeddings` container keeps only the active `intfloat/multilingual-e5-large` TEI model.
result: pass
verified_by: docker cache listing

### 4. Staged benchmark methodology is documented for future reruns
expected: `docs/reranker-benchmark-methodology.md` explains the two-stage process: latency gate first, quality gate second, live-corpus/runtime contract, label format, metrics, pool_miss semantics, current Phase 20/21 results, and the future-agent procedure for adding temporary new candidates and cleaning rejected models.
result: pass
verified_by: documentation grep

### 5. Recommendation is clear and actionable
expected: Phase 21 documentation says to keep `mmarco-minilm` as the only production reranker, treat `msmarco-minilm` as historical negative control only, remove `mxbai-xsmall-v1` from production candidates, and revisit model search only with newer multilingual/Russian candidates using the documented staged methodology.
result: pass
verified_by: documentation grep and live runtime check

## Summary

total: 5
passed: 5
issues: 0
pending: 0
skipped: 0
blocked: 0

## Gaps

[none yet]
