---
phase: 27
reviewers: [claude, opencode]
reviewed_at: 2026-05-07T17:57:00+05:00
plans_reviewed:
  - 27-01-storage-binding-state-PLAN.md
  - 27-02-filesystem-unbind-and-rebind-PLAN.md
  - 27-03-public-active-filtering-PLAN.md
  - 27-04-regression-docs-and-verification-PLAN.md
current_high: 10
---

# Cross-AI Plan Review - Phase 27

## Review Invocation

- Command requested: `Skill(skill="gsd-review", args="--phase 27 --opencode --claude")`
- Reviewer set preserved: Claude and OpenCode.
- OpenCode executable used: `/home/j2h4u/.opencode/bin/opencode` because it was installed outside `PATH`.
- OpenCode model config note: `.planning/config.json` contains `review.models.opencode = "opencode run"`, which is a command string rather than a model id, so the review used OpenCode default/user-configured model selection.

## Consensus Summary

Both reviewers found the phase direction sound: a generic resource-binding table, filesystem-first validation slice, service-level public filtering, and no full reindex by default all match the Phase 27 boundary. The unresolved risk is integration completeness. As written, the plans can pass narrow fixture tests while breaking existing indexed data or leaking inactive filesystem refs through fallback paths. The review should be fed back into planning before execution.

### Agreed Strengths

- Wave ordering is coherent: storage primitives, filesystem lifecycle, public filtering, then regression/docs.
- Scope remains generic and avoids Telegram ingestion, edit/delete TTL policy, attachments, and plugin UI.
- Service-level active filtering is the right public boundary because search engines can still return retained inactive candidates internally.
- No-full-reindex intent is explicit and aligns with Phase 26 source-ref-first migration constraints.

### Agreed Concerns

- **HIGH:** Existing `source_documents` rows need an idempotent active-binding backfill before public active filtering lands.
- **HIGH:** Normal filesystem indexing must explicitly create or upsert active resource bindings; deactivation alone is only half of the lifecycle.
- **HIGH:** Public read/search fallback paths must not bypass active-binding checks, especially filesystem fallback for present files.
- **HIGH:** Deactivation must preserve provenance and retained artifacts; shared cleanup primitives that delete provenance cannot be reused blindly.
- **HIGH:** Fixed over-fetch (`top_k * 3`) can underfill results when inactive candidates dominate the fused pool.
- **MEDIUM:** Rebind reuse needs behavioral verification, not just summary text saying recomputation remains.
- **MEDIUM:** Query-plan and performance checks should lock in the new active-binding join behavior.

### Current HIGH Concerns

- Missing backfill from existing `source_documents` into active `resource_bindings` before Plan 03 filtering.
- Undefined `content_fingerprint` and `metadata_fingerprint` producer despite schema and rebind logic depending on them.
- Missing active-binding creation/upsert on successful filesystem indexing.
- Rebind acceptance can pass without proving TEI/chunk/artifact reuse.
- Modified-file lifecycle and fingerprint update behavior are underspecified.
- Fixed `top_k * 3` active-filter over-fetch can starve active results under inactive-candidate skew.
- `resource_bindings` duplicates `source_documents` metadata without a source-of-truth rule.
- Trickle `index_file()` path and restored-file interaction are not covered enough for the production path.
- Deactivation path risks deleting provenance if it reuses `_holder_aware_chunk_cleanup`.
- Filesystem fallback in `read`/source resolution can bypass or confuse active-binding enforcement.

### Divergent Views

- Claude emphasized schema-level fingerprint ownership and hardening the rebind acceptance criterion.
- OpenCode emphasized current code-path hazards in `_resolve_source_document`, `_filesystem_path_for_source`, `_holder_aware_chunk_cleanup`, and trickle indexing.
- Claude rated overall risk `MEDIUM-HIGH`; OpenCode rated it `HIGH`. The practical shared recommendation is the same: update the plans before execution.

---

## Claude Review

# Phase 27 Plan Review

## Summary

The four plans deliver a coherent generic resource-binding foundation that respects the stated phase boundaries: source-agnostic schema, no full reindex, no Telegram ingestion, no recycle-bin UX. Wave ordering is sound (storage primitives → filesystem lifecycle → public filter → regression/docs), and decisions D-01 through D-17 are traceable into concrete tasks. The main weaknesses are two cross-plan gaps that would break a real deployment on first restart, and an acceptance criterion for rebind reuse that is permissive enough to let a thinly delivered Plan 02 pass. The plans are stronger as a research artifact than as a turnkey execution package — a planner reading them today would still need to invent two missing slices.

