---
phase: 35
reviewers: [codex, opencode]
reviewed_at: 2026-05-10T00:00:00Z
plans_reviewed: [35-01-PLAN.md, 35-02-PLAN.md]
---

# Cross-AI Plan Review — Phase 35: Filesystem Unified Source Adapter

Plans reviewed: PLAN 01 (rename `_from_file_info` → `document_for_file_info`), PLAN 02 (public boundary + D-04 round-trip TDD tests).

> **Cycle 2 — 2026-05-10**: Fresh independent reviews from Codex and OpenCode. See Consensus Summary for resolved/outstanding items.

---

## Codex Review

### Summary

The plans are sound and appropriately narrow for the decisions captured in `CONTEXT.md`. I verified the current code shape: `_from_file_info` exists only in `source.py`, one pipeline call site, and one test double. Renaming it plus adding lifecycle-boundary tests directly addresses the FS-03 public-boundary concern without pulling filesystem-specific APIs into `SourceAdapterProtocol`. Main gap: the phase success criteria mention search/read preservation, but the plan's explicit verification is mostly ingestion/source-boundary oriented.

### Strengths

- Keeps `SourceAdapterProtocol` clean: no filesystem-only `FileInfo` method forced onto Telegram or future adapters.
- Preserves dependency direction: adapter builds `SourceDocument`; pipeline owns orchestration, binding, retained docs, and validation.
- Correctly treats trickle `index_file(Path)` as an OS-event boundary, not a lifecycle bypass.
- Good sequencing: rename first, then add tests against the new public boundary.
- Tests focus on behavior through direct adapter and `SourceRuntimeFactory`, not brittle implementation policing.

### Concerns

- **MEDIUM:** Plan verification does not explicitly prove filesystem search/read still work, although the phase success criteria mention indexing/search/read. If existing tests cover this, name and run them; otherwise add a small existing-regression selection to verification.
- **LOW:** `Plan 01` grep count checks are useful locally but brittle as formal acceptance. A future comment/docstring could skew counts. The important checks are behavior and absence of the private call in production.
- **LOW:** `Plan 02` lifecycle factory test depends on constructing `SQLiteMetadataStore`; this is fine with `tmp_path`, but the test should avoid relying on global state and should close/let fixtures clean up cleanly if the suite has leakage issues.
- **LOW:** Because `document_for_file_info` intentionally stays off `SourceAdapterProtocol`, the pipeline depends on the filesystem-specific `SourceRuntimeBundle.source` type. That is acceptable now, but worth making explicit in the test/assertion names so future generalization does not accidentally erase the filesystem-specific boundary.

### Suggestions

- Add explicit verification for existing read/search preservation — name the smallest relevant tests around filesystem provenance/search, or current ingestion-to-read regression tests if they exist.
- Replace "exactly N grep lines" acceptance with semantic checks: no `_from_file_info` under `backend/src`, pipeline calls `document_for_file_info`, and targeted pytest suite passes.
- In Test 1, assert `source_uri` and `document_type` too, since those are part of the parser/read/display contract.
- In Test 2, assert `bundle.source is not None` before calling the method. It documents the lifecycle expectation and gives clearer failures.
- In Test 3, keep the D-04 invariant focused: use a real markdown file and real checksums, then round-trip through `source_document_to_file_info` and assert path/title/kind/frontmatter.

### Risk Assessment

**Overall risk: LOW.** The implementation change is a rename plus one pipeline call-site update, with no storage, trickle, parser, MCP, API, or search behavior changes. The largest risk is not runtime breakage but under-proving the broader phase wording around search/read. Add or name the relevant existing regression tests, and the plan is strong enough to execute as written.

---

## OpenCode Review

### Plan 01 Review: Rename `_from_file_info` → `document_for_file_info`

**Summary:** A minimal, mechanical rename across 4 files (definition, 2 internal calls, 1 pipeline call site, 1 test double). Risk is near-zero — it's a find-and-replace with no behavioral change. This is exactly the right scope for what it does.

**Strengths:**

- **Zero behavioral change**: the rename is purely cosmetic — code continues to work identically.
- **Correct scope**: only touches the 4 locations that reference the private name. There are no other references to `_from_file_info` in the codebase (confirmed by `rg`).
- **Clear verification**: `rg "_from_file_info" backend/` returning empty output is a strong, one-command completeness check.
- **No protocol change**: correctly avoids `SourceAdapterProtocol` per D-03 (ISP).

