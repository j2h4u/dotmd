---
phase: 27-resource-bindings-retained-artifacts-foundation
plan: 02
subsystem: ingestion
tags: [filesystem, resource-bindings, retained-artifacts, sqlite, tdd]

requires:
  - phase: 27-resource-bindings-retained-artifacts-foundation
    provides: resource_bindings storage helpers and active provenance state from Plan 01
provides:
  - Active filesystem resource binding upsert on successful indexing
  - Normal filesystem missing-path deactivation without artifact purge
  - Equivalent retained filesystem content rebind without TEI recomputation
affects: [phase-27, phase-28, phase-29, phase-30, phase-31, source-adapters]

tech-stack:
  added: []
  patterns:
    - SourceDocument-to-ResourceBinding lifecycle helpers in IndexingPipeline
    - Missing filesystem resources deactivate bindings while retaining derived rows
    - Retained-content rebind diagnostics for reused chunks and embeddings

key-files:
  created:
    - .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-02-SUMMARY.md
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/storage/metadata.py
    - backend/tests/ingestion/test_source_filesystem.py
    - backend/tests/ingestion/test_metadata_only_reindex.py
    - backend/tests/ingestion/test_pipeline_purge.py
    - backend/tests/ingestion/test_pipeline_orphan_sweep.py

key-decisions:
  - "Normal filesystem disappearance now deactivates resource_bindings and preserves source_documents, provenance, holder rows, chunks, FTS, vector metadata, and graph artifacts."
  - "Modified files keep the hard replacement cleanup path through _purge_file; only missing/deleted paths use _deactivate_filesystem_binding."
  - "Equivalent filesystem rebind is constrained to matching content_fingerprint and metadata_fingerprint, so metadata changes intentionally follow refresh/reindex semantics."

patterns-established:
  - "Successful filesystem indexing upserts an active binding from the same SourceDocument used for source provenance."
  - "Rebind happens before chunking/embedding on no-change bulk and trickle index_file paths, allowing zero TEI calls for retained equivalent content."

requirements-completed: [R1, R2, R8]

duration: 9min
completed: 2026-05-07
---

# Phase 27 Plan 02: Filesystem Unbind and Rebind Summary

**Filesystem missing-path handling now deactivates active bindings while retaining derived artifacts, and restored equivalent content rebinds with zero TEI calls**

## Performance

- **Duration:** 9 min
- **Started:** 2026-05-07T14:47:39Z
- **Completed:** 2026-05-07T14:56:24Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Added active filesystem binding upserts after successful bulk indexing, trickle `index_file()`, and metadata-only refresh paths.
- Split normal missing-file handling from destructive hard purge: deleted/orphan paths now deactivate bindings and retain source/provenance/chunk/FTS/vector/graph artifacts.
- Added equivalent retained-content rebind before chunking/embedding, with `rebound`, `reused_chunks`, `reused_embeddings`, and `retained_hidden` diagnostics.
- Added regression tests proving restored unchanged filesystem content reactivates retained bindings with `TEI encode call count == 0`.

## Task Commits

Each task was committed atomically with TDD RED and GREEN commits:

1. **Task 1: Upsert active filesystem bindings during successful indexing**
   - `f7309ef` test(27-02): add failing test for active filesystem bindings
   - `6cbe01b` feat(27-02): upsert active filesystem bindings
2. **Task 2: Split normal unbind from hard purge**
   - `8acabb4` test(27-02): add failing test for filesystem unbind
   - `3b512e1` feat(27-02): split filesystem unbind from hard purge
3. **Task 3: Rebind equivalent filesystem content to retained artifacts**
   - `29724ae` test(27-02): add failing test for retained filesystem rebind
   - `001b9f7` feat(27-02): rebind retained filesystem content

**Plan metadata:** committed separately in the final docs commit.

## Files Created/Modified

- `backend/src/dotmd/ingestion/pipeline.py` - Added active binding upsert, normal deactivation, retained rebind, and deleted/orphan routing changes.
- `backend/src/dotmd/storage/metadata.py` - Added inactive binding lookup by content and metadata fingerprints.
- `backend/tests/ingestion/test_source_filesystem.py` - Added active-binding and zero-TEI rebind coverage for bulk and trickle paths.
- `backend/tests/ingestion/test_metadata_only_reindex.py` - Added binding fingerprint coverage for body, metadata-only, and trickle modified-file refreshes.
- `backend/tests/ingestion/test_pipeline_purge.py` - Added retained-artifact normal-unbind coverage and graph-delete negative assertions.
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py` - Updated orphan sweep expectations from hard purge to deactivation.

## Decisions Made

- Rebind requires both `content_fingerprint` and `metadata_fingerprint` to match. Metadata-only changes remain refresh/reindex work instead of being treated as equivalent retained-content rebinds.
- `_purge_file()` remains the explicit destructive cleanup primitive for modified-file replacement and future hard purge/GC contexts.
- Phase 27 same-path filesystem rebind preserves retained holder/provenance rows rather than adding broader cross-path rebinding behavior.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q` - PASS, 15 passed, 15 warnings.
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q` - PASS, 30 passed, 22 warnings.
- Acceptance grep checks confirmed `upsert_resource_binding`, `_deactivate_filesystem_binding`, deleted-path deactivation, modified-path `_purge_file`, `rebound`, `reused_chunks`, and `reused_embeddings` are present.
- `_deactivate_filesystem_binding` block scan confirmed no calls to `_holder_aware_chunk_cleanup`, `delete_chunk_provenance_for_document`, `delete_chunks_from_graph`, `delete_file_node`, or `delete_file_subgraph`.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Test Fixture Bug] Updated purge fixture FTS5 schema**
- **Found during:** Task 2 (Split normal unbind from hard purge)
- **Issue:** The new retained-FTS assertion was seeded with the old two-column FTS5 fixture schema, and pipeline startup migrated it by dropping the table before the unbind assertion.
- **Fix:** Updated the purge test fixture FTS5 tables to include current `title` and `tags` columns.
- **Files modified:** `backend/tests/ingestion/test_pipeline_purge.py`
- **Verification:** `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q` passed.
- **Committed in:** `3b512e1`

---

**Total deviations:** 1 auto-fixed (1 bug).
**Impact on plan:** Fixture correction only; production behavior stayed within planned scope.

## Issues Encountered

- The same Pydantic settings warning appeared during ingestion tests: `Config key toml_file is set in model_config but will be ignored...`. This is pre-existing test noise and did not affect pass/fail results.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. `source_unit_refs=[]` and `metadata_json={}` are intentional Phase 27 filesystem binding defaults, not unwired UI/data stubs.

## TDD Gate Compliance

PASS - RED and GREEN commits exist for each behavior task. No refactor commit was needed.

## Next Phase Readiness

Ready for Plan 27-03. Ingestion now maintains active/inactive filesystem binding state and retains reusable artifacts; public search/read filtering can build on these active bindings without requiring full reindex, TEI recomputation of unchanged work, FTS rebuild, vector rebuild, or graph rebuild.

## Self-Check: PASSED

- Summary file exists.
- Task commits exist: `f7309ef`, `6cbe01b`, `8acabb4`, `3b512e1`, `29724ae`, `001b9f7`.
- Required verification commands passed.
- Unrelated dirty work remained unstaged: `.opencode/opencode.json`, `.opencode/plugins/`, `.planning/graphs/`, `graphify-out/`.

---
*Phase: 27-resource-bindings-retained-artifacts-foundation*
*Completed: 2026-05-07*
