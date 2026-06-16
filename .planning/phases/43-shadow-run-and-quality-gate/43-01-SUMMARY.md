---
phase: 43-shadow-run-and-quality-gate
plan: 01
subsystem: testing
tags: [surrealdb, shadow-run, metrics, memory, tdd]
requires:
  - phase: 38-storage-simplification
    provides: "Scale-gate field names and completeness semantics reused by Phase 43 metrics"
  - phase: 40-evaluation-harness-and-golden-queries
    provides: "Golden-query diff vocabulary consumed by later shadow-run plans"
  - phase: 42-surreal-native-retrieval-implementation
    provides: "Explicit Surreal override seam that will emit Phase 43 candidate evidence"
provides:
  - "Typed shadow metric bundle with preserved Phase 38 scale-gate field names"
  - "Paired baseline/candidate memory metrics plus explicit guardrail evaluation"
  - "Deterministic UTF-8 JSON writer for Phase 43 shadow evidence artifacts"
affects: [phase-43, phase-44, surrealdb, search, shadow-run]
tech-stack:
  added: []
  patterns:
    - "Shadow metrics keep scale-gate and memory evidence as separate nested surfaces"
    - "Memory guardrails compare candidate vs baseline with ratio and slack checks"
key-files:
  created:
    - backend/src/dotmd/search/surreal_shadow_metrics.py
    - backend/tests/search/test_surreal_shadow_metrics.py
    - .planning/phases/43-shadow-run-and-quality-gate/43-01-SUMMARY.md
  modified: []
key-decisions:
  - "Phase 43 metric JSON keeps Phase 38 scale-gate field names unchanged and nests memory evidence separately."
  - "Memory guardrails require paired baseline and candidate payloads and reject zero or negative baseline divisors before ratio evaluation."
  - "The capture helper owns tracemalloc start/stop so peak Python heap evidence cannot silently stay zero."
patterns-established:
  - "Validation fails closed on incomplete scale, memory, or guardrail fields before any shadow artifact is written."
  - "Production-derived non-ASCII refs and titles are preserved in JSON with ensure_ascii disabled."
requirements-completed: [SURR-CUT-01]
duration: 3 min
completed: 2026-06-16
status: complete
---

# Phase 43 Plan 01: Shadow Metric Contract Summary

**Typed Phase 43 shadow metrics with paired memory guardrails, tracemalloc-backed capture, and deterministic UTF-8 JSON output**

## Performance

- **Duration:** 3 min
- **Started:** 2026-06-16T06:51:19Z
- **Completed:** 2026-06-16T06:54:05Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added RED coverage that locks the Phase 43 bundle shape, paired memory requirements, guardrail behavior, and UTF-8 JSON expectations before the runner exists.
- Implemented a stdlib-only `surreal_shadow_metrics.py` module with frozen/slotted dataclasses, paired baseline/candidate validation, and ratio-plus-slack memory guardrails.
- Added a deterministic JSON writer and a tracemalloc-backed measurement helper that later shadow-run plans can call without touching live services or retrieval defaults.

## Task Commits

Each task was committed atomically:

1. **Task 1: RED tests for shadow metric completeness** - `384ef1a` (test)
2. **Task 2: GREEN metric helpers and JSON writer** - `fef3318` (feat)

## Files Created/Modified

- `backend/src/dotmd/search/surreal_shadow_metrics.py` - typed metric bundle, memory guardrails, capture helper, validation, and JSON writer for Phase 43 evidence
- `backend/tests/search/test_surreal_shadow_metrics.py` - RED/GREEN contract coverage for metric shape, fail-closed validation, tracemalloc capture, and UTF-8 serialization

## Decisions Made

- Kept the Phase 38 scale gate vocabulary untouched and added memory evidence as a separate nested `memory` object so later plans do not inherit a second scale/quality terminology.
- Required paired `baseline` and `candidate` memory payloads and rejected zero or negative baseline RSS/heap divisors before ratio evaluation so guardrails cannot divide by zero or slack-pass malformed baselines.
- Made `capture_shadow_memory_metrics()` an optional measurement helper that always starts and stops `tracemalloc`, which guarantees real heap evidence for the runner instead of a silent zero.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

- The first GREEN run exposed a bad RED fixture for the slack-pass case: the baseline values were too large to exceed the `1.25` ratio. The test data was corrected so the ratio exceeds the threshold while the absolute delta still stays under the fixed slack.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 43-02 can consume a stable JSON-ready metric contract for scale, latency, store-size, and paired memory evidence without inventing new field names.
- The shadow runner can reuse `validate_shadow_metric_bundle()` and `write_shadow_metric_json()` to fail closed before writing any incomplete evidence artifact.

## Self-Check: PASSED

- Summary file exists on disk.
- Claimed task artifacts exist on disk: `backend/src/dotmd/search/surreal_shadow_metrics.py` and `backend/tests/search/test_surreal_shadow_metrics.py`.
- Task commits `384ef1a` and `fef3318` are present in git history.
- `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py -q` failed in RED state for the expected missing-module reason before implementation.
- `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py --collect-only -q` collected the 17 named contract tests required by the plan.
- `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py tests/search/test_surreal_retrieval_parity.py -q` passed (`27 passed`).
- `cd backend && uv run ruff check src/dotmd/search/surreal_shadow_metrics.py tests/search/test_surreal_shadow_metrics.py` passed.
