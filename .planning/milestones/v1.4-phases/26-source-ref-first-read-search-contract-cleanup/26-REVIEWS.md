---
phase: 26
review_cycle: 4
replan_commit: ff94f31
reviewers: [opencode, claude]
requested_reviewers: [opencode, claude]
unavailable_reviewers: []
reviewed_at: 2026-05-06T16:18:01+05:00
plans_reviewed:
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-01-core-ref-model-and-service-resolution-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-02-mcp-api-cli-ref-contract-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-regression-docs-and-live-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 26

## Reviewer Availability

- OpenCode: invoked successfully via `/home/j2h4u/.opencode/bin/opencode run --dir /home/j2h4u/repos/j2h4u/dotmd -` after exporting `PATH=/home/j2h4u/.opencode/bin:$PATH`.
- Claude: invoked successfully via `claude -p -` after exporting `PATH=/home/j2h4u/.opencode/bin:$PATH` for the run environment.

## OpenCode Review

## Plan Review: Phase 26 — Cycle 4

### Summary

All three plans are well-structured with clear task boundaries, concrete acceptance criteria, and proper wave dependencies. The four HIGH concerns from cycle 3 have been directly addressed with specific SQL ordering, a mandatory backfill safety gate with dry-run/count semantics, explicit single-strategy read scoping, and a pinned MCP error-wrapping location with action hints. The no-full-reindex constraint is respected throughout. This is a clean, executable plan set.

### Strengths

- **Adversarial multi-provenance test** (Plan 01 Task 2): reverse-insertion fixture verifying SQL ORDER BY + first-wins dict logic, not SQLite insertion order — directly addresses the canonical selection ambiguity.
- **Mandatory provenance safety gate** (Plan 01 verification): count → dry-run → write → re-count sequence blocks deployment if backfill can't reach zero, with explicit stop-and-report behavior.
- **Active-strategy-only scoping** (Plan 01 Task 3): explicit `self._settings.chunk_strategy` usage, clear error for zero-chunk sources, and a code comment marking future discovery as out of scope.
- **MCP error boundary** (Plan 02 Task 1): wrapper lives in `mcp_server.py`, not `DotMDService`; ValueError → RuntimeError with Action hint, unexpected exceptions → generic failure. Both unit and e2e tests assert tool-level errors, not JSON-RPC protocol errors.
- **Acceptance criteria are concrete and grep-able** across all three plans — reduces ambiguity for autonomous execution.
- **Wave dependency is correct**: Plan 02 depends on Plan 01's domain model changes; Plan 03 depends on both being complete.

### Concerns

- **Backfill `document_ref` resolution** (Plan 01 Task 2) — **LOW**: The backfill helper says `document_ref=file_path` from `chunk_file_paths_<strategy>`. If holder paths were ever stored non-resolved (relative), the generated ref would not match `str(Path(file_path).resolve())` from `SourceDocument` validation. In practice the pipeline resolves paths at index time so this should be fine, but a single `resolve()` call in the backfill SQL or helper would make this bulletproof.
- **Protocol abstraction for provenance store** (Plan 01 Task 2) — **LOW**: Adding a `_ChunkProvenanceBatchStore` Protocol in `fusion.py` when `MetadataStore` already has the method is marginal YAGNI. A direct dependency on the concrete store is simpler and sufficient for Phase 26 scope. The executor can omit the Protocol if it adds no test value.
- **`drill` return shape `title` provenance** (Plan 01 Task 3) — **LOW**: The `drill` payload includes `title` but the context doesn't specify where it's sourced from (frontmatter key? filename stem?). The executor will need to pick a derivation. Not blocking, but worth a one-line note in the acceptance criteria.
- **No explicit migration for pre-Phase-25 data** (Plan 01 Task 2) — **LOW**: The plan assumes Phase 25 shipped provenance for all indexed chunks. If any chunks were indexed before Phase 25 and never re-indexed, the count/backfill gate handles it. This is correct, but the plan could note this as the expected recovery path rather than leaving it implicit.

### Suggestions

