---
phase: 25
reviewers: [opencode]
reviewed_at: 2026-05-05T23:54:45+05:00
convergence_cycle: 3
plans_reviewed:
  - 25-01-domain-models-and-filesystem-adapter-PLAN.md
  - 25-02-ingestion-routing-and-chunk-provenance-PLAN.md
  - 25-03-provenance-persistence-and-read-search-compatibility-PLAN.md
  - 25-04-regression-docs-and-phase-verification-PLAN.md
---

# Cross-AI Plan Review — Phase 25

## OpenCode Review

CYCLE_SUMMARY: current_high=0

## Current HIGH Concerns
None.

## Plan 25-01: Source Models and Filesystem Markdown Adapter

### Summary
A well-scoped foundational plan that introduces three Pydantic models with `ConfigDict(extra="forbid")` and a Protocol-style filesystem adapter wrapping current reader logic. The filesystem identity invariant (`document_ref == str(Path.resolve())`) is enforced at model construction time with validation error on mismatch. Scope is tightly bounded with explicit negative acceptance criteria.

### Strengths
- **Filesystem invariant enforcement at construction time** (Task 1) prevents the most dangerous silent divergence bug: `namespace=="filesystem"` with mismatched `file_path`/`document_ref` raises `ValueError`.
- **`ConfigDict(extra="forbid")`** on new models is forward-looking — prevents accidental field injection from future consumers.
- **Protocol-style adapter** with in-process constraint matches established dotMD patterns.
- **Fingerprint preservation tests** (body-only vs metadata-only) directly address TH-25-04.
- **Explicit negative criteria** ("does not contain `telegram`", "does not contain `SourceAsset`") are strong scope guards.

### Concerns
- **MEDIUM — `source_document_to_file_info()` calls `stat()` at conversion time** (Task 3). The adapter already called `stat()` during discovery; this is a redundant syscall per file. For 13,500 files it's ~1 second on SSD — non-critical but avoidable by adding `size_bytes` to `SourceDocument`.
- **LOW — `SourceUnit` is model-only scaffolding.** No adapter method emits units in Plan 01. Acceptable for Phase 25 but should be noted in code comments.

### Suggestions
- Add `size_bytes: int` to `SourceDocument` to avoid redundant `stat()` in the bridge helper.
- Add a direct unit test in Plan 01: `assert filesystem_document_ref(p) == IndexingPipeline._meta_entity_id(p)` so the invariant is validated at the boundary where it's defined, not deferred to Plan 02.

### Risk Assessment: **LOW**

---

## Plan 25-02: Ingestion Routing and Chunk Provenance

### Summary
The highest-risk plan, now substantially improved from cycle 2. The `index_file()` refactor is split across two tasks: Task 3 creates helper seams (`_source_document_for_file_info`, `_file_info_and_source_document`, `_filesystem_chunk_provenance`, `_assert_filesystem_document_ref`) and Task 4 refactors the method through those helpers. `chunk_file()` default provenance behavior is explicitly specified. `documents_by_path` ownership is clearly defined as a call-chain parameter.

### Strengths
- **Task 3/4 split resolves the cycle-2 HIGH concern** about underestimating `index_file()` complexity. Helpers are created and tested before the 244-line method is touched.
- **`chunk_file()` default behavior is now explicit**: omitted provenance → `None`, no synthesis or inference. This resolves the cycle-2 HIGH about unspecified defaults.
- **`documents_by_path` ownership rule** — local to indexing call, passed as parameter, not stored as mutable instance state — resolves the cycle-2 MEDIUM about handoff ambiguity.
- **`source_unit_refs=[]` is now explicitly the Phase 25 filesystem value**, with a rule against inventing pseudo-unit IDs.
- **Task 5 verification** compares bulk `index()` and trickle `index_file()` provenance for the same file.

### Concerns
- **MEDIUM — Task 4 preservation list is comprehensive but fragile.** The task lists 10+ specific branches/operations to preserve ("`_beacon`, timing accumulators, holder-aware purge transaction, graph cleanup fallback...") in the same order. An executor could miss one during the refactor. The acceptance criteria partially mitigate this (existing tests must pass), but a checklist-based verification in the task description would be stronger.
- **LOW — `_save_and_embed_chunks()` parameter signature change is implied but not specified.** Plan 02 Task 2 says `documents_by_path` is passed into this method, but the exact parameter addition isn't called out in acceptance criteria for Plan 02 (it's implicit in Plan 03's writes).

### Suggestions
- Add an explicit checklist item in Task 4: "After refactoring, run the existing `test_pipeline_m2m_insert`, `test_pipeline_reindex_shared_chunk`, and `test_metadata_only_reindex` tests to confirm no branch was missed."
- Document the `_save_and_embed_chunks(documents_by_path=...)` parameter addition explicitly in Task 2 or Task 4 acceptance criteria.

### Risk Assessment: **MEDIUM** (improved from HIGH in cycle 2)

---

## Plan 25-03: Provenance Persistence and Read/Search Compatibility

