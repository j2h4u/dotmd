---
phase: 26
review_cycle: 3
replan_commit: 171e6b6
reviewers: [opencode, claude]
requested_reviewers: [opencode, claude]
unavailable_reviewers: []
reviewed_at: 2026-05-06T16:04:07+05:00
plans_reviewed:
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-01-core-ref-model-and-service-resolution-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-02-mcp-api-cli-ref-contract-PLAN.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-regression-docs-and-live-smoke-PLAN.md
---

# Cross-AI Plan Review - Phase 26

## Reviewer Availability

- OpenCode: invoked successfully via `/home/j2h4u/.opencode/bin/opencode run --dir /home/j2h4u/repos/j2h4u/dotmd -` after exporting `PATH=/home/j2h4u/.opencode/bin:$PATH`.
- Claude: invoked successfully via `claude -p -`.

## OpenCode Review

OpenCode inspected the current plans and relevant implementation files before reviewing.

CYCLE_SUMMARY: current_high=3

## Current HIGH Concerns

- **HIGH-1 (Plan 01 Task 2): Multi-provenance canonical ref selection has a data correctness gap.** The plan requires `get_chunk_provenance_for_chunk_ids()` to use `ORDER BY chunk_id, namespace, document_ref` and first-wins logic. The current implementation orders only by `chunk_id` and uses dict last-wins semantics. The plan identifies the need, but the acceptance criteria should verify SQL ordering and use a test where the lexicographic first provenance row is not the database's original row order.
- **HIGH-2 (Plan 01 Task 2): Missing provenance as a hard `ValueError` may be production-breaking with no migration safety net.** The plan mandates a hard error for chunks lacking provenance. The count query is a good gate, but the plan does not make the backfill mandatory when count is nonzero. A deploy-then-discover path could make production search fail for any result set containing a legacy chunk.
- **HIGH-3 (Plan 01 Task 3): `read(ref)` resolution chain is under-specified for the `strategy` parameter.** Existing file-range helpers are keyed by strategy. The plan resolves a source document and calls existing helpers, but does not say whether `read(ref)` is single-strategy-only or how it discovers strategies for a source document.

### Plan 01: Core Ref Model and Service Resolution

**Summary:** Plan 01 targets the right domain-layer changes: replacing public `SearchResult.file_paths` with `ref`, hydrating refs from Phase 25 provenance, and adding `read(ref)` / `drill(ref)` service behavior. The wave sequencing and TDD approach are sound, but OpenCode found three HIGH issues around canonical provenance selection, missing-provenance rollout safety, and strategy handling in `read(ref)`.

**Strengths:**
- Correctly identifies `build_search_results()` as the hydration point.
- Uses Phase 25 provenance tables rather than falling back to holder paths.
- Preserves internal holder mechanics while changing the public contract.
- Includes a missing-provenance count query before merge.

**Concerns:**
- **HIGH:** Multi-provenance canonical ref selection must be verified at the SQL ordering level, not only by Python first-wins logic.
- **HIGH:** Missing-provenance backfill must be a mandatory branch of Task 2 when the audit count is nonzero.
- **HIGH:** `read(ref)` must either state it is single-strategy-only or define strategy discovery for source documents.
- **MEDIUM:** `_ChunkProvenanceBatchStore` replacement versus coexistence with `_FilePathsBatchStore` is not explicit.
- **MEDIUM:** Service access to `SQLiteMetadataStore.get_source_document()` should be spelled out.
- **MEDIUM:** `drill(ref)` returning `source_uri` may expose a filesystem-looking field after the public contract becomes source-ref-first.

**Suggestions:**
- Add acceptance criteria for the actual SQL `ORDER BY chunk_id, namespace, document_ref`.
- Define the scoped provenance backfill as mandatory if the audit query finds gaps.
- Specify strategy behavior for `read(ref)`: either current configured strategy only, with an explicit comment, or a strategy-discovery helper.

### Plan 02: MCP/API/CLI Ref Contract

**Summary:** Plan 02 correctly targets MCP, FastAPI, CLI, and e2e smoke surfaces. The error hint, `drill` addition, and search shape changes are directionally right, but OpenCode found several MEDIUM issues in API/test coverage and cross-wave breakage.

**Strengths:**
- Recognizes that no `drill` tool exists yet and that `EXPECTED_TOOLS` must become `{"search", "read", "drill", "feedback"}`.
- Defines the invalid-ref action hint: `Action: pass a ref returned by search.`
- Includes malformed and nonexistent ref smoke cases.
- Uses an `rg` discovery step for FastAPI routes.

**Concerns:**
- **MEDIUM:** FastAPI `GET /search` exists and serializes `SearchResult` objects, so its response shape must be updated explicitly.
- **MEDIUM:** CLI acceptance criteria do not match the current f-string shape for the `+N more` holder display.
- **MEDIUM:** `backend/tests/cli/test_search_output.py` constructs `SearchResult(file_paths=...)`; if Plan 01 removes the field before Plan 02 runs, tests can fail between waves.
- **LOW:** `OPTIONAL_SEARCH_RESULT_FIELDS` should be handled alongside `REQUIRED_SEARCH_RESULT_FIELDS`.