1. In the backfill helper, add `Path(file_path).resolve()` to ensure generated `document_ref` matches `SourceDocument` validation, even if holder paths are somehow non-canonical. One line of defense.
2. Drop the `_ChunkProvenanceBatchStore` Protocol unless the executor finds a test-mocking reason to keep it. Direct calls to `MetadataStore` are simpler.
3. Add a one-line note in Plan 01 Task 3 about where `title` is derived (e.g., "from frontmatter `title` key, falling back to filename stem"). This prevents the executor from inventing a complex derivation.
4. Plan 03 Task 3 could note that the `docker restart` also restarts the trickle indexer, which holds the fcntl lock. This is fine for a smoke, but worth recording so the executor doesn't try to run `dotmd index` commands concurrently.

### Risk Assessment: **LOW**

All four previous HIGHs are fully resolved with concrete, testable specifications. The remaining concerns are LOW-severity implementation details that the executor can handle autonomously. The no-full-reindex constraint is well-protected by the provenance safety gate and the explicit verification commands.

---

## Recheck of Previous Cycle HIGHs

### HIGH 1: Multi-provenance canonical ref selection
**Status: FULLY RESOLVED.** Plan 01 Task 2 specifies `ORDER BY chunk_id, namespace, document_ref`, first-wins dict population (`if chunk_id not in result`), and an adversarial test inserting `filesystem:/mnt/b.md` before `filesystem:/mnt/a.md` asserting canonical selection of `/mnt/a.md`. Acceptance criteria include both the SQL clause and the reverse-insertion test.

### HIGH 2: Missing-provenance hard errors with backfill safety net
**Status: FULLY RESOLVED.** Plan 01 Task 2 defines `count_missing_source_provenance()` with a concrete SQL query, `backfill_missing_source_provenance_from_file_paths()` with dry-run/write modes and idempotent `INSERT OR IGNORE`, full test coverage (count=1, dry-run, write, second-write=0, final count=0), and a mandatory verification gate that stops deployment if backfill can't reach zero.

### HIGH 3: read(ref) strategy handling
**Status: FULLY RESOLVED.** Plan 01 Task 3 explicitly scopes `read(ref)` as active-strategy-only using `self._settings.chunk_strategy`, raises `ValueError("No chunks for source ref in active strategy")` when empty, and includes a code comment marking strategy discovery as future work. Acceptance criteria verify all three elements.

### HIGH 4: MCP error-wrapping and action-hint behavior
**Status: FULLY RESOLVED.** Plan 02 Task 1 pins the wrapper in `mcp_server.py` (not `DotMDService`), specifies ValueError → RuntimeError with `Action: pass a ref returned by search.` at warning level, unexpected exceptions → generic failure at error level. Unit tests assert both error paths. E2e smoke (Plan 02 Task 3, Plan 03 Task 3) asserts tool-level errors for invalid/malformed refs on both `read` and `drill`.

---

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns
None.

---

## Claude Review

<sef-eval phase="USER-PROMPT">
<task>cross-AI plan review for dotMD Phase 26 — assess whether 4 prior HIGH concerns are resolved in convergence cycle 4</task>
<skills>none — listed skills are for the dotMD developer's GSD workflow (gsd-plan-review-convergence orchestrates the loop, gsd-review requests reviews); no skill targets the external reviewer role this prompt assigns me</skills>
<decision>proceed</decision>
</sef-eval>

# Cross-AI Plan Review — Phase 26, Cycle 4

## Summary

The replan at ff94f31 closes all four previously unresolved HIGH concerns with concrete, gripable acceptance criteria. The canonical-ref selection now mandates `ORDER BY chunk_id, namespace, document_ref` plus first-wins dict population and an adversarial reverse-insertion fixture; the missing-provenance hard error is gated behind a mandatory dry-run-first idempotent backfill helper with deployment evidence captured in 26-03-SUMMARY.md; `read(ref)` is explicitly pinned to `self._settings.chunk_strategy` with a code comment naming Phase 26 as the constraint and a clear `No chunks for source ref in active strategy` error; and MCP error wrapping is pinned to `mcp_server.py` (not the service), differentiating `ValueError` (warning + tool-level error with `Action: pass a ref returned by search.`) from unexpected exceptions, with the e2e smoke required to observe tool-level errors rather than JSON-RPC protocol errors. The plans remain incremental, derive refs from existing Phase 25 provenance, and explicitly document no-full-reindex throughout.

## Strengths

