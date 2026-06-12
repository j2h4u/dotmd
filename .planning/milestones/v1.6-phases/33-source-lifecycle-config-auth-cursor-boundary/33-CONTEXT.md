# Phase 33: Source lifecycle/config/auth/cursor boundary - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Build the lifecycle service/factory that constructs source runtimes from Phase
32 registry entries, typed local source config, credential references, cursor
state, and runtime helpers.

This phase proves the boundary with the existing filesystem and Telegram
construction paths. It is not a connector marketplace, not a broad SaaS
platform runtime, not a full OAuth UI, not federated search, and not the
Phase 34-37 connector compatibility work.

</domain>

<decisions>
## Implementation Decisions

### Airweave-Lite Runtime Boundary

- **D-01:** Use Airweave as an architecture reference for source runtime
  construction, not as a schema, platform, or runtime dependency.
- **D-02:** Phase 33 should implement an **Airweave-lite runtime bundle**:
  a compact dotMD lifecycle/factory boundary that assembles the pieces needed
  to run a source without importing Airweave's marketplace, organizations,
  billing, Temporal workers, or connector framework.
- **D-03:** The high-ROI Airweave ideas to keep are: source descriptor plus
  typed config, credential/auth provider, cursor state, runtime helper/client
  wiring, and one construction boundary per source runtime.

### Runtime Bundle Shape

- **D-04:** The lifecycle/factory should return a full minimal runtime bundle,
  not only a bare provider/source object.
- **D-05:** The bundle should include at least: `SourceDescriptor`, typed
  source config, credential/auth provider access, cursor store/state, the
  provider/source object, and small runtime helpers such as logger/client
  wiring where useful.
- **D-06:** Keep the bundle inspectable enough for future planning, tests, and
  debugging. Hiding config, cursor, or credential boundaries entirely inside a
  provider object would reduce short-term code but make Phases 34-37 harder.

### Config And Credential Ownership

- **D-07:** Source config belongs in a local source config store. Descriptors
  remain declarative; they describe config/auth/cursor schemas but do not hold
  per-source runtime config or credential material.
- **D-08:** The local source config store may hold typed config values and
  credential references. It must not become a raw secret store.
- **D-09:** Source adapters/providers must access credentials through a
  credential/auth provider interface. They must not read raw secret storage
  directly.
- **D-10:** Runtime construction should fail fast: if required source config or
  required credential references are missing or invalid, lifecycle must not
  create a runtime.

### Cursor And Checkpoint Semantics

- **D-11:** Carry forward the Phase 28 rule unchanged:
  `checkpoint_cursor` is durable progress, while `next_cursor` is only a
  provider continuation hint.
- **D-12:** Cursor/checkpoint commits happen only after local persistence and
  indexing transaction work succeeds. This applies to Telegram provider
  checkpoints and any lifecycle-mediated source with durable cursor state.
- **D-13:** Filesystem does not pretend to have provider-owned cursor commits.
  Its lifecycle path should still represent filesystem fingerprint/change state
  through the same runtime vocabulary where useful.

### Filesystem And Telegram Migration Path

- **D-14:** Phase 33 must route both filesystem and Telegram construction paths
  through the lifecycle/factory boundary. The phase should not stop at test-only
  shims or a dead architecture layer.
- **D-15:** Telegram remains delegated to `mcp-telegram`. dotMD lifecycle may
  build the Telegram runtime and client wrapper, but dotMD must not become a
  direct Telegram API client.
- **D-16:** Filesystem paths remain internal holder mechanics for discovery,
  reads, delete detection, parser routing, and content-addressed reuse. The
  lifecycle migration must not turn paths back into public source identity.

### the agent's Discretion

- Choose exact Python class names, module placement, and bundle model names as
  long as they follow the existing Pydantic/Protocol style and keep the
  descriptor/lifecycle boundary clean.
- Choose the concrete local config persistence shape, but keep it typed,
  inspectable, and distinct from raw secret storage.
- Choose the smallest credential provider interface that supports current
  filesystem/no-auth and Telegram/delegated-auth needs while leaving room for
  future SaaS credentials.
- Choose whether filesystem fingerprint state is represented as cursor-store
  state, runtime metadata, or a filesystem-specific lifecycle helper, as long
  as it does not claim provider-owned checkpoint semantics.
- No pending todos were folded into Phase 33 context. Low-confidence matches
  for graph/config and soft-delete TTL were reviewed and left out of scope.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone And Phase Definition

- `.planning/ROADMAP.md` - Phase 33 goal, dependency on Phase 32, requirement
  mapping, and success criteria.
- `.planning/REQUIREMENTS.md` - LIFE-01 through LIFE-04 and v1.6 source
  lifecycle requirements.
- `.planning/PROJECT.md` - Source architecture decisions, especially
  `checkpoint_cursor` durability and source-ref boundary decisions.
- `.planning/STATE.md` - Current workflow state and next-step routing.

### Prior Source Architecture Decisions

- `.planning/phases/32-source-capability-registry/32-CONTEXT.md` - Descriptor
  stays declarative; lifecycle owns runtime construction, credentials, cursor
  state, and provider factory wiring.
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md` -
  Minimal provider contract, `export_changes`, source-unit boundary, and
  checkpoint cursor semantics.
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md` -
  Telegram message refs, `mcp-telegram` boundary, and low-signal message
  handling.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
  - Active binding as public visibility gate; retained artifacts are for reuse.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  - Public source-ref-first contract and no-full-reindex guardrail.

