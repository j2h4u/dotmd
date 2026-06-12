---
phase: 19-reranker-adapter-layer-and-multi-model-comparison
plan: 01-reranker-protocol-registry
subsystem: search
tags: [reranker, protocol, registry, factory, cross-encoder]

requires:
  - phase: 18
    provides: Qwen3 reranker selection and CPU latency concern
provides:
  - RerankerProtocol boundary for reranker adapters
  - Stable built-in reranker registry names
  - Cached RerankerFactory over CrossEncoderReranker
  - Name-based reranker configuration defaults
affects: [phase-19, search, api-service, cli]

tech-stack:
  added: []
  patterns:
    - Protocol-based adapter boundary
    - Frozen dataclass registry specs
    - Factory cache keyed by stable short name

key-files:
  created: []
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/search/reranker.py
    - backend/tests/test_reranker.py

key-decisions:
  - "Use qwen3-0.6b as the stable default reranker name while keeping legacy model/backend settings."
  - "Keep Reranker as a compatibility alias for CrossEncoderReranker."

patterns-established:
  - "Reranker adapters implement RerankerProtocol with name, model_name, warmup(), and rerank()."
  - "RerankerFactory owns adapter caching; direct construction should be compatibility-only."

requirements-completed:
  - RERANK-ADAPTER-01
  - RERANK-SELECT-04

duration: 4min
completed: 2026-05-01
---

# Phase 19 Plan 01: Reranker Protocol, Registry, and Factory Summary

**Reranker adapter boundary with stable-name registry and cached CrossEncoder factory for Qwen/MiniLM/GTE/BGE candidates**

## Performance

- **Duration:** 4min
- **Started:** 2026-05-01T12:12:58Z
- **Completed:** 2026-05-01T12:17:24Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `Settings.reranker_name` and parsed `reranker_compare_names` defaults with tests.
- Added `RerankerProtocol`, `RerankerSpec`, `BUILTIN_RERANKERS`, and `available_rerankers()`.
- Renamed the concrete adapter to `CrossEncoderReranker`, added `warmup()`, and exposed compatibility alias `Reranker`.
- Added `create_reranker()` and `RerankerFactory` with cached lookups and clear unknown-name errors.

## Task Commits

Each TDD task was committed atomically:

1. **Task 1 RED: Add failing tests for reranker settings** - `63bf0fb` (test)
2. **Task 1 GREEN: Add name-based reranker settings** - `6babe53` (feat)
3. **Task 2 RED: Add failing tests for reranker registry** - `ef394e3` (test)
4. **Task 2 GREEN: Add reranker protocol registry** - `a7ef4d7` (feat)
5. **Task 3 RED: Add failing tests for reranker factory** - `304f651` (test)
6. **Task 3 GREEN: Add reranker factory cache** - `0073118` (feat)

## Files Created/Modified

- `backend/src/dotmd/core/config.py` - Added stable reranker name defaults and parsed comparison names.
- `backend/src/dotmd/search/reranker.py` - Added protocol, registry, CrossEncoder adapter metadata/warmup, factory, and cache.
- `backend/tests/test_reranker.py` - Added focused TDD coverage for settings, registry, factory, warmup, and alias behavior.

## Decisions Made

- Kept `reranker_model`, `reranker_backend`, and scoring knobs intact for backward-compatible environment configuration.
- Used registry model names for non-default candidates and allowed the existing Qwen `reranker_model` setting to preserve the default adapter model.
- Left `DotMDService` wiring to Plan 02, matching this plan's boundary-only scope.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Fixed pytest regex style flagged by ruff**
- **Found during:** Task 3 (Add factory/cache over CrossEncoder adapter)
- **Issue:** The new unknown-name pytest assertion used a non-raw regex string, triggering `RUF043`.
- **Fix:** Converted the match pattern to a raw string and escaped the literal dot in `qwen3-0.6b`.
- **Files modified:** `backend/tests/test_reranker.py`
- **Verification:** `cd backend && uv run ruff check src/dotmd/search/reranker.py tests/test_reranker.py`
- **Committed in:** `0073118`

---

**Total deviations:** 1 auto-fixed (Rule 3).
**Impact on plan:** No scope expansion; the fix was required for the planned ruff gate.

## Issues Encountered

None beyond the ruff cleanup documented above.

## User Setup Required

None - no external service configuration required.

## Verification

- `cd backend && uv run pytest tests/test_reranker.py -q` - PASS (`22 passed`, warnings only from existing pydantic-settings TOML warning)
- `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py tests/test_reranker.py` - PASS

## Next Phase Readiness

Ready for Plan 02 to route `DotMDService` through `RerankerFactory` and share retrieval candidates for comparison work.

## Self-Check: PASSED

- Confirmed modified files and summary exist on disk.
- Confirmed task commits exist: `63bf0fb`, `6babe53`, `ef394e3`, `a7ef4d7`, `304f651`, `0073118`.
- Confirmed no generated or runtime files were left untracked.

---
*Phase: 19-reranker-adapter-layer-and-multi-model-comparison*
*Completed: 2026-05-01*