---

## Plan 27-01: Storage Binding State

### Strengths
- Generic `(namespace, resource_ref, document_ref, ref)` shape genuinely supports both filesystem and Telegram without future migration.
- Idempotent `CREATE TABLE IF NOT EXISTS` and explicit "no rebuild" preserves the no-full-reindex guardrail.
- `get_active_chunk_provenance_for_chunk_ids` cleanly routes the visibility join through existing `chunk_source_provenance_<strategy>`, avoiding new joins on hot search paths beyond a single index lookup.
- Deterministic canonical ref selection (`ORDER BY chunk_id, namespace, document_ref`) preserves Phase 26 behavior under multi-binding chunks.
- Acceptance criteria are mostly grep-able strings, which makes auto-verification cheap.

### Concerns
- **HIGH — No backfill from `source_documents`.** Plan 01 creates the table but never populates it for documents already indexed by Phase 26. After Plan 03 lands, `_require_active_source_document(ref)` will reject every existing ref because no binding row exists. This is a silent foot-gun: tests pass on a fresh fixture DB but production breaks on first container restart. Plan must add: on `ensure_resource_bindings_table`, backfill one `active=1` binding per row in `source_documents` (idempotent, single-transaction, fingerprints can be `''` or backfilled lazily).
- **HIGH — `content_fingerprint` and `metadata_fingerprint` are `NOT NULL` but undefined.** What computes them, from what input, on what trigger? Plan 02 assumes they exist for rebind matching but the producer is never specified. Either drop the `NOT NULL` (allow `''` and compute lazily on first rebind opportunity) or specify the producer in Plan 01. As written, the schema accepts data Plan 02 cannot supply.
- **MEDIUM — `ref` is derivable but stored.** Storing `ref == f"{namespace}:{document_ref}"` is redundant and can drift. Either make it a SQLite generated column (`GENERATED ALWAYS AS (... ) STORED`) or drop it from the schema and compute at read time.
- **MEDIUM — Performance characterization missing.** With ~13,500 documents (full corpus), every search will JOIN provenance against bindings. The `(namespace, document_ref, active)` index helps, but no plan asserts query plan / EXPLAIN output. Cheap to add a smoke assertion in Plan 04.
- **LOW — `metadata_json` and `source_unit_refs` are unused in Phase 27.** They are Telegram-future scaffolding. Defensible, but worth marking as such in the docstring so future readers don't assume they're load-bearing.

### Suggestions
- Add a Task 3: **Backfill existing source documents into resource_bindings on first run.** Idempotent, transaction-scoped, no schema migration tool needed.
- Make `content_fingerprint` / `metadata_fingerprint` nullable in this phase, with the rebind path filling them when it's the producer. Or pin a producer (e.g., `_meta_entity_id` for filesystem).
- Add an EXPLAIN-based assertion or comment on the helper SQL to lock in the index path.

---

## Plan 27-02: Filesystem Unbind and Rebind

### Strengths
- Clean split of `_deactivate_filesystem_binding` from `_purge_file`, with explicit docstring guarding the lifecycle distinction.
- Routes both `_incremental_index` deleted-file path and `purge_orphaned_files` through the new method — symmetric coverage.
- Test asserts graph delete helpers are *not* called on normal unbind, which directly enforces D-12.
- `rebound`, `reused_chunks`, `reused_embeddings`, `retained_hidden` keys are stable and assertable.

