---
phase: 43-shadow-run-and-quality-gate
plan: 03
subsystem: storage-migration
tags: [surrealdb, migration, shadow-run, evidence, instrumentation]
requires:
  - phase: 41-production-grade-surreal-schema-and-import
    provides: "Surreal migration runner, schema, import evidence, and embedded-local restore rehearsal"
  - phase: 43-shadow-run-and-quality-gate
    provides: "Plan 43-02 shadow-run runner, manifest inputs, and quality-gate artifact contract"
provides:
  - "Verified production-derived SurrealKV migration target in local cache"
  - "Idempotent/resumable migration fixes for fingerprints, graph replacement, entity defaults, and expanded graph counts"
  - "Progress telemetry covering source_capture, migration phases, verification, restore_rehearsal, and reporting"
  - "Documented partial execution state: original shadow-run result artifacts are still not produced"
affects: [phase-43, phase-44, surrealdb, migration, shadow-run, production-cutover]
tech-stack:
  added: []
  patterns:
    - "Migration evidence uses cache-local large artifacts instead of committing SurrealKV stores into .planning"
    - "Resume-safe progress checkpoints must preserve previously applied migration phases"
    - "Expanded graph expected counts must match synthetic section/entity/tag records created from relations"
key-files:
  created:
    - .planning/phases/43-shadow-run-and-quality-gate/43-03-SUMMARY.md
  modified:
    - backend/src/dotmd/ingestion/migrate_surreal.py
    - backend/src/dotmd/storage/surreal.py
    - backend/devtools/surreal_migration_runner.py
    - backend/tests/ingestion/test_surreal_transform_only_migration.py
    - backend/tests/ingestion/test_surreal_production_migration.py
    - backend/tests/devtools/test_surreal_migration_runner.py
key-decisions:
  - "Do not claim Plan 43-03 complete: the original shadow-run baseline/candidate/diff/metric artifacts were not produced."
  - "Keep migrated embeddings table SCHEMALESS after bulk load because Surreal schemafull validation over large vector records failed with a segment-size internal error."
  - "Use the verified cache-local SurrealKV target as migration evidence, while keeping large DB artifacts out of .planning."
patterns-established:
  - "Long migration/rehearsal runs must expose named progress phases before expensive work starts."
  - "Restore rehearsal can use validated fallback copy evidence when the Surreal CLI is unavailable."
  - "GSD summaries for partially executed plans must record the gap instead of advancing cutover readiness."
requirements-completed:
  - SURR-CUT-01
  - SURR-EVAL-03
  - SURR-SEARCH-02
duration: multi-hour
completed: 2026-06-16
status: partial
---

# Phase 43 Plan 03: Migration Evidence and Instrumentation Summary

**Verified the production-derived Surreal migration target and fixed the opaque/idempotency failures that blocked Phase 43, but did not produce the original shadow-run quality artifacts**

## Performance

- **Duration:** Multi-hour debugging and migration rehearsal session
- **Started:** 2026-06-16
- **Completed:** 2026-06-16
- **Tasks:** Partial execution of Plan 43-03 plus prerequisite migration-runner remediation
- **Files modified:** 6 source/test files plus this summary

## Accomplishments

- Produced a verified embedded-local SurrealKV migration target:
  `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db`
  (`3.8G` after cleanup).
- Final migration evidence report is verified:
  `/home/j2h4u/.cache/dotmd/phase43-target/report.md`
  reports `report_status: verified`, `restore_status: verified_with_fallback`,
  and `unresolved_blockers: none`.
- Verified imported counts match expected counts, including:
  `chunks=149801`, `embeddings=149801`, `documents=1433`,
  `graph_relations=354618`, `graph_entities=52869`,
  `graph_sections=46775`, `graph_tags=326`, and `feedback=5`.
- Added migration fixes needed for idempotent/resumable production-derived apply:
  fingerprint dedupe, graph table cleanup before replacement, graph defaults,
  expanded graph expected counts, and resume-safe progress phases.
- Added operator-visible progress coverage across:
  `source_capture -> migration phases -> verification -> restore_rehearsal -> reporting`.
- Removed temporary `.backup` and `.restored` SurrealKV copies after each
  verified rehearsal, leaving only the main target and small evidence JSON/MD
  files in `/home/j2h4u/.cache/dotmd/phase43-target/`.

## Task Commits

The work landed as a sequence of focused fixes:

1. **Deduplicate source fingerprints** - `f1918d5`
2. **Defer embedding indexes during bulk migration** - `ea5c255`
3. **Bulk load embeddings without schema validation** - `f010377`
4. **Avoid schemafull validation for migrated embeddings** - `dd6730c`
5. **Backfill graph section document refs** - `48e15ac`
6. **Make graph replacement idempotent** - `1affc32`
7. **Clear graph tables before migration graph replace** - `d9987b3`
8. **Default graph entity relation metadata** - `f7d59aa`
9. **Verify expanded graph migration counts** - `2702674`
10. **Expose migration verification progress** - `091c7af`
11. **Expose source capture progress** - `41921da`

Earlier progress-formatting commits for this same plan:

- `5aca0b6` - instrument migration batch progress
- `4cc10a1` - add migration ETA telemetry
- `6bfbe83` - simplify long ETA formatting
- `bd6d948` - omit zero seconds in ETA

## Files Created/Modified

