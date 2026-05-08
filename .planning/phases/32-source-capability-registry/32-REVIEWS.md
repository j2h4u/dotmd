---
phase: 32
reviewers: [opencode, claude]
reviewed_at: 2026-05-08T17:57:49+05:00
cycle: 2
plans_reviewed:
  - 32-01-source-descriptor-contract-PLAN.md
  - 32-02-filesystem-telegram-registry-seeds-PLAN.md
  - 32-03-provider-description-compatibility-PLAN.md
  - 32-04-airweave-mapping-docs-PLAN.md
---

# Cross-AI Plan Review - Phase 32

Cycle 2 review after replan commit `eafd8ed`.

## Consensus Summary

CYCLE_SUMMARY: current_high=0

### Current HIGH Concerns

None.

### Agreed Strengths

- Both reviewers agree the cycle-1 HIGH about filesystem config schema requiredness is resolved: the latest Plan 02 explicitly requires `paths` as required `list[str]` and `exclude` as optional `list[str]`, with concrete assertions.
- Both reviewers agree the cycle-1 HIGH about Telegram daemon capability string mismatch is resolved: the latest Plan 03 defines `LEGACY_CAPABILITY_ALIASES`, a `normalized_capabilities()` accessor, and tests for legacy acceptance plus canonical normalization.
- Both reviewers agree the phase remains additive, declarative, and runtime-neutral, with no production indexing, credential, cursor commit, or Airweave runtime dependency in scope.

### Agreed Concerns

- MEDIUM: Capability semantics need careful wording. `MATERIALIZATION` on filesystem and `FEDERATED_SEARCH` on Telegram are defensible as source-model capabilities, but downstream phases need explicit semantics so they do not confuse provider capability with current dotMD routing.
- LOW/MEDIUM: The two-module naming pattern, `core/source_registry.py` and `ingestion/source_registry.py`, remains easy to confuse during execution and review.
- LOW: Some verification is grep-based and could be made more precise, especially around `ConfigDict(extra="forbid")` on every new descriptor sub-model.

### Divergent Views

- OpenCode treated the remaining filename collision and capability semantics as non-blocking design opinions.
- Claude recommended a few extra comments or acceptance criteria to make the same concerns clearer, but still classified the overall phase risk as LOW and found no HIGH blockers.

### Recommendation

Proceed to execution. The unresolved concerns are below HIGH severity and can be handled as implementation polish or reviewer attention points during Phase 32 execution.

---

## OpenCode Review

# Cross-AI Plan Review: Phase 32, Cycle 2

## Plan 01: Source Descriptor Contract

### Summary

Clean TDD plan establishing the closed `SourceCapability` enum, typed descriptor models, and immutable registry container. The prior concerns about mutable defaults, untyped field_type, and missing `extra="forbid"` mandate are all explicitly resolved. The plan is ready for execution.

### Strengths

- `SOURCE_SCHEMA_FIELD_TYPES = frozenset({...})` with explicit validation addresses the prior stringly-typed `field_type` concern directly. The allowed vocabulary is closed and testable.
- `Field(default_factory=...)` is now a mandatory acceptance criterion - grep-able and prevents the `B006` ruff issue.
- `ConfigDict(extra="forbid")` appears in both the task action and acceptance criteria, closing the prior ambiguity.
- Threat model entry for "Schema field type strings become arbitrary values" with MEDIUM severity and explicit mitigation shows the planners understood the concern even if they kept `str` for flexibility.

### Concerns

- **MEDIUM - Two `source_registry.py` modules persist.** `core/source_registry.py` (container) and `ingestion/source_registry.py` (seeds). The naming collision is real but the boundary is clean (model container vs. ingestion-layer factory). Acceptable trade-off, just requires care in reviews.
- **LOW - Test placement remains under `tests/ingestion/`** for what are core-level model tests. Not a correctness issue; discoverability could improve later.

### Risk: **LOW**

Both prior cycle-1 HIGHs for Plan 01 (mutable defaults, untyped field_type) are resolved with explicit acceptance criteria and tests.

---

## Plan 02: Filesystem And Telegram Registry Seeds

### Summary