### Concerns
- **HIGH — Where is the binding *created*?** Neither plan specifies that normal indexing/reindexing must `upsert_resource_binding(active=True)` for each discovered file. Without this, `_deactivate_filesystem_binding` operates on rows that never existed (or only exist due to backfill from Plan 01, which is also missing). This is the symmetric half of the unbind path.
- **HIGH — Rebind acceptance has a soft escape hatch.** Acceptance criterion 6 reads: *asserts TEI encoding is not called for unchanged retained chunk text, **or** documents a single remaining recomputation in a summary/gap with a focused follow-up.* The OR allows Plan 02 to ship with no actual reuse, just a paragraph explaining why. R1's acceptance criterion is "Rebinding equivalent content can reuse retained chunks/embeddings/artifacts" — that's a behavior, not a writeup. Tighten to: TEI mock call count == 0 on the unchanged-content rebind fixture, no exceptions.
- **HIGH — Modified files unaddressed.** Plan says "Do not change modified-file handling unless tests cover the replacement path." But if a file's content changes, the existing active binding's `content_fingerprint` is now stale. Should the binding be updated, deactivated-and-rebound, or left alone? Without specification, modified files will silently retain stale fingerprints, breaking later content-fingerprint-based reuse logic.
- **MEDIUM — Rebind discovery mechanism is hand-waved.** Plan says "discovered with a `content_fingerprint` and `metadata_fingerprint` matching retained inactive binding/source rows." How? No index on `content_fingerprint` is added in Plan 01, and `chunk_source_provenance_<strategy>` doesn't store fingerprints. Either Plan 01 needs a `content_fingerprint` index or Plan 02 needs to specify lookup via `text_hash` on existing chunk rows.
- **MEDIUM — `chunk_file_paths_<strategy>` lifecycle is ambiguous.** "Preserve unless a replacement holder mapping exists in the same task" leaves rebind ambiguous. On rebind: does the existing holder row remain, get re-pointed, or get re-inserted? Tests will fix one behavior, but the plan doesn't pre-commit to which.
- **LOW — Pipeline reentry for previously deleted paths.** Re-discovery of a path that was deactivated within the same session: does `_index_file()` see it as new? Existing diff logic compares against `file_trackers` — which still has the row if Plan 02 preserves source_documents. Worth a test.

### Suggestions
- Add an explicit task 0 / sub-step: **on every successful index of a filesystem file, upsert the resource binding active=True with current fingerprints.** This is the symmetric writer paired with the deactivator.
- Tighten rebind acceptance to a hard "TEI encode call count == 0" assertion on the rebind fixture.
- Specify modified-file behavior: simplest is "modified file = update binding fingerprints in place, no deactivation, existing reindex path runs."
- Pin `chunk_file_paths_<strategy>` rebind semantics: most likely "preserve, no change" since chunks are content-addressed.

---

## Plan 27-03: Public Active Filtering

### Strengths
- Filters at hydration boundary (D-11) without forcing engine-level changes — minimal blast radius across semantic/FTS5/graph engines.
- Over-fetch (`top_k * 3`) is a reasonable first-pass guard against underfill.
- `_require_active_source_document` correctly placed before filesystem fallback so existing-file leak path from Phase 26 is closed.
- Memory-aware: explicitly forbids `load_index(` inside search/read/drill (matches feedback memory `feedback_no_redundant_questions`-adjacent reload concern).
- Diagnostic keys (`active`, `inactive`, `retained`, `reused`) are exact and testable.

### Concerns
- **HIGH — `top_k * 3` over-fetch is fragile under skewed inactive distributions.** During a large filesystem reorganization (mass move/rename), a high fraction of fused candidates can be inactive in the window before rebind. With `top_k=10`, fetching 30 candidates can return zero active results even when active candidates exist further down. Recommend either: (a) iterative refetch with doubling until `top_k` active filled or pool exhausted, or (b) filter at the engine candidate level for at least one engine. Document the assumption in code.
- **HIGH — Same backfill problem as Plan 01.** `_require_active_source_document` rejects refs without active bindings. Without Plan 01 backfill, every Phase 26 ref breaks. Cannot ship Plan 03 without the backfill addressed first.
- **MEDIUM — RRF ranking computed on inactive candidates.** Inactive chunks influence RRF scores of their cohort before the filter drops them. If two engines both rank an inactive chunk highly, the post-fusion top-K may be dominated by inactive entries even though the true top-K active candidates exist further down. The over-fetch helps but doesn't fully decouple. Note as a known limitation in code.
- **MEDIUM — Multi-binding chunk semantics.** When a chunk is held by both an active and inactive binding (M2M), `get_active_chunk_provenance_for_chunk_ids` returns the active provenance. Good. But add a test that exercises this: chunk shared across two filesystem paths, one deactivated, expect active path selected.
- **MEDIUM — graph-direct candidate count.** Graph-direct may return fewer than `top_k * 3` candidates by nature. Filter may starve graph results disproportionately. Either bias the over-fetch per-engine or accept and document.
- **LOW — Error string coupling.** `Action: pass a ref returned by search.` test asserts verbatim. Fragile but acceptable.

