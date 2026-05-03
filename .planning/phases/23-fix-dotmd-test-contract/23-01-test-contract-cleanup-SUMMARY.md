---
phase: 23-fix-dotmd-test-contract
plan: 01-test-contract-cleanup
subsystem: testing
tags: [pytest, just, mcp, e2e, pyright, ruff]

requires:
  - phase: 22-improve-search-snippet-boundaries
    provides: current local test suite and MCP search/read behavior
provides:
  - Honest local and live test command tiers
  - Removed stale smoke suite and skip-all green path
  - Live MCP e2e fail-fast runtime contract
  - Behavior-focused search and MCP tests
  - Explicit embedding encode-boundary coverage
  - Lower pyright ratchet baseline
affects: [testing, mcp, search, ingestion, developer-workflow]

tech-stack:
  added: []
  patterns:
    - "Local tests exclude live markers by default"
    - "Explicit live e2e fails non-zero on missing runtime"
    - "Focused unit tests verify MCP schema/call contracts rather than private docstrings"

key-files:
  created:
    - .planning/phases/23-fix-dotmd-test-contract/23-01-test-contract-cleanup-SUMMARY.md
  modified:
    - justfile
    - README.md
    - backend/pyproject.toml
    - backend/devtools/pyright-baseline.json
    - backend/tests/conftest.py
    - backend/tests/e2e/conftest.py
    - backend/tests/e2e/test_mcp_smoke.py
    - backend/tests/api/test_service_search.py
    - backend/tests/api/test_search_result_shape.py
    - backend/tests/mcp/test_search_tool.py
    - backend/tests/ingestion/test_pipeline_metadata.py
    - backend/tests/smoke/

key-decisions:
  - "Removed test-smoke instead of aliasing it to test-e2e."
  - "Kept the global semantic encode mock for fast local tests, with a marker escape hatch for one boundary test."
  - "Captured live DOTMD_* env at e2e conftest import time so stdio e2e is not poisoned by root test env monkeypatching."

patterns-established:
  - "Use just test for local-only gates and just test-e2e for live container MCP gates."
  - "Use tools/list schema and stubbed tools/call output for MCP contract tests."
  - "Use a marker to opt out of global embedding mocks only for tests that prove the real encode boundary."

requirements-completed: [TEST-CONTRACT-01, TEST-CONTRACT-02, TEST-CONTRACT-03, TEST-CONTRACT-04]

duration: 1h
completed: 2026-05-03
---

# Phase 23: Fix dotMD Test Contract Summary

**Local tests are now local-only, live MCP e2e fails honestly, stale smoke coverage is gone, and misleading tests were replaced with behavior checks.**

## Performance

- **Duration:** ~1h
- **Started:** 2026-05-03T11:48:10Z
- **Completed:** 2026-05-03T12:00:39Z
- **Tasks:** 4
- **Files modified:** 18

## Accomplishments

- Separated `just test` / `just check` from live runtime by adding `-m "not e2e and not smoke"`.
- Removed `test-smoke` and deleted `backend/tests/smoke`, including the old skip-all-on-missing-port path.
- Made `just test-e2e` run inside the `dotmd` container and fail non-zero when `/health` is unavailable.
- Split e2e HTTP/stdout fixture behavior so HTTP cases do not start `_StdioSession`; stdio resolves lazily via `request.getfixturevalue("_stdio_session")`.
- Replaced low-signal service, graph hydration, and MCP tests with call-contract, `build_search_results`, registered schema, and stubbed tool-call checks.
- Added a focused `real_semantic_encode_batch` marker and test that records the actual `encode_batch` boundary, including `passage:` and heading context.
- Lowered pyright ratchet from 91 to 76 errors.

## Task Commits

Execution is committed as one phase implementation commit because this was a single tightly-coupled plan with one wave.

1. **Task 1: Make developer test commands tier-aware** - this commit
2. **Task 2: Remove stale smoke suite and make live e2e fail honestly** - this commit
3. **Task 3: Replace low-signal search and MCP tests** - this commit
4. **Task 4: Add explicit embedding-boundary coverage and close gates** - this commit

## Files Created/Modified

- `justfile` - local-only `test`, containerized `test-e2e`, removed `test-smoke`.
- `README.md` - documents local vs live test command semantics.
- `backend/tests/e2e/conftest.py` - fail-fast live runtime fixture, lazy stdio fixture, PIN-code OAuth helper, live env capture for stdio.
- `backend/tests/e2e/test_mcp_smoke.py` - no longer skips canonical result-shape checks after the suite has established live search works.
- `backend/tests/smoke/` - deleted stale smoke suite.
- `backend/tests/api/test_service_search.py` - asserts service call contract instead of tautological result length.
- `backend/tests/api/test_search_result_shape.py` - graph-direct hydration now goes through `build_search_results`.
- `backend/tests/mcp/test_search_tool.py` - validates registered MCP output schema and stubbed tool-call output.
- `backend/tests/conftest.py` / `backend/pyproject.toml` - added `real_semantic_encode_batch` marker escape hatch.
- `backend/tests/ingestion/test_pipeline_metadata.py` - adds encode-boundary recording test and fixes nearby typing issues.
- `backend/devtools/pyright-baseline.json` - ratchet lowered to 76.

## Decisions Made

- `test-smoke` was removed outright. Keeping it as an alias would preserve ambiguity about two live test names.
- E2E missing runtime is a hard failure, not a skip. This makes explicit live commands red when the live runtime contract is not satisfied.
- The root test env fixture stays in place for local tests; e2e stdio captures live `DOTMD_*` env before that fixture mutates env for local test safety.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Stdio e2e inherited local-test embedding env**
- **Found during:** Task 4 final `just test-e2e`
- **Issue:** root `tests/conftest.py` changed `DOTMD_EMBEDDING_URL` to `http://test-tei:8088`; stdio e2e copied that env into the subprocess, so real search failed DNS resolution.
- **Fix:** captured live `DOTMD_*` env at `tests/e2e/conftest.py` import time and used that for the stdio subprocess.
- **Files modified:** `backend/tests/e2e/conftest.py`
- **Verification:** `just test-e2e` passed `30 passed in 114.14s`.
- **Committed in:** this commit

---

**Total deviations:** 1 auto-fixed (blocking live e2e correctness).
**Impact on plan:** Improved the e2e contract without changing product behavior.

## Issues Encountered

- `gsd-sdk query config-set workflow._auto_chain_active false` reported the key as unknown in this repo's current GSD config surface. Execution continued because this only clears stale auto-chain intent and no auto-chain was active.
- `just test-e2e` is intentionally slow because it runs real live MCP HTTP and stdio paths.

## User Setup Required

None.

## Verification

- `just --list` - passed; no `test-smoke` recipe.
- `just test --collect-only -q` - passed; `251/281 tests collected (30 deselected)`.
- `just lint` - passed.
- `just typecheck` - passed; `pyright ratchet: 76 errors (baseline 76)`.
- `just test` - passed; `251 passed, 30 deselected`.
- `just test-e2e` - passed; `30 passed in 114.14s`.
- `just check` - passed; lint, typecheck, and local tests all green.
- `test ! -d backend/tests/smoke` - passed.
- `! just --list | rg "test-smoke"` - passed.
- `! just test-smoke 2>&1 | rg "9 skipped"` - passed.

## Next Phase Readiness

Phase 23 is ready for verification/security review. The remaining pyright debt is reduced but not eliminated; baseline is now 76 and should continue ratcheting down in nearby work.

---
*Phase: 23-fix-dotmd-test-contract*
*Completed: 2026-05-03*
