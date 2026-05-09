---
phase: 35
reviewers: [codex, opencode]
reviewed_at: 2026-05-09T22:46:26Z
plans_reviewed: [35-01-PLAN.md, 35-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 35: Filesystem Unified Source Adapter

Plans reviewed: PLAN 01 (rename `_from_file_info` → `document_for_file_info`), PLAN 02 (public boundary + D-04 round-trip TDD tests).

---

## Codex Review

### Summary

Overall, both plans are well-scoped and aligned with the Phase 35 boundary. Plan 01 is a low-risk mechanical rename that directly addresses the private adapter bypass. Plan 02 adds the right kind of behavioral proof without expanding into trickle or pipeline restructuring. The main gap is that Plan 02 proves the public filesystem conversion path, but only lightly proves the broader FS-03 lifecycle claim; that may be acceptable given the phase decisions, but the verification wording should be tightened.

### Strengths

- Clear dependency order: Plan 02 correctly depends on Plan 01.
- The rename avoids polluting `SourceAdapterProtocol` with filesystem-only `FileInfo`, which preserves ISP/LSP for Telegram and future adapters.
- Keeping `source_document_to_file_info` in `source.py` is sound because it enforces the document-ref/file-path invariant, not just data conversion.
- The plans avoid pipeline/trickle restructuring, matching the phase boundary.
- Tests are targeted and behavioral, not brittle grep-only guards.
- Existing pipeline bridge already validates round-trip fields, so Plan 02 complements existing coverage instead of duplicating everything.

### Concerns

- **MEDIUM:** Plan 02's lifecycle test only proves `SourceRuntimeFactory.build("filesystem")` exposes the adapter method. It does not directly prove that production indexing/search/read/delete flows no longer bypass lifecycle. Existing tests may cover much of FS-01, but the plan should name which existing tests are relied on.
- **MEDIUM:** Verification says "Full test suite green." That is good as a final gate, but the actionable minimum should include `tests/ingestion/test_source_filesystem.py` and `tests/ingestion/test_source_lifecycle.py`; otherwise failures elsewhere could obscure whether this phase is correct.
- **LOW:** Plan 01 says `rg "_from_file_info" backend/` should return no output. The intent is right, but the acceptance criterion should be "no symbol references" rather than any string anywhere.
- **LOW:** Plan 02 test 1 directly instantiates `FilesystemMarkdownSourceAdapter()`. That is fine for adapter unit coverage, but it should be explicitly framed as a unit test exception so it is not confused with production lifecycle bypass.
- **LOW:** The "GREEN: fix assertion mismatches without changing assertions" wording is awkward. Better to say assertions may only change if they contradict established adapter contract.

### Suggestions

- Add explicit verification for lifecycle construction in Plan 02: `assert isinstance(bundle.source, FilesystemMarkdownSourceAdapter)` and `assert callable(bundle.source.document_for_file_info)`.
- Add or preserve a pipeline-level assertion that `_source_document_for_file_info()` calls the lifecycle factory and records the file info through the lifecycle adapter.
- Run focused checks before the full suite: `pytest backend/tests/ingestion/test_source_filesystem.py backend/tests/ingestion/test_source_lifecycle.py`
- Keep the grep check, but phrase it as: `rg "\\b_from_file_info\\b" backend/src backend/tests` returns no symbol references.
- In the round-trip test, assert `document.document_ref == str(md_path.resolve())` before converting back to directly exercise D-04's invariant surface.

### Risk Assessment

**Overall risk: LOW.**

The change is mostly a public-method rename plus focused tests. It does not alter source identity, parser routing, storage schema, trickle event handling, search, or read behavior. The only meaningful risk is false confidence around FS-03 if the lifecycle boundary is interpreted more broadly than the tests prove.

---

## OpenCode Review

### PLAN 01 — Rename _from_file_info and update callers

**Summary:** A clean mechanical rename touching 4 call sites across 3 files with grep-based verification. Low complexity, single concern — appropriate for Wave 1 with no dependencies.

**Strengths:**

- **Correct call site count.** The research confirmed exactly 4 references (2 self-calls in `discover()`/`discover_multi()`, 1 external in `pipeline.py:1371` via `bundle.source._from_file_info(file_info)`, 1 test double override at `test_source_filesystem.py:268`). All are accounted for in the tasks.
- **Phase 33 dependency honoured.** The pipeline call site already accesses through the lifecycle bundle, so the rename propagates correctly through the Phase 33 boundary without wiring changes.
- **Verification strategy is appropriate.** `rg "_from_file_info" backend/` + full test suite is sufficient for a rename.
- **Pure behavioral no-op.** The method body, signature, return type, and all semantics are unchanged — only visibility changes from `_private` to `public`.

**Concerns:**

- **[HIGH] Verification grep is scoped to `backend/src/` only.** Task 35-01-03 updates `_RecordingLifecycleAdapter` in tests, but the verification step `grep -rn "_from_file_info" backend/src/` excludes `backend/tests/`. Any other test file referencing `_from_file_info` would survive undetected. The grep should cover `backend/` (or `backend/src/` + `backend/tests/` separately).
- **[MEDIUM] No handling of `_source_document_for_file_info` renaming.** The pipeline method is also `_`-prefixed. While D-01 permits private pipeline orchestration methods, this is worth flagging as potential follow-up.
- **[LOW] No semantic change, only visibility.** The FS-03 "no bypass" guarantee depends on convention, not compiler enforcement. Aligned with D-02.

**Suggestions:**

- Expand the final grep verification to `grep -rn "_from_file_info" backend/` to catch test-only references.
- Consider running the existing test `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` after Task 35-01-01 (before the test double is updated) as a RED check.

**Risk Assessment: LOW** — A pure rename with 4 call sites and no behavioral change.

### PLAN 02 — Add public boundary and D-04 round-trip tests (TDD)

**Summary:** Three targeted TDD tests: direct adapter call, lifecycle factory path, and `FileInfo → SourceDocument → FileInfo` round-trip idempotency check. Together they validate FS-03 and D-04. The RED/GREEN structure is sound and the tests complement existing recording adapter tests.

**Strengths:**

- **Test 1 (direct adapter instantiation) is a valid unit-level boundary test.** Proves the method is callable and returns correct fields.
- **Test 2 (lifecycle factory path) validates FS-03.** Going through `SourceRuntimeFactory.build("filesystem")` is the "no bypass" proof.
- **Test 3 (round-trip idempotency) directly encodes D-04.** Covers `path`, `title`, `kind`, and `frontmatter` — exactly the fields production code validates.
- **RED phase before GREEN.** Correct TDD discipline.
- **All imports verified to exist.** All referenced classes are importable.

**Concerns:**

- **[HIGH] D-04 validation invariant (`source_document_to_file_info`) was untested in prior plan versions.** The current Plan 02 (as updated) adds this round-trip test — good. But the test description should clarify it tests both the conversion AND the invariant guard: namespace must be `"filesystem"`, `file_path` must not be `None`, `file_path` must exist on disk, and `document_ref` must match the resolved file path.
- **[MEDIUM] Test 2 may need more setup than the task description implies.** `SQLiteSourceCursorStore` likely requires a database connection or path. If it can't be constructed without a real SQLite database, the test will fail at setup, not at assertion. Use `tmp_path / "cursors.db"` or a minimal stub.
- **[MEDIUM] Test 1's assertion on fingerprints may be fragile.** `content_fingerprint` and `metadata_fingerprint` are computed by checksum functions that read the actual file. The test must create a real `.md` file before constructing `FileInfo` — otherwise `FileNotFoundError` in the RED phase.
- **[MEDIUM] FS-01 regression scope is narrower than the requirement.** Plan 02 tests only the adapter construction + document creation path. Trickle indexing, delete detection, content-addressed reuse are deferred to existing integration tests per D-06 — but the plan should explicitly name which existing tests are relied on.
- **[LOW] Test 2 assertion on `document_for_file_info` access underspecified.** Should call `bundle.source.document_for_file_info(file_info)` and verify the result, not just check `hasattr`.
- **[LOW] FS-02 coverage.** The requirement "Filesystem internals keep paths only where they are still required" is not directly addressed by these two plans.

**Suggestions:**

- For Test 2, use `tmp_path / "cursors.db"` for `SQLiteSourceCursorStore` or create a minimal stub.
- For Test 1, explicitly create a small `.md` file in `tmp_path` before constructing the `FileInfo`.
- For Test 2, assert by calling `bundle.source.document_for_file_info(file_info)` and checking the result, not just `hasattr`.
- Consider adding an error-path test: `document_for_file_info(FileInfo(path=nonexistent_path, ...))` to verify error originates from checksum functions.

**Risk Assessment: MEDIUM** — Test design is sound and imports are verified. Medium risk from unspecified `SQLiteSourceCursorStore` constructor requirements and missing explicit file-creation steps for fingerprint assertions.

### OpenCode Cross-Plan Summary

| Requirement | Plan 01 | Plan 02 | Notes |
|-------------|---------|---------|-------|
| FS-01 (everything works through unified contract) | Indirect (rename preserves behaviour) | Test 2 (lifecycle factory path) | Existing integration tests are primary per D-06 |
| FS-02 (paths only where needed) | Not addressed | Not addressed | Needs additional plan(s) |
| FS-03 (no lifecycle bypass) | Public method name (D-02) | Test 2 (factory path) | Good coverage |

**The phase requires additional plans beyond these two** to fully address FS-02.

---

## Consensus Summary

Two reviewers (Codex and OpenCode) independently reviewed Plans 01 and 02 for Phase 35. Both verified plans against the actual codebase before reviewing.

### Agreed Strengths

- Plan 01 is a minimal, correctly-scoped rename that closes the FS-03 bypass without touching `SourceAdapterProtocol` or moving orchestration out of the pipeline (D-01, D-03).
- The call-site audit in Plan 01 is complete: definition, two internal callers, pipeline call site, and test double.
- Plan 02 tests map directly to D-07's specified goals (direct adapter access + lifecycle factory path + D-04 round-trip).
- Verification gates are concrete and measurable (grep + pytest exits).
- The approach correctly avoids grep-based guard tests (D-08) in favor of behavioral tests.
- `source_document_to_file_info` retention in `source.py` is sound — it carries the document_ref ↔ file_path validation invariant.

### Agreed Concerns

- **[HIGH] Verification grep scope too narrow (Plan 01).** Both reviewers flag that the verification grep for `_from_file_info` excludes `backend/tests/`. Any surviving test reference would go undetected. Fix: expand to `rg "_from_file_info" backend/` covering both `src/` and `tests/`.
- **[MEDIUM] Test 2 SQLiteSourceCursorStore setup requirements unspecified.** Both reviewers flagged potential test setup issues — `SQLiteSourceCursorStore` may need a real SQLite database path. Resolution: use `tmp_path / "cursors.db"` or a minimal stub.
- **[MEDIUM] Plan 02 verification list should name specific existing tests that prove FS-01 coverage.** "Full test suite green" is too broad. Should explicitly reference `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` as the primary FS-01 regression proofs.
- **[MEDIUM] FS-02 not addressed by either plan.** Both reviewers independently noted that FS-02 ("paths only where still required") is unaddressed. Phase is incomplete without additional plan(s).

### Divergent Views

- **OpenCode rates Plan 01 verification gap as HIGH** (grep scope too narrow); Codex rates it LOW. Given that a missed reference would silently survive, HIGH is the more cautious and appropriate rating.
- **OpenCode raised D-04 round-trip test absence as HIGH** in prior review cycle; the current Plan 02 now includes Test 3 (the round-trip test), addressing this concern. This is now a RESOLVED item.
- **Overall phase risk:** Codex rates LOW overall; OpenCode rates Plan 02 at MEDIUM due to setup risks. Both agree fixes are lightweight.

### Top Priority Action Items for Executor

1. **Expand Plan 01 verification grep** to cover `backend/` not just `backend/src/`: `rg "_from_file_info" backend/` must return no output.
2. **Fix Test 2 cursor store setup** in Plan 02: use `SQLiteSourceCursorStore(SQLiteMetadataStore(db_path=tmp_path / "cursors.db", table_name="..."))` pattern from `test_source_lifecycle.py`.
3. **Ensure Test 1 creates a real `.md` file** in `tmp_path` before constructing `FileInfo` — fingerprint assertions require the file to exist on disk.
4. **Test 2 assertion should call `bundle.source.document_for_file_info(file_info)`** and verify the result, not just check attribute existence.
5. **Add additional plan(s)** to address FS-02 (paths only where still required) — not covered by Plans 01 or 02.