### Suggestions
- Replace fixed `* 3` multiplier with constant `ACTIVE_FILTER_OVERFETCH_FACTOR = 3` and add a TODO/comment about iterative refetch for skewed cases.
- Add a multi-binding M2M test specifically.
- Verify `_require_active_source_document` falls back gracefully (not silently) for backfilled refs with empty fingerprints — important if Plan 01 backfill ships with `''` placeholders.

---

## Plan 27-04: Regression, Docs, and Verification

### Strengths
- Concrete `uv run pytest` command lines and grep checks with allowed-hits semantics.
- Explicit `Self-Check: PASSED` gate tied to verification criteria.
- `no dotmd index --force` is a verifiable string in the summary.
- Docs updates correctly limit scope (Phase 27 foundation only, Telegram deferred, GC deferred).

### Concerns
- **MEDIUM — File existence assumptions.** Plan references `tests/ingestion/test_metadata_only_reindex.py` and `tests/ingestion/test_source_filesystem.py` — verify these exist (or list as "create if missing" in Plan 02). If they don't exist, the regression run silently passes by collecting nothing.
- **MEDIUM — "No full reindex" check is a string match in the summary.** Not a behavioral verification. A stronger check: assert TEI encoder mock call count across the Phase 27 test suite stays at zero on rebind fixtures. This is cheap and enforces D-08.
- **LOW — Acceptance criteria are keyword-presence only.** A summary file with the right strings but weak narrative passes. Add one criterion that asserts the test command output is captured verbatim (e.g., `passed` count for each file).
- **LOW — No latency or query-plan check.** With a per-query active filter join, a quick `EXPLAIN QUERY PLAN` snapshot would lock in the index path. Worth ten lines.
- **LOW — Architecture doc updates risk being terse.** Acceptance is "contains active resource binding" — a single sentence passes. Consider adding a minimum line count or reviewer checkpoint.

### Suggestions
- Add a TEI-call-count assertion across the test suite as the canonical "no rebuild" check.
- Make pytest output capture mandatory in `27-04-SUMMARY.md` (paste the trailing `N passed in Xs` line per file).
- Add an EXPLAIN QUERY PLAN check on the active-provenance helper.

---

## Cross-Plan Issues

- **HIGH — Backfill gap (Plans 01 + 03).** Detailed above. This is the single biggest deployment risk: a clean test run that breaks production on first restart because `source_documents` rows have no corresponding `resource_bindings` rows.
- **HIGH — Binding-creation symmetry (Plan 02).** No plan task says "create active binding when indexing a file." Without it, the deactivation path is one half of a missing pair. Plan 01 backfill plus Plan 02 indexing-side upsert close this together.
- **MEDIUM — Rebind softness (Plan 02 + 04).** The OR-clause acceptance and the string-only "no full reindex" check together let a weak rebind implementation slip through. Tighten both.
- **MEDIUM — Fingerprint producer ownership.** No plan owns the question of *who computes content_fingerprint/metadata_fingerprint and from what.* Plan 01 stores them, Plan 02 reads them. The writer is unspecified.
- **LOW — Modified-file binding update.** Quietly out of scope; will become a real bug as soon as anyone edits a file.

---

## Risk Assessment

**Overall risk: MEDIUM-HIGH** for execution as written.

Justification:
- Architectural direction is correct, scope is disciplined, decisions D-01 through D-17 are traceable into tasks. The plans would not produce something embarrassing.
- However, the **backfill gap and binding-creation symmetry gap together create a deployment break risk that is not visible from green tests.** Both are mechanical fixes (a few lines each) but the plans don't currently assign them to a task. A planner executing Plan 03 first or executing without spotting these gaps will land a CI-green change that breaks every existing search ref on restart.
- The rebind reuse acceptance criterion is permissive enough to let R1's "rebinding can reuse retained chunks/embeddings" ship without actual reuse, just a writeup.
- Drop to **MEDIUM-LOW** if: (1) Plan 01 adds explicit backfill task, (2) Plan 02 adds explicit binding-upsert-on-index task, (3) Plan 02 rebind acceptance hardens to "TEI encode call count == 0" with no OR-escape, (4) fingerprint producer is named.

Recommendation: address the four bolded fixes above before execution. They are small in code but large in risk reduction.

---

## OpenCode Review

# Cross-AI Plan Review: Phase 27 — Resource Bindings and Retained Artifacts Foundation

## Plan 01: Storage Binding State