**Concerns:**

- **MEDIUM**: The acceptance criterion for Task 35-01-01 says "at least 3 lines" for `grep -n "document_for_file_info" source.py`. There are exactly 3 occurrences (definition + 2 `self.*` calls in `discover`/`discover_multi`). Using "at least 3" instead of "exactly 3" is slightly weaker — a docstring example could skew the count and mask incomplete rename. Consider "exactly 3" for production code verification.
- **LOW**: The verification criteria #1 (`rg "_from_file_info" backend/ returns no output`) runs across the entire codebase. If any planning document or ADR in `backend/` happened to reference the old name, this check would fail incorrectly. Since `backend/` is the Python source root, this is probably fine.
- **LOW**: The `_RecordingLifecycleAdapter` in the test file currently overrides `_from_file_info` as a recording proxy. After the rename, this will be `document_for_file_info`. The plan correctly identifies this.

**Suggestions:**

1. Tighten the acceptance criterion from "at least 3" to "exactly 3" in source.py.
2. Consider scoping verification #1 to `rg "_from_file_info" backend/src/ backend/tests/` to be explicit.
3. Verify `super()._from_file_info(file_info)` in the test double also gets renamed — the plan mentions updating the override but should explicitly confirm the `super()` call line.

**Risk Assessment: LOW** — A single-method rename with exactly 6 locations changed. No dependencies, no behavioral edge cases. Verifiable with a single grep.

### Plan 02 Review: Public `document_for_file_info` boundary tests

**Summary:** Adds three behavior-focused tests that prove the public boundary: direct adapter access, lifecycle-factory path, and round-trip invariant. Test structure is sound — it covers the exact access patterns that matter for FS-03 compliance. However, the test construction is under-specified in one critical place (file creation before `chunk_checksum`), which will cause a RED-phase failure that needs fixing in GREEN.

**Strengths:**

- **Well-structured coverage**: Test 1 proves direct adapter access, Test 2 proves lifecycle factory path, Test 3 proves the D-04 round-trip invariant. Each tests a distinct boundary.
- **Correct dependency on Plan 01**: the tests naturally require the rename to exist first.
- **Existing regression coverage respected (D-06)**: the plan relies on existing integration tests (`test_pipeline_source_document_for_file_info_uses_lifecycle_adapter`, `test_source_lifecycle.py`).
- **No grep-based guard tests (D-08)**: correctly avoids brittle structural assertions in favor of behavioral tests.
- **Imports are well-understood**: all types come from existing modules (`source_lifecycle`, `source_registry`, `storage.metadata`).

**Concerns:**

- **HIGH**: Test 1 and Test 2 are under-specified about file creation. `document_for_file_info()` calls `chunk_checksum(file_info.path)` and `meta_checksum(file_info.path)` — both of which read the file. If the test constructs a `FileInfo(path=tmp_path / "test.md", ...)` without first writing the file to disk, `chunk_checksum` will raise `FileNotFoundError`. Task 35-02-02 mentions `_write_markdown` in its common checks list, but without an explicit connection to Test 1's setup. The RED→GREEN flow is correct (tests fail first, then fix), but this is the expected failure mode.
- **MEDIUM**: `SQLiteSourceCursorStore` requires an `SQLiteMetadataStore` for construction. The `db_path` should be a `Path` object, e.g. `tmp_path / "test.db"`, not a string representation. Task 35-02-02 handles this in the GREEN phase but the spec is ambiguous.
- **MEDIUM**: `source_document_to_file_info` (used in Test 3) raises `FileNotFoundError` if `document.file_path` doesn't exist on disk. The round-trip test must ensure the source markdown file exists before converting. The plan mentions `_write_markdown` for round-trip but the connection is implicit.
- **LOW**: Test 1 "construct a `FileInfo`" — `FileInfo` requires `last_modified: datetime` and `size_bytes: int`. The plan doesn't specify what values to use. GREEN phase notes should address these defaults.

**Suggestions:**