Detailed seed descriptors with exact field assertions. The prior HIGH about filesystem config schema requiredness is fully resolved - `paths` is now asserted as required and `exclude` as optional with typed field_type. The `socket_path` naming now aligns with the existing codebase. Default registry test is a hard set equality.

### Strengths

- `paths.required is True` and `exclude.required is False` are now explicit acceptance criteria with matching implementation in task 2. Prior HIGH fully resolved.
- `socket_path` replaces the earlier `daemon_socket`, matching `telegram_provider.py:71`'s existing `socket_path: Path` attribute.
- Default registry test uses `== {"filesystem", "telegram"}` - no escape hatch. Prior hedged-test concern resolved.
- Telegram seed asserts `cursor_schema.cursor_kind == "provider_checkpoint"`, closing the prior LOW about missing cursor_kind assertion.
- Exact capability sets are asserted with both positive and negative checks.

### Concerns

- **MEDIUM - `federated_search` on Telegram remains aspirational.** The capability is declared but Phase 34 implements it. The descriptor describes the *source model* capability (the provider can support it), not current dotMD implementation status. This is a defensible design choice documented in context, but downstream phases should be aware of the distinction. No action needed in Phase 32 plans.
- **MEDIUM - `materialization` on filesystem is still semantically debatable.** Same as cycle 1. The plan documents it, the descriptor carries it, and Phase 35 can refine semantics when it migrates the filesystem execution path. Not a blocker.

### Risk: **LOW**

Prior HIGH resolved. Remaining concerns are design opinions, not plan quality defects.

---

## Plan 03: Provider Description Compatibility

### Summary

The capability string mismatch - the headline risk from cycle 1 - is now explicitly addressed with `LEGACY_CAPABILITY_ALIASES`, a `normalized_capabilities()` accessor, and tests for both legacy acceptance and canonical normalization. The bridge is cleanly scoped: no protocol changes, no runtime construction, no `descriptor_display` metadata_json copy.

### Strengths

- `LEGACY_CAPABILITY_ALIASES: dict[str, str] = {"unit-window": "read_unit_window", "incremental-export": "incremental_cursor"}` is a concrete, testable normalization map. Prior HIGH resolved.
- `normalized_capabilities(self) -> list[str]` provides canonical access while preserving raw `capabilities: list[str]` for backward compatibility with the daemon payload contract.
- Tests cover all three angles: legacy payload validates, legacy normalizes to canonical, and `describe_source()` produces normalized capabilities from current daemon strings.
- Explicitly forbids `descriptor_display` metadata_json copy - prior MEDIUM resolved.
- Protocol return type preserved; `TelegramApplicationSourceProvider` still calls `ApplicationSourceDescription(**self._client.describe_source())`.

### Concerns

- **MEDIUM - `LEGACY_CAPABILITY_ALIASES` lives on `ApplicationSourceDescription`** rather than near the `SourceCapability` enum. When Phase 33 lifecycle owns provider migration and the daemon contract updates, the alias map should move or be removed. Not a Phase 32 concern, but worth a TODO comment pointing to Phase 33/36 migration.
- **LOW - No explicit test that unknown legacy strings pass through `normalized_capabilities` unchanged.** The map only covers two known aliases. If a future provider sends `"some-other-string"`, the normalization should leave it alone (identity mapping). The plan implies this but doesn't test it.

### Risk: **LOW**

The capability string mismatch is now a solved problem with a tested bridge. No remaining HIGH concerns.

---

## Plan 04: Airweave Mapping Documentation

### Summary

Documentation plan with concrete mapping table, closed status vocabulary, runtime-boundary section, and strengthened grep checks. Prior concerns about conditional README modification and weak Airweave-import verification are resolved.

### Strengths

- `files_modified` correctly omits `README.md`; only listed when the conditional task actually modifies it.
- Grep checks now include Airweave-specific identifiers (`supports_browse_tree`, `output_entity_definitions`, `class_name`, `feature_flag`) beyond just import checks.
- Every mapping table row must have a non-empty Reason cell - explicit acceptance criterion.
- Four-section structure (Copied/Adapted/Rejected/Deferred) matches D-13/D-14 exactly.

