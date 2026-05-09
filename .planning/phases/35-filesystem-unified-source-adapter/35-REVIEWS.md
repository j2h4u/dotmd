---
phase: 35
reviewers: [codex, opencode]
reviewed_at: 2026-05-10T00:00:00Z
plans_reviewed: [35-01-PLAN.md, 35-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 35

## Codex Review

## Summary

Plan 01 is solid and correctly scoped: it implements the public filesystem adapter boundary without moving orchestration into the adapter or widening `SourceAdapterProtocol`. Plan 02 is directionally right, but its lifecycle factory test is not executable against the current code as written because `SourceRuntimeFactory` does not accept `filesystem=config` directly. Overall, the phase is low implementation risk, with one medium test-plan correction needed before execution.

## Plan 01: Rename `_from_file_info`

### Strengths

- Correctly preserves the adapter/pipeline boundary from D-01.
- Does not add filesystem-specific behavior to `SourceAdapterProtocol`, which matches D-03.
- Updates the real production call site in `pipeline._source_document_for_file_info`.
- Keeps the change small and easy to review.
- Existing `_RecordingLifecycleAdapter` test double is the right place to prove the pipeline uses the lifecycle adapter.

### Concerns

- **LOW:** The verification says "existing test suite passes unchanged," but the test double must change from `_from_file_info` to `document_for_file_info`. The behavior stays unchanged, but the wording is slightly misleading.
- **LOW:** The grep check only covers `backend/src/`. That is fine for production code, but review should also expect `_from_file_info` to disappear from affected tests unless there is an intentional compatibility alias, which this plan does not propose.

### Suggestions

- Add a verification check for tests too: `rg "_from_file_info" backend/tests/ingestion/test_source_filesystem.py`.
- Prefer `rg` over `grep` in the verification commands.
- Make the acceptance wording "existing behavior passes unchanged" rather than "test suite passes unchanged."

### Risk Assessment

**LOW.** This is a mechanical rename with a narrow production surface. The main risk is missing a test double or one production call site, both covered by the proposed verification.

## Plan 02: Targeted Lifecycle Boundary Tests

### Strengths

- Tests the exact decision from D-07: public adapter method and lifecycle-built adapter method.
- Avoids brittle grep guard tests, matching D-08.
- Keeps the proof focused on filesystem behavior instead of expanding into trickle E2E scope.
- The direct adapter test checks the important identity fields: `namespace`, `document_ref`, `ref`, `media_type`, and `parser_name`.

### Concerns

- **MEDIUM:** The lifecycle factory test uses the wrong constructor shape. Current `SourceRuntimeFactory` requires `registry`, `config_store`, `credential_provider`, and `cursor_store`; it cannot be constructed as `SourceRuntimeFactory(filesystem=config)`.
- **LOW:** The test stubs reference `DocKind` but `test_source_filesystem.py` currently imports `ExtractDepth`, `FileInfo`, and `SourceDocument`, not `DocKind`.
- **LOW:** Verification commands use `tests/ingestion/...`, but from the repo root the path appears to be `backend/tests/ingestion/...`. Either run from `backend/` or use repo-root paths.
- **LOW:** "Do NOT change the test assertions" is too strict. If current canonical behavior includes frontmatter normalization or path resolution details, the executor should be allowed to adjust assertions to match the intended contract, not incidental stub text.

### Suggestions

- Rewrite the lifecycle test setup to mirror existing `test_source_lifecycle.py` patterns:
  - `InMemorySourceConfigStore`
  - `SourceConfigRecord(namespace="filesystem", config=FilesystemSourceConfig(paths=[str(tmp_path)]))`
  - `default_source_registry()`
  - `DefaultSourceCredentialProvider()`
  - `SQLiteSourceCursorStore(...)`
- Import `DocKind` if using `DocKind.DOCUMENT`, or use the existing string style if that is preferred in this test file.
- Change verification to one of:
  - `cd backend && python -m pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_source_lifecycle.py -q`
  - `python -m pytest backend/tests/ingestion/test_source_filesystem.py backend/tests/ingestion/test_source_lifecycle.py -q`
- Consider asserting `content_fingerprint` and `metadata_fingerprint` are non-empty in the direct test. That proves the public method still performs the full filesystem conversion, not just identity mapping.

### Risk Assessment

**MEDIUM as written, LOW after correction.** The implementation goal is simple, but the lifecycle test stub will fail until it uses the real factory construction path. Once corrected, the test adds useful coverage with little maintenance burden.

## Codex Overall Risk

**LOW to MEDIUM.** The phase plan achieves FS-02 and FS-03 cleanly, and FS-01 is adequately covered by existing pipeline tests plus the new lifecycle boundary tests. There are no meaningful security or performance concerns because this only renames a method and adds tests. The main fix needed is to make Plan 02's lifecycle factory setup match the actual codebase.

---

## OpenCode Review

# Phase 35 Plan Review

## Plan 01: Rename _from_file_info and update callers

### Summary

Plan 01 is a focused, minimal rename that correctly identifies the primary bypass — the pipeline calling a private `_from_file_info` on the adapter — and fixes it by making the method public. The scope is appropriate given the phase boundary, and the call-site audit (internal self-calls + pipeline call site + test double) is complete. However, the plan's verification omits `backend/tests/` from its grep exclusion check, risking overlooked test-only references.

### Strengths

- **Correctly identifies the architectural bypass:** The `_`-prefixed method being called from pipeline.py is the core FS-03 violation. Making it public is the right fix.
- **Minimal scope, no drift:** Three files touched, three call sites updated. Exactly fits D-02's interpretation of "public interface = no bypass."
- **Respects D-01 and D-03:** Doesn't touch `SourceAdapterProtocol`, doesn't move orchestration methods out of pipeline.
- **Verification is concrete and grep-able** — each verification item maps to a specific, measurable outcome.

### Concerns

- **HIGH — Verification grep is scoped to `backend/src/` only.** Task 35-01-03 updates `_RecordingLifecycleAdapter` in tests, but the verification step `grep -rn "_from_file_info" backend/src/` excludes `backend/tests/`. Any other test file referencing `_from_file_info` would survive undetected. The grep should cover `backend/` (or `backend/src/` + `backend/tests/` separately).

- **MEDIUM — No handling of `_source_document_for_file_info` renaming.** The pipeline method is also `_`-prefixed (it's the wrapper around the adapter call). While D-01 permits private pipeline orchestration methods, the method exists solely to wrap a single public adapter call. This is non-blocking for this plan, but worth flagging as potential follow-up scope creep if someone later questions why the pipeline still has `_filesystem_*` methods after the "unified" refactor.

- **LOW — No semantic change, only visibility.** The plan doesn't change behavior — it only removes an underscore. The "bypass" is resolved by convention (public API) rather than by structural enforcement (Protocol method). This is aligned with D-02, but means the FS-03 "no bypass" guarantee depends on discipline, not compiler enforcement.

### Suggestions

- Expand the final grep verification to `grep -rn "_from_file_info" backend/` to catch test-only references.
- Consider renaming `_source_document_for_file_info` to `source_document_for_file_info` (drop `_`) to signal the pipeline's public orchestration API, keeping D-01's spirit while reducing `_`-prefix proliferation around filesystem code.

### Risk Assessment: **LOW**

The plan is a pure rename with no behavioral changes. Failure mode is trivial — a missed call site would cause a runtime `AttributeError`. Existing test coverage catches this path. The only risk is an undiscovered call site in another test file that survives because verification grep is too narrow.

---

## Plan 02: Add targeted behavioral tests for public lifecycle boundary

### Summary

Plan 02 adds two behavior-driven tests proving the renamed public API works both directly on the adapter and through the lifecycle factory path. The tests are well-formed and map directly to D-07. However, the plan's TDD framing (RED first, GREEN second) collapses into a single de facto step since the stubs already assert the entire API shape. More critically, the plan contains no negative-path tests and doesn't cover the `source_document_to_file_info` validation invariant (D-04), which is the round-trip partner of `document_for_file_info`.

### Strengths

- **Tests map directly to D-07 requirements:** The two test cases exactly implement the two testing goals the user specified.
- **Lifecycle factory path is end-to-end:** Test 2 exercises `SourceRuntimeFactory.build("filesystem")` → `bundle.source.document_for_file_info()` — the complete construction path.
- **Verification gates are comprehensive:** Full test suite green + grep absence check provides a strong regression baseline.
- **GREEN task lists common pitfalls** (import paths, constructor arg names), which reduces debugging time during implementation.

### Concerns

- **HIGH — No negative/error-path tests.** What happens when `document_for_file_info` receives a `FileInfo` whose `path` points to a non-existent file? A file outside the configured source paths? A directory instead of a file? The adapter should either raise a specific exception or gracefully handle these cases. Without negative tests, the contract is underspecified.

- **HIGH — D-04 validation invariant (`source_document_to_file_info`) is untested.** The `source_document_to_file_info` function carries a validation invariant — `document_ref` must match the resolved `file_path`. This is the reverse direction of the tested flow and is not covered by either Plan 01 or Plan 02. If this invariant diverges from `document_for_file_info` during future changes, it will break delete detection and trickle rebinding silently.

- **MEDIUM — Test stubs hardcode `FilesystemSourceConfig(paths=[str(tmp_path)])`.** If the actual constructor uses a different field name (e.g., `source_paths`, `dir_paths`, `roots`), the RED phase will fail with an unrelated error, consuming implementation time on import/discovery rather than behavior verification. This isn't a plan defect per se, but the TDD workflow breaks if stubs don't compile.

- **MEDIUM — FS-01 regression scope is narrower than the requirement.** FS-01 demands that "discovery, trickle indexing, local file reads, delete detection, parser routing, and content-addressed reuse continue to work." Plan 02 tests only the adapter construction + document creation path. It does not test:
  - **trickle indexing** (adapter used in `index_file` flow with real pipeline)
  - **parser routing** (adapter producing correct `parser_name`)
  - **delete detection** (adapter used in `_deactivate_filesystem_binding`)
  - **content-addressed reuse** (adapter interacting with text_hash/embedding cache)
  
  D-06 defers these to existing integration tests, but Plan 02's verification only checks the full test suite is green — it doesn't add any of these failure-mode-specific tests.

- **LOW — D-08 tension.** The plan says "No grep-based guard tests" (D-08), but verification item 4 uses `grep` to verify code cleanliness. This is a non-issue (verification ≠ test), but D-08's rationale could be interpreted to discourage grep verification too. Worth clarifying in the plan that verification grep is post-hoc, not automated.

### Suggestions

- Add a third test for the `source_document_to_file_info` round-trip: `FileInfo → document_for_file_info → source_document_to_file_info → FileInfo` should be idempotent (D-04).
- Add a fourth test for the negative case: `document_for_file_info` with a `FileInfo` whose path doesn't exist raises a specific, documented exception (e.g., `FileNotFoundError` or a custom `SourceError`).
- Verify `parser_name` in both tests is actually `"markdown"` (already present in Test 1 but as a specific assert) — this is the parser routing path for FS-01. Good as-is.
- Consider renaming Task 35-02-02 from "GREEN" to "GREEN — fix imports and assertions" to avoid implying a separate commit after a failing test commit (TDD RED/GREEN should be atomic per test, not two tasks).

### Risk Assessment: **LOW**

The tests themselves are solid for what they cover. The risk is not in what's present but in what's missing — D-04 validation and negative-path coverage. Without these, future refactors (Telegram adapter in Phase 36-37, discovery API changes) could silently break filesystem invariants that existing tests don't guard.

---

## OpenCode Holistic Assessment

### Do these plans achieve the phase goals?

**FS-01** (everything still works): Partially. Plan 02 adds positive-path tests. The verification relies on existing integration tests (D-06), which is reasonable, but the lack of trickle/delete/parser-specific regression tests means this is a confidence-based proof, not an evidence-based one.

**FS-02** (paths only where needed): Minimally. Only one `_`-prefixed method is renamed. No audit confirms that no other path-shaped internals remain inappropriately. The plan assumes (reasonably) that `_from_file_info` was the sole bypass, but doesn't prove it.

**FS-03** (no bypass of registry/lifecycle): Achieved. Plan 01 fixes the known bypass, Plan 02 tests the lifecycle construction path. Combined with D-05 (trickle's `index_file(path)` is not a bypass), the public boundary is respected.

### Critical Gap

The D-04 invariant (`source_document_to_file_info` validation that `document_ref` matches `file_path`) has zero test coverage in these plans. Since Phase 33 (the dependency) presumably introduced `SourceDocument` and this invariant, it's surprising that Phase 35 wouldn't regression-test it. A `SourceDocument` with a mismatched `document_ref`/`file_path` would corrupt the M2M content-addressed schema, leading to orphaned chunks and broken deletes. This is the highest-value missing test.

### Recommendation

**Ship both plans as-is** with one amendment: add a D-04 round-trip test to Plan 02. Everything else can be addressed in follow-up phases or as Phase 35 is actually executed (the negative-path tests can be written opportunistically during GREEN). The plans are narrow but correctly focused — they just undershoot the full phase guarantee.

---

## Consensus Summary

Two reviewers — Codex and OpenCode — independently reviewed Plans 01 and 02 for Phase 35.

### Agreed Strengths

- Plan 01 is a minimal, correctly-scoped rename that closes the FS-03 bypass without touching `SourceAdapterProtocol` or moving orchestration out of the pipeline (D-01, D-03).
- The call-site audit in Plan 01 is complete: definition, two internal callers, pipeline call site, and test double.
- Plan 02 tests map directly to D-07's two specified goals (direct adapter access + lifecycle factory path).
- Verification gates are concrete and measurable (grep + pytest exits).
- The approach correctly avoids grep-based guard tests (D-08) in favor of behavioral tests.

### Agreed Concerns

- **Verification grep scope too narrow (Plan 01):** Both reviewers flag that `grep -rn "_from_file_info" backend/src/` excludes `backend/tests/`. Any surviving test reference would go undetected. Fix: expand to `backend/` or explicitly add `backend/tests/` to the check.
- **`SourceRuntimeFactory` constructor shape incorrect in Plan 02 lifecycle test:** Both reviewers note the test stub uses `SourceRuntimeFactory(filesystem=config)` which does not match the actual constructor. The executor needs to mirror existing `test_source_lifecycle.py` patterns (config store, registry, credential provider, cursor store).
- **`DocKind` import missing in Plan 02:** Both reviewers note `DocKind` is not currently imported in `test_source_filesystem.py` and must be added or substituted.

### Divergent Views

- **OpenCode rates two Plan 02 concerns as HIGH** (no negative-path tests, D-04 invariant untested); **Codex rates these MEDIUM or omits them.** OpenCode's framing is stronger: the D-04 round-trip (`document_for_file_info` → `source_document_to_file_info`) being untested is a real gap because a mismatch could silently corrupt the M2M schema and break delete detection. The reviewer consensus leans toward OpenCode's view that a D-04 round-trip test should be added to Plan 02.
- **OpenCode raises `_source_document_for_file_info` pipeline method renaming** as a MEDIUM suggestion; Codex does not surface this. This is an optional follow-up, not a blocker.
- **Overall phase risk:** Codex calls it LOW-MEDIUM overall; OpenCode agrees but labels Plan 02-specific gaps as HIGH. Both agree the fix is lightweight.

### Top Priority Action Items for Executor

1. **Expand Plan 01 verification grep** to cover `backend/` not just `backend/src/`.
2. **Fix Plan 02 lifecycle factory setup** to use `InMemorySourceConfigStore` + `SourceConfigRecord` + `default_source_registry()` pattern from `test_source_lifecycle.py`.
3. **Add a D-04 round-trip test** to Plan 02: `FileInfo → document_for_file_info → source_document_to_file_info → FileInfo` should be idempotent. This is the highest-value missing test per OpenCode.
4. **Verify `DocKind` import** or substitute the existing enum style used in the test file.
