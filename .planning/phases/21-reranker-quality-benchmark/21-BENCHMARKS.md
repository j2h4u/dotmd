# Phase 21 Reranker Quality Benchmark

Status: DRAFT LABELS, NOT CANONICAL.

`21-LABELS.jsonl` was drafted from the current live container/index by taking
top hybrid no-rerank candidates as label suggestions. These rows are review
inputs, not ground truth. canonical scoring requires 21-LABELS-REVIEW.md to
contain APPROVED.

## Live Runtime Snapshot

- Runtime: `dotmd` container
- Index files: 826
- Chunks: 19575
- Entities: 44253
- Edges: 286361
- Graph: `falkordb @ redis://falkordb:6379/dotmd`
- chunk strategy: `contextual_512_50`
- Data dir: `/mnt`
- Index dir: `/dotmd-index`

## Canonical Protocol v1

- `model_set=msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1`
- `negative_control=msmarco-minilm`
- `mode=hybrid`
- `expand=true`
- `shared_pool_size=20`
- `top_n=10`
- `minimum_queries=30`
- `metrics=Hit@1,Hit@3,Hit@5,MRR@10,nDCG@10`
- `grade_map=relevant:2,maybe:1,irrelevant:0`
- `sort_metric=nDCG@10`
- `tie_breakers=MRR@10,Hit@3,lower p95 hot rerank_ms`
- `pool_miss_policy=exclude_from_quality_average_and_report_separately`
- `label_approval=21-LABELS-REVIEW.md APPROVED`

msmarco-minilm is a negative historical control

pool_miss queries are retrieval gaps; they are excluded from per-model quality
averages and reported separately

canonical scoring requires 21-LABELS-REVIEW.md to contain APPROVED

## Model Table

| Model key | Model id | Role | Expected use |
|---|---|---|---|
| `msmarco-minilm` | `cross-encoder/ms-marco-MiniLM-L-6-v2` | negative historical control | Keep as baseline because it was the original English/MS MARCO-style reranker and performed poorly on Russian relevance. |
| `mmarco-minilm` | `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` | multilingual candidate | Candidate intended to improve Russian/multilingual behavior while remaining small enough for CPU use. |
| `mxbai-xsmall-v1` | `mixedbread-ai/mxbai-rerank-xsmall-v1` | compact modern candidate | Candidate from the Phase 20 latency shortlist with smaller CPU footprint. |

## Metrics

| Metric | Definition |
|---|---|
| `Hit@1` | `1` when a `relevant` or `maybe` label appears in rank 1, otherwise `0`. |
| `Hit@3` | `1` when a `relevant` or `maybe` label appears in ranks 1-3, otherwise `0`. |
| `Hit@5` | `1` when a `relevant` or `maybe` label appears in ranks 1-5, otherwise `0`. |
| `MRR@10` | Reciprocal rank of the first `relevant` or `maybe` label in ranks 1-10, otherwise `0`. |
| `nDCG@10` | Discounted gain over ranks 1-10 using `relevant=2`, `maybe=1`, normalized by ideal DCG for the query labels. |

Raw cross-encoder scores are diagnostics only. They are not comparable across
models and must not be used as quality metrics.

## Pre-Run Checklist

- [ ] Commit hash recorded.
- [ ] Container/runtime recorded.
- [ ] Query count recorded and >= 30.
- [ ] Label coverage recorded.
- [ ] `shared_pool_size=20` recorded.
- [ ] `top_n=10` recorded.
- [ ] Model list recorded exactly as `msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1`.
- [ ] chunk strategy recorded from `Settings.chunk_strategy`.
- [ ] Command recorded.
- [ ] Raw output path recorded.
- [ ] `21-LABELS-REVIEW.md` exists and contains `Status: APPROVED`.

## Draft Label Notes

The current `21-LABELS.jsonl` intentionally keeps `draft_source` and
`draft_note` fields so the human review can distinguish machine-selected
candidates from approved relevance judgments.

Some draft candidates are expected to be weak or irrelevant because they were
generated from the current retrieval stack, not from manual judgment. This is
acceptable before Task 2 and unacceptable for canonical scoring.

## Canonical Result Template

Fill this section after Task 4.

| Model | Valid queries | Pool misses | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 hot rerank_ms | p95 hot rerank_ms |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `msmarco-minilm` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `mmarco-minilm` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |
| `mxbai-xsmall-v1` | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

## Canonical Run 2026-05-02

- commit: `e7beafc`
- runtime/container: live `dotmd` container
- runner path: copied to `/tmp/reranker_quality_bench.py` because `/app/devtools` did not contain the new runner and `/app/.planning` was not mounted
- raw output path: `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl`
- summary path: `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`
- query count: 30
- label resolution count: 30 queries / 90 model rows
- label approval: `.planning/phases/21-reranker-quality-benchmark/21-LABELS-REVIEW.md`, `Status: APPROVED`, `Query count: 30`
- chunk strategy: `contextual_512_50`
- `shared_pool_size=20`
- `top_n=10`
- mode: `hybrid`
- expansion: enabled
- errors: 0

Command:

```bash
docker exec dotmd python /tmp/reranker_quality_bench.py \
  --labels /tmp/21-LABELS.jsonl \
  --output /tmp/2026-05-02-rerank-quality.jsonl \
  --summary /tmp/2026-05-02-rerank-quality-summary.md \
  --rerankers msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1 \
  --mode hybrid \
  --top-n 10 \
  --pool-size 20 \
  --commit e7beafc
```

Observed FTS5 parser warnings for queries containing punctuation or hyphenated
tokens: `oauth_state.json`, `sqlite-vec`, and `content-addressed`. They were
non-fatal; semantic and graph retrieval continued.

| Model | Valid queries | Pool misses | Errors | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 hot rerank | p95 hot rerank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mmarco-minilm` | 21 | 9 | 0 | 0.524 | 0.714 | 0.857 | 0.659 | 0.606 | 8s | 8s |
| `mxbai-xsmall-v1` | 21 | 9 | 0 | 0.524 | 0.810 | 0.857 | 0.676 | 0.593 | 12s | 12s |
| `msmarco-minilm` | 21 | 9 | 0 | 0.476 | 0.714 | 0.762 | 0.597 | 0.493 | 4s | 4s |

`msmarco-minilm` remains the negative historical control: it is fastest, but it
lost clearly on `nDCG@10`, `MRR@10`, `Hit@1`, and `Hit@5`.

pool_miss query ids: `rq-007`, `rq-011`, `rq-013`, `rq-014`, `rq-015`,
`rq-016`, `rq-017`, `rq-018`, `rq-020`.

pool_miss queries are retrieval gaps; they are excluded from per-model quality
averages and reported separately

Per-query failure examples: none. All model rows completed without provider
errors.

Recommendation: keep `mmarco-minilm` as the default reranker for now. It has the
best `nDCG@10` in the canonical run and stays under 10s p95 hot rerank on the
current CPU path. `mxbai-xsmall-v1` is competitive and stronger on `Hit@3` /
`MRR@10`, but its p95 hot rerank was about 12s and its `nDCG@10` was lower.
Continue model search only if the next requirement prioritizes `Hit@3` over
`nDCG@10` or if a faster multilingual reranker is added.
