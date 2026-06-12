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

Latency survivors, based only on Phase 20 CPU timing:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`

Quality remains out of scope for Phase 20. `msmarco-minilm` is retained as a
negative historical control, not as a serious Russian-language candidate.

## Shortlist Model Evidence

This section explains what the latency shortlist means before a later quality
phase. The local benchmark above measured only CPU latency on the current
`dotmd` runtime. The external notes below come from public model cards and
dataset cards found with Exa on 2026-05-02.

Important context:

- Historical dotMD baseline before Phase 18 was `msmarco-minilm`, backed by
  `cross-encoder/ms-marco-MiniLM-L-6-v2`. In real dotMD use it behaved poorly:
  it did not understand Russian well enough to rank Russian notes usefully.
  Phase 18 replaced the default with `qwen3-0.6b` for multilingual quality
  reasons, but Phase 20 found Qwen operationally unusable on the current
  CPU-only host.
- dotMD's real corpus is predominantly Russian. English-only public benchmark
  strength is useful only as a baseline signal, not as proof of quality for our
  production workload.
- The next phase should compare relevance quality across the latency survivors,
  but `msmarco-minilm` should be treated as a negative historical control. A
  candidate that cannot beat it on Russian queries is not worth keeping.

| Local alias | Provider model | Phase 20 local latency | Public benchmark / model-card evidence | Multilingual / Russian evidence | Interpretation |
|---|---|---:|---|---|---|
| `msmarco-minilm` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | fast, p95 hot rerank ~= 4s | Hugging Face reports TREC DL 2019 NDCG@10 `74.30`, MS MARCO dev MRR@10 `39.01`, and `1800` docs/sec on V100 for this L6 model. L12 is only marginally higher (`74.31` / `39.02`) but slower. | Model card and tags are English/MS MARCO. No Russian training signal found. Local user experience confirms it ranked Russian poorly. | Negative historical control only: very fast, but not a viable Russian-language reranker. |
| `mmarco-minilm` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | fast, p95 hot rerank ~= 8s | No directly comparable TREC/MS MARCO ranking table found on the model card. It is a multilingual MiniLMv2 cross-encoder trained on mMARCO. | mMARCO is machine-translated MS MARCO. Its dataset card includes Russian among 14 languages; the model card tags include `ru` and `multilingual`. | Best language-fit survivor for dotMD. It is older and translation-trained, but it is the only latency survivor with explicit Russian/multilingual training evidence. |
| `mxbai-xsmall-v1` | `mixedbread-ai/mxbai-rerank-xsmall-v1` | acceptable, p95 hot rerank ~= 12s | Mixedbread reports BEIR aggregate NDCG@10 `43.9` and Accuracy@3 `70.0`; it beats Lucene (`38.0` / `66.4`) and BGE reranker base (`41.6` / `66.9`) in their table, but trails their base/large rerankers. | Hugging Face and Mixedbread docs identify the xsmall v1 model as English, with recommended sequence length 512. The docs mention multilingual for other Mixedbread products, not for this xsmall v1 reranker. | Good small modern reranker and plausible speed/quality tradeoff, but Russian support is unproven. Needs local quality testing before promotion. |

### Rejected Models After Latency Gate

| Local alias | Reason rejected for current CPU runtime | External quality note |
|---|---|---|
| `qwen3-0.6b` | DNF after `model_wall_timeout_s=900`; one completed cold row spent about 14m in reranking. | Phase 18 selected it from public multilingual evidence, but local CPU latency makes it unusable without a different serving path. |
| `bge-v2-m3` | DNF after `model_wall_timeout_s=900`; cold rows were tens of seconds to minutes. | Phase 18 research found strong Russian-specific evidence for BGE reranking, but current latency excludes it from local CPU production. |
| `gte-multilingual` | First hot row exceeded `hot_query_timeout_s=120` at about 3m18s. | Public multilingual evidence is strong, but not enough to pass current latency gate. |
| `jina-v2-multilingual` | DNF before producing a measured row. | Multilingual candidate, but current local CrossEncoder path is operationally too slow. |
| `gte-modernbert-base` | DNF after `model_wall_timeout_s=900`; cold rows were tens of seconds to minutes. | Interesting smaller ModernBERT candidate, but current latency excludes it. |
| `mxbai-base-v1` | DNF after `model_wall_timeout_s=900`; partial hot p95 was about 28s but it did not complete canonical samples. | Better public BEIR score than xsmall, but too slow for the full canonical local pass. |

### Source Links

- `cross-encoder/ms-marco-MiniLM-L6-v2` model card:
  https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2
- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` model card:
  https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1
- `unicamp-dl/mmarco` dataset card:
  https://huggingface.co/datasets/unicamp-dl/mmarco
- `mixedbread-ai/mxbai-rerank-xsmall-v1` model card:
  https://huggingface.co/mixedbread-ai/mxbai-rerank-xsmall-v1
- Mixedbread xsmall v1 docs:
  https://www.mixedbread.com/docs/reranking/mxbai-rerank-xsmall-v1
