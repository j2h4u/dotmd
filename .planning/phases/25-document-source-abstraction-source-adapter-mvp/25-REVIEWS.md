---
phase: 25
reviewers: [opencode]
reviewed_at: 2026-05-05T23:29:09+05:00
plans_reviewed:
  - 25-01-domain-models-and-filesystem-adapter-PLAN.md
  - 25-02-ingestion-routing-and-chunk-provenance-PLAN.md
  - 25-03-provenance-persistence-and-read-search-compatibility-PLAN.md
  - 25-04-regression-docs-and-phase-verification-PLAN.md
---

# Cross-AI Plan Review — Phase 25

## OpenCode Review

# Cross-AI Plan Review: Phase 25 — Document Source Abstraction

## Plan 25-01: Source Models and Filesystem Markdown Adapter

### Summary

A clean, focused plan that defines new domain models and wraps existing reader behavior behind a Protocol-style adapter. The scope is appropriately narrow — models only, no pipeline changes — and the test strategy is solid. The main gaps are around the SourceDocument/FileInfo relationship semantics and the undefined adapter protocol method signature.

### Strengths

- **Tight scope boundary.** No pipeline changes, no search changes, just models + adapter + tests. This is the right MVP shape.
- **Explicit deferral tests.** Task 4 explicitly checks that no Telegram/SourceAsset/entity code enters the codebase — good scope enforcement.
- **Fingerprint preservation.** The plan explicitly preserves the split content/metadata fingerprint semantics and asserts they match existing `chunk_checksum`/`meta_checksum` formulas.
- **`ConfigDict(extra="forbid")` on new models.** Consistent with `Chunk`'s existing pattern and prevents accidental field drift.

### Concerns

1. **`SourceDocument.file_path: Path | None` and `document_ref` coexistence is underspecified.** (HIGH) — The plan says `file_path` is "compatibility" but doesn't define the invariant: is `document_ref` always derivable from `file_path`? What happens if they disagree? For filesystem, `document_ref` should be a deterministic function of `file_path`, and a test should assert this.

2. **`content_fingerprint` semantics don't match `chunk_checksum` signature.** (MEDIUM) — `chunk_checksum(path: Path)` reads the file from disk, parses frontmatter, and hashes `kind + "\n" + body`. The adapter plan says "content_fingerprint equal to the current chunk_checksum(path)" but `SourceDocument` is already parsed — it doesn't re-read from disk. The plan needs to clarify whether the adapter calls `chunk_checksum(file_path)` directly (disk read) or computes the equivalent from already-parsed data. If the latter, the fingerprint formula must be documented as identical to `chunk_checksum`'s.

3. **`SourceAdapterProtocol` method signature is undefined.** (MEDIUM) — Task 2 says "a method that can discover or export SourceDocument objects" but doesn't specify: is it `discover(directory: Path) -> list[SourceDocument]`? `discover(paths: list[str], exclude: list[str]) -> list[SourceDocument]`? This matters because `discover_files_multi` supports multi-path + excludes, and the protocol must cover that or explicitly not cover it in this plan.

4. **`metadata_json` vs `FileInfo.frontmatter` redundancy.** (LOW) — `SourceDocument.metadata_json: dict` and `FileInfo.frontmatter: dict` serve the same purpose. The plan should clarify that `metadata_json` is the frontmatter dict and that the FileInfo conversion path preserves it directly.

5. **`SourceUnit` is defined but never populated in this plan.** (LOW) — The model is added in Task 1 but no filesystem adapter code emits SourceUnits in Tasks 2-3. This is fine for the model definition, but the plan should explicitly state that SourceUnit population is deferred to Plan 25-02 where chunking happens.

### Suggestions

- Add a test asserting `document_ref` is a deterministic function of the filesystem path (e.g., `str(Path(path).resolve())`).
- Define the `SourceAdapterProtocol` method signature explicitly in Task 2 — suggest `discover(directory: Path) -> list[SourceDocument]` and `discover_multi(paths: list[str], exclude: list[str]) -> list[SourceDocument]`.
- Document the fingerprint computation strategy: adapter calls existing `chunk_checksum(file_path)` / `meta_checksum(file_path)` from reader.py (preserving disk-read semantics), or computes equivalent from parsed content with an explicit formula assertion test.
- Consider adding `source_uri: str` normalization to always use `str(Path(path).resolve())` for consistency with `_meta_entity_id()`.

### Risk Assessment: **LOW**

