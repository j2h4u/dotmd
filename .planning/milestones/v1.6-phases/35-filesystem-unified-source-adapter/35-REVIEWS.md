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

The two plans are narrowly scoped and mostly sound. Plan 01 directly removes the private adapter method from the production lifecycle path, matching FS-03 and D-03. Plan 02 adds useful behavioral coverage for the new public boundary and the D-04 conversion invariant. The main gap is that these plans prove the `FileInfo -> SourceDocument` bridge, but they do not fully prove the whole Phase 35 goal by themselves: filesystem indexing/read/delete/parser routing/content reuse still rely on existing regression tests staying green.

### Strengths

- Plan 01 is appropriately small: rename adapter method, update the pipeline call, update the lifecycle test double.
- It preserves the decision not to add `document_for_file_info` to `SourceAdapterProtocol`, avoiding a leaky generic interface.
- The existing production instantiation rule is already structurally good: `FilesystemMarkdownSourceAdapter()` appears in production only in `source_lifecycle.py`.
- Plan 02 tests the important lifecycle construction path: `SourceRuntimeFactory.build("filesystem") -> bundle.source.document_for_file_info(...)`.
- The D-04 round-trip test is valuable because `source_document_to_file_info` enforces the filesystem document ref invariant.

### Concerns

- **MEDIUM:** Plan 02 is labeled TDD, but it depends on Plan 01. If Plan 01 is already applied, the expected RED failure will not happen. This is not a functional problem, but the plan wording is internally inconsistent.
- **MEDIUM:** These plans do not independently prove all of FS-01. They cover the bridge method and lifecycle access, but not delete detection, parser routing, local read behavior, trickle watcher behavior, or content-addressed reuse except through existing regression suites.
- **LOW:** Exact grep line-count acceptances are brittle. They are fine as sanity checks, but behavioral tests should be the actual gate.
- **LOW:** The new round-trip test should assert `last_modified` and `size_bytes` as well as path/title/kind/frontmatter. Otherwise it does not fully prove `FileInfo` compatibility.
- **LOW:** In the lifecycle factory test, the plan should explicitly assert `bundle.source is not None` before calling the method. That makes the failure clearer.

### Suggestions

- Keep Plan 01 as-is, but make the final verification use `rg "_from_file_info" backend/` as the real no-private-reference gate.
- Reword Plan 02 from "TDD RED/GREEN" to "behavioral regression tests after public rename," unless the runner will intentionally execute it before Plan 01.
- Add to the round-trip test: `recovered.last_modified == file_info.last_modified` and `recovered.size_bytes == md_path.stat().st_size`.
- Add a production-only instantiation check: `rg "FilesystemMarkdownSourceAdapter\\(" backend/src` — expected: only `source_lifecycle.py`.
- Treat `pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_source_lifecycle.py` as the focused required gate, and `pytest tests/ingestion/ -q` / `pytest -q` as broader confidence gates.

### Risk Assessment

**Overall risk: LOW.**

The implementation change is a public rename with a single production call site in `pipeline.py` and a small number of adapter self-calls. The biggest risk is overclaiming Phase 35 completion from these two plans alone — they cover D-03/D-04 and part of FS-03, but final phase acceptance should still lean on existing pipeline regression tests for FS-01 behavior across indexing, reads, parser routing, delete handling, and reuse.

---

## OpenCode Review

### Plan 01 Review: Rename `_from_file_info` → `document_for_file_info`

