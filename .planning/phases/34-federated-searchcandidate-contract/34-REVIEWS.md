---
phase: 34
reviewers: [codex]
cycle: 4
status: complete
reviewed_at: 2026-05-08T19:38:08Z
plans_reviewed:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md
  - 34-02-federated-fanout-and-source-status-PLAN.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-PLAN.md
---

# Cross-AI Plan Review — Phase 34 (Cycle 4, Post Replan-2)

> Cycle 4 is a **single-reviewer cycle** (codex via `ssh hetz sudo codex
> exec --skip-git-repo-check`). Opencode remains dropped after two
> failed cycles 1–2 (32-min hang, then Explore-Agent fanout that never
> returned). Other CLIs (gemini, cursor, claude, ollama, lm-studio,
> llama-cpp) are unavailable or excluded for self-review independence
> reasons. No cross-AI consensus is therefore available — codex's
> findings stand alone.
>
> The cycle ran as a **post-replan-2 re-review**: the prompt explicitly
> told codex what was just fixed in commit `13a39af` on `dev` (the one
> cycle-3 HIGH about `asyncio.to_thread` per-engine wraps, plus three
> MEDIUMs/LOWs) and asked codex to verify each fix and surface any NEW
> concerns introduced by the fix strategy itself. Codex returned a
> substantive 3.2 KB structured review with explicit closure verdicts.

## Codex Review

Codex (hand-run on hetz: `ssh hetz sudo codex exec --skip-git-repo-check -`)
returned a structured 3.2 KB review at the requested format. The hetz
sandbox blocks reading `/home/j2h4u` directly, so the review is grounded
in the embedded prompt context (PROJECT.md head, CONTEXT.md,
RESEARCH.md, all three PLAN.md files — total 189 KB prompt). The
verbatim output follows.

---

**Summary** — Replan-2 correctly fixes the specific Cycle 3 defect: it replaces three concurrent per-engine `asyncio.to_thread(...)` calls with one off-loop local sequence and overlaps that with federated fan-out. The plan is materially better and preserves local-engine sequencing within a single search call. I do see one new HIGH edge case: concurrent `search_async()` requests can still run multiple local sequences at the same time on the default thread pool, so the broader SQLite/metadata/graph single-access invariant is not globally pinned.

**Closure verification of cycle-3 HIGH (event-loop block)**

- **FULLY RESOLVED** — Plan 34-02 Task 3 now specifies `asyncio.to_thread(self._run_local_search_sequence, ...)` exactly once, with semantic -> keyword -> graph_direct run sequentially inside that helper and composed with federated fan-out via `asyncio.gather(local_task, federated_task)`.

**Regression check vs cycle-2 fixes**

- **Partially preserved** — the single-thread local invariant is preserved **within one `search_async()` call**, and the new thread-ID test pins that; however, the plan does not serialize local search across **multiple concurrent `search_async()` calls**, so shared SQLite/metadata/graph clients can still be touched concurrently by two request-level worker threads.

**New Concerns**

- **HIGH** — Cross-request local concurrency remains unguarded. Because each `search_async()` call uses `asyncio.to_thread(...)` on the default executor, two simultaneous MCP/FastAPI searches can run two `_run_local_search_sequence(...)` calls concurrently on different worker threads. That is a missed edge case against the Cycle 2 single-thread SQLite/metadata/graph invariant.

- **MEDIUM** — `test_search_async_does_not_block_event_loop` needs to explicitly capture `interleave_count` at the moment `search_async` completes. As written in the plan, `await asyncio.gather(service.search_async(...), interleaver())` followed by asserting the final count can pass even if `search_async` blocked first and the interleaver only ran afterward.

- **LOW** — Task 3 Stage 5 wording is slightly contradictory: it says to merge per-engine attribution from federated engine names, then says federated candidates must have `engine_scores=None`. The D-02 invariant and test are clear, but the implementation instruction should be tightened.

**Suggestions**

- Add a service-level local-search gate: either an `asyncio.Lock` around the single `to_thread` local sequence, or a dedicated single-worker executor for local search. The goal is no overlapping local sequences across concurrent requests.

- Add a test like `test_concurrent_search_async_calls_do_not_overlap_local_sequences`: launch two `search_async()` calls, make `_run_local_search_sequence` block briefly, and assert no overlap.

- Fix the event-loop test by wrapping search in a coroutine that records the interleaver count in a `finally` or immediately after `await service.search_async(...)`, then assert that recorded value is >= 15.

**Risk Assessment**

- **MEDIUM** — The targeted Cycle 3 issue is closed, but the cross-request concurrency hole is significant for a server surface. With a local-search lock or single-worker executor plus the adjusted test, risk drops to LOW.

