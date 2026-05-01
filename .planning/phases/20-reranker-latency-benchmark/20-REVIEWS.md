---
phase: 20
reviewers: [claude, opencode]
reviewed_at: 2026-05-01T20:48:51+05:00
plans_reviewed: [20-01-latency-benchmark-protocol-PLAN.md]
---

# Cross-AI Plan Review - Phase 20

## Claude Review

### Summary

The plan is directionally correct and well-scoped. The locked decisions in
20-CONTEXT.md (hot `rerank_ms` as production gate, apples-to-apples constraint,
quality out of scope) are sound, and the exploratory ledger is handled exactly
right: annotated as non-canonical with explicit limitation notes. The main risk
is protocol ambiguity: two definitions are loose enough that two independent
runs could produce incomparable results and still claim to follow the protocol.
The hot/cold separation mechanism also needs to be made explicit before anyone
runs canonical measurements.

### Strengths

- Correct latency decomposition. Separating `load_ms` from `rerank_ms` is the
  right move; total elapsed was misleading the exploratory phase.
- Non-goals are tight. No quality evaluation, no production switch, no fusion
  tuning, which prevents scope creep on a short benchmark phase.
- Ledger is pre-populated correctly. Exploratory runs are preserved with
  explicit limitations and marked non-canonical.
- The 10-query bilingual set is representative and covers keyword, semantic,
  entity, and operational queries.
- The phase goal is achievable: latency shortlist first, quality bake-off later.

### Concerns

- HIGH: Pool size is env-var-referenced, not fixed. The protocol says "current
  configured `DOTMD_RERANK_POOL_SIZE`." If that var changes between runs or
  differs between machines, rows become incomparable. The canonical protocol
  must hard-code a number, such as 20 candidates, rather than deferring to
  runtime config.
- HIGH: Hot/cold measurement mechanism is unspecified. The plan says "one cold
  run followed by at least three hot runs per model" but does not say how. If
  each `docker exec dotmd dotmd rerank compare ...` spawns a new subprocess,
  every invocation is cold and hot measurements never actually happen. The
  protocol must name the exact mechanism: flag, script loop, or subprocess
  lifecycle.
- HIGH: "Three hot runs" is ambiguous: per query or per full pass. If one run is
  one query, there are 3 measurements per model. If one run is all 10 queries,
  there are 30. Only the 30-sample interpretation makes percentiles meaningful.
- MEDIUM: No timeout policy. Exploratory runs showed qwen3-0.6b at 14 minutes,
  bge-v2-m3 at 9 minutes, and gte-modernbert-base at 8 minutes. A canonical run
  of 10 queries times 4 passes could take many hours per slow model. The protocol
  should define a per-query hot timeout and record timeout/DNF rows.
- MEDIUM: Statistical validity of p50/p95 is underdefined. The expected sample
  count should be explicit; p95 from a tiny sample is effectively max.
- LOW: Returned top count is unspecified. Exploratory runs used 3 and 10; the
  canonical protocol should name the value.
- LOW: Cold run validity requires model-cache state. If the container has
  recently used the same model, the cold measurement may already be warm. Either
  document the caveat or specify a cache-clearing/restart step.

### Suggestions

- Fix pool size in the protocol. Change "current configured
  `DOTMD_RERANK_POOL_SIZE`" to an explicit integer, likely 20 to match the
  exploratory baseline.
- Name the hot/cold mechanism. Add one line explaining whether the benchmark
  uses a new script/flag and keeps one process alive for repeats.
- Clarify "run" definition: one cold pass of all 10 queries, followed by 3 hot
  passes of all 10 queries, giving 30 hot samples per model.
- Add a timeout. For example, hot rerank exceeding 120 seconds is recorded as
  timeout and excluded from the shortlist.
- State expected sample count explicitly.
- Add a pre-run checklist to `20-BENCHMARKS.md`: commit hash, container image or
  runtime, pool size, top-K, query set version.

### Risk Assessment

MEDIUM. The protocol has fixable ambiguities around pool size and hot/cold
mechanism that would produce non-reproducible results if not resolved before
running canonical measurements. The phase goal remains achievable once these
gaps are closed.

---

## OpenCode Review

### Summary

The plan is well-scoped and directly addresses the phase goal. It correctly
prioritizes hot reranking latency over cold load, maintains a clean separation
between exploratory and canonical data, and resists scope creep into quality
evaluation. However, several protocol parameters are under-specified: the shared
pool size is referenced as a config variable rather than a pinned value, no
wall-clock timeout is defined for slow models, and no pass/fail latency
threshold is stated. These gaps could produce canonical runs that are not truly
reproducible or that stall indefinitely on known-slow models.

### Strengths

- Hot/cold split is correctly identified as the production-relevant distinction,
  with `rerank_ms` as the gate metric and `load_ms` recorded separately for
  warmup planning.
- Exploratory versus canonical distinction with explicit protocol fields
  prevents mixing non-comparable data.