### Summary
Adds two SQLite tables (global `source_documents`, strategy-scoped `chunk_source_provenance_<strategy>`) and wires provenance writes into all chunk save paths. The cycle-2 HIGH about undefined `source_unit_refs` is resolved: filesystem Phase 25 semantics are explicitly `[]` with validation against non-empty values. The cycle-2 MEDIUM about `conn` parameter pattern is resolved with an explicit transaction rule.

### Strengths
- **`source_unit_refs` semantics are now defined before persistence**: explicitly `[]` for filesystem Markdown, with a fail/log guard against non-empty values. Resolves cycle-2 HIGH.
- **Global vs strategy-scoped split is correct and well-documented** in the objective section.
- **Transaction rule is explicit**: write/delete helpers require `conn`; only read helpers may default to `self._conn`. Resolves cycle-2 MEDIUM.
- **`reindex_vectors()` behavior is specified**: leave existing provenance unchanged, don't synthesize missing rows, newly indexed chunks get provenance through the save path. Resolves cycle-2 MEDIUM.
- **Delete cleanup cascade** extends holder-aware purge to provenance rows.
- **Idempotent DDL** with `CREATE TABLE IF NOT EXISTS`.

### Concerns
- **MEDIUM — Migration path for existing databases is untested.** Adding tables to a production `index.db` with existing chunks and M2M data should have at least one test proving DDL is idempotent on a populated database. The acceptance criteria don't include this.
- **LOW — `source_document_to_file_info()` stat() redundancy carries forward.** The `size_bytes` field is still read from `stat()` at conversion time rather than carried on `SourceDocument`.

### Suggestions
- Add a test: create a metadata store with existing chunks/M2M data, call `ensure_source_document_table()` and `ensure_chunk_source_provenance_table()`, verify no data loss and tables exist.
- Consider carrying `size_bytes` on `SourceDocument` to eliminate the redundant stat() in the bridge helper.

### Risk Assessment: **LOW**

---

## Plan 25-04: Regression Suite, Documentation, and Phase Verification

### Summary
Solid closing plan with cross-surface regression coverage, documentation updates, and deferred-scope audit. The deferred-scope audit checklist is a strong scope-control mechanism. Verification gate is well-defined with concrete commands.

### Strengths
- **Deferred-scope audit** (Task 4) with explicit checklist items ("Telegram read-only adapter not implemented") prevents scope creep from going unnoticed.
- **Cross-surface test run** (Task 3) covers ingestion + storage + API + MCP together.
- **Documentation requirements** (Task 2) include the canonical mapping rules, future-scope boundary, and public contract preservation.

### Concerns
- **MEDIUM — Task 1 is partially meta.** It says "Ensure the final test coverage proves the compatibility shim at every surface" and lists coverage requirements, but most tests are written in Plans 01-03. If Plans 01-03 are complete, Task 1 is verification-only. If gaps exist, the plan doesn't specify which new tests to write. The acceptance criteria help but are somewhat circular (checking that test files contain expected strings rather than asserting specific new test functions).
- **LOW — `ruff check` is not in the verification gate.** AGENTS.md specifies `ruff check .` as a pre-commit requirement, but Plan 04 only runs `pyright`.

### Suggestions
- Add `cd backend && uv run ruff check .` to the Task 3 verification command.
- Make Task 1 concrete: if no new tests are needed beyond Plans 01-03, rename to "Verify existing test coverage is sufficient" and list the specific test functions that must pass.

### Risk Assessment: **LOW**

---

## Overall Phase Assessment

**Overall Risk: LOW** (improved from MEDIUM in cycle 2)

All three previous HIGH concerns are resolved:

1. **`index_file()` complexity** → Split into helper seams (Task 3) + focused refactor (Task 4)
2. **`chunk_file()` default provenance** → Explicitly specified: omitted → `None`, no synthesis
3. **`source_unit_refs` semantics** → Defined as intentionally empty `[]` with validation guard

Both previous MEDIUM concerns are resolved:

4. **`reindex_vectors()` provenance** → Explicit: leave existing unchanged, don't synthesize legacy rows
5. **`documents_by_path` handoff** → Explicit: local parameter, not mutable instance state

Scope control remains excellent. The explicit deferral tests and negative acceptance criteria make scope creep very difficult during execution.

---

## Consensus Summary

Only the OpenCode reviewer was invoked for cycle 3, per the requested reviewer set, so this summary reflects single-reviewer findings rather than cross-reviewer consensus.

### Agreed Strengths
- The three cycle-2 HIGH concerns are now resolved by explicit plan changes.
- Scope control remains strong through negative acceptance criteria and deferred-scope checks.
- Plan sequencing is clearer: source models, ingestion routing, provenance persistence, then regression/docs verification.

### Agreed Concerns
- No HIGH concerns remain.
- MEDIUM follow-ups remain around redundant `stat()` calls, fragile `index_file()` preservation work, missing populated-DB DDL migration coverage, and Plan 25-04's somewhat meta test-coverage task.

### Divergent Views
- None. Only OpenCode was requested and invoked in this cycle.
