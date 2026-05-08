---
phase: "32"
plan: "04"
type: execute
wave: 3
depends_on:
  - "32-01"
  - "32-02"
  - "32-03"
files_modified:
  - docs/source-registry-airweave-mapping.md
  - docs/source-adapter-architecture.md
autonomous: true
requirements: ["SRC-04"]
requirements_addressed: ["SRC-04"]
must_haves:
  truths:
    - "D-01: Airweave is an engineering reference for source catalog concepts, not a schema to copy."
    - "D-02: Phase 32 uses useful Airweave categories including source catalog entries, schemas, capabilities, browse tree, federated search, ACL, and incremental sync markers."
    - "D-03: Phase 32 rejects or defers organizations, collections, billing, Temporal orchestration, connector marketplace UI, and Airweave as a runtime dependency."
    - "D-13: Documentation includes an explicit Airweave-to-dotMD mapping table."
    - "D-14: The mapping table classifies each Airweave concept as copied, adapted, rejected, or deferred."
    - "D-15: The mapping explains why dotMD adapts the ideas: local source refs, retained artifacts, typed Pydantic contracts, and no runtime Airweave dependency."
---

# Phase 32 Plan 04: Airweave Mapping Documentation

<objective>
Document how Airweave source metadata maps to the dotMD source descriptor
model, and update architecture docs so future connector work does not reopen
Phase 32 decisions.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| "Inspired by Airweave" turns into vague copying | HIGH | Add a field-by-field mapping table with copied/adapted/rejected/deferred status. |
| Future phases import Airweave runtime by default | HIGH | State that Phase 32 has no runtime Airweave dependency and list avoided subsystems. |
| Docs hide the registry/lifecycle boundary | MEDIUM | Add a clear section saying Phase 33 owns lifecycle construction, credentials, and cursor commits. |
| Public docs expose real private source details | MEDIUM | Use generic filesystem and Telegram examples without real dialog names or personal data. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Create Airweave-to-dotMD mapping document</title>
<read_first>
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md`
- `.planning/phases/32-source-capability-registry/32-RESEARCH.md`
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/schemas/source.py`
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/google_slides.py`
- `docs/source-adapter-architecture.md`
</read_first>
<files>
- `docs/source-registry-airweave-mapping.md`
</files>
<action>
Create `docs/source-registry-airweave-mapping.md`.

Concrete target state:
- Title: `# Source Registry Airweave Mapping`
- Include a short statement: `dotMD has no runtime Airweave dependency`.
- Include a table with columns:
  - `Airweave concept`
  - `dotMD descriptor field`
  - `Status`
  - `Reason`
- The table must include these Airweave concepts:
  - `name`
  - `description`
  - `short_name`
  - `class_name`
  - `auth_methods`
  - `oauth_type`
  - `requires_byoc`
  - `auth_config_class`
  - `auth_fields`
  - `config_class`
  - `config_fields`
  - `supports_continuous`
  - `federated_search`
  - `supports_access_control`
  - `supports_browse_tree`
  - `rate_limit_level`
  - `feature_flag`
  - `output_entity_definitions`
  - `supported_auth_providers`
  - `Temporal orchestration`
  - `organizations/collections/billing`
- Use status values exactly from this set: `copied`, `adapted`, `rejected`, `deferred`.
- Every mapping table row must have a non-empty `Reason` cell.
- Add sections:
  - `## Copied Concepts`
  - `## Adapted Concepts`
  - `## Rejected Concepts`
  - `## Deferred Concepts`
  - `## Runtime Boundary`
- Runtime boundary must state that Phase 33 owns runtime construction,
  credentials, and cursor commit behavior.
</action>
<acceptance_criteria>
- `docs/source-registry-airweave-mapping.md` exists.
- `docs/source-registry-airweave-mapping.md` contains `dotMD has no runtime Airweave dependency`.
- `docs/source-registry-airweave-mapping.md` contains `Temporal orchestration`.
- `docs/source-registry-airweave-mapping.md` contains `organizations/collections/billing`.
- `docs/source-registry-airweave-mapping.md` contains all four words `copied`, `adapted`, `rejected`, and `deferred`.
- `rg -n "from airweave|import airweave" backend/src backend/tests docs/source-registry-airweave-mapping.md` returns no backend runtime imports of Airweave.
- `rg -n "supports_browse_tree|output_entity_definitions|class_name|feature_flag" backend/src backend/tests` returns no Airweave-specific copied runtime identifiers.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Update architecture docs with registry boundary</title>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/mcp-telegram-source-contract.md`
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md`
- `docs/source-registry-airweave-mapping.md`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
</files>
<action>
Update the main source architecture docs after the registry implementation
exists.

Concrete target state:
- Add a `## Phase 32 Planned Source Registry` or equivalent section to
  `docs/source-adapter-architecture.md`.
- The section must state:
  - source descriptors are declarative;
  - registry seeds include filesystem and Telegram;
  - filesystem paths remain internal holder mechanics;
  - Telegram remains behind `mcp-telegram`;
  - lifecycle construction, credential access, and cursor commit mechanics are
    Phase 33 scope;
  - Airweave mapping lives in `docs/source-registry-airweave-mapping.md`.
- Add a concise README pointer only if README already has an architecture/docs
  section; otherwise skip README rather than creating a noisy doc index.
  If README is changed, add it as an extra modified file in the task summary.
</action>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `Phase 32` and `source registry`.
- `docs/source-adapter-architecture.md` contains `docs/source-registry-airweave-mapping.md`.
- `docs/source-adapter-architecture.md` contains `declarative`.
- `docs/source-adapter-architecture.md` contains `mcp-telegram`.
- `docs/source-adapter-architecture.md` contains `Phase 33`.
- If `README.md` is modified, it contains `source-registry-airweave-mapping.md`.
</acceptance_criteria>
</task>
</tasks>

<verification>
- `rg -n "dotMD has no runtime Airweave dependency|copied|adapted|rejected|deferred" docs/source-registry-airweave-mapping.md`
- `rg -n "Phase 32|source registry|Phase 33|mcp-telegram" docs/source-adapter-architecture.md`
- `rg -n "from airweave|import airweave" backend/src backend/tests` returns no matches.
</verification>

<success_criteria>
- SRC-04 is satisfied by an explicit mapping table and runtime-boundary docs.
- Future connector phases can see what was copied, adapted, rejected, and deferred.
- No runtime Airweave dependency is introduced.
</success_criteria>
