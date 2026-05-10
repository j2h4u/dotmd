# Phase 37: Airweave connector compatibility spike - Context

**Gathered:** 2026-05-11
**Status:** Ready for planning

<domain>
## Phase Boundary

Prove that dotMD can wrap any Airweave `BaseSource` connector as a **federated
search provider** using Gmail as the test subject — without local indexing,
without embedding, and without adopting Airweave's Vespa/Temporal/billing stack.

Concretely, this phase delivers:
1. A generic `AirweaveConnectorBridge` that wraps any `BaseSource.search()`
   and converts `BaseEntity` output to dotMD `SearchCandidate` objects.
2. Gmail registered in dotMD's source registry with `FEDERATED_SEARCH`
   capability; `GmailSource.search()` powering live query-time search.
3. Real OAuth credentials for the personal Gmail inbox, wired through the
   `source_lifecycle` credential-provider boundary.
4. `read_unit_window` implementation so `read(ref)` resolves Gmail message refs.
5. `docs/airweave-compatibility.md` — structured analysis of what's reusable
   directly from Airweave, what requires shims, and what to avoid (AIR-02).

This phase is NOT ingesting Gmail into the local SQLite/FTS5/vector index, NOT
defining `SourceAsset`, NOT building a connector marketplace, and NOT a
Gmail-specific hard-coded integration (the bridge must generalize).

</domain>

<decisions>
## Implementation Decisions

### Pilot Connector

- **D-01:** The pilot connector is **Gmail** (`GmailSource` from Airweave's
  platform layer). Entities: `GmailThreadEntity` (thread = SourceDocument
  identity anchor), `GmailMessageEntity` (message = SourceUnit / search unit),
  `GmailAttachmentEntity` (→ SourceAsset, deferred — see D-11).

### Spike Architecture: Federated Search, Not Local Indexing

- **D-02:** Gmail participates as a **federated search provider** only —
  no embedding, no FTS5, no graph, no trickle. The pattern mirrors Telegram
  native FTS (Phase 36 SEARCH-04): `DotMDService.search()` queries Gmail live
  at request time via `GmailSource.search(query)`, converts results to
  `SearchCandidate`, and fuses them with local results.

- **D-03:** The bridge must be **generic across all `BaseSource` subclasses**,
  not Gmail-specific. Gmail is the test subject; the architecture should
  make adding a second Airweave connector (e.g., Notion, GitHub) a
  configuration exercise, not a new integration.

### Airweave Dependency

- **D-04:** Prefer **vendoring**: copy
  `airweave/platform/sources/`, `airweave/platform/entities/`,
  `airweave/platform/configs/`, and the minimal supporting modules into a
  vendored subtree inside dotMD's backend (e.g.,
  `backend/src/dotmd/vendor/airweave/`). No `pip install airweave` as a
  declared dependency.

  **Exception:** If the researcher confirms the Airweave package installs
  without Temporal, Vespa, or other heavy optional dependencies (i.e., only
  `httpx`, `pydantic`, `tenacity`-level deps), pip install is acceptable.
  Researcher must check `pyproject.toml` dependency footprint and report.

### Auth / Credential Wiring

- **D-05:** Google OAuth credentials are created as part of this spike:
  - Google Cloud project with Gmail API enabled
  - OAuth 2.0 client (type: Desktop or Web, `OAuthType.WITH_REFRESH`)
  - Initial OAuth flow run once to obtain refresh token
  - Credentials stored in `~/.secrets/dotmd-gmail.env` (consistent with
    server secrets convention: `~/.secrets/`)

- **D-06:** Airweave's `BaseSource.create()` needs `SourceAuthProvider`,
  `ContextualLogger`, and `AirweaveHttpClient`. These are Airweave-internal
  DI types. The bridge must provide **shim implementations** that fulfill
  these protocols without depending on Airweave's full DI framework. Planner:
  check whether these are Protocol-typed (structural subtyping) or class-based
  (requires inheritance).

- **D-07:** The Gmail credential provider goes through dotMD's
  `SourceRuntimeFactory` / `CredentialProviderProtocol` boundary (Phase 33).
  Do NOT read raw secret files inside the source adapter.

### Generic Bridge Shape

- **D-08:** The bridge converts any `BaseEntity` → `SearchCandidate` using
  the common fields shared across all Airweave entities:
  - `entity_id` / `name` → `SearchCandidate.ref` (namespace:entity_id)
  - `textual_representation` → `snippet`
  - `updated_at` → candidate recency signal
  - `breadcrumbs` → provenance / title hierarchy
  Source-specific fields (e.g., Gmail `thread_id`, `sender`) go into
  `metadata_json`.

- **D-09:** The bridge also exposes `read_unit_window` so `read(ref)` works
  for Gmail refs. For Gmail: fetch the full message body from the Gmail API
  using the `message_id` from the ref. Content returned as a `SourceUnitWindow`.

### Registry & Lifecycle

- **D-10:** Gmail registers in `source_registry.py` as a new
  `SourceDescriptor` with namespace `"gmail"`, capabilities:
  `[FEDERATED_SEARCH, READ_UNIT_WINDOW]`. No `LOCAL_SYNC` or
  `INCREMENTAL_CURSOR` for the spike — federated only.