### Architecture Notes

- `docs/source-registry-airweave-mapping.md` - Airweave-to-dotMD mapping and
  the explicit Phase 33 runtime boundary.
- `docs/source-adapter-architecture.md` - Current source/document/unit model
  and future source architecture direction.
- `docs/source-adapter-architecture-panel-review.md` - Prior expert-panel
  recommendations on source APIs, cursor commits, credential isolation, and
  adapter boundaries.
- `docs/mcp-telegram-source-contract.md` - Telegram provider payloads,
  `checkpoint_cursor` vs `next_cursor`, and unit-window semantics.
- `docs/architecture.md` - Current architecture summary and Phase 27-28 source
  lifecycle/provider notes.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py` - `SourceDescriptor`,
  `SourceCapability`, source schema models, `ApplicationSourceDescription`,
  `ApplicationSourceChangeBatch`, `SourceDocument`, and `SourceUnit`.
- `backend/src/dotmd/core/source_registry.py` - In-memory descriptor registry
  container from Phase 32.
- `backend/src/dotmd/ingestion/source_registry.py` - Filesystem and Telegram
  descriptor seeds and `default_source_registry()`.
- `backend/src/dotmd/ingestion/source_provider.py` - Current application source
  provider protocol.
- `backend/src/dotmd/ingestion/source.py` - Current filesystem source adapter
  and filesystem document-ref bridge.
- `backend/src/dotmd/ingestion/telegram_provider.py` - Telegram provider and
  UNIX socket client wrapper around `mcp-telegram`.
- `backend/src/dotmd/ingestion/pipeline.py` - Existing application-source
  ingestion, filesystem discovery/indexing, and checkpoint commit transaction
  behavior.
- `backend/src/dotmd/storage/metadata.py` - Source checkpoints, source-unit
  fingerprints, source documents, resource bindings, and provenance storage.

### Airweave Reference

- `/home/j2h4u/repos/airweave-ai/airweave` - Local Airweave checkout used as
  architecture reference material only. Planning may inspect source lifecycle
  and connector construction patterns, but must adapt them into dotMD's local
  single-user source-ref model.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceDescriptor` and schema models already provide the declarative source
  metadata that lifecycle should consume.
- `SourceRegistry` plus `default_source_registry()` already provide filesystem
  and Telegram descriptor lookup by namespace.
- `ApplicationSourceProviderProtocol` already defines the provider shape for
  Telegram-like application sources.
- `FilesystemMarkdownSourceAdapter` already provides the filesystem discovery
  object that lifecycle can wrap.
- `TelegramApplicationSourceProvider` and `UnixSocketTelegramSourceClient`
  already provide the delegated Telegram runtime pieces lifecycle can assemble.
- `SQLiteMetadataStore.commit_source_checkpoint()` already enforces
  caller-owned transaction semantics for checkpoint writes.

### Established Patterns

- dotMD prefers small Protocol/Pydantic boundaries over broad plugin
  frameworks.
- Public behavior flows through `DotMDService`, CLI, MCP, and FastAPI; storage
  internals should not become public integration APIs.
- Descriptors are declarative; runtime construction belongs outside descriptor
  definitions.
- Source refs are the public identity. Filesystem paths remain internal holder
  mechanics.
- Migrations/backfills should be idempotent, countable, and avoid full reindex.

### Integration Points

- A lifecycle module should connect the Phase 32 registry to existing
  filesystem and Telegram construction code.
- The local source config store and credential provider boundary need to be
  consumable by the lifecycle/factory without leaking raw secrets into
  descriptors or providers.
- `IndexingPipeline.ingest_application_source_batch()` already demonstrates
  checkpoint-after-transaction semantics that lifecycle should preserve rather
  than replace.
- Filesystem discovery/indexing methods in `IndexingPipeline` are the main
  existing path that must route through lifecycle without changing public
  filesystem search/read behavior.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly asked for the "retro-optimal" / maximum-ROI use of the
  prior reference project. The selected answer is Airweave-lite: keep the
  source lifecycle/factory pattern and discard platform-heavy concepts.
- Phase 33 should produce working construction paths, not only an architecture
  sketch. Filesystem and Telegram both need to use lifecycle in this phase.

</specifics>

<deferred>
## Deferred Ideas

- Full connector marketplace remains deferred.
- Production OAuth UI for arbitrary SaaS apps remains deferred.
- Rate-limit framework and broad SaaS runtime policy remain deferred unless a
  concrete source needs them later.
- Federated `SearchCandidate` implementation remains Phase 34.
- Full filesystem source unification remains Phase 35.
- Telegram unified sync/federated migration remains Phase 36.
- Airweave connector compatibility spike remains Phase 37.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` - Not folded;
  matched only the generic `config` keyword and belongs outside Phase 33.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` - Not folded;
  removed-source TTL/GC policy remains a separate lifecycle cleanup topic.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` - Not
  folded; matched only the generic `config` keyword and is unrelated to source
  lifecycle construction.

</deferred>

---

*Phase: 33-Source lifecycle/config/auth/cursor boundary*
*Context gathered: 2026-05-08*