**Summary:** A clean, well-scoped mechanical rename. All 4 call sites (2 internal in `discover`/`discover_multi`, 1 in pipeline's `_source_document_for_file_info`, 1 test double override) are correctly identified. The plan correctly scopes `SourceAdapterProtocol` to remain at `discover` + `discover_multi` only, respecting D-03's ISP/LSP rationale.

**Strengths:**

- Exhaustive call-site enumeration: every reference accounted for (source.py definition + 2 internal callers; pipeline.py:1371; test_source_filesystem.py recorder override + super() call).
- Grep-based verification gates are precise: "exactly 3 lines" / "exactly 1 line" — grep won't silently pass if something is missed.
- Respects protocol boundary: correctly leaves `SourceAdapterProtocol` untouched per D-03.

**Concerns:**

- **MEDIUM:** The `_RecordingLifecycleAdapter` overrides `discover` and `discover_multi` to return `[]`, bypassing the internal `self._from_file_info` calls. After rename, the recorder never exercises the `discover` → `document_for_file_info` internal path — only the `super()` dispatch is exercised. This is sufficient for `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` (which calls `_source_document_for_file_info` explicitly), but worth noting as a coverage gap.
- **LOW:** The `super()._from_file_info(file_info)` call in the recorder relies on the superclass rename happening atomically in the same plan. Incomplete rename caught by verification gates.

**Suggestions:**

- Consider tightening the grep acceptance from plain string match to `rg "def document_for_file_info|self\.document_for_file_info"` pattern to avoid false matches from docstrings/comments.

**Risk Assessment: LOW** — Mechanical rename, exhaustive call-site accounting, strong verification gates.

---

### Plan 02 Review: Public `document_for_file_info` Boundary Tests (TDD)

**Summary:** Three well-designed behavioral tests: direct invocation, lifecycle-factory round-trip, and D-04 idempotency invariant. The TDD structure (RED → GREEN) is explicit and expected failure modes are documented. Test 3 is especially valuable — it encodes the invariant that `document_for_file_info` / `source_document_to_file_info` form an isomorphic pair.

**Strengths:**

- **Test 3 (round-trip)** directly encodes D-04's validation invariant as executable proof — `FileInfo → document → FileInfo` idempotency ensures no field drift through the adapter bridge.
- **Test 2** verifies the full lifecycle construction path (`SourceRuntimeFactory.build("filesystem") → bundle.source.document_for_file_info()`), which is the actual runtime path used in production.
- **Test 1** is the simplest happy-path test — document that the method exists, is callable, and produces the right shape.
- "Common issues" section is practical and grounded in real footguns (`chunk_checksum` requires file on disk, `FilesystemSourceConfig.paths` is `list[str]`).
- Correctly identifies `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` as FS-01 regression proofs.

**Concerns:**

- **MEDIUM:** Test 2 constructs `SourceRuntimeFactory` from scratch rather than using `source_runtime_factory_from_settings`. Valid for direct construction testing, but doesn't exercise the settings→config_record bridge that the pipeline's `__init__` actually uses. If someone breaks that integration path, Test 2 won't catch it.
- **MEDIUM:** Test 2 needs `SQLiteSourceCursorStore` but doesn't use cursor functionality — it just satisfies the factory constructor. Consider a minimal/noop cursor store to reduce test setup surface area.
- **LOW:** Plan 02 should specify using `file_info_from_path` (from `dotmd.ingestion.reader`) rather than manual `FileInfo` construction, to match how production code builds documents.
- **LOW:** Test 1 asserts on 10+ fields of `SourceDocument`. A new required field later could break this test for an unrelated reason. Consider asserting structurally critical fields only (namespace, document_ref, ref, title, file_path, content_fingerprint).
- **LOW:** No test verifies behavior when `document_for_file_info` is called with a missing file (the `chunk_checksum` → `FileNotFoundError` path). Not blocking but error message quality matters for debugging.

**Suggestions:**

1. For Test 2, consider constructing `FileInfo` via `file_info_from_path` to avoid reconstructing frontmatter/stat logic manually.
2. Add a quick sanity assertion in Test 1: `assert not hasattr(adapter, '_from_file_info')` — implicit in the grep gates but useful as explicit defense-in-depth.
3. Consider whether `test_document_for_file_info_and_source_document_to_file_info_round_trip` should also verify that `source_document_to_file_info`'s namespace guard raises `ValueError` for non-filesystem documents (out of scope for this test, but the guard exists).

**Risk Assessment: LOW** — Purely additive tests. Tightly scoped. Zero production code changes. Strong verification gates.

### OpenCode Cross-Plan Summary

| Requirement | Plan 01 | Plan 02 | Evidence |
|-------------|---------|---------|----------|
| FS-01 (works through contract) | Indirect | Primary | Plan 02's 3 tests + existing regression suite |
| FS-02 (paths only where needed) | N/A | N/A | No new path usage introduced |
| FS-03 (no bypass) | Core | Secondary | Private→public rename; Test 2 proves lifecycle path |

The plans don't address every dimension of FS-01 (trickle, delete detection, parser routing, content-addressed reuse covered by existing regression tests per D-06), which is the correct pragmatic decision per CONTEXT.md.

---

## Consensus Summary

Two reviewers (Codex, OpenCode) independently reviewed Plans 01 and 02 for Phase 35 in Cycle 3 on 2026-05-10. Both reviewers inspected actual codebase files before reviewing.

### Agreed Strengths

- Plan 01 is a minimal, correctly-scoped rename that closes the FS-03 bypass without touching `SourceAdapterProtocol` or moving orchestration out of the pipeline (D-01, D-03).
- The call-site audit in Plan 01 is complete: definition, two internal callers, pipeline call site, and test double — all accounted for. The recorder's `super()` dispatch is also explicitly handled.
- Plan 02 tests map directly to D-07's specified goals (direct adapter access + lifecycle factory path + D-04 round-trip).
- Verification gates are concrete and measurable (grep + pytest exits). The `rg "_from_file_info" backend/` final gate is strong.
- The approach correctly avoids grep-based guard tests (D-08) in favor of behavioral tests.
- `source_document_to_file_info` retention in `source.py` is sound — it carries the document_ref ↔ file_path validation invariant.
- Both reviewers agree overall risk is LOW for both plans.

### Agreed Concerns

- **MEDIUM (both):** Plans 01+02 do not independently prove all of FS-01. Delete detection, parser routing, trickle watcher, and content-addressed reuse are covered by existing regression suites (per D-06) — both reviewers accept this as the correct scoping, but executors should explicitly run `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` as the primary FS-01 gates at the end.
- **MEDIUM (both):** Plan 02 TDD RED/GREEN framing is internally inconsistent — if Plan 01 is applied first, RED will not occur as described. Codex recommends rewording to "behavioral regression tests after public rename"; OpenCode notes this is not a functional problem but the wording misleads.
- **MEDIUM (OpenCode):** Plan 02 Test 2 doesn't exercise `source_runtime_factory_from_settings` integration path — the production factory wiring through settings is not covered by these new tests.

### Divergent Views

- **round-trip field coverage:** Codex recommends adding `last_modified` and `size_bytes` assertions to Test 3 for full `FileInfo` field proof; OpenCode focuses on the idempotency invariant and doesn't raise this. Codex's suggestion is a worthwhile improvement.
- **Test 1 assertion scope:** OpenCode suggests asserting fewer fields (structurally critical subset only) to reduce fragility; Codex does not flag this. The current plan's 10+ field assertions are acceptable given the test is isolated and the fields are stable.
- **`_RecordingLifecycleAdapter` coverage gap:** OpenCode flags that the recorder never exercises the `discover` → `document_for_file_info` internal path (overrides return `[]`). Codex does not raise this. Not blocking — the production call path through `_source_document_for_file_info` is separately tested.

### Top Priority Action Items for Executor

1. **Run FS-01 named regression proofs explicitly** at final verification: `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` and `test_source_lifecycle.py` are the primary FS-01 gates — not just "full suite green."
2. **Round-trip test field completeness**: consider adding `recovered.last_modified` and `recovered.size_bytes` assertions to Test 3 per Codex suggestion.
3. **Plan 02 TDD framing**: executor should run Plan 01 to completion before starting Plan 02; the RED phase in 35-02-01 is only meaningful if Plan 01 has not yet been applied.
4. **Production instantiation check**: after all tasks complete, verify `rg "FilesystemMarkdownSourceAdapter(" backend/src` returns only `source_lifecycle.py` — a useful final structural check neither plan currently mandates.
5. **`bundle.source is not None` assertion**: explicitly assert before calling `bundle.source.document_for_file_info(file_info)` in Test 2.
