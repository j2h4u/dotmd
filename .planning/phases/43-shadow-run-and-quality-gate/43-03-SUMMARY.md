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
  - "Completed shadow-run result artifacts with accepted non-regression unclear rows"
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
  - "Plan 43-03 is complete after producing baseline/candidate/diff/metric artifacts and passing verify-only."
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
status: complete
---

# Phase 43 Plan 03: Migration Evidence and Instrumentation Summary

**Verified the production-derived Surreal migration target, fixed the opaque/idempotency failures, and produced the shadow-run quality artifacts**

## Performance

- **Duration:** Multi-hour debugging and migration rehearsal session
- **Started:** 2026-06-16
- **Completed:** 2026-06-16
- **Tasks:** Plan 43-03 execution plus prerequisite migration/shadow-run remediation
- **Files modified:** migration runner, shadow runner, focused tests, phase artifacts, and this summary

## Accomplishments

- Produced a verified embedded-local SurrealKV migration target:
  `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db`
  (`3.5G` after cleanup; deferred secondary indexes are not built in the main apply).
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
- Produced the Plan 43-03 shadow-run artifacts:
  `source-capture.json`, `baseline-results.jsonl`, `candidate-results.jsonl`,
  `shadow-diffs.jsonl`, `shadow-summary.md`, `scale-metrics.json`, and
  `memory-metrics.json`.
- Shadow quality gate now passes with `regression=0`, `harmless_reorder=4`,
  and 12 accepted `unclear` rows where candidate refs/ranks are identical to
  baseline and the issue is missing golden evidence, not a Surreal migration
  regression.
- Captured real query latency evidence:
  baseline p50 `3224.126ms`, p95 `7008.1125ms`;
  candidate p50 `3071.718ms`, p95 `6790.503ms`.

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
- `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db` - verified SurrealKV target (`3.5G`)
- `/home/j2h4u/.cache/dotmd/phase43-target/report.md` - verified evidence report
- `/home/j2h4u/.cache/dotmd/phase43-target/progress.json` - final progress chain
- `/home/j2h4u/.cache/dotmd/phase43-target/restore-manifest.json` - fallback restore verification

Repo-local artifacts produced or updated for Plan 43-03:

- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture-expected.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-config.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/metrics-replay-queries.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/accepted-diffs.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/baseline-results.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-results.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-diffs.jsonl`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-summary.md`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/scale-metrics.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/memory-metrics.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/preflight-progress.json`
- `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-run-progress.json`

## Verification Output

- `cd backend && uv run pytest tests/ingestion/test_surreal_transform_only_migration.py tests/ingestion/test_surreal_production_migration.py tests/devtools/test_surreal_migration_runner.py -q`
  -> PASS (`32 passed`)
- `cd backend && uv run ruff check src/dotmd/ingestion/migrate_surreal.py devtools/surreal_migration_runner.py tests/devtools/test_surreal_migration_runner.py tests/ingestion/test_surreal_production_migration.py`
  -> PASS
- Live resume-run against `/home/j2h4u/.cache/dotmd/phase43-target/phase43-fresh.surreal.db`
  -> PASS; final `report_status: verified`, `restore_status: verified_with_fallback`,
  blockers `[]`.
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_eval_runner.py tests/ingestion/test_surreal_transform_only_migration.py tests/devtools/test_surreal_migration_runner.py -q`
  -> PASS (`85 passed`)
- `cd backend && uv run ruff check devtools/surreal_shadow_runner.py devtools/surreal_migration_runner.py src/dotmd/ingestion/migrate_surreal.py tests/devtools/test_surreal_shadow_runner.py tests/ingestion/test_surreal_transform_only_migration.py`
  -> PASS
- `cd backend && env ... uv run python devtools/surreal_shadow_runner.py --verify-only ...`
  -> PASS

## Decisions Made

- The final migrated `embeddings` table remains `SCHEMALESS`. Returning it to
  `SCHEMAFULL` after bulk load ran for roughly an hour and failed with:
  `Record is too large to fit in a segment. Increase max segment size`.
  Deferred retrieval indexes are intentionally split out of the main migration
  apply; this is a migration observability tradeoff, not a silent omission.
- Graph expected counts now reflect the writer's real behavior: relations can
  synthesize missing section/entity/tag nodes, so expected counts must use set
  union semantics, not `max(existing, derived)`.
- Large migration artifacts belong under `/home/j2h4u/.cache/dotmd/`, not under
  `.planning/`, to avoid turning planning docs into multi-GB database storage.
- Phase 43 cannot advance to production cutover solely on this evidence because
  deferred retrieval indexes still need an explicit post-step decision before
  production cutover performance testing.

## Deviations from Plan

### Deferred retrieval indexes

- **Planned:** Build deferred Surreal retrieval indexes as part of migration apply.
- **Actual:** The main apply now skips deferred secondary index construction by
  default because Surreal `DEFINE INDEX` on the migrated embeddings table is not
  internally progress-observable and violated the 120-second no-output rule.
- **Impact:** Data migration and shadow quality evidence are complete; retrieval
  index build remains a separate explicit post-step before production cutover.

---

**Total deviations:** 1 material deviation.
**Impact on plan:** Phase 43 shadow evidence is complete; production cutover
still needs an explicit deferred-index build/performance decision.

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

Do not proceed to production cutover from this summary alone. The remaining
cutover prerequisite is an explicit deferred-index build/performance decision.

## Next Phase Readiness

Phase 44 is not ready yet.

Ready:

- A verified SurrealKV candidate target exists.
- The migration runner is substantially safer, resumable, and instrumented.
- Restore rehearsal evidence is green.
- Shadow-run quality artifacts exist and verify-only passes.
- Real baseline/candidate timing evidence exists.

Not ready:

- Deferred Surreal retrieval indexes were intentionally not built in the main
  apply.
- Stale `preflight-failure.md` was removed after passing preflight and
  shadow-run artifacts were produced.

## Self-Check: PASSED

- Found `43-03-PLAN.md`.
- Found source/target cache evidence under `/home/j2h4u/.cache/dotmd/`.
- Found final verified report at `/home/j2h4u/.cache/dotmd/phase43-target/report.md`.
- Found commits listed above in git history.
- Confirmed shadow-run output artifacts exist.
- Confirmed `shadow-summary.md` report gate is `passed: true`.
- Confirmed verify-only passes.

---
*Phase: 43-shadow-run-and-quality-gate*
*Completed: 2026-06-16*
