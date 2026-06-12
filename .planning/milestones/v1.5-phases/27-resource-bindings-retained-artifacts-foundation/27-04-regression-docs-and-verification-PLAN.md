---
phase: "27"
plan: "04"
type: execute
wave: 4
depends_on:
  - "27-01"
  - "27-02"
  - "27-03"
files_modified:
  - backend/tests/storage/test_metadata_m2m.py
  - backend/tests/ingestion/test_pipeline_purge.py
  - backend/tests/ingestion/test_pipeline_orphan_sweep.py
  - backend/tests/ingestion/test_source_filesystem.py
  - backend/tests/ingestion/test_metadata_only_reindex.py
  - backend/tests/api/test_service_search.py
  - backend/tests/test_fusion.py
  - backend/tests/mcp/test_search_tool.py
  - docs/source-adapter-architecture.md
  - docs/architecture.md
  - .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md
autonomous: true
requirements: ["R1", "R2", "R8"]
requirements_addressed: ["R1", "R2", "R8"]
must_haves:
  truths:
    - "D-03: No user-facing recycle-bin search or inactive-content browsing is shipped."
    - "D-05: Inactive retained artifacts do not leak through public output."
    - "D-06: Old TTL soft-delete todo is historical only."
    - "D-10: Filesystem conversion is validated as the concrete Phase 27 slice."
    - "D-14: Telegram deleted-message metadata is not modeled as resource unbind in Phase 27."
    - "D-15: Telegram recycle-bin behavior is out of scope."
    - "D-16: Integration tests prove unbind hides public search/read while retaining reusable artifacts."
    - "D-17: Local fixture/integration tests are sufficient for Phase 27; runtime Telegram live smoke belongs later."
    - "Review feedback: validation proves full unbind-search-read-rebind-search-read behavior and shared-chunk visibility."
    - "Review feedback: summary records pytest pass lines, TEI encode count evidence, EXPLAIN/query-plan evidence, and typecheck/lint ratchet status."
    - "Full-reindex answer: this plan verifies no dotmd index --force/full rebuild was needed."
---

# Phase 27 Plan 04: Regression, Docs, and Verification

<objective>
Close Phase 27 by proving the storage, pipeline, and service changes satisfy
R1/R2/R8, keep filesystem Markdown behavior compatible, and document the
generic binding/retention foundation without moving into Telegram ingestion or
garbage-collection policy.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Tests prove isolated helpers but not the real lifecycle | HIGH | Add an end-to-end filesystem integration test: index, search/read visible, deactivate, search/read hidden, rebind, search/read visible again. |
| Shared content disappears when one holder is inactive | HIGH | Add a shared-chunk visibility edge-case test where inactive A plus active B still returns B. |
| Rebind claims reuse without proving it | HIGH | Require TEI encode call count `0` for unchanged retained-content rebind and record it in the summary. |
| Docs describe future Telegram behavior as already implemented | MEDIUM | Update docs with "Phase 27 foundation only" wording and keep Telegram adapter surfaces deferred. |
| Public inactive browsing sneaks in as a debug convenience | HIGH | Add grep checks for `include_inactive`, recycle-bin language, and inactive browsing surfaces. |
| A hidden full reindex is required but undocumented | HIGH | Summary records commands run and explicitly states no `dotmd index --force` or full rebuild was run. |
| Type/lint ratchet hides regressions | MEDIUM | Run `just typecheck` and `just lint`; record pre-existing ratchet if either does not pass. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Add missing end-to-end and edge-case regression assertions</title>
<name>Add missing end-to-end and edge-case regression assertions</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-VALIDATION.md`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/test_fusion.py`
- `backend/tests/mcp/test_search_tool.py`
</read_first>
<files>
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/test_fusion.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Before final verification, ensure the tests created by Plans 01-03 include the
review-critical scenarios.

Required checks:
- Confirm every test file listed in this plan exists. If any are missing, create
  the missing test file and add at least one focused test for its assigned behavior.
- Add or confirm one end-to-end filesystem fixture covering:
  1. index a Markdown file;
  2. `service.search()` returns its active `ref`;
  3. `service.read(ref)` returns content;
  4. deactivate the filesystem binding through the Phase 27 missing-path path;
  5. `service.search()` excludes the inactive ref;
  6. `service.read(ref)` raises `ValueError("Unknown source ref")`;
  7. restore equivalent content;
  8. rebind/reactivate the binding;
  9. `service.search()` returns the ref again;
  10. `service.read(ref)` returns content again;
  11. TEI encode call count for unchanged retained chunk text is exactly `0`.
- Add or confirm a shared-chunk fixture:
  - file A and file B share at least one chunk/content hash;
  - deactivate file A;
  - search excludes file A ref but still returns file B active ref for the shared chunk;
  - active provenance helper returns B as the public provenance.
- Add or confirm an EXPLAIN query-plan check for the active-binding join that
  asserts the `idx_resource_bindings_document_active` index is used.
- Add or confirm trickle coverage:
  - `index_file()` restores/reactivates an equivalent inactive file;
  - `index_file()` on a modified present file updates fingerprints and leaves the binding active.