This plan adds models and an adapter layer without touching the pipeline. The worst case is that the models need adjustment in Plan 02 when they meet the pipeline, but the cost of model changes is low since nothing depends on them yet.

---

## Plan 25-02: Ingestion Routing and Chunk Provenance

### Summary

This is the highest-risk plan in the phase. It routes the existing pipeline through the new adapter, attaches provenance to chunks, and must preserve fingerprint behavior, chunk text, file_paths, and metadata-only fast paths. The plan correctly identifies the critical compatibility risks but leaves too many integration details to implementer discretion, particularly around the FileTracker/SourceDocument impedance mismatch.

### Strengths

- **Correct threat identification.** All four threats are real and correctly prioritized: chunk text drift, metadata-only regression, file_path loss, and provenance vagueness.
- **Chunk text comparison test.** Task 4 explicitly asserts chunk text remains identical before and after provenance-aware chunking — this is the single most important compatibility test.
- **Metadata-only path preservation.** Task 3 explicitly requires the `test_metadata_only_reindex_exactly_one_tei_call` test to keep passing, which is the right regression gate.

### Concerns

1. **`FileTracker.diff()` works with `list[FileInfo]`, not `list[SourceDocument]`.** (HIGH) — The pipeline's `index()` method currently calls `discover_files(directory)` → `list[FileInfo]` → `self._chunk_tracker.diff(files)`. The plan says to route discovery through the adapter, which returns `list[SourceDocument]`. But `FileTracker.diff()` expects `FileInfo` objects (it accesses `fi.path`, `fi.last_modified`, `fi.size_bytes`). The plan says "maps adapter documents to the existing FileInfo/chunking flow" but doesn't specify: does the adapter also return FileInfo? Does the pipeline convert SourceDocument → FileInfo? This is the central integration decision and it's left to implementer discretion.

2. **`index_file()` (trickle path) is not addressed.** (HIGH) — The trickle indexer calls `pipeline.index_file(file_info)` which accepts `FileInfo | Path`, constructs its own `FileInfo`, and runs the two-phase pipeline independently. Plan 02 Task 2 only mentions `pipeline.index(directory)` and `_chunk_files()`. The trickle path must also go through the adapter, or the two paths will produce inconsistent provenance. The plan doesn't address this.

3. **`discover_files_multi()` is not addressed.** (MEDIUM) — Production uses `discover_files_multi(paths, exclude)` via `DotMDService`. The plan routes bulk discovery through the adapter but only describes the single-directory case. If `FilesystemMarkdownSourceAdapter` only wraps `discover_files()`, the multi-path code path will bypass the adapter, creating two discovery paths.

4. **`chunk_file()` provenance signature is vague.** (MEDIUM) — Task 1 says "Update chunk_file() to accept optional provenance inputs" with parameters like `namespace: str = "filesystem"`, `document_ref: str | None = None`, `source_unit_refs`. But `chunk_file()` is also called from many test fixtures with just `(path, content)`. Adding optional parameters is fine, but the plan doesn't specify whether provenance is populated inside `chunk_file()` or by the caller after chunking.

5. **`_meta_entity_id()` normalization must align with `document_ref`.** (MEDIUM) — `_meta_entity_id()` returns `str(Path(path).resolve())` and is used as the key for VecComponentStore. If `document_ref` uses a different normalization, the metadata-only fast path will break because e_meta lookups will miss. The plan doesn't address this alignment.

6. **`_save_and_embed_chunks` groups chunks by `str(fi.path)` lookup into `fi_by_path` dict.** (LOW) — If the adapter changes the path representation (e.g., to `document_ref`), this grouping logic needs updating. The plan doesn't flag this.

### Suggestions

- **Specify the FileTracker impedance solution explicitly.** Either: (a) the adapter returns `SourceDocument` + a method to extract compatible `FileInfo`, or (b) the pipeline maintains a parallel `list[FileInfo]` alongside `list[SourceDocument]`. Option (a) is cleaner.
- **Add a task or acceptance criterion covering the `index_file()` trickle path.** At minimum, assert that trickle-indexed files have the same provenance as bulk-indexed files.
- **Address `discover_files_multi`.** Either the adapter wraps both discovery functions, or the plan explicitly documents that multi-path discovery is a Plan 03 follow-up with a temporary bypass.
- **Specify `document_ref` normalization as `str(Path(path).resolve())` explicitly** to align with `_meta_entity_id()`.

### Risk Assessment: **HIGH**

