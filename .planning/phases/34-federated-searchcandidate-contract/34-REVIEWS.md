---
phase: 34
reviewers: [codex]
cycle: 5
status: complete
reviewed_at: 2026-05-09T00:00:00Z
plans_reviewed:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md
  - 34-02-federated-fanout-and-source-status-PLAN.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-PLAN.md
---

# Cross-AI Plan Review — Phase 34 (Cycle 5, FINAL, Post Replan-3)

> Cycle 5 is the **final cycle** of `/gsd-plan-review-convergence`
> (`MAX_CYCLES=5`). Single reviewer: **codex** via
> `ssh hetz sudo codex exec --skip-git-repo-check`. Opencode remained
> dropped after cycles 1–2 failures; other CLIs unavailable or excluded
> for independence. No cross-AI consensus is available — codex's
> findings stand alone.
>
> The cycle ran as a **post-replan-3 re-review**: the prompt explicitly
> told codex what was just fixed in commit `577756a` on `dev` (the one
> cycle-4 HIGH about cross-request concurrency, plus a MEDIUM around the
> `interleave_count` capture window and a LOW around D-02 invariant
> stamping single-pointness) and asked codex to verify each fix and
> surface any NEW concerns introduced by the fix strategy itself. The
> prompt also drew an explicit boundary against scope-broadening: the
> single-process / single-container / single-service-instance scope is
> the natural ceiling, and reaching past it (cross-process, cross-host,
> cross-container) signals invariant closure rather than a new HIGH.

## Codex Review

```
Previous HIGH Status

The cycle-4 HIGH is FULLY RESOLVED. Replan-3's dedicated
ThreadPoolExecutor(max_workers=1, thread_name_prefix="dotmd-local-search")
makes cross-request local-search overlap structurally impossible as long
as local work is submitted through self._local_executor. The two new
tests are load-bearing:

- test_local_executor_has_max_workers_one fails if max_workers=2, if the
  executor is removed, or if the implementation stops using the named
  dedicated executor.
- test_concurrent_search_async_calls_do_not_overlap_local_sequences
  fails for the original asyncio.to_thread / default-executor
  regression when two concurrent search_async() calls overlap on
  separate worker threads.

No further broader scope remains inside the stated single-process,
single-container, single-service-instance boundary.

.planning/PROJECT.md

No concerns.

Verdict: PASS

34-CONTEXT.md

No concerns. The boundary is clear, and the guardrails now correctly
stop at cross-request concurrency rather than expanding into
cross-process/container cases.

Verdict: PASS

34-RESEARCH.md

No concerns. It still contains the earlier generic asyncio.gather /
wait_for patterns, but the concrete plans supersede that with the local
single-worker executor. No contradiction severe enough to block.

Verdict: PASS

34-01 Plan

No HIGH concerns.

LOW:
- The MCP projection language is still slightly over-specified for
  Plan 01: it says MCP returns SearchCandidate directly, while also
  allowing a "thin renderer" that rounds fused_score. That is probably
  harmless, but the plan should avoid any renderer that changes
  canonical field values if round-trip equality is asserted later.

Verdict: PASS with LOW note

34-02 Plan

No HIGH concerns.

MEDIUM:
- DotMDService.close() is added, but shutdown integration is partly
  deferred: "register it via FastAPI/MCP shutdown hooks" is described as
  out of scope if it touches lifecycle wiring. Because the executor
  thread is non-daemon by default, production should have a clear
  lifecycle hook before final verification. This is not a contract
  blocker, but it is a real operational cleanup risk.

LOW:
- Task 1 acceptance says the rg for five named tests "returns three
  matches." That should be corrected to five, otherwise the acceptance
  text is stale.
- The behavioral non-overlap test text describes Invariant A and B, but
  B is effectively the same interval assertion without same-thread
  identity. The test should implement A as the actual assertion plus a
  clear failure message; the fallback wording should not weaken the
  expected single-worker invariant.

MEDIUM fix status:
- The frozen interleave_count capture is FULLY RESOLVED. Capturing
  search_finished_count in finally inside search_wrapper() correctly
  prevents a post-return tick burst from masking event-loop blockage. A
  pathological scheduler can always create noisy timing, but the
  threshold >=15 over a 2s blocking simulation is a reasonable
  regression pin.

LOW fix status:
- The D-02 stamping prose is FULLY RESOLVED. Stage 5 now has explicit
  LOCAL and FEDERATED branches, and federated candidates have
  engine_scores overwritten to None at the builder boundary regardless
  of provider input. That is a single enforcement point.

Verdict: PASS with MEDIUM/LOW cleanup

34-03 Plan

No HIGH concerns.

MEDIUM:
- Task 0 writes .planning/phases/.../34-PREFLIGHT.md and may edit
  .planning/BACKLOG.md, but those files are not listed in
  files_modified. Add them so execution tools and reviewers expect
  those writes.
- The can_read test wording says "stub provider whose object does NOT
  have a read_unit_window attribute," but the implementation derives
  from client method read_source_unit_window. That naming mismatch
  could produce a false-positive test if provider/client capability
  boundaries are confused. The plan should consistently say the
  Telegram provider derives can_read from the underlying client/provider
  capability it actually calls.

LOW:
- Task 5 says docker compose restart dotmd is autonomous regardless of
  endpoint. That is consistent with prior constraints, but it should
  name the compose working directory or rely on existing project
  scripts; otherwise execution may restart from the wrong cwd.

Verdict: PASS with MEDIUM cleanup

Overall Verdict

PASS. The cycle-4 cross-request concurrency HIGH is fully resolved by
the single-worker executor design and pinned by both structural and
behavioral tests. I do not see any new HIGH in the replan itself. The
remaining issues are cleanup-level: lifecycle shutdown wiring, stale
acceptance text, file lists for preflight/backlog writes, and one
capability-naming mismatch in Telegram tests.
```

