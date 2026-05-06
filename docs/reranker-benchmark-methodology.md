# Reranker Benchmark Methodology

This document is the canonical reranker evaluation runbook for dotMD.

Current production reranker: `mmarco-minilm`
(`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`).

Only `mmarco-minilm` is kept in the production built-in registry. Historical
models from Phase 20/21 remain documented here as benchmark evidence, not as
production candidates.

## Why The Benchmark Is Staged

Reranker evaluation is split into two gates:

1. Latency gate: can the model run at an acceptable speed on our CPU runtime?
2. Quality gate: among latency survivors, does the model improve ranking on the
   live dotMD corpus?

This order is intentional. A high-quality reranker that takes minutes per query
is not usable for interactive search, so quality work starts only after latency
has removed operationally impossible candidates.

## Corpus And Runtime Contract

Canonical benchmarks use the live dotMD index, not a synthetic benchmark corpus.

For the 2026-05-02 Phase 21 run:

- Runtime: live `dotmd` container
- Index: `/dotmd-index/index.db`
- Data root: `/mnt`
- Files: 826
- Chunks: 19575
- Entities: 44253
- Edges: 286361
- Graph: `falkordb @ redis://falkordb:6379/dotmd`
- Chunk strategy: `contextual_512_50`

Do not run `dotmd index --force` during benchmarking while the production
container is running. The benchmark must measure the current indexed corpus.

## Stage 1: Latency Gate

Purpose: eliminate models that are too slow, fail to load, require unavailable
runtime features, or make CPU search unusable.

Canonical latency runner:

```bash
cd backend
uv run python devtools/reranker_latency_bench.py \
  --output ../.planning/phases/20-reranker-latency-benchmark/results/<date>-rerank-latency.jsonl \
  --summary ../.planning/phases/20-reranker-latency-benchmark/results/<date>-rerank-latency-summary.md \
  --rerankers <comma-separated-candidate-names> \
  --mode hybrid \
  --top-n 3 \
  --pool-size 20
```

The latency runner records:

- cold load time: model load/warmup cost
- hot `rerank_ms`: scoring cost after the model is loaded
- human-readable elapsed fields such as `4s` or `1m12s`
- errors and timeouts
- p50, p95, and max hot rerank latency

Latency rows are sorted from fastest usable model to slowest. Models with
provider errors, wall timeouts, or hot latency that makes interactive use
impossible are rejected before the quality gate.

The threshold is a product decision, not a universal constant. In Phase 20 we
treated roughly seconds-to-tens-of-seconds as worth testing for quality and
minutes-per-query as unusable.

## Stage 2: Quality Gate

Purpose: measure whether latency survivors actually improve ranking on the live
dotMD corpus.

Canonical quality runner:

```bash
cd backend
uv run python devtools/reranker_quality_bench.py \
  --labels ../.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl \
  --output ../.planning/phases/21-reranker-quality-benchmark/results/<date>-rerank-quality.jsonl \
  --summary ../.planning/phases/21-reranker-quality-benchmark/results/<date>-rerank-quality-summary.md \
  --rerankers <comma-separated-latency-survivors> \
  --mode hybrid \
  --top-n 10 \
  --pool-size 20
```

Quality runs must use one shared candidate pool per query:

1. Expand the query.
2. Run semantic, FTS5, and graph-direct retrieval.
3. Fuse candidates with RRF.
4. Pass the same candidate IDs to every reranker.
5. Compare only the final reranked order.

This prevents comparing retrieval differences instead of reranker quality.

## Labels

Quality labels live in JSONL. Each row has:

- `id`: stable query id, for example `rq-001`
- `category`: `setup`, `architecture`, `decision-history`, `weak-baseline`, or
  `ambiguous`
- `query`: a Russian or mixed real-use query
- `relevant`: chunk labels that should rank highly
- `maybe`: optional acceptable-but-weaker labels

Labels can use direct chunk ids or historical path-plus-text selectors. Direct
chunk ids are preferred for canonical reruns because they are unambiguous.

The 2026-05-02 label set contains 30 Russian/mixed queries. It was reviewed via
an agent-delegated checkpoint requested by the user and approved in
`21-LABELS-REVIEW.md`.

## Metrics

`Hit@1`: whether a `relevant` or `maybe` label appears in the first result.

`Hit@3`: whether a `relevant` or `maybe` label appears in the first three
results. This is a coarse UX metric: "did the user see a useful answer near the
top?"

`Hit@5`: same as `Hit@3`, but for the first five results.

`MRR@10`: reciprocal rank of the first `relevant` or `maybe` label in the top
10. A useful hit at rank 1 scores `1.0`; rank 2 scores `0.5`; rank 10 scores
`0.1`.

`nDCG@10`: graded quality of the whole top 10. `relevant` labels count more
than `maybe` labels, and higher ranks matter more than lower ranks. This can
prefer a model that orders the whole top 10 better even if another model has a
higher `Hit@3`.

Raw cross-encoder scores are not compared across models. They are model-local
diagnostics only.

## Pool Misses

`pool_miss=true` means no approved label appeared in the shared retrieval pool
before reranking. That is a retrieval gap, not a reranker failure.

Pool-miss rows are excluded from per-model quality averages and reported
separately. This keeps reranker evaluation from penalizing models for documents
they never received.

## Phase 20/21 Results

Phase 20 latency gate narrowed the candidate set to:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`

Phase 21 quality gate used 30 live-index Russian/mixed queries. After correcting
`pool_miss` to use the shared candidate pool, the canonical run produced:

| Model | Valid queries | Pool misses | Errors | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 rerank | p95 rerank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mmarco-minilm` | 21 | 9 | 0 | 0.524 | 0.714 | 0.857 | 0.659 | 0.606 | 8s | 8s |
| `mxbai-xsmall-v1` | 21 | 9 | 0 | 0.524 | 0.810 | 0.857 | 0.676 | 0.593 | 12s | 12s |
| `msmarco-minilm` | 21 | 9 | 0 | 0.476 | 0.714 | 0.762 | 0.597 | 0.493 | 4s | 4s |

Decision:

- Keep `mmarco-minilm` as the only production reranker.
- Remove `msmarco-minilm` from production candidates. It was fast but ranked
  Russian dotMD content worse.
- Remove `mxbai-xsmall-v1` from production candidates. It was competitive on
  `Hit@3` and `MRR@10`, but slower and lower on the primary `nDCG@10` metric.

## How To Repeat This In The Future

When agents research newer models, they should:

1. Find small, CPU-viable multilingual or Russian-capable rerankers.
2. Record model id, release date, license, parameter size, expected language
   coverage, and whether `trust_remote_code` is needed.
3. Add temporary candidate registry entries.
4. Run the Stage 1 latency gate against the live container/runtime.
5. Remove models that fail to load, timeout, or are operationally too slow.
6. Run the Stage 2 quality gate only for latency survivors.
7. Compare quality by `nDCG@10` first, then `MRR@10`, `Hit@3`, and p95 hot
   `rerank_ms`.
8. Update this document with the exact command, commit, runtime, query count,
   label set, summary table, and production decision.
9. Remove rejected candidates from the built-in registry and Hugging Face cache.

Historical phase artifacts:

- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl`