This plan modifies the core indexing pipeline — the most complex and test-sensitive component in the codebase. The FileTracker/SourceDocument impedance mismatch, the unaddressed trickle path, and the `_meta_entity_id` normalization alignment are all HIGH-severity integration gaps that could cause silent regressions in incremental indexing or embedding reuse.

---

## Plan 25-03: Provenance Persistence and Read/Search Compatibility

### Summary

Adds SQLite provenance tables and integrates provenance writes into the pipeline's save path, then extends delete cleanup to the new tables. The plan correctly keeps provenance additive and preserves `file_paths`/MCP read as the compatibility path. The main gap is the strategy-scoping ambiguity for source_documents.

### Strengths

- **Additive schema only.** `CREATE TABLE IF NOT EXISTS` with no column drops or renames. Safe for existing index databases.
- **Delete cleanup is a first-class task, not an afterthought.** Task 4 addresses provenance row deletion within the existing `_holder_aware_chunk_cleanup` transaction boundary.
- **`file_paths` remains authoritative for search/read.** The plan explicitly does not replace `chunk_file_paths_<strategy>` with provenance-based hydration for MCP/search, which prevents a compatibility break.
- **Search compatibility tests.** Task 3 asserts `SearchResult.file_paths`, MCP `SearchHit.file_paths`, and MCP `read(file_path)` remain valid.

### Concerns

1. **`source_documents` table scoping is ambiguous.** (HIGH) — The plan says "source_documents_<strategy> or a non-strategy table" — this decision is deferred to implementation. But it's not a trivial choice: if strategy-scoped, every strategy gets a separate copy of the same source document metadata (wasteful); if global, the helper methods need a different API (no `strategy` parameter). The research doc raises this ambiguity and the plan doesn't resolve it. This should be a plan-time decision.

2. **Provenance write location in pipeline is unspecified.** (MEDIUM) — Task 2 says "When saving adapter-routed chunks, persist source documents and chunk provenance alongside existing chunks." But it doesn't specify: is it in `_save_and_embed_chunks`? In `save_chunks`? In a new method? The pipeline has multiple chunk-save paths (bulk `_save_and_embed_chunks`, trickle `index_file`'s per-chunk loop, `reindex_vectors`). Each needs provenance writes, and the plan only addresses the bulk path.

3. **`source_unit_refs` stored as JSON text — no query capability.** (LOW) — Storing `source_unit_refs` as a JSON text column means you can't efficiently query "which chunks came from source unit X." This is fine for Phase 25 (query not needed) but should be documented as a known limitation for the future Telegram phase.

4. **`delete_source_document_for_file(strategy, file_path, conn=...)` has confusing parameters.** (LOW) — If source_documents is strategy-independent, `strategy` is a misleading parameter. If strategy-scoped, `file_path` should maybe be `document_ref`. The helper API should match the chosen table scoping.

### Suggestions

- **Resolve the strategy-scoping decision now.** I recommend a non-strategy-scoped `source_documents` table (source metadata is strategy-independent by nature — a Markdown file's namespace/ref/media_type doesn't change per chunk strategy). Use `document_ref` as the primary key.
- **Specify all write paths that need provenance.** List: `_save_and_embed_chunks`, `index_file`'s per-chunk transaction, and `reindex_vectors`. At minimum, add acceptance criteria covering trickle-indexed file provenance.
- **Add an index on `chunk_source_provenance.chunk_id`** for efficient batch hydration.

### Risk Assessment: **MEDIUM**

The additive schema approach limits blast radius, but the strategy-scoping ambiguity and the multiple unaddressed write paths (trickle, reindex) could leave provenance incomplete. The delete cleanup is well-designed.

---

## Plan 25-04: Regression Suite, Documentation, and Phase Verification

### Summary

A solid closing plan that runs all test surfaces, updates documentation, and writes a comprehensive final summary. The deferred scope audit is a good practice. Minor concerns about acceptance criteria fragility and the grep-based scope enforcement test.

### Strengths

- **Cross-surface regression coverage.** Tests ingestion, storage, API, and MCP in a single verification pass.
- **Deferred scope audit in the final summary.** Explicitly listing all deferred items (Telegram, assets, entities, transports, TTL, validation) is excellent for future phase boundaries.
- **Architecture panel acceptance gate answers.** Task 4 explicitly answers every question from the planning acceptance gate.
- **No production restart.** Explicitly documents that `dotmd index --force` and production restarts are not part of verification.

### Concerns