### Summary
Well-scoped storage-layer plan that introduces the `ResourceBinding` model, `resource_bindings` table, and active-provenance query helpers. The TDD approach and clear acceptance criteria are strong. However, there are significant concerns around data duplication with `source_documents`, missing backfill strategy for existing databases, and a subtle schema conflict that will cause production errors.

### Strengths
- Clean wave-1 isolation: storage only, no pipeline/service changes
- TDD with specific acceptance criteria keyed to exact method/table names
- `CREATE TABLE IF NOT EXISTS` avoids migration risk
- `get_active_chunk_provenance_for_chunk_ids` preserves Phase 26's deterministic `ORDER BY chunk_id, namespace, document_ref` canonical selection
- `count_resource_bindings()` keeps diagnostics simple per D-03

### Concerns

- **HIGH — No backfill for existing databases.** After Plan 01 ships, `resource_bindings` is empty. When Plan 03 adds active-binding filtering to `_execute_search`, all existing files become invisible because no binding rows exist. The plan must include a backfill step (likely in `_ensure_source_provenance_ready` or pipeline `__init__`) that creates active bindings for all existing `source_documents` rows. Without this, Plan 03 breaks production search on day one.

- **HIGH — Schema duplication with `source_documents`.** Both tables store `document_ref`, `ref`, `content_fingerprint`, `metadata_fingerprint`, and `metadata_json`. This creates two sources of truth that will diverge on updates. Consider whether `resource_bindings` should hold only binding state (`namespace`, `resource_ref`, `active`, `bound_at`, `unbound_at`) and join to `source_documents` for metadata, or whether the plan must explicitly document why denormalization is intentional (e.g., retained documents may have deleted `source_documents` rows in future GC phases).

- **MEDIUM — `source_unit_refs` is premature.** Filesystem bindings have empty `source_unit_refs` (Phase 25 enforces this). Adding this column now is speculative for Telegram. Per kaizen/YAGNI, add it when Phase 28 needs it.

- **MEDIUM — `metadata_json` on binding duplicates `source_documents.metadata_json`.** Two JSON blobs with the same logical content will drift. If binding metadata is meant to be binding-specific (e.g., `{"deactivation_reason": "file_missing"}`), document this distinction explicitly.

- **LOW — `count_resource_bindings()` returns `active/inactive/total` but Plan 03 expects `active/inactive/retained/reused`.** The count key names should be aligned across plans or the divergence explicitly documented.

### Suggestions
- Add a backfill helper: `backfill_resource_bindings_from_source_documents() -> int` that creates active bindings for all `source_documents` rows missing bindings. Call it once from `_ensure_source_provenance_ready` or `__init__`. This is the highest-priority fix.
- Consider reducing `resource_bindings` to binding-state-only columns and joining to `source_documents` for metadata, or explicitly document why denormalization is needed.
- Drop `source_unit_refs` from the initial schema.

---

## Plan 02: Filesystem Unbind and Rebind

### Summary
The core behavioral change plan — converting hard purge to deactivation and proving rebind reuse. The split between normal unbind and hard purge is well-designed, and the task decomposition is logical. However, there are critical gaps around the modified-file path, the trickle indexer's `index_file()` path, and the rebind complexity.

### Strengths
- Clear separation of `_deactivate_filesystem_binding` from `_purge_file` with docstring guard
- Explicitly preserves graph artifacts on unbind (D-12)
- Rebind task includes TEI-call-count verification
- Keeps hard purge available for explicit GC/drop contexts

### Concerns

- **HIGH — Modified files also call `_purge_file()`.** At `pipeline.py:1366-1368`, `_incremental_index()` calls `_purge_file()` for both `diff.deleted` AND `diff.modified`. The plan correctly routes `diff.deleted` to deactivation but doesn't explicitly address `diff.modified`. Modified files should still be hard-purged (they're being re-indexed with new content, so old chunks/vectors must go). The acceptance criteria should test that modified files still go through full re-index, not deactivation.

- **HIGH — `index_file()` trickle path not addressed.** The trickle indexer calls `index_file()` (line 1684) which calls `_holder_aware_chunk_cleanup()` (line 1733) for modified files. This is the same hard-purge path that deletes source_documents, provenance, and orphans. The plan only addresses `_incremental_index()` and `purge_orphaned_files()` but misses the trickle path. If a file goes missing during trickle, it calls `purge_orphaned_files()` which Plan 02 correctly routes to deactivation, but the trickle's `index_file()` also directly handles the "file disappeared" case at line 815-816 where it returns `None` early. This is fine for now but should be documented.

