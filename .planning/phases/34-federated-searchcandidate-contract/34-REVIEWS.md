---
phase: 34
reviewers: [opencode, codex]
reviewed_at: 2026-05-08T20:55:00Z
plans_reviewed:
  - 34-01-searchcandidate-contract-and-ref-keyed-fusion-PLAN.md
  - 34-02-federated-fanout-and-source-status-PLAN.md
  - 34-03-telegram-federated-proof-and-read-roundtrip-PLAN.md
cycle: 2
status: partial
---

# Cross-AI Plan Review — Phase 34

> Cycle 2 ran with `--opencode` (gsd-review pipeline, default model after
> the bad `review.models.opencode = "opencode run"` config was cleared)
> and codex hand-run via `ssh hetz sudo codex exec --skip-git-repo-check`.
> Codex returned a substantive review (~12 KB). OpenCode produced only
> 96 B (a single intro sentence) before exiting cleanly — a different
> failure mode than Cycle 1's hang, but still no substantive output.
> Convergence math is therefore based on codex alone; opencode is NOT
> counted as silent agreement.

## OpenCode Review

OpenCode review failed or returned empty output.

**Outcome:** `opencode run -` (default model `build · glm-5.1`)
accepted the prompt (`/tmp/gsd-review-prompt-34.md`, 161 KB) and began
spawning Explore Agents (`Explore dotMD codebase for review` ✓,
`Examine Airweave federated search` ●). The process exited cleanly
(exit 0) after writing only the intro string `Let me first examine the
current codebase state and the Airweave reference to ground my review.`
to stdout (96 bytes). No review sections, no concerns, no risk
assessment were emitted. The Explore Agent pipeline did not loop back
into a final answer to stdout.

This is a different failure mode from Cycle 1 (which was a 32-min hang
on the LLM response dispatch). The Cycle 2 process actually finished —
but with the model deciding to delegate to sub-agents and then never
producing the summarizing answer. Likely an opencode build-mode quirk
when the prompt is large enough to trigger Explore Agent fanout.

**Substantive feedback gathered:** none.

---

## Codex Review

Codex (hand-run on hetz: `ssh hetz sudo codex exec --skip-git-repo-check -`)
returned a substantive review of ~12 KB. The reviewer noted that the
hetz sandbox blocks reading `/home/j2h4u` directly, so the review is
grounded in the embedded prompt context (PROJECT.md, CONTEXT, RESEARCH,
all three PLAN.md files) rather than fresh repo reads. The full text
follows.

### Overall Summary

The phase is well decomposed: Plan 01 establishes the contract and
ref-keyed local fusion, Plan 02 adds generic federated fan-out, and
Plan 03 proves Telegram end-to-end. The main risks are not conceptual,
but in boundary details: the MCP result shape does not yet expose the
full `SearchCandidate` contract, source identity is underspecified,
async fan-out may clash with the existing sync/threading model, and
Telegram `read(ref)` routing could bypass the active-binding gate for
already-indexed Telegram content.

### Plan 34-01: SearchCandidate Contract And Ref-Keyed Fusion

**Summary.** Strong foundation plan, but it needs tighter contract
fidelity. The `SearchCandidate` fields mostly match the requirements,
and the ref-keyed RRF migration is the right architectural move. The
biggest issue is that "source identity" is not fully represented:
`namespace` + `source_kind` is not the same as
"namespace + descriptor key".

**Strengths.**

- Clean break from `SearchResult` matches D-01 and avoids legacy shim drift.
- Ref-keyed fusion preserves rank-only RRF while preparing federated
  results to participate naturally.
- Pre-fusion provenance hydration is the right place to move
  chunk-to-ref resolution.
- Tests explicitly pin `extra="forbid"`, default `can_materialize=False`,
  and absence of `SearchResult`.
- `engine_scores` as diagnostics only is a good separation from public
  ranking semantics.

**Concerns.**

- **HIGH:** `SearchCandidate` lacks the descriptor key/source key
  required by SEARCH-02 and D-04. `namespace` + `source_kind` is not
  enough to distinguish multiple descriptors within a namespace or
  future bindings.
- **HIGH:** MCP `SearchHit` remains a subset of `SearchCandidate`.
  SEARCH-01 says `SearchCandidate` is the single public result type at
  service and MCP layers; the MCP surface should expose `can_read`,
  `can_materialize`, `source_native_score`, `source_native_rank`,
  title/source identity, etc., or directly serialize `SearchCandidate`.