### Concerns

- **LOW - No guidance on where in `docs/source-adapter-architecture.md` to insert the Phase 32 section.** The execution agent will need to read the full file to find the right insertion point. Minor discoverability issue.

### Risk: **LOW**

Documentation-only, well-scoped, with strong grep-based verification.

---

## Cross-Plan Assessment

### Prior HIGH Resolution

| Prior HIGH | Resolution | Evidence |
|---|---|---|
| Plan 02 filesystem config schema requiredness | **Resolved** | Task 1 asserts `paths.required is True`, `exclude.required is False`, both `field_type == "list[str]"`. Task 2 implementation specifies exact `SourceSchemaField` definitions. |
| Plan 03 capability string mismatch | **Resolved** | `LEGACY_CAPABILITY_ALIASES` map, `normalized_capabilities()` accessor, tests for legacy acceptance + canonical normalization + `describe_source()` producing canonical strings. |

### Agreed Remaining Concerns (all MEDIUM or below)

- Two `source_registry.py` filenames - acceptable boundary, not a quality defect.
- `federated_search` on Telegram is aspirational - defensible design choice for Phase 32.
- `materialization` on filesystem is semantically debatable - Phase 35 can refine.
- `LEGACY_CAPABILITY_ALIASES` placement should point to Phase 33/36 for eventual removal.

### Overall Phase Risk: **LOW**

Both cycle-1 HIGH concerns are resolved with concrete, testable mechanisms. The phase is additive, declarative, and well-gated by TDD. No production runtime behavior changes. Ready for execution.

---

## Current HIGH Concerns

None.

---

## Claude Review

# Cross-AI Plan Review - Phase 32 (Cycle 2)

## Cycle Summary

CYCLE_SUMMARY: current_high=0

---

## Plan 01: Source Descriptor Contract

### Summary
The plan now mandates `Field(default_factory=...)` for every collection/dict default, requires `ConfigDict(extra="forbid")` on every new descriptor model, defines a closed `SOURCE_SCHEMA_FIELD_TYPES` vocabulary, and adds a mutability test that catches shared-default leakage. The cycle-1 style and field-type concerns are now grep-verifiable.

### Strengths
- `SOURCE_SCHEMA_FIELD_TYPES = frozenset({"str", "int", "bool", "path", "list[str]", "dict[str, Any]"})` closes the previously-open `field_type: str` design debt.
- `test_descriptor_collection_defaults_are_not_mutable` directly exercises shared-state leakage instead of trusting style alone.
- `model_copy(deep=True)` on every read keeps the registry immutable from caller mutation.
- Explicit grep negatives (`does not contain "airweave"`, `does not contain "TokenProvider" or "credential"`) catch scope creep cheaply.

### Concerns
- **MEDIUM - Filename collision still present.** `core/source_registry.py` (Plan 01) and `ingestion/source_registry.py` (Plan 02) coexist. Imports like `from dotmd.core.source_registry import SourceRegistry` and `from dotmd.ingestion.source_registry import default_source_registry` are easy to confuse during edits and reviews. Cycle 1 flagged this; it was not addressed.
- **LOW - `ConfigDict(extra="forbid")` grep is satisfied by pre-existing models.** `models.py` already contains `ConfigDict(extra="forbid")` for `SourceDocument` etc., so the grep passes even if a new descriptor model omits it. The `test_source_descriptor_forbids_extra_fields` test mitigates this for `SourceDescriptor`, but not for `SourceDisplayMetadata`, `SourceConfigSchema`, `SourceAuthSchema`, `SourceCursorSchema`, or `SourceSchemaField`.
- **LOW - Test discoverability.** Tests for `core` types still live under `tests/ingestion/test_source_registry.py`. Not blocking, but `tests/core/` would be more conventional.

### Suggestions
- Rename one of the two `source_registry.py` modules - e.g., `core/source_registry_models.py` for the type contract, keeping `ingestion/source_registry.py` for seeds. Or collapse the `SourceRegistry` container into `ingestion/source_registry.py` since that is where seeds live.
- Add per-model `extra="forbid"` tests for each descriptor sub-model, or add a stronger acceptance criterion: `rg -c 'extra="forbid"' backend/src/dotmd/core/models.py >= 9` (current 4 + 5 new).