**Suggestions:**
- Add an explicit FastAPI `/search` assertion that `file_paths` is absent and `ref` is present.
- Move CLI fixture updates that depend on the `SearchResult` constructor into Plan 01, or make Plan 02's dependency handling explicit.

### Plan 03: Regression, Documentation, and Live Smoke

**Summary:** Plan 03 is a solid cleanup and verification wave. The doc grep gates, batched restart, live MCP smoke, and deferred-scope audit are appropriate.

**Strengths:**
- Keeps the source-mounted container restart batched to one restart.
- Adds doc grep gates for public contract cleanup.
- Uses live MCP smoke against the running container.
- Lists deferred scope explicitly.

**Concerns:**
- **MEDIUM:** `just typecheck` target existence/equivalence is assumed.
- **MEDIUM:** The plan does not state a recovery path if live smoke fails after the one restart.
- **LOW:** `test_mcp_smoke.py` may already be changed by Plan 02, so Plan 03 should mainly verify it.

**Suggestions:**
- Add a minimal rollback/recovery note for failed live smoke.
- Confirm `just typecheck` is the intended typecheck gate.

### OpenCode Overall Risk Assessment

**Risk Level: MEDIUM.**

The plan wave structure is sound, the no-full-reindex constraint is respected, and internal holder mechanics are correctly preserved. The main blockers are operational and correctness-oriented: mandatory provenance gap handling, SQL-level deterministic canonical provenance selection, and explicit strategy behavior for `read(ref)`.

## Claude Review

# Phase 26 Plan Review - Convergence Cycle 3

## Plan 01: Core Ref Model and Service Resolution

**Summary.** Solid TDD plan that swaps `SearchResult.file_paths` for `ref`, derives public refs from Phase 25 provenance, and gates against missing provenance with a count query. The no-reindex answer is explicit and well-justified. Multi-holder canonical selection is deterministic. Internal holder mechanics are preserved.

**Strengths.**
- Explicit no-full-reindex declaration and supporting evidence.
- Missing-provenance treated as an invariant rather than a silent holder-path fallback.
- First-wins lexicographic canonical ref is pinned in acceptance criteria.
- Pre-merge SQL count gate stops the plan if Phase 25 left orphan chunks.
- `chunk_file_paths_<strategy>` stays internal.

**Concerns.**
- **MEDIUM:** Pre-merge SQL has literal `<strategy>` placeholder. The executor must substitute real table suffixes and account for multi-strategy storage.
- **MEDIUM:** Drill graph-entity enrichment is vague and may invite scope creep or inconsistent behavior.
- **MEDIUM:** Acceptance criteria require literal warning text `frontmatter parse failed`, which is brittle.
- **MEDIUM:** A filesystem ref with a `source_documents` row but missing file on disk raises `Unknown source ref`, conflating unknown refs with missing files.
- **LOW:** `_parse_ref` should document the first-colon split assumption.

**Suggestions.**
- Derive active provenance tables from `sqlite_master` instead of using a literal `<strategy>` placeholder.
- Either implement drill entity enrichment deterministically through a named helper or defer it cleanly.
- Prefer stable warning categories or exception types over exact log-message text.

**Risk:** **MEDIUM.**

## Plan 02: MCP/API/CLI Ref Contract

**Summary.** Updates MCP `SearchHit` / `ReadResult`, adds `drill(ref)`, rewrites instructions, and updates CLI/API surfaces and e2e smoke. Discovery for FastAPI routes is good. Invalid-ref behavior is specified, but the MCP error-wrapping layer is not pinned.

**Strengths.**
- Hard-pins the expected MCP tool set and required search result fields.
- Enumerates FastAPI surface before changing it.
- Removes holder display from CLI output rather than hiding it cosmetically.
- Covers malformed and nonexistent refs in smoke tests.

**Concerns.**
- **HIGH:** **MCP error-wrapping layer is unspecified.** Plan 02 task 3 requires live smoke to observe a tool-level error containing both `Unknown source ref` and `Action: pass a ref returned by search.`. Plan 01 has `DotMDService.read()` raise only `ValueError("Unknown source ref ...")`. Nothing pins where the action hint is appended or where service `ValueError` is caught and converted to a tool-level MCP error rather than a protocol-level error.
- **MEDIUM:** New `drill` behavior for unsupported namespaces or refs with missing frontmatter is not specified.
- **MEDIUM:** FastAPI route changes are not backed by an assertion test if a search/read route exists.
- **LOW:** `heading` becomes optional but should remain allowed in the public shape.

