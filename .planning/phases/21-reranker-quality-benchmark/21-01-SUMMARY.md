# Phase 21 Plan 01 Summary: Reranker Quality Benchmark

## Result

Phase 21 completed the canonical live-index quality benchmark for the three
latency-surviving rerankers. The benchmark used the running `dotmd` container,
the current `/dotmd-index/index.db`, 30 approved Russian/mixed queries, one
shared retrieval/fusion pool per query, and rank-based quality metrics.

## Final Quality Table

| Model | Valid queries | Pool misses | Errors | Hit@1 | Hit@3 | Hit@5 | MRR@10 | nDCG@10 | p50 rerank | p95 rerank |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| `mmarco-minilm` | 21 | 9 | 0 | 0.524 | 0.714 | 0.857 | 0.659 | 0.606 | 8s | 8s |
| `mxbai-xsmall-v1` | 21 | 9 | 0 | 0.524 | 0.810 | 0.857 | 0.676 | 0.593 | 12s | 12s |
| `msmarco-minilm` | 21 | 9 | 0 | 0.476 | 0.714 | 0.762 | 0.597 | 0.493 | 4s | 4s |

`msmarco-minilm` was treated as the negative historical control. It stayed the
fastest model, but it lost on `nDCG@10`, `MRR@10`, `Hit@1`, and `Hit@5`.

## Retrieval Gaps

The run recorded 9 pool_miss queries: `rq-007`, `rq-011`, `rq-013`, `rq-014`,
`rq-015`, `rq-016`, `rq-017`, `rq-018`, and `rq-020`.

These are retrieval gaps, not reranker failures. They were excluded from
per-model `Hit@K`, `MRR@10`, and `nDCG@10` averages.

## Recommendation

Keep `mmarco-minilm` as the default reranker.

It beat the negative historical control and had the best `nDCG@10` in the
canonical run while staying under 10s p95 hot rerank on the current CPU path.
`mxbai-xsmall-v1` is a real alternate because it had better `Hit@3` and
`MRR@10`, but it was slower at about 12s p95 hot rerank and had lower
`nDCG@10`.

No default config change is needed because the current default is already
`DOTMD_RERANKER_NAME=mmarco-minilm`.

## Commands Run

- PASS: `python3` JSONL validation for `21-LABELS.jsonl`
- PASS: `rg "Status: APPROVED|Reviewed by: human|Query count:" 21-LABELS-REVIEW.md`
- PASS: `cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py tests/api/test_service_search.py -q`
- PASS: `cd backend && uv run ruff check src/dotmd/api/service.py devtools/reranker_quality_bench.py tests/devtools/test_reranker_quality_bench.py`
- PASS: `docker exec dotmd dotmd status`
- PASS: `docker exec dotmd python /tmp/reranker_quality_bench.py ...`
- PASS: `test -s results/2026-05-02-rerank-quality.jsonl`
- PASS: `test -s results/2026-05-02-rerank-quality-summary.md`
- PASS: `rg "Canonical Run|Hit@1|MRR@10|nDCG@10|negative historical control|Recommendation|chunk strategy|pool_miss|Status: APPROVED" 21-BENCHMARKS.md`

## Deviations from Plan

- Human review checkpoint was delegated to an agent at the user's explicit
  request. The approval file records this as `human-delegated agent per user
  override`.
- The first quality runner implementation marked `pool_miss` from each model's
  top results. This was corrected before the canonical result was recorded:
  `pool_miss` now comes from the shared candidate pool exposed by
  `DotMDService.compare_rerankers()`.

## Self-Check: PASSED
