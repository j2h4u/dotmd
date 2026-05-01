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

No canonical runs yet. Start after the split timing fields from commit
`1ed6aa6` are present in the running container.
