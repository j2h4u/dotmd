# Phase 33: Source lifecycle/config/auth/cursor boundary - Research

**Researched:** 2026-05-08
**Status:** Complete

## Research Question

What does the planner need to know to build the Airweave-lite source
lifecycle/factory boundary for dotMD, while preserving the source-ref-first
public contract, retained-artifact visibility model, and existing filesystem
and Telegram behavior?

## Current dotMD Surfaces

### Phase 32 registry foundation

Phase 32 created the declarative pieces Phase 33 should consume:

- `backend/src/dotmd/core/models.py` defines `SourceDescriptor`,
  `SourceCapability`, `SourceConfigSchema`, `SourceAuthSchema`, and
  `SourceCursorSchema`.
- `backend/src/dotmd/core/source_registry.py` defines the copy-safe in-memory
  `SourceRegistry`.
- `backend/src/dotmd/ingestion/source_registry.py` seeds `filesystem` and
  `telegram` descriptors through `default_source_registry()`.
- Descriptors are declarative only. They do not construct providers, read
  credentials, or write checkpoints.

Phase 33 should not replace this registry. It should add the lifecycle layer
that consumes descriptors and local runtime config.

### Existing direct construction paths

Live source checks show the runtime construction paths Phase 33 must route
through lifecycle:

- `backend/src/dotmd/ingestion/pipeline.py` constructs
  `FilesystemMarkdownSourceAdapter()` directly in `_discover_documents()`,
  `_discover_documents_multi()`, and `_source_document_for_file_info()`.
- `backend/src/dotmd/api/service.py` constructs the Telegram provider directly
  in `_build_telegram_provider()` from `settings.telegram_daemon_socket`.
- `backend/src/dotmd/cli.py` constructs `UnixSocketTelegramSourceClient` and
  `TelegramApplicationSourceProvider` directly in `dotmd telegram ingest`.
- `backend/src/dotmd/ingestion/pipeline.py` reads and commits source
  checkpoints directly through `SQLiteMetadataStore` inside
  `ingest_application_source()`.

These are the integration points for Phase 33. The plan should prove the
lifecycle boundary is live, not a test-only wrapper.

### Cursor/checkpoint behavior

The existing checkpoint safety rule is already implemented:

- `SQLiteMetadataStore.commit_source_checkpoint()` requires a caller-owned
  transaction connection.
- `IndexingPipeline.ingest_application_source()` commits source documents,
  resource bindings, source-unit fingerprints, chunks, FTS rows, vector rows,
  and source checkpoint in one local transaction.
- `tests/storage/test_metadata_m2m.py::TestSourceCheckpointState` proves
  checkpoint writes roll back with the caller transaction.
- Telegram ingest tests prove repeated replay and edited-message behavior.

Phase 33 should preserve this behavior while moving checkpoint access behind a
small cursor-store interface used by lifecycle-mediated runtimes. Do not loosen
the rule by allowing cursor commits outside the local persistence transaction.

### Config and credentials

Current config is split:

- Filesystem runtime config comes from deployment settings: configured source
  roots and exclude patterns.
- Telegram runtime config comes from `DOTMD_TELEGRAM_DAEMON_SOCKET`.
- Filesystem has no explicit source credential.
- Telegram auth remains delegated to `mcp-telegram`; dotMD must not become a
  Telegram API client or raw Telegram session store.

Phase 33 needs a local typed source config store and a credential/auth provider
interface. The provider can be minimal for current sources:

- `filesystem`: no-auth provider, no secret material.
- `telegram`: delegated credential/access provider that proves the adapter gets
  access through lifecycle, not by reading raw secret storage.

The local config store may hold typed values and credential references. It must
not become a raw secret store.

## Airweave Reference Findings

The useful Airweave lifecycle concepts are in:

- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/sources/lifecycle.py`
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/sources/protocols.py`
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/sources/types.py`
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/sources/token_providers/protocol.py`

Airweave's `SourceLifecycleService.create()` is valuable as a construction
boundary: it loads source connection data, resolves registry entries, resolves
auth, builds runtime helpers, parses typed config, creates a source instance,
and validates credentials before use.

dotMD should adapt only the construction-boundary idea:

- Keep one source runtime factory/lifecycle service.
- Inject local dependencies instead of using module-level locators.
- Parse typed source config before construction.
- Provide credential/auth access through an interface.
- Provide cursor/checkpoint state through a small cursor store.
- Return an inspectable bundle, not only the provider object.

dotMD should not copy Airweave organizations, collections, billing, Temporal
workers, source connection database model, marketplace decorators, or
Airweave runtime imports.

## Recommended Phase Shape

### Lifecycle module

Add a compact dotMD lifecycle module near ingestion runtime code, for example:

