---
phase: 27-resource-bindings-retained-artifacts-foundation
plan: 04
subsystem: regression-docs-verification
tags: [pytest, resource-bindings, retained-artifacts, docs, verification]

requires:
  - phase: 27-resource-bindings-retained-artifacts-foundation
    provides: storage bindings, filesystem unbind/rebind, and public active filtering from Plans 01-03
provides:
  - End-to-end filesystem binding lifecycle regression covering search/read hide and restore
  - Focused Phase 27 pytest/typecheck/lint verification evidence
  - Architecture documentation for the retained-artifact lifecycle boundary
  - Explicit no-full-reindex verification record
affects: [phase-27, phase-28, phase-29, phase-30, phase-31, source-adapters, mcp]

tech-stack:
  added: []
  patterns:
    - Regression summaries record exact command output lines for verification gates
    - Retained artifact documentation states shipped foundation separately from future Telegram work

key-files:
  created:
    - .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md
  modified:
    - backend/tests/api/test_service_search.py
    - docs/source-adapter-architecture.md
    - docs/architecture.md

key-decisions:
  - "Phase 27 is foundation only: filesystem retained-artifact lifecycle shipped; Telegram ingestion/export, TTL/GC, recycle-bin behavior, attachments/media, and live Telegram smoke remain deferred."
  - "Verification evidence is local fixture/integration coverage for Phase 27; no production full reindex or dotmd index --force was run."
  - "Active resource bindings remain the public search/read/drill visibility gate while retained inactive artifacts remain internal reuse state."

patterns-established:
  - "End-to-end lifecycle regression patches retrieval candidates while using real pipeline metadata, service search filtering, and read(ref) enforcement."
  - "Docs describe source_documents as active/current metadata truth and resource_bindings as active state plus retained fingerprint snapshots."

requirements-completed: [R1, R2, R8]

duration: 7min
completed: 2026-05-07
---

# Phase 27 Plan 04: Regression, Docs, and Verification Summary

**Focused Phase 27 regression proof plus retained-artifact lifecycle docs, with filesystem unbind/rebind verified without full reindex**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-07T15:13:08Z
- **Completed:** 2026-05-07T15:19:37Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added an end-to-end filesystem lifecycle regression in `backend/tests/api/test_service_search.py` that indexes a Markdown file, verifies `service.search()` and `service.read(ref)`, deactivates through the missing-file indexing path, verifies search/read hiding, restores equivalent content, and verifies search/read restoration.
- Confirmed retained rebind reuse with `TEI encode call count = 0` for unchanged retained content.
- Ran the focused Phase 27 verification suite plus `just typecheck` and `just lint`.
- Updated architecture docs to state the Phase 27 foundation honestly: active bindings gate public visibility; retained inactive artifacts are hidden reuse state; Telegram ingestion, export, TTL/GC, recycle-bin behavior, attachments/media, plugin UI, and live Telegram smoke are deferred.
- Recorded that no `dotmd index --force`, full reindex, or full rebuild was run.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add missing end-to-end and edge-case regression assertions** - `32b5f09` (test)
2. **Task 2: Run focused Phase 27 regression suite** - `a8346dc` (fix)
3. **Task 3: Document retained-artifact lifecycle boundary** - `693d3d7` (docs)

**Plan metadata:** committed separately in the final docs commit.

## Files Created/Modified

- `backend/tests/api/test_service_search.py` - Added filesystem binding lifecycle regression and lint/typecheck-safe setup.
- `docs/source-adapter-architecture.md` - Added Phase 27 delivered-state section and clarified deferred Telegram/GC scope.
- `docs/architecture.md` - Added active bindings to storage/query architecture and documented retained-artifact lifecycle boundary.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md` - Verification summary and self-check record.

## Verification

### Focused Phase 27 Pytest

Command:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q
```

Result:

```text
130 passed, 73 warnings in 6.57s
```

Earlier post-Task-1 run also passed:

```text
130 passed, 73 warnings in 6.84s
```

### Typecheck

Command:

```bash
just typecheck
```

Result:

```text
pyright ratchet: 66 errors (baseline 69)
  improvements: -3 across 2 files (run with --update to lock the new floor)
```

This is a ratchet pass with no Phase 27 regression.

### Lint

Command:

```bash
just lint
```

Result:

```text
All checks passed!
```

### Lifecycle Evidence

