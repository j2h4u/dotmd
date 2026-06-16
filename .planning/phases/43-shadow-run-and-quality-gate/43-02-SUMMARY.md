---
phase: 43-shadow-run-and-quality-gate
plan: 02
subsystem: testing
tags: [surrealdb, shadow-run, falkordb, eval, rehearsal, tdd]
requires:
  - phase: 43-shadow-run-and-quality-gate
    provides: "Phase 43 metric bundle and guardrail schema from 43-01"
  - phase: 40-evaluation-harness-and-golden-queries
    provides: "Phase 40 EvalResult JSONL and diff runner semantics"
  - phase: 41-production-grade-surreal-schema-and-import
    provides: "Manifest-driven source capture and migration evidence flow"
  - phase: 42-surreal-native-retrieval-implementation
    provides: "Explicit Surreal engine override seam for candidate capture"
provides:
  - "Configurable FalkorDB graph-name binding with a dotmd-safe default"
  - "Repo-local Phase 43 shadow runner with manifest, ledger, and verify-only guards"
  - "Operator runbook for bounded old-stack versus Surreal evidence capture"
affects: [43, 44, surrealdb, search, quality-gate, operator-rehearsal]
tech-stack:
  added: []
  patterns:
    - "Baseline graph isolation is a config-bound FalkorDB graph copy, not a runtime default switch"
    - "Phase 43 acceptance ledgers strip sentinel metadata before delegating to Phase 40 loaders"
    - "Verify-only diff validation compares canonical query_id keyed payloads instead of file ordering"
key-files:
  created:
    - backend/devtools/surreal_shadow_runner.py
    - backend/tests/devtools/test_surreal_shadow_runner.py
    - docs/surrealdb-shadow-run-quality-gate.md
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/tests/search/test_falkordb_graph_name_config.py
key-decisions:
  - "Added Settings.falkordb_graph_name with a dotmd default so baseline rehearsals can bind to isolated graph copies without changing production startup defaults."
  - "Phase 43 ledger metadata is written as a sentinel row and stripped into a temp acceptance file before Phase 40 run_eval consumes real acceptance rows."
  - "Verify-only artifact checking uses canonical query_id keyed diff maps so row-order drift does not look like a semantic regression."
patterns-established:
  - "Manifest and candidate-config loaders fail closed on missing, unknown, or non-positive fields before any capture work starts."
  - "Rehearsal index validation enforces path isolation, symlink refusal, and SQLite integrity checks before baseline service construction."
requirements-completed: [SURR-CUT-01, SURR-EVAL-03]
duration: 23 min
completed: 2026-06-16
status: complete
---

# Phase 43 Plan 02: Shadow Run and Quality Gate Summary

**Manifest-bound shadow runner with isolated FalkorDB graph binding, verify-only artifact checks, and an operator runbook for bounded baseline versus Surreal evidence capture**

## Performance

- **Duration:** 23 min
- **Started:** 2026-06-16T07:02:26Z
- **Completed:** 2026-06-16T07:25:12Z
- **Tasks:** 4
- **Files modified:** 6

## Accomplishments

- Added RED/GREEN coverage for the new `falkordb_graph_name` setting so baseline rehearsals can bind to an isolated FalkorDB graph copy while production keeps the `dotmd` default.
- Added a full Phase 43 runner surface with strict manifest/config parsing, rehearsal-path and graph-isolation guards, Phase 40 diff delegation, sentinel-stripping acceptance handling, and verify-only artifact checks.
- Wrote a bounded operator runbook that ties the runner back to the Phase 40 evaluation harness, Phase 41 migration evidence, and Phase 42 explicit Surreal override seam.

## TDD Notes

- **RED:** `dd0e196` added the failing graph-name config tests; `b118c44` added the failing shadow-run contract suite and confirmed the missing runner module.
- **GREEN:** `b7b7308` implemented the graph-name config seam; `e9aa858` implemented the shadow runner and made the focused and plan-level suites pass.
- **REFACTOR:** None as a separate commit. Test-fixture corrections were folded into the GREEN work while preserving the same contract.

## Task Commits

1. **Task 1: Make the FalkorDB graph name a configurable Settings field** - `dd0e196` (`test`), `b7b7308` (`feat`)
2. **Task 2: RED tests for manifest-bound shadow runner behavior** - `b118c44` (`test`)
3. **Task 3: GREEN shadow runner and CLI** - `e9aa858` (`feat`)
4. **Task 4: Document the bounded shadow-run operator flow** - `f1107d0` (`docs`)

