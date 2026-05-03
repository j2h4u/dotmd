---
created: "2026-05-03T11:22:56.217Z"
title: Fix dotMD test contract
area: testing
files:
  - justfile
  - backend/pyproject.toml
  - backend/tests/conftest.py
  - backend/tests/e2e/conftest.py
  - backend/tests/e2e/test_mcp_smoke.py
  - backend/tests/smoke/conftest.py
  - backend/tests/smoke/test_api.py
  - backend/tests/smoke/test_search_engines.py
  - backend/tests/api/test_service_search.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/mcp/test_search_tool.py
---

## Problem

dotMD's test surface currently mixes local unit/integration tests with live
container MCP checks. This can make commands look green while they prove little:

- `just test`/`just check` collect live `e2e` and `smoke` tests unless markers
  are used explicitly.
- `just test-smoke` currently runs on the host against `localhost:8080`; when the
  port is unavailable the suite skips all tests and exits green.
- The legacy `tests/smoke` suite is stale against the current MCP surface
  (`status` tool removed; MCP `search` does not accept `rerank=True`).
- E2E/smoke tests contain skip paths for missing indexed data that can hide
  targeted behavior when tests are run selectively.
- Some API/MCP tests are low-signal: tautological assertions, tests that mostly
  verify mock setup, and tests that inspect private helpers/docstrings instead
  of the real tool schema or behavior.
- The global test fixture monkeypatches `SemanticSearchEngine.encode_batch` for
  all tests, which is useful for local speed but can hide regressions in prefix
  injection, TEI batching, embedding dimension handling, and encoded text
  selection.

## Solution

Create a small GSD phase to make the test contract honest:

- Define explicit tiers:
  - local tests: no live containers, no network dependency, exclude `e2e` and
    live `smoke` markers by default;
  - live container e2e: runs inside the `dotmd` container and fails if runtime
    prerequisites are missing;
  - remote/Funnel smoke: remains separate and explicitly operator-triggered.
- Update `just` commands so default gates cannot silently skip live behavior, and
  opt-in live commands fail fast when the required runtime is absent.
- Delete or replace stale `tests/smoke` with the current `tests/e2e` contract.
- Split e2e HTTP/stdio fixtures so HTTP cases do not start a stdio subprocess.
- Replace misleading tests with behavior checks:
  - assert `_execute_search` call contracts or exercise real service paths
    instead of checking mock-returned lengths;
  - exercise graph-direct/file-path hydration through `build_search_results` or
    service search, not direct `SearchResult` construction;
  - inspect registered MCP schema / real `tools/call` output instead of
    docstrings/private formatting helpers.
- Narrow the global semantic-engine monkeypatch or add explicit boundary tests
  that assert real embedding inputs and dimensions through a controlled fake TEI
  boundary.
- Document the tiers and commands in developer docs so future agents know which
  command proves which class of behavior.
