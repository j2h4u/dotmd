---
phase: 28
reviewers: [codex, opencode]
reviewed_at: 2026-05-07T23:01:07+05:00
plans_reviewed:
  - .planning/phases/28-application-source-provider-contract/28-01-provider-models-and-protocol-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-02-source-state-and-fingerprint-storage-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-03-fixture-provider-contract-PLAN.md
  - .planning/phases/28-application-source-provider-contract/28-04-docs-and-telegram-contract-note-PLAN.md
---

# Cross-AI Plan Review - Phase 28

## Codex Review

# Cross-AI Plan Review

## Plan 01: Provider Models and Protocol

**Summary**  
Strong minimal contract plan, aligned with the phase boundary and locked decisions. Main risk is that making `SourceUnit.updated_at` required may break existing filesystem ingestion/tests unless all current constructors are audited in the same wave.

**Strengths**
- Keeps provider names generic and Telegram only in examples/tests.
- Correctly avoids `export_documents` / `export_units`.
- Uses Protocol + Pydantic, matching existing project style.
- Explicitly blocks human-rendered MCP output as an input format.

**Concerns**
- **HIGH:** Adding required `SourceUnit.updated_at` can break existing filesystem paths, storage tests, pipeline code, or fixtures that construct `SourceUnit`.
- **MEDIUM:** Verification only runs the new provider test file, so regressions in existing source adapter behavior may not surface until Plan 04.
- **LOW:** “Protocol exposes exactly the required methods” is hard to prove structurally in Python; tests should check absence from module/classes, not rely on Protocol semantics.

**Suggestions**
- Add a task step to `rg "SourceUnit(" backend` and update all existing constructors.
- Include `tests/ingestion/test_source_filesystem.py` in Plan 01 verification if `SourceUnit` is changed.
- Consider whether provider payload models belong in `core/models.py` or a dedicated source-provider model module to avoid overloading core.

**Risk Assessment: MEDIUM**  
The contract design is sound, but the required model-field change has non-local blast radius.

---

## Plan 02: Source State and Fingerprint Storage

**Summary**  
Good storage foundation for cursor safety and idempotent unit processing. The checkpoint semantics are especially well framed. The main gap is transaction API realism: requiring `conn` everywhere is safe, but the plan should verify it matches current `SQLiteMetadataStore` connection patterns.

**Strengths**
- Correctly distinguishes `checkpoint_cursor` from speculative `next_cursor`.
- Adds additive tables only, avoiding rebuild/reindex risk.
- Tests rollback behavior, which is the right failure mode to validate.
- Keeps lifecycle/delete semantics deferred.

**Concerns**
- **HIGH:** Helper signatures requiring `conn: _SQLiteConn` may not match existing public storage helper patterns; risk of awkward or leaky API.
- **MEDIUM:** `record_source_checkpoint_error(..., conn=...)` could require callers to open transactions just to record failures; clarify intended usage.
- **MEDIUM:** `upsert_source_unit_fingerprint` returning only `bool` may be too lossy later; callers may need `new`, `changed`, or `unchanged`.
- **LOW:** Storing `metadata_json` as a dict-returning helper needs JSON parse/serialization error tests.

**Suggestions**
- Match existing metadata transaction conventions exactly; if there is a store-managed transaction helper, use it.
- Consider returning an enum/string status from fingerprint upsert: `new`, `changed`, `unchanged`.
- Add tests for `checkpoint_cursor=None`, metadata round-trip, and updated timestamp format.

**Risk Assessment: MEDIUM**  
Conceptually right, but storage APIs can become brittle if they do not fit the existing store transaction style.

---

## Plan 03: Fixture Provider Contract

**Summary**  
Useful proof layer that makes the contract executable without Telegram. It appropriately validates cursor slices, windows, implicit root units, and fingerprint replay. Risk is modest, mostly around putting a fixture provider in production source code.

**Strengths**
- Tests real provider behavior rather than only model construction.
- Covers Telegram-like unit windows and document-only fallback.
- Validates no dependency on `mcp-telegram` internals.
- Exercises idempotent fingerprint flow across provider + storage.

**Concerns**
- **MEDIUM:** `FixtureApplicationSourceProvider` in `backend/src` may ship test-only code as public API unless clearly marked.
- **MEDIUM:** Cursor parsing with `offset:<n>` needs validation for malformed cursors, negative offsets, and invalid limits.
- **LOW:** Sorting by `order_key` assumes lexical order works for all fixture examples; tests should use stable sortable keys.
- **LOW:** Unknown-unit behavior uses `ValueError`; acceptable, but provider error semantics are otherwise undefined.