- **MEDIUM:** `frozen=True` is shallow. `matched_engines: list`,
  `engine_scores: dict`, and `provider_metadata: dict` remain mutable
  after construction. The tests may overstate immutability.
- **MEDIUM:** Collapsing local hits by `ref` before fusion may merge
  multiple chunks from the same document/source unit. That is intended
  only if `ref` is truly the public unit identity. If local markdown
  refs are document-level rather than chunk/unit-level, snippet and
  chunk selection can become lossy.
- **LOW:** Task 1 says "all eight tests" but lists nine concrete tests.

**Suggestions.**

- Add `descriptor_key: str` or `source_key: str` to `SearchCandidate`;
  keep `source_kind` if useful, but do not substitute it for descriptor
  identity.
- Make MCP return a full `SearchCandidate`-equivalent model, not a
  reduced `SearchHit`, unless the plan explicitly narrows MCP and
  revises the success criteria.
- Either use immutable containers (`tuple`, read-only mappings) or
  remove claims/tests that imply deep immutability.
- Add a test for two local chunks mapping to the same `ref`, pinning
  which snippet/chunk metadata wins.
- Keep `SearchResult` residual scan acceptance simple: after Plan 01,
  zero references outside explicit removal tests.

**Risk Assessment.** **MEDIUM.** The direction is correct, but the
contract has two public-surface gaps: descriptor identity and MCP
shape. Fixing those now is cheap; discovering them in Plan 03 would
be disruptive.

### Plan 34-02: Federated Fan-out And Source Status

**Summary.** The generic fan-out design matches the phase goal,
especially soft-skip and rank-only RRF. However, the plan currently
blurs local engine outputs and federated candidate outputs under one
`EngineOutcome.candidates: list[SearchCandidate]`, which conflicts with
local engines still returning chunk-keyed tuples. The sync/async
bridge also needs a safer design.

**Strengths.**

- `SourceStatus` envelope directly implements D-11 and gives agents
  useful partial-result visibility.
- Soft timeout plus no fail-fast matches the user's chosen failure mode.
- Separate `FederatedSearchProviderProtocol` avoids bloating the
  Phase 28 provider surface.
- Lifecycle `supports_federated_search` property is a good
  capability-discovery boundary.
- Tests for raw provider scores not directly influencing rank are
  important and well chosen.

**Concerns.**

- **HIGH:** `EngineOutcome` is typed as `list[SearchCandidate]`, but
  Plan 02 says local outcomes are chunk-keyed ranked lists. This is a
  type and design mismatch. Local and federated outcomes need either
  separate payload types or a generic ranked-output abstraction.
- **HIGH:** Running existing local engines through `asyncio.to_thread`
  in parallel may break if they share SQLite connections, metadata
  stores, graph clients, or other non-thread-safe service state.
- **HIGH:** `DotMDService.search()` using `asyncio.run()` plus
  "schedule onto existing loop" is risky. A synchronous method cannot
  safely block on the currently running event loop in the same thread.
  This can deadlock or fail in FastAPI/MCP contexts.
- **HIGH:** Building all lifecycle bundles at service init can turn
  one misconfigured federated source into service startup failure.
  D-08 says search queries constructible sources; construction failures
  should be captured as skipped/error status, not necessarily crash
  service startup.
- **MEDIUM:** Applying the same `federated_timeout_seconds` to local
  engines can accidentally soft-skip semantic/graph work on cold or
  slow local calls. D-09 is about federated per-source timeout, not
  necessarily local engine deadlines.
- **MEDIUM:** `asyncio.wait_for(asyncio.to_thread(...))` does not
  cancel the underlying thread. A timed-out sync provider can keep
  running, consuming resources.
- **MEDIUM:** Existing `mode` semantics may be broken if every search
  always calls semantic, keyword, and graph engines regardless of
  caller-selected mode.
- **MEDIUM:** Plan 02 says to merge federated engine score attribution
  into candidates, but D-02 says federated candidates leave
  `engine_scores=None`.

**Suggestions.**

- Define two outcome shapes: `LocalEngineOutcome(name, ranked_chunks)`
  and `FederatedEngineOutcome(name, candidates)`, or make
  `EngineOutcome.payload` generic and typed by engine kind.
- Keep local search execution mostly as-is initially; run federated
  providers in parallel with the existing local pipeline rather than
  parallelizing all local internals unless thread-safety is proven.
