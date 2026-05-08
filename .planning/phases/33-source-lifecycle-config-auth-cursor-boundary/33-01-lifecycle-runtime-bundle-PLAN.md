---
phase: "33"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/tests/ingestion/test_source_lifecycle.py
  - backend/tests/storage/test_metadata_m2m.py
autonomous: true
requirements: ["LIFE-01", "LIFE-02", "LIFE-03"]
requirements_addressed: ["LIFE-01", "LIFE-02", "LIFE-03"]
must_haves:
  truths:
    - "D-01: Use Airweave as an architecture reference, not as a runtime dependency."
    - "D-02: Implement an Airweave-lite lifecycle/factory boundary."
    - "D-03: Keep source descriptor plus typed config, credential/auth provider, cursor state, runtime helper/client wiring, and one construction boundary per source runtime."
    - "D-04: Lifecycle returns a full minimal runtime bundle, not a bare provider/source object."
    - "D-05: Bundle includes descriptor, typed config, credential/auth access, cursor store/state, provider/source object, and helpers where useful."
    - "D-06: Keep the runtime bundle inspectable for future planning, tests, and debugging; do not hide config, cursor, or credential boundaries entirely inside provider objects."
    - "D-07: Source config belongs in a local source config store; descriptors do not hold runtime config or credential material."
    - "D-08: The local config store may hold typed config values and credential references; it must not become a raw secret store."
    - "D-09: Adapters access credentials through a credential/auth provider interface."
    - "D-10: Runtime construction fails fast on missing or invalid required config/credential references."
    - "D-11: checkpoint_cursor is durable progress; next_cursor is only provider continuation hint."
    - "D-12: Cursor/checkpoint commits happen only after local persistence and indexing transaction work succeeds."
---

# Phase 33 Plan 01: Lifecycle Runtime Bundle Contract

<objective>
Create the typed lifecycle/factory contract that builds inspectable source
runtime bundles from registry descriptors, local source config, credential
access, and cursor state without integrating call sites yet.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Lifecycle becomes an Airweave runtime copy | HIGH | Add tests and static checks that `source_lifecycle.py` imports no Airweave modules and uses dotMD descriptors. |
| Local source config stores raw secrets | HIGH | Model config records separately from `SourceCredentialRef`; tests assert config payloads contain typed config and refs only. |
| Adapters can bypass credential provider | HIGH | Runtime bundle includes a `SourceCredentialProviderProtocol` access result; factory tests assert credential provider is called for Telegram. |
| Missing runtime config creates partially valid runtimes | HIGH | `SourceRuntimeFactory.build(namespace)` raises `SourceLifecycleConfigError` for missing filesystem paths or missing Telegram socket. |
| Cursor commits escape the local transaction | HIGH | `SourceCursorStore.commit_checkpoint()` requires `conn=` and delegates to `SQLiteMetadataStore.commit_source_checkpoint()` without committing. |
| Runtime bundle hides debugging state | MEDIUM | Bundle exposes descriptor, typed config, access result, cursor store, source/provider object, and metadata helpers. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add lifecycle contract tests first</name>
<title>Add lifecycle contract tests first</title>
<read_first>
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-RESEARCH.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-PATTERNS.md`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/source_registry.py`
- `backend/src/dotmd/ingestion/source_registry.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/storage/metadata.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_lifecycle.py`
</files>
<action>
Create `backend/tests/ingestion/test_source_lifecycle.py` with failing tests for
the lifecycle contract.

Concrete tests:
- `test_filesystem_runtime_bundle_contains_descriptor_config_access_and_source`
  builds a factory from `default_source_registry()`, a local config store with
  `FilesystemSourceConfig(paths=[str(tmp_path)], exclude=[".git"])`, a no-op
  credential provider, and a cursor store fixture. Assert:
  - `bundle.descriptor.namespace == "filesystem"`
  - `bundle.config.paths == [str(tmp_path)]`
  - `bundle.access.kind == "none"`
  - `bundle.source` is a `FilesystemMarkdownSourceAdapter`
  - `bundle.provider is None`
  - `bundle.cursor_store is cursor_store`