- Adversarial dedup test pins both **SQL ordering** and **first-wins dict population** — the fixture inserts `b.md` before `a.md` and asserts `a.md` wins, defeating accidental insertion-order reliance.
- Backfill helper has a tight, concrete SQL specification (LEFT JOIN count query, `INSERT OR IGNORE`, lexicographically-first holder path), is idempotent and resumable, and the verification gate explicitly forbids deployment until the post-backfill count is `0`.
- Strategy decision is documented in three places: explicit `read(ref)` action ("active-strategy-only"), code comment ("Phase 26 read(ref) is active-strategy-only; future source adapters may add explicit strategy discovery."), and SUMMARY entry — making the deferred surface unambiguous.
- MCP error wrapper location pinned to `mcp_server.py` not `DotMDService`, keeping domain errors clean and conversion at the boundary; e2e smoke explicitly asserts tool-level error payloads with `isError`/tool error content semantics, not protocol-level errors.
- Both error contract directions (malformed `not-a-ref` and resolved-but-missing `filesystem:/nonexistent/file.md`) are tested, and both `read` and `drill` are tested for the wrapper behavior.
- Phase boundary is explicit and consistent across all three plans: graph `File` rewrite, holder-table replacement, source-unit emission, Telegram adapter, and pretty `title` labels are all called out as deferred, blocking inadvertent scope creep.
- The "no full reindex" constraint is enforced both as plan acceptance criteria and as an audit line in 26-03-SUMMARY.md ("dotmd index --force was not run").

## Concerns

- **MEDIUM — Plan 03 Task 1 acceptance criterion permits literal `<active_strategy>` placeholder.** Plan 01's verification explicitly forbids leaving the placeholder ("do not leave a literal `<strategy>` placeholder in commands or summaries"), but Plan 03 Task 1 accepts either `chunks_<active_strategy>` *or* the real table name. A strict executor would still substitute the real name, but the looser gate could pass a summary that documents the placeholder verbatim. Tighten Plan 03 Task 1 acceptance to require the real `chunks_<suffix>` name only.
- **MEDIUM — `payload["ref"]` checks presence on a single result, not all results.** Plan 02 Task 1's MCP test acceptance criteria are presence-string greps (`payload["ref"]`, `assert "file_paths" not in payload`). A test that indexes only `payload[0]` would still satisfy the grep. Consider adding `all("ref" in r for r in results)` or equivalent in the acceptance criteria.
- **MEDIUM — backfill helper's parser-metadata copy path is unspecified for the no-source-document case.** Plan 01 Task 2 says "parser metadata copied from the matching `source_documents` row when available". If `source_documents` has no row for the discovered filesystem path either, the helper presumably defaults to filesystem semantics — but the plan does not name the default. Worth one sentence describing the default `parser_name` / `document_type` fallback to keep the helper deterministic.
- **LOW — `drill(ref)` graph/entity enrichment is conditionally optional ("if existing helper is cheap and stable; failures must be non-fatal").** This is fine as a Phase 26 boundary decision, but means the `DrillResult` shape on production may or may not include entities, depending on what the executor finds. The contract should pick one and stick to it; recommend explicitly excluding entities in Phase 26 and deferring to a future enrichment plan to keep the shape stable.
- **LOW — e2e smoke runs `tests/e2e/` (the entire directory) rather than the specific smoke file.** If any other e2e test exists or is added later, it implicitly becomes part of the gate. Acceptable but worth narrowing to `tests/e2e/test_mcp_smoke.py` for predictability.
- **LOW — Plan 03 Task 2 docs grep gate is judgmental.** `rg "file_paths|file_path\b" docs/ backend/src/dotmd/mcp_server.py` returning hits requires manual inspection to confirm each is "explicit internal-holder wording". An allowlist of phrases (e.g., "internal holder", "Chunk.file_paths is internal") would make the gate mechanical.

## Suggestions