- **HIGH — `_holder_aware_chunk_cleanup` deletes provenance.** At line 2023-2028, `_holder_aware_chunk_cleanup` calls `delete_chunk_provenance_for_document` which hard-deletes provenance rows. Plan 02 says deactivation preserves provenance, but the implementation path goes through `_holder_aware_chunk_cleanup` which is the shared primitive. The plan must either: (a) create a separate deactivation path that skips provenance deletion, or (b) modify `_holder_aware_chunk_cleanup` to accept a `deactivate=True` flag. Option (a) is cleaner.

- **MEDIUM — Rebind is underspecified for chunk ID stability.** Task 2 says "keep existing retained chunk IDs where the chunk/body strategy is unchanged." Chunk IDs are blake3 hashes of chunk content, so identical content produces identical IDs. But `insert_chunk` uses `INSERT OR IGNORE` — so retained chunks are already present. The rebind path needs to: (1) re-add M2M rows, (2) re-add provenance rows, (3) upsert source_document, (4) reactivate binding, (5) update fingerprints. The plan mentions some of these but the full sequence isn't documented, making it easy to miss a step.

- **MEDIUM — No backfill awareness.** `_deactivate_filesystem_binding` calls `set_resource_binding_active` on a binding that may not exist (pre-Plan-01 database). Must upsert the binding first or the deactivation silently no-ops.

### Suggestions
- Explicitly state that `diff.modified` files in `_incremental_index()` still call `_purge_file()` — only `diff.deleted` routes to deactivation.
- Add a separate deactivation path that does NOT go through `_holder_aware_chunk_cleanup`. The shared primitive deletes provenance and orphans, which is wrong for deactivation. A new `_deactivate_filesystem_binding` should: (1) upsert binding as inactive, (2) leave all other rows untouched.
- Document the exact rebind sequence as a numbered list: upsert binding → add M2M rows → add provenance rows → update fingerprints → verify embedding reuse via text_hash.
- Add acceptance criteria for the trickle `index_file()` path (file exists → normal re-index; file missing → returns 0, deactivation handled by `purge_orphaned_files`).

---

## Plan 03: Public Active Filtering

### Summary
Implements the service-level visibility gate that makes Plans 01-02 functional from the user's perspective. The over-fetch-and-filter approach is sound but the over-fetch multiplier is brittle. A critical gap exists around the `_resolve_source_document()` filesystem fallback, which can bypass the active-binding gate entirely.

### Strengths
- Service-level filtering preserves engine independence (D-11, D-12, D-13)
- Over-fetch strategy addresses the underfill pitfall from research
- `read`/`drill` rejection tests with retained chunks present prove the right invariant
- Grep check for `include_inactive` prevents scope creep

### Concerns

- **HIGH — `_resolve_source_document()` filesystem fallback bypasses binding check.** At `service.py:707-731`, when no `source_documents` row exists but the file exists on disk, a synthetic `SourceDocument` is created. This completely bypasses any binding check. An inactive binding with a present file would still be readable. The plan mentions this ("Existing Phase 26 fallback... must not bypass active binding state") but the acceptance criteria don't test this specific bypass. Add: "test where binding is inactive, file exists on disk, `service.read(ref)` raises ValueError."

- **HIGH — `_filesystem_path_for_source()` at line 744 checks `Path.exists()`.** Even if `_resolve_source_document` is fixed, the `read()` method calls `_filesystem_path_for_source()` which checks `path.exists()` and raises on missing files. For active bindings with present files this is fine, but the error message "Unknown source ref" would be confusing for inactive bindings. The active-binding check must happen BEFORE filesystem fallback.

- **HIGH — Over-fetch `top_k * 3` may be insufficient.** If 80% of the corpus is inactive (after a bulk deletion), 3x over-fetch yields ~60% active candidates, which may underfill results. A more robust approach: over-fetch, filter, and if results are underfilled, log a warning but don't loop (to avoid performance regressions). Document the expected inactive ratio and why 3x is sufficient for the filesystem use case (most files are active).

- **MEDIUM — `build_search_results()` raises on missing provenance.** At `fusion.py:298`, `ValueError(f"missing source provenance for chunk_id={chunk_id}")` is raised if provenance is absent. If Plan 02 preserves provenance for inactive chunks, the active filter runs before `build_search_results` and this is fine. But if provenance is accidentally deleted (e.g., by a bug in deactivation), the error message should distinguish "inactive binding" from "missing provenance." Consider filtering at the `_execute_search` level before passing to `build_search_results`.

