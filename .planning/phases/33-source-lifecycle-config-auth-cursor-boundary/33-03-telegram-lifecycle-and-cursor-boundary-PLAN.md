---
phase: "33"
plan: "03"
type: tdd
wave: 3
depends_on:
  - "33-01"
  - "33-02"
files_modified:
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/cli.py
  - backend/tests/ingestion/test_source_lifecycle.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/api/test_service_search.py
  - backend/tests/storage/test_metadata_m2m.py
  - docs/source-adapter-architecture.md
  - docs/source-registry-airweave-mapping.md
autonomous: true
requirements: ["LIFE-01", "LIFE-02", "LIFE-03", "LIFE-04"]
requirements_addressed: ["LIFE-01", "LIFE-02", "LIFE-03", "LIFE-04"]
must_haves:
  truths:
    - "D-09: Source adapters/providers access credentials through a credential/auth provider interface."
    - "D-11: checkpoint_cursor is durable progress; next_cursor is only a provider continuation hint."
    - "D-12: Cursor/checkpoint commits happen only after local persistence and indexing transaction work succeeds."
    - "D-14: Telegram construction path must route through lifecycle/factory, not stop at test-only shims."
    - "D-15: Telegram remains delegated to mcp-telegram; dotMD must not become a direct Telegram API client."
    - "Phase 29 guardrail: dotMD consumes structured mcp-telegram provider payloads, not private SQLite tables or human-rendered output."
    - "Phase 31 baseline: Telegram refs remain concrete message refs that round-trip through read/drill."
---

# Phase 33 Plan 03: Telegram Lifecycle And Cursor Boundary