- **D-10b:** Construction goes through `SourceRuntimeFactory.build("gmail")`
  per AIR-03. No direct `GmailSource()` instantiation outside lifecycle.

### SourceAsset

- **D-11:** `SourceAsset` is **deferred**. `GmailAttachmentEntity` maps
  to a future `SourceAsset` shape that dotMD does not have yet. The
  AIR-02 report documents this mapping and notes it as a future addition.
  No `SourceAsset` model is added to `models.py` in this phase.

### AIR-02 Compatibility Report

- **D-12:** The compatibility analysis is written to
  `docs/airweave-compatibility.md`. It must answer:
  1. **Reusable directly** — Airweave source/entity definitions, entity
     field conventions (`AirweaveField`, `is_entity_id`, `is_name`), cursor
     pattern.
  2. **Requires shims** — `SourceAuthProvider`, `ContextualLogger`,
     `AirweaveHttpClient` DI types; `@source` decorator (may need a minimal
     reimplementation); deletion entity (`GmailMessageDeletionEntity` →
     dotMD's binding deactivation).
  3. **Should be avoided** — Airweave's indexing pipeline, Vespa/Temporal
     runtime, `AirweaveSystemMetadata` (embedding, chunk_index, sync_id —
     dotMD has its own), `FileService`, `AccessControl` (dotMD is
     single-user), `supports_access_control`.

### Claude's Discretion

- Exact module path for the vendored Airweave subtree (suggested:
  `backend/src/dotmd/vendor/airweave/` or `backend/src/dotmd/ingestion/airweave/`).
- Whether the shim for `ContextualLogger` and `AirweaveHttpClient` is a
  minimal dataclass or a thin wrapper around dotMD's existing logger and `httpx`.
- Whether the Gmail descriptor config schema reuses `TelegramSourceConfig`
  patterns (TOML/env fields) or invents its own.
- Whether `dotmd status` should surface last-federated-search stats for Gmail.
- Search result limit for live Gmail queries (suggest default 10, configurable).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Definition

- `.planning/ROADMAP.md` — Phase 37 goal, requirements AIR-01, AIR-02,
  AIR-03, success criteria (one pilot connector mapped, AIR-02 report,
  same registry/lifecycle contracts as filesystem and Telegram).
- `.planning/REQUIREMENTS.md` — AIR-01 through AIR-03 v1.6 compatibility
  requirements. Read exact requirement text before planning.
- `.planning/STATE.md` — current workflow state and milestone progress.

### Prior Architecture Decisions

- `.planning/phases/36-telegram-unified-sync-and-federated-search/36-CONTEXT.md`
  — D-02 (Telegram auto-polling task pattern), federated search via
  `search_native`. Gmail federated search follows the same lifecycle and
  search-path pattern as Telegram.
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
  — `SearchCandidate` contract shape, federated score fusion, `can_read`
  semantics. Gmail `SearchCandidate` must conform to this contract.
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
  — `SourceRuntimeFactory`, `CredentialProviderProtocol`, lifecycle bundle.
  Gmail construction goes through this boundary (D-10b).
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md`
  — `SourceDescriptor` structure, capability flags, namespace lookup.
  Gmail descriptor must register here.

### Airweave Reference Repo

- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/gmail.py`
  — `GmailSource` class: `generate_entities()`, `search()`, cursor handling,
  auth dependency injection. Primary reference for the bridge.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/entities/gmail.py`
  — `GmailThreadEntity`, `GmailMessageEntity`, `GmailAttachmentEntity`,
  `GmailMessageDeletionEntity`. Shows which fields map to dotMD contracts.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py`
  — `BaseSource` contract: `create()`, `generate_entities()`, `search()`,
  `validate()`. The generic bridge wraps this interface.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/entities/_base.py`
  — `BaseEntity`, `Breadcrumb`, `AirweaveSystemMetadata`. Shows common fields
  available on every entity for the generic bridge (D-08).
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/decorators.py`
  — `@source` decorator. Researcher: determine if it's needed or can be
  bypassed in the vendored subtree.

### Current Code Surfaces

- `backend/src/dotmd/ingestion/source_registry.py` — `SourceDescriptor`,
  `default_source_registry()`. Gmail descriptor is added here (D-10).
- `backend/src/dotmd/ingestion/source_lifecycle.py` — `SourceRuntimeFactory`,
  `SourceRuntimeBundle`, `CredentialProviderProtocol`. Gmail construction
  path (D-07, D-10b).
- `backend/src/dotmd/ingestion/telegram_provider.py` — `search_native()`
  returns `SearchCandidate` objects. This is the exact pattern to follow
  for the Gmail bridge's search method.
- `backend/src/dotmd/core/models.py` — `SearchCandidate`, `SourceCapability`,
  `SourceDescriptor`. Gmail bridge output shape must conform to these.
- `backend/src/dotmd/api/service.py` — `DotMDService._build_federated_bundles()`,
  federated search fan-out. Gmail provider plugs in here.
- `backend/src/dotmd/mcp_server.py` — `_server_lifespan`. If Gmail source
  needs any startup initialization, it wires in here.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `TelegramApplicationSourceProvider` in `telegram_provider.py` — `search_native()`
  method is the direct pattern for the Gmail bridge's federated search path.
  Copy the `SearchCandidate` construction idiom.
- `SourceRuntimeFactory.build("telegram")` — shows how to wire a new source
  through the lifecycle factory with config, credentials, and cursor state.
  Gmail follows the same construction path.
- `DotMDService._build_federated_bundles()` — already fans out to multiple
  federated providers. Gmail registers here without changing the fan-out logic.
- `ApplicationSourceDescription.from_descriptor()` — already converts
  `SourceDescriptor` to a description shape. Gmail descriptor will auto-work.
- `mcp_server.py` `_server_lifespan` / `indexer_task` — lifecycle pattern
  for background tasks. If Gmail needs any connection warm-up, mirror this.

### Established Patterns

- **No direct instantiation outside lifecycle**: `SourceRuntimeFactory` is
  the single construction point for all sources. Gmail is no exception.
- **Federated search score fusion**: `SearchCandidate` includes
  `source_native_score`; dotMD's fusion layer handles heterogeneous scores
  without pretending they're directly comparable. Gmail scores are
  Gmail-API-native relevance values.
- **D-LOCAL-SERIALIZED**: All SQLite writes run on `_local_executor`. Gmail
  federated search does not write to SQLite (pure read path at query time),
  so this constraint is not triggered.
- **Credential provider boundary**: Adapters do not read raw `.env` files.
  Credentials come in through `CredentialProviderProtocol`.

### Integration Points

- `source_registry.py` — add `gmail_source_descriptor()` and register in
  `default_source_registry()`.
- `source_lifecycle.py` — add `GmailSourceConfig` (TOML/env fields: OAuth
  client_id, client_secret, refresh_token) and wire into
  `SourceRuntimeFactory.build("gmail")`.
- `telegram_provider.py` — pattern reference for `search_native()` →
  `SearchCandidate`. New file `gmail_provider.py` mirrors this structure.
- `api/service.py` — `_build_federated_bundles()` picks up Gmail provider
  when `DOTMD_GMAIL_*` env vars are set.
- `docs/` — new file `airweave-compatibility.md` (AIR-02 deliverable).

### Anti-Patterns To Avoid

- Do not add `GmailSource()` instantiation outside `source_lifecycle.py`.
- Do not import `airweave` as a top-level pip dependency without confirming
  there are no Temporal/Vespa/heavy transitive deps.
- Do not make the bridge Gmail-specific — every method that touches Gmail
  entity types should be a generic `BaseEntity` operation with Gmail-specific
  bits isolated to the descriptor/config only.
- Do not use `AirweaveSystemMetadata` fields (embedding, chunk_index, sync_id)
  — dotMD has its own equivalents and they are not compatible.

</code_context>

<specifics>
## Specific Ideas

- The user's stated intent is to support **any** Airweave connector in dotMD
  going forward. Gmail is the first test. The generic bridge is the real
  deliverable; the AIR-02 report validates whether the generic approach holds.
- The bridge should make adding a second Airweave connector (e.g., Notion,
  GitHub) a configuration + descriptor exercise without new bridge code.
- Airweave vendoring preferred: copy `platform/sources/`, `platform/entities/`,
  `platform/configs/` only. The researcher should check whether the `@source`
  decorator and `AirweaveField` are self-contained or pull in Airweave's
  full DI machinery.
- Google OAuth credentials go in `~/.secrets/dotmd-gmail.env` (server
  convention). OAuth flow can be run interactively once to obtain the refresh
  token; subsequent runs use the stored refresh token.

</specifics>

<deferred>
## Deferred Ideas

- **`SourceAsset` model** — `GmailAttachmentEntity` maps to a `SourceAsset`
  shape. Defined in AIR-02 as future work; no `models.py` change in this phase.
- **Local Gmail indexing** — ingesting Gmail threads into the local
  SQLite/FTS5/vector store. Out of scope for the spike; could be a future
  phase once the bridge is validated.
- **`GmailMessageDeletionEntity` handling** — deletion signals from Gmail's
  History API. dotMD handles deletions through binding deactivation, not a
  deletion entity type. Document in AIR-02 as a shim required; implement
  in a follow-on phase.
- **Multi-connector runtime** — supporting multiple simultaneous Airweave
  connectors (Gmail + Notion + GitHub) in one dotMD instance. The architecture
  should enable this but Phase 37 only validates one.
- **Connector config UI** — no admin UI for adding new Airweave connectors.
  Config stays env/TOML-based.
- **Access control** — Airweave's `AccessControl` model is multi-tenant. dotMD
  is single-user; ACL enforcement is explicitly out of scope.

### Reviewed Todos (not folded)

- All matched todos (FalkorDB migration, trickle indexer, soft-delete TTL,
  pplx eval, fork scouting, smoke tests) — none are related to Airweave
  connector compatibility. All deferred.

</deferred>

---

*Phase: 37-airweave-connector-compatibility-spike*
*Context gathered: 2026-05-11*
