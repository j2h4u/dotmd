---
phase: 23
reviewers: [opencode, claude]
reviewed_at: 2026-05-03T16:38:20+05:00
plans_reviewed:
  - 23-01-test-contract-cleanup-PLAN.md
---

# Cross-AI Plan Review — Phase 23

## OpenCode Review

Let me examine the current state of the relevant files before providing the review.
Now I have a complete picture. Here's my review:

---

## Plan Review: Phase 23 Plan 01 — Test Contract Cleanup

### Summary

A well-structured, single-plan cleanup that directly addresses all four TEST-CONTRACT requirements and all eight user decisions. The plan correctly identifies the root causes (stale skip-all green paths, unsplit stdio fixture, tautological assertions, global mock blind spot) and proposes surgical fixes. The main risks are in Task 3 (judgment calls on how far to rewrite mock-heavy tests) and Task 4 (embedding boundary test scope creep). Overall a solid executable plan with one significant gap and a few minor issues.

### Strengths

- **Precise problem diagnosis.** The stale smoke suite (`tool_call("status")`, `rerank=True`), the e2e skip-all-on-unreachable pattern, and the `_stdio_session` bleeding into HTTP tests are all confirmed by code inspection. The plan doesn't invent problems.
- **Marker exclusion strategy is sound.** Only 4 files use `pytestmark` — the 3 smoke files use `@pytest.mark.smoke` and the e2e file uses `@pytest.mark.e2e`. All other ~40 test files have no marker, so `-m "not e2e and not smoke"` will correctly isolate local tests.
- **Threat model maps to real failure modes.** Each threat row corresponds to a specific, observable behavior in the current codebase.
- **Verification commands are concrete and automatable.** Both positive (`just test`, `just check`) and negative (no `9 skipped` in output) checks are specified.
- **Task ordering is correct.** Task 1 (commands) → Task 2 (delete stale) → Task 3 (fix low-signal) → Task 4 (close gates) follows natural dependency.
- **One plan, one wave is the right call.** The tasks are interdependent enough that splitting into multiple plans would add coordination overhead for no benefit.

### Concerns

- **[MEDIUM] Task 2: `pytest.exit()` at collection time may conflict with pytest internals.** `pytest_collection_modifyitems` is a hook that runs during collection. Calling `pytest.exit()` there works but produces an ugly "session interrupted" message and may not play well with plugins like `-p no:cacheprovider`. A cleaner alternative: use a `session-scoped` fixture (`_require_live_server`) that does a health check and calls `pytest.exit()` or raises a fixture-setup error. This also avoids the subtle issue where `pytest_collection_modifyitems` sees ALL collected items (not just e2e), so the `if "e2e" in str(item.fspath)` string check is fragile.

- **[MEDIUM] Task 2: stdio fixture split design is underspecified.** The current `mcp_call` fixture is a single parametrized fixture that takes `_stdio_session` as a dependency. Splitting this requires either (a) two separate fixtures (`mcp_call_http` / `mcp_call_stdio`) with separate parametrization, or (b) making `_stdio_session` an optional dependency via `request.param`. The plan says "Split HTTP and stdio fixtures" but doesn't specify the mechanism, and this is the trickiest refactor in the plan because every e2e test uses `mcp_call`.

- **[LOW] Task 3: Scope boundary for `test_service_search.py` is ambiguous.** The file has 532 lines. The low-signal issues are in `TestSearchReturnsFilePaths` (lines 32-59, specifically line 52) and `TestSearchRespectsTopK` (lines 62-86, specifically the mock-returning-exactly-3 issue). But the plan doesn't explicitly state whether `TestCompareRerankers` (~200 lines of detailed mock assertions), `TestServiceWarmup`, and `TestSearchApiRerankerSurfaces` are in scope. Those test classes have reasonable assertion quality (they check call arguments, shared pools, error isolation). The plan should explicitly say "only rewrite the two flagged test classes" to avoid scope creep.

