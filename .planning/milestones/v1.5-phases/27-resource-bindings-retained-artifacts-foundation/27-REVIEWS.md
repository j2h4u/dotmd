---
phase: 27
reviewers: [claude, opencode]
reviewed_at: 2026-05-07T18:15:39+05:00
cycle: 2
plans_reviewed:
  - 27-01-storage-binding-state-PLAN.md
  - 27-02-filesystem-unbind-and-rebind-PLAN.md
  - 27-03-public-active-filtering-PLAN.md
  - 27-04-regression-docs-and-verification-PLAN.md
---

# Cross-AI Plan Review - Phase 27 Cycle 2

## Consensus Summary

Both requested reviewers agreed that the replan in commit `57bfe39` addresses the 10 HIGH concerns from cycle 1. Claude found no unresolved HIGH concerns and classified the remaining issues as MEDIUM/LOW wiring, observability, and edge-case-test refinements. OpenCode also found no unresolved HIGH concerns and classified remaining issues as MEDIUM/LOW implementation clarity or diagnostics.

### Agreed Strengths

- Backfill is now explicit, idempotent, and runs before binding-aware operations.
- Successful filesystem indexing now has a symmetric active binding upsert path.
- Deactivation is separated from purge/delete helpers, preserving retained artifacts.
- Rebind acceptance is behaviorally pinned to zero TEI encoding calls for unchanged retained chunk text.
- Public active filtering now happens before reranking and before filesystem fallback paths.
- Verification now includes end-to-end lifecycle coverage, shared-chunk visibility, TEI call-count evidence, and EXPLAIN evidence.

### Agreed Concerns

- MEDIUM: Rebind implementation needs precise attention during execution. Claude wanted the exact insertion point before chunking/embedding pinned more explicitly; OpenCode wanted the M2M/provenance "preserve or re-add" wording tightened.
- MEDIUM: Active filtering is acceptable but has quality/observability edge cases. Claude noted extreme inactive skew can still underfill; OpenCode noted inactive candidates still influence RRF scores before filtering.
- LOW/MEDIUM: Additional diagnostics would strengthen execution: EXPLAIN for the fingerprint rebind lookup, warm-start backfill behavior, and clearer documentation of intentional metadata-fingerprint behavior.

### Divergent Views

- Claude treated the rebind lookup index and warm-start backfill test as MEDIUM improvements; OpenCode considered the current acceptance criteria sufficient and did not raise those above LOW/unstated.
- OpenCode suggested dropping `source_unit_refs` as premature schema, while Claude did not flag it as a concern.

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.

---

## Claude Review

<sef-eval phase="USER-PROMPT">
<task>Cross-AI plan review - Phase 27 cycle 2 replanned plans, count unresolved HIGH concerns from prior cycle's 10</task>
<skills>none - this is direct review work, no available skill matches "cross-AI plan review counting"; gsd-review is the orchestrator that spawned this, not a sub-skill to invoke recursively</skills>
<decision>proceed</decision>
</sef-eval>

# Phase 27 Plan Review - Cycle 2

## Summary

The replan substantively addresses all 10 HIGH concerns from cycle 1 with concrete tasks, named helpers, and verifiable acceptance criteria. Plan 01 adds the missing backfill and pins fingerprint ownership/source-of-truth rules. Plan 02 adds the symmetric binding-upsert-on-index, splits deactivation cleanly from `_holder_aware_chunk_cleanup`, hardens rebind acceptance to "TEI encode call count == 0", and explicitly covers the trickle path and modified-file lifecycle. Plan 03 replaces the brittle `top_k * 3` over-fetch with a named `ACTIVE_FILTER_OVERFETCH_FACTOR = 5` plus a `top_k + 50` floor and underfill warning, and routes `_require_active_source_document` ahead of the Phase 26 filesystem fallback. Plan 04 adds the end-to-end lifecycle test, shared-chunk visibility test, EXPLAIN-plan evidence, and TEI-count evidence in the summary. The plans now read as a turnkey execution package rather than a research artifact.

## Strengths

