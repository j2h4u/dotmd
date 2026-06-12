---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
plan: 04
subsystem: database
tags: [surrealdb, operations, rollback, recommendation, storage]
requires:
  - phase: 38-03
    provides: retrieval parity gate and failure categories
  - phase: 38-05
    provides: embedded atomicity and writer-safety gate
provides:
  - copied-store backup/restore rehearsal helpers
  - current-stack rollback rehearsal helpers
  - conservative migrate/defer/reject recommendation builder
  - final Phase 38 storage recommendation
affects: [storage, surrealdb, roadmap, migration]
tech-stack:
  added: []
  patterns: [operations-gated-recommendation, copied-store-rollback, conservative-migration-gate]
key-files:
  created:
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-SUMMARY.md
  modified:
    - backend/src/dotmd/storage/surreal_ops.py
    - backend/tests/storage/test_surreal_ops_safety.py
key-decisions:
  - "Final Phase 38 recommendation is reject because retrieval parity failed with hybrid/RRF gap."
  - "Operations evidence is spike-sufficient but cannot override STOR-02 failure."
patterns-established:
  - "Migrate is impossible unless transform, parity, scale, backup/restore, rollback, embedded safety, and writer coordination gates all pass."
  - "Rollback rehearsal must return to copied current SQLite/sqlite-vec/FTS5 plus FalkorDB originals."
requirements-completed: [STOR-04]
duration: 20min
completed: 2026-06-12
status: complete
---

# Phase 38 Plan 04: Operations and Recommendation Summary

**Copied-store operations rehearsal and final reject recommendation for Embedded SurrealDB storage migration**

## Performance

- **Duration:** 20 min
- **Started:** 2026-06-12T15:45:00Z
- **Completed:** 2026-06-12T16:05:00Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added operations safety helpers for backup/restore fallback validation, current-stack rollback rehearsal, same-corpus smoke assembly, and conservative recommendation gating.
- Extended `test_surreal_ops_safety.py` with RED/GREEN coverage for STOR-04 operations and recommendation behavior.
- Wrote `38-04-OPERATIONS.md` and `38-RECOMMENDATION.md`; final decision is `Recommendation: reject` with `Failure category: hybrid/RRF gap`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED operations safety and recommendation tests** - `b7edf06` (`test`)
2. **Task 2: Implement operations safety helpers and rehearsal evidence** - `2a061b1` (`feat`)
3. **Task 3: Produce final migrate, defer, or reject recommendation** - `4f66521` (`docs`)

## Files Created/Modified

- `backend/src/dotmd/storage/surreal_ops.py` - Adds operations reports, rollback rehearsal, backup/restore fallback validation, full-pipeline smoke, and recommendation builder.
- `backend/tests/storage/test_surreal_ops_safety.py` - Adds operations and recommendation gate coverage.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-04-OPERATIONS.md` - Records operations evidence.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-RECOMMENDATION.md` - Records final Phase 38 reject recommendation.

## Decisions Made

- Recommendation is `reject`, not `defer`, because Plan 38-03 reported a blocking `reject: hybrid/RRF gap`.
- Surreal remains spike-only; no production wiring into `DotMDService`, `IndexingPipeline`, startup, Docker, or CLI defaults.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocker] Continued inline after subagent quota failure**
- **Found during:** Wave 5 dispatch
- **Issue:** The `38-04` executor hit a provider usage limit before creating files or commits.
- **Fix:** Verified no partial dirty state existed, closed the failed agent, and executed the plan inline using the same GSD close-out order.
- **Files modified:** `backend/src/dotmd/storage/surreal_ops.py`, `backend/tests/storage/test_surreal_ops_safety.py`, `38-04-OPERATIONS.md`, `38-RECOMMENDATION.md`
- **Verification:** `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py -x`; `cd backend && uv run python -m py_compile src/dotmd/storage/surreal_ops.py`
- **Committed in:** `b7edf06`, `2a061b1`, `4f66521`

---

**Total deviations:** 1 auto-fixed (`Rule 3`: 1)
**Impact on plan:** Execution mode changed, but scope and verification stayed aligned with the plan.

## Issues Encountered

- Retrieval parity from Plan 38-03 failed. Plan 38-04 correctly propagated that failure into the final recommendation instead of producing a migrate recommendation.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 38 has enough evidence to close with a reject recommendation for Embedded SurrealDB as a single replacement backend. Future work should not proceed to migration planning unless weighted FTS and hybrid/RRF parity are solved or the architecture is deliberately narrowed to a partial Surreal role.

## Self-Check: PASSED

- Summary file exists on disk.
- All claimed task artifacts exist on disk.
- Task commits are present in `git log --oneline --all`.
- Plan-level verification commands passed.
