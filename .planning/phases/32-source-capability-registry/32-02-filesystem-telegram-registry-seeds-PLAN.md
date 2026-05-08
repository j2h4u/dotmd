---
phase: "32"
plan: "02"
type: tdd
wave: 2
depends_on:
  - "32-01"
files_modified:
  - backend/src/dotmd/ingestion/source_registry.py
  - backend/src/dotmd/ingestion/source.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/tests/ingestion/test_source_registry.py
  - backend/tests/ingestion/test_source_filesystem.py
  - backend/tests/ingestion/test_telegram_provider.py
autonomous: true
requirements: ["SRC-02", "SRC-03"]
requirements_addressed: ["SRC-02", "SRC-03"]
must_haves:
  truths:
    - "D-02: Take useful Airweave categories: source catalog entries, config schema, auth schema, cursor schema, capability flags, browse-tree support, federated-search marker, ACL marker, and incremental/continuous sync marker."
    - "D-10: Filesystem and Telegram are detailed reference entries, not empty seeds."
    - "D-11: Filesystem still acknowledges local paths as internal holder mechanics for discovery, reads, delete detection, parser routing, and content-addressed reuse."
    - "D-12: Telegram is an application source behind mcp-telegram, not a direct Telegram API client in dotMD."
---

# Phase 32 Plan 02: Filesystem And Telegram Registry Seeds

<objective>
Seed the default source registry with detailed filesystem and Telegram
descriptors using the Phase 32 capability vocabulary.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Filesystem stays outside the registry | HIGH | Add a default registry test requiring `filesystem` and `telegram` namespaces. |
| Telegram descriptor implies direct Telegram API ownership | HIGH | Encode auth as delegated to `mcp-telegram` and assert no direct API auth method appears. |
| Seed descriptors overclaim capabilities | HIGH | Assert exact capability sets for filesystem and Telegram. |
| Seed descriptors are too empty to guide later phases | MEDIUM | Require config, auth, and cursor schema names and at least one meaningful field/example where applicable. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add default registry seed tests</title>
<read_first>
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md`
- `.planning/phases/32-source-capability-registry/32-RESEARCH.md`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_telegram_provider.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_registry.py`
</files>
<action>
Extend `backend/tests/ingestion/test_source_registry.py` with failing tests for
default registry seed descriptors.

Concrete tests:
- `test_default_registry_contains_filesystem_and_telegram` asserts
  `default_source_registry().list()` contains exactly the `filesystem` and
  `telegram` namespaces for Phase 32 seeds, unless implementation also
  includes test fixtures explicitly marked non-default.
- `test_filesystem_descriptor_shape` asserts:
  - namespace `filesystem`
  - source_kind `local_filesystem`
  - display name `Filesystem Markdown`
  - config schema has a `paths` field and an `exclude` field
  - auth schema auth_kind `none`
  - cursor schema cursor_kind `fingerprint`
  - capabilities exactly `local_sync`, `materialization`, `browse_tree`
- `test_telegram_descriptor_shape` asserts:
  - namespace `telegram`
  - source_kind `chat`
  - display name `Telegram`
  - config schema has `daemon_socket`
  - auth schema auth_kind `delegated` and delegated_to `mcp-telegram`
  - cursor schema contains example `telegram:v1:dialog:<dialog_id>:message:<message_id>`
  - capabilities include `local_sync`, `read_unit_window`, `incremental_cursor`, and `federated_search`
  - capabilities do not include `acl`
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_registry.py` contains `test_default_registry_contains_filesystem_and_telegram`.
- The filesystem seed test asserts exact capabilities.
- The Telegram seed test asserts `delegated_to == "mcp-telegram"`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` fails before task 2 and exits 0 after task 2.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement default source registry seeds</title>
<read_first>
- `backend/src/dotmd/core/source_registry.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_source_registry.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source_registry.py`
- `backend/tests/ingestion/test_source_registry.py`
</files>
<action>
Add `backend/src/dotmd/ingestion/source_registry.py` with descriptor builders
and a default registry factory.

Concrete target state:
- `filesystem_source_descriptor() -> SourceDescriptor`
- `telegram_source_descriptor() -> SourceDescriptor`
- `default_source_registry() -> SourceRegistry`
- Filesystem descriptor:
  - namespace `filesystem`
  - source_kind `local_filesystem`
  - display display_name `Filesystem Markdown`
  - config schema name `FilesystemSourceConfig`
  - config fields `paths` and `exclude`
  - auth schema auth_kind `none`
  - cursor schema cursor_kind `fingerprint`
  - capabilities `SourceCapability.LOCAL_SYNC`, `SourceCapability.MATERIALIZATION`, `SourceCapability.BROWSE_TREE`
  - metadata_json includes `media_type: "text/markdown"` and `parser_name: "markdown"`
- Telegram descriptor:
  - namespace `telegram`
  - source_kind `chat`
  - display display_name `Telegram`
  - config schema name `TelegramSourceConfig`
  - config field `daemon_socket`
  - auth schema auth_kind `delegated`, delegated_to `mcp-telegram`
  - cursor schema cursor_kind `provider_checkpoint`
  - cursor examples include `telegram:v1:dialog:<dialog_id>:message:<message_id>`
  - capabilities `SourceCapability.LOCAL_SYNC`, `SourceCapability.READ_UNIT_WINDOW`, `SourceCapability.INCREMENTAL_CURSOR`, `SourceCapability.FEDERATED_SEARCH`
  - metadata_json includes `transport: "mcp-telegram-daemon"`
- Do not import Telethon, Telegram API clients, Airweave, docker, sqlite3, or settings.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/source_registry.py` contains `def default_source_registry`.
- `backend/src/dotmd/ingestion/source_registry.py` contains `filesystem_source_descriptor`.
- `backend/src/dotmd/ingestion/source_registry.py` contains `telegram_source_descriptor`.
- `backend/src/dotmd/ingestion/source_registry.py` contains `mcp-telegram`.
- `backend/src/dotmd/ingestion/source_registry.py` does not contain `Telethon`.
- `backend/src/dotmd/ingestion/source_registry.py` does not contain `airweave`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_telegram_provider.py -q`
- `cd backend && uv run pyright`
</verification>

<success_criteria>
- SRC-02 is satisfied by real filesystem and Telegram registry entries.
- SRC-03 is satisfied by exact capability assertions for both seed sources.
- Registry seeds stay declarative and do not construct runtimes.
</success_criteria>