### Risk: LOW

---

## Plan 02: Filesystem And Telegram Registry Seeds

### Summary
Cycle-1 HIGH on filesystem field types and requiredness is fully resolved. Plan now mandates `paths` required `list[str]`, `exclude` optional `list[str]`, exact capability sets, and `cursor_schema.cursor_kind == "provider_checkpoint"` for Telegram. The default-registry test uses hard set equality.

### Strengths
- Filesystem config schema now has typed, required-marked fields with descriptions matching the live `discover_multi(paths, exclude=None)` signature.
- `test_default_registry_contains_filesystem_and_telegram` uses `== {"filesystem", "telegram"}` instead of a hedged assertion.
- Filesystem cursor_kind description (`fingerprint-based change detection over content and metadata fingerprints; filesystem does not own provider cursor commits`) clarifies the previously-ambiguous "fingerprint" overload.
- Telegram auth `delegated_to == "mcp-telegram"` is grep-asserted, preventing the descriptor from implying direct Telegram API ownership.
- Forbidden imports (`Telethon`, `airweave`) catch runtime creep.

### Concerns
- **MEDIUM - `MATERIALIZATION` capability on filesystem still semantically thin.** The plan retains it but adds no documentation justifying why a local filesystem source has it. If the intent is "this source can produce on-demand bytes for a unit ref," that should be in the `SourceCapability.MATERIALIZATION` docstring or in the Airweave mapping doc. Otherwise Phase 33+ readers will assign different meanings.
- **MEDIUM - `FEDERATED_SEARCH` on Telegram is aspirational.** Phase 32 does not implement federated search; Phase 34 does. The descriptor advertises a capability dotMD does not yet route. There is no `planned_capabilities` vs `available_capabilities` split, so consumers must guess. Either document explicitly that capability flags describe the source *model*, not current dotMD wiring, or split into provider-supported vs dotmd-routed.
- **LOW - Telegram `socket_path` field.** The descriptor uses `socket_path` matching `TelegramSourceClientProtocol`, which is consistent with the live code. Fine, just noting alignment was achieved.

### Suggestions
- Add a one-line definition for each `SourceCapability` enum value (docstring or comment). The mapping doc in Plan 04 is the natural home for `MATERIALIZATION` and `FEDERATED_SEARCH` semantics.
- Optional: add a `planned_capabilities` field for future-only flags, or document in Plan 04 that Phase 32 capability flags are source-model claims, not implementation claims.

### Risk: LOW

---

## Plan 03: Provider Description Compatibility

### Summary
Cycle-1 HIGH on capability string mismatch is fully resolved with `LEGACY_CAPABILITY_ALIASES` and `normalized_capabilities()`. The bridge keeps existing daemon payloads validating, exposes a canonical view, and explicitly declines to change the daemon contract (deferred to Phase 33+ when lifecycle owns providers). The acceptance criteria grep for both legacy and canonical strings.

### Strengths
- `LEGACY_CAPABILITY_ALIASES = {"unit-window": "read_unit_window", "incremental-export": "incremental_cursor"}` makes the two-vocabulary problem auditable in one place.
- `normalized_capabilities()` is a clear migration point: future code compares canonical, legacy payloads still validate.
- `from_descriptor` no longer adds `descriptor_display` to `metadata_json`; the cycle-1 ambiguity is removed.
- `ApplicationSourceProviderProtocol.describe_source()` return type is unchanged - Phase 33 lifecycle work is not pre-empted.
- Tests exercise both paths: legacy validation and canonical normalization.