<objective>
Route Telegram provider construction and application-source cursor access
through lifecycle while preserving delegated `mcp-telegram` auth, checkpoint
commit safety, and existing Telegram read/drill behavior.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Telegram provider remains a bespoke service/CLI construction path | HIGH | Service and CLI tests assert construction goes through lifecycle factory; static checks reject direct provider construction in those files. |
| dotMD starts owning Telegram credentials or API access | HIGH | Credential provider returns delegated `mcp-telegram` access only; static scan rejects Telethon/direct Telegram client imports/private SQLite access. |
| Cursor commit moves before local persistence | HIGH | Pipeline ingest uses lifecycle cursor store inside the existing transaction; rollback tests prove checkpoint is absent after rollback. |
| Optional Telegram runtime breaks service startup without socket | HIGH | Service uses `build_if_configured("telegram")` and returns `None` when no socket is configured. |
| Lifecycle changes break Telegram message refs/read windows | HIGH | Existing API/service and Telegram ingest tests continue to assert message refs and read/drill windows. |
| Lifecycle docs drift from source-ref-first and retained-artifact decisions | MEDIUM | Architecture docs update Phase 33 lifecycle while preserving Phase 26 and 27 guardrails. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add Telegram lifecycle and cursor boundary regression tests</name>
<title>Add Telegram lifecycle and cursor boundary regression tests</title>
<read_first>
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-RESEARCH.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-PATTERNS.md`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Add failing tests proving Telegram construction and cursor access use lifecycle.

Concrete tests:
- In `test_source_lifecycle.py`, add
  `test_source_runtime_factory_from_settings_seeds_telegram_config_when_socket_configured`:
  build settings with `telegram_daemon_socket=tmp_path / "daemon.sock"` and
  assert the settings helper seeds a `TelegramSourceConfig` with that path.
- In `test_source_lifecycle.py`, add
  `test_telegram_lifecycle_does_not_accept_raw_secret_fields`: attempt to
  create a Telegram config/access payload with `token`, `password`, or `secret`
  and assert Pydantic validation or lifecycle construction rejects it.
- In `test_service_search.py`, add or extend a service construction test so a
  fake lifecycle factory returning a Telegram provider is used by
  `DotMDService._build_telegram_provider()`. Assert no direct socket/provider
  construction is required in service.
- In `test_telegram_ingestion.py`, add
  `test_ingest_application_source_uses_lifecycle_cursor_store_for_checkpoint`:
  create a recording `SQLiteSourceCursorStore`, call the lifecycle-mediated
  ingest path from task 2, and assert `get_checkpoint` and `commit_checkpoint`
  were called with namespace `telegram`.
- In `test_telegram_ingestion.py`, add
  `test_lifecycle_cursor_checkpoint_rolls_back_when_index_transaction_fails`:
  use a provider batch that raises during indexing after source-unit state has
  started, assert the checkpoint row remains absent or unchanged, and assert
  `record_error("telegram", ...)` is written.
- In `test_telegram_provider.py` or `test_source_lifecycle.py`, assert Telegram
  access remains `kind == "delegated"` and `delegated_to == "mcp-telegram"`.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_source_runtime_factory_from_settings_seeds_telegram_config_when_socket_configured`.
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_telegram_lifecycle_does_not_accept_raw_secret_fields`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `test_ingest_application_source_uses_lifecycle_cursor_store_for_checkpoint`.
- `backend/tests/ingestion/test_telegram_ingestion.py` contains `test_lifecycle_cursor_checkpoint_rolls_back_when_index_transaction_fails`.
- A service-level test asserts `_build_telegram_provider()` can receive a lifecycle-built provider.
- Tests fail before task 2 and exit 0 after task 2 with `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` fails before task 2 because Telegram construction and cursor access still bypass lifecycle.
</verify>
<done>
Telegram lifecycle, delegated-auth, service construction, CLI construction, and cursor rollback tests are present.
</done>
</task>

<task id="2" type="tdd">
<name>Route Telegram service, CLI, and checkpoint access through lifecycle</name>
<title>Route Telegram service, CLI, and checkpoint access through lifecycle</title>
<read_first>
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Complete Telegram lifecycle integration.

Concrete target state:
- Extend `source_runtime_factory_from_settings()` from Plan 02 so it seeds:
  - `SourceConfigRecord(namespace="telegram", config=TelegramSourceConfig(socket_path=settings.telegram_daemon_socket), credential_ref=SourceCredentialRef(namespace="telegram", credential_ref="mcp-telegram"))` when `settings.telegram_daemon_socket` is not `None`.
  - No raw token/password/secret fields.
- In `DotMDService.__init__`, reuse the pipeline/source lifecycle factory or
  create an equivalent factory from settings and metadata store. Prefer one
  factory owned by the pipeline if that keeps dependency flow simpler.
- Replace `DotMDService._build_telegram_provider()` direct construction with:
  - `bundle = self._source_runtime_factory.build_if_configured("telegram")`
  - return `None` if the bundle is `None`
  - validate `bundle.provider is not None`
  - return `bundle.provider`
- Replace `dotmd telegram ingest` direct construction with lifecycle:
  - settings still performs the existing socket presence and `is_socket()`
    checks before non-dry-run/dry-run behavior.
  - build the Telegram runtime through lifecycle.
  - use `bundle.provider` for dry-run and ingest.
- Add a lifecycle-mediated ingest entry point in `IndexingPipeline`, for
  example `ingest_application_source_runtime(bundle, limit=limit)`, or change
  `ingest_application_source()` to accept an optional `cursor_store` defaulting
  to the lifecycle cursor store.
- Replace direct checkpoint reads/writes in application-source ingest with
  `SourceCursorStoreProtocol` methods:
  - read: `cursor_store.get_checkpoint(namespace)`
  - success commit: `cursor_store.commit_checkpoint(namespace, batch.checkpoint_cursor, conn=self._conn, metadata_json={...})`
  - empty batch commit: same store method inside transaction.
  - failure: `cursor_store.record_error(namespace, str(exc))`
- Preserve the existing transaction boundaries:
  - source document, resource binding, source-unit fingerprint, chunks, FTS,
    vectors, vector components, and checkpoint commit remain inside the same
    `BEGIN`/`COMMIT`.
  - rollback still prevents checkpoint persistence.
- Do not change Telegram public ref shape.
- Do not read private `mcp-telegram` SQLite tables.
- Do not import Telethon or any direct Telegram API client.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `build_if_configured("telegram")`.
- `backend/src/dotmd/api/service.py` does not contain `TelegramApplicationSourceProvider(`.
- `backend/src/dotmd/api/service.py` does not contain `UnixSocketTelegramSourceClient(`.
- `backend/src/dotmd/cli.py` uses `build("telegram")` or `build_if_configured("telegram")` for `telegram ingest`.
- `backend/src/dotmd/cli.py` does not contain `TelegramApplicationSourceProvider(`.
- `backend/src/dotmd/cli.py` does not contain `UnixSocketTelegramSourceClient(`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `cursor_store.get_checkpoint`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `cursor_store.commit_checkpoint`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `cursor_store.record_error`.
- `backend/src/dotmd/ingestion/pipeline.py` still contains `self._conn.execute("BEGIN")` before checkpoint commit.
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q`
`cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py`
</verify>
<done>
Telegram service and CLI runtime construction use lifecycle, and application-source checkpoint access goes through the lifecycle cursor store inside the existing transaction.
</done>
</task>

<task id="3" type="execute">
<name>Document Phase 33 lifecycle boundary and run static source-boundary guards</name>
<title>Document Phase 33 lifecycle boundary and run static source-boundary guards</title>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-registry-airweave-mapping.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/source-registry-airweave-mapping.md`
</files>
<action>
Update architecture docs to record what Phase 33 delivered.

Concrete target state:
- In `docs/source-adapter-architecture.md`, add a `## Phase 33 Planned Source Lifecycle` or delivered-state section near the Phase 32 section that states:
  - lifecycle/factory constructs source runtime bundles from registry descriptors, typed local config, credential/auth provider access, cursor store, and runtime helpers.
  - filesystem and Telegram construction paths are routed through lifecycle.
  - filesystem paths remain internal holder mechanics, not public source identity.
  - Telegram remains delegated to `mcp-telegram`; dotMD does not own Telegram API auth.
  - `checkpoint_cursor` commits remain after successful local persistence only.
  - no full reindex is required.
- In `docs/source-registry-airweave-mapping.md`, update `Runtime Boundary` to
  mention that Phase 33 adapts Airweave's lifecycle idea as a compact dotMD
  runtime bundle/factory, while still rejecting Airweave organizations,
  Temporal, billing, and marketplace runtime.
- Run static source-boundary guards and fix any accidental direct dependency:
  - `rg -n "from airweave|import airweave" backend/src backend/tests`
  - `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests`
  - `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py`
  - `rg -n "TelegramApplicationSourceProvider\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py`
</action>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `Phase 33`.
- `docs/source-adapter-architecture.md` contains `source runtime bundles`.
- `docs/source-adapter-architecture.md` contains `checkpoint_cursor`.
- `docs/source-adapter-architecture.md` contains `mcp-telegram`.
- `docs/source-registry-airweave-mapping.md` contains `Phase 33`.
- `docs/source-registry-airweave-mapping.md` contains `runtime bundle`.
- `rg -n "from airweave|import airweave" backend/src backend/tests` returns no matches.
- `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests` returns no new runtime direct Telegram API/private SQLite access.
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` returns no matches.
- `rg -n "TelegramApplicationSourceProvider\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py` returns no matches.
</acceptance_criteria>
<verify>
`rg -n "Phase 33|source runtime bundles|checkpoint_cursor|mcp-telegram" docs/source-adapter-architecture.md`
`rg -n "Phase 33|runtime bundle" docs/source-registry-airweave-mapping.md`
`rg -n "from airweave|import airweave" backend/src backend/tests` returns no matches.
`rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests` returns no new direct Telegram API or private SQLite access.
</verify>
<done>
Architecture docs record the Phase 33 lifecycle boundary and static source-boundary scans pass.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py -q`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py src/dotmd/api/service.py src/dotmd/cli.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py tests/api/test_service_search.py tests/storage/test_metadata_m2m.py`
- `rg -n "from airweave|import airweave" backend/src backend/tests`
- `rg -n "Telethon|telegram\\.client|sqlite.*telegram|telegram.*sqlite" backend/src backend/tests`
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py`
- `rg -n "TelegramApplicationSourceProvider\\(" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py`
</verification>

<success_criteria>
- LIFE-01 is satisfied for Telegram and application-source runtimes.
- LIFE-02 is satisfied by delegated credential/auth provider access.
- LIFE-03 is satisfied by lifecycle cursor store use inside the existing local transaction.
- LIFE-04 is complete: filesystem and Telegram construction paths use lifecycle.
- Source-ref-first and retained-artifacts guardrails are preserved.
</success_criteria>