`backend/src/dotmd/ingestion/source_lifecycle.py`

Recommended types:

- `FilesystemSourceConfig(paths: list[str], exclude: list[str])`
- `TelegramSourceConfig(socket_path: Path | None = None)`
- `SourceCredentialRef(namespace: str, credential_ref: str | None = None)`
- `SourceAccess(kind: Literal["none", "delegated"], delegated_to: str | None = None)`
- `SourceConfigStoreProtocol.get_config(namespace: str) -> BaseModel`
- `SourceCredentialProviderProtocol.get_access(descriptor, credential_ref) -> SourceAccess`
- `SourceCursorStoreProtocol.get_checkpoint(namespace)`, `commit_checkpoint(...)`,
  and `record_error(...)`
- `SourceRuntimeBundle` with descriptor, config, access, cursor_store,
  provider/source object, and small helpers.
- `SourceRuntimeFactory.build(namespace)` and
  `SourceRuntimeFactory.build_if_configured(namespace)`.

The exact names are agent discretion, but the boundary must be inspectable and
typed. Tests should assert that missing required config or delegated access
fails before a runtime is returned.

### Filesystem migration

Route existing filesystem construction through the lifecycle:

- Build the filesystem runtime from `default_source_registry()`.
- Use typed settings-derived config for `paths` and `exclude`.
- Return the existing `FilesystemMarkdownSourceAdapter` as the runtime source.
- Replace direct `FilesystemMarkdownSourceAdapter()` calls in the pipeline
  with lifecycle runtime construction.
- Keep filesystem refs as `filesystem:<resolved_path>` and paths as internal
  holder mechanics only.

Filesystem still does not have provider-owned cursor commits. Fingerprint and
change state can be represented as lifecycle metadata/helpers without claiming
incremental provider cursor semantics.

### Telegram migration

Route Telegram provider construction through lifecycle:

- Build the Telegram runtime from the descriptor and typed config.
- Construct `UnixSocketTelegramSourceClient` and
  `TelegramApplicationSourceProvider` inside the lifecycle factory.
- Keep auth delegated to `mcp-telegram`; do not add raw Telegram credentials or
  direct Telegram API clients.
- Update `DotMDService._build_telegram_provider()` and `dotmd telegram ingest`
  to use lifecycle.
- Move checkpoint read/commit/error access in application-source ingest behind
  a cursor-store interface while preserving caller-owned transaction behavior.

`build_if_configured("telegram")` may return `None` when no Telegram socket is
configured for optional service startup. Direct `build("telegram")` should fail
fast if required runtime config is missing.

## Validation Architecture

Phase 33 should be verified with targeted automated checks:

1. Lifecycle contract tests prove runtime bundles are inspectable, descriptor
   driven, typed-config driven, and fail fast on missing config/credential
   references.
2. Filesystem regression tests prove `IndexingPipeline` discovers documents
   through lifecycle while preserving resolved filesystem refs and internal
   holder paths.
3. Telegram regression tests prove service and CLI provider construction use
   lifecycle, preserve `mcp-telegram` delegation, and do not read raw secret
   storage or private Telegram SQLite tables.
4. Cursor rollback tests prove lifecycle-mediated cursor commits still happen
   only inside the local persistence transaction.
5. Static checks prove no Airweave imports and no direct Telegram API clients
   are introduced.

Recommended commands:

- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q`
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/storage/test_metadata_m2m.py -q`
- `cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py`
- `rg -n "from airweave|import airweave|Telethon|telegram\\.client|sqlite.*telegram" backend/src backend/tests`

## Source Audit

| Source | Item | Planning implication |
|--------|------|----------------------|
| GOAL | Build lifecycle service from registry, config, credentials, cursor state, helpers | Plan a concrete lifecycle/factory module and integration tasks. |
| REQ | LIFE-01 | Runtime construction must use registry descriptor, typed config, credential access, and cursor state. |
| REQ | LIFE-02 | Credentials must be accessed through provider interface; adapters must not read raw secret storage. |
| REQ | LIFE-03 | Cursor commits must remain after successful local persistence only. |
| REQ | LIFE-04 | Filesystem and Telegram construction paths must use lifecycle. |
| CONTEXT | D-01 to D-03 | Use Airweave-lite construction boundary, not Airweave platform runtime. |
| CONTEXT | D-04 to D-06 | Return inspectable runtime bundles, not bare objects. |
| CONTEXT | D-07 to D-10 | Config store and credential provider are distinct; fail fast on invalid runtime config. |
| CONTEXT | D-11 to D-13 | Preserve checkpoint cursor semantics; filesystem does not pretend to own provider cursors. |
| CONTEXT | D-14 to D-16 | Route real filesystem and Telegram paths; preserve source-ref-first identity. |

## RESEARCH COMPLETE
