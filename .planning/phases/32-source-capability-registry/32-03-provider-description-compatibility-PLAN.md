---
phase: "32"
plan: "03"
type: tdd
wave: 2
depends_on:
  - "32-01"
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/tests/ingestion/test_application_source_provider.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/ingestion/test_source_registry.py
autonomous: true
requirements: ["SRC-01", "SRC-02"]
requirements_addressed: ["SRC-01", "SRC-02"]
must_haves:
  truths:
    - "D-04: A source descriptor is declarative only and must not instantiate providers, open clients, read secrets, or persist cursors."
    - "D-05: Runtime construction, credential access, cursor state ownership, and provider factory wiring are Phase 33 lifecycle scope."
    - "D-06: Descriptor schemas are typed enough for Phase 33 to consume without redefining the contract."
    - "D-10: Filesystem and Telegram seed entries populate descriptor metadata, capability flags, config schema, auth schema, and cursor schema."
---

# Phase 32 Plan 03: Provider Description Compatibility

<objective>
Keep existing application-source provider descriptions working while exposing a
clear bridge to the richer Phase 32 source descriptors.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Runtime providers are forced to return new descriptors before lifecycle exists | HIGH | Preserve `ApplicationSourceProviderProtocol.describe_source()` compatibility. |
| Descriptor and lightweight description diverge immediately | MEDIUM | Add conversion helpers/tests for descriptor-to-description compatibility. |
| Existing Telegram ingestion breaks because daemon payload still returns simple capability strings | HIGH | Keep `ApplicationSourceDescription` able to accept current daemon payloads. |
| Compatibility code grows into a lifecycle factory | HIGH | Limit work to model conversion and tests; no construction or cursor persistence. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Test descriptor compatibility with existing provider descriptions</title>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_application_source_provider.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/ingestion/test_source_registry.py`
</read_first>
<files>
- `backend/tests/ingestion/test_application_source_provider.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/tests/ingestion/test_source_registry.py`
</files>
<action>
Add tests proving the richer descriptor contract does not break the current
provider protocol.

Concrete tests:
- Add a source registry test that converts `telegram_source_descriptor()` to an
  `ApplicationSourceDescription` and asserts:
  - namespace `telegram`
  - source_kind `chat`
  - display_name `Telegram`
  - capabilities include normalized string values from the descriptor.
- Add an application-provider test that current simple
  `ApplicationSourceDescription(namespace="telegram", source_kind="chat", display_name="Telegram", capabilities=["incremental-export", "unit-window"])`
  still validates.
- Add a Telegram provider test that `TelegramApplicationSourceProvider(...).describe_source()`
  still accepts daemon payloads using current capability strings
  `incremental-export` and `unit-window`.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_registry.py` contains a descriptor-to-description compatibility test.
- `backend/tests/ingestion/test_application_source_provider.py` still constructs `ApplicationSourceDescription` with current string capabilities.
- `backend/tests/ingestion/test_telegram_provider.py` still asserts `provider.describe_source().namespace == "telegram"`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` exits 0 after task 2.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Add descriptor-to-description bridge without changing runtime protocol</title>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/source_registry.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/test_source_registry.py`
- `backend/tests/ingestion/test_application_source_provider.py`
- `backend/tests/ingestion/test_telegram_provider.py`
</files>
<action>
Add a compatibility bridge while preserving the provider protocol.

Concrete target state:
- Keep `ApplicationSourceDescription` fields compatible with current payloads:
  `namespace`, `source_kind`, `display_name`, `capabilities: list[str]`, and
  `metadata_json`.
- Add one explicit bridge, either:
  - `ApplicationSourceDescription.from_descriptor(descriptor: SourceDescriptor) -> ApplicationSourceDescription`, or
  - `source_descriptor_to_application_description(descriptor: SourceDescriptor) -> ApplicationSourceDescription`.
- The bridge converts `SourceCapability` enum values to their string `.value`.
- The bridge copies descriptor display metadata into `metadata_json` under a
  non-conflicting key such as `descriptor_display` if that is useful, but it
  must not flatten typed config/auth/cursor schemas into runtime settings.
- Do not change `ApplicationSourceProviderProtocol.describe_source()` return
  type away from `ApplicationSourceDescription` in Phase 32.
- Do not make `TelegramApplicationSourceProvider` construct runtimes from the
  registry.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `from_descriptor` or an explicit descriptor-to-description conversion helper.
- `backend/src/dotmd/ingestion/source_provider.py` still contains `def describe_source(self) -> ApplicationSourceDescription`.
- `backend/src/dotmd/ingestion/telegram_provider.py` still calls `ApplicationSourceDescription(**self._client.describe_source())`.
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` exits 0.
- `cd backend && uv run pyright` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q`
- `cd backend && uv run pyright`
</verification>

<success_criteria>
- Existing Telegram/application-source runtime payloads still validate.
- New descriptors can produce the lightweight description shape.
- Phase 33 lifecycle remains untouched.
</success_criteria>

