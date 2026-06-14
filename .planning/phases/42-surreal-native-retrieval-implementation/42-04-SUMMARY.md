---
phase: 42-surreal-native-retrieval-implementation
plan: 04
subsystem: search
tags: [surrealdb, python, hybrid, fusion, tdd]
requires:
  - phase: 42-surreal-native-retrieval-implementation
    provides: surreal native FTS, vector, and graph-direct engines from plans 42-02 and 42-03
  - phase: 39-surrealdb-native-retrieval-contract
    provides: hybrid fusion contract and explainable attribution expectations
provides:
  - explicit Surreal-native engine override builder for the existing service seam
  - optional candidate-pool engine overrides that preserve default runtime behavior
  - hybrid attribution coverage proving Surreal result sets reuse Python RRF and SearchCandidate metadata
affects: [43, 44]
tech-stack:
  added: []
  patterns: [explicit service seam overrides, Python-side hybrid fusion reuse, no-startup-cutover Surreal wiring]
key-files:
  created:
    - backend/src/dotmd/search/surreal_native.py
    - backend/tests/search/test_surreal_native_hybrid.py
  modified:
    - backend/src/dotmd/api/service.py
    - backend/tests/api/test_service_search.py
key-decisions:
  - "Phase 42 keeps Surreal hybrid collection behind an explicit override seam instead of changing DotMDService startup defaults."
  - "Graph enrichment continues to use the existing post-fusion path unless an explicit graph override is passed for test or evaluation use."
  - "Capability-probe artifacts remain unconsumed by service startup, CLI, MCP, and settings construction until later cutover phases."
patterns-established:
  - "Build Surreal-native override sets with the existing service engine names: semantic, keyword, and graph_direct."
  - "Accept only explicit known override keys at collection time and ignore absent or unrelated keys by falling back to the default runtime engines."
requirements-completed: [SURR-SEARCH-04]
duration: 3 min
completed: 2026-06-14
status: complete
---

# Phase 42 Plan 04: Surreal-native retrieval implementation Summary

**Explicit Surreal engine overrides now feed the existing hybrid candidate-pool seam while keeping production startup behavior unchanged**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-14T08:09:43Z
- **Completed:** 2026-06-14T08:12:10Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added RED coverage for the Surreal-native override builder, candidate-pool override behavior, engine attribution on overlapping hits, graph override routing, and the absence of Phase 42 runtime cutover wiring.
- Added `build_surreal_native_engine_overrides()` so evaluation and test code can assemble Surreal FTS, vector, and graph-direct engines without changing `DotMDService` startup defaults.
- Extended `_collect_candidate_pool()` to accept explicit engine overrides while preserving the existing Python `fuse_results()` path, default runtime engines, and post-fusion graph enrichment behavior.

## TDD Notes

- **RED:** `2fc9b7b` added failing hybrid override tests and static scope guards for capability-probe non-consumption.
- **GREEN:** `0b2e8f0` implemented the Surreal override builder and service seam wiring, then passed the focused and phase-wide verification gates.
- **REFACTOR:** None.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED tests for Surreal hybrid fusion through the service seam | `2fc9b7b` | `test` |
| 2 | Implement Surreal native engine overrides and hybrid candidate-pool wiring | `0b2e8f0` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/search/surreal_native.py` - Builds explicit Surreal-native semantic, keyword, and graph-direct engine overrides from `Settings` plus the retrieval schema parameters.
- `backend/src/dotmd/api/service.py` - Accepts optional engine overrides in `_collect_candidate_pool()` while preserving existing defaults and Python-side fusion.
- `backend/tests/search/test_surreal_native_hybrid.py` - Covers the override builder contract, HNSW bound enforcement through the vector engine, and the absence of startup/runtime cutover wiring.
- `backend/tests/api/test_service_search.py` - Covers candidate-pool override routing, optional graph override use, and overlapping engine attribution through `build_candidates()`.

## Decisions Made

- Kept the Surreal-native seam explicit and opt-in: no service constructor wiring, settings toggle, CLI flag, MCP/server startup hook, or fallback backend switch was introduced in this phase.
- Reused the existing `fuse_results()` and `build_candidates()` path instead of adding any Surreal built-in hybrid helper dependency.
- Modeled graph enrichment as a separate optional override so seed-based graph expansion stays post-fusion and does not change the builder’s `semantic` / `keyword` / `graph_direct` contract.

## Verification Output

- `cd backend && uv run pytest tests/search/test_surreal_native_hybrid.py tests/api/test_service_search.py -q` -> PASS (`57 passed, 1 warning`)
- `cd backend && uv run pytest tests/storage/test_surreal_schema_definition.py tests/ingestion/test_surreal_production_migration.py tests/search/test_surreal_native_fts.py tests/search/test_surreal_native_vector.py tests/search/test_surreal_native_graph.py tests/search/test_surreal_native_hybrid.py tests/api/test_service_search.py -q` -> PASS (`105 passed, 1 warning`)
- `cd backend && uv run ruff check src/dotmd/api/service.py src/dotmd/search/surreal_native.py tests/api/test_service_search.py tests/search/test_surreal_native_hybrid.py` -> PASS

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The existing `SearchEngineProtocol` covers peer retrieval engines but not seed-based graph enrichment, so the service seam adds a narrow local protocol for the optional `graph` override without changing the builder’s public key set.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 43 can consume `build_surreal_native_engine_overrides()` directly for explicit old-vs-Surreal shadow runs without changing live runtime defaults.
- Phase 44 still owns any startup/runtime consumer for the Phase 42 capability probe and any production cutover wiring.

## Self-Check

PASSED

- Found `.planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md`
- Found task commits `2fc9b7b` and `0b2e8f0` in git history

---
*Phase: 42-surreal-native-retrieval-implementation*
*Completed: 2026-06-14*
