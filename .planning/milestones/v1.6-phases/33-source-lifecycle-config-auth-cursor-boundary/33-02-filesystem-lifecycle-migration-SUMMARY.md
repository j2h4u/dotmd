---
phase: 33-source-lifecycle-config-auth-cursor-boundary
plan: "02"
subsystem: ingestion
tags: [source-lifecycle, filesystem, source-ref, indexing-pipeline, tdd]

requires:
  - phase: 33-source-lifecycle-config-auth-cursor-boundary
    provides: lifecycle runtime bundle and SourceRuntimeFactory from Plan 01
provides:
  - Settings-derived source runtime factory seeding filesystem config
  - IndexingPipeline filesystem discovery routed through lifecycle
  - IndexingPipeline FileInfo-to-SourceDocument bridge routed through lifecycle
  - Regression coverage preserving filesystem source refs and no provider cursor claim
affects: [filesystem-unification, source-lifecycle, retained-artifacts, source-ref-contract]

tech-stack:
  added: []
  patterns:
    - Settings-to-lifecycle factory helper using typed SourceConfigRecord values
    - Pipeline call sites obtaining filesystem adapters from lifecycle bundles

key-files:
  created:
    - .planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-02-filesystem-lifecycle-migration-SUMMARY.md
  modified:
    - backend/src/dotmd/ingestion/source_lifecycle.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/tests/ingestion/test_source_lifecycle.py
    - backend/tests/ingestion/test_source_filesystem.py

key-decisions:
  - "Filesystem lifecycle config is seeded from settings.indexing_paths and settings.effective_indexing_exclude."
  - "IndexingPipeline now builds filesystem adapters through SourceRuntimeFactory.build(\"filesystem\") instead of direct construction."
  - "Filesystem runtime bundles keep provider as None and preserve existing filesystem:<resolved_path> refs."

patterns-established:
  - "source_runtime_factory_from_settings(settings, metadata_store) is the default wiring point for lifecycle-mediated source runtimes."
  - "Pipeline filesystem helper methods guard against lifecycle bundles without a source adapter."

requirements-completed: ["LIFE-01", "LIFE-04"]

duration: 6 min
completed: 2026-05-08
---

# Phase 33 Plan 02: Filesystem Lifecycle Migration Summary

**IndexingPipeline filesystem discovery and SourceDocument construction now obtain their adapter through the source lifecycle factory while preserving filesystem refs.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-08T15:13:38Z
- **Completed:** 2026-05-08T15:19:20Z
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added RED regression tests proving settings-derived filesystem lifecycle config, pipeline lifecycle discovery, pipeline lifecycle SourceDocument construction, and filesystem no-provider behavior.
- Added `source_runtime_factory_from_settings()` to seed filesystem lifecycle config from live `Settings` and optional Telegram config only when configured.
- Routed `IndexingPipeline` filesystem discovery and FileInfo bridging through `self._source_runtime_factory.build("filesystem")`.
- Preserved filesystem refs as `filesystem:<resolved_path>` and kept filesystem provider cursor ownership absent.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add filesystem lifecycle regression tests** - `c35a554` (test)
2. **Task 2: Route IndexingPipeline filesystem construction through lifecycle** - `ff2e515` (feat)

**Plan metadata:** committed separately after this summary.

## Files Created/Modified

- `backend/tests/ingestion/test_source_lifecycle.py` - Added settings-derived filesystem lifecycle factory regression.
- `backend/tests/ingestion/test_source_filesystem.py` - Added pipeline lifecycle discovery and SourceDocument bridge regressions; aligned pipeline test fixtures with lifecycle-required `indexing_paths`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` - Added default settings-to-runtime-factory helper.
- `backend/src/dotmd/ingestion/pipeline.py` - Stored lifecycle factory and routed filesystem adapter use through lifecycle; added narrow pyright casts for existing dynamic vector-store internals.
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-02-filesystem-lifecycle-migration-SUMMARY.md` - Execution outcome summary.

## Decisions Made

- Used `settings.indexing_paths` directly for filesystem lifecycle config, matching the plan and avoiding any resolved-indexing-path alias.
- Preserved existing filesystem adapter private bridge method `_from_file_info()` but now obtains the adapter from lifecycle first.
- Kept Telegram config opportunistic in the helper: only present when `settings.telegram_daemon_socket` is configured, leaving Plan 03 to extend Telegram call-site migration.

## TDD Gate Compliance

- **RED:** `c35a554` added failing lifecycle migration tests. Focused pytest failed before implementation with `AttributeError: module 'dotmd.ingestion.source_lifecycle' has no attribute 'source_runtime_factory_from_settings'`.
- **GREEN:** `ff2e515` implemented lifecycle factory wiring and pipeline migration. Focused pytest, pyright, and static grep checks passed.
- **REFACTOR:** No separate refactor commit was needed.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q` -> `32 passed`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py` -> `0 errors, 0 warnings, 0 informations`
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` -> no matches
- `rg -n "resolved[_]indexing[_]paths" backend/src/dotmd/ingestion/source_lifecycle.py` -> no matches

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed pyright blockers in the required pipeline verification target**
- **Found during:** Task 2 (Route IndexingPipeline filesystem construction through lifecycle)
- **Issue:** The plan-required pyright command surfaced dynamic vector-store attribute accesses and one possibly-unbound local in `pipeline.py`.
- **Fix:** Added narrow `Any` casts around dynamic vector-store internals and initialized `e_text_vectors` before branching.
- **Files modified:** `backend/src/dotmd/ingestion/pipeline.py`
- **Verification:** Plan pyright command exits 0.
- **Committed in:** `ff2e515`

**2. [Rule 3 - Blocking] Aligned filesystem pipeline fixtures with lifecycle-required indexing paths**
- **Found during:** Task 2 (Route IndexingPipeline filesystem construction through lifecycle)
- **Issue:** Existing filesystem pipeline tests constructed `Settings` without `indexing_paths`, but lifecycle correctly requires filesystem paths before building the runtime bundle.
- **Fix:** Added `indexing_paths=[str(data_dir)]` to the affected test settings fixtures.
- **Files modified:** `backend/tests/ingestion/test_source_filesystem.py`
- **Verification:** Focused filesystem lifecycle pytest command exits 0.
- **Committed in:** `ff2e515`

---

**Total deviations:** 2 auto-fixed (Rule 3)
**Impact on plan:** Both fixes were required to satisfy the plan's verification gate and preserve lifecycle runtime correctness.

## Issues Encountered

None beyond the auto-fixed blocking issues documented above.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 03 can migrate Telegram construction and cursor boundaries on top of the now-live lifecycle factory. Filesystem construction no longer bypasses lifecycle.

## Self-Check: PASSED

- Found `backend/src/dotmd/ingestion/source_lifecycle.py`
- Found `backend/src/dotmd/ingestion/pipeline.py`
- Found `backend/tests/ingestion/test_source_lifecycle.py`
- Found `backend/tests/ingestion/test_source_filesystem.py`
- Found `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-02-filesystem-lifecycle-migration-SUMMARY.md`
- Found commit `c35a554`
- Found commit `ff2e515`

---
*Phase: 33-source-lifecycle-config-auth-cursor-boundary*
*Completed: 2026-05-08*