- **MEDIUM — Reranker pool interaction.** Reranking happens on `fused[:pool_size]` candidates BEFORE active filtering. If many top candidates are inactive, the reranker wastes computation on them. Consider filtering before reranking, or at least logging the inactive ratio in the rerank pool.

- **LOW — Plan says "do not add `include_inactive`" but doesn't specify behavior for `_execute_search` internal diagnostics.** If an admin wants to verify inactive results are properly hidden, the only option is direct DB queries. This is acceptable per D-03 but worth documenting.

### Suggestions
- Fix `_resolve_source_document` to check active binding BEFORE filesystem fallback. The fix should be: (1) check `source_documents`, (2) if found, check active binding, (3) if not found, check active binding for a synthetic ref, (4) only then fall back to filesystem existence. This is the most critical fix in the entire phase.
- Move active-binding filtering BEFORE reranking to avoid wasting cross-encoder computation on invisible candidates.
- Increase over-fetch to `top_k * 5` or make it configurable, and add a log warning when >50% of candidates are filtered out.
- Add explicit acceptance test: inactive binding + file exists on disk → `service.read(ref)` raises `ValueError("Unknown source ref")`.

---

## Plan 04: Regression, Docs, and Verification

### Summary
Clean verification and documentation plan. The grep checks for scope-creep terms are a strong pattern. Well-scoped with clear acceptance criteria.

### Strengths
- Grep checks prevent inactive-browsing features from sneaking in
- Explicit "no `dotmd index --force`" verification
- `Self-Check: PASSED` gate prevents premature completion
- Doc updates cover both `source-adapter-architecture.md` and `architecture.md`

### Concerns

- **MEDIUM — No integration test for the full unbind→search→rebind→search cycle.** Individual plans test each step but Plan 04 should include an end-to-end integration test: index file → verify search returns it → deactivate → verify search hides it → verify read rejects it → rebind → verify search returns it again → verify read works. This is the D-16 acceptance criterion.

- **MEDIUM — No test for shared-chunk visibility edge case.** If file A and file B share a chunk (same content, M2M), and file A is deactivated while file B remains active, the shared chunk should still be visible through file B's ref. This edge case is not tested anywhere in Plans 01-04.

- **LOW — `just typecheck` and `just lint` are run but pre-existing ratchet status is not recorded.** If these commands have known pre-existing failures, the summary should document the baseline so new regressions are distinguishable.

### Suggestions
- Add one end-to-end integration test covering: index → search hits → deactivate → search misses → rebind → search hits again. This is the single most important test for the entire phase.
- Add a test for the shared-chunk visibility edge case.
- Record baseline typecheck/lint status in the summary.

---

## Overall Risk Assessment

**Risk: HIGH**

### Justification

The plans are well-structured individually but have two critical cross-plan gaps:

1. **Backfill gap (Plans 01 → 03):** Without backfilling `resource_bindings` from existing `source_documents`, Plan 03's active-binding filter makes the entire production index invisible. This is a deployment-breaking bug. The plans should add an explicit backfill step in Plan 01 or early Plan 02, triggered during pipeline initialization.

2. **Filesystem fallback bypass (Plan 03):** `_resolve_source_document()` in `service.py:707-731` creates synthetic `SourceDocument` objects for filesystem refs with no `source_documents` row, bypassing any binding check. This is a pre-existing Phase 26 fallback that must be explicitly narrowed or removed in Plan 03, and the current plan text acknowledges the risk but the acceptance criteria don't test the bypass scenario.

3. **Shared primitive contamination (Plan 02):** `_holder_aware_chunk_cleanup()` deletes provenance rows (line 2023-2028). The deactivation path cannot go through this primitive without modification. Plan 02 needs a completely separate deactivation method, not a conditional branch in the shared primitive.

4. **Trickle indexer coverage:** The trickle path (`index_file()` + `purge_orphaned_files()`) is the primary production code path. Plans address `purge_orphaned_files` but don't test the interaction between trickle deactivation and subsequent trickle re-indexing of a restored file.

These gaps are fixable with targeted additions to the plans, but they must be addressed before execution begins. The overall architecture (binding table → deactivation → service filter) is sound; the risks are in the integration details.
