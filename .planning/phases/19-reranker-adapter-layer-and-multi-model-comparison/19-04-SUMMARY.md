---
phase: 19-reranker-adapter-layer-and-multi-model-comparison
plan: 04-latency-docs-verification
subsystem: search
tags: [reranker, latency, diagnostics, docs, verification]

requires:
  - phase: 19-reranker-adapter-layer-and-multi-model-comparison
    provides: developer comparison service/API/CLI over one shared candidate pool
provides:
  - Latency and cardinality regression coverage for reranker comparison output
  - Documentation for stable reranker selection and developer comparison
  - Focused Phase 19 verification results and Qwen CPU smoke status
affects: [phase-19, search, api-service, cli, docs]

tech-stack:
  added: []
  patterns:
    - Developer diagnostics report measured elapsed_ms instead of hard latency thresholds
    - Production search remains single-reranker while comparison stays developer-only

key-files:
  created:
    - .planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md
  modified:
    - backend/tests/api/test_service_search.py
    - README.md
    - docs/architecture.md
    - .env.example

key-decisions:
  - "Do not add hard model-specific latency thresholds; comparison records measured elapsed_ms."
  - "Skip live CPU smoke unless explicitly requested by the operator because it can download/run real models."
  - "Keep production default as a single qwen3-0.6b reranker selected by stable name."

patterns-established:
  - "Reranker comparison tests assert elapsed_ms, row cardinality, error-row empties, Qwen default naming, and one retrieval pass for three rerankers."
  - "Docs describe comparison as developer-only and safe to run without a production restart."

requirements-completed:
  - RERANK-COMPARE-01
  - RERANK-LATENCY-01

duration: 3min
completed: 2026-05-01
---

# Phase 19 Plan 04: Latency Diagnostics, Docs, and Verification Summary

**Reranker comparison now has pinned latency diagnostics, shared-pool invariants, and docs for comparing Qwen CPU latency without changing production search.**

## Performance

- **Duration:** 3min
- **Started:** 2026-05-01T12:36:18Z
- **Completed:** 2026-05-01T12:39:03Z
- **Tasks:** 3
- **Files modified:** 5

## Accomplishments

- Added regression coverage that every comparison row exposes float `elapsed_ms`, consistent `returned_count`, ordered `top_chunk_ids`, and matching score counts.
- Proved three-reranker comparison uses one retrieval/fusion candidate pool by asserting each retrieval engine is called once.
- Documented the stable production default `DOTMD_RERANKER_NAME=qwen3-0.6b`, the `dotmd rerank compare` workflow, and the adapter/factory/shared candidate pool architecture.
- Recorded that production remains single-reranker by default; multi-reranker comparison is developer-only diagnostics.

## Task Commits

Each task was committed atomically:

1. **Task 1: Pin latency diagnostics and no-retrieval-repeat behavior** - `22a4c97` (test)
2. **Task 2: Document adapter layer and developer comparison** - `270e880` (docs)
3. **Task 3: Run focused checks and write Phase 19 summary** - this summary commit (docs)

## Files Created/Modified

- `backend/tests/api/test_service_search.py` - Added comparison invariants for latency, Qwen naming, error rows, cardinality, overlap reference, and retrieval call counts.
- `README.md` - Added stable reranker default, runtime reranker CLI example, developer comparison command, and `elapsed_ms` diagnostics explanation.
- `docs/architecture.md` - Added reranker adapter section covering `RerankerProtocol`, registry, factory/cache, shared candidate pool, `DotMDService`, and no per-request index reloads.
- `.env.example` - Added `DOTMD_RERANKER_NAME` and `DOTMD_RERANKER_COMPARE_NAMES` defaults.
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md` - Execution summary and verification record.

## Decisions Made

- Do not fail tests on a fixed Qwen latency threshold. Qwen CPU latency is measured through `elapsed_ms` and evaluated from comparison output.
- Live CPU smoke was skipped because the plan makes it optional unless the operator explicitly requests a real model run and the environment is ready.
- Keep MCP unchanged; developer comparison is documented through CLI/API and production remains single-reranker.

## Commands run

- `cd backend && uv run pytest tests/api/test_service_search.py -q` - PASS (`12 passed`, warnings only)
- `rg --no-heading "dotmd rerank compare|RerankerProtocol|DOTMD_RERANKER_NAME" README.md docs/architecture.md .env.example` - PASS
- `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py -q` - PASS (`48 passed`, warnings only)
- `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py` - PASS

## Qwen CPU Latency

The comparison output surfaces Qwen CPU latency through per-reranker `elapsed_ms`, and docs call out this diagnostic explicitly.

The optional live CPU smoke was skipped. No observed Qwen `elapsed_ms` was recorded in this plan because the operator did not explicitly request a real model run.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Existing Behavior Already Present] TDD RED tests passed immediately**
- **Found during:** Task 1 (Pin latency diagnostics and no-retrieval-repeat behavior)
- **Issue:** The new invariants passed on the first run because Plan 03 had already implemented the comparison output shape and first-success overlap behavior.
- **Fix:** Kept the new regression tests as the durable acceptance gate; no production code change was needed.
- **Files modified:** `backend/tests/api/test_service_search.py`
- **Verification:** `cd backend && uv run pytest tests/api/test_service_search.py -q`
- **Committed in:** `22a4c97`

---

**Total deviations:** 1 documented (existing implementation already satisfied the new TDD assertions).
**Impact on plan:** No scope expansion. The plan's intended behavior is now pinned by tests.

## Issues Encountered

None beyond the TDD RED-pass note above.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. Stub scan only found intentional empty collections/defaults in implementation and mocked test assertions.

## Threat Flags

None. This plan added docs and tests only; no new network endpoints, auth paths, file access patterns, or schema changes were introduced.

## Next Phase Readiness

Phase 19 is ready for orchestrator-level wave completion. The adapter/factory layer, shared candidate pool, developer comparison surfaces, latency diagnostics, docs, and focused verification are complete. Production remains single-reranker by default.

## Self-Check: PASSED

- Confirmed key files exist on disk: `backend/tests/api/test_service_search.py`, `README.md`, `docs/architecture.md`, `.env.example`, and this summary.
- Confirmed task commits exist for Task 1 and Task 2; Task 3 is this committed summary.
- Confirmed summary acceptance strings exist: `Qwen CPU latency`, `production remains single-reranker`, `Commands run`, and `live CPU smoke was skipped`.
- Confirmed the summary commit did not delete tracked files.
- Confirmed `.planning/STATE.md` remains uncommitted because it was pre-existing orchestrator-owned local state.

---
*Phase: 19-reranker-adapter-layer-and-multi-model-comparison*
*Completed: 2026-05-01*