- Tighten Plan 03 Task 1 acceptance to forbid the `<active_strategy>` literal and require the real chunk-strategy suffix that the executor used.
- Add an explicit "all results carry `ref`" assertion to Plan 02 Task 1 acceptance, e.g., a contains-check for `for hit in results` plus `"ref" in hit`.
- Specify the backfill helper's default parser metadata when `source_documents` has no matching row (suggest `parser_name='filesystem'`, `document_type='markdown'` or whatever the existing filesystem source emits at ingestion).
- Decide whether `drill(ref)` includes entities in Phase 26; if not, lock the `DrillResult` schema to the seven fields enumerated in Plan 01 Task 3 and defer entity enrichment.
- Narrow Plan 03 Task 3's pytest target from `tests/e2e/` to `tests/e2e/test_mcp_smoke.py`, or document why directory-wide is intentional.

## Risk Assessment

**Overall: LOW.** The plans are tightly specified, dependency-ordered (Wave 1 → 2 → 3), preserve internal holder mechanics, and prove their public-contract change through both adversarial unit fixtures and a live MCP smoke against the running container. The remaining concerns are MEDIUM/LOW polish on acceptance-criteria precision, not load-bearing design gaps. No-full-reindex is structurally enforced (refs are derived from Phase 25 tables; backfill scope is metadata rows only). The breaking change is acceptable per the project context (no external consumers) and is gated behind a deployment-blocking provenance count of `0`.

## Previous Cycle HIGHs Recheck

1. **Multi-provenance canonical ref selection (SQL ordering + adversarial fixture)** — **FULLY RESOLVED.** Plan 01 Task 2 mandates `ORDER BY chunk_id, namespace, document_ref` + first-wins population; reverse-insertion fixture (`b.md` before `a.md` → expect `a.md`) is in acceptance criteria.
2. **Missing-provenance hard errors need migration/backfill safety net** — **FULLY RESOLVED.** `count_missing_source_provenance(strategy)` and `backfill_missing_source_provenance_from_file_paths(strategy, dry_run=True)` are specified with concrete SQL, idempotency via `INSERT OR IGNORE`, dry-run-first contract, and a deployment-blocking gate in Plan 01 verification + Plan 03 Task 1 summary requirement.
3. **read(ref) strategy handling under-specified** — **FULLY RESOLVED.** Plan 01 Task 3 explicitly pins to `self._settings.chunk_strategy`, raises `No chunks for source ref in active strategy` when empty, and embeds a code comment naming Phase 26 as the active-strategy-only boundary.
4. **MCP error wrapping and action-hint behavior under-specified** — **FULLY RESOLVED.** Wrapper is pinned to `mcp_server.py` (Plan 02 Task 1), splits `ValueError` (warning + tool-level error with `Action: pass a ref returned by search.`) from unexpected exceptions, and the e2e smoke (Plan 02 Task 3 + Plan 03 Task 3) explicitly asserts tool-level error payloads rather than JSON-RPC protocol errors for both `read` and `drill`, both malformed and missing refs.

CYCLE_SUMMARY: current_high=0
## Current HIGH Concerns
None.

---

## Consensus Summary

Both requested reviewers completed successfully against the replan commit `ff94f31`. They independently agree that all four HIGH concerns from the previous cycle are now fully resolved by concrete plan changes and verification criteria. The current unresolved HIGH count is therefore 0.

### Agreed Strengths

- The canonical multi-provenance ref rule is now pinned through SQL ordering, first-wins population, and an adversarial reverse-insertion fixture.
- Missing provenance is now guarded by count, dry-run backfill, write backfill, and final zero-count evidence before deployment enables hard failures.
- `read(ref)` strategy behavior is explicitly active-strategy-only for Phase 26, with future strategy discovery deferred instead of left ambiguous.
- MCP `ValueError` conversion is pinned to `mcp_server.py`, with tool-level error behavior and the exact action hint covered by unit and live smoke expectations.
- The no-full-reindex constraint is preserved across the phase and must be recorded in the implementation summary.

### Agreed Concerns

- No unresolved HIGH concerns remain.
- Remaining reviewer concerns are implementation-polish issues around acceptance-criteria precision, deterministic defaults, optional `drill` enrichment scope, and making grep gates more mechanical.

### Divergent Views

- OpenCode rates the residual issues as LOW and considers the plan ready to execute.
- Claude rates several precision issues as MEDIUM, especially the loose `<active_strategy>` acceptance wording, all-result `ref` assertions, and default parser metadata for backfill when `source_documents` has no matching row. These do not change the HIGH count but are useful execution notes.

### Current HIGH Count For Convergence

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns
None.