1. **Explicitly describe Test 1 setup**: write the file with `_write_markdown(md_path, 'Test', ['tag'], 'body')` before constructing `FileInfo`.
2. **For Test 2**: use `db_path=tmp_path / "cursors.db"` for `SQLiteMetadataStore` to avoid ambiguity.
3. **For Test 3 round-trip**: make explicit that `source_document_to_file_info` re-reads `stat()` from disk, so `size_bytes` in the recovered `FileInfo` will be the actual file size.
4. **Add `from datetime import UTC, datetime`** to the import list if not already present.

**Risk Assessment: LOW** — Three isolated behavioral tests with well-understood dependencies. The under-specification of file creation will cause a RED-phase failure, but Task 35-02-02 explicitly exists to handle this. No production code changes, no schema modifications, no new dependencies.

### OpenCode Cross-Plan Summary

| Requirement | Plan 01 | Plan 02 | Notes |
|-------------|---------|---------|-------|
| FS-01 (everything works through unified contract) | Indirect (rename preserves behaviour) | Test 2 (lifecycle factory path) | Existing integration tests are primary per D-06 |
| FS-02 (paths only where needed) | Not addressed | Not addressed | Accepted per CONTEXT.md scope |
| FS-03 (no lifecycle bypass) | Public method name (D-02) | Test 2 (factory path) | Good coverage |

---

## Consensus Summary

Two reviewers (Codex, OpenCode) independently reviewed Plans 01 and 02 for Phase 35 on 2026-05-10. Both reviewers inspected actual codebase files before reviewing.

### Agreed Strengths

- Plan 01 is a minimal, correctly-scoped rename that closes the FS-03 bypass without touching `SourceAdapterProtocol` or moving orchestration out of the pipeline (D-01, D-03).
- The call-site audit in Plan 01 is complete: definition, two internal callers, pipeline call site, and test double — all accounted for.
- Plan 02 tests map directly to D-07's specified goals (direct adapter access + lifecycle factory path + D-04 round-trip).
- Verification gates are concrete and measurable (grep + pytest exits).
- The approach correctly avoids grep-based guard tests (D-08) in favor of behavioral tests.
- `source_document_to_file_info` retention in `source.py` is sound — it carries the document_ref ↔ file_path validation invariant.

### Agreed Concerns

- **MEDIUM (both)**: Plan 02 test setup under-specifies file creation. `document_for_file_info()` reads the file for checksums, so all three tests must call `_write_markdown` before constructing `FileInfo`. The GREEN task (35-02-02) exists to fix this, but executors should know the expected RED failure mode: `FileNotFoundError` from `chunk_checksum`, not an assertion error.
- **MEDIUM (both)**: Plan 02 verification should explicitly name the FS-01 primary regression proofs. "Full test suite green" is too broad — should explicitly call out `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` as the named FS-01 gates.
- **MEDIUM (Codex)**: Plan verification does not explicitly prove filesystem search/read still work. Either name the relevant existing tests or add them to the final verification gate.
- **MEDIUM (OpenCode)**: Plan 01 acceptance criterion uses "at least 3 lines" for the grep count; "exactly 3" would be tighter.

### Divergent Views

- **Codex** rates overall risk as LOW throughout; **OpenCode** rated Plan 02 medium initially due to setup risks, but both agree the fixes are lightweight and self-correcting via TDD.
- **FS-02 coverage**: OpenCode flagged it as "needs additional plan(s)"; Codex did not raise it explicitly. Per CONTEXT.md, FS-02 ("paths only where still required") is addressed by the design decisions themselves (D-01, D-04, D-05) — paths stay in pipeline orchestration and `source_document_to_file_info`. The reviewers disagree on whether this requires an explicit test or plan task. Given the CONTEXT.md decisions are authoritative, this is not a blocking concern.

### Top Priority Action Items for Executor

1. **File creation before FileInfo construction (Tests 1, 2, 3)**: call `_write_markdown(md_path, ...)` before building `FileInfo` in all three Plan 02 tests. Expected RED failure without this: `FileNotFoundError` from `chunk_checksum`.
2. **Cursor store db_path**: use `tmp_path / "cursors.db"` for `SQLiteMetadataStore` in Test 2.
3. **Plan 02 verification block**: explicitly name `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` as the primary FS-01 regression proofs.
4. **Plan 01 grep count**: tighten "at least 3" to "exactly 3" for the `document_for_file_info` occurrence count in source.py.
5. **`super()` call in test double**: confirm both the method name and the `super()._from_file_info` call inside it are renamed in `_RecordingLifecycleAdapter`.
