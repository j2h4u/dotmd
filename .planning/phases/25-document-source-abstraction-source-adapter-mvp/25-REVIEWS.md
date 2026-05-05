---
phase: 25
reviewers: [opencode]
reviewed_at: 2026-05-05T23:57:00+05:00
convergence_cycle: 2
plans_reviewed:
  - 25-01-domain-models-and-filesystem-adapter-PLAN.md
  - 25-02-ingestion-routing-and-chunk-provenance-PLAN.md
  - 25-03-provenance-persistence-and-read-search-compatibility-PLAN.md
  - 25-04-regression-docs-and-phase-verification-PLAN.md
---

# Cross-AI Plan Review — Phase 25

## OpenCode Review

# Cross-AI Plan Review: Phase 25 — Document Source Abstraction (Cycle 2)

## Plan 25-01: Source Models and Filesystem Markdown Adapter

### Summary
A well-scoped plan that introduces `SourceDocument`, `SourceUnit`, and `ChunkProvenance` Pydantic models plus a `FilesystemMarkdownSourceAdapter` wrapping current discovery logic. The filesystem identity invariant (`document_ref == str(Path.resolve())`) is clearly defined and validated. Scope is tightly bounded with explicit deferral tests.

### Strengths
- **Invariant enforcement is excellent.** The `file_path` / `document_ref` mismatch check (Task 1) and the `filesystem_document_ref()` normalizer matching `_meta_entity_id()` (Task 2) prevent the most dangerous silent divergence bug in this phase.
- **ConfigDict(extra="forbid")** on new models prevents accidental field injection — a good forward-looking choice for a model that will see many consumers.
- **Protocol-style adapter boundary** with in-process constraint matches established dotMD patterns (`VectorStoreProtocol`, `GraphStoreProtocol`).
- **Explicit negative acceptance criteria** ("does not contain `telegram`", "does not contain `SourceAsset`") are a strong scope guard.
- **Fingerprint preservation tests** (body-only vs metadata-only change) directly address TH-25-04 from the research threat model.

### Concerns

- **MEDIUM — `source_document_to_file_info()` calls `stat()` at conversion time.** Task 3 requires `size_bytes=document.file_path.stat().st_size`, but the adapter already called `stat()` during discovery (reader.py line 142). This is a redundant I/O syscall per file. For 13,500 files that's non-trivial during full reindex. Consider storing `size_bytes` on `SourceDocument` or passing it through from the original discovery.
- **MEDIUM — `SourceUnit` is defined but never emitted or used in Plan 01.** The model is added to `models.py` but no adapter method produces `SourceUnit` instances. This is acceptable scaffolding but the acceptance criteria should note it's a type-only addition (no runtime behavior) to avoid confusion during execution.
- **LOW — `_meta_entity_id()` alignment is asserted in Plan 02, not Plan 01.** Plan 01 Task 2 says `filesystem_document_ref()` "must match `_meta_entity_id(path)`" but the assertion/test is in Plan 02 Task 2. Consider adding a unit test in Plan 01 that compares both functions directly, so the invariant is validated at the boundary where it's defined.

### Suggestions
- Add `size_bytes: int` to `SourceDocument` to avoid the redundant `stat()` call in the bridge helper.
- Add a direct unit test: `assert filesystem_document_ref(p) == IndexingPipeline._meta_entity_id(p)` in Plan 01 test suite.
- Clarify in the plan that `SourceUnit` is model-only in Plan 01 — the first emission belongs to Plan 02 chunking.

### Risk Assessment: **LOW**
The plan introduces new types and an adapter that wraps existing code without modifying the pipeline. The `discover_files()` functions are preserved as-is. Regression risk is minimal because nothing in the existing code path changes yet.

---

## Plan 25-02: Ingestion Routing and Chunk Provenance

### Summary
The highest-risk plan. Routes filesystem Markdown indexing through the adapter-backed path while preserving `FileTracker.diff()` on `FileInfo` objects. The dual-object approach (`SourceDocument` → provenance, `FileInfo` → tracker diffing) is architecturally sound but creates a synchronization surface that needs careful testing.