- Non-goals are clear and well-enforced: no quality, no fusion tuning, no
  default switching.
- Query set is realistic with 10 bilingual queries matching actual usage
  patterns.
- Aggregation at p50/p95/max is appropriate for operational latency
  characterization.
- Plan is appropriately sized: 5 tasks, no over-engineering.

### Concerns

- HIGH: No timeout/wall-clock limit. Exploratory runs show models taking 3 to 14
  minutes. Without a defined abort ceiling, canonical runs could hang for hours
  on a slow model, and there is no rule for when to mark a model as too slow to
  complete.
- MEDIUM: Shared pool size is not pinned. The protocol says "current configured
  `DOTMD_RERANK_POOL_SIZE`", which is a config value, not a fixed canonical
  constant. If config changes between runs, canonical rows are no longer
  apples-to-apples.
- MEDIUM: Returned top count is unspecified. The plan says "fixed for all runs"
  but never states what the fixed value is.
- MEDIUM: No pass/fail latency threshold. Without a production ceiling, the
  shortlist is a ranking rather than a gate. The phase goal says
  "operationally plausible"; that needs a numeric definition.
- MEDIUM: Model list for first canonical run is unspecified. The context lists 9
  candidates but the plan does not identify which enter the first canonical pass.
  Given that `bge-v2-m3` and `qwen3-0.6b` took 9 to 14 minutes in exploratory
  runs, the plan should explicitly decide whether to include or defer them.
- MEDIUM: No container state reset between models. Loading one model may leave
  memory pressure that affects the next model's cold load or hot performance.
  The protocol should specify whether the container is restarted or memory is
  cleared between model sequences.
- LOW: p95 with a small sample is not statistically meaningful. This is fine for
  operational characterization, but the summary should acknowledge it.
- LOW: Error handling during canonical runs is unspecified. If a model errors
  mid-canonical-run, the protocol should say whether it is retried or marked
  failed.

### Suggestions

- Pin all runtime parameters as constants in the protocol header: exact
  `shared_pool_size`, exact `top_n`, and commit hash.
- Define a wall-clock timeout, such as 10 minutes per model for cold+hot sequence
  or 5 minutes for hot-only runs. Models exceeding it are marked timeout and
  rejected from the shortlist without needing to complete all repeats.
- State the production latency ceiling in the protocol. This converts the
  ranking into an actual gate.
- Specify which models enter the first canonical run. At minimum include models
  that completed exploratory runs without error; decide explicitly on known-slow
  models.
- Specify container state management. Either restart the container between model
  sequences or explicitly accept residual memory and record available RAM at the
  start of each model sequence.
- Acknowledge p95 is close to max with small N in the summary template.

### Risk Assessment

MEDIUM. The plan structure is sound and scope is well-controlled. The main risk
is that without a timeout, canonical execution could stall on known-slow models.
The secondary risk is that unpinned parameters could produce non-reproducible
canonical rows if config drifts. Both are fixable with small protocol amendments.

---

## Consensus Summary

Both reviewers agree the phase is scoped correctly and that the latency-first,
hot-rerank-first framing is the right direction. They also agree the current
plan is not ready for execution until several protocol constants and execution
rules are pinned.

### Agreed Strengths

- Hot `rerank_ms` is the right production metric; cold `load_ms` should be
  recorded separately.
- Exploratory runs are correctly preserved but excluded from canonical ranking.
- Quality evaluation is correctly out of scope.
- The query set is realistic enough for the first latency pass.
- The plan is small and achievable.

### Agreed Concerns

- HIGH: `shared_pool_size` must be a fixed numeric constant, not "current
  configured value".
- HIGH: Hot/cold measurement mechanism must be explicit. Repeated `docker exec`
  calls may measure cold starts repeatedly unless a runner keeps the model
  loaded.
- HIGH: Timeout policy is required before running known-slow models.
- MEDIUM: Returned top count must be pinned.
- MEDIUM: The first canonical model list must be explicit.
- MEDIUM: Sample count and percentile interpretation must be explicit.
- MEDIUM: Error/timeout handling rules must be written before execution.

### Divergent Views

- OpenCode explicitly asks for a numeric pass/fail latency threshold before
  execution. Claude frames this as useful but focuses first on reproducibility
  and timeout handling. This should be resolved by defining provisional latency
  bands rather than pretending there is already a final acceptance threshold.

### Recommended Planning Updates Before Execution

1. Amend `20-01-latency-benchmark-protocol-PLAN.md` to pin
   `shared_pool_size=20` and a single `top_n` value.
2. Specify the runner/subprocess lifecycle that produces true hot repeats.
3. Define one cold full-query pass plus three hot full-query passes as the
   minimum sample shape.
4. Add timeout and DNF/error row rules.
5. Define the first canonical model set and explicitly defer known-heavy models
   if needed.
6. Add a summary note that p95 with small N is an operational percentile, not a
   statistically strong service SLO.
