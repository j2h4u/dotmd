---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
plan: 05
subsystem: database
tags: [surrealdb, surrealkv, embedded, locking, tdd]
requires:
  - phase: 38-01
    provides: inventory evidence and transform-first migration map for current SQLite/FalkorDB data
provides:
  - verified official `surrealdb` SDK dependency evidence
  - embedded `surrealkv://` atomicity probe and rollback evidence
  - local writer guard with TTL stale recovery and force-release
  - Phase 38 go/no-go gate report for Plan 38-02
affects: [38-02, STOR-04, surrealdb spike]
tech-stack:
  added: [surrealdb]
  patterns: [query_raw embedded transaction probes, sidecar writer guard metadata, gate-report driven phase blocking]
key-files:
  created:
    - backend/src/dotmd/storage/surreal_ops.py
    - backend/tests/storage/test_surreal_ops_safety.py
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-SURREAL-PACKAGE-VERIFY.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-EMBEDDED-SAFETY-GATE.md
  modified:
    - backend/pyproject.toml
    - backend/uv.lock
key-decisions:
  - "Embedded SDK probes use SurrealQL BEGIN/COMMIT via query_raw because client-side begin()/commit() are unsupported on `surrealkv://`."
  - "Single-writer spike safety is enforced with a target-specific sidecar JSON guard that supports TTL stale recovery and explicit force-release."
patterns-established:
  - "Phase gates can block downstream Surreal work with explicit markdown evidence instead of silent assumptions."
  - "Embedded storage probes must run only on local tmp targets and never against live dotMD volumes."
requirements-completed: [STOR-04]
duration: 10 min
completed: 2026-06-12
status: complete
---

# Phase 38 Plan 05: Embedded Safety Gate Summary

**Verified the official `surrealdb` SDK, proved embedded `surrealkv://` commit/rollback semantics on local stores, and added a writer-safety gate before Plan 38-02 schema/import work**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-12T14:30:09Z
- **Completed:** 2026-06-12T14:40:05Z
- **Tasks:** 3
- **Files modified:** 6

## Accomplishments

- Recorded the blocking package checkpoint evidence in `38-05-SURREAL-PACKAGE-VERIFY.md` and added the official `surrealdb` SDK to the backend environment only after that approval record existed.
- Added `surreal_ops.py` with embedded atomicity probes, local single-writer guard helpers, stale-owner TTL recovery, force-release, report writing, and gate assertion helpers.
- Wrote and passed focused TDD coverage for embedded transaction safety and generated `38-05-EMBEDDED-SAFETY-GATE.md` from real local `surrealkv://` probe runs.

## Task Commits

1. **Checkpoint: Approve surrealdb package dependency** - approved in prompt, no repo diff
2. **Task 1: Verify the SurrealDB Python SDK source and add the dependency** - `6f622b4` (`chore`)
3. **Task 2 RED: Prove embedded transaction atomicity and writer safety** - `01e892c` (`test`)
4. **Task 2 GREEN: Implement embedded safety gate and report generation** - `5d721a9` (`feat`)

## Files Created/Modified

- `backend/pyproject.toml` - adds the verified `surrealdb` dependency
- `backend/uv.lock` - locks the new SDK and its transitive runtime dependencies
- `backend/src/dotmd/storage/surreal_ops.py` - embedded atomicity probe, writer guard, gate merge/report helpers
- `backend/tests/storage/test_surreal_ops_safety.py` - TDD coverage for embedded commit/rollback, writer guard, stale TTL, force-release, and control-result blocking
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-SURREAL-PACKAGE-VERIFY.md` - package legitimacy evidence and approval note
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-05-EMBEDDED-SAFETY-GATE.md` - real probe evidence consumed by later Phase 38 plans

## Decisions Made

- Used embedded `query_raw("BEGIN TRANSACTION; ... COMMIT TRANSACTION;")` probes instead of SDK `begin()/commit()` methods because the installed embedded client explicitly rejects client-side transaction APIs.
- Kept writer-safety as a local spike boundary concern with a sidecar metadata guard instead of assuming SurrealKV itself provides the required same-path single-writer coordination guarantees.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The embedded SDK does not support client-side `begin()/commit()` on `surrealkv://`. The implementation treated that as evidence to record, then proved atomicity and rollback through raw SurrealQL transactions instead of stopping on the unsupported client API.
- One acceptance check raced the markdown report write when run in parallel. Re-running the existence and keyword checks sequentially against the written absolute path resolved the verification loop without changing shipped code.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 38-02 can now consume `38-05-EMBEDDED-SAFETY-GATE.md` instead of assuming embedded safety.
- The current gate passed on local `surrealkv://` evidence, but later plans still need migration, retrieval parity, and rollback recommendation work before the full Phase 38 decision is complete.

## Self-Check: PASSED

- Verified required artifacts exist on disk.
- Verified task commit hashes `6f622b4`, `01e892c`, and `5d721a9` exist in git history.