- **Unbind hides public search/read:** `TestFilesystemBindingLifecycle.test_filesystem_unbind_rebind_hides_and_restores_search_read_without_tei` unlinks the indexed Markdown file, runs `service.index(data_dir)` through the missing-path path, asserts `service.search(...) == []`, and asserts `service.read(ref, 0, 1)` raises `ValueError("Unknown source ref")`.
- **Retained chunks/provenance/vector/FTS rows remain:** Plan 27-02 retained-artifact tests in `tests/ingestion/test_pipeline_purge.py` and `tests/ingestion/test_pipeline_orphan_sweep.py` passed inside the focused suite; the retained unbind path does not call graph delete helpers and keeps chunk/provenance/FTS fixtures.
- **Equivalent rebind exercises reuse:** `tests/ingestion/test_source_filesystem.py` and the new service lifecycle regression restore equivalent content and confirm original chunk IDs/provenance stay usable after reactivation.
- **TEI encode call count:** The new service lifecycle regression clears `encode_calls` before restored equivalent rebind and asserts `encode_calls == []`; this is recorded as `TEI encode call count = 0` for unchanged retained-content rebind.
- **EXPLAIN QUERY PLAN:** `tests/storage/test_metadata_m2m.py::test_active_chunk_provenance_uses_document_active_index` runs `EXPLAIN QUERY PLAN` over the active provenance join with `INDEXED BY idx_resource_bindings_document_active` and asserts the plan contains `idx_resource_bindings_document_active`.
- **Shared chunks remain visible through active bindings:** `tests/storage/test_metadata_m2m.py::test_active_chunk_provenance_excludes_inactive_retained_rows` inserts inactive and active provenance for a shared chunk, then asserts inactive-only chunks are hidden while `active[shared_chunk_id].document_ref` resolves to the active file.
- **Filesystem fallback bypass:** `tests/api/test_service_search.py::test_read_ref_rejects_inactive_filesystem_binding_with_present_file` keeps the file present but inactive and asserts `ValueError("Unknown source ref")`.
- **Trickle coverage:** `tests/ingestion/test_source_filesystem.py` covers `index_file()` equivalent rebind with no encode calls; `tests/ingestion/test_metadata_only_reindex.py` covers modified `index_file()` updating binding fingerprints while leaving the binding active.
- **Telegram live smoke:** Not run. Phase decision D-17 explicitly defers runtime Telegram live smoke to the later Telegram search/read/drill phase; Phase 27 uses local fixture/integration tests.
- **no dotmd index --force:** no `dotmd index --force`, full reindex, or full rebuild command was run. Verification used local pytest fixtures, `just typecheck`, `just lint`, and documentation grep checks only.

### Documentation Grep Checks

Command:

```bash
rg "include_inactive|recycle-bin|recycle bin|inactive browsing|list_inactive" docs/ backend/src/dotmd backend/tests
```

Allowed hits were explicit deferred/out-of-scope wording:

```text
docs/architecture.md:bin or inactive browsing surface.
docs/source-adapter-architecture.md:Retained inactive artifacts are not a recycle bin or inactive browsing feature.
docs/source-adapter-architecture.md:- Telegram recycle-bin behavior;
```

Command:

```bash
rg "dotmd index --force|full reindex|full rebuild" docs/source-adapter-architecture.md docs/architecture.md .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-04-SUMMARY.md
```

Result includes explicit no-full-reindex / no-full-rebuild statements in the docs and this summary.

## Decisions Made

- Kept Phase 27 documentation scoped to the filesystem foundation and did not claim Telegram adapter behavior shipped.
- Treated live Telegram smoke as deferred by D-17, not a missing Phase 27 gate.
- Kept `source_documents` as active/current document metadata truth and documented `resource_bindings` as binding activity plus retained fingerprint snapshots.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical Regression] Added service-level lifecycle fixture**
- **Found during:** Task 1 (Add missing end-to-end and edge-case regression assertions)
- **Issue:** Prior tests covered the pieces individually, but the review-critical single service lifecycle path was not present as one regression.
- **Fix:** Added `TestFilesystemBindingLifecycle.test_filesystem_unbind_rebind_hides_and_restores_search_read_without_tei`.
- **Files modified:** `backend/tests/api/test_service_search.py`
- **Verification:** Focused pytest command passed with `130 passed, 73 warnings`.
- **Committed in:** `32b5f09`

**2. [Rule 3 - Blocking] Fixed lint/typecheck gate issue in touched test file**
- **Found during:** Task 2 (Run focused Phase 27 regression suite)
- **Issue:** `just lint` required import formatting and rejected a constant `setattr`; direct assignment then caused a pyright ratchet regression.
- **Fix:** Let Ruff sort imports and used `object.__setattr__` for the dynamic test-only diagnostic attribute.
- **Files modified:** `backend/tests/api/test_service_search.py`
- **Verification:** Focused pytest, `just typecheck`, and `just lint` passed.
- **Committed in:** `a8346dc`

---

**Total deviations:** 2 auto-fixed (1 missing critical regression, 1 blocking lint/typecheck issue).
**Impact on plan:** Both fixes strengthened planned verification without expanding Phase 27 product scope.

## Issues Encountered

- The focused pytest suite still emits the pre-existing Pydantic settings warning about `toml_file` being ignored without `TomlConfigSettingsSource`. It does not affect pass/fail status.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. Empty source-unit refs for filesystem Markdown and empty metadata defaults remain intentional Phase 25/27 filesystem compatibility behavior, not unwired UI/data stubs.

## Threat Flags

None. This plan added tests and docs only; it introduced no new network endpoints, auth paths, file access trust boundary, or schema change.

## Next Phase Readiness

Phase 27 is ready for orchestrator-owned verification/routing. The plan does not update final phase-complete state. Later phases can build the application source provider contract and Telegram adapter on top of active resource bindings and retained artifact reuse.

## Self-Check: PASSED

- Files exist: `backend/tests/api/test_service_search.py`, `docs/source-adapter-architecture.md`, `docs/architecture.md`, and this summary.
- Commits exist: `32b5f09`, `a8346dc`, and `693d3d7`.
- Summary acceptance strings are present: focused test file paths, `just typecheck`, `just lint`, `TEI encode call count`, `EXPLAIN QUERY PLAN`, `no dotmd index --force`, and `Self-Check: PASSED`.
- Stub scan found only intentional test fixture defaults: `metadata_json={}`, `source_unit_refs=[]`, and `MagicMock(return_value=[])`.
- Inactive browsing grep hits are explicit deferred/out-of-scope wording only.

---
*Phase: 27-resource-bindings-retained-artifacts-foundation*
*Completed: 2026-05-07*
