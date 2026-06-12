---
phase: "23"
plan: "01-test-contract-cleanup"
type: execute
wave: 1
depends_on: []
files_modified:
  - justfile
  - README.md
  - backend/pyproject.toml
  - backend/tests/conftest.py
  - backend/tests/e2e/conftest.py
  - backend/tests/e2e/test_mcp_smoke.py
  - backend/tests/smoke/__init__.py
  - backend/tests/smoke/conftest.py
  - backend/tests/smoke/test_api.py
  - backend/tests/smoke/test_hybrid_fusion.py
  - backend/tests/smoke/test_search_engines.py
  - backend/tests/api/test_service_search.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/mcp/test_search_tool.py
  - backend/devtools/pyright-baseline.json
autonomous: true
requirements:
  - TEST-CONTRACT-01
  - TEST-CONTRACT-02
  - TEST-CONTRACT-03
  - TEST-CONTRACT-04
requirements_addressed: [TEST-CONTRACT-01, TEST-CONTRACT-02, TEST-CONTRACT-03, TEST-CONTRACT-04]
must_haves:
  truths:
    - "D-01: Local tests do not require live Docker containers, external ports, TEI, or production data"
    - "D-02: Explicit live commands fail non-zero when required runtime is missing"
    - "D-03: `just test` and `just check` exclude `e2e` and live `smoke` by default"
    - "D-04: The stale `backend/tests/smoke` suite is deleted; `test-smoke` is removed from the command surface"
    - "D-05: HTTP e2e cases do not start the stdio MCP subprocess"
    - "D-06: Low-signal tests are replaced with behavior checks"
    - "D-07: Embedding boundary coverage is explicit despite the global semantic-engine test patch"
    - "D-08: Developer docs state what each test command proves"
    - "D-09: Nearby pyright errors are reduced opportunistically when the fix is local and low-risk"
  artifacts:
    - path: "justfile"
      provides: "canonical developer test commands"
      contains: "test-e2e"
    - path: "backend/tests/e2e/conftest.py"
      provides: "live MCP transport fixtures"
      contains: "mcp_call"
    - path: "README.md"
      provides: "developer command documentation"
      contains: "just check"
  key_links:
    - from: "just check"
      to: "local-only quality gate"
      via: "just test"
      pattern: "not e2e and not smoke"
---

# Phase 23 Plan 01: Test Contract Cleanup

<objective>
Make dotMD's test commands and tests honest: local gates should run only local
tests, explicit live MCP checks should run in the live container and fail when
runtime prerequisites are missing, and low-signal tests should be replaced with
behavioral checks that catch the regressions that caused this phase.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| A command exits green while all live tests skipped | HIGH | Remove skip-based live command success; explicit live commands must fail when runtime is unavailable. |
| `just check` gives false confidence by collecting live tests that skip | HIGH | Make the default `just test` local-only with marker exclusion, and keep live suites opt-in. |
| Stale smoke tests remain as duplicate green noise | HIGH | Delete `backend/tests/smoke`; remove `test-smoke` from the command surface rather than aliasing it. |
| E2E HTTP tests accidentally validate stdio startup too | MEDIUM | Split HTTP and stdio fixtures so stdio starts only for stdio-parametrized cases. |
| Low-signal tests preserve mock behavior instead of production behavior | MEDIUM | Replace tautologies and mock-return checks with call-contract or real-path behavior assertions. |
| Global embedding mock hides real embedding-input regressions | MEDIUM | Add a focused test that bypasses/overrides the global patch and asserts encoded text/dimensions through a controlled boundary. |
| Docs continue to recommend misleading commands | MEDIUM | Update README/developer docs to name local vs live command semantics. |
</threat_model>

<tasks>
<task id="1" type="auto">
<name>Task 1: Make developer test commands tier-aware</name>
<read_first>
- `justfile`
- `backend/pyproject.toml`
- `README.md`
- `backend/tests/e2e/conftest.py`
- `backend/tests/smoke/conftest.py`
- `.planning/phases/23-fix-dotmd-test-contract/23-CONTEXT.md`
- `.planning/phases/23-fix-dotmd-test-contract/23-RESEARCH.md`
</read_first>
<files>
- `justfile`
- `README.md`
- `backend/pyproject.toml`
</files>
<action>
Update `justfile` so command tiers are explicit:

- `test *args` runs local tests only, excluding live markers with:
  `cd backend && uv run pytest -m "not e2e and not smoke" {{args}}`
- `check` continues to run `lint typecheck test`.
- `test-e2e *args` runs inside the `dotmd` container:
  `docker exec dotmd sh -lc 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -p no:cacheprovider --tb=short -q {{args}}'`
- Remove `test-smoke *args` from the command surface. Do not alias it to
  `test-e2e`; keeping both names would preserve ambiguity about which live suite
  is authoritative.

Update `README.md` Common Commands so it states:

- `just test` runs local tests only, excluding live MCP e2e/smoke.
- `just test-e2e` runs live MCP e2e inside the running `dotmd` container.
- `just test-mcp-remote` runs production/Funnel connectivity smoke.
- `just check` is `lint + typecheck + local tests`.