**Suggestions**
- Put fixture provider in tests unless Phase 29 needs it as a reusable dev utility.
- Add tests for malformed cursor, `limit <= 0`, and unknown unit.
- Document that fixture cursor format is non-contractual.

**Risk Assessment: LOW-MEDIUM**  
Good executable validation. Keep test utilities from becoming accidental production API.

---

## Plan 04: Docs and Telegram Contract Note

**Summary**  
Well-scoped documentation closeout. It directly addresses the `mcp-telegram` boundary and should prevent Phase 29 from reopening major decisions. Verification is grep-heavy, so it should be paired with final tests from prior plans.

**Strengths**
- Explicitly forbids direct Telethon/client ownership and private SQLite reads.
- Documents cursor commit ordering clearly.
- Provides concrete Telegram mappings and payload examples.
- Correctly states Phase 28 is contract/fixture only, not ingestion.

**Concerns**
- **MEDIUM:** Grep checks prove strings exist, not that examples are valid JSON or match implemented model fields.
- **MEDIUM:** The summary allows `Self-Check: PASSED` with “ratchet documented”; criteria should define what failures are acceptable.
- **LOW:** `metadata_json` examples may accidentally encode too much Telegram-specific structure unless framed as optional provider metadata.

**Suggestions**
- Validate JSON examples with a simple parser test or keep them as clearly marked JSONC/pseudocode.
- Require docs to mention `checkpoint_cursor` is committed only after source-document, fingerprint, binding/provenance, and indexing persistence succeeds.
- Add a brief “not implemented in Phase 28” section to avoid future confusion.

**Risk Assessment: LOW**  
Mostly documentation risk. Scope is clear and unlikely to destabilize code.

---

## Overall Assessment

The phase plan is coherent and mostly well bounded. It achieves the core goal: a minimal application-source provider contract, durable checkpoint/fingerprint support, fixture validation, and a concrete `mcp-telegram` boundary note.

Biggest improvement: move regression checks earlier. Plan 01 changes a core model, so filesystem ingestion and existing service tests should run before later waves. The remaining risks are manageable if transaction helper APIs are aligned with current `metadata.py` patterns and test-only fixtures are kept from becoming accidental public framework surface.

---

## OpenCode Review

## Phase 28 Plan Review

### Summary

The four plans form a clean, well-scoped contract foundation: protocol/payloads (Plan 01) → durable state (Plan 02) → fixture validation (Plan 03) → documentation (Plan 04). The wave ordering is correct, decisions are faithfully mapped, and the plans explicitly avoid full reindex, Telegram-specific leaks, and premature lifecycle abstractions. The main concerns are: (1) adding `updated_at` to `SourceUnit` is a breaking change for any existing instantiation, and the plans don't acknowledge this; (2) existing `SourceUnit` fields (`unit_type`, `chunking_hints`) are absent from D-14 and unmentioned in the plans; (3) the fixture provider ships in production code rather than test infrastructure.

---

### Plan 01: Provider Models and Protocol

**Strengths**
- TDD-first with explicit failing-test-first discipline
- Correctly identifies `updated_at` as missing from `SourceUnit` (verified: line 147-160 of `models.py` has no timestamp field)
- Generic naming enforced via acceptance criteria (`does not contain export_documents`)
- Protocol mirrors existing `SourceAdapterProtocol` style in `source.py` — consistent with codebase conventions
- `SourceUnitWindow` model is well-scoped for the `read_unit_window` contract

**Concerns**
- **HIGH: Adding `updated_at` to `SourceUnit` will break existing instantiations.** `SourceUnit` uses `ConfigDict(extra="forbid")` (verified at line 148). Every `SourceUnit(...)` call in the codebase must supply `updated_at` after this change. The plan mentions the field addition but does not scope a search-and-fix for existing callers. If Phases 25-27 already instantiate `SourceUnit` anywhere in pipeline or storage code, the plan's `pytest` command is too narrow to catch those breaks — it only runs `test_application_source_provider.py`.
- **MEDIUM: Existing `SourceUnit` fields `unit_type` and `chunking_hints` are invisible to the plan.** `SourceUnit` currently has `unit_type: str` and `chunking_hints: dict` (verified: lines 152, 158). D-14 lists required minimum fields but these existing fields aren't mentioned. This creates ambiguity: do providers *need* to set `unit_type`? The fixture provider in Plan 03 will have to supply it regardless because of `extra="forbid"`. The plan should either acknowledge this or make `unit_type` optional.
- **MEDIUM: SourceDocument has many required fields not shown in test examples.** Plan 01 task 1 shows `SourceDocument(namespace="telegram", document_ref="dialog:123", ref="telegram:dialog:123", ...)` but `SourceDocument` requires `title`, `source_uri`, `media_type`, `parser_name`, `updated_at`, `content_fingerprint`, `metadata_fingerprint` (verified: lines 81-113). The `...` hides real test fixture complexity. The plan should either make the full example explicit or acknowledge that test helpers will be needed.
- **LOW: No mention of `SourceDocument._validate_refs` impact.** The existing validator enforces `ref == "{namespace}:{document_ref}"`. For Telegram, `ref="telegram:dialog:123"` with `namespace="telegram"`, `document_ref="dialog:123"` works. But this is a tight coupling the plan inherits silently.

