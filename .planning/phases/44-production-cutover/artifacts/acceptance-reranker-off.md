# Phase 44 Acceptance: Reranker Off

## Source Evidence

- Candidate reranker-off evidence:
  `/home/j2h4u/.cache/dotmd/phase43-target/shadow-refreshg-candidate-only14/`
- Baseline timing sample reused from Phase 43 accepted evidence:
  `/home/j2h4u/.cache/dotmd/phase43-target/shadow-refreshg-candidate-rerank01/`

## Quality

- Classification: `regression=0`, `harmless_reorder=4`, `unclear=12`.
- Accepted semantic changes: `sq-002`, `sq-003`, `sq-004`, `sq-007`,
  `sq-009`, `sq-010`, `sq-011`, `sq-012`, `sq-013`, `sq-014`, `sq-015`,
  `sq-016`.
- Unresolved blockers: none.
- Report gate: passed.

## Latency

- Baseline mean: `3618.5ms`
- Baseline p50: `3224.1ms`
- Baseline p95: `7008.1ms`
- Candidate mean: `2433.6ms`
- Candidate p50: `1308.1ms`
- Candidate p95: `8494.1ms`

## Decision

Reranker-off acceptance is **promising but not sufficient for cutover**.

Reason: the candidate is faster on mean and p50, but Phase 44 requires both
reranker modes and runtime smoke. Reranker-on remains too slow, and the repo
does not yet expose a Surreal-only runtime switch for MCP/API/CLI/trickle.