### Strengths
- **The `documents_by_path` bridge pattern is correct.** Converting `SourceDocument` → `FileInfo` for tracker diffing while maintaining a parallel mapping for provenance avoids changing `FileTracker` internals.
- **`_meta_entity_id()` alignment assertion** (Task 2) is the most critical invariant check in the entire phase. Placing it at the diff/save boundary catches mismatches early.
- **The explicit rule "tracker calls never receive `SourceDocument`"** prevents a common error where adapter types leak into storage internals.
- **Test that `index_file(Path(...))` produces identical provenance as bulk `index()`** (Task 4) catches the most likely real-world divergence.

### Concerns

- **HIGH — `index_file()` refactoring complexity is underestimated.** The current `index_file()` (pipeline.py:1446-1690) is a 244-line method with multiple phases, error handling branches, beacon writes, and two-phase embed logic. Plan 02 Task 3 proposes significant structural changes to it (constructing `SourceDocument` from `Path` or `FileInfo`, asserting `_meta_entity_id` alignment, passing provenance through to chunking/save). The plan treats this as one task but it touches the most complex method in the codebase. A missed edge case here could break trickle indexing silently.
- **HIGH — `chunk_file()` signature change may break existing callers.** Task 1 proposes adding provenance parameters to `chunk_file()`. The current signature is clean (`file_path, content, max_tokens, overlap_tokens, kind, chunk_strategy`). Adding optional provenance params is backward-compatible at the type level, but `chunk_file()` is called from multiple sites (`_chunk_files()`, `index_file()`, and tests). The plan says "caller-owned provenance is preferred" but doesn't specify what happens when `chunk_file()` is called without provenance from a test or non-adapter path.
- **MEDIUM — `_save_and_embed_chunks()` provenance injection point is ambiguous.** The plan says "Persist source document row per discovered Markdown file into global `source_documents`" but `_save_and_embed_chunks()` operates on `list[Chunk]` grouped by file, not on `SourceDocument` objects. The mapping between chunks and source documents must go through `file_paths[0]` → `documents_by_path`, which is fragile if `file_paths` ordering changes or a chunk is shared across documents.
- **MEDIUM — `reindex_vectors()` is mentioned as "must not create duplicate source document rows" but Plan 02 doesn't modify `reindex_vectors()`.** The `reindex_vectors()` path (pipeline.py:899-975) discovers files from M2M table and re-embeds them. If it runs after Plan 02 without provenance writes, it creates chunks without source provenance. This gap should be acknowledged explicitly or addressed in Plan 03.

### Suggestions
- **Split Task 3 into two tasks**: one for the bulk `index()` path and one for `index_file()`. The trickle path is complex enough to warrant its own focused task with dedicated tests.
- **Specify the default provenance behavior for `chunk_file()` without adapter context.** When called directly from tests or `reindex_vectors()`, should it default to `namespace="filesystem"` with no `document_ref`? Or should it require provenance? This should be an explicit design decision.
- **Add a test that `reindex_vectors()` does not crash or produce inconsistent state after Plan 02 changes.** Even if provenance writes are deferred to Plan 03, the read path must handle chunks with and without provenance gracefully.
- **Document the `file_paths[0]` → `documents_by_path` lookup contract explicitly** in the plan. If this mapping ever fails (shared chunk from two different source documents), the plan should specify the fallback behavior.

### Risk Assessment: **MEDIUM**
This plan touches the most critical and complex code path (`index_file()` and `_save_and_embed_chunks()`). The dual-object synchronization pattern is sound but creates a new invariant surface. The 244-line `index_file()` method is the primary risk — the plan should either split the work or add more granular intermediate verification.

---

## Plan 25-03: Provenance Persistence and Read/Search Compatibility