- **Backfill is explicit and idempotent.** Plan 01 Task 2 reads from `source_documents`, uses `INSERT ... ON CONFLICT(namespace, resource_ref) DO NOTHING`, and tests both first-run creation and second-run idempotence plus inactive-row preservation.
- **Source-of-truth rule is documented and tested.** Plan 01 Task 1 truths block names `source_documents` as authoritative; Plan 03 Task 3 asserts `metadata_json` is not duplicated.
- **Symmetric binding lifecycle.** Plan 02 Task 1 upserts active bindings on every successful index path (incremental, metadata-only, trickle), matching Task 2's deactivation path.
- **Hard separation of deactivation from purge.** Plan 02 Task 2 explicitly forbids `_holder_aware_chunk_cleanup` and `delete_chunk_provenance_for_document` calls in `_deactivate_filesystem_binding`, with grep-style assertions.
- **Rebind reuse is behaviorally pinned.** "TEI encoding call count equals 0" replaces the OR-escape clause from cycle 1.
- **Modified-file lifecycle is named.** Plan 02 Task 1 distinguishes modified (replacement + fingerprint update) from missing (deactivation); Task 2 acceptance asserts modified files do NOT call `_deactivate_filesystem_binding`.
- **Filesystem fallback bypass is closed.** Plan 03 Task 2 places `_require_active_source_document` before synthetic `SourceDocument` reconstruction and `Path.exists()`; tests cover the inactive-binding-with-present-file scenario explicitly.
- **Filter-before-rerank ordering.** Plan 03 Task 1 ensures the cross-encoder only sees active candidates, addressing OpenCode's reranker-pool waste concern from cycle 1.
- **Verification evidence is concrete.** Plan 04 Task 2 requires `EXPLAIN QUERY PLAN`, `TEI encode call count`, pytest tail lines, and `no dotmd index --force` literally in the summary.
- **Shared-chunk M2M case is now covered** (Plan 04 Task 1) - closes OpenCode's missing edge case from cycle 1.

## Concerns

### MEDIUM - Rebind fingerprint-discovery flow is named but not fully wired in the pipeline

**Severity: MEDIUM**

Plan 02 Task 3 says "When a filesystem document is discovered and an inactive binding exists with the same namespace, content_fingerprint, and metadata_fingerprint", but doesn't specify where in `_index_file()` / `index_file()` / `_incremental_index()` this lookup is inserted. The lookup must happen *after* fingerprint computation but *before* chunking/embedding for reuse to work. As written, a planner could compute fingerprints, chunk and embed, and then "reactivate" - defeating the purpose. The acceptance criterion ("TEI encode call count == 0") catches this behaviorally, but the wiring location is implicit.

### MEDIUM - Over-fetch policy is improved but still bounded; no iterative refetch fallback

**Severity: MEDIUM**