**Suggestions.**
- Add Plan 02 task 1 acceptance criteria that `mcp_server.py` contains `Action: pass a ref returned by search.` and wraps service `ValueError` as MCP tool-level errors.
- Specify unsupported-namespace behavior for `drill`, mirroring `read`.
- Add a tiny FastAPI assertion if the `/search` route exists.

**Risk:** **MEDIUM-HIGH** because the live smoke depends on this error conversion contract.

## Plan 03: Regression, Documentation, and Live Smoke

**Summary.** Closes the phase with focused regression, doc grep gates, batched restart live smoke, and final summary. Doc gates exclude allowed internal-holder mentions.

**Strengths.**
- Single batched `docker restart dotmd`.
- Practical doc grep gates for public contract cleanup.
- Final summary includes deferred-scope audit.
- Self-check gating is tied to all required commands passing.

**Concerns.**
- **MEDIUM:** Live smoke assumes the repo bind mount path and that `pytest` is installed in the production container.
- **MEDIUM:** Doc grep must return only explicitly allowed internal-holder hits, but the exception list is not mechanical.
- **LOW:** `just typecheck` target is assumed.

**Suggestions.**
- Add a precheck: `docker exec dotmd python -c "import pytest, sys; print(sys.executable)"`.
- Replace judgment-based doc grep review with a mechanical exception list.

**Risk:** **MEDIUM.**

## Claude Cross-Plan Risk Assessment

**Overall: MEDIUM.**

The plan set is well-decomposed, threat-modeled, and gated. The no-reindex constraint is honored end-to-end. Internal holder mechanics are explicitly preserved. Deferred scope is correctly fenced.

The one HIGH found by Claude is the MCP error-wrapping contract: the live smoke depends on both `Unknown source ref` and `Action: pass a ref returned by search.` appearing in a tool-level error, but no plan acceptance criterion pins the wrapper behavior.

CYCLE_SUMMARY: current_high=1

## Current HIGH Concerns

- **MCP error-wrapping contract is unspecified** (Plan 02 task 1 / Plan 02 task 3 / Plan 03 task 3): The live MCP smoke requires tool-level errors containing both `Unknown source ref` and `Action: pass a ref returned by search.`, but Plan 01's service layer raises only `Unknown source ref` and no acceptance criterion forces `mcp_server.py` to catch service `ValueError`, decorate the message, and surface an MCP tool-level error.

---

## Consensus Summary

This cycle successfully exercised both requested reviewers after adding `/home/j2h4u/.opencode/bin` to `PATH`. OpenCode and Claude both judged the overall plan structure as sound and medium-risk, but OpenCode raised three HIGH concerns and Claude raised one distinct HIGH concern. None are resolved in this cycle because this workflow only reviewed the current plan artifacts.

### Agreed Strengths

- The phase is correctly scoped around source-ref-first search/read/drill behavior.
- The no-full-reindex constraint is preserved by deriving refs from Phase 25 provenance rather than rebuilding the index.
- Internal holder mechanics remain explicitly internal and are not rewritten in this phase.
- The plan sequence of core model/service changes, public API updates, and regression/live smoke is broadly sound.

### Agreed Concerns

- Missing-provenance handling needs a stronger execution gate. OpenCode treats the absence of a mandatory backfill path as HIGH; Claude treats related multi-strategy audit mechanics as MEDIUM.
- Public API and smoke verification need sharper mechanical acceptance criteria.
- Live smoke/error handling must be specified precisely enough to distinguish MCP tool-level errors from protocol-level failures.

### Divergent Views

- OpenCode treats SQL-level canonical provenance ordering, missing-provenance rollout safety, and read strategy handling as HIGH. Claude did not classify those as HIGH, but did note adjacent multi-strategy and verification brittleness risks.
- Claude treats MCP error wrapping as HIGH. OpenCode mentioned the action hint positively but did not elevate MCP error conversion to HIGH.

### Current HIGH Count For Convergence

The unresolved HIGH count for this review cycle is the union of distinct unresolved HIGH concerns raised by the reviewers:

1. Multi-provenance canonical ref selection must be verified at the SQL ordering level.
2. Missing-provenance hard errors need a mandatory migration/backfill safety net before deployment.
3. `read(ref)` strategy handling is under-specified.
4. MCP error-wrapping and action-hint behavior are under-specified.

CYCLE_SUMMARY: current_high=4

## Current HIGH Concerns

- Multi-provenance canonical ref selection must be verified at the SQL ordering level, including `ORDER BY chunk_id, namespace, document_ref` and a reverse-insertion or otherwise adversarial fixture.
- Missing-provenance hard errors need a mandatory migration/backfill safety net when the audit count is nonzero, before deployment can enable the invariant.
- `read(ref)` strategy handling is under-specified; the plan must define single-strategy behavior explicitly or add strategy discovery for source documents.
- MCP error-wrapping and action-hint behavior are under-specified; the plan must pin where service `ValueError`s become tool-level MCP errors containing `Action: pass a ref returned by search.`.
