---
phase: 34
reviewers: [codex]
cycle: 3
status: complete
reviewed_at: 2026-05-08T19:24:54Z
plans_reviewed:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md
  - 34-02-federated-fanout-and-source-status-PLAN.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-PLAN.md
---

# Cross-AI Plan Review — Phase 34 (Cycle 3, Post-Replan)

> Cycle 3 is a **single-reviewer cycle** (codex via `ssh hetz sudo codex
> exec --skip-git-repo-check`). Opencode was dropped this cycle after
> failing twice in different ways across cycles 1–2 (32-min hang, then
> Explore-Agent fanout that never returned a final answer). Other CLIs
> (gemini, cursor, claude, ollama, lm-studio, llama-cpp) are unavailable
> or excluded for self-review independence reasons. No cross-AI consensus
> is therefore available — codex's findings stand alone.
>
> The cycle ran as a **post-replan re-review**: the prompt explicitly
> told codex what was just fixed (the eight cycle-2 HIGHs and seven
> MEDIUMs folded into commit `4feab98` on `dev`) and asked codex to
> verify each fix and surface any NEW concerns introduced by the fix
> strategy itself. Codex returned a substantive 5 KB structured review
> with explicit closure verdicts.

## Codex Review

Codex (hand-run on hetz: `ssh hetz sudo codex exec --skip-git-repo-check -`)
returned a structured 5 KB review at the requested format. The hetz
sandbox blocks reading `/home/j2h4u` directly, so the review is grounded
in the embedded prompt context (PROJECT.md, REQUIREMENTS.md, ROADMAP
phase section, CONTEXT.md, RESEARCH.md, PATTERNS.md, all three PLAN.md
files — total 200 KB prompt). The verbatim output follows.

---

**Summary** — The replan closes the eight Cycle 2 HIGHs structurally. The plans are much more explicit about source identity, MCP contract shape, async boundaries, lifecycle failure handling, local Telegram visibility, and mcp-telegram coordination. I see two new concerns introduced by the fix strategy: one HIGH around `search_async` blocking the MCP/FastAPI event loop while local engines run synchronously, and one MEDIUM around an untestable/fragile "mutate then accept either behavior" contract for shallow-frozen containers.

**Closure verification of cycle-2 HIGHs**

- **1. descriptor_key added** — **FULLY RESOLVED**. `descriptor_key: str` is required, no default, independently tested from `source_kind`, and carried into Telegram candidates.
- **2. SearchHit narrowing removed** — **FULLY RESOLVED**. Plans require no `SearchHit` / `SearchEnvelope` narrowing and MCP returns full `SearchResponse` with full `SearchCandidate` records.
- **3. EngineOutcome split** — **FULLY RESOLVED**. `LocalEngineOutcome.ranked_chunks` and `FederatedEngineOutcome.candidates` are distinct, with tests forbidding shape conflation.
- **4. Local engine concurrency** — **FULLY RESOLVED** for the original SQLite/thread-safety concern. Local engines are sequential; only federated providers fan out.
- **5. search_async canonical / sync wrapper safety** — **PARTIALLY RESOLVED**. The running-loop `RuntimeError` and MCP `search_async` call are fixed, but the planned `search_async` runs local sync engines directly inside the event loop. See new HIGH.
- **6. Lifecycle init failures** — **FULLY RESOLVED**. Per-source build failures are captured in `_lifecycle_init_errors` and surfaced as persistent `SourceStatus(error)`.
- **7. Telegram read active-binding gate** — **FULLY RESOLVED**. The new `TelegramReadPath` local-first routing explicitly prevents inactive local Telegram refs from falling through to provider.
- **8. autonomous flag / daemon endpoint** — **FULLY RESOLVED**. Task 0 preflight, `34-PREFLIGHT.md`, conditional smoke, and backlog follow-up address the out-of-repo dependency.

**New Concerns**

- **HIGH — `search_async` blocks the event loop during local search.** Plan 34-02 says MCP/FastAPI call `await service.search_async(...)` directly, but `search_async` then calls `_run_local_engine(...)` synchronously for semantic, keyword, and graph engines. That preserves single-threaded local access, but it also blocks the FastMCP/FastAPI event loop for the full local search duration before federated fan-out begins. This is a regression from the old MCP `asyncio.to_thread(service.search, ...)` bridge and can stall unrelated MCP requests.

- **MEDIUM — Plan 34-02 accidentally serializes local and federated work.** The plan runs all local engines first, then federated fan-out. This is safe but undercuts the always-on fan-out latency model: the 4s federated timeout becomes additive after local search instead of overlapping with it. This may be acceptable, but it should be an explicit tradeoff and tested as `local_duration + federated_timeout`, not described as preserving response budget.

- **MEDIUM — The shallow-frozen container test is non-deterministic as written.** Plan 34-01 says a test may either observe mutation succeeds or assert mutation raises if the implementer chooses stronger immutability. That is not a stable contract test. Pick one contract: either convert containers to immutable types, or document shallow immutability and assert mutation succeeds as current Pydantic behavior.

- **LOW — Minor internal inconsistency in Plan 34-02 task 4 done text.** It says "MCP `search` tool returns `SearchEnvelope`," while acceptance criteria explicitly forbid `SearchEnvelope` and require `SearchResponse`. Acceptance is correct; fix the done text to avoid executor confusion.

