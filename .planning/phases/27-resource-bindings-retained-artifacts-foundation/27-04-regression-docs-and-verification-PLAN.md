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
  - backend/tests/api/test_service_search.py
  - backend/tests/test_fusion.py
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
| Tests prove storage helpers but not real filesystem behavior | HIGH | Run focused pipeline/source filesystem integration tests after storage/service tests. |
| Docs describe future Telegram behavior as already implemented | MEDIUM | Update docs with "Phase 27 foundation only" wording and keep Telegram adapter surfaces deferred. |
| Public inactive browsing sneaks in as a debug convenience | HIGH | Add grep checks for `include_inactive`, recycle-bin language, and inactive browsing surfaces. |
| A hidden full reindex is required but undocumented | HIGH | Summary records commands run and explicitly states no `dotmd index --force` or full rebuild was run. |
| Type/lint ratchet hides regressions | MEDIUM | Run `just typecheck` and `just lint`; record pre-existing ratchet if any. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Run focused Phase 27 regression suite</title>
<name>Run focused Phase 27 regression suite</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-VALIDATION.md`
- `backend/pyproject.toml`
- `justfile`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/test_fusion.py`
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
- pass/fail summaries;
- evidence that unbind hides public search/read;
- evidence that retained chunks/provenance/vector/FTS rows remain;
- evidence that equivalent rebind reports or exercises reuse;
- evidence that no Telegram live smoke was run because D-17 defers it;
- `Self-Check: PASSED` only when the focused checks pass or documented
  pre-existing ratchet is outside Phase 27 changes.
</action>
<acceptance_criteria>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/storage/test_metadata_m2m.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/ingestion/test_pipeline_purge.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `tests/api/test_service_search.py`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `just typecheck`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `just lint`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `no dotmd index --force`.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` contains `Self-Check: PASSED` only if verification criteria are met.
</acceptance_criteria>
</task>

<task id="2" type="execute">
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
- Retained inactive artifacts are hidden from normal public `search/read`.
- Retained artifacts exist for reuse and are not a recycle-bin feature.
- Garbage collection/TTL policy is deferred.
- Filesystem missing paths now deactivate bindings rather than normal hard purge.
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
- Phase 27 stays within scope and does not implement Telegram ingestion, export API, TTL/GC policy, attachments/media, or plugin UI.
</success_criteria>

## PLANNING COMPLETE