- `backend/src/dotmd/ingestion/migrate_surreal.py` - streaming/count-aware migration fixes, graph expected-count expansion, verification progress, source-capture phase support, ETA behavior.
- `backend/src/dotmd/storage/surreal.py` - graph replacement/idempotency/default payload fixes.
- `backend/devtools/surreal_migration_runner.py` - restore/report/source-capture progress, duplicate manifest-build removal, fallback restore rehearsal reporting.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py` - coverage for expanded graph expected counts and migration behavior.
- `backend/tests/ingestion/test_surreal_production_migration.py` - coverage for verification checkpoint reporting.
- `backend/tests/devtools/test_surreal_migration_runner.py` - coverage for final progress chain and restore evidence.

## Evidence Produced

Cache-local evidence, intentionally not committed to `.planning`:

- `/home/j2h4u/.cache/dotmd/phase43-source/index.db` - source SQLite snapshot (`2.4G`)
- `/home/j2h4u/.cache/dotmd/phase43-source/graph-export.json` - graph export (`121M`)
- `/home/j2h4u/.cache/dotmd/phase43-source/feedback-export.json` - feedback export
- `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db` - verified SurrealKV target (`3.8G`)
- `/home/j2h4u/.cache/dotmd/phase43-target/report.md` - verified evidence report
- `/home/j2h4u/.cache/dotmd/phase43-target/progress.json` - final progress chain
- `/home/j2h4u/.cache/dotmd/phase43-target/restore-manifest.json` - fallback restore verification

Repo-local artifacts that still exist from the original Plan 43-03 setup:

- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture-expected.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-config.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/metrics-replay-queries.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/accepted-diffs.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/preflight-failure.md`

## Verification Output

- `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py tests/ingestion/test_surreal_production_migration.py tests/devtools/test_surreal_migration_runner.py -q`
  -> PASS (`32 passed`)
- `cd backend && uv run ruff check src/dotmd/ingestion/migrate_surreal.py devtools/surreal_migration_runner.py tests/devtools/test_surreal_migration_runner.py tests/ingestion/test_surreal_production_migration.py`
  -> PASS
- Live resume-run against `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db`
  -> PASS; final `report_status: verified`, `restore_status: verified_with_fallback`,
  blockers `[]`.

## Decisions Made

- The final migrated `embeddings` table remains `SCHEMALESS`. Returning it to
  `SCHEMAFULL` after bulk load ran for roughly an hour and failed with:
  `Record is too large to fit in a segment. Increase max segment size`.
  Retrieval indexes are still rebuilt; this is a migration safety tradeoff, not
  a silent omission.
- Graph expected counts now reflect the writer's real behavior: relations can
  synthesize missing section/entity/tag nodes, so expected counts must use set
  union semantics, not `max(existing, derived)`.
- Large migration artifacts belong under `/home/j2h4u/.cache/dotmd/`, not under
  `.planning/`, to avoid turning planning docs into multi-GB database storage.
- Phase 43 cannot advance to production cutover solely on this evidence because
  the original old-stack-vs-Surreal shadow-run result artifacts were not created.

## Deviations from Plan

### Scope completed instead of original shadow-run capture

- **Planned:** Run the Phase 43 shadow runner to produce baseline/candidate
  result JSONL, diffs, summary, scale metrics, and memory metrics.
- **Actual:** The session focused on making the production-derived Surreal target
  safe, resumable, verified, and observable. This was necessary because the
  prior preflight failed before trustworthy shadow capture could begin.
- **Impact:** Plan 43-03 is not plan-complete. It now has a verified candidate
  migration target, but the quality comparison artifacts are still missing.

### Artifact gap

The following Plan 43-03 output artifacts are still not present in the repo:

- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/baseline-results.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-results.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-diffs.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-summary.md`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/scale-metrics.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/memory-metrics.json`

---

**Total deviations:** 2 material deviations.
**Impact on plan:** The migration/preflight blocker is resolved, but Phase 43
shadow quality evidence remains incomplete and must be completed or explicitly
replanned before Phase 44 production cutover.

## Issues Encountered

- Initial migration runs were opaque, slow, and not sufficiently instrumented.
  Progress now persists named phases and ETA formatting no longer emits useless
  `5m 0s` style output.
- Target directories temporarily grew by additional `3.8G` backup/restored
  copies during fallback restore rehearsal. These were deleted after verified
  reports.
- The old graph export lacked fields required by the Surreal graph schema; the
  migration now supplies `document_ref`, `schema_version`, and `metadata`
  defaults where needed.
- The original graph expected-count gate undercounted synthetic records created
  from relations; this made a good target look blocked until expected-count
  logic matched writer behavior.

## User Setup Required

None for the migration evidence target.

Do not proceed to production cutover from this summary alone. The missing
shadow-run quality artifacts require either:

1. completing the original `43-03` runner capture against the verified target, or
2. explicitly replanning Phase 43 so the migration evidence report replaces the
   original shadow-run gate by decision.

## Next Phase Readiness

Phase 44 is not ready yet.

Ready:

- A verified SurrealKV candidate target exists.
- The migration runner is substantially safer, resumable, and instrumented.
- Restore rehearsal evidence is green.

Not ready:

- Old-stack baseline results are missing.
- Surreal candidate result JSONL is missing.
- Shadow diffs, quality summary, scale metrics, and memory metrics are missing.
- The stale `preflight-failure.md` should be updated or superseded once the
  actual shadow-run capture succeeds.

## Self-Check: PARTIAL

- Found `43-03-PLAN.md`.
- Found source/target cache evidence under `/home/j2h4u/.cache/dotmd/`.
- Found final verified report at `/home/j2h4u/.cache/dotmd/phase43-target/report.md`.
- Found commits listed above in git history.
- Confirmed `git status` was clean before creating this summary.
- Confirmed the original Plan 43-03 shadow-run output artifacts are not present.

---
*Phase: 43-shadow-run-and-quality-gate*
*Completed: 2026-06-16*
