---
phase: 39-surrealdb-native-retrieval-contract
plan: 01
subsystem: search
tags: [surrealdb, retrieval, contract, migration, evaluation]
requires:
  - phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
    provides: "SurrealDB spike evidence, transform-only import proof, retrieval parity findings, and final recommendation"
provides:
  - "Typed SurrealDB-native retrieval contract vocabulary"
  - "Contract invariant tests for retrieval surfaces, accepted differences, cutover gates, and migration reuse"
  - "Durable architecture doc and phase-local handoff for Phases 40-43"
affects: [phase-40, phase-41, phase-42, phase-43, surrealdb, search, migration]
tech-stack:
  added: []
  patterns:
    - "Policy-only contract module with no storage/runtime dependencies"
    - "Quality-difference vocabulary replaces old-stack rank parity as the cutover target"
key-files:
  created:
    - backend/src/dotmd/search/surreal_contract.py
    - backend/tests/search/test_surreal_contract.py
    - docs/surrealdb-native-retrieval-contract.md
    - .planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md
    - .planning/phases/39-surrealdb-native-retrieval-contract/39-01-SUMMARY.md
  modified: []
key-decisions:
  - "The old SQLite/sqlite-vec/FTS5 + FalkorDB stack is baseline/evaluator only, not a product compatibility target."
  - "Exact old-stack rank parity is not required; differences are classified as improvement, harmless reorder, regression, or unclear."
  - "Regressions block cutover and unclear differences require explicit acceptance."
  - "Existing chunks, embeddings, source refs, graph relations, feedback, cursors, and checkpoints should be preserved where practical."
  - "No runtime fallback backend or productized compatibility shims remain after cutover acceptance."
patterns-established:
  - "SurrealRetrievalContract can be imported by later evaluators without constructing SQLite, FalkorDB, TEI, or SurrealDB clients."
  - "Migration reuse policy is part of the retrieval contract, preventing clean-room reindex assumptions."
requirements-completed: [SURR-RET-01, SURR-RET-02, SURR-RET-03, SURR-MIG-02]
duration: 24 min
completed: 2026-06-13
status: complete
---

# Phase 39 Plan 01: SurrealDB-Native Retrieval Contract Summary

**Policy-only SurrealDB retrieval contract with quality-difference gates, migration reuse constraints, and no fallback/compatibility-shim posture**

## Performance

- **Duration:** 24 min
- **Started:** 2026-06-12T21:01:00Z
- **Completed:** 2026-06-12T21:25:12Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added RED/GREEN contract invariant coverage for required retrieval surfaces, accepted differences, cutover gates, and migration reuse policy.
- Implemented `surreal_contract.py` as a dependency-free policy module for Phase 40 evaluation and Phase 43 shadow-run reporting.
- Documented the durable SurrealDB-native retrieval contract and phase-local handoff for Phases 40-43.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED contract invariant tests** - `174dd68` (test)
2. **Task 2: Implement the typed retrieval contract module** - `9bdec64` (feat)
3. **Task 3: Write human-readable contract and phase handoff** - `d908369` (docs)

## Files Created/Modified

- `backend/src/dotmd/search/surreal_contract.py` - typed retrieval contract vocabulary and default policy factory
- `backend/tests/search/test_surreal_contract.py` - invariant tests for contract policy
- `docs/surrealdb-native-retrieval-contract.md` - durable architecture contract
- `.planning/phases/39-surrealdb-native-retrieval-contract/39-RETRIEVAL-CONTRACT.md` - phase-local handoff and downstream constraints

## Decisions Made

- The old stack is a baseline/evaluator, not a product compatibility target.
- SurrealDB cutover quality is judged through accepted-difference categories, not exact rank parity.
- Regression blocks cutover; unclear differences require explicit acceptance.
- Migration reuse is part of the retrieval contract so later phases do not assume clean-room reindexing.
- Runtime fallback backends and productized compatibility shims are forbidden after cutover acceptance.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 40 can now build golden queries and diff reports using `AcceptedDifference`
and `CutoverGate`. Phase 41 must preserve the migration reuse targets where
practical. Phase 42 implements the five retrieval surfaces, and Phase 43 uses
the contract to classify shadow-run differences.

## Self-Check: PASSED

- Summary file exists on disk.
- All claimed task artifacts exist on disk.
- Task commits `174dd68`, `9bdec64`, and `d908369` are present in git history.
- Plan verification commands passed.

---
*Phase: 39-surrealdb-native-retrieval-contract*
*Completed: 2026-06-13*
