# Phase 23: Fix dotMD test contract - Research

## Research Complete

This phase is a test-infrastructure cleanup. No external library research is
needed; the relevant facts are in the current repo and live command behavior.

## Current Command Contract

- `just test` runs `cd backend && uv run pytest {{args}}`.
- `backend/pyproject.toml` sets `testpaths = ["tests"]`, so a default pytest
  collection includes local tests, e2e tests, and legacy smoke tests.
- `just check` depends on `lint typecheck test`, so it inherits the same
  collection behavior.
- `just test-e2e` has already been corrected in the current working tree to run
  inside the `dotmd` container:
  `docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ ...'`.
- `just test-smoke` still runs the legacy host-local smoke suite and currently
  returns green with all tests skipped when no host `localhost:8080` exists.

## Runtime Evidence

- `just test-smoke` produced:
  `sssssssss [100%] 9 skipped in 0.06s`
  with exit code 0.
- `just test-e2e` produced:
  `30 passed in 108.42s`
  when run through the corrected container command.
- `just typecheck` is currently:
  `pyright ratchet: 91 errors (baseline 91)`.
- `just lint` is currently green.

## Stale Smoke Suite

The legacy `backend/tests/smoke` suite is not aligned with the current MCP
server:

- `backend/tests/smoke/conftest.py` calls `tool_call("status")`, but current MCP
  tools are `search`, `read`, and `feedback`.
- `backend/tests/smoke/test_search_engines.py` passes `rerank=True` to MCP
  `search`, but MCP `search` accepts only `query` and `top_k`.
- `backend/tests/smoke` duplicates intent already covered more accurately by
  `backend/tests/e2e`.

Recommendation: delete `backend/tests/smoke` or turn `just test-smoke` into a
compatibility alias for the live container e2e suite. Do not preserve the stale
suite as skipped coverage.

## E2E Fixture Issue

`backend/tests/e2e/conftest.py` has a parametrized `mcp_call` fixture that takes
`_stdio_session` unconditionally. That starts the stdio MCP subprocess before
HTTP cases too. Split the fixture so HTTP calls do not depend on the stdio
fixture.

## Low-Signal Test Findings

### `backend/tests/api/test_service_search.py`

- `TestSearchReturnsFilePaths.test_search_returns_file_paths_list` patches
  `_execute_search` and asserts `len(results) >= 0`, which is a tautology.
- `TestSearchRespectsTopK.test_search_respects_top_k` returns `stub_results[:3]`
  from the mock and then asserts the length is 3, which verifies the mock setup,
  not service behavior.

Recommendation: either assert `_execute_search` call arguments precisely, or
use fake engines and the real service path to test top-k truncation.

### `backend/tests/api/test_search_result_shape.py`

- The graph-direct hydration test directly instantiates `SearchResult`, so it
  does not prove graph-direct hits are hydrated through metadata/file-path
  lookup.

Recommendation: call `build_search_results` or a thin service path with fake
metadata and candidate IDs.

### `backend/tests/mcp/test_search_tool.py`

- Tests inspect `_format_result` and the Python docstring. That does not prove
  the registered MCP schema or real `tools/call` serialization.

Recommendation: inspect `tools/list` and a real/stubbed tool call result.

## Global Semantic Engine Patch

`backend/tests/conftest.py` globally patches:

- `SemanticSearchEngine.encode_batch` to return 8-dimensional zero vectors.
- `SemanticSearchEngine.get_tei_model_id` to return `stub-model`.

This is useful for speed, but it can hide regressions in encoded text selection,
prefix injection, TEI batching, and embedding dimensions. Keep it only as a
local-test speed boundary and add a focused boundary test that bypasses or
overrides the patch.

## Recommended Implementation Shape

One plan is enough:

1. Fix command tiering and remove stale smoke.
2. Split e2e HTTP/stdio fixture startup and make live e2e fail on missing
   runtime when explicitly invoked.
3. Replace low-signal tests with behavior checks.
4. Add focused embedding-boundary coverage or narrow the global patch.
5. Update README/developer docs.

## Verification Strategy

Required validation commands:

- `just test`
- `just check`
- `just test-e2e`
- `just typecheck`
- `just lint`

Negative validation:

- If `dotmd` container is unavailable, `just test-e2e` must exit non-zero rather
  than reporting all tests skipped.
- `just test-smoke` must no longer produce `9 skipped` as a successful command.
