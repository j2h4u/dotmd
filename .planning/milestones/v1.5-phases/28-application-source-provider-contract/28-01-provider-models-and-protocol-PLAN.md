---
phase: "28"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/source_provider.py
  - backend/tests/ingestion/test_application_source_provider.py
autonomous: true
requirements: ["R3", "R4", "R8"]
requirements_addressed: ["R3", "R4", "R8"]
must_haves:
  truths:
    - "D-01: The generic contract is minimal and is not a Telegram-only import path or plugin framework."
    - "D-02: The generic model names and fields stay viable for Slack, Notion, PDFs, and other application sources."
    - "D-04: The required provider methods are describe_source, export_changes(cursor, limit), and read_unit_window(unit_ref, before, after)."
    - "D-05: export_changes returns active records only in Phase 28."
    - "D-06: export_changes carries documents and units; no export_documents or export_units method is added."
    - "D-10: Every provider exposes a stable SourceDocument envelope."
    - "D-11: Providers emit or normalize content through SourceUnit."
    - "D-12: Telegram examples use real message units; document-only sources can use an implicit root unit."
    - "D-13: SourceUnit is the provider-owned sync/indexing item and avoids Telegram-specific generic fields."
    - "D-14: SourceUnit has namespace, document_ref, unit_ref, text, fingerprint, updated_at, order_key, and metadata_json."
    - "D-16: read_unit_window(unit_ref, before, after) is required."
    - "D-17: Providers without neighbors may return only the requested unit."
    - "D-18: The contract keeps future search -> ref -> read/drill context behavior possible without overcomplicating simple sources."
    - "D-22/D-23: graphify is advisory only; this plan verifies against live source files."
    - "Full-reindex answer: this plan requires no dotmd index --force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild."
---

# Phase 28 Plan 01: Provider Models and Protocol

