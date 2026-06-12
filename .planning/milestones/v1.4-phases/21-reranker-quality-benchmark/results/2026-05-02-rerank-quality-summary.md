# Phase 21 Canonical Reranker Quality Summary

- commit: `e7beafc`
- query_count: 30
- `shared_pool_size=20`
- `top_n=10`
- mode: `hybrid`
- expansion: enabled
- `chunk_strategy=contextual_512_50`
- negative historical control: `msmarco-minilm`

Rows are sorted by `nDCG@10` descending, then `MRR@10`, `Hit@3`, and lower p95 hot `rerank_ms`.
Pool-miss queries are retrieval gaps and are excluded from per-model quality averages.

| Model | Valid queries | Pool misses | Errors | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 rerank | p95 rerank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mmarco-minilm` | 21 | 9 | 0 | 0.524 | 0.714 | 0.857 | 0.659 | 0.606 | 8s | 8s |
| `mxbai-xsmall-v1` | 21 | 9 | 0 | 0.524 | 0.810 | 0.857 | 0.676 | 0.593 | 12s | 12s |
| `msmarco-minilm` | 21 | 9 | 0 | 0.476 | 0.714 | 0.762 | 0.597 | 0.493 | 4s | 4s |

## Retrieval Gaps

pool_miss query ids: rq-007, rq-011, rq-013, rq-014, rq-015, rq-016, rq-017, rq-018, rq-020