## Files Created/Modified

- `backend/src/dotmd/core/config.py` - Added `DEFAULT_FALKORDB_GRAPH_NAME` plus `Settings.falkordb_graph_name`.
- `backend/src/dotmd/ingestion/pipeline.py` - Threaded `settings.falkordb_graph_name` into `_create_graph_store()`.
- `backend/devtools/surreal_shadow_runner.py` - Added the Phase 43 runner, loaders, isolation helpers, verify-only checks, and CLI.
- `backend/tests/devtools/test_surreal_shadow_runner.py` - Added the RED/GREEN contract suite for manifests, ledgers, graph isolation, rehearsal checks, and verify-only behavior.
- `backend/tests/search/test_falkordb_graph_name_config.py` - Added focused coverage for the new graph-name config seam.
- `docs/surrealdb-shadow-run-quality-gate.md` - Added the operator runbook for bounded shadow evidence capture.

## Decisions Made

- Kept the new FalkorDB graph-name surface as a normal settings knob with a `dotmd` default instead of introducing environment aliases, compatibility logic, or production cutover behavior.
- Modeled Phase 43 ledger metadata as a sentinel row in `accepted-diffs.jsonl`, then stripped it into a temporary acceptance file before calling the Phase 40 runner so the older loader never sees metadata-only rows.
- Used query-ID keyed canonical comparison for verify-only diff checks so the integrity gate focuses on semantic content, not JSONL line ordering.

## Verification Output

- `cd backend && uv run pytest tests/search/test_falkordb_graph_name_config.py -q` -> PASS (`2 passed`)
- `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/ingestion/pipeline.py tests/search/test_falkordb_graph_name_config.py` -> PASS
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py --collect-only -q` -> PASS (`44 tests collected`)
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py -q` -> PASS (`44 passed`)
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py tests/search/test_surreal_shadow_metrics.py tests/search/test_falkordb_graph_name_config.py tests/devtools/test_surreal_eval_runner.py -q` -> PASS (`68 passed`)
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py -q -k "rehearsal_isolation or rehearsal_identity or build_baseline_service or ledger_sentinel or expected_manifest"` -> PASS (`12 passed, 32 deselected`)
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py -q -k "candidate_config or baseline_graph_isolation or copy_baseline_graph or teardown_baseline_graph or capture_baseline_eval_results_runs_full_corpus or production_index_and_graph_untouched or verify_only_regenerates or run_eval_receives_stripped_acceptance_path or rehearsal_identity_vec_table_name or deletes_stale_destination or refuses_production_destination"` -> PASS (`24 passed, 20 deselected`)
- `cd backend && uv run python devtools/surreal_shadow_runner.py --help` -> PASS
- `cd backend && uv run ruff check devtools/surreal_shadow_runner.py tests/devtools/test_surreal_shadow_runner.py` -> PASS
- `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_eval_runner.py -q` -> PASS (`66 passed`)

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

- The repo test harness autouses an in-memory graph-store patch, so the new graph-name config tests needed a file-local fixture override to exercise the real `_create_graph_store()` path without opening a live FalkorDB connection.
- Early RED fixtures for runtime-path overlap and canonical diff comparison were too loose and initially exercised the wrong failure modes. Those fixtures were tightened during GREEN work so the suite pins the intended Phase 43 contracts.
- The standalone script entrypoint initially failed on a relative `devtools` import; the runner now adds the backend root to `sys.path` for direct `uv run python devtools/surreal_shadow_runner.py --help` execution.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no production restart, new dependency install, or secret rotation was required for this plan.

## Next Phase Readiness

- Plan 43-03 can reuse the new runner’s `--preflight-candidate-target`, manifest loader, ledger sentinel contract, and verify-only artifact checks instead of inventing another preflight surface.
- Phase 44 now has a bounded, repeatable evidence runner and an operator guide for shadow-quality review without changing startup defaults or the live storage backend.

## Self-Check

PASSED

- Found `.planning/phases/43-shadow-run-and-quality-gate/43-02-SUMMARY.md`
- Found task commits `dd0e196`, `b7b7308`, `b118c44`, `e9aa858`, and `f1107d0` in git history
- Found claimed artifacts on disk: `backend/devtools/surreal_shadow_runner.py`, `backend/tests/devtools/test_surreal_shadow_runner.py`, `backend/tests/search/test_falkordb_graph_name_config.py`, and `docs/surrealdb-shadow-run-quality-gate.md`

---
*Phase: 43-shadow-run-and-quality-gate*
*Completed: 2026-06-16*