- **[LOW] Task 2: `backend/tests/smoke/pytest.ini` is listed in `files_modified` but doesn't exist.** Only `__init__.py`, `conftest.py`, and the three test files exist in the smoke directory. Minor — won't cause a failure, but indicates the plan was written from audit notes rather than a directory listing.

- **[LOW] Task 4: "Controlled fake TEI" is architecturally vague.** The plan says "assert encoded input text or fake TEI request payload content" but the current `SemanticSearchEngine.encode_batch` is a method that makes HTTP calls to TEI. A "controlled fake TEI" would require either (a) an `httpx` mock at the transport level, (b) a fake TEI server on a port, or (c) intercepting at the `encode_batch` boundary with a recording wrapper. The plan wisely says "Do not perform a broad test rewrite" but should commit to one of these approaches to avoid ambiguity during execution.

- **[LOW] Task 1: `test-smoke` alias decision is left open.** The plan says "Either make it a compatibility alias to `just test-e2e` or remove it." This should be decided now — leaving it open means the executor has to make a product decision. Given D-04 and the plan's own analysis, removal is the right call.

### Suggestions

- **Task 2: Replace the `pytest_collection_modifyitems` skip hook with a session-scoped `_require_live_server` fixture.** This is cleaner than calling `pytest.exit()` inside a collection hook, and it naturally fails with a clear error message when the health check fails. Example:

  ```python
  @pytest.fixture(scope="session", autouse=True)
  def _require_live_server():
      try:
          r = httpx.get("http://localhost:8080/health", timeout=5.0)
          if r.status_code == 200:
              return
      except (httpx.ConnectError, httpx.TimeoutException):
          pass
      pytest.exit("dotMD MCP server not reachable at http://localhost:8080", returncode=1)
  ```

  Remove the `pytest_collection_modifyitems` hook entirely.

- **Task 2: For the stdio split, use indirect fixture parametrization.** Keep one `mcp_call` fixture but make `_stdio_session` a conditional dependency:

  ```python
  @pytest.fixture(params=["http", "stdio"])
  def mcp_call(request):
      if request.param == "http":
          return _http_call
      sess = request.getfixturevalue("_stdio_session")
      return sess.call
  ```

  `request.getfixturevalue()` lazily resolves the fixture only when needed, so HTTP cases never trigger `_stdio_session` startup.

- **Task 3: Scope the rewrite to exactly the flagged items.** Explicitly list what to rewrite:
  - `TestSearchReturnsFilePaths.test_search_returns_file_paths_list` — fix line 52 assertion
  - `TestSearchRespectsTopK.test_search_respects_top_k` — use real service path or fix mock
  - `TestGraphDirectHitAlsoHydrates` — exercise `build_search_results` or `get_file_paths_for_chunk_ids`
  - `TestFilePathsIsJsonArray` + `TestDocstringMentionsFilePaths` — inspect registered schema
  - Leave all `TestCompareRerankers`, `TestServiceWarmup`, and `TestSearchApiRerankerSurfaces` tests untouched.

- **Task 4: Commit to a recording wrapper approach.** Add a test that uses the real `SemanticSearchEngine` class but intercepts at the `httpx.post` level to record what text gets sent to TEI. This tests the actual prefix-injection and batching logic without needing a running TEI server.

- **Task 1: Decide `test-smoke` → remove it.** Alias adds confusion. Update docs accordingly.

### Risk Assessment

**Risk: MEDIUM**

The plan is well-scoped and the first two tasks are straightforward deletions and config changes with clear acceptance criteria. The risk comes from:

1. **Task 2 stdio refactor** — the parametrized fixture split requires understanding pytest's fixture resolution lifecycle. Using `request.getfixturevalue()` is the right approach but the plan doesn't specify it, leaving the executor to design the solution.
2. **Task 3 scope ambiguity** — without an explicit "rewrite only these 4-5 test methods" list, an autonomous executor might over-rewrite the well-structured `TestCompareRerankers` tests.
3. **Task 4 is open-ended** — "focused boundary test" could mean 20 lines or 200 lines depending on interpretation.

None of these are blockers, and the plan's "do not perform a broad test rewrite" guardrails help. The phase goal is achievable with this plan, but the executor should resolve the three ambiguities above before starting.

