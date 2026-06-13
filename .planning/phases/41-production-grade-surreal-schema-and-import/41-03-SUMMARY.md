---
phase: 41-production-grade-surreal-schema-and-import
plan: 03
subsystem: database
tags: [surrealdb, migration, evidence, devtools, docs, tdd]
requires:
  - phase: 41-production-grade-surreal-schema-and-import
    provides: production migration manifest, overwrite policy, checkpoints, and no-recompute runner semantics
provides:
  - restore manifests with verified fallback rehearsal semantics
  - JSON and Markdown migration evidence reports for operator review
  - repo-local Phase 41 migration runner and operator runbook
affects: [42, 43, 44, migration evidence review, operator rehearsal]
tech-stack:
  added: []
  patterns: [report-first migration evidence, verified fallback restore rehearsal, fail-closed devtool runner]
key-files:
  created:
    - backend/devtools/surreal_migration_runner.py
    - backend/tests/devtools/test_surreal_migration_runner.py
    - docs/surrealdb-production-migration.md
  modified:
    - backend/src/dotmd/storage/surreal_ops.py
    - backend/tests/storage/test_surreal_ops_safety.py
    - backend/tests/ingestion/test_surreal_production_migration.py
key-decisions:
  - "Restore evidence never claims success from CLI absence alone; fallback restore requires a rehearsal target plus count and smoke verification."
  - "The devtool runner validates graph and feedback JSON before invoking the core migration runner so syntax and row-shape failures stay operator-readable."
  - "Evidence artifacts preserve non-ASCII content with ensure_ascii=False and expose explicit sample redaction controls."
requirements-completed: [SURR-MIG-02, SURR-MIG-03]
duration: 10min
completed: 2026-06-14
status: complete
---

# Phase 41 Plan 03: Production-grade Surreal schema and import Summary

**Migration evidence reports, verified restore rehearsal, fail-closed repo-local runner, and operator runbook for the Phase 41 import path**

## Performance

- **Duration:** 10 min
- **Started:** 2026-06-14T00:02:07+05:00
- **Completed:** 2026-06-14T00:12:33+05:00
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Added RED coverage for restore manifests, evidence classification, malformed JSON handling, runner flag validation, non-ASCII report output, and fail-closed apply behavior.
- Implemented `SurrealRestoreManifest`, `SurrealMigrationEvidenceReport`, evidence classification/writing helpers, and a standalone `devtools/surreal_migration_runner.py`.
- Added `docs/surrealdb-production-migration.md` to document the copied-source operator flow, report fields, restore semantics, redaction controls, and the strict Phase 41 scope boundary.

## TDD Notes

- **RED:** `fc046ba` added the failing restore/report/runner tests and confirmed the missing Phase 41 evidence surface by import failure.
- **GREEN:** `71b4492` implemented the evidence helpers and repo-local runner, then passed the focused Phase 41 suite.
- **REFACTOR:** None as a separate commit. Verification-gate cleanup was folded into the documentation task commit because `just verify` was a required Task 3 acceptance gate.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED restore, report, and runner tests | `fc046ba` | `test` |
| 2 | Implement evidence reports, restore manifests, and devtool runner | `71b4492` | `feat` |
| 3 | Document the production migration operator flow and scope boundary | `dc89795` | `docs` |

## Files Created/Modified

- `backend/src/dotmd/storage/surreal_ops.py` - Added restore-manifest and evidence-report dataclasses, false-success blocking logic, and JSON/Markdown report writers.
- `backend/devtools/surreal_migration_runner.py` - Added the Phase 41 repo-local CLI wrapper with explicit modes, target modes, input validation, restore rehearsal, and report artifact writing.
- `backend/tests/storage/test_surreal_ops_safety.py` - Extended safety coverage for restore-manifest semantics, report classification, and non-ASCII/redacted evidence output.
- `backend/tests/devtools/test_surreal_migration_runner.py` - Added runner coverage for CLI flags, malformed JSON distinction, unsafe apply failure, and Unicode report artifacts.
- `docs/surrealdb-production-migration.md` - Added the operator/developer runbook for Phase 41 source capture, apply gating, verification, restore evidence, and scope limits.
- `backend/tests/ingestion/test_surreal_production_migration.py` - Tightened the helper typing so the repo pyright ratchet stayed at baseline during full verification.

