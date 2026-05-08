---
phase: 32
reviewers: [claude, opencode]
reviewed_at: 2026-05-08T17:47:16+05:00
plans_reviewed:
  - 32-01-source-descriptor-contract-PLAN.md
  - 32-02-filesystem-telegram-registry-seeds-PLAN.md
  - 32-03-provider-description-compatibility-PLAN.md
  - 32-04-airweave-mapping-docs-PLAN.md
cycle: 1
current_high: 2
---

# Cross-AI Plan Review — Phase 32

## Cycle Summary

CYCLE_SUMMARY: current_high=2

## Current HIGH Concerns

- Plan 02 does not specify or test the filesystem config schema field types and requiredness, especially `paths` required and `exclude` optional, despite the existing filesystem adapter contract.
- Plan 03 leaves a capability string mismatch between the new registry enum values (`read_unit_window`, `incremental_cursor`) and the live Telegram daemon payload strings (`unit-window`, `incremental-export`) without a concrete normalization or migration plan.

## Consensus Summary

### Agreed Strengths

- The phase is appropriately scoped as additive, declarative registry work with no runtime lifecycle construction, credential access, or Airweave dependency.
- The TDD structure is sound: model contract first, seed descriptors and compatibility bridge next, documentation last.
- Both reviewers found the source-provider boundary largely correct, especially keeping Telegram behind `mcp-telegram` and preserving the existing `ApplicationSourceProviderProtocol` surface.
- Both reviewers liked the closed capability vocabulary and strict Pydantic model direction as a guard against descriptor drift.

### Agreed Concerns

- Capability semantics need tightening before execution. Both reviewers called out ambiguity around Telegram `federated_search`; both also flagged the broader risk of registry capability values drifting away from live provider payloads.
- Plan 01 should explicitly require `Field(default_factory=...)` for collection/dict defaults and make strict Pydantic validation grep-able in the plan.
- Descriptor schema field typing is under-specified. Both reviewers accepted a lightweight Phase 32 shape, but recommended documenting or constraining valid `field_type` values so Phase 33 does not inherit arbitrary strings.
- Filesystem cursor/materialization semantics are ambiguous enough to create downstream confusion unless Phase 32 clarifies whether these describe current implementation, source model capability, or future lifecycle behavior.
- The optional README/doc placement guidance in Plan 04 should be made less ambiguous for autonomous execution.

### Divergent Views

- Claude treated the capability-string mismatch as a medium maintainability risk because the bridge is small and fenced; OpenCode classified it as HIGH because live daemon payload strings already differ from the planned enum values and future comparisons could fail.
- Claude considered filesystem materialization semantically odd and possibly unnecessary; OpenCode accepted it as reasonable but emphasized that cursor/config details need stronger tests.
- Claude recommended avoiding two modules named `source_registry.py`; OpenCode viewed the split between core model contract and ingestion seed registry as a clean boundary.

### Recommended Replan Focus

- Resolve the two HIGH findings explicitly in the Phase 32 plans before execution.
- Add concrete acceptance criteria for capability vocabulary normalization or migration ownership.
- Strengthen Plan 02 tests for schema field type and requiredness.
- Tighten Plan 01 style requirements for mutable defaults and strict Pydantic models.

---

## Claude Review

# Cross-AI Plan Review: Phase 32 — Source Capability Registry

## Plan 01: Source Descriptor Contract

### Summary
Solid TDD plan that establishes the typed descriptor vocabulary with a closed `SourceCapability` enum, strict Pydantic models, and an immutable registry container. Tests-first ordering and grep-able acceptance criteria are well-suited for autonomous execution. The main weaknesses are Python-level: mutable defaults on Pydantic fields and an under-specified module organization that creates a `source_registry.py` filename collision with Plan 02.

### Strengths
- Closed `StrEnum` for capabilities + explicit `extra="forbid"` test prevents the very drift the threat model calls out.
- `model_copy(deep=True)` on every read prevents accidental registry mutation by callers.
- Acceptance criteria use grep-able invariants (`does not contain "airweave"`, `does not contain "TokenProvider"`) so a downstream agent can self-verify without judgment calls.
- Threat model and tasks are explicitly aligned (each threat has a corresponding test).

