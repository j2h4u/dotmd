---
phase: 41-production-grade-surreal-schema-and-import
plan: 02
subsystem: database
tags: [surrealdb, python, migration, tdd, schema, import]
requires:
  - phase: 41-production-grade-surreal-schema-and-import
    provides: versioned schema catalog, schema apply-status outcomes, and relation-table constraints from 41-01
provides:
  - production migration manifest/report surface with plan, dry-run, apply, and verify modes
  - explicit overwrite and partial-failure semantics for Surreal imports
  - no-recompute import coverage for embeddings, graph rows, feedback, cursors, checkpoints, and chunk_file_bindings
affects: [41-03, surreal migration runner, cutover reporting, restore planning]
tech-stack:
  added: []
  patterns: [report-first migration runner, explicit overwrite policy, relation-table insert semantics, source-capture manifests]
key-files:
  created:
    - backend/tests/ingestion/test_surreal_production_migration.py
  modified:
    - backend/src/dotmd/ingestion/migrate_surreal.py
    - backend/src/dotmd/storage/surreal.py
    - backend/src/dotmd/storage/surreal_schema.py
    - backend/tests/ingestion/test_surreal_transform_only_migration.py
key-decisions:
  - "Phase 41 migration input is copied SQLite plus materialized graph/feedback export files, and the runner fails closed on truncated or recompute-requiring sources."
  - "Apply mode always inspects target pre-counts, refuses populated targets by default, and only performs destructive replacement under explicit_replace."
  - "Graph edges are imported into the Surreal relation table with INSERT RELATION plus derived section/tag endpoints so rel_type, weight, and properties survive import."
patterns-established:
  - "Build manifest first, then branch into plan/dry-run/apply/verify using the same expected-count and source-capture evidence."
  - "Preserve embedded writer safety and no-recompute guarantees in the runner instead of delegating those checks to ad hoc callers."
requirements-completed: [SURR-MIG-01, SURR-MIG-02, SURR-MIG-03]
duration: 27min
completed: 2026-06-13
status: complete
---

# Phase 41 Plan 02: Production-grade Surreal schema and import Summary

**Production Surreal migration runner with source-capture manifests, explicit overwrite safety, relation-table graph import, and restore-required partial-failure reporting**

## Performance

- **Duration:** 27 min
- **Started:** 2026-06-13T23:30:00+05:00
- **Completed:** 2026-06-13T23:56:37+05:00
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments

- Added RED coverage for the full Phase 41 migration contract: manifest capture, target modes, overwrite policy, verification depth, recompute guards, and partial-write evidence.
- Replaced the Phase 38 `run_surreal_import()` prototype with a typed `build/run/verify` migration surface that preserves stored rows instead of wiping-and-rolling back by default.
- Hardened Surreal storage writes so embedded vectors persist as `array<float>`, schema inspection recognizes current and SCHEMALESS targets, and graph relations land as real `TYPE RELATION` rows.

## TDD Notes

- **RED:** `90ad20f` added the failing production migration contract and moved transform-only coverage onto the new Phase 41 surface.
- **GREEN:** `7135061` implemented the production migration runner, relation-table import semantics, and schema/storage fixes required to satisfy the contract.
- **REFACTOR:** None - the GREEN commit includes the focused correctness fixes discovered while making the contract pass.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED production migration runner tests | `90ad20f` | `test` |
| 2 | Implement plan/dry-run/apply/verify migration semantics | `7135061` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/ingestion/migrate_surreal.py` - New Phase 41 enums, manifest/report dataclasses, source-capture loaders, plan/dry-run/apply/verify runner, and partial-failure reporting.
- `backend/src/dotmd/storage/surreal.py` - Schema-owned table clearing, stronger schema inspection, relation-table insert handling, graph row replacement helpers, and cursor/vector import fixes.
- `backend/src/dotmd/storage/surreal_schema.py` - Embedding/vector component field typing upgrades and preserved graph entity identifiers.
- `backend/tests/ingestion/test_surreal_production_migration.py` - Behavior-first contract coverage for production migration semantics.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py` - Updated transform-only invariants to assert the old runner is replaced and that the Phase 41 runner preserves stored data.
- `.planning/phases/41-production-grade-surreal-schema-and-import/41-02-SUMMARY.md` - Execution summary for this plan.