If `backend/pyproject.toml` marker descriptions mention smoke/e2e behavior, keep
them accurate after stale smoke removal.
</action>
<verify>
<automated>just --list</automated>
<automated>! just --list | rg "test-smoke"</automated>
<automated>just test --collect-only -q</automated>
<automated>just check</automated>
</verify>
<acceptance_criteria>
- `justfile` contains `pytest -m "not e2e and not smoke"`.
- `justfile` contains `docker exec dotmd`.
- `just --list` does not contain `test-smoke`.
- `README.md` contains `just test-e2e`.
- `README.md` contains `just test-mcp-remote`.
- `README.md` contains `local tests`.
- `just test --collect-only -q` does not collect `tests/e2e/test_mcp_smoke.py`.
- `just check` exits 0.
</acceptance_criteria>
<done>
Local and live test commands have separate, documented contracts.
</done>
</task>

<task id="2" type="auto">
<name>Task 2: Remove stale smoke suite and make live e2e fail honestly</name>
<read_first>
- `backend/tests/smoke/__init__.py`
- `backend/tests/smoke/conftest.py`
- `backend/tests/smoke/test_api.py`
- `backend/tests/smoke/test_hybrid_fusion.py`
- `backend/tests/smoke/test_search_engines.py`
- `backend/tests/e2e/conftest.py`
- `backend/tests/e2e/test_mcp_smoke.py`
- `backend/src/dotmd/mcp_server.py`
</read_first>
<files>
- `backend/tests/smoke/__init__.py`
- `backend/tests/smoke/conftest.py`
- `backend/tests/smoke/test_api.py`
- `backend/tests/smoke/test_hybrid_fusion.py`
- `backend/tests/smoke/test_search_engines.py`
- `backend/tests/smoke/pytest.ini`
- `backend/tests/e2e/conftest.py`
- `backend/tests/e2e/test_mcp_smoke.py`
</files>
<action>
Delete the stale `backend/tests/smoke` suite completely, including
`__init__.py`, `conftest.py`, `pytest.ini`, and all smoke test files. The suite
must no longer exist; do not keep a replacement smoke file.

The deleted suite must remove these stale patterns from the active test tree:

- `tool_call("status")`
- `rerank=True` passed to MCP `search`
- a collection hook that marks all smoke tests skipped when `localhost:8080` is
  unavailable

Update `backend/tests/e2e/conftest.py` so:

- Explicit e2e runs fail on missing `http://localhost:8080/health` instead of
  marking every e2e test skipped. Implement this as a session-scoped autouse
  `_require_live_server` fixture that performs one health probe and calls:
  `pytest.exit("dotMD MCP server not reachable at http://localhost:8080", returncode=1)`.
- Remove the skip-all `pytest_collection_modifyitems` hook.
- HTTP-parametrized tests do not depend on `_stdio_session`.
- `_stdio_session` starts only for stdio-parametrized cases. Keep one `mcp_call`
  fixture if that is the smallest change, but resolve `_stdio_session` lazily
  with `request.getfixturevalue("_stdio_session")` only when `request.param`
  selects `stdio`.
- The PIN-code OAuth helper from the current working tree remains intact.

