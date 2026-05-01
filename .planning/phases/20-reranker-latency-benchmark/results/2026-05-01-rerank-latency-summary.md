# Phase 20 Canonical Reranker Latency Summary

- commit: `ed5808b`
- query set: `QUERY_SET_V1`
- `shared_pool_size=20`
- `top_n=3`
- mode: `hybrid`
- expansion: enabled
- `cold_passes=1`
- `hot_passes=3`
- `hot_samples_per_model=30`
- `model_wall_timeout_s=900`
- `hot_query_timeout_s=120`

Rows are sorted by hot p95 `rerank_ms` from fastest to slowest. Bands use hot rows only; any provider error, timeout, or DNF is `unusable`.

| Model | Band | Hot samples | p50 rerank | p95 rerank | max rerank | cold load max | Errors | Timeouts |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| `msmarco-minilm` | fast | 30 | 4s | 4s | 4s | 10s | 0 | 0 |
| `mmarco-minilm` | fast | 30 | 8s | 8s | 9s | 9s | 0 | 0 |
| `mxbai-xsmall-v1` | acceptable | 30 | 12s | 12s | 12s | 8s | 0 | 0 |
| `mxbai-base-v1` | unusable | 20 | 27s | 28s | 28s | 8s | 1 | 1 |
| `gte-multilingual` | unusable | 1 | 3m18s | 3m18s | 3m18s | 12s | 0 | 1 |
| `bge-v2-m3` | unusable | 0 | n/a | n/a | n/a | 8s | 1 | 1 |
| `gte-modernbert-base` | unusable | 0 | n/a | n/a | n/a | 14s | 1 | 1 |
| `jina-v2-multilingual` | unusable | 0 | n/a | n/a | n/a | n/a | 1 | 1 |
| `qwen3-0.6b` | unusable | 0 | n/a | n/a | n/a | 16s | 1 | 1 |

This summary does not judge relevance quality and does not change the production default reranker.