- `test_telegram_runtime_bundle_uses_delegated_access_and_provider` builds a
  Telegram runtime with `TelegramSourceConfig(socket_path=tmp_path / "daemon.sock")`
  and a fake client factory. Assert:
  - credential provider was called with descriptor namespace `telegram`
  - `bundle.access.kind == "delegated"`
  - `bundle.access.delegated_to == "mcp-telegram"`
  - `bundle.provider` is a `TelegramApplicationSourceProvider`
  - `bundle.source is None`
- `test_build_fails_fast_when_required_filesystem_paths_missing` asserts direct
  `factory.build("filesystem")` raises `SourceLifecycleConfigError` containing
  `filesystem.paths`.
- `test_build_fails_fast_when_telegram_socket_missing` asserts direct
  `factory.build("telegram")` raises `SourceLifecycleConfigError` containing
  `telegram.socket_path`.
- `test_build_if_configured_returns_none_for_optional_telegram_without_socket`
  asserts optional service startup can call `build_if_configured("telegram")`
  and receive `None` when no Telegram socket is configured.
- `test_source_config_store_keeps_credential_refs_separate_from_config` asserts
  the local config record has `credential_ref` separate from the typed config
  model and does not expose any `secret`, `token`, or `password` config fields.
- `test_source_cursor_store_requires_transaction_for_commit` asserts
  `SourceCursorStore.commit_checkpoint("telegram", "checkpoint:1")` without
  `conn=` raises `TypeError`, and committing with a transaction rolls back when
  the caller rolls back.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_filesystem_runtime_bundle_contains_descriptor_config_access_and_source`.
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_telegram_runtime_bundle_uses_delegated_access_and_provider`.
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_source_cursor_store_requires_transaction_for_commit`.
- Tests reference `SourceLifecycleConfigError`.
- Tests reference `build_if_configured("telegram")`.
- Tests fail before task 2 and exit 0 after task 2 with `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py -q` fails before task 2 because lifecycle symbols do not exist yet.
</verify>
<done>
Lifecycle contract tests are present and fail for missing implementation only.
</done>
</task>

<task id="2" type="tdd">
<name>Implement lifecycle factory, config store, credential provider, and cursor store</name>
<title>Implement lifecycle factory, config store, credential provider, and cursor store</title>
<read_first>
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/source_registry.py`
- `backend/src/dotmd/ingestion/source_registry.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/storage/metadata.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Add `backend/src/dotmd/ingestion/source_lifecycle.py` with the compact
Airweave-lite dotMD lifecycle boundary.

Concrete target state:
- Define `SourceLifecycleConfigError(ValueError)`.
- Define strict Pydantic config models:
  - `FilesystemSourceConfig(paths: list[str], exclude: list[str] = Field(default_factory=list))`
  - `TelegramSourceConfig(socket_path: Path | None = None)`
- Define `SourceCredentialRef(namespace: str, credential_ref: str | None = None)`
  as a strict model separate from runtime config.
- Define `SourceAccess(BaseModel)` with:
  - `kind: Literal["none", "delegated"]`
  - `delegated_to: str | None = None`
  - no raw token/password/secret fields.
- Define `SourceConfigRecord(BaseModel)` with:
  - `namespace: str`
  - `config: FilesystemSourceConfig | TelegramSourceConfig`
  - `credential_ref: SourceCredentialRef = Field(default_factory=...)`
- Define protocols:
  - `SourceConfigStoreProtocol.get_config(namespace: str) -> SourceConfigRecord | None`
  - `SourceCredentialProviderProtocol.get_access(descriptor: SourceDescriptor, credential_ref: SourceCredentialRef) -> SourceAccess`
  - `SourceCursorStoreProtocol.get_checkpoint(namespace: str) -> dict[str, object] | None`
  - `SourceCursorStoreProtocol.commit_checkpoint(namespace: str, checkpoint_cursor: str | None, *, conn: Any, metadata_json: dict | None = None) -> None`
  - `SourceCursorStoreProtocol.record_error(namespace: str, error: str, *, conn: Any | None = None) -> None`
- Define `InMemorySourceConfigStore` with `set_config(record)` and `get_config(namespace)`.
- Define `DefaultSourceCredentialProvider`:
  - filesystem descriptors return `SourceAccess(kind="none")`.
  - delegated descriptors return `SourceAccess(kind="delegated", delegated_to=descriptor.auth_schema.delegated_to)`.
  - delegated descriptors with no `delegated_to` raise `SourceLifecycleConfigError`.
  - direct/raw secret access is not implemented.
- Define `SQLiteSourceCursorStore` wrapping `SQLiteMetadataStore`:
  - `get_checkpoint()` delegates to `get_source_checkpoint()`.
  - `commit_checkpoint()` delegates to `commit_source_checkpoint(..., conn=conn, metadata_json=...)`; it must not call `commit()`.
  - `record_error()` delegates to `record_source_checkpoint_error()`.
- Define `SourceRuntimeBundle` with:
  - `descriptor: SourceDescriptor`
  - `config: FilesystemSourceConfig | TelegramSourceConfig`
  - `access: SourceAccess`
  - `cursor_store: SourceCursorStoreProtocol`
  - `source: FilesystemMarkdownSourceAdapter | None = None`
  - `provider: ApplicationSourceProviderProtocol | None = None`
  - `metadata_json: dict[str, object] = Field(default_factory=dict)`
- Define `SourceRuntimeFactory` with constructor dependencies:
  - `registry: SourceRegistry`
  - `config_store: SourceConfigStoreProtocol`
  - `credential_provider: SourceCredentialProviderProtocol`
  - `cursor_store: SourceCursorStoreProtocol`
  - optional `telegram_client_factory: Callable[[Path], TelegramSourceClientProtocol]`
- `build("filesystem")`:
  - requires `FilesystemSourceConfig.paths` to be non-empty.
  - returns a bundle with `FilesystemMarkdownSourceAdapter()`.
- `build("telegram")`:
  - requires `TelegramSourceConfig.socket_path is not None`.
  - gets delegated access through credential provider.
  - constructs `UnixSocketTelegramSourceClient(socket_path)` through the client factory.
  - wraps it in `TelegramApplicationSourceProvider`.
- `build_if_configured("telegram")`:
  - returns `None` when no Telegram config or no socket path exists.
  - otherwise returns `build("telegram")`.
- Do not import Airweave.
- Do not import Telethon or any direct Telegram API client.
- Do not read SQLite tables from `mcp-telegram`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `class SourceRuntimeBundle`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `class SourceRuntimeFactory`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `class DefaultSourceCredentialProvider`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `class SQLiteSourceCursorStore`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `def build_if_configured`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `FilesystemMarkdownSourceAdapter`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `TelegramApplicationSourceProvider`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` does not contain `airweave`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` does not contain `Telethon`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` does not contain `password` or `secret`.
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py -q`
`cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py`
`rg -n "from airweave|import airweave|Telethon|telegram\\.client|sqlite.*telegram" backend/src/dotmd/ingestion/source_lifecycle.py backend/tests/ingestion/test_source_lifecycle.py` returns no matches.
</verify>
<done>
Lifecycle bundle construction, typed config storage, delegated credential access, and transaction-owned cursor storage are implemented and verified.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py -q`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py tests/ingestion/test_source_lifecycle.py tests/storage/test_metadata_m2m.py`
- `rg -n "from airweave|import airweave|Telethon|telegram\\.client|sqlite.*telegram" backend/src/dotmd/ingestion/source_lifecycle.py backend/tests/ingestion/test_source_lifecycle.py`
</verification>

<success_criteria>
- LIFE-01 has an importable lifecycle factory and runtime bundle contract.
- LIFE-02 has credential/auth provider access with no raw secret store.
- LIFE-03 has a cursor store wrapper that preserves transaction-owned commits.
- No filesystem or Telegram call sites are migrated yet; Plans 02 and 03 own integration.
</success_criteria>