### Concerns
- **MEDIUM - No enforcement that future code uses `normalized_capabilities()` over raw `capabilities`.** The bridge solves drift only if consumers consistently pick the normalized view. Today nothing prevents new code from comparing raw `description.capabilities` against `SourceCapability.READ_UNIT_WINDOW.value` and silently failing for legacy payloads. Phase 32 cannot fully prevent this, but a comment near `capabilities: list[str]` directing new code to `normalized_capabilities()` would reduce footguns.
- **LOW - `LEGACY_CAPABILITY_ALIASES` is a static map.** If future daemon versions introduce new legacy strings, the map must be updated by hand. A test that asserts every alias source is unique and every alias target is in `SourceCapability` would catch typos.
- **LOW - No daemon-payload migration owner identified.** The plan defers daemon contract migration to "Phase 33 lifecycle" implicitly. A one-line forward reference (e.g., "Phase 33+ may migrate the daemon payload to canonical strings; until then, normalize at read time") in the threat model or success criteria would close the loop.

### Suggestions
- Add a docstring on `ApplicationSourceDescription.capabilities` directing readers to `normalized_capabilities()` for canonical comparison.
- Add a self-check test: `assert all(target in {c.value for c in SourceCapability} for target in LEGACY_CAPABILITY_ALIASES.values())`.
- Add a one-line forward-reference comment in `models.py` near `LEGACY_CAPABILITY_ALIASES` saying "Phase 33+ owns daemon payload migration; until then normalize at read time."

### Risk: LOW

---

## Plan 04: Airweave Mapping Documentation

### Summary
Documentation-only plan. Mandates field-by-field mapping, closed status vocabulary (copied/adapted/rejected/deferred), runtime-boundary section, and grep-verified absence of Airweave imports.

### Strengths
- Mandatory concept list prevents cherry-picking.
- Status values are closed (`copied`, `adapted`, `rejected`, `deferred`).
- "Every mapping table row must have a non-empty `Reason` cell" is explicit.
- Runtime boundary section pre-emptively answers the "where does Phase 33 start" question.

### Concerns
- **LOW - README handling is conditional but `files_modified` does not reflect that.** The header still implies README will be modified; the task body says "skip README rather than creating a noisy doc index." Inconsistent for autonomous agents. Acceptance criterion `If README.md is modified, it contains ...` is conditional, which is correct, but `files_modified` is misleading.
- **LOW - No verification that capability-flag semantics (MATERIALIZATION, FEDERATED_SEARCH) are documented in the mapping doc.** Plan 02's capability semantics are still under-defined; Plan 04 is the natural place to clarify them, but no acceptance criterion requires it.
- **LOW - Stronger Airweave-runtime forbidden-pattern grep.** The verification includes `rg -n "from airweave|import airweave"` and a separate `rg -n "supports_browse_tree|output_entity_definitions|class_name|feature_flag"` for runtime-identifier copy. Good. Could add `rate_limit_level`, `requires_byoc` for completeness.

### Suggestions
- Move `README.md` out of the `files_modified` header; make it conditional in the task body only, or add `(if applicable)` next to it.
- Add an acceptance criterion that the mapping doc defines what `MATERIALIZATION` and `FEDERATED_SEARCH` mean for dotMD specifically - addresses the Plan 02 semantic gap.
- Extend the forbidden-identifier grep to include `rate_limit_level` and `requires_byoc`.

### Risk: LOW

---

## Cross-Plan Concerns

- **MEDIUM - Capability semantics drift across plans.** Plan 02 advertises `MATERIALIZATION` (filesystem) and `FEDERATED_SEARCH` (Telegram) without defining what they mean for dotMD specifically. Plan 04 is the natural home for those definitions but does not require them. Recommend adding a row to the mapping doc for every `SourceCapability` value that explains what dotMD takes the flag to mean.
- **LOW - Two `source_registry.py` modules.** Cycle 1 flagged this; not addressed in cycle 2. Renaming or merging is a low-cost fix.
- **LOW - `ConfigDict(extra="forbid")` not grep-enforced per-new-model.** Existing `models.py` content satisfies the grep regardless of whether new descriptor sub-models include it.

---

## Overall Risk Assessment: **LOW**

Cycle 1's two HIGH concerns (filesystem field requiredness; capability string mismatch) are both explicitly resolved with testable, grep-verifiable acceptance criteria. The remaining concerns are MEDIUM/LOW cosmetic, semantic-clarity, or style-enforcement issues that do not block execution. The phase remains additive, declarative, and runtime-neutral.

---

## Current HIGH Concerns

None.