---

## Claude Review

## Phase 23 Plan 01: Test Contract Cleanup — Review

### Summary

A well-scoped, research-backed cleanup plan with concrete acceptance criteria and a verified threat model. The task ordering is sound (config → delete stale → improve unit tests → add boundary coverage), and the research phase already identified the specific problematic patterns. The main weakness is two spots of implementation ambiguity — Task 1 leaves the fate of `test-smoke` as an either/or, and Task 4's "focused boundary test" is underspecified enough that two executors would write different things. Neither is a blocking issue, but both will require judgment calls mid-execution.

---

### Strengths

- **Phase boundary is tight.** Explicitly excludes runtime behavior changes; only test infrastructure and signal quality in scope.
- **Research is already done and specific.** Exact file names, line-level patterns (`tool_call("status")`, `rerank=True`, `len(results) >= 0`), and observed exit codes are all captured. Executor doesn't need to re-investigate.
- **Acceptance criteria are machine-checkable.** Most `<acceptance_criteria>` blocks can be verified with `rg` or pytest collection output rather than human judgment.
- **Negative validation is included.** The final `! just test-smoke 2>&1 | rg "9 skipped"` check guards against the exact regression that triggered this phase.
- **Threat model covers false-confidence scenarios** — the most dangerous class of test infra bugs — rather than just "tests pass/fail."

---

### Concerns

**HIGH**

- **Task 4: Embedding boundary test is underspecified.** The action says "add a marker or fixture override" and "assert encoded input text or fake TEI request payload content" without specifying the mechanism. A fake HTTP TEI server, a monkeypatch override, or a standalone unit test against `encode_batch` all satisfy the acceptance criteria but have very different scopes and maintenance costs. Two of these three options require non-trivial setup. Without a prescribed approach, the executor may produce something too thin (just overrides the global patch and asserts the argument is a string) or too heavy (spins up a test HTTP server). The acceptance criterion "asserts encoded input text or fake TEI request payload content" is too broad — it should name the specific invariant: context prefix injection, correct chunk text selection, or embedding dimension.

- **Task 1: `test-smoke` fate is ambiguous.** The action says "either make it a compatibility alias to `just test-e2e`, or remove it." D-04 says "Delete it or replace it." These are meaningfully different: removing test-smoke and aliasing it to test-e2e affect the final verification differently. The end-of-plan verification `! just test-smoke 2>&1 | rg "9 skipped"` would pass either way (removed recipe → rg finds nothing → negation succeeds), but the developer doc update in Task 1 depends on which path was chosen. Pick one.

**MEDIUM**

- **`pytest.exit` placement isn't specified.** Task 2 requires `backend/tests/e2e/conftest.py` to call `pytest.exit(returncode=1)` when the MCP server is unreachable. The acceptance criterion doesn't say whether this is a session-scoped autouse fixture, a module-level check, or a skip-turn-to-fail. Session-scoped is correct (one check, fail fast), but a module-level check would silently pass if the conftest is collected but no tests run. The executor needs to be explicit.

- **`just test-e2e` in final verification requires a running container.** The plan's final checklist calls `just test-e2e`, which by design will exit non-zero without the container. This is the right behavior per D-02, but the verification section doesn't acknowledge that this step requires the container to be up. Anyone reading the plan as a CI checklist will be confused. Add a note: "run `just test-e2e` inside the live environment only."

- **Task 3: Graph-direct hydration replacement is underspecified.** "Exercise `build_search_results` or the service search path with fake metadata" — these are different test shapes. `build_search_results` is a unit test; the service search path with fake engines is an integration test. Both would satisfy the acceptance criterion. Recommend: call `build_search_results` directly with a fake candidate list containing graph-direct IDs, then assert that `file_paths` is populated from metadata. Simpler, focused.

- **New test files may introduce pyright errors.** Task 4 instructs: "Do not raise the baseline." But Tasks 3 and 4 both write new test code. If new files have type errors, the baseline would need to increase. The plan should state: fix type errors in new/modified test code rather than baselining them.

**LOW**

