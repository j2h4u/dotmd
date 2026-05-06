---
phase: 26
review_cycle: 2
replan_commit: 7e094fc
reviewers: [claude]
requested_reviewers: [opencode, claude]
unavailable_reviewers: [opencode]
reviewed_at: 2026-05-06T15:50:27+05:00
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

# Phase 26 Plan Review - Convergence Cycle 2

## Summary

The replan commit `7e094fc` substantively resolves all three HIGH concerns from cycle 1. Missing-provenance is locked to a hard `ValueError` (no skip-and-warn fallback), the invalid-ref smoke pins exact tool-level error text in both Plan 02 acceptance criteria and Plan 03 evidence, and the multi-holder canonical-source rule is now `ORDER BY chunk_id, namespace, document_ref` first-wins with concrete `filesystem:/mnt/a.md` vs `filesystem:/mnt/b.md` test fixtures. The plans hold the no-full-reindex constraint and stay disciplined within the source-ref-first cleanup boundary; deferred items (Telegram, graph rewrite, holder-table replacement) are explicitly listed for the phase audit.

## Strengths

- **Determinism upgrades**: `missing source provenance for chunk_id=` is both raised in code (Plan 01) and asserted as a regression gate (Plan 03 task 4). Same for the canonical-ref rule and the `Action: pass a ref returned by search.` error suffix.
- **No-full-reindex audit is now first-class**: Plan 01 verification adds an explicit count query for chunks lacking provenance, with a stop-before-merge gate if count > 0. Plan 03 task 4 records the result.
- **Single batched container restart**: Plan 03 task 3 explicitly limits to one `docker restart dotmd` after all implementation, respecting the `feedback_no_prod_restarts.md` memory.
- **Clean break, no compat shims**: No `display_path`/`source_uri`/path-fallback hedging in public search hits - D-03 is enforced by acceptance grep.
- **FastAPI escape clause**: Plan 02 task 2 enumerates routes via `rg` and records "no read/search routes" as a valid finding rather than inventing API surface.

## Concerns

### MEDIUM

1. **Path-with-colon edge case lacks test coverage.** Threat model lists "ref parsing mishandles filesystem paths containing colons" with mitigation "split only on the first colon," but neither Plan 01 task 1 nor task 3 acceptance criteria require a test for `filesystem:/mnt/foo:bar.md` resolving to `("filesystem", "/mnt/foo:bar.md")`. Real voicenote/transcript filenames sometimes contain colons (timestamps, "Title: Subtitle" exports). Add an acceptance criterion: a `_parse_ref` test or `SearchResult.ref` validation test asserting first-colon-only split for a path containing additional colons.

2. **Audit of all `SearchResult.file_paths`/`SearchHit.file_paths` consumers is implicit, not explicit.** Plan 01 only lists `test_fusion.py` and `test_search_result_shape.py`; Plan 03 task 1 catches stragglers via the full non-e2e pytest run, but there's no upfront `rg "SearchResult\(.*file_paths|\.file_paths" backend/` audit. If, say, `test_pipeline_metadata.py` or any ingestion test constructs `SearchResult(file_paths=...)` for fixtures, the failure surfaces only at Plan 03. Recommend adding the audit `rg` to Plan 01 task 1 read_first or as a pre-task step.

3. **`get_chunk_provenance_for_chunk_ids()` semantics change isn't sized for existing callers.** Plan 01 task 2 changes the helper to first-wins canonical dedup. If any existing caller relied on receiving every `(chunk_id, namespace, document_ref)` row (e.g., for invariant checks or holder reconciliation), this silently drops data. Recommend a one-line `rg "get_chunk_provenance_for_chunk_ids"` in read_first to confirm callers, or explicitly state in Plan 01 acceptance that the helper is currently called only from search hydration.

4. **Trickle activity during `docker restart dotmd` is not addressed.** Phase memory notes trickle uses fcntl exclusive lock and runs continuously. A restart mid-indexing could leave a stale lock or partial transaction. Plan 03 task 3 doesn't suggest checking `docker logs dotmd` for in-flight indexing before the restart, or mention WAL/lock recovery on first start. Minor since SQLite WAL handles crashes, but worth a one-line guard ("verify no active indexing run before restart").

### LOW

5. **`drill(ref)` entity enrichment was promised but quietly dropped.** Phase context D-09 says `drill(ref) -> frontmatter/entities/chunk_count`. Plan 01 task 3 makes entities optional and Plan 02 task 1 omits them from `DrillResult`. This is a defensible scope reduction (graph internals shouldn't block contract), but the deferred-scope audit in Plan 03 task 4 doesn't list "entity enrichment in drill" as deferred. Add it to the deferred audit or note the scope reduction.

6. **Container internal path `/mnt/home/repos/j2h4u/dotmd/backend` is unverified.** Plan 03 task 3 hardcodes this path inside `docker exec`. AGENTS.md confirms `DOTMD_DATA_DIR=/mnt` is locked, but the bind-mount layout for the source code is implicit. Worth confirming during execution rather than at smoke-test time.

7. **Plan 03 task 1 mixes two test commands but only checks `Self-Check: PASSED` once.** The acceptance "`Self-Check: PASSED` if all required commands pass" is a conditional in the criterion; in practice executors sometimes record PASSED on the first command and skip the second. Recommend separate evidence lines per command.

## Suggestions

- Add this acceptance criterion to Plan 01 task 1 or task 3: `_parse_ref("filesystem:/mnt/foo:bar.md")` returns `("filesystem", "/mnt/foo:bar.md")` covered by a unit test.
- Add to Plan 01 task 2 read_first: `rg -n "get_chunk_provenance_for_chunk_ids" backend/src` to confirm the helper signature change is safe.
- Add to Plan 03 task 3 action: "verify `docker logs dotmd --tail 50` shows no active indexing run before restart; if active, wait for current run to drain."
- Add to Plan 03 task 4 deferred-scope list: "drill graph/entity enrichment remains deferred; current `drill(ref)` returns metadata only."

## Risk Assessment

**LOW**.

Justification: All cycle 1 HIGHs are resolved with concrete, gate-checkable behavior. The remaining concerns are MEDIUM/LOW edge-case test coverage, refactor-safety audits, and operational guardrails - none block the public-contract change or invite full reindex. The plans correctly derive `ref` from existing Phase 25 provenance tables, leave holder mechanics intact, and stage the breaking change behind a single batched container restart.

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.

---

## Consensus Summary

Only one requested external reviewer produced output because OpenCode is not installed in this environment. The synthesized consensus therefore mirrors the Claude review rather than claiming multi-reviewer agreement.

### Agreed Strengths

- The cycle 1 HIGH concerns are resolved in the current plans with deterministic, testable behavior.
- The no-full-reindex constraint is preserved through source ref derivation from Phase 25 provenance.
- The breaking public contract remains scoped to source-ref-first search/read/drill behavior, with holder tables and Telegram deferred.

### Agreed Concerns

- No HIGH concerns remain unresolved.
- Medium-priority polish remains around first-colon ref parsing tests, explicit `file_paths` consumer audits, helper caller sizing, and restart guardrails.

### Divergent Views

- No divergent reviewer views were available. OpenCode could not be invoked because `opencode` was missing from `PATH`.

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.
