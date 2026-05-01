# Phase 21: Reranker Quality Benchmark Research

## Implementation Approach

The existing `DotMDService.compare_rerankers()` already does the most important
apples-to-apples operation: it expands the query, collects one fused candidate
pool, and reranks the same `chunk_ids` with each selected model.

Phase 21 should build a devtool around that behavior rather than introducing a
separate retrieval implementation.

Recommended new tool:

- `backend/devtools/reranker_quality_bench.py`

Recommended tests:

- `backend/tests/devtools/test_reranker_quality_bench.py`

Recommended artifacts:

- `.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl`
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`

## Runner Design

The runner should load a JSONL labels file and execute one row per
query/model. It should preserve the Phase 20 invariants:

- current `dotmd` container/runtime
- `mode=hybrid`
- query expansion enabled by default
- `shared_pool_size=20`
- `top_n=10` for quality scoring
- model list fixed to `msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1`

Unlike the latency runner, the quality runner should not sort models by
`rerank_ms`. It should sort by quality summary, then display latency beside the
quality metrics.

## Label Resolution

Labels need to be stable and reviewable. The best supported forms are:

- exact `chunk_id`
- `file_path` plus optional `contains` text

The runner can resolve `file_path + contains` by reading chunks from
`metadata_store.get_chunks_for_file_range(...)` and matching the substring. If
multiple chunks match, the runner should fail loudly and ask for a more specific
label. This keeps labels human-authored without requiring the user to know
chunk IDs upfront.

## Metrics

Use rank-based metrics only:

- `Hit@1`: top result is relevant or maybe
- `Hit@3`: any relevant or maybe result appears in top 3
- `Hit@5`: any relevant or maybe result appears in top 5
- `MRR@10`: reciprocal rank of first relevant or maybe result
- `nDCG@10`: graded relevance, `relevant=2`, `maybe=1`, missing label = 0

Per-query rows should include:

- query
- model
- ordered top chunk IDs
- ordered top file paths
- labels matched at each rank
- metric values
- `rerank_ms`
- error text, if any

## Failure Modes

| Failure | Mitigation |
|---|---|
| Labels drift because index changes | Use current live index for this phase; record commit and runtime in benchmark ledger. |
| Labels are too weak or ambiguous | Runner fails on unresolved or multiply resolved labels; summary reports label coverage. |
| Model score scales differ | Ignore raw scores for quality; use only rank order. |
| Retrieval pool misses every labeled item | Record `pool_miss=true`; this identifies retrieval/fusion gaps and should not be blamed on reranker quality. |
| English-only baseline wins due to bad labels | Include Russian-heavy query categories and failure examples in the summary. |

## Validation Architecture

Automated validation:

- Unit tests for JSONL label parsing.
- Unit tests for metric calculation, including ties and empty results.
- Unit tests that prove all three default models are in the runner default list.
- Unit tests that prove summary sorting uses quality metrics, not latency.

Runtime validation:

- Run the quality benchmark against the live `dotmd` container.
- Store raw JSONL and markdown summary under Phase 21 `results/`.
- Ledger records command, commit hash, model list, query count, pool size, top N,
  metric definitions, and whether any labels were unresolved.

Decision validation:

- `msmarco-minilm` must be explicitly reported as negative historical control.
- If neither `mmarco-minilm` nor `mxbai-xsmall-v1` beats `msmarco-minilm` on
  Russian quality metrics, the summary must recommend keeping the registry
  narrow but continuing model search rather than promoting a poor candidate.
