# Phase 23: Fix dotMD test contract - Context

**Gathered:** 2026-05-03
**Status:** Ready for planning
**Source:** Capture from live debugging and two read-only audit agents

<domain>
## Phase Boundary

Make dotMD's test commands and tests tell the truth about what they verify.
This phase is about test infrastructure and test signal, not product search
behavior.

The phase may change `justfile`, pytest markers/config, test files, and developer
docs. It should not change runtime search, indexing, OAuth, reranker, or MCP
production behavior except where tests reveal a real regression that must be
fixed to keep existing behavior.
</domain>

<decisions>
## Implementation Decisions

### D-01 Test tiers must be explicit
- Local tests must not require live Docker containers, external ports, TEI, or
  production data. Live container MCP tests must run through their own explicit
  command.

### D-02 Explicit live commands must fail on missing runtime
- If a developer runs `just test-e2e` or any remaining explicit live-smoke
  command and the required container/server is unavailable, the command must
  exit non-zero. A full-suite skip with exit code 0 is not acceptable.

### D-03 Default quality gate must not collect live suites accidentally
- `just test` and `just check` must run the local gate only by default. They must
  exclude `e2e` and any live `smoke` marker unless the user explicitly runs a
  live command.

### D-04 Legacy smoke tests should not survive as stale duplicate coverage
- The old `backend/tests/smoke` suite is stale against the current MCP surface
  (`status` removed, `search` does not accept `rerank=True`). Delete it or
  replace it with the current e2e contract; do not keep a command that skips all
  tests and returns green.

### D-05 E2E HTTP and stdio paths must be independent
- HTTP e2e cases must not start the stdio subprocess. Stdio should start only
  for stdio-parametrized tests.

### D-06 Low-signal tests should be replaced with behavioral checks
- Remove tautological assertions such as `len(results) >= 0`.
- Do not test mock setup and call that behavior coverage.
- Prefer public service/tool contracts over private helper/docstring assertions
  unless the private helper is intentionally the unit under test.

### D-07 Global embedding mocks need a clear boundary
- The global `SemanticSearchEngine.encode_batch` patch is allowed for fast local
  storage/unit tests only if its scope is explicit. At least one focused test
  must cover the real embedding-input boundary through a controlled fake TEI or
  equivalent boundary that does not rely on the global zero-vector patch.

### D-08 Documentation must name what each command proves
- README/developer docs must state which command is local-only, which command
  runs live container e2e, and which remote/Funnel smoke is operator-triggered.
</decisions>

<canonical_refs>
## Canonical References

### Existing test commands and config
- `justfile` - current developer command surface.
- `backend/pyproject.toml` - pytest markers and default addopts.
- `README.md` - currently describes `just check`, `just test`, and
  `just test-smoke`.
- `AGENTS.md` - project runtime instructions.

### Live MCP e2e
- `backend/tests/e2e/conftest.py` - HTTP/stdin MCP test transports and current
  PIN-code OAuth helper.
- `backend/tests/e2e/test_mcp_smoke.py` - current MCP surface contract tests for
  `search`, `read`, and `feedback`.
- `backend/src/dotmd/mcp_server.py` - current MCP tool surface.

### Stale smoke suite
- `backend/tests/smoke/conftest.py` - host-local health probe and all-skip
  behavior.
- `backend/tests/smoke/test_api.py` - stale host smoke assertions.
- `backend/tests/smoke/test_search_engines.py` - stale rerank smoke coverage.
- `backend/tests/smoke/test_hybrid_fusion.py` - stale hybrid smoke coverage.

### Low-signal tests flagged by audit
- `backend/tests/api/test_service_search.py` - mock-heavy search API tests with
  tautological or mock-return assertions.
- `backend/tests/api/test_search_result_shape.py` - result shape tests,
  including graph-direct hydration claim.
- `backend/tests/mcp/test_search_tool.py` - MCP tests that inspect helpers and
  docstrings instead of registered schema/call behavior.
- `backend/tests/conftest.py` - global semantic-engine patch.
</canonical_refs>

<specifics>
## Specific Findings To Address

- `just test-smoke` currently exits 0 with `9 skipped` when `localhost:8080`
  is unreachable.
- Plain pytest collection currently includes local, e2e, and smoke tests.
- `backend/tests/smoke/conftest.py` calls non-existent MCP `status`.
- `backend/tests/smoke/test_search_engines.py` passes unsupported `rerank=True`
  to MCP `search`.
- `backend/tests/e2e/conftest.py` injects `_stdio_session` into the parametrized
  `mcp_call` fixture, so stdio starts for HTTP cases too.
- `backend/tests/api/test_service_search.py` has low-signal assertions around
  mocked `_execute_search`.
- `backend/tests/api/test_search_result_shape.py` has a graph-direct hydration
  test that directly constructs `SearchResult` instead of exercising hydration.
- `backend/tests/mcp/test_search_tool.py` relies on `_format_result` and
  docstring inspection for MCP contract evidence.
</specifics>

<deferred>
## Deferred Ideas

- CI is desirable but may remain a follow-up if this repo intentionally has no
  remote CI surface yet. This phase should at least make local commands honest.
- Remote/Funnel tests remain separate under `just test-mcp-remote`; this phase
  should not require public network connectivity for local `just check`.
</deferred>

---

*Phase: 23-fix-dotmd-test-contract*
*Context gathered: 2026-05-03*
