# Phase 44 Acceptance: Reranker On

## Source Evidence

- Full old-vs-standalone run:
  `/home/j2h4u/.cache/dotmd/phase43-target/baseline-compare-refreshg01/`
- Candidate reranker-on follow-up:
  `/home/j2h4u/.cache/dotmd/phase43-target/shadow-refreshg-candidate-rerank01/`

## Quality

- Full run classification: `regression=0`, `harmless_reorder=6`,
  `unclear=10`.
- Candidate reranker-on follow-up classification: `regression=0`,
  `harmless_reorder=4`, `unclear=12`, all unclear rows accepted.
- Search-quality evidence does not show a material regression, but the golden
  corpus still has weak labels for several accepted unclear rows.

## Latency

Full old-vs-standalone run:

- Baseline mean: `20066.7ms`
- Baseline p50: `18902.2ms`
- Candidate mean: `24346.9ms`
- Candidate p50: `24606.5ms`

Candidate reranker-on follow-up:

- Candidate mean: `20289.2ms`
- Candidate p50: `14371.0ms`
- Candidate max: `94299.7ms`

## Decision

Reranker-on acceptance is **not cutover-ready**.

Reason: quality is acceptable enough for continued work, but latency remains too
high and unstable for a production cutover decision. This is a runtime-quality
blocker, not a data-migration blocker.