**Suggestions**
- Add a task or sub-step: grep codebase for all `SourceUnit(` instantiations and update them with `updated_at`. Run the full test suite, not just the new provider test file.
- Explicitly decide: does `unit_type` stay required, become optional, or get a provider-agnostic default? Document the decision.
- Provide a complete `SourceDocument(...)` construction example in the test to surface the field burden early.

---

### Plan 02: Source State and Fingerprint Storage

**Strengths**
- Checkpoint-after-transaction pattern is well-designed: `commit_source_checkpoint` takes `conn: _SQLiteConn` (matching existing caller-owns-tx pattern in `metadata.py`)
- Rollback test explicitly required — directly addresses the D-07/D-08 crash-safety concern
- `upsert_source_unit_fingerprint` returning `bool` (changed vs unchanged) is a clean idempotency contract
- No `deleted_at` column — correctly defers lifecycle per D-15
- `CREATE TABLE IF NOT EXISTS` — additive, no migration risk

**Concerns**
- **MEDIUM: `ensure_source_state_tables()` called from `SQLiteMetadataStore.__init__`.** The existing store calls multiple `ensure_*` methods in `__init__`. Adding two more tables is fine in isolation, but the plan should verify this doesn't create issues with the existing in-memory test stores that use temporary databases. The test patterns in `test_metadata_m2m.py` use `_build_m2m_store()` which creates a fresh `SQLiteMetadataStore` — so this should be safe, but it's worth confirming the new table creation doesn't fail on stores that don't need source checkpoints.
- **LOW: `source_checkpoints.last_error` column is storage-level error tracking.** This is the first error-tracking column in the metadata store. It's useful for diagnostics but the plan doesn't describe when `record_source_checkpoint_error` is called relative to the normal flow. Is it called in a `except` block? Inside the same transaction? If the transaction rolls back, the error record rolls back too. This might be intentional but should be documented.
- **LOW: `indexed_at` on `source_unit_fingerprints` uses `TEXT` type.** Existing metadata tables use `TEXT` for timestamps (ISO 8601 strings), so this is consistent. But the plan mentions `indexed_at: datetime | None = None` in the helper signature — clarify whether the storage layer stores ISO strings and the helper converts, or if it stores datetime objects directly.

**Suggestions**
- Add a brief note about `record_source_checkpoint_error` transaction semantics: does it auto-commit or require a caller-owned connection?
- Verify that existing test fixtures that create `SQLiteMetadataStore` won't break when `__init__` tries to create two new tables.

---

### Plan 03: Fixture Provider Contract

**Strengths**
- Deterministic cursor model (`offset:<n>`) keeps tests predictable and debuggable
- Tests both message-window and document-only fallback paths — covers D-16/D-17/D-18
- Replay idempotency test connects the fixture to storage fingerprint helpers from Plan 02
- No `telethon` / `mcp_telegram` imports enforced via acceptance criteria

**Concerns**
- **MEDIUM: `FixtureApplicationSourceProvider` lives in production code (`backend/src/dotmd/ingestion/source_provider.py`).** The plan says "test-only-safe" but ships it in the importable package. Any future `from dotmd.ingestion.source_provider import FixtureApplicationSourceProvider` in production code would pull in test infrastructure. A cleaner approach: put the fixture in `tests/ingestion/` or a `tests/conftest.py` and keep `source_provider.py` as pure protocol + payload models.
- **MEDIUM: `make_implicit_root_unit` is a production-code helper.** This helper normalizes document-only sources into a single `SourceUnit`. It's useful but is it part of the contract or a test convenience? If it's a real helper that Phase 29 needs, it should be documented as such. If it's test-only, it shouldn't be in the ingestion module.
- **LOW: Unknown `unit_ref` raises `ValueError`.** This is reasonable but the existing codebase patterns in `storage/metadata.py` tend to return `None` for missing items rather than raising. The error surface is internal (provider-to-dotMD), so raising is acceptable, but it should be noted as a deviation.