### Summary
Adds two new SQLite tables (`source_documents` global, `chunk_source_provenance_<strategy>` per-strategy) and wires provenance writes into all chunk save paths. The table scoping decision (global vs strategy-scoped) is well-justified and correctly documented.

### Strengths
- **The global vs strategy-scoped split is correct.** Source documents are independent of chunking strategy — a Markdown file is the same document regardless of how it's chunked. Only chunk-level provenance varies by strategy.
- **Delete cleanup cascade (Task 4)** correctly extends the existing holder-aware purge pattern to clean provenance rows alongside M2M rows.
- **`CREATE TABLE IF NOT EXISTS` and additive-only schema** is the right migration strategy for an existing production database.
- **The `delete_source_document_for_file()` helper** deriving `document_ref` from `file_path` maintains the filesystem identity contract at the storage layer.

### Concerns

- **HIGH — `source_unit_refs` stored as JSON text has no query surface.** The plan stores `source_unit_refs` as a JSON TEXT column in `chunk_source_provenance_<strategy>`. This is fine for persistence, but Phase 25 never defines what `source_unit_refs` actually contains for filesystem Markdown. Plan 01 defines `SourceUnit` but no adapter method emits units. Plan 02 says "at least one deterministic source unit ref" in tests but never specifies the format. If `source_unit_refs` is always `[]` for Phase 25, this is dead storage. If it contains something, the format must be defined before persistence is implemented.
- **MEDIUM — Provenance write in `reindex_vectors()` is not covered.** Task 2 says "reindex_vectors() must not create duplicate source document rows and must not drop existing provenance" but doesn't specify whether `reindex_vectors()` should *create* provenance rows for chunks that lack them (e.g., chunks created before Phase 25). This is a migration concern.
- **MEDIUM — `conn=None` parameter pattern in helper methods may cause transaction issues.** The plan proposes helpers like `upsert_source_document(document, conn=None)`. But the existing `SQLiteMetadataStore` pattern (e.g., `delete_m2m_for_file`) requires explicit `conn` with caller-managed transactions. Optional `conn` with a fallback to `self._conn` can silently break transaction boundaries. The helpers should either always require `conn` or document when autocommit is acceptable.
- **LOW — No VACUUM or migration test for existing databases.** Adding two tables to an existing ~50-min-full-reindex production database should include a test that proves the DDL is idempotent on a populated database.

### Suggestions
- **Define what `source_unit_refs` contains for filesystem Markdown before persisting it.** If the answer is "always empty list for Phase 25," say so explicitly and add a test asserting it. If it should contain something meaningful (e.g., `["filesystem:<path>:chunk:<index>"]`), define the format.
- **Unify the `conn` parameter pattern** with existing store helpers. Prefer mandatory `conn` for methods called inside transactions and document autocommit behavior for standalone calls.
- **Add a test for the migration path**: open an existing `index.db` with chunks and M2M data, create provenance tables, verify no data loss.

### Risk Assessment: **MEDIUM**
The storage changes are additive and safe in isolation. The primary risk is the undefined `source_unit_refs` content — implementing persistence before defining what's being persisted could lead to a format that's wrong for future Telegram work and requires a migration to fix.

---

## Plan 25-04: Regression Suite, Documentation, and Phase Verification

### Summary
A solid closing plan that adds cross-surface regression tests, updates documentation, and writes the final phase summary. The deferred-scope audit is a strong pattern that prevents scope creep from going unnoticed.

### Strengths
- **The deferred-scope audit (Task 4)** with explicit checklists ("Telegram read-only adapter not implemented") is an excellent scope-control mechanism.
- **Running all test suites together** (ingestion + storage + API + MCP) provides the integration coverage that individual plan tests cannot.
- **The documentation task (Task 2)** correctly captures the canonical mapping rules and future-scope boundary.

### Concerns