<objective>
Define the generic application-source provider contract and payload models that
Phase 29 can implement for Telegram without making Telegram the generic shape.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Generic provider classes accidentally become Telegram-specific | HIGH | Use source-neutral class and field names; keep Telegram only in tests/examples. |
| Cursor export gets split into speculative document/unit methods | HIGH | Protocol exposes only `describe_source`, `export_changes`, and `read_unit_window`. |
| SourceUnit remains too weak for per-message incremental sync | HIGH | Add `updated_at` and tests requiring all D-14 fields. |
| Adding required `SourceUnit.updated_at` breaks existing constructors | HIGH | Audit every `SourceUnit(` call site before editing the model, update all non-class constructors in the same task, and run existing filesystem/service regression tests in Plan 01. |
| Provider input accepts human-rendered output | HIGH | Payload models require `SourceDocument` and `SourceUnit` objects, not formatted text. |
| Full reindex hidden in model change | HIGH | Add only Pydantic/protocol/test files; no index rebuild command or data rewrite. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add provider payload models and SourceUnit updated_at</title>
<name>Add provider payload models and SourceUnit updated_at</name>
<read_first>
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md`
- `.planning/phases/28-application-source-provider-contract/28-RESEARCH.md`
- `.planning/phases/28-application-source-provider-contract/28-PATTERNS.md`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</files>
<behavior>
- Constructing `SourceUnit` without `updated_at` fails validation.
- Constructing `SourceUnit` with D-14 fields succeeds.
- Existing `SourceUnit(` constructors in `backend/src` and `backend/tests` are audited and either updated with `updated_at` in this task or confirmed to be only the class definition.
- Existing `SourceUnit` fields `unit_type` and `chunking_hints` stay part of the model contract unless the executor finds a current-code reason to make them optional; all new test constructors set them explicitly.
- `ApplicationSourceChangeBatch` carries `changes`, `next_cursor`, and `checkpoint_cursor`.
- `ApplicationSourceChange` carries one `SourceDocument` and one `SourceUnit`.
</behavior>
<action>
Create `backend/tests/ingestion/test_application_source_provider.py` first with failing tests, then update `backend/src/dotmd/core/models.py`.

Concrete target state:
- Before changing `SourceUnit`, run `rg -n "SourceUnit\\(" backend/src backend/tests`.
  - If the only match is `backend/src/dotmd/core/models.py:class SourceUnit`, record that in the task notes and continue.
  - If any constructor call exists, update that constructor in the same task with `updated_at=<datetime>`, preserve `unit_type`, `order_key`, `fingerprint`, `metadata_json`, and `chunking_hints`, and include the touched file in verification.
- Add `updated_at: datetime` to `SourceUnit`.
- Keep `SourceUnit.model_config = ConfigDict(extra="forbid")`.
- Keep the existing required `unit_type: str` and `chunking_hints: dict = Field(default_factory=dict)` fields visible in tests. Do not remove or silently weaken them in this phase.
- Add `ApplicationSourceDescription` with:
  - `namespace: str`
  - `source_kind: str`
  - `display_name: str`
  - `capabilities: list[str] = Field(default_factory=list)`
  - `metadata_json: dict = Field(default_factory=dict)`
- Add `ApplicationSourceChange` with:
  - `document: SourceDocument`
  - `unit: SourceUnit`
- Add `ApplicationSourceChangeBatch` with:
  - `changes: list[ApplicationSourceChange] = Field(default_factory=list)`
  - `next_cursor: str | None = None`
  - `checkpoint_cursor: str | None = None`
- Use generic names exactly above. Do not introduce `TelegramProvider`, `TelegramChange`, `export_documents`, or `export_units` in generic code.
- Test a complete Telegram-like example without hiding required fields:
  - `SourceDocument(namespace="telegram", document_ref="dialog:123", ref="telegram:dialog:123", source_uri="telegram://dialog/123", media_type="text/plain", parser_name="telegram-message", document_type="dialog", title="Telegram dialog 123", updated_at=<datetime>, content_fingerprint="doc-content", metadata_fingerprint="doc-meta", metadata_json={})`
  - `SourceUnit(namespace="telegram", document_ref="dialog:123", unit_ref="dialog:123:message:456", unit_type="message", text="hello", order_key="0000000456", fingerprint="unit-fingerprint", updated_at=<datetime>, metadata_json={}, chunking_hints={})`
</action>
<verify>
<automated>rg -n "SourceUnit\\(" backend/src backend/tests</automated>
<automated>cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class ApplicationSourceDescription`.
- `backend/src/dotmd/core/models.py` contains `class ApplicationSourceChange`.
- `backend/src/dotmd/core/models.py` contains `class ApplicationSourceChangeBatch`.
- `backend/src/dotmd/core/models.py` contains `updated_at: datetime` inside `class SourceUnit`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `dialog:123:message:456`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `unit_type="message"` or `unit_type='message'`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `chunking_hints={}`.
- `backend/tests/ingestion/test_application_source_provider.py` asserts `checkpoint_cursor == "cursor:456"` or equivalent explicit checkpoint cursor value.
- `backend/tests/ingestion/test_application_source_provider.py` does not contain `export_documents`.
- `rg -n "SourceUnit\\(" backend/src backend/tests` has no stale constructor that omits `updated_at`.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Define the application provider Protocol</title>
<name>Define the application provider Protocol</name>
<read_first>
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</files>
<behavior>
- A fixture class satisfying `ApplicationSourceProviderProtocol` exposes exactly the required methods.
- The protocol does not define `export_documents` or `export_units`.
- `read_unit_window(unit_ref, before, after)` returns a `SourceUnitWindow`.
</behavior>
<action>
Add a new small module `backend/src/dotmd/ingestion/source_provider.py`.

Concrete target state:
- Define `ApplicationSourceProviderProtocol(Protocol)` with methods:
  - `def describe_source(self) -> ApplicationSourceDescription: ...`
  - `def export_changes(self, cursor: str | None, limit: int) -> ApplicationSourceChangeBatch: ...`
  - `def read_unit_window(self, unit_ref: str, before: int, after: int) -> SourceUnitWindow: ...`
- Define `SourceUnitWindow` in `backend/src/dotmd/core/models.py` with:
  - `namespace: str`
  - `document_ref: str`
  - `unit_ref: str`
  - `units: list[SourceUnit]`
  - `metadata_json: dict = Field(default_factory=dict)`
- Add tests proving the protocol module exports `ApplicationSourceProviderProtocol` and `SourceUnitWindow` is usable for a Telegram-like neighboring-message window.
- Ensure the protocol module has no import from `mcp_telegram`, `telethon`, or `/home/j2h4u/repos/j2h4u/mcp-telegram`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/source_provider.py` contains `class ApplicationSourceProviderProtocol`.
- `backend/src/dotmd/ingestion/source_provider.py` contains `describe_source`.
- `backend/src/dotmd/ingestion/source_provider.py` contains `export_changes`.
- `backend/src/dotmd/ingestion/source_provider.py` contains `read_unit_window`.
- `backend/src/dotmd/ingestion/source_provider.py` does not contain `export_documents`.
- `backend/src/dotmd/ingestion/source_provider.py` does not contain `export_units`.
- `backend/src/dotmd/ingestion/source_provider.py` does not contain `mcp_telegram`.
- `backend/src/dotmd/core/models.py` contains `class SourceUnitWindow`.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
rg -n "SourceUnit\\(" backend/src backend/tests
cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q
```
</verification>

<success_criteria>
- R3 is covered by a generic provider protocol and typed payload models.
- R4 is prepared through Telegram-like examples without dotMD owning Telegram auth/runtime.
- R8 is covered by fixture tests that do not require live Telegram.
- The provider contract remains source-neutral and does not introduce hidden full reindex work.
</success_criteria>

## PLANNING COMPLETE