**Suggestions**

- Keep local engines sequential, but move the whole local sequence off the event loop through one dedicated worker call, e.g. `await asyncio.to_thread(self._run_local_search_sequence, ...)`. That preserves "one thread, sequential local engines" while preventing MCP/FastAPI event-loop blockage.

- Start federated fan-out before awaiting local worker completion if lifecycle providers are independent: create federated tasks, run the local sequence in one worker thread, then await both. This overlaps federated timeout with local work without concurrent local DB access.

- Replace the flexible shallow-freeze test with a single chosen contract. Prefer immutable containers if this is a public model: `tuple[str, ...]` for `matched_engines` and read-only copied dicts, or document shallow freeze and avoid pretending the model is deeply immutable.

- Fix Plan 34-02 task 4 `<done>` to say `SearchResponse`, not `SearchEnvelope`.

**Risk Assessment** — **MEDIUM**. The replan closes the original HIGHs well, and the test strategy is strong. The main remaining risk is operational: the canonical async API may block the server event loop during local search unless the sequential local path is moved into one worker thread or otherwise isolated.

---

## Reviewer Outcomes (Operational)

| Reviewer | Status      | Wall time | Output bytes | Notes |
|----------|-------------|-----------|--------------|-------|
| codex (ssh-hetz) | substantive | 39s | 5115 | `ssh hetz sudo codex exec --skip-git-repo-check -`. Default model (no `review.models.codex` override). 200 KB prompt accepted. Output: 1 NEW HIGH, 2 NEW MEDIUM, 1 NEW LOW. 7/8 cycle-2 HIGHs marked FULLY RESOLVED, 1/8 (HIGH-5) marked PARTIALLY RESOLVED — same defect codex re-raises as the new HIGH. 65,015 tokens used. Stderr was a thinking-trace duplicate, not an error log. |

## Consensus Summary

**Single-reviewer cycle — no cross-AI consensus available.** Cycle 3
ran with codex only; opencode was dropped after two failed runs and no
other CLI was available. The summary below reflects codex's findings
alone and should be treated as raised-by-codex, not consensus-blocking.

### Strengths (codex)

- All eight cycle-2 HIGHs structurally addressed (7 FULLY RESOLVED + 1
  PARTIALLY RESOLVED with a precisely identified residual gap).
- Source identity, MCP contract shape, EngineOutcome typing, lifecycle
  init resilience, Telegram active-binding gate, and mcp-telegram
  daemon coordination all read as correct.
- Test strategy is "strong" per codex. `descriptor_key` independence,
  `EngineOutcome` shape forbidding, `TelegramReadPath` local-first
  routing — all explicitly testable.

### Concerns (codex; treat as raised, not consensus-blocking)

1. **`search_async` event-loop blockage (NEW HIGH).** Local engines run
   synchronously inside the awaited `search_async` coroutine. Stalls
   FastMCP / FastAPI event loop for the full local-search duration
   before federated fan-out starts. Same defect codex flagged as
   HIGH-5 PARTIALLY RESOLVED — closing HIGH-5 means addressing this.
2. **Sequential local-then-federated execution (NEW MEDIUM).** Federated
   timeout becomes additive instead of overlapping with local work.
   Either accept and document as `local_duration + federated_timeout`
   budget, or overlap via concurrent task creation.
3. **Shallow-frozen container test indeterminacy (NEW MEDIUM).** Plan
   34-01's "accept either mutation-succeeds or mutation-raises" test
   is not a stable contract. Pick one and assert it.
4. **Plan 34-02 Task 4 `<done>` text mismatch (NEW LOW).** Says
   `SearchEnvelope`; acceptance criteria require `SearchResponse`.

### Divergent Views

Not applicable — only one reviewer in this cycle.

---

## HIGH Concern Counting (Cycle 3)

Per the GSD review-convergence contract:

- **FULLY RESOLVED HIGHs (excluded):** 7 — HIGH-1, HIGH-2, HIGH-3,
  HIGH-4, HIGH-6, HIGH-7, HIGH-8.
- **PARTIALLY RESOLVED HIGHs (counted):** 1 — HIGH-5 (search_async
  event-loop blockage).
- **NEW HIGHs (counted):** 1 — `search_async` blocks event loop. **This
  is the same defect as the HIGH-5 residual** (codex explicitly says
  "See new HIGH" in its HIGH-5 verdict). To avoid double-counting,
  treated as a single unresolved HIGH.

**Total unresolved HIGHs (current_high): 1.**

prev_high_count was 8; current_high is 1. Stall trigger
(current_high >= prev_high_count) does NOT fire. Convergence loop is
making progress and may continue to Cycle 4 if a replan is performed,
or may proceed to plan acceptance if the operator deems 1 HIGH about
event-loop blocking acceptable / addressable as a quick edit during
execution.

---

*Cycle 3 of cross-AI review for Phase 34. Single reviewer (codex).
Replan from cycle 2 commit `4feab98` verified: 7/8 prior HIGHs fully
closed, 1/8 partially closed (residual surfaced as new HIGH about
event-loop blockage). Plans are otherwise sound; risk dropped from
MEDIUM-HIGH (cycle 2) to MEDIUM (cycle 3).*