- Prefer an explicit async service method, e.g.
  `async_search() -> SearchResponse`, and make sync `search()` only
  call it from non-event-loop contexts. MCP should call the async path
  directly.
- Catch lifecycle build failures and store unavailable source statuses,
  or defer provider construction until first fan-out with bounded
  error handling.
- Use separate timeouts: local engine status reporting can exist
  without enforcing the federated timeout.
- Keep `engine_scores=None` on federated candidates; provider rank/score
  belong in `source_native_rank` and `source_native_score`.

**Risk Assessment.** **HIGH.** The fan-out semantics are right, but
the implementation plan has concurrency and typing hazards that could
cause runtime failures even if unit tests pass.

### Plan 34-03: Telegram Federated Proof And Read/Drill Round-trip

**Summary.** This plan targets the right proof: Telegram native FTS
returns a public ref, then `read(ref)` and `drill(ref)` work without
local indexing. The main risk is overbroad Telegram ref routing:
routing every Telegram ref through the provider before local
active-binding checks can violate the Phase 27 visibility gate for
locally-backed Telegram content.

**Strengths.**

- Keeps dotMD behind the mcp-telegram daemon socket; no direct
  Telegram client ownership.
- Tests cover daemon request shape, candidate construction, provider
  errors, no materialization, and row-count stability.
- `search_native` producing `tg:fts` candidates is a clean proof of
  the generic provider interface.
- Documentation updates include the daemon socket contract and
  coordination state.
- Explicit static scans for Telethon/private SQLite access are good
  defense-in-depth.

**Concerns.**

- **HIGH:** `read()` / `drill()` dispatches all Telegram refs through
  provider before `_require_active_source_document`. That can bypass
  the active-binding gate for Telegram refs that are already locally
  indexed but inactive. The context explicitly says federated read
  must not bypass the gate for locally-backed candidates.
- **HIGH:** The plan assumes `search_messages` can be added to
  `UnixSocketTelegramSourceClient`, but live success depends on an
  out-of-repo daemon endpoint. This is identified, but Plan 03 is
  marked `autonomous: true`; that is misleading if live proof may
  require coordination.
- **MEDIUM:** `can_read=True` is hard-coded for Telegram search
  results. It should be derived from provider capability or unit
  support, even if Telegram always supports it today.
- **MEDIUM:** Provider error messages use raw `str(exc)`. Fine for
  localhost, but consider truncating or normalizing so socket
  paths/internal details do not leak into MCP responses unnecessarily.
- **MEDIUM:** `source_native_rank` is zero-based in tests. If this is
  public contract, decide explicitly whether rank is zero- or one-based
  and document it.
- **LOW:** `provider_metadata` should be checked not to include
  credentials, phone numbers, auth session paths, or other sensitive
  daemon internals.

**Suggestions.**

- Implement read/drill routing as: check whether the ref is locally
  backed and active first; use provider-only path only when no local
  active document/unit exists or when explicitly identified as
  federated-only.
- Change Plan 03 `autonomous` to conditional, or split daemon endpoint
  verification into a preflight task before implementation.
- Add `supports_read_unit_window(unit_type/ref)` or equivalent
  capability check before setting `can_read=True`.
- Document `source_native_rank` indexing convention.
- Add a test for an inactive locally-indexed Telegram ref to ensure
  provider fallback does not bypass the visibility gate.

**Risk Assessment.** **MEDIUM-HIGH.** The Telegram proof is well
scoped, but the active-binding bypass risk is serious because it cuts
across an established security/visibility invariant.

### Cross-Plan Suggestions (Codex)

- Treat the MCP response as canonical: return `SearchResponse`
  containing full `SearchCandidate` objects, not `SearchHit` subsets.
- Add `descriptor_key`/`source_key` before any tests are written, so
  all later fixtures use the final source identity shape.
- Split Plan 02 into "federated executor over provider candidates"
  and "local engine async refactor" only if local engine thread-safety
  is verified. Otherwise avoid parallelizing local engines.
- Add a preflight task before Plan 03: verify whether mcp-telegram
  daemon socket supports `search_messages`; update plan status based
  on that result.
- Add one integration test specifically for "locally-backed inactive
  Telegram ref must not be readable via federated provider fallback."

### Final Risk Assessment (Codex)

