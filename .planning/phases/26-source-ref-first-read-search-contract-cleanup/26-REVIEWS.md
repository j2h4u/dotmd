---
phase: 26
reviewers: [claude]
requested_reviewers: [opencode, claude]
unavailable_reviewers: [opencode]
reviewed_at: 2026-05-06T15:40:45+05:00
plans_reviewed:
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-01-core-ref-model-and-service-resolution-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-02-mcp-api-cli-ref-contract-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-regression-docs-and-live-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 26

## Reviewer Availability

- Claude: invoked successfully via `claude -p -`.
- OpenCode: requested but unavailable in this environment; `command -v opencode` returned missing, so no OpenCode review was produced.

## Claude Review

I'll review the three Phase 26 plans against the goal of removing the Phase 25 filesystem-path-first compatibility layer without requiring a full reindex.

## Review

### Summary

The three-plan decomposition (domain/service -> public surfaces -> regression/docs/smoke) is sound and correctly aligned with the Phase 26 goal. The reindex constraint (D-17, D-18) is honored - refs are derived from existing `source_documents` and `chunk_source_provenance_<strategy>` rows, no embeddings/FTS/graph rebuild. Acceptance criteria are concrete and grep-checkable, and the deferred-scope audit (graph `File`, `chunk_file_paths_*` holder tables, Telegram, pretty labels) matches the phase boundary. The main risks are unresolved behavioral ambiguities at error/edge boundaries - particularly missing-provenance handling - and a few weakly specified verification gates.

### Strengths

- **Reindex avoidance is structural, not just stated.** Plan 01 hydrates from existing provenance tables; no plan touches vectors, FTS5, or graph data. The summary in Plan 03 explicitly audits this.
- **Wave ordering is correct.** Plan 01 lands `DotMDService.drill(ref)` and `read(ref)` before Plan 02 wires MCP tools that call them. Plan 03 only verifies after both ship.
- **Acceptance criteria are mostly verifiable.** Concrete `rg`/pytest invocations with required strings make automated checking feasible.
- **Internal vs public boundary is preserved correctly.** `Chunk.file_paths` and `chunk_file_paths_<strategy>` stay as internal holder mechanics (D-13), avoiding scope creep into a storage rewrite (D-14).
- **Live smoke in Plan 03 task 3 matches the agent reality.** Running `tests/e2e/` inside the container after a single batched restart reflects "our agents are the consumer," not abstract local mocks.
- **Error guidance is user-facing.** "Action: pass a ref returned by search." gives breaking-change recovery instructions.

### Concerns

#### HIGH: Missing-provenance behavior is ambiguous (Plan 01, task 2)

The action says missing provenance handling is *"preferred: skip the chunk and log a warning... acceptable alternative: raise a ValueError"*. These two behaviors produce materially different system contracts:

- **Skip+warn**: search results silently shrink from N->M; agents see incomplete results with no signal at the API surface.
- **Raise**: a single bad row breaks search entirely.

Phase 25 was supposed to populate provenance for every chunk, so this should be an invariant ("invariant by construction" per recorded user feedback) - `raise` is the right choice. Either way, the plan must lock this down before execution. Leaving it as a coin flip means Plan 03's regression tests cannot deterministically pin the contract.

#### HIGH: Invalid-ref smoke behavior is also left open (Plan 02, task 3)

> "Pin whichever behavior implementation chooses."

The smoke test is the contract. Letting implementation choose means the smoke can't be a regression gate - it just records whatever happened. Lock this: `read(ref="filesystem:/nonexistent/file.md")` should return a tool-level error (not a protocol error) with `Unknown source ref` (matching Plan 01 task 3's error string).

#### HIGH: Multi-holder chunk semantics are not specified (Plan 01, task 2)

Content-addressed dedup means one `chunk_id` can be referenced by multiple files (`chunk_file_paths_<strategy>` is M2M for exactly this reason). Provenance is one row per chunk, so the public `ref` is unique - but this means a chunk physically present in 3 files surfaces as ref to only ONE of them. The plan should:

- explicitly state this is intentional (single canonical source per chunk),
- add a test that proves a deduped chunk returns the canonical provenance ref, not a holder-path ref,
- decide what "canonical" means when the same content was indexed from multiple sources (e.g., earliest-indexed wins).

