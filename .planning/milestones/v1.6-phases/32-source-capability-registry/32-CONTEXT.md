# Phase 32: Source capability registry - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Introduce a dotMD-native source registry and declarative capability model,
seeded with filesystem and Telegram entries.

This phase turns the Airweave-inspired source catalog idea into a compact
dotMD contract: descriptors say what a source is, what it can do, and what
typed config/auth/cursor schemas it exposes. Phase 32 does not construct source
runtimes, read credentials, manage cursor commits, implement federated search,
or migrate filesystem/Telegram execution paths. Those belong to later v1.6
phases.

</domain>

<decisions>
## Implementation Decisions

### Airweave Adaptation Mode

- **D-01:** Use Airweave principles-first, not schema-first. Airweave is an
  engineering reference for source catalog concepts, but dotMD should produce
  a compact native contract shaped around its own `search -> ref -> read/drill`
  workflow, retained artifacts, and single-user/local deployment constraints.
- **D-02:** Phase 32 should take useful engineering categories from Airweave:
  source catalog entries, config schema, auth schema, cursor schema,
  capability flags, browse-tree support, federated-search marker, ACL marker,
  and incremental/continuous sync marker.
- **D-03:** Phase 32 should explicitly reject or defer Airweave SaaS/platform
  concerns that do not belong in the registry: organizations, collections,
  billing, Temporal orchestration, connector marketplace UI, and Airweave as a
  runtime dependency.

### Descriptor Contract

- **D-04:** A source descriptor is declarative only. It describes the source
  kind, display metadata, schemas, and capabilities; it must not instantiate
  providers, open clients, read secrets, or persist cursors.
- **D-05:** Runtime construction, credential access, cursor state ownership,
  and provider factory wiring are Phase 33 lifecycle scope. Planning must keep
  the registry/lifecycle boundary clean.
- **D-06:** Descriptor schemas should be structural Pydantic models, not loose
  untyped dictionaries and not placeholder strings. Even simple schemas should
  have typed shape so Phase 33 can consume them without redefining the contract.

### Capability Vocabulary

- **D-07:** Capability flags should be a closed enum in Phase 32. Downstream
  agents should not invent arbitrary strings during implementation.
- **D-08:** The initial closed capability vocabulary should cover the Phase 32
  success criteria and v1.6 roadmap needs: local sync, federated/native search,
  read-unit windows, materialization, browse trees, ACL support, and
  incremental cursors.
- **D-09:** New capabilities can be added later through explicit model changes,
  but Phase 32 should prefer a small auditable vocabulary over extensibility
  that lets names drift.

### Filesystem And Telegram Seed Entries

- **D-10:** Filesystem and Telegram should be detailed reference entries, not
  nearly empty seeds. Each should populate descriptor metadata, capability
  flags, config schema, auth schema, and cursor schema, even when a schema is
  intentionally empty or minimal.
- **D-11:** The filesystem entry should still acknowledge filesystem-specific
  holder mechanics: local paths remain required internally for discovery,
  reads, delete detection, parser routing, and content-addressed reuse. This
  does not make paths public source identity again.
- **D-12:** The Telegram entry should model Telegram as an application source
  behind `mcp-telegram`, not as a direct Telegram API client in dotMD. It should
  describe sync/export, read-unit windows, incremental cursors, and future
  federated search where supported.

### Airweave Mapping Documentation

- **D-13:** Phase 32 documentation must include an explicit Airweave-to-dotMD
  mapping table for important source schema fields.
- **D-14:** The mapping table should classify each Airweave concept as copied,
  adapted, rejected, or deferred. This is mandatory context for future
  connector compatibility work so "inspired by Airweave" does not become vague
  copying.
- **D-15:** The mapping should explain why dotMD adapts the ideas: local
  source refs, retained artifacts, typed Pydantic contracts, and no runtime
  Airweave dependency.

### the agent's Discretion

- Choose exact Python class names, module placement, and enum names as long as
  they match existing Pydantic/Protocol style and keep the descriptor
  declarative.
- Choose whether schemas are represented as direct Pydantic model classes,
  serializable schema descriptor models, or another typed pattern, as long as
  the result is not an untyped `dict` bag and can support Phase 33 lifecycle.
- Choose the exact display metadata fields for Phase 32, but keep them useful
  to source selection/docs rather than marketplace/product-card bloat.
- Downstream researchers/planners may use Graphify as a codebase navigation
  aid, especially for Phases 33-36 where source lifecycle, pipeline, storage,
  service, filesystem, and Telegram dependencies become more coupled. Graphify
  output is advisory only; all findings must be verified against live source
  files before planning or implementation.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone And Phase Definition

- `.planning/ROADMAP.md` - Phase 32 goal, requirements mapping, Airweave
  reference, dependency on Phase 31, and success criteria.
- `.planning/REQUIREMENTS.md` - v1.6 requirements, especially SRC-01 through
  SRC-04.