**Suggestions**
- Move `FixtureApplicationSourceProvider` and `make_implicit_root_unit` to `tests/ingestion/fixtures.py` or a dedicated test module. Keep `source_provider.py` as pure protocol + `SourceUnitWindow`.
- If `make_implicit_root_unit` is intended for production use in Phase 29, rename it to something like `normalize_document_to_unit` and document it as a contract utility rather than a fixture helper.

---

### Plan 04: Docs and Telegram Contract Note

**Strengths**
- Explicit scope exclusions prevent Phase 29 scope creep
- Grep-based acceptance criteria are verifiable and concrete
- `28-04-SUMMARY.md` with `Self-Check: PASSED` gate is a good traceability practice
- Commit-order rule documented prominently

**Concerns**
- **LOW: Verification command includes the full test suite but Plan 01's breaking change may cause failures.** If Plan 01 adds `updated_at` to `SourceUnit` and doesn't update all callers, Plan 04's full-suite pytest command will fail, blocking the `Self-Check: PASSED` gate.
- **LOW: `docs/architecture.md` update is vague.** "A short Phase 28 paragraph" doesn't specify what architectural information to convey. The existing architecture doc likely has specific section formatting that should be matched.

**Suggestions**
- Add explicit instruction to run `just typecheck` and `just lint` *before* the full pytest suite in the summary verification, since type errors from Plan 01's breaking change will be caught faster by mypy.

---

### Risk Assessment: **MEDIUM**

**Justification:** The plans are well-structured, correctly scoped, and faithful to the decisions. The primary risk is **Plan 01's breaking change to `SourceUnit`** — adding `updated_at` to a model with `ConfigDict(extra="forbid")` will break every existing instantiation site. The plan's verification scope (`test_application_source_provider.py` only) is too narrow to catch these breaks. A single grep for `SourceUnit(` across the codebase followed by a full test run would reduce this to LOW risk.

The secondary risk is **fixture provider placement in production code**, which is a code-smell rather than a functional issue but creates a precedent that's harder to correct later.

---

## Consensus Summary

Both reviewers found the Phase 28 plan coherent, well scoped, and aligned with the application-source provider boundary. They agreed that the contract correctly avoids direct Telegram ownership, human-rendered MCP output as input, forced full reindex, and premature lifecycle/delete abstractions.

### Agreed Strengths

- Minimal generic provider contract with Telegram treated as the first proof source, not a Telegram-only design.
- Cursor/checkpoint semantics are explicitly called out, with durable progress saved only after local persistence succeeds.
- Fixture-based validation avoids depending on live Telegram or `mcp-telegram` internals during this phase.
- Documentation closeout should give Phase 29 a concrete `mcp-telegram` payload boundary without reopening broader integration questions.

### Agreed Concerns

- **HIGH:** Adding required `SourceUnit.updated_at` has non-local blast radius. Existing `SourceUnit(...)` constructors, filesystem source tests, storage tests, and pipeline/service paths must be audited and updated before the plan-local verification can be trusted.
- **MEDIUM:** The fixture provider and implicit-root helper risk becoming accidental production API if they live in importable source code without clear intent.
- **MEDIUM:** Verification should move broader regression checks earlier, especially around existing filesystem ingestion and service tests affected by the `SourceUnit` model change.
- **MEDIUM:** The documentation grep checks prove key strings exist, but do not validate JSON examples or field-level alignment with implemented Pydantic models.

### Divergent Views

- Codex raised a second **HIGH** around storage helper signatures requiring explicit `conn` handles: the plan must match existing `SQLiteMetadataStore` transaction conventions to avoid a leaky or awkward API. OpenCode considered the caller-owned transaction pattern consistent with current `metadata.py`, but still suggested clarifying error-recording transaction semantics.
- Codex suggested returning a richer fingerprint status (`new`, `changed`, `unchanged`) instead of a boolean. OpenCode found the boolean contract clean enough for Phase 28.
- OpenCode specifically flagged existing `SourceUnit` fields such as `unit_type` and `chunking_hints` as plan ambiguity; Codex framed the same area more generally as constructor/test blast radius.

### Current HIGH Concerns

- Adding required `SourceUnit.updated_at` can break existing instantiation sites and is not covered early enough by the current Plan 01 verification scope.
- Storage helper signatures that require explicit `conn` handles may not match existing metadata-store transaction conventions, risking a leaky API unless verified against `metadata.py`.