- **MEDIUM — Task 1 is a meta-task without new test code.** It says "Ensure the final test coverage proves the compatibility shim at every surface" but lists test files from Plans 01-03. If Plans 01-03 already wrote all the tests, Task 1 is verification-only. If additional tests are needed, the plan should specify which ones. As written, an executor could interpret this as "run existing tests and confirm they pass" without adding anything new.
- **LOW — `pyright` verification but no `ruff` or `mypy`.** The AGENTS.md specifies `ruff check .` and `mypy` as pre-commit gates. Plan 04 only mentions `pyright`. Either add `ruff` and `mypy` to the verification command, or document why `pyright` alone is sufficient for Phase 25.

### Suggestions
- **Make Task 1 concrete**: list specific new test cases (if any) beyond what Plans 01-03 already added. If no new tests are needed, rename the task to "Verify existing test coverage is sufficient."
- **Add `ruff check` to the verification gate** to match AGENTS.md pre-commit requirements.
- **Consider a grep-based scope audit test** (e.g., `rg -l "telegram|SourceAsset|TTL" backend/src/dotmd/ingestion/source.py backend/src/dotmd/core/models.py`) as an automated check that can run in CI.

### Risk Assessment: **LOW**
This plan is primarily verification and documentation. The main risk is under-coverage if Plans 01-03 tests have gaps, but the cross-surface test run should surface most issues.

---

## Overall Phase Assessment

**Overall Risk: MEDIUM**

The phase is well-structured with clear dependencies (Wave 1→2→3→4), tight scope boundaries, and strong negative acceptance criteria. The primary risks are:

1. **Plan 02 complexity** — `index_file()` refactoring in a single task is the highest-risk single unit of work in the phase.
2. **`source_unit_refs` is undefined** — the three new models are defined but only `SourceDocument` has clear Phase 25 semantics. `SourceUnit` and `ChunkProvenance.source_unit_refs` are scaffolding for future work, and persisting `source_unit_refs` before defining its format is premature.
3. **`reindex_vectors()` gap** — Plans 02 and 03 both mention it but neither fully addresses provenance behavior for the rebuild path. This could leave chunks with partial provenance.

**Cross-plan dependency concern:** Plan 03 Task 2 requires writing provenance during `_save_and_embed_chunks()`, but the `documents_by_path` mapping is created in Plan 02 Task 2. If Plan 02 stores this mapping as a local variable inside `index()`, Plan 03 cannot access it in `_save_and_embed_chunks()`. The plans should agree on where this mapping lives (e.g., a pipeline attribute or a parameter passed through the call chain).

**Scope control is excellent.** The explicit deferral tests and negative acceptance criteria are the strongest aspect of this plan suite. They make it very difficult for scope creep to enter during execution.

---

## Consensus Summary

Only OpenCode was invoked in this convergence cycle, per the requested reviewer set. This summary therefore synthesizes repeated or cross-plan themes from that single review rather than cross-reviewer agreement.

### Agreed Strengths

- Phase 25 remains well-structured with clear sequencing from source models to ingestion routing, provenance persistence, and verification.
- The replanned filesystem identity invariant, especially `document_ref == str(Path.resolve())`, directly addresses prior path-normalization risks.
- Scope control is strong: Telegram, `SourceAsset`, entity catalog work, TTL, and validation-source expansion remain explicitly deferred.
- The persistence design is additive and keeps existing `file_paths`/MCP read/search behavior as the compatibility surface.

### Agreed Concerns

- HIGH: Plan 25-02 still underestimates the complexity of refactoring the 244-line `index_file()` trickle path.
- HIGH: Plan 25-02 does not fully specify default provenance behavior for `chunk_file()` callers that do not have adapter context.
- HIGH: Plan 25-03 persists `source_unit_refs` before defining concrete filesystem semantics or deciding whether it is intentionally empty in Phase 25.
- MEDIUM: Provenance behavior for `reindex_vectors()` remains incomplete across Plans 25-02 and 25-03.
- MEDIUM: The handoff of `documents_by_path` from Plan 25-02 to Plan 25-03 needs a concrete call-chain or ownership decision.

### Divergent Views

- No divergent reviewer views: this cycle intentionally used OpenCode only.