---

## Reviewer Outcomes (Operational)

| Reviewer | Status      | Wall time | Output bytes | Notes |
|----------|-------------|-----------|--------------|-------|
| codex (ssh-hetz) | substantive | ~50s | 3280 | `ssh hetz sudo codex exec --skip-git-repo-check -`. Default model. 189 KB prompt. Output: cycle-3 HIGH FULLY RESOLVED, 1 NEW HIGH (cross-request concurrency), 1 NEW MEDIUM (test capture timing), 1 NEW LOW (stage-5 wording). 65,192 tokens used. Stderr was a thinking-trace duplicate, not an error log. |

## Consensus Summary

**Single-reviewer cycle — no cross-AI consensus available.** Cycle 4
ran with codex only; opencode remains dropped after two prior failed
runs and no other CLI is available. The summary below reflects codex's
findings alone and should be treated as raised-by-codex, not
consensus-blocking.

### Strengths (codex)

- Cycle-3 HIGH (event-loop block) **FULLY RESOLVED** — single
  `asyncio.to_thread(_run_local_search_sequence, ...)` overlapping
  federated fan-out via `asyncio.gather(local_task, federated_task)`.
- New regression-pin tests (loop-not-blocked, single-worker-thread,
  local↔federated overlap) directly target the defect class and lock
  the structural choice.
- Plan is "materially better" per codex.

### Concerns (codex; treat as raised, not consensus-blocking)

1. **NEW HIGH — Cross-request local concurrency unguarded.** Two
   simultaneous `search_async()` calls each call `to_thread` on the
   default executor; two `_run_local_search_sequence(...)` invocations
   can overlap on different worker threads. Cycle-2 single-thread
   SQLite/metadata/graph invariant holds **per request** but not
   **across requests**. Suggested fix: service-level `asyncio.Lock`
   around the local-sequence `to_thread`, or a dedicated single-worker
   executor.
2. **NEW MEDIUM — Event-loop test timing.** `await asyncio.gather(...)`
   in the test allows the interleaver to keep ticking after
   `search_async` returns, so the count assertion may pass even if
   `search_async` itself blocked first. Capture `interleave_count`
   immediately when `search_async` completes (e.g. via `finally`).
3. **NEW LOW — Stage 5 wording in Plan 34-02 Task 3.** Reads as if
   federated engine attribution is merged into `engine_scores`, then
   immediately says `engine_scores=None` for federated. The D-02
   invariant and test are right; only the prose contradicts itself.

### Divergent Views

Not applicable — only one reviewer in this cycle.

---

## HIGH Concern Counting (Cycle 4)

Per the GSD review-convergence contract:

- **FULLY RESOLVED prior HIGHs (excluded):** 1 — cycle-3 event-loop
  block (now structurally fixed by single-helper `to_thread` plus
  `gather`).
- **NEW HIGHs (counted):** 1 — cross-request local concurrency
  unguarded. Default executor allows two simultaneous `search_async`
  calls to run two `_run_local_search_sequence` invocations on
  different worker threads, breaking the cycle-2 single-thread
  SQLite/metadata/graph invariant globally.

**Total unresolved HIGHs (current_high): 1.**

prev_high_count was 1; current_high is 1. **Stall trigger fires
(current_high >= prev_high_count).** This is a concerning signal:
replan-1 closed 7/8 cycle-2 HIGHs but left a residual that became
cycle-3's HIGH. Replan-2 closed cycle-3's HIGH but surfaced a new
cycle-4 HIGH about cross-request concurrency — the **same invariant
class** (single-thread SQLite/metadata/graph) but at a different scope
(cross-request rather than per-request). The reviewer scope keeps
expanding: per-engine → per-request → cross-request.

The orchestrator should weigh:

- The new HIGH is a known fix (service-level `asyncio.Lock` or single-
  worker executor — codex spelled it out). Replan-3 is small and well-
  scoped.
- This is cycle 4 of MAX_CYCLES=5. Replan-3 → cycle 5 review is the
  last allotted slot. If cycle 5 surfaces yet another invariant scope,
  convergence has failed and operator review is needed.
- Alternatively: ship as-is and address cross-request concurrency
  during execution, since dotMD is single-user localhost and concurrent
  searches are rare. This is a defensible "known issue, deferred"
  call given the system's actual usage pattern.

---

*Cycle 4 of cross-AI review for Phase 34. Single reviewer (codex).
Replan-2 from commit `13a39af` verified: cycle-3 HIGH fully closed; one
new HIGH surfaced about cross-request concurrency (same invariant
class, broader scope). Stall trigger fires. Risk remains MEDIUM.*