- **`backend/tests/smoke/__init__.py` not listed.** If it exists, it needs to be in `files_modified` or the directory delete needs an explicit `rm -r` instruction.
- **Stdio fixture verification is implicit.** The acceptance criterion "HTTP e2e tests can run without starting `_StdioSession`" has no automated check. `just test-e2e` passing only proves the suite runs, not that stdio was never started for HTTP cases. A log-level assertion or a counter fixture would make this explicit, but this is a low-priority gap.
- **README update completeness is not verified.** Task 1 checks for presence of `just test-e2e` and `local tests` strings in README, but doesn't verify accuracy of the `just test-mcp-remote` section which is mentioned in the action but not in the acceptance criteria.

---

### Suggestions

1. **Task 1:** Remove `test-smoke` from justfile entirely. Update README to note it's been removed. This is cleaner than aliasing and avoids confusion about whether `test-smoke` and `test-e2e` are different things.

2. **Task 2:** Specify a session-scoped autouse fixture in `conftest.py` that does a `GET /health` probe at session start. On failure: `pytest.exit("dotMD MCP server unreachable at http://localhost:8080 — run `just test-e2e` inside the container", returncode=1)`.

3. **Task 4:** Narrow the embedding boundary test requirement. The invariant to protect is context prefix injection. The focused test should: (a) create a `SemanticSearchEngine` with a fake TEI callable, (b) index one chunk with a known title, (c) assert the concatenated input to `encode_batch` starts with `"passage: <title>"` (or however the prefix is constructed). This is a unit test, no HTTP server needed, and it directly catches a regression in prefix injection logic.

4. **Add to Task 4 acceptance criteria:** "New and modified test files produce no new pyright errors (baseline does not increase)."

5. **Final verification section:** Add: "`just test-e2e` requires the `dotmd` container to be running and healthy. Run this step in the live environment only."

---

### Risk Assessment

**MEDIUM**

The plan is solid and all four requirements are clearly addressed. The medium risk comes from the two underspecified implementation points (Task 1 either/or and Task 4 boundary test shape) that will require in-flight judgment calls. Neither will cause a wrong outcome, but both could produce a weaker result than intended — specifically, an embedding boundary test that asserts something too shallow to catch real regressions. The stale smoke removal and conftest.py fix are well-specified and low-risk.

---

## Consensus Summary

Both reviewers consider the plan directionally correct and executable, with medium overall risk. The shared concern is not that Phase 23 is too broad, but that a few executor choices are left open where the right answer is already implied by the phase decisions.

### Agreed Strengths

- The plan targets real observed failures: skip-all green smoke, stale MCP smoke calls, stdio startup bleed into HTTP e2e, tautological assertions, and the global embedding mock blind spot.
- One plan / one wave is appropriate because the tasks are tightly coupled and share the same test-command contract.
- The threat model and verification commands focus on false confidence, which is the correct risk class for this phase.
- Requirements and decisions are covered by the plan.

### Agreed Concerns

- `test-smoke` should not remain an either/or decision. Both reviewers recommend removing it rather than aliasing it to `test-e2e`.
- The e2e missing-runtime failure should be implemented with a session-scoped autouse fixture or equivalent fail-fast mechanism, not a collection-time all-skip hook.
- The e2e fixture split should use lazy fixture resolution such as `request.getfixturevalue("_stdio_session")` so HTTP cases do not start stdio.
- Task 3 should be explicitly scoped to the known low-signal tests and avoid broad rewrites of existing high-signal reranker comparison tests.
- Task 4 should specify one focused embedding-boundary invariant, preferably context prefix / encoded input content, and should not introduce new pyright debt.

### Divergent Views

- OpenCode rated the embedding-boundary ambiguity as LOW and the stdio split as MEDIUM; Claude rated the embedding-boundary ambiguity as HIGH. Both agree it should be tightened before execution.
- OpenCode suggested an `httpx.post` recording-wrapper approach for the embedding boundary, while Claude suggested a fake TEI callable / unit-level context-prefix invariant. Both point to the same intent: test encoded input content without a real TEI server.