Without this, real corpus search may surface refs that don't match the file the agent expects.

#### MEDIUM: FastAPI scope is undefined (Plan 02, task 2)

The plan says *"If routes exist, their response/input shape must use `ref`"* but does not enumerate the routes. Per AGENTS.md, the deployed entrypoint is MCP-only (streamable-http on 8080); FastAPI may exist but be unused in production. The plan should either:

- list the actual `@router` decorations in `api/server.py`, or
- explicitly mark FastAPI as out-of-scope-if-unmounted with a confirming `rg` check.

Otherwise this task is "go look and decide what to do" - not a plan.

#### MEDIUM: Live smoke execution model is underspecified (Plan 03, task 3)

`docker exec dotmd sh -c "cd /mnt/.../backend && python -m pytest tests/e2e/"` - does this:

(a) connect to the running MCP server inside the container (the streamable-http process), or
(b) spawn a fresh MCP subprocess via stdio inside the container?

These test entirely different things. (a) requires the bind-mounted code to have been reloaded by the running process - which it hasn't, because Python doesn't reload. So a restart is *always* needed before (a) can work, not "if needed." If (b), the smoke doesn't validate that the running production process serves the new contract. Plan 03 should pick one and justify it.

#### MEDIUM: Doc grep gates are brittle (Plan 03, task 2)

The patterns:
```bash
rg "read\(file_path|Only pass file_paths|Returns ranked hits with source `file_paths`"
```
will miss many variants: `read(file_path=...)`, `file_paths field`, `result.file_paths`, prose like "the file_paths array", etc. A stronger gate: `rg "file_paths|file_path\b" docs/` with an explicit allow-list for files documenting internal holder mechanics. Otherwise stale public-contract docs can survive.

#### MEDIUM: `drill(ref)` performance/safety not specified (Plan 01, task 3)

`drill` reads frontmatter from `SourceDocument.file_path` on each call. What happens if:

- the file was deleted but the source_documents row remains (delete detection runs in trickle, may lag)?
- the file is large or the directory is on slow storage?
- frontmatter parsing fails?

The plan says graph/entity enrichment failure must be non-fatal - it should extend the same to frontmatter failure (return `frontmatter: {}` with a warning) and missing-file (raise `Unknown source ref` to match the resolver behavior, since the SourceDocument exists but its target is gone).

#### MEDIUM: No fallback path for legacy chunks indexed pre-Phase-25 (Plan 01)

Research says Phase 25 shipped provenance, but were existing v1.3-era chunks backfilled? If not, the missing-provenance branch is the *normal* case for older data, not exceptional. Plan should include a one-shot count query in Plan 01 verification:
```sql
SELECT COUNT(*) FROM chunk_metadata_<strategy> c
LEFT JOIN chunk_source_provenance_<strategy> p ON c.chunk_id = p.chunk_id
WHERE p.chunk_id IS NULL;
```
If this returns >0, the missing-provenance handler is hot path, not an edge case, and the lightweight backfill mentioned in D-20 may actually be required.

#### LOW: SearchHit field exclusivity not asserted negatively in MCP test (Plan 02, task 1)

Acceptance criteria assert `payload["ref"]` exists but don't assert `"file_paths" not in payload`. Easy to add and locks down D-03/D-04 against accidental field carryover.

#### LOW: Plan 03 task 1 runs only focused tests, not full suite

The risk is that ref-first changes ripple into unrelated tests (anything that touches `SearchResult` construction, fixtures, or `read()`). Suggest adding `cd backend && uv run pytest -q --ignore=tests/e2e` as a sanity check before declaring `Self-Check: PASSED`.

#### LOW: `chunk_file_paths_<strategy>` rename/comment deferral could leak

The plan defers any rename of this table but expects future readers to know it's now internal-only. A single-line comment or docstring update in `storage/metadata.py` flagging "internal dedup holder; not the public read identity, see Phase 26" is cheap insurance against the next refactor reintroducing path-first behavior.

### Suggestions

