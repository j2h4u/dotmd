---
phase: 42-surreal-native-retrieval-implementation
plan: 03
subsystem: search
tags: [surrealdb, python, graph, retrieval, tdd]
requires:
  - phase: 42-surreal-native-retrieval-implementation
    provides: retrieval indexes, target-id relation index, and embedded Surreal test fixture
  - phase: 39-surrealdb-native-retrieval-contract
    provides: surreal-native graph/entity retrieval semantics
provides:
  - relation-backed Surreal graph direct engine
  - target_id-indexed graph retrieval without scan_table hot-path scans
  - embedded Surreal graph retrieval tests covering relation metadata rows
affects: [42-04, 43]
tech-stack:
  added: []
  patterns: [fixed SurrealQL with bound variables, weighted graph score normalization, embedded relation-table assertions]
key-files:
  created:
    - backend/src/dotmd/search/surreal_graph.py
    - backend/tests/search/test_surreal_native_graph.py
  modified: []
key-decisions:
  - "Surreal graph retrieval keeps GraphDirectEngine's n-gram matcher but swaps chunk lookup to one bounded relations query filtered by target_id and rel_type."
  - "Relation rows are scored from flat source_id/target_id/rel_type/weight fields even when TYPE RELATION rows also expose Surreal in/out endpoints."
patterns-established:
  - "Use fixed relation-table SELECT statements with entity names and allowed relation labels passed only as data variables."
  - "Embedded Surreal graph tests should insert relation rows with RELATE so assertions exercise real TYPE RELATION storage semantics."
requirements-completed: [SURR-SEARCH-03]
duration: 6min
completed: 2026-06-14
status: complete
---

# Phase 42 Plan 03: Surreal-native retrieval implementation Summary

**Relation-backed Surreal graph direct retrieval with indexed target-id lookup, weighted chunk scoring, and embedded TYPE RELATION verification**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-14T12:55:00+05:00
- **Completed:** 2026-06-14T13:01:00+05:00
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added RED coverage for one-time entity catalog loading, GraphDirect-style n-gram matching, indexed relation lookups, weighted normalization, and fail-soft graph search behavior.
- Implemented `SurrealGraphDirectEngine` with a fixed `relations` query that filters by `target_id` and allowed `rel_type` values instead of scanning relation rows in Python.
- Proved the engine against embedded Surreal `TYPE RELATION` rows created with `RELATE`, including rows that expose both Surreal endpoints and dotMD's flat relation metadata fields.

## TDD Notes

- **RED:** `3e310dd` added the failing graph retrieval tests and the mandatory embedded Surreal assertion.
- **GREEN:** `d502537` implemented the relation-backed graph engine, weighted score aggregation, deterministic sorting, and fail-soft logging.
- **REFACTOR:** None.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED tests for relation-backed graph direct retrieval | `3e310dd` | `test` |
| 2 | Implement Surreal relation-backed graph direct engine | `d502537` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/search/surreal_graph.py` - Surreal graph direct engine with load-once entity catalog, fixed relation query, weighted aggregation, and deterministic normalization.
- `backend/tests/search/test_surreal_native_graph.py` - Focused RED/GREEN coverage for catalog loading, query shape, relation metadata handling, fail-soft behavior, and embedded relation retrieval.

## Decisions Made

- Kept the query-text matching policy identical to `GraphDirectEngine` and limited the Surreal-native change to entity catalog loading plus relation-backed chunk retrieval.
- Bound only `entity_names`, `allowed_rel_types`, and `limit` as Surreal variables; user query text never shapes Surreal identifiers or statement structure.
- Used `source_table = 'sections'` in the relation query so graph retrieval returns chunk-backed section hits only.

## Verification Output

- `cd backend && uv run pytest tests/search/test_surreal_native_graph.py -q` -> PASS (`8 passed`)
- `cd backend && uv run ruff check src/dotmd/search/surreal_graph.py tests/search/test_surreal_native_graph.py` -> PASS

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Embedded Surreal `TYPE RELATION` rows could not be inserted with direct `create()` calls; the integration test had to use real `RELATE` statements so the stored rows carried valid `in`/`out` endpoints.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 42-04 can treat the graph engine as a peer retrieval surface alongside the already-shipped FTS and vector engines.
- Phase 43 can reuse the embedded graph tests as a contract baseline while comparing old-stack versus Surreal graph/entity behavior.

## Self-Check

PASSED

- Found `.planning/phases/42-surreal-native-retrieval-implementation/42-03-SUMMARY.md`
- Found task commits `3e310dd` and `d502537` in git history

---
*Phase: 42-surreal-native-retrieval-implementation*
*Completed: 2026-06-14*