1. **Grep-based scope enforcement test is fragile.** (LOW) — Task 1 says "at least one test asserts no runtime Telegram adapter or source asset/entity implementation exists in Phase 25 files." String-matching source code for absence of terms is fragile (e.g., a docstring mentioning "Telegram" as a future reference would fail). Consider testing for the absence of specific imports or class instantiations instead.

2. **No performance regression test.** (LOW) — Phase 25 adds new DB tables and provenance writes on every chunk save. There's no test verifying that the overhead is negligible (e.g., timing assertion that bulk indexing N files with provenance is within 5% of baseline without provenance). This matters on the Ivy Bridge hardware.

3. **Acceptance criteria are string-matching checks.** (LOW) — e.g., "`25-04-SUMMARY.md` contains `Canonical filesystem ref`". These are easily gamed and don't verify content quality. However, given the autonomous execution context, this is an acceptable trade-off.

### Suggestions

- Replace the grep-based scope test with a structural test: verify `SourceAdapterProtocol.__abstractmethods__` contains only the expected methods, or verify `SourceDocument` has no `telegram`/`SourceAsset`/`SourceEntity` fields via Pydantic schema inspection.
- Add a lightweight performance assertion (e.g., indexing 10 files with provenance completes in <2x the time without provenance).

### Risk Assessment: **LOW**

This is a verification and documentation plan with minimal code changes. The main risk is incomplete coverage, not regressions.

---

## Overall Phase Assessment

### Risk Assessment: **MEDIUM**

The phase is well-scoped and the four-plan decomposition is logical. Plans 01 and 04 are LOW risk. Plan 03 is MEDIUM risk due to schema ambiguity but is bounded by its additive approach. **Plan 02 is the critical risk path** — it touches the pipeline's core indexing loop and has three unresolved HIGH-severity integration gaps:

1. **FileTracker/SourceDocument impedance mismatch** — the central routing decision is unspecified
2. **Unaddressed trickle `index_file()` path** — will produce inconsistent provenance
3. **`_meta_entity_id()` normalization alignment** — will silently break the metadata-only fast path

### Cross-Cutting Recommendations

1. **Resolve `document_ref` normalization now, not in implementation.** Specify that `document_ref = str(Path(path).resolve())` for filesystem Markdown. This aligns with `_meta_entity_id()`, `VecComponentStore` keys, and existing path-based lookups.

2. **Resolve the SourceDocument → FileInfo bridge now.** The simplest approach: `FilesystemMarkdownSourceAdapter.discover()` returns `list[SourceDocument]`, each of which can produce a `FileInfo` via a `to_file_info()` method. The pipeline continues to use `FileInfo` for tracker operations but uses `SourceDocument` for provenance.

3. **Address all pipeline write paths, not just bulk `index()`.** The trickle `index_file()` path and `reindex_vectors()` must be included in Plans 02-03 scope.

4. **Address `discover_files_multi`.** Either the adapter wraps it, or the plan documents it as temporarily bypassed with a follow-up task.

5. **Resolve `source_documents` table scoping as strategy-independent.** Source metadata (namespace, document_ref, media_type) is inherently strategy-independent. Use `document_ref` as PK.

---

## Consensus Summary

Only OpenCode was invoked in this cycle, per the requested reviewer set. The synthesis below therefore captures recurring or phase-level themes inside the single OpenCode review rather than cross-reviewer agreement.

### Agreed Strengths

- Phase 25 is decomposed cleanly into model, routing, persistence, and verification plans.
- The plans preserve current filesystem Markdown behavior as the MVP path and defer Telegram/source asset/entity expansion.
- Compatibility with existing chunk text, fingerprints, `file_paths`, and MCP read/search surfaces is treated as a first-class regression concern.
- The persistence plan is additive and keeps `file_paths` authoritative for current search/read compatibility.

### Agreed Concerns

- HIGH: `SourceDocument.file_path` and `document_ref` coexistence lacks an explicit invariant and deterministic filesystem normalization rule.
- HIGH: The `SourceDocument` to `FileInfo` bridge for `FileTracker.diff()` is not specified, leaving the core routing decision to implementation.
- HIGH: The trickle `index_file()` path is not covered, so it may bypass adapter/provenance behavior used by bulk indexing.
- HIGH: `source_documents` table scoping is unresolved even though strategy-scoped versus global storage changes helper APIs and duplication behavior.
- MEDIUM: `discover_files_multi`, provenance write locations, and `document_ref` alignment with `_meta_entity_id()` need explicit plan-time decisions.
### Divergent Views

- No divergent reviewer views: this cycle intentionally used OpenCode only.