## Decisions Made

- Kept graph and feedback import on export-file inputs so the runner can record checksums, timestamps, and skew policy in a source-capture manifest before any claimed parity.
- Used `phase41_migration` as the target database default for the new runner while leaving retrieval and runtime cutover out of scope for this plan.
- Verified imported embeddings against stored `text_hash`, `vector_rowid`, and `array<float>` payloads instead of treating vector presence alone as success.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Explicit-replace apply was re-running DDL against existing tables**
- **Found during:** Task 2
- **Issue:** Clearing rows and immediately replaying `DEFINE TABLE` statements failed on already-existing Phase 41 tables.
- **Fix:** Reused the existing schema on explicit replacement and refreshed the `schema_meta` sentinel separately.
- **Files modified:** `backend/src/dotmd/ingestion/migrate_surreal.py`
- **Verification:** Focused pytest gate passed explicit-replace coverage.
- **Committed in:** `7135061`

**2. [Rule 1 - Bug] Relation rows could not be imported with plain upserts into a `TYPE RELATION` table**
- **Found during:** Task 2
- **Issue:** Surreal rejected graph edge upserts because relation rows require relation semantics with `in` / `out` endpoints.
- **Fix:** Switched graph edge import to `INSERT RELATION INTO relations` with derived section/tag endpoints and encoded relation IDs.
- **Files modified:** `backend/src/dotmd/storage/surreal.py`
- **Verification:** Focused pytest gate passed graph relation preservation checks.
- **Committed in:** `7135061`

**3. [Rule 1 - Bug] Embedded vector payloads and schema inspection were producing false verification failures**
- **Found during:** Task 2
- **Issue:** `array`-typed embedding fields stored empty lists, and schema inspection missed the `schema_meta` sentinel plus SCHEMALESS table definitions.
- **Fix:** Changed vector fields to `array<float>` and switched schema inspection to read `schema_meta` rows and `INFO FOR DB` table definitions.
- **Files modified:** `backend/src/dotmd/storage/surreal.py`, `backend/src/dotmd/storage/surreal_schema.py`
- **Verification:** Focused pytest gate passed embedding reuse, schema-mismatch, and vector-dimension assertions.
- **Committed in:** `7135061`

---

**Total deviations:** 3 auto-fixed (3 bug fixes)
**Impact on plan:** All auto-fixes were required for correctness and production-grade import semantics. No retrieval or cutover scope was added.

## Issues Encountered

- `AGENTS.md` still states `main` as the generic working branch, but this phase was already active on `milestone/v1.8-surrealdb-cutover` and the user explicitly targeted that checkout. Execution stayed on current HEAD to avoid rewriting user-owned branch state.

## Verification Output

- `cd backend && uv run pytest tests/ingestion/test_surreal_production_migration.py tests/ingestion/test_surreal_transform_only_migration.py tests/storage/test_surreal_schema_definition.py -x` -> PASS (`18 passed`)
- `cd backend && uv run ruff check src/dotmd/ingestion/migrate_surreal.py src/dotmd/storage/surreal.py src/dotmd/storage/surreal_schema.py tests/ingestion/test_surreal_production_migration.py tests/ingestion/test_surreal_transform_only_migration.py` -> PASS

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 41-03 can build report/export artifacts on top of the new manifest, phase checkpoint, and restore-required failure surfaces.
- Retrieval behavior, shadow-run execution, production cutover, and legacy deletion remain untouched, which keeps the Phase 41 boundary intact.

## Self-Check

PASSED

- Found `.planning/phases/41-production-grade-surreal-schema-and-import/41-02-SUMMARY.md`
- Found task commits `90ad20f` and `7135061` in git history

---
*Phase: 41-production-grade-surreal-schema-and-import*
*Completed: 2026-06-13*
