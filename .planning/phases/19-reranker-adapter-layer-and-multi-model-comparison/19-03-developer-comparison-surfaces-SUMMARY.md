---
phase: 19-reranker-adapter-layer-and-multi-model-comparison
plan: 03-developer-comparison-surfaces
subsystem: search
tags: [reranker, comparison, fastapi, cli, diagnostics]

requires:
  - phase: 19-reranker-adapter-layer-and-multi-model-comparison
    provides: shared candidate pool and factory-backed runtime reranker selection
provides:
  - Developer reranker comparison over one shared candidate pool
  - Runtime reranker selection through FastAPI and CLI
  - Typed FastAPI comparison response validation
  - CLI diagnostics for latency, scores, top IDs, overlap, and per-reranker errors
affects: [phase-19, api-service, fastapi, cli, reranker-comparison]

tech-stack:
  added: []
  patterns:
    - Service TypedDict diagnostic payloads validated by FastAPI Pydantic models
    - Developer-only comparison route and CLI command outside MCP
    - TDD RED/GREEN commits per comparison surface

key-files:
  created:
    - backend/tests/test_cli.py
    - .planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-03-developer-comparison-surfaces-SUMMARY.md
  modified:
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/api/server.py
    - backend/src/dotmd/cli.py
    - backend/tests/api/test_service_search.py

key-decisions:
  - "Unknown reranker names propagate as ValueError from service comparison and are translated at FastAPI/CLI boundaries."
  - "Comparison overlap uses only successful rerankers, with the first successful reranker named as the reference."
  - "MCP search schema remains unchanged; developer comparison is exposed only through FastAPI and CLI."

patterns-established:
  - "compare_rerankers expands once, collects candidates once, then runs each reranker over the same ordered chunk IDs."
  - "FastAPI uses RerankerComparisonResponse.model_validate(comparison) instead of raw ** unpacking."
  - "CLI rerank compare prints shared pool size, per-reranker diagnostics, overlap reference, and overlap map."

requirements-completed:
  - RERANK-SELECT-04
  - RERANK-COMPARE-01
  - RERANK-LATENCY-01

duration: 5min
completed: 2026-05-01
---

# Phase 19 Plan 03: Developer Comparison Service, API, and CLI Surfaces Summary

**Developer reranker comparison over one shared retrieval pool with typed FastAPI output and CLI diagnostics**

## Performance

- **Duration:** 5min
- **Started:** 2026-05-01T12:28:32Z
- **Completed:** 2026-05-01T12:33:39Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Added `DotMDService.compare_rerankers()` with one query expansion, one `_collect_candidate_pool()` call, per-reranker timing, ordered top IDs, scores, error isolation, and overlap diagnostics.
- Added `GET /search?reranker=...` and `GET /rerank/compare` with typed Pydantic response validation and HTTP 400 for unknown reranker names.
- Added `dotmd search --reranker ...` and `dotmd rerank compare ...` with readable diagnostic output and Click-friendly unknown-name errors.
- Added focused service/API/CLI tests proving shared-pool reuse, partial failure behavior, schema validation, runtime selection, and developer comparison output.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: Add failing service comparison tests** - `a1817b1` (test)
2. **Task 1 GREEN: Add service reranker comparison** - `17b1cc6` (feat)
3. **Task 2 RED: Add failing FastAPI reranker surface tests** - `8933d2b` (test)
4. **Task 2 GREEN: Expose FastAPI reranker comparison** - `c66859e` (feat)
5. **Task 3 RED: Add failing CLI reranker surface tests** - `590dd9b` (test)
6. **Task 3 GREEN: Expose CLI reranker comparison** - `59219b1` (feat)

## Files Created/Modified

- `backend/src/dotmd/api/service.py` - Added comparison TypedDicts and `compare_rerankers()` diagnostic flow over the shared candidate pool.
- `backend/src/dotmd/api/server.py` - Added runtime reranker query parameter, comparison response models, and `/rerank/compare` route.
- `backend/src/dotmd/cli.py` - Added `search --reranker` and `rerank compare` developer diagnostics.
- `backend/tests/api/test_service_search.py` - Added service and FastAPI coverage for comparison behavior and runtime reranker selection.
- `backend/tests/test_cli.py` - Added CLI tests for runtime selection, comparison output, and unknown-name errors.

## Decisions Made

- Unknown reranker names are not converted into per-reranker diagnostic rows; they remain selection errors and are translated to HTTP 400 or Click errors at the user-facing boundary.
- Comparison uses the first successful reranker as `overlap_reference`; failed rerankers are excluded from overlap maps to avoid misleading zero-overlap diagnostics.
- The existing MCP tool schema was intentionally left untouched.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

The plan referenced `backend/tests/test_cli.py`, which did not exist in this checkout because prior CLI tests live under `backend/tests/cli/`. The task itself listed `backend/tests/test_cli.py` as the target file and verification path, so the new comparison CLI coverage was added there.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. Stub-pattern scan only found intentional empty collections/defaults in implementation and mocked empty values in tests.

## Threat Flags

None. The new developer FastAPI route was already covered by the plan threat model and MCP remained unchanged.

## Verification

- `cd backend && uv run pytest tests/api/test_service_search.py -q` - PASS (`10 passed`, warnings only from existing pydantic-settings TOML warning)
- `cd backend && uv run pytest tests/test_cli.py -q` - PASS (`3 passed`, warnings only)
- `cd backend && uv run pytest tests/api/test_service_search.py tests/test_cli.py -q` - PASS (`13 passed`, warnings only)
- `cd backend && uv run ruff check src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/api/test_service_search.py tests/test_cli.py` - PASS

## Next Phase Readiness

Ready for Plan 04 to document and verify latency expectations using the developer comparison surfaces without changing production MCP search behavior.

## Self-Check: PASSED

- Confirmed key files and summary exist on disk.
- Confirmed task commits exist: `a1817b1`, `17b1cc6`, `8933d2b`, `c66859e`, `590dd9b`, `59219b1`.
- Confirmed `.planning/STATE.md` remains uncommitted because it was pre-existing orchestrator-owned local state.

---
*Phase: 19-reranker-adapter-layer-and-multi-model-comparison*
*Completed: 2026-05-01*
