# Phase 20 Reranker Latency Benchmark Ledger

This ledger keeps every reranker latency run. Rows marked **exploratory** are
useful operational evidence, but they are not used for canonical model ranking.

## Canonical Protocol v1

- Runtime: current `dotmd` container.
- Query set: `QUERY_SET_V1`, 10 queries.
- Mode: `hybrid`.
- Expansion: enabled.
- `shared_pool_size=20`.
- `top_n=3`; this is output size, not the candidate scoring workload.
- `cold_passes=1` full pass over all queries.
- `hot_passes=3` full passes over all queries.
- `hot_samples_per_model=30`.
- `model_wall_timeout_s=900`.
- `hot_query_timeout_s=120`.
- Sort/rank metric: hot `rerank_ms`, summarized as p50/p95/max.
- Record separately: cold `load_ms`, total `elapsed_ms`, errors, timeouts,
  and DNF rows.
- Latency bands:
  - `fast: p95 rerank_ms <= 10000`
  - `acceptable: p95 rerank_ms <= 30000`
  - `slow: p95 rerank_ms <= 120000`
  - `unusable: p95 rerank_ms > 120000, timeout, DNF, or provider error`

Canonical model set:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`
- `mxbai-base-v1`
- `jina-v2-multilingual`
- `gte-multilingual`
- `bge-v2-m3`
- `qwen3-0.6b`
- `gte-modernbert-base`

### Canonical Pre-Run Checklist

Each canonical run must record:

- commit hash
- container name or runtime identifier
- benchmark runner command
- query set version
- model list
- `shared_pool_size`
- `top_n`
- `mode`
- expansion setting
- timeout settings
- raw output path

## Exploratory Runs Before Phase 20

These runs happened while shaping the benchmark surface. They are not
apples-to-apples canonical ranking rows.

### 2026-05-01 Full Initial Comparison

Command:

```bash
docker exec dotmd dotmd rerank compare "как подключить MCP к ChatGPT" --mode hybrid -n 10
```

Shared pool: 20 candidates.

Limitations:

- Output predates split `load_ms` / `rerank_ms`.
- Rows contain total `elapsed_ms` only.
- Returned top count was 10.

| Reranker | Status | Total elapsed | `elapsed_ms` | Returned |
|---|---|---:|---:|---:|
| `msmarco-minilm` | ok | 22s | 22311.2 | 10 |
| `mmarco-minilm` | ok | 33s | 32970.6 | 10 |
| `bge-v2-m3` | ok | 9m06s | 545916.9 | 10 |
| `qwen3-0.6b` | ok | 13m56s | 836450.3 | 10 |
| `gte-multilingual` | error | 1s | 1128.2 | 0 |

Observation: GTE failed before per-model `trust_remote_code=True` was added.

### 2026-05-01 GTE Remote-Code Smoke

Command:

```bash
docker exec dotmd dotmd rerank compare "как подключить MCP к ChatGPT" --rerankers gte-multilingual --mode hybrid -n 3
```

Shared pool: 20 candidates.

Limitations:

- Output predates split `load_ms` / `rerank_ms`.
- Single model only.
- Returned top count was 3.

| Reranker | Status | Total elapsed | `elapsed_ms` | Returned |
|---|---|---:|---:|---:|
| `gte-multilingual` | ok | 3m55s | 235374.9 | 3 |

Observation: per-model `trust_remote_code=True` fixed the provider error, but
total latency remained minutes on CPU.

### 2026-05-01 Additional Candidate Smoke

Command:

```bash
docker exec dotmd dotmd rerank compare "как подключить MCP к ChatGPT" --rerankers jina-v2-multilingual,mxbai-xsmall-v1,mxbai-base-v1,gte-modernbert-base --mode hybrid -n 3
```

Shared pool: 20 candidates.

Limitations:

- Output predates split `load_ms` / `rerank_ms`.
- Returned top count was 3.
- `jina-v2-multilingual` was missing `einops` at the time of this run.

| Reranker | Status | Total elapsed | `elapsed_ms` | Returned |
|---|---|---:|---:|---:|
| `mxbai-xsmall-v1` | ok | 32s | 31696.7 | 3 |
| `mxbai-base-v1` | ok | 48s | 47627.0 | 3 |
| `gte-modernbert-base` | ok | 7m46s | 465664.3 | 3 |
| `jina-v2-multilingual` | error | 8s | 8017.3 | 0 |

Observation: Jina dependency was fixed by adding `einops>=0.8`; a later Jina-only
run was interrupted after it exceeded several minutes, so it is recorded as
operationally slow but not as a completed canonical row.

## Canonical Runs

### 2026-05-01 Canonical Protocol v1

Pre-run checklist:

- commit hash: `ed5808b`
- container name or runtime identifier: `dotmd` container, healthy, current
  CPU-only runtime
- benchmark runner command:

```bash
docker exec dotmd python /app/devtools/reranker_latency_bench.py \
  --output /tmp/dotmd-phase20-results/2026-05-01-rerank-latency.jsonl \
  --summary /tmp/dotmd-phase20-results/2026-05-01-rerank-latency-summary.md \
  --mode hybrid \
  --top-n 3 \
  --pool-size 20 \
  --cold-passes 1 \
  --hot-passes 3 \
  --model-wall-timeout-s 900 \
  --hot-query-timeout-s 120 \
  --commit ed5808b
```

- query set version: `QUERY_SET_V1`
- model list: `msmarco-minilm`, `mmarco-minilm`, `mxbai-xsmall-v1`,
  `mxbai-base-v1`, `jina-v2-multilingual`, `gte-multilingual`, `bge-v2-m3`,
  `qwen3-0.6b`, `gte-modernbert-base`
- `shared_pool_size`: 20
- `top_n`: 3
- `mode`: `hybrid`
- expansion setting: enabled
- timeout settings: `model_wall_timeout_s=900`, `hot_query_timeout_s=120`
- raw output path:
  `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl`
- summary path:
  `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`
- raw row count: 180

Runner note: `backend/devtools` is not bind-mounted into the container, so the
committed runner was copied to `/app/devtools/reranker_latency_bench.py` before
execution. The measured code paths were the container's mounted `/app/src`
runtime.

Operational note: FTS5 logged parse errors for hyphenated benchmark query terms
such as `content-addressed` and `sqlite-vec`; these did not become benchmark
row errors because the search pipeline continued with the remaining retrieval
engines.

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

Shortlist for later quality comparison, based only on latency:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`

Quality remains out of scope for Phase 20.