## Reviewer Outcomes

| Plan / File   | Verdict (codex)             | Closure of prior cycle-4 items                  |
|---------------|-----------------------------|-------------------------------------------------|
| PROJECT.md    | PASS                        | n/a                                             |
| 34-CONTEXT.md | PASS                        | n/a                                             |
| 34-RESEARCH.md| PASS                        | n/a                                             |
| 34-01 PLAN    | PASS with LOW note          | n/a                                             |
| 34-02 PLAN    | PASS with MEDIUM/LOW cleanup| Cycle-4 MEDIUM (frozen interleave_count) FULLY RESOLVED |
| 34-03 PLAN    | PASS with MEDIUM cleanup    | n/a                                             |
| Overall       | **PASS**                    | Cycle-4 HIGH (cross-request concurrency) **FULLY RESOLVED** |

## Consensus Summary

**Single-reviewer cycle — final cycle of /gsd-plan-review-convergence.**

- The cycle-4 HIGH (cross-request concurrency on the default executor)
  is **FULLY RESOLVED**. Codex independently verified that the dedicated
  single-worker `ThreadPoolExecutor` with `_thread_name_prefix=
  "dotmd-local-search"` makes overlap structurally impossible for any
  local work routed through `self._local_executor`. Both new tests
  (`test_local_executor_has_max_workers_one` and
  `test_concurrent_search_async_calls_do_not_overlap_local_sequences`)
  are confirmed load-bearing — they fail under the prior
  `asyncio.to_thread`/default-executor regression.
- The cycle-4 MEDIUM (frozen `interleave_count` capture) is
  **FULLY RESOLVED**.
- The cycle-4 LOW (single-point D-02 invariant stamping) is
  **FULLY RESOLVED**.
- **Zero new HIGHs raised.** Codex explicitly notes "No further broader
  scope remains inside the stated single-process, single-container,
  single-service-instance boundary." The scope-expansion pattern
  flagged in cycle 4 (per-engine → per-request → cross-request) has
  reached its natural ceiling, as predicted by the convergence prompt.
- Residual issues are cleanup-level only:
  - 34-01 LOW: tighten language around any "thin renderer" that
    might round canonical field values vs. round-trip equality.
  - 34-02 MEDIUM: production lifecycle hook for
    `DotMDService.close()` (executor thread is non-daemon).
  - 34-02 LOW: stale "three matches" acceptance text (should be
    "five"); behavioral non-overlap test wording around
    Invariant A vs. B fallback.
  - 34-03 MEDIUM: missing `34-PREFLIGHT.md` / `BACKLOG.md` in
    `files_modified`; `can_read` test wording naming mismatch
    against `read_source_unit_window` derivation.
  - 34-03 LOW: name compose working directory for `docker compose
    restart dotmd`.

**Total unresolved HIGHs (current_high): 0.**

prev_high_count was 1; current_high is 0. **Convergence achieved on the
final cycle.** Replan-3's "invariant by construction" choice (Option B,
single-worker executor) was structurally sound and codex confirmed
closure without raising any successor HIGH at any broader scope. Risk
profile drops from MEDIUM to LOW: residuals are documentation cleanup
and a non-blocker lifecycle wiring item that can be addressed during
execution.

The phase is **cleared to proceed to execution** under standard
`/gsd-execute-phase` flow. The MEDIUM/LOW cleanups should be folded into
the corresponding plan task acceptance during execution rather than
re-cycled through plan review.

---

*Cycle 5 of cross-AI review for Phase 34 — FINAL of MAX_CYCLES=5.
Single reviewer (codex). Replan-3 from commit `577756a` verified:
cycle-4 HIGH fully closed; zero new HIGHs at any scope. Convergence
achieved. Risk now LOW.*