## Decisions Made

- `report` mode stays a reporting/verification surface on top of the existing Phase 41 migration runner instead of becoming a second migration engine.
- Embedded-local restore rehearsal uses explicit copied backup and restored target evidence so fallback verification is concrete rather than documentation-only.
- The runner records explicit owner, redaction, and sample-limit metadata in the evidence payload to support later Phase 43/44 review without adding cutover behavior here.

## Verification Output

- `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py tests/devtools/test_surreal_migration_runner.py -x` -> PASS (`18 passed`)
- `cd backend && uv run pytest tests/storage/test_surreal_ops_safety.py tests/devtools/test_surreal_migration_runner.py tests/ingestion/test_surreal_production_migration.py -x` -> PASS (`27 passed`)
- `cd backend && just verify` -> PASS (`ruff format --check`, strict `ruff check`, `pyright_ratchet`, `lint-imports`, `actionlint`, `compileall`, `vulture`, and `pytest -q -m "not e2e and not smoke"`; final pytest gate `615 passed, 36 deselected, 1 warning`)

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking Issue] Restored the full verify gate on the active Phase 41 branch**
- **Found during:** Task 3
- **Issue:** `just verify` failed on formatting drift, strict lint findings, and pyright regressions across the active Phase 41 Surreal files and tests.
- **Fix:** Formatted the affected Phase 41 files, addressed the local strict-lint findings, and tightened test typing so the pyright ratchet returned to baseline.
- **Files modified:** `backend/devtools/surreal_migration_runner.py`, `backend/src/dotmd/ingestion/migrate_surreal.py`, `backend/src/dotmd/storage/surreal.py`, `backend/src/dotmd/storage/surreal_ops.py`, `backend/src/dotmd/storage/surreal_schema.py`, `backend/tests/devtools/test_surreal_migration_runner.py`, `backend/tests/ingestion/test_surreal_production_migration.py`, `backend/tests/ingestion/test_surreal_transform_only_migration.py`, `backend/tests/storage/test_surreal_ops_safety.py`, `backend/tests/storage/test_surreal_schema_definition.py`, `backend/tests/storage/test_surreal_storage_contract.py`
- **Verification:** `cd backend && just verify`
- **Committed in:** `dc89795`

**Total deviations:** 1 auto-fixed (1 blocking issue)
**Impact on plan:** The extra cleanup did not expand feature scope. It was required to satisfy the plan’s full verification gate on the current Phase 41 branch.

## Issues Encountered

- `AGENTS.md` still describes `main` as the general working branch, but this execution target was explicitly the existing `milestone/v1.8-surrealdb-cutover` checkout. Work stayed on current HEAD to avoid rewriting active branch state.
- Per user instruction, `STATE.md` and `ROADMAP.md` were intentionally not updated by this plan executor. The close-out here is limited to task commits plus this summary artifact.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no production restart, package install, or new secret was required.

## Next Phase Readiness

- Phase 42 can consume the new evidence and restore artifacts without reworking the Phase 41 import runner.
- Phase 43/44 now have operator-readable JSON/Markdown evidence, explicit restore status values, and documented sample-redaction guidance.
- Retrieval implementation, shadow-run execution, cutover, fallback, and legacy deletion remain intentionally untouched.

## Self-Check

PASSED

- Found `.planning/phases/41-production-grade-surreal-schema-and-import/41-03-SUMMARY.md`
- Found task commits `fc046ba`, `71b4492`, and `dc89795` in git history

---
*Phase: 41-production-grade-surreal-schema-and-import*
*Completed: 2026-06-14*