- Add or confirm the filesystem fallback bypass test:
  - inactive binding plus present file on disk makes `service.read(ref)` raise `ValueError`.
</action>
<acceptance_criteria>
- `test -f backend/tests/ingestion/test_metadata_only_reindex.py` exits 0.
- `test -f backend/tests/ingestion/test_source_filesystem.py` exits 0.
- `test -f backend/tests/ingestion/test_pipeline_purge.py` exits 0.
- `test -f backend/tests/api/test_service_search.py` exits 0.
- Tests contain `Unknown source ref`.
- Tests contain `idx_resource_bindings_document_active`.
- Tests contain `encode` and assert call count `0` or equivalent explicit no-TEI assertion for unchanged rebind.
- Tests contain a shared-chunk or shared active/inactive provenance case.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Run focused Phase 27 regression suite</title>
<name>Run focused Phase 27 regression suite</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-VALIDATION.md`
- `backend/pyproject.toml`
- `justfile`
- all test files listed in task 1
</read_first>
<files>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md`
- affected tests from Plans 01-03 if failures expose incomplete assertions
</files>
<action>
Run and record the focused Phase 27 verification suite.

Required commands:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q
just typecheck
just lint
```

Create `27-04-SUMMARY.md` and include:
- exact command lines;
- trailing pytest pass/fail output line for the focused pytest command, for example `N passed in Xs`;
- pass/fail summaries for `just typecheck` and `just lint`, including pre-existing ratchet status if either fails for reasons outside Phase 27 changes;
- evidence that unbind hides public search/read;
- evidence that retained chunks/provenance/vector/FTS rows remain;
- evidence that equivalent rebind exercises reuse;
- exact TEI encode call count evidence for unchanged retained-content rebind;
- EXPLAIN/query-plan evidence for the active-binding join;
- evidence that shared chunks remain visible through active bindings;
- evidence that no Telegram live smoke was run because D-17 defers it;
- the literal string `no dotmd index --force`;
- `Self-Check: PASSED` only when the focused checks pass or documented pre-existing ratchet is outside Phase 27 changes.
</action>
<acceptance_criteria>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/storage/test_metadata_m2m.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/ingestion/test_pipeline_purge.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/ingestion/test_metadata_only_reindex.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/api/test_service_search.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `just typecheck`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `just lint`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `TEI encode call count`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `EXPLAIN QUERY PLAN`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `no dotmd index --force`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `Self-Check: PASSED` only if verification criteria are met.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Document retained-artifact lifecycle boundary</title>
<name>Document retained-artifact lifecycle boundary</name>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`
- `docs/architecture.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
- `.planning/REQUIREMENTS.md`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/architecture.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md`
</files>
<action>
Update architecture docs to reflect the Phase 27 foundation.

Required doc content:
- Active resource bindings are the public visibility gate.
- `source_documents` remains the source of truth for active/current source document metadata and fingerprints.
- `resource_bindings` stores binding activity plus retained fingerprint snapshots for rebind lookup.
- Retained inactive artifacts are hidden from normal public `search/read`.
- Retained artifacts exist for reuse and are not a recycle-bin feature.
- Garbage collection/TTL policy is deferred.
- Filesystem missing paths deactivate bindings rather than normal hard purge.
- Modified files still use replacement reindex semantics and update active binding fingerprints after successful reindex.
- Telegram ingestion, `mcp-telegram` export API, attachments/media, and generic plugin UI remain later-phase work.
- Telegram deleted-upstream metadata is not a Phase 27 unbind rule.
- No full reindex is required for Phase 27.

Run grep checks:

```bash
rg "include_inactive|recycle-bin|recycle bin|inactive browsing|list_inactive" docs/ backend/src/dotmd backend/tests
rg "dotmd index --force|full reindex|full rebuild" docs/source-adapter-architecture.md docs/architecture.md .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md
```

Allowed hits for the first command must be explicit deferred/out-of-scope
wording or tests asserting absence.
</action>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `active resource binding` or equivalent wording.
- `docs/source-adapter-architecture.md` contains `retained inactive artifacts`.
- `docs/source-adapter-architecture.md` says `source_documents` is the source of truth for active/current document metadata or equivalent wording.
- `docs/source-adapter-architecture.md` says garbage collection or TTL is deferred.
- `docs/architecture.md` mentions the Phase 27 foundation or retained artifact lifecycle boundary.
- No docs claim Telegram ingestion shipped in Phase 27.
- Grep output for inactive browsing terms is either empty or explicitly deferred/out-of-scope.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q
just typecheck
just lint
```
</verification>

<success_criteria>
- R1, R2, and R8 are covered by automated tests and documented verification.
- Filesystem behavior remains source-ref-first and compatible for active documents.
- Retained inactive content cannot leak through public search/read.
- Rebind reuse is proven behavior, not summary-only acceptance.
- Phase 27 stays within scope and does not implement Telegram ingestion, export API, TTL/GC policy, attachments/media, or plugin UI.
</success_criteria>

## PLANNING COMPLETE