### Concerns
- **MEDIUM — Mutable defaults on Pydantic fields.** The model definitions use `labels: list[str] = []`, `metadata_json: dict = {}`, `fields: list[SourceSchemaField] = []`, `examples: list[str] = []`. Pydantic v2 deep-copies these on each instance, so this is not the classic Python footgun, but it's still discouraged style and `ruff` (`B006`) will flag it. Plan should mandate `Field(default_factory=list)` / `Field(default_factory=dict)` to match the codebase's strict-model conventions.
- **MEDIUM — Filename collision risk.** Plan 01 creates `backend/src/dotmd/core/source_registry.py` and Plan 02 creates `backend/src/dotmd/ingestion/source_registry.py`. Two modules with the same basename make import lines harder to read at a glance and increase the chance of editing the wrong one. Consider renaming one (e.g., `core/source_registry.py` → `core/source_registry_types.py` or move the `SourceRegistry` container into `ingestion/source_registry.py` since that's where seeds live).
- **MEDIUM — `ConfigDict(extra="forbid")` is implied but not mandated.** PATTERNS.md calls out the `extra="forbid"` convention, but Plan 01's task 2 does not explicitly require it on each new model — only the test indirectly enforces it via `test_source_descriptor_forbids_extra_fields`. Make it an explicit acceptance criterion (`backend/src/dotmd/core/models.py contains 'extra="forbid"'` for the new descriptor models).
- **LOW — Test placement.** Tests for `core` types live under `tests/ingestion/test_source_registry.py`. The descriptor models are core-level; tests for them would be more discoverable under `tests/core/`. Seed tests can stay under `tests/ingestion/`.
- **LOW — `SourceSchemaField.field_type: str`.** Using a free-form string for a type name (rather than an enum or Python-typed reference) means Phase 33 will have to interpret these strings to instantiate runtimes. Trade-off is acceptable to keep the descriptor lightweight, but worth a one-liner in the threat model acknowledging that Phase 33 is responsible for validating field_type values.

### Suggestions
- Add explicit `Field(default_factory=...)` requirement for every collection/dict default.
- Rename `core/source_registry.py` → `core/source_registry_container.py`, OR collapse the container into `ingestion/source_registry.py`.
- Add `extra="forbid"` as an explicit grep-able acceptance criterion.
- Move type-level tests to `tests/core/test_source_registry.py`; keep seed tests in `tests/ingestion/`.

### Risk Assessment: **LOW**
Surface is small, additive, declarative, and unit-tested. No runtime impact, no migration. Worst case is Phase 33 finds the descriptor too thin and asks for additions — easy to evolve.

---

## Plan 02: Filesystem And Telegram Registry Seeds

### Summary
Detailed seed entries with exact field assertions. The plan correctly keeps Telegram delegated to `mcp-telegram` and resists pulling Telegram API ownership into dotMD. The capability assignments deserve scrutiny: `materialization` on filesystem is semantically questionable, and `federated_search` on Telegram conflates "provider supports it natively" with "dotMD can route through it" — a distinction Phase 34 will need.

### Strengths
- Both seeds populate config/auth/cursor schemas with real fields, not placeholders — meets D-10's "detailed reference entries" mandate.
- Telegram auth is explicitly `delegated` to `mcp-telegram`, with a grep-able acceptance criterion.
- Negative assertions (`acl` not in Telegram caps) prevent overclaiming.
- Forbidden-import grep checks (no `Telethon`, no `airweave`) close off the "creep into runtime" failure mode.

### Concerns
- **MEDIUM — `MATERIALIZATION` capability on filesystem is semantically odd.** Materialization in Airweave/connector vocabulary typically means "make a remote artifact available as a local readable byte stream." For a filesystem source, the artifact is already local — the capability is trivially true and adds no information. Either drop it for filesystem, or define materialization more precisely in the descriptor docs (e.g., "this source can produce on-demand bytes for a unit ref"). Otherwise downstream phases will read different meanings into it.
- **MEDIUM — `FEDERATED_SEARCH` capability on Telegram conflates two things.** The flag suggests Telegram supports federated search, but Phase 34 is what implements the SearchCandidate pipeline. As declared today, the flag answers "does the *provider* expose native search?" rather than "is dotMD wired to consume it?". When Phase 34 lands, the same flag can mean "dotMD can route this source through the federated path." Today the flag is aspirational. Add a note in the descriptor docs distinguishing "provider-supported" from "dotMD-implemented," or split into two capabilities.
- **MEDIUM — Default-registry test is hedged.** `test_default_registry_contains_filesystem_and_telegram` says "exactly the filesystem and telegram namespaces ... unless implementation also includes test fixtures explicitly marked non-default." That escape hatch undercuts the test. Either the default registry has exactly those two namespaces in Phase 32, or the contract is open. Recommend hard assertion: `set(ns for d in default_source_registry().list()) == {"filesystem", "telegram"}`.
- **LOW — `metadata_json` carries semi-structured filesystem fields.** `media_type: "text/markdown"` and `parser_name: "markdown"` go into `metadata_json` rather than typed descriptor fields. This is fine for Phase 32 but worth noting: if Phase 33 needs these, they'll be reading a `dict[str, Any]`. Consider whether `parser_name` should be a first-class descriptor field (it appears already on `FilesystemMarkdownSourceAdapter`).
- **LOW — Cursor schema mismatch between test and implementation.** Test asserts `cursor_kind == "fingerprint"` for filesystem; implementation says `cursor_kind: "fingerprint"`. Telegram test asserts only the example string is present; implementation has `cursor_kind: "provider_checkpoint"`. The Telegram test should probably also assert `cursor_kind`.

### Suggestions
- Drop `MATERIALIZATION` from filesystem caps (or define it precisely and document why local files have it).
- Split `FEDERATED_SEARCH` into `PROVIDER_FEDERATED_SEARCH` (provider exposes it) vs `DOTMD_FEDERATED_SEARCH` (dotMD routes it), OR document the dual meaning explicitly.
- Tighten the default-registry test to a hard set equality.
- Add cursor_kind assertion to the Telegram seed test.
- Consider promoting `parser_name` and `media_type` to typed descriptor fields rather than metadata_json keys.

### Risk Assessment: **LOW–MEDIUM**
Capability semantics will affect Phase 33 and Phase 34. Locking ambiguous flags now creates rework risk later. The materialization/federated_search definitions should be tightened in this phase, not deferred.

---

## Plan 03: Provider Description Compatibility

### Summary
Necessary glue plan that prevents the new descriptor from breaking the live Telegram daemon payload. Preserves `ApplicationSourceProviderProtocol` unchanged and adds an explicit one-way bridge from descriptor to legacy description. The capability string mismatch between the new closed enum (`local_sync`, `incremental_cursor`) and the legacy daemon payload (`incremental-export`, `unit-window`) is acknowledged through coexistence but no migration path is defined.

### Strengths
- No runtime protocol change — Phase 33 and the live daemon are not pressured into rework.
- Bridge is one-way (descriptor → description), avoiding the temptation to read legacy payloads back into the new enum.
- Explicit grep checks that `describe_source(self) -> ApplicationSourceDescription` is preserved in both the protocol and Telegram provider.

### Concerns
- **MEDIUM — Capability string drift is left coexisting indefinitely.** The new enum produces `local_sync`, `read_unit_window`, `incremental_cursor`. The legacy Telegram daemon payload sends `incremental-export`, `unit-window`. The bridge does not normalize the legacy strings to the new vocabulary, and no future-phase task is queued for it. Consumers will see two parallel taxonomies. At minimum, add a TODO/ticket reference (or a Phase 33+ requirement) so the daemon payload migrates eventually.
- **LOW — "Copy display metadata into metadata_json if useful" is vague.** Either the bridge does it or it doesn't. Vague acceptance criteria in autonomous plans tend to produce inconsistent agent decisions. Pick one.
- **LOW — `from_descriptor` placement.** Putting it on `ApplicationSourceDescription` as a classmethod is fine but couples the legacy model to the new one. A free function `source_descriptor_to_application_description()` is more reversible. Plan offers both; it should pick one.

### Suggestions
- Define a concrete capability-string normalization plan: either the bridge translates legacy strings ↔ new enum values, or a Phase 33 task migrates the daemon payload. Don't leave both vocabularies alive forever.
- Decide whether `descriptor_display` is copied into `metadata_json` — yes or no.
- Pick free function vs classmethod for the bridge and stick with it.

### Risk Assessment: **LOW**
Bridge code is small and well-fenced. The unresolved capability-string duality is a slow-burn maintainability concern, not a correctness or security issue.

---

## Plan 04: Airweave Mapping Documentation

### Summary
Documentation-only plan with concrete required tables, classifications, and forbidden-import checks. Discharges D-13/D-14/D-15 cleanly. Light on edge cases because docs don't have many; the small concerns are about scope creep into README and a slightly weak verification surface for "no runtime dependency."

### Strengths
- Mandates exact set of Airweave concepts to map — prevents an agent from cherry-picking the easy ones.
- Status vocabulary is closed (`copied`/`adapted`/`rejected`/`deferred`).
- Explicit "Runtime Boundary" section addresses Phase 33 ownership question that would otherwise come up in every later phase.

### Concerns
- **LOW — README modification is hedged.** `files_modified` lists `README.md`, but the task body says "skip README rather than creating a noisy doc index." If the intent is "modify only if there's already an architecture section," remove README from `files_modified` and put the conditional logic into the acceptance criteria.
- **LOW — `from airweave|import airweave` grep is weak verification.** Airweave isn't pip-installed; the import would fail anyway. The real risk is the agent vendoring Airweave code or copying decorators into dotMD. A stronger check would also grep for `class_name`, `output_entity_definitions`, `feature_flag` (Airweave-specific identifiers) appearing in `backend/src/`.
- **LOW — `supported_auth_providers` and `feature_flag` are listed as required mapping rows but their dotMD equivalents are unclear.** If they map to "rejected" or "deferred," the table should still have a non-empty Reason column — make sure the agent doesn't leave Reason blank.

### Suggestions
- Drop `README.md` from `files_modified` if the README change is conditional.
- Add a stronger forbidden-pattern grep: e.g., `rg -n "supports_browse_tree|output_entity_definitions|class_name" backend/src` returns no matches (these are Airweave-specific identifiers).
- Add an acceptance criterion that every row in the mapping table has a non-empty `Reason` cell.

### Risk Assessment: **LOW**
Docs-only, no runtime impact. Worst case is the table is incomplete and Phase 37 has to redo mapping work — recoverable.

---

## Cross-Plan Concerns

- **MEDIUM — Threat IDs `T-32-01` through `T-32-06` referenced in `32-VALIDATION.md` are not defined in any plan's threat model.** The plans use unlabeled threat tables. Either add IDs to plan threat tables matching the validation doc, or remove the IDs from validation. Right now the traceability column is dead text.
- **MEDIUM — No explicit Phase 33 consumability test.** Phase 32 produces descriptors that Phase 33 must consume. There is no skeletal test in this phase that mocks lifecycle consumption (e.g., "given a descriptor, lifecycle can read auth_schema.auth_kind and pick a credential provider strategy"). Adding one cheap test would catch design gaps before Phase 33 starts and avoid descriptor rework.
- **LOW — No CLI/MCP exposure of the registry.** `dotmd sources list` would be a natural debug surface and a sanity check that the registry actually lives in a publicly accessible place. Plan 04 could add this as a deferred follow-up rather than ignore it.
- **LOW — Pydantic v2 model_dump round-trip is untested.** If Phase 34's SearchCandidate or any MCP tool ever serializes a descriptor, round-trip should work. Adding `model_dump_json() → model_validate_json()` to one test would future-proof for free.

---

## Overall Risk Assessment: **LOW–MEDIUM**

The phase is intentionally additive, declarative, and code-only with no production runtime change. TDD ordering and grep-able acceptance criteria are well-suited for autonomous execution. The headline risks are:

1. **Capability semantics** (`materialization` on filesystem, `federated_search` as a hybrid flag) — should be tightened *now*, not in Phase 33.
2. **Mutable defaults and pydantic style** — needs an explicit acceptance criterion before plan 01 ships.
3. **Filename collision** between two `source_registry.py` files — easy to fix before execution.
4. **Capability string drift** between new enum and legacy daemon payload — needs a migration owner (Phase 33+) or it will calcify.

None of these are blockers. With the above tightenings, Phase 32 is ready to execute autonomously.

---

## OpenCode Review

Let me verify key code surfaces the plans reference before reviewing.
Now I have a thorough understanding of the existing code. Here's my review:

---

# Phase 32 Plan Review: Source Capability Registry

## Plan 01: Source Descriptor Contract

### Summary

Clean TDD plan that introduces the `SourceCapability` enum and typed descriptor models. The scope is well-bounded to declarative models only, with an explicit boundary against Phase 33 lifecycle concerns. The two-task structure (tests first, then models) is sound.

### Strengths

- **Threat model is precise and actionable** — each threat maps to a concrete mitigation in the tests (e.g., reject unknown capability values, forbid extra fields).
- **Closed enum with explicit values** — directly addresses D-07/D-08 and prevents capability drift.
- **`extra="forbid"` on all models** — matches existing `SourceDocument`, `ApplicationSourceDescription` patterns (`core/models.py:84,119,150,167,179`).
- **`model_copy(deep=True)`** for registry immutability — prevents caller mutation leaking into registry state.
- **No Airweave import, no credential, no runtime construction** — acceptance criteria explicitly grep for these.

### Concerns

- **MEDIUM — `SourceSchemaField.field_type: str` is untyped**. A `field_type: str` that should represent `"str"`, `"int"`, `"list[str]"`, etc. is effectively a stringly-typed type system. For Phase 32 (declarative only) this is acceptable, but the plan should note that Phase 33 lifecycle will need to either validate these strings against real Python types or the field should use a `JsonSchemaType` enum. If left as `str`, future phases risk "made-up" type strings the same way D-07 prevents made-up capability strings.
- **MEDIUM — `SourceDisplayMetadata.labels: list[str] = []` uses mutable default**. Pydantic handles this correctly via `Field(default_factory=list)`, but the plan writes `labels: list[str] = []`. The actual implementation must use `Field(default_factory=list)` to match the existing pattern (`models.py:78,97,131`).
- **LOW — No `__contains__` or iteration on `SourceRegistry`**. The plan specifies `register`, `get`, `require`, `list` but callers (and tests in Plans 02/03) will need `"filesystem" in registry`-style checks. Not a blocker, but `require` throwing `KeyError` or a custom error should be specified.
- **LOW — Plan puts models in `core/models.py`** which is already 328 lines. Adding 6+ new models will push it toward 400+. This is fine for now but worth noting for future refactoring.

### Suggestions

- Specify that `require(namespace)` raises `KeyError(namespace)` or a domain-specific error, so Plan 02 tests can assert on the exception type.
- Clarify that `SourceSchemaField.field_type` values should be drawn from a known set (e.g., `"str"`, `"int"`, `"bool"`, `"list[str]"`, `"path"`) and that Phase 33 may tighten this.

### Risk: LOW

The plan is narrowly scoped, well-gated by tests, and has no runtime dependencies. The main risk is the stringly-typed `field_type`, which is a design debt rather than an execution risk.

---

## Plan 02: Filesystem And Telegram Registry Seeds

### Summary

Seeds the registry with detailed filesystem and Telegram descriptors. The TDD wave structure (test the seeds, then implement) is correct. The descriptors are carefully grounded in existing code constants (`namespace = "filesystem"`, `media_type = "text/markdown"`, etc.).

### Strengths

- **Exact capability assertions** — filesystem gets `local_sync`, `materialization`, `browse_tree` and NOT `incremental_cursor` (correct: filesystem uses fingerprints, not provider cursors). Telegram gets `incremental_cursor` and `federated_search` but NOT `acl`. This shows deep understanding of the source semantics.
- **Telegram `delegated_to = "mcp-telegram"`** — directly encodes D-12 (Telegram is behind `mcp-telegram`, not a direct API client) and matches the existing `TelegramSourceClientProtocol` boundary at `telegram_provider.py:41`.
- **`metadata_json` includes `media_type` and `parser_name`** for filesystem — matches the existing `FilesystemMarkdownSourceAdapter` class attributes at `source.py:41-43`.
- **New module `ingestion/source_registry.py`** — keeps descriptor *seeds* (which are ingestion-layer concepts) separate from the *model contract* in `core/source_registry.py`. Clean boundary.

### Concerns

- **HIGH — Filesystem config schema has `paths` and `exclude` but no `field_type` or `required` specification in the plan**. The test says "config schema has a `paths` field and an `exclude` field" but doesn't specify whether `paths` is required and `exclude` is optional. Given that the filesystem adapter's `discover_multi` signature is `paths: list[str], exclude: list[str] | None = None` (`source.py:32-33`), `paths` should be required and `exclude` should be optional. The test should assert this.
- **MEDIUM — `cursor_schema.cursor_kind = "fingerprint"` for filesystem is ambiguous**. Filesystem uses content fingerprints and metadata fingerprints (two separate fingerprints per `SourceDocument`), but `cursor_kind` is singular. Is this a composite cursor? The plan should clarify that the filesystem cursor kind describes the *mechanism* (fingerprint-based change detection) rather than a single field, since filesystem doesn't use provider-owned cursors at all.
- **MEDIUM — Telegram descriptor claims `federated_search` capability but Phase 32 doesn't implement federated search**. The plan says "capabilities include... `federated_search`" but D-12 says "future federated search where supported." If the descriptor says a capability exists, Phase 34 will need to implement it. Consider whether Telegram should have `federated_search` now or whether it should be added in Phase 34 when federated search is actually implemented. The CONTEXT says "Telegram registers... federated-search capabilities **where available**" — but it's not available yet. This is a declarative claim that may need a `planned` vs `available` distinction.
- **LOW — `daemon_socket` field name for Telegram config**. The existing implementation uses `socket_path: Path` (`telegram_provider.py:71`). The descriptor uses `daemon_socket`. These should align or the plan should explain the mapping.

### Suggestions

- Assert `required=True` for filesystem `paths` and `required=False` for `exclude` in the test.
- Consider whether `SourceCapability` needs a `planned` qualifier or whether the descriptor should have a separate `planned_capabilities: list[SourceCapability]` field to distinguish "implemented now" from "will be implemented." Alternatively, document clearly that capabilities describe the source *model*, not current dotMD implementation status.
- Align Telegram config field name with existing `socket_path` naming in the codebase, or add a comment explaining the intentional rename.

### Risk: MEDIUM

The `federated_search` capability claim for Telegram is the main concern — it's a forward promise that Phase 34 must honor. The filesystem cursor kind ambiguity could cause confusion in Phase 35. Both are design decisions that should be made now rather than deferred.

---

## Plan 03: Provider Description Compatibility

### Summary

Bridges the new `SourceDescriptor` to the existing `ApplicationSourceDescription` without changing the runtime protocol. This is the most delicate plan because it touches the live provider path — `TelegramApplicationSourceProvider.describe_source()` at `telegram_provider.py:150-151` currently does `ApplicationSourceDescription(**self._client.describe_source())`.

### Strengths

- **Preserves `ApplicationSourceProviderProtocol` return type** — the plan explicitly says "do not change `describe_source()` return type away from `ApplicationSourceDescription`." This is critical since the protocol is used by `pipeline.py` and tested by fixtures.
- **Bridge direction is correct** — `from_descriptor()` converts the richer descriptor to the lighter description, not the other way. This means Phase 33 lifecycle can produce a description from a descriptor without breaking existing code.
- **Capability string normalization** — converting `SourceCapability` enum values to `.value` strings preserves the current `capabilities: list[str]` contract on `ApplicationSourceDescription` (`models.py:184`).

### Concerns

- **HIGH — Capability string mismatch between registry and live daemon payloads**. The Telegram daemon fixture returns `capabilities: ["incremental-export", "unit-window"]` (`test_telegram_provider.py:25`), but the Telegram registry descriptor uses `SourceCapability.READ_UNIT_WINDOW` (value `"read_unit_window"`) and `SourceCapability.INCREMENTAL_CURSOR` (value `"incremental_cursor"`). These strings don't match. The bridge test says "capabilities include normalized string values from the descriptor" but the existing provider test still asserts on the old strings. There's no migration plan for the capability string vocabulary. Either:
  1. The `SourceCapability` enum should use the existing daemon strings (`incremental-export`, `unit-window`), or
  2. The bridge should include a mapping layer, or
  3. The daemon payload contract should be updated separately.
  This is the highest-risk item across all four plans.
- **MEDIUM — `from_descriptor` adds `descriptor_display` to `metadata_json`**. The plan says "it must not flatten typed config/auth/cursor schemas into runtime settings" but then suggests putting display metadata into `metadata_json`. Since `ApplicationSourceDescription` already has `display_name` as a top-level field, adding `descriptor_display` to `metadata_json` is redundant. The bridge should just map `descriptor.display.display_name` to `description.display_name` directly.
- **LOW — No test for filesystem provider description compatibility**. The plan only tests Telegram description compatibility. The filesystem adapter (`FilesystemMarkdownSourceAdapter`) doesn't implement `ApplicationSourceProviderProtocol` (it implements `SourceAdapterProtocol` from `source.py:22`), so there's nothing to bridge. But the plan doesn't call this out explicitly.

### Suggestions

- **Address the capability string mismatch explicitly.** Either:
  - Change `SourceCapability` values to match existing daemon strings (e.g., `INCREMENTAL_EXPORT = "incremental-export"`, `UNIT_WINDOW = "unit-window"`), or
  - Add a normalization mapping in the bridge that converts `SourceCapability.READ_UNIT_WINDOW.value` → `"unit-window"` and `SourceCapability.INCREMENTAL_CURSOR.value` → `"incremental-export"`, or
  - Document that the daemon payload contract will be updated when Phase 36 migrates Telegram execution.
  The first option is cleanest but requires changing the enum values. The second adds bridge complexity. The third is a deferral risk.
- Remove the `descriptor_display` metadata_json suggestion — just map directly.
- Add a note that `FilesystemMarkdownSourceAdapter` uses a different protocol (`SourceAdapterProtocol`) and is not in scope for this bridge.

### Risk: HIGH

The capability string mismatch between registry enum values and live daemon payloads is a real integration bug waiting to happen. If Plan 02 ships `read_unit_window` and the daemon returns `unit-window`, any code comparing them will fail silently (string inequality) or loudly. This must be resolved before execution.

---

## Plan 04: Airweave Mapping Documentation

### Summary

Documentation-only plan that creates an explicit Airweave-to-dotMD mapping table and updates architecture docs. Straightforward and well-scoped.

### Strengths

- **Explicit "no runtime Airweave dependency" statement** — checked via grep in acceptance criteria.
- **Four-status classification** (copied, adapted, rejected, deferred) — matches D-13/D-14 exactly.
- **Comprehensive concept list** — covers all Airweave source schema fields plus Temporal, organizations, billing.
- **Architecture doc update includes Phase 33 boundary** — prevents future confusion about where lifecycle lives.

### Concerns

- **MEDIUM — Plan says "update README.md" but only conditionally**. The acceptance criteria say "if README.md is modified, it contains `source-registry-airweave-mapping.md`." This is fine but the `files_modified` header lists `README.md` unconditionally, which could mislead execution agents into always modifying it.
- **LOW — No review of existing `docs/source-adapter-architecture.md` content**. The plan says to add a Phase 32 section but doesn't specify what the current document contains or where the section should go. The execution agent will need to read the full file to find the right insertion point.

### Suggestions

- Move `README.md` from `files_modified` to a conditional note — only modify if the README already has an architecture section.
- Add a note about where in `docs/source-adapter-architecture.md` the Phase 32 section should be inserted (e.g., "after the existing Phase 29 section").

### Risk: LOW

Documentation-only with grep-based acceptance criteria. Minimal execution risk.

---

## Overall Phase Assessment

### Dependency Graph

```
Plan 01 (models) ──┬── Plan 02 (seeds) ──── Plan 04 (docs)
                    └── Plan 03 (bridge) ── Plan 04 (docs)
```

Waves 1 → 2 → 3 are correct. Plans 02 and 03 can run in parallel (both depend only on Plan 01), which is already reflected in their shared Wave 2 assignment.

### Cross-Plan Issues

1. **Capability string vocabulary mismatch** (Plan 02 vs Plan 03 vs live code) — the `SourceCapability` enum values don't match the existing daemon payload strings. This is the single highest-risk item and should be resolved before any plan executes.
2. **`SourceSchemaField.field_type: str`** (Plan 01) — if this is meant to be consumed by Phase 33 lifecycle, the valid values should be documented now rather than left open.
3. **Filesystem `cursor_kind = "fingerprint"` semantics** (Plan 02) — the word "fingerprint" is overloaded in dotMD (content fingerprint, metadata fingerprint, source unit fingerprint). The cursor kind should be more specific.

### Overall Risk: MEDIUM

The plans are well-structured and the phase boundary is clean. The main risk is the capability string mismatch between the new registry vocabulary and existing live daemon payloads — resolving this before execution will drop overall risk to LOW.