1. **Lock missing-provenance behavior to `raise ValueError("missing source provenance for chunk_id=...")`** in Plan 01 task 2. Pair with a count-check verification before merging Plan 01 to confirm zero rows lack provenance in the production index.
2. **Pin invalid-ref smoke** in Plan 02 task 3 to: `read(ref="filesystem:/nonexistent/file.md")` -> tool error containing `Unknown source ref`. Same for malformed refs (`read(ref="not-a-ref")`).
3. **Enumerate FastAPI scope** in Plan 02 task 2 by listing `api/server.py` route decorators, then either updating them or explicitly marking out-of-scope.
4. **Specify the live smoke execution model** in Plan 03 task 3: state explicitly whether the e2e tests connect to the running streamable-http MCP server (requires restart-then-test) or spawn stdio subprocesses (no restart needed). Match `.mcp.json` semantics.
5. **Add a multi-holder/dedup test** to Plan 01 task 2 that indexes the same content from two filesystem paths and asserts search returns the canonical provenance ref.
6. **Add a negative MCP assertion** to Plan 02 task 1: `assert "file_paths" not in payload and "file_path" not in payload`.
7. **Add a single internal-holder docstring** in `storage/metadata.py` near `chunk_file_paths_<strategy>` clarifying it is an internal dedup holder and not the public read identity, citing Phase 26.
8. **Strengthen doc grep gate** in Plan 03 task 2 to `rg "file_paths|file_path\b" docs/` with an allow-list, not a 3-pattern union.
9. **Add `pyright`/full-suite sanity** to Plan 03 task 1 verification before `Self-Check: PASSED`.

### Risk Assessment

**Overall: MEDIUM**

The architectural decisions are correct and the reindex constraint is structurally honored. Wave ordering and dependency tracking are clean. However, three behavioral contracts are left underspecified (missing-provenance handling, invalid-ref behavior, multi-holder semantics), and one verification gate (live smoke execution model) is ambiguous. None of these block the phase, but each can produce a contract that drifts from intent or a regression test that doesn't actually regress. Tightening these in the plans (rather than discovering them in execution) avoids replans.

The phase boundary itself is solid - no creep into Telegram, graph rewrite, or holder-table replacement - and the deferred-scope audit in Plan 03 task 4 keeps that boundary explicit.

CYCLE_SUMMARY: current_high=3

## Current HIGH Concerns

- Plan 01 task 2: missing-provenance behavior is left as either-or (skip+warn vs raise); must be locked to one before execution so Plan 03 can pin it as a regression gate.
- Plan 02 task 3: invalid/nonexistent-ref smoke behavior says "pin whichever behavior implementation chooses" - the smoke is the contract and must specify the expected tool error and message.
- Plan 01 task 2: multi-holder/deduped chunk semantics are not specified - the public `ref` is one source per chunk, but the canonical-source rule and a covering test are missing, risking surprising production results.

---

## Consensus Summary

Only one requested external reviewer produced output because OpenCode is not installed in this environment. The synthesized consensus therefore mirrors the Claude review rather than claiming multi-reviewer agreement.

### Agreed Strengths

- The phase split is coherent: service/domain changes land before public MCP/API/CLI contract changes, with regression/docs/smoke last.
- The plans preserve the hard no-full-reindex constraint by deriving refs from Phase 25 provenance tables instead of touching embeddings, FTS5, or graph rebuild paths.
- The scope boundary is mostly disciplined: Telegram, source-unit emission, graph rewrite, and holder-table replacement stay deferred.

### Agreed Concerns

- Missing-provenance behavior must be deterministic before execution; the current skip-versus-raise choice changes the public search contract.
- Invalid or nonexistent ref handling must be pinned as an expected tool-level error rather than captured after implementation.
- Multi-holder/dedup semantics need an explicit canonical-source rule and regression coverage.

### Divergent Views

- No divergent reviewer views were available. OpenCode could not be invoked because `opencode` was missing from `PATH`.

CYCLE_SUMMARY: current_high=3

## Current HIGH Concerns

- Plan 01 task 2: missing-provenance behavior is left as either-or (skip+warn vs raise); must be locked to one before execution so Plan 03 can pin it as a regression gate.
- Plan 02 task 3: invalid/nonexistent-ref smoke behavior says "pin whichever behavior implementation chooses" - the smoke is the contract and must specify the expected tool error and message.
- Plan 01 task 2: multi-holder/deduped chunk semantics are not specified - the public `ref` is one source per chunk, but the canonical-source rule and a covering test are missing, risking surprising production results.