`active_pool_size = max(pool_size, top_k * 5, top_k + 50)` is a real improvement over `top_k * 3`. The `+50` floor handles small `top_k` cases, and the underfill warning makes the failure mode observable. However, under extreme inactive skew (e.g., bulk move/rename of the corpus), even the cushion can be exhausted. The plan accepts this consciously (warn, don't loop) but doesn't document the corpus-state assumption. Worth a docstring noting "expected inactive ratio < ~80% in steady state; bulk-move events trigger the underfill warning by design."

### MEDIUM - `idx_resource_bindings_fingerprints` exists but rebind query path is not exercised

**Severity: MEDIUM**

Plan 01 Task 1 adds `idx_resource_bindings_fingerprints` on `(namespace, content_fingerprint, metadata_fingerprint, active)`. Plan 02 Task 3 implies but does not require an EXPLAIN QUERY PLAN check that the rebind lookup actually uses this index. Plan 04 Task 1 only asserts the EXPLAIN check for `idx_resource_bindings_document_active`. With ~13,500 documents and rebind events potentially common during filesystem reorganizations, a missed index could silently degrade rebind from O(log n) to O(n).

### LOW - `chunk_file_paths_<strategy>` rebind semantics are still "preserve or re-add"

**Severity: LOW**

Plan 02 Task 3 says "preserve or re-add M2M chunk_file_paths_<strategy> holder rows for the restored filesystem path". Since holder rows are preserved on deactivation (Task 2), and resource_ref equals the absolute path, on rebind to the same path the rows already exist. On rebind to a new path with matching content fingerprint, new holder rows are needed. This is decidable but the OR-clause leaves it implicit; a test like "rebind same content to a different path adds new holder rows for the new path" would lock this in.

### LOW - Migration test for live database is implicit

**Severity: LOW**

Plan 01 Task 2 tests backfill via in-memory fixtures with manually-inserted `SourceDocument` rows. There's no test that simulates "real index DB with N existing documents, restart, backfill produces N active bindings, search/read still works." The end-to-end test in Plan 04 Task 1 starts from empty state. A "warm-start" test that pre-populates `source_documents` (without bindings), runs `__init__`, and asserts search/read continues to function would prove the deployment-break risk is fully closed. The acceptance criteria are sufficient to catch it in code review, but a behavioral test is stronger.

### LOW - `bound_at` source for backfill defaults to `updated_at` or "now"

**Severity: LOW**

Plan 01 Task 2: `bound_at = source_documents.updated_at if present, otherwise current UTC timestamp`. This is fine, but `updated_at` may not exist on older `source_documents` rows depending on schema history. A defensive fallback chain (`updated_at` -> `created_at` -> `now`) would be more robust. Not a correctness issue, just a clean-data concern for diagnostics.

### LOW - `Self-Check: PASSED` gate in Plan 04 has soft escape for typecheck/lint

**Severity: LOW**

Plan 04 Task 2 says "documented pre-existing ratchet status" allows `Self-Check: PASSED` even on lint/typecheck failures. This was added per OpenCode's cycle-1 suggestion and is reasonable, but it's a softer gate than "all checks green." Worth requiring the summary to enumerate the specific pre-existing failures by file/line so a future reviewer can verify nothing new was introduced.

## Suggestions

1. **Plan 02 Task 3:** Pin the rebind-lookup insertion point in the pipeline. One explicit sentence: "In `_index_file()`, after computing `content_fingerprint` and `metadata_fingerprint` and before invoking the chunker, query `resource_bindings` for an inactive match; on hit, reactivate and skip the chunk/embed path."
2. **Plan 04 Task 1:** Add an EXPLAIN QUERY PLAN assertion for the rebind lookup using `idx_resource_bindings_fingerprints`, parallel to the existing one for `idx_resource_bindings_document_active`.
3. **Plan 04 Task 1:** Add a "warm-start" backfill behavioral test - pre-populate `source_documents` without bindings, instantiate `SQLiteMetadataStore`, assert search/read works post-init.
4. **Plan 02 Task 3:** Add a focused test "rebind same content fingerprint to a different filesystem path" to lock M2M holder semantics.
5. **Plan 03 Task 1:** Add a one-line code comment near `ACTIVE_FILTER_OVERFETCH_FACTOR` documenting the corpus-state assumption ("steady-state inactive ratio < ~80%; bulk-move events trigger underfill warnings by design").
6. **Plan 04 Task 2:** Require ratcheted lint/typecheck failures to be enumerated by file in the summary, not just acknowledged.

## Risk Assessment

**Overall risk: LOW-MEDIUM** - substantial improvement from cycle 1's MEDIUM-HIGH / HIGH split.

Justification:
- All 10 cycle-1 HIGH concerns have concrete mitigations with grep-checkable acceptance criteria.
- The two structural risks (backfill gap, binding-creation symmetry) that would have caused production-breakage on first restart are closed by Plan 01 Task 2 and Plan 02 Task 1.
- The behavioral softness in cycle 1 (rebind OR-escape, fixed over-fetch, filesystem fallback bypass) is now hardened with assertable invariants.
- Remaining concerns are MEDIUM at most and are about wiring clarity, observability, and edge-case test coverage - not deployment risks. They can be addressed inline during execution without replanning.
- The plans correctly preserve the no-full-reindex guardrail and stay within phase scope (no Telegram, no GC, no recycle bin).

The plans are executable as written. The MEDIUM concerns above are worth addressing during execution (especially the rebind lookup wiring and the rebind-index EXPLAIN check), but none rise to "block execution and replan again."

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.

---

## OpenCode Review

# Cross-AI Plan Review - Phase 27 Cycle 2

## Consensus Summary

All 10 HIGH concerns from Cycle 1 have been addressed in the replanned Phase 27 plans. The plans now form a coherent, execution-ready package: Plan 01 includes explicit backfill and source-of-truth rules, Plan 02 adds the symmetric binding-upsert writer and a separate deactivation path, Plan 03 filters before reranking and gates filesystem fallback, and Plan 04 requires end-to-end lifecycle and shared-chunk edge-case tests. No new HIGH concerns were identified.

---

## Plan 27-01: Storage Binding State

### Summary

Solid storage foundation that correctly addresses the three Cycle 1 HIGHs (backfill, fingerprint producer, source-of-truth). The source-of-truth documentation between `source_documents` and `resource_bindings` is now explicit and testable.

### Strengths

- **Task 2 backfill** is idempotent (`ON CONFLICT DO NOTHING`), transaction-scoped, and runs in `__init__` before any pipeline operation can touch bindings. This eliminates the deployment-break risk.
- **Source-of-truth rule** is explicit: `source_documents` owns current metadata; `resource_bindings` holds activity state plus fingerprint snapshots for rebind lookup. `metadata_json` is binding-lifecycle-only (`{"deactivation_reason": "file_missing"}`).
- **Task 3** adds an `EXPLAIN QUERY PLAN` assertion for `idx_resource_bindings_document_active`, locking in the index path early.
- Deterministic canonical selection (`ORDER BY chunk_id, namespace, document_ref`) preserved from Phase 26.

### Concerns

- **MEDIUM - `source_unit_refs` column is premature.** Filesystem bindings always have empty source_unit_refs. Per YAGNI, add when Phase 28 needs it. Minor schema bloat but not harmful.
- **LOW - `ref` is derivable.** `ref == f"{namespace}:{document_ref}"` is stored but computable. A generated column would prevent drift, but the upsert helper constructs it consistently, so the risk is low.

### Suggestions

- Drop `source_unit_refs` from the initial schema and add it in Phase 28 when Telegram source units are modeled.
- Consider making `ref` a SQLite `GENERATED ALWAYS AS` column to eliminate any drift possibility.

---

## Plan 27-02: Filesystem Unbind and Rebind

### Summary

The core behavioral change plan now correctly addresses all five Cycle 1 HIGHs (binding creation, rebind acceptance, modified files, trickle coverage, deactivation path). The three-task decomposition is well-ordered: upsert -> deactivation -> rebind.

### Strengths

- **Task 1** adds the missing symmetric writer - every successful index upserts an active binding with current fingerprints. Trickle `index_file()` is explicitly covered.
- **Modified-file rule** is explicit: replacement reindex semantics preserved, fingerprints updated after successful reindex, no deactivation. Task 2 acceptance criteria test this.
- **Task 2** creates a completely separate deactivation path (`_deactivate_filesystem_binding`) that explicitly does NOT call `_holder_aware_chunk_cleanup`, `delete_chunk_provenance_for_document`, or graph delete helpers. The hard purge remains available via `_purge_file` for replacement/GC contexts.
- **Task 3 rebind** has a hard acceptance criterion: "TEI encoding call count equals 0 for unchanged retained chunk text" - no OR-escape hatch.
- Trickle coverage in Task 3 covers restored-file reactivation, modified-file fingerprint update, and disappeared-file no-op.

### Concerns

- **MEDIUM - Rebind sequence "preserve or re-add" is slightly ambiguous for M2M rows.** Task 3 step 4 says "preserve or re-add M2M chunk_file_paths rows" and step 5 says "preserve or re-add chunk_source_provenance rows." The "or" leaves implementation choice, but the acceptance criteria are concrete enough (rows must exist after restore) that either behavior passes. Consider pre-committing to "preserve" since chunks are content-addressed and already present.
- **LOW - Rebind discovery depends on fingerprint match across both content AND metadata fingerprints.** If metadata fingerprint changes (e.g., frontmatter edit without content change), rebind won't fire even though chunks are identical. This is correct behavior per D-07 but should be documented as an intentional design choice.

### Suggestions

- Pre-commit to "preserve" for M2M/provenance rows on rebind (since chunks are content-addressed and unchanged), removing the "or re-add" ambiguity.
- Add a brief comment in the rebind path explaining that both fingerprints must match, and metadata-only changes intentionally trigger re-processing.

---

## Plan 27-03: Public Active Filtering

### Summary

The service-level filtering plan now correctly addresses the two Cycle 1 HIGHs (over-fetch brittleness, filesystem fallback bypass). The over-fetch is no longer a fixed multiplier and active-binding checks happen before all fallback paths.

### Strengths

- **`ACTIVE_FILTER_OVERFETCH_FACTOR = 5`** with `max(pool_size, top_k * 5, top_k + 50)` is significantly more robust than the previous fixed `top_k * 3`. The floor of `top_k + 50` handles small top_k values.
- **Filtering before reranking** eliminates wasted cross-encoder computation on inactive candidates.
- **Underfill logging** (`active filter underfilled` with counts) makes the edge case observable without silent quality degradation.
- **Task 2** explicitly requires active-binding check before `_resolve_source_document()` synthetic fallback, `_filesystem_path_for_source()` `Path.exists()`, frontmatter reads, and chunk reads. The acceptance criteria include the critical bypass test: inactive binding + present file -> `ValueError`.
- **Task 2** also covers the case where no `source_documents` row exists but the file is on disk - the missing/inactive binding must prevent synthetic fallback.

### Concerns

- **MEDIUM - RRF fusion scores are still computed on mixed active+inactive candidates.** Inactive chunks influence RRF cohort scores before the filter removes them. This is a known quality limitation, not a correctness issue (inactive results never reach the user). The underfill log makes it observable. Worth a brief code comment.
- **LOW - Graph-direct may return fewer candidates than the over-fetch target.** Graph traversal is inherently bounded by graph structure. The `top_k + 50` floor and underfill log handle this acceptably.

### Suggestions

- Add a code comment in the fusion path noting that RRF scores include inactive candidates and that the filter runs post-fusion, pre-rerank.
- Consider adding a per-engine inactive-ratio metric to the underfill log for debugging.

---

## Plan 27-04: Regression, Docs, and Verification

### Summary

Comprehensive verification plan that closes the Cycle 1 gaps (end-to-end lifecycle test, shared-chunk edge case, TEI call count evidence, EXPLAIN evidence, typecheck/lint ratchet status).

### Strengths

- **Task 1** requires an explicit 11-step end-to-end filesystem lifecycle test (index -> search -> read -> deactivate -> search hidden -> read rejected -> rebind -> search -> read -> TEI count 0). This is the D-16 acceptance criterion made concrete.
- **Shared-chunk test** explicitly covers: A and B share a chunk, deactivate A, B's ref still visible via active provenance. This was a missing edge case in Cycle 1.
- **Task 2** requires recording TEI encode call count evidence, EXPLAIN QUERY PLAN evidence, and pytest pass lines verbatim in the summary.
- **Task 3** docs scope is tight: Phase 27 foundation only, Telegram deferred, GC deferred. Grep checks for `include_inactive` and `recycle-bin` language prevent scope creep.

### Concerns

- **LOW - No latency regression check.** With a per-search active-binding join, a quick wall-clock comparison before/after would be valuable. Not required for correctness but useful for production confidence.

### Suggestions

- Consider adding a rough latency sanity check (e.g., search time on a fixture with 100+ documents should not increase by more than 2x).

---

## Cross-Plan Assessment

### Resolved Cycle 1 HIGH Concerns

| # | Original Concern | Resolution Location |
|---|---|---|
| 1 | Missing backfill | Plan 01 Task 2: `backfill_resource_bindings_from_source_documents()` in `__init__` |
| 2 | Undefined fingerprint producer | Plan 01 source-of-truth rule + backfill from `source_documents` columns |
| 3 | Missing binding upsert on index | Plan 02 Task 1: explicit upsert in successful index path |
| 4 | Soft rebind acceptance | Plan 02 Task 3: hard `TEI encode call count == 0` |
| 5 | Modified files underspecified | Plan 02 Task 1 explicit modified-file rule + Task 2 test |
| 6 | Fixed over-fetch starvation | Plan 03 Task 1: `ACTIVE_FILTER_OVERFETCH_FACTOR = 5` + `top_k + 50` floor + underfill log |
| 7 | Source-of-truth duplication | Plan 01 explicit documentation + test |
| 8 | Trickle coverage gap | Plan 02 Task 1 + Task 3 trickle acceptance criteria |
| 9 | Deactivation reuses purge primitive | Plan 02 Task 2: separate path, explicit prohibition list |
| 10 | Filesystem fallback bypass | Plan 03 Task 2: active check before all fallback paths + bypass test |

### New Concerns

No new HIGH concerns identified. Remaining MEDIUM/LOW concerns are implementation details that the acceptance criteria and test coverage already constrain sufficiently.

---

## Risk Assessment

**Overall risk: MEDIUM-LOW**

The architectural direction is sound and all deployment-break risks from Cycle 1 have been addressed with specific, testable mitigations. The backfill runs at init before any pipeline operation, binding upsert is paired with deactivation, the active filter gates all public paths before filesystem fallback, and rebind must prove zero recomputation. The remaining risks are quality-edge concerns (RRF score influence from inactive candidates, rebind M2M semantics ambiguity) that do not affect correctness and are observable through logging and diagnostics.

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns

None.
