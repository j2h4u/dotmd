---
phase: "20"
plan: "01-latency-benchmark-protocol"
status: completed
completed_at: "2026-05-01"
requirements_addressed: [RERANK-LATENCY-02, RERANK-BENCH-01]
---

# Phase 20 Plan 01 Summary: Reranker Latency Benchmark Protocol

## Outcome

Phase 20 produced a canonical, repeatable reranker latency benchmark and a
latency-only shortlist for later quality testing.

Shortlist for quality testing:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`

Phase 20 made no relevance-quality judgment and did not change
`DOTMD_RERANKER_NAME`.

## Canonical Constants

- query set: `QUERY_SET_V1`, 10 queries
- runtime: current `dotmd` container, CPU-only
- mode: `hybrid`
- expansion: enabled
- `shared_pool_size=20`
- `top_n=3`
- `cold_passes=1`
- `hot_passes=3`
- `hot_samples_per_model=30` when the model completes all hot passes
- `model_wall_timeout_s=900`
- `hot_query_timeout_s=120`
- production gate metric: hot rerank_ms, summarized with p50, p95, and max
- cold load_ms is recorded separately for warmup/deploy planning

The p95 value here is an operational percentile from up to 30 hot samples per
measured model, not a statistically strong long-term SLO.

## Benchmark Results

| Model | Band | Hot samples | p50 hot rerank_ms | p95 hot rerank_ms | max hot rerank_ms | max cold load_ms | Errors | Timeouts |
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

Rejected or deferred models:

- `mxbai-base-v1`: `unusable`, because the model hit `model_wall_timeout_s`
  before completing the canonical 30 hot samples.
- `gte-multilingual`: `unusable`, because the first hot row exceeded
  `hot_query_timeout_s` with p95 hot rerank_ms at 3m18s.
- `bge-v2-m3`: `unusable`, because the model hit `model_wall_timeout_s`.
- `gte-modernbert-base`: `unusable`, because the model hit
  `model_wall_timeout_s`.
- `jina-v2-multilingual`: `unusable`, because the model hit
  `model_wall_timeout_s` before producing a measured row.
- `qwen3-0.6b`: `unusable`, because the model hit `model_wall_timeout_s`; the
  one completed cold row spent about 14 minutes in reranking.

## Artifacts

- Raw JSONL:
  `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl`
- Generated summary:
  `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`
- Ledger:
  `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- Runner:
  `backend/devtools/reranker_latency_bench.py`

## Commands Run

| Command | Status |
|---|---|
| `rg --no-heading "shared_pool_size=20\|top_n=3\|hot_samples_per_model=30\|model_wall_timeout_s=900\|Exploratory Runs" .planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md` | PASS |
| `cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py -q` | PASS, 7 passed |
| `docker exec dotmd python /app/devtools/reranker_latency_bench.py ... --pool-size 20 --top-n 3 --cold-passes 1 --hot-passes 3 --model-wall-timeout-s 900 --hot-query-timeout-s 120 --commit ed5808b` | PASS, produced 180 JSONL rows |
| `test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl` | PASS |
| `test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md` | PASS |
| `cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py tests/test_reranker.py tests/api/test_service_search.py tests/test_cli.py -q` | PASS, 54 passed, 24 warnings |
| `cd backend && uv run ruff check src devtools tests` | PASS |

## Notes

- `backend/devtools` is not bind-mounted into the running container, so the
  committed runner was copied into `/app/devtools` before execution. The
  benchmark still used the container's mounted `/app/src` runtime.
- FTS5 logged parse errors for hyphenated benchmark query terms such as
  `content-addressed` and `sqlite-vec`. They did not become benchmark row errors
  because the pipeline continued with other retrieval engines.
- The benchmark did not change production serving behavior or the production
  default reranker.
