# Phase 20: Reranker Latency Benchmark Context

**Created:** 2026-05-01
**Workflow:** short follow-up phase after Phase 19
**Depends on:** Phase 19

## Phase Goal

Establish a reproducible latency benchmark protocol for rerankers and select the
models worth comparing for quality.

## Why This Phase Exists

Phase 19 added the adapter layer and developer comparison surface. Initial live
smokes showed that several multilingual rerankers take tens of seconds or
minutes on the current CPU-only container. That makes latency a first-class
quality gate before any quality bake-off.

The main production question is not cold startup. Cold load time matters for
deploy/warmup operations, but user-facing search depends on hot reranking time
once the model is already loaded.

## Locked Decisions

1. **Latency comes before quality.**
   Phase 20 only decides which models are operationally plausible. It does not
   judge relevance quality.

2. **Hot `rerank_ms` is the production gate.**
   `load_ms` is recorded separately for warmup policy. `elapsed_ms` remains total
   time and must not be used alone to reject or accept production candidates.

3. **All canonical rows must be apples-to-apples.**
   A canonical run fixes query set, container/runtime, mode, expansion setting,
   shared candidate pool size, reranker list, and repeat count.

4. **Ad hoc exploratory runs are evidence, not ranking data.**
   Earlier manual runs are kept in the ledger, but they are explicitly marked
   non-canonical when protocol fields differ or hot/cold timings were not split.

5. **Quality bake-off is out of scope.**
   Quality comparison starts only after latency shortlist is known.

## Candidate Sources

Phase 18 research remains the source of model candidates:

- `Qwen/Qwen3-Reranker-0.6B`
- `BAAI/bge-reranker-v2-m3`
- `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
- `Alibaba-NLP/gte-multilingual-reranker-base`
- `jinaai/jina-reranker-v2-base-multilingual`
- `jinaai/jina-reranker-v3`
- `mixedbread-ai/mxbai-rerank-xsmall-v1`
- `mixedbread-ai/mxbai-rerank-base-v1`
- `Alibaba-NLP/gte-reranker-modernbert-base`

Not every candidate must enter the first canonical run. Heavy or non-CrossEncoder
models can be deferred if they need a separate adapter or dependency spike.

## Benchmark Contract

Canonical benchmark rows must record:

- commit hash
- container/runtime identifier
- command
- query set name and query text
- `mode`
- expansion on/off
- `shared_pool_size`
- returned top count
- reranker name and model name
- `load_ms`
- `rerank_ms`
- `elapsed_ms`
- error text, if any
- raw output or path to raw output

The canonical summary should report p50, p95, max, and error count per model
over hot `rerank_ms`.

## Out Of Scope

- Relevance quality judgments
- Fusion weight tuning
- Production default switch
- New non-CrossEncoder serving backend unless needed to measure a specific model