- `.planning/PROJECT.md` - Current v1.6 milestone framing, Airweave reference
  boundary, and source architecture goals.
- `.planning/STATE.md` - Current workflow state and milestone routing.

### Prior Source Architecture Decisions

- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
  - Active binding as public visibility gate; retained artifacts are for reuse,
  not public archive browsing.
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md`
  - Minimal provider contract, source-unit boundary, and checkpoint cursor
  semantics.
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md` -
  Telegram dialog/message mapping, message-shaped refs, `mcp-telegram`
  boundary, and low-signal message handling.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  - Public source-ref-first contract and no-full-reindex guardrail.

### Architecture Notes

- `docs/source-adapter-architecture.md` - Current source/document/unit model,
  Phase 27-29 delivered state, future source examples, and open source
  architecture questions.
- `docs/source-adapter-architecture-panel-review.md` - Prior expert-panel
  concerns and recommendations around source contracts, cursors, delete
  semantics, and future connector boundaries.
- `docs/mcp-telegram-source-contract.md` - Concrete Telegram provider boundary
  and message/window payload expectations.
- `docs/architecture.md` - High-level current architecture and source-adapter
  summary.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py` - Existing `SourceDocument`,
  `SourceUnit`, `SourceUnitWindow`, `ApplicationSourceDescription`,
  `ApplicationSourceChangeBatch`, `ResourceBinding`, and `SearchResult`
  models.
- `backend/src/dotmd/ingestion/source_provider.py` - Current application source
  provider protocol that descriptors must not collapse into runtime creation.
- `backend/src/dotmd/ingestion/source.py` - Filesystem source adapter and
  filesystem document-ref mapping.
- `backend/src/dotmd/ingestion/telegram_provider.py` - Telegram provider
  mapping through structured `mcp-telegram` payloads.
- `backend/src/dotmd/ingestion/pipeline.py` - Existing filesystem and
  application-source ingestion integration points.
- `backend/src/dotmd/storage/metadata.py` - Source documents, resource
  bindings, source-unit fingerprints, checkpoints, and provenance storage.
- `.planning/graphs/` and `graphify-out/`, if present - Optional codebase
  graph/navigation outputs. Use only as planning aids; verify against live
  source files.

### Airweave Reference

- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/schemas/source.py`
  - Airweave `Source` schema with source display fields, auth/config schema
  references, continuous sync, federated search, ACL, browse tree, labels, and
  rate-limit metadata.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/google_slides.py`
  - Example Airweave source decorator showing auth methods, config class,
  continuous sync, rate limits, and cursor class.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `ApplicationSourceDescription` already carries `namespace`, `source_kind`,
  `display_name`, `capabilities`, and `metadata_json`; Phase 32 can evolve this
  into or alongside a richer descriptor.
- `SourceDocument`, `SourceUnit`, and `SourceUnitWindow` already define the
  document/unit/window vocabulary that registry capabilities should describe.
- `FilesystemMarkdownSourceAdapter` already exposes filesystem namespace,
  media type, parser name, and canonical document ref behavior.
- `TelegramApplicationSourceProvider` already maps structured
  `mcp-telegram` payloads into dotMD source models.

### Established Patterns

- dotMD prefers small Pydantic models and Protocol boundaries over broad plugin
  frameworks.
- Public behavior flows through `DotMDService`, MCP, CLI, and FastAPI; storage
  internals should not become public integration APIs.
- Source refs are the public contract; filesystem paths remain internal holder
  mechanics.
- Migrations and backfills should be idempotent, countable, and avoid full
  reindex.

### Integration Points

- Registry models likely belong near `core/models.py` or a small adjacent
  source-registry module, with public use routed through service/CLI docs later
  rather than direct storage internals.
- Phase 33 lifecycle should consume registry descriptors to construct
  filesystem and Telegram runtimes, so Phase 32 should leave a clear importable
  boundary.
- Documentation should make the Airweave mapping concrete enough that Phase 37
  connector compatibility can evaluate shims without re-opening Phase 32.

</code_context>

<specifics>
## Specific Ideas

- Use Airweave as borrowed engineering experience: keep the useful categories,
  adapt them to dotMD, and improve where dotMD can keep sharper boundaries.
- The source registry should answer "what is this source and what can it do?"
  not "how do I create and run it?"
- Filesystem and Telegram entries should be examples future source authors can
  copy from, not temporary stubs.

</specifics>

<deferred>
## Deferred Ideas

- Runtime lifecycle/factory construction, credential provider access, and
  cursor commit mechanics remain Phase 33.
- Federated `SearchCandidate` implementation remains Phase 34.
- Filesystem execution-path migration remains Phase 35.
- Telegram unified sync/federated migration remains Phase 36.
- Airweave connector compatibility spike remains Phase 37.
- No pending todos were folded into Phase 32 context.

</deferred>

---

*Phase: 32-Source capability registry*
*Context gathered: 2026-05-08*