Update e2e tests so targeted search/read shape tests do not silently skip if the
known smoke query returns no data after the suite already established that the
index should contain results. Prefer failing with a clear message for the
canonical query instead of `pytest.skip("no results to check")`.
</action>
<verify>
<automated>test ! -d backend/tests/smoke</automated>
<automated>rg --no-heading "_require_live_server|pytest.exit|returncode=1|getfixturevalue\\(\"_stdio_session\"\\)" backend/tests/e2e/conftest.py</automated>
<automated>just test-e2e</automated>
</verify>
<acceptance_criteria>
- `backend/tests/smoke` is deleted.
- `backend/tests/e2e/conftest.py` contains `_require_live_server`.
- `backend/tests/e2e/conftest.py` contains `pytest.exit`.
- `backend/tests/e2e/conftest.py` contains `returncode=1`.
- `backend/tests/e2e/conftest.py` contains `getfixturevalue("_stdio_session")`.
- HTTP e2e tests can run without starting `_StdioSession`.
- `just test-e2e` exits 0 when the running `dotmd` container is healthy.
</acceptance_criteria>
<done>
The stale smoke surface is gone and explicit live e2e fails honestly when runtime is absent.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Replace low-signal search and MCP tests</name>
<read_first>
- `backend/tests/api/test_service_search.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/mcp_server.py`
</read_first>
<files>
- `backend/tests/api/test_service_search.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Replace only the low-signal tests identified in `23-RESEARCH.md` and the review:

- `TestSearchReturnsFilePaths.test_search_returns_file_paths_list`
- `TestSearchRespectsTopK.test_search_respects_top_k`
- `TestGraphDirectHitAlsoHydrates`
- MCP search contract tests that prove behavior by inspecting `_format_result`
  internals or docstrings instead of registered tool schema / call output

Do not rewrite `TestCompareRerankers`, `TestServiceWarmup`, or
`TestSearchApiRerankerSurfaces` unless a focused adjustment is directly needed
to keep the changed contract passing.

1. In `backend/tests/api/test_service_search.py`, remove any assertion equivalent
   to `len(results) >= 0`. If `_execute_search` is mocked, assert the exact call
   arguments that matter: `top_k`, `rerank`, `pool_size`, and `reranker_name`.
   If the intent is top-k behavior, use a real service path or fake engines that
   return more results than requested and assert the service truncates them.

2. In `backend/tests/api/test_search_result_shape.py`, replace the graph-direct
   hydration claim that directly instantiates `SearchResult`. Exercise
   `build_search_results` directly with fake metadata and candidate IDs so the
   test proves graph-direct/fused candidate IDs hydrate to `file_paths`.

3. In `backend/tests/mcp/test_search_tool.py`, stop using docstring inspection as
   MCP contract proof. Inspect registered `tools/list` schema and a real/stubbed
   `tools/call` result for `search` instead. Keep `_format_result` unit coverage
   only if it asserts formatting behavior that is intentionally private.
</action>
<verify>
<automated>! rg --quiet "len\\(results\\) >= 0" backend/tests/api/test_service_search.py</automated>
<automated>cd backend && uv run pytest tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q</automated>
<automated>cd backend && uv run ruff check tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py</automated>
</verify>
<acceptance_criteria>
- `backend/tests/api/test_service_search.py` contains no `len(results) >= 0`.
- Search service mock tests assert relevant call arguments or use real-path fake engines.
- Graph-direct/file-path hydration is tested through `build_search_results` or service search.
- MCP search contract tests inspect registered schema or real/stubbed tool-call output.
- Focused API/MCP test command exits 0.
</acceptance_criteria>
<done>
Known low-signal tests now assert behavior that can catch regressions.
</done>
</task>

<task id="4" type="auto">
<name>Task 4: Add explicit embedding-boundary coverage and close gates</name>
<read_first>
- `backend/tests/conftest.py`
- `backend/src/dotmd/search/semantic.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_pipeline_metadata.py`
- `backend/pyproject.toml`
- `README.md`
</read_first>
<files>
- `backend/tests/conftest.py`
- `backend/tests/ingestion/test_pipeline_metadata.py`
- `backend/devtools/pyright-baseline.json`
</files>
<action>
Make the global semantic-engine patch boundary explicit.

- Keep the global patch for fast local tests if removing it would make the local
  suite too slow.
- Add one focused recording-wrapper test that bypasses or overrides the global
  zero-vector patch around `SemanticSearchEngine.encode_batch`.
- The invariant is context-prefix / encoded input content: a known title/context
  prefix and chunk body must reach the encoding boundary in the expected order.
- Prefer a unit-level recording wrapper over a fake HTTP server or live TEI.
- Avoid relying on the global 8-dimensional stub. Either return a controlled
  non-8-dimensional embedding from the recording boundary or assert the expected
  dimension path explicitly.
- Do not invert the global patch unless the focused recording-boundary test is
  impossible with the current fixture layout.

After code changes, update `backend/devtools/pyright-baseline.json` only if
`just typecheck` reports an actual improvement. Do not raise the baseline.
New or modified tests must introduce no pyright errors; fix type issues in the
changed tests instead of baselining them.

Opportunistically reduce additional pyright errors that are literally adjacent
to the files changed in this phase when the fix is mechanical, local, and
low-risk. Do not broaden the phase into unrelated typing refactors; leave
far-away or design-heavy type debt for a separate work item.
</action>
<verify>
<automated>just lint</automated>
<automated>just typecheck</automated>
<automated>just test</automated>
<automated>just test-e2e</automated>
<automated>just check</automated>
</verify>
<acceptance_criteria>
- At least one test bypasses or overrides the global `encode_batch` patch.
- That test asserts context-prefix / encoded input content at the
  `encode_batch` boundary.
- New and modified tests introduce no pyright errors.
- Additional nearby pyright errors are reduced when doing so is local and does
  not expand scope.
- `just lint` exits 0.
- `just typecheck` exits 0 and does not increase the pyright baseline.
- `just test` exits 0 without collecting live e2e/smoke tests.
- `just test-e2e` exits 0 inside the running `dotmd` container.
- `just check` exits 0.
</acceptance_criteria>
<done>
The local gate, live e2e gate, and focused embedding-boundary coverage are all green.
</done>
</task>
</tasks>

<verification>
Before marking Phase 23 complete:

```bash
just lint
just typecheck
just test
just test-e2e
just check
```

`just test-e2e` is intentionally a live-runtime gate. It requires the `dotmd`
container to be running and healthy; if the runtime is missing, the command
must fail non-zero instead of reporting skipped tests.

Also verify the stale smoke failure mode is gone:

```bash
! just --list | rg "test-smoke"
! just test-smoke 2>&1 | rg "9 skipped"
```
</verification>