**Overall risk: MEDIUM-HIGH.** The architecture is sound and the phase
decomposition is mostly right, but there are a few contract and
concurrency flaws that should be corrected before execution. The
highest-priority fixes are: full MCP `SearchCandidate` envelope,
descriptor-key source identity, safer async/service boundary, distinct
local vs federated outcome types, and preserving active-binding checks
for locally-backed Telegram refs.

---

## Consensus Summary

Only one reviewer (codex) returned substantive content this cycle, so
"consensus" is degenerate. We do not infer agreement from opencode's
silence. Sections below reflect codex's findings only; cycle-3 with a
second working reviewer would be required for true cross-AI agreement.

### Agreed Strengths

Single reviewer; no cross-reviewer agreement to record. Codex
explicitly highlighted:

- Clean break from `SearchResult` (D-01 alignment, no shim drift).
- Ref-keyed RRF is the right architectural move for federated peers.
- `SourceStatus` envelope correctly implements D-11.
- Soft timeout + no fail-fast matches the chosen failure mode.
- Decision to keep dotMD behind the mcp-telegram daemon socket.
- `search_native` over the generic `FederatedSearchProviderProtocol`
  as the Telegram proof.

### Agreed Concerns (single-reviewer; treat as raised, not consensus-blocking)

1. **Source identity gap.** `SearchCandidate` lacks
   `descriptor_key`/`source_key`; `namespace` + `source_kind` is not
   sufficient for SEARCH-02 / D-04 (HIGH).
2. **MCP contract narrowing.** MCP `SearchHit` exposes a subset of
   `SearchCandidate`; SEARCH-01 implies full contract should be public
   (HIGH).
3. **Engine outcome typing mismatch.** `EngineOutcome.candidates:
   list[SearchCandidate]` collides with local chunk-keyed engine
   outputs in Plan 02 (HIGH).
4. **Local engine thread-safety unproven.** `asyncio.to_thread` over
   shared SQLite/graph clients risks corruption (HIGH).
5. **Sync→async bridge in `DotMDService.search()`.** `asyncio.run`
   from inside a running loop is unsafe in FastAPI/MCP contexts (HIGH).
6. **Eager lifecycle bundle construction.** Service startup fails if
   any federated source misconfigures; D-08 implies graceful skip
   (HIGH).
7. **Telegram active-binding bypass.** Routing all Telegram refs
   through provider before `_require_active_source_document` violates
   the Phase 27 visibility gate for locally-indexed inactive refs
   (HIGH).
8. **`autonomous: true` on Plan 03.** Live proof may require
   out-of-repo mcp-telegram daemon endpoint that does not yet exist;
   the autonomous flag misrepresents this dependency (HIGH).

### Divergent Views

Not applicable — only one reviewer produced substantive content.

---

## Reviewer Outcomes (Operational)

| Reviewer | Status      | Wall time     | Output bytes | Notes |
|----------|-------------|---------------|--------------|-------|
| opencode | empty-after-explore | ~7 min  | 96 (intro line only) | Default model `build · glm-5.1` via `opencode run -`. Spawned Explore Agents but never emitted final answer to stdout; exit 0. Different failure mode from Cycle 1's 32-min hang. |
| codex    | substantive | ~6 min        | 11789 | `ssh hetz sudo codex exec --skip-git-repo-check -`. Default model. Sandbox blocked direct repo read; review grounded in embedded prompt context. 8 HIGH, 9 MEDIUM, 2 LOW concerns. |

Cycle 2 produced 8 unresolved HIGH concerns, all newly raised by codex
this cycle (no prior HIGHs existed — Cycle 1 was no-signal). Per the
GSD review contract, this triggers a Cycle 2 → Cycle 3 replan loop:
the planner should fold codex's HIGHs into revised PLAN.md files and
the next cycle should validate convergence with at least one working
non-codex reviewer.

If a Cycle 3 is desired, options are:

- Re-run with `--codex --gemini` (or `--cursor`) to add a different
  model family and corroborate or challenge the codex HIGHs.
- Investigate the opencode build-mode Explore Agent → no-final-answer
  failure (consider `--quiet` mode or a smaller prompt) before
  re-including it.
- Treat codex's HIGHs as the cycle-2 deliverable and proceed to
  replan via `/gsd-plan-phase 34 --reviews`.

---

*Cycle 2 of cross-AI review for Phase 34. Plans remain as last
committed pending replan. 8 HIGH concerns surfaced — replan recommended
before Cycle 3.*
