---
phase: "28"
plan: "03"
type: tdd
wave: 3
depends_on:
  - "28-01"
  - "28-02"
files_modified:
  - backend/tests/ingestion/application_source_fixtures.py
  - backend/tests/ingestion/test_application_source_provider.py
autonomous: true
requirements: ["R3", "R4", "R8"]
requirements_addressed: ["R3", "R4", "R8"]
must_haves:
  truths:
    - "D-03: dotMD fixture/provider tests do not read mcp-telegram private SQLite tables."
    - "D-04: The fixture provider implements describe_source, export_changes, and read_unit_window."
    - "D-05: export_changes returns active fixture records only."
    - "D-06: Documents and units are included in export_changes payloads."
    - "D-09: Repeating the same active record and fingerprint is safe and idempotent."
    - "D-10: The fixture provider emits stable SourceDocument envelopes."
    - "D-11: The fixture provider emits SourceUnit content."
    - "D-12: Telegram-like fixture records use real message units; document-only fixture records use an implicit root unit."
    - "D-16/D-17/D-18: read_unit_window returns neighboring units when meaningful and a single-unit fallback otherwise."
    - "Full-reindex answer: this plan exercises fixture providers only; no live Telegram, dotmd index --force, or rebuild."
---

# Phase 28 Plan 03: Fixture Provider Contract

<objective>
Prove the provider contract with deterministic fixtures so Phase 29 can plan a
Telegram adapter against tested behavior instead of prose alone.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Contract looks correct but cannot be exercised end-to-end | HIGH | Add a fixture provider with export and read-window behavior under pytest. |
| Fixture silently depends on live Telegram or mcp-telegram internals | HIGH | Tests use in-memory fixture records only and grep against forbidden imports/paths. |
| Fixture code becomes accidental production API | MEDIUM | Keep `FixtureApplicationSourceProvider` and implicit-root helpers under `backend/tests`, while production `source_provider.py` remains protocol-only. |
| Document-only sources cannot fit the contract | MEDIUM | Add implicit root unit fixture and fallback read window. |
| Duplicate active batches trigger recomputation expectations | HIGH | Test fingerprint helper or fixture processing identifies duplicate unchanged units. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add deterministic fixture provider</title>
<name>Add deterministic fixture provider</name>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/application_source_fixtures.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</read_first>
<files>
- `backend/tests/ingestion/application_source_fixtures.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</files>
<behavior>
- `FixtureApplicationSourceProvider.describe_source()` returns namespace `telegram_fixture` or equivalent source-neutral fixture metadata.
- `export_changes(None, limit=2)` returns two active changes and a `checkpoint_cursor`.
- Calling `export_changes(checkpoint_cursor, limit=2)` returns the next batch or empty batch deterministically.
- The fixture has no `mcp_telegram` or `telethon` import.
</behavior>
<action>
Add a test-only fixture provider in `backend/tests/ingestion/application_source_fixtures.py`. Do not add fixture classes or implicit-root helpers to production `backend/src/dotmd/ingestion/source_provider.py`; that module stays limited to the protocol and production payload imports from Plan 01.

Concrete target state:
- Define `FixtureApplicationSourceProvider` that implements `ApplicationSourceProviderProtocol`.
- Constructor accepts `description: ApplicationSourceDescription` and `changes: list[ApplicationSourceChange]`.
- Cursors are opaque strings in the form `offset:<n>` for the fixture only.
- `export_changes(cursor, limit)` slices active fixture changes and returns:
  - `changes` for the requested slice;
  - `next_cursor="offset:<end>"` when more records exist, otherwise `None`;
  - `checkpoint_cursor="offset:<end>"` after each non-empty batch.
- Add helper `make_implicit_root_unit(document: SourceDocument, text: str, fingerprint: str, updated_at: datetime) -> SourceUnit`.
  - The helper must set `unit_type="root"`, `unit_ref=f"{document.document_ref}:root"`, `order_key="0000000000"`, `metadata_json={}`, and `chunking_hints={}` unless a test passes explicit overrides.
- Keep the fixture provider generic; Telegram-like examples live in tests, not class names.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q</automated>
<automated>rg -n "FixtureApplicationSourceProvider|make_implicit_root_unit|telethon|mcp_telegram" backend/src/dotmd/ingestion/source_provider.py backend/tests/ingestion/application_source_fixtures.py</automated>
</verify>
<acceptance_criteria>
- `backend/tests/ingestion/application_source_fixtures.py` contains `class FixtureApplicationSourceProvider`.
- `backend/tests/ingestion/application_source_fixtures.py` contains `offset:`.
- `backend/tests/ingestion/application_source_fixtures.py` contains `def make_implicit_root_unit`.
- `backend/tests/ingestion/application_source_fixtures.py` contains `unit_type="root"` or `unit_type='root'`.
- `backend/src/dotmd/ingestion/source_provider.py` does not contain `FixtureApplicationSourceProvider`.
- `backend/src/dotmd/ingestion/source_provider.py` does not contain `make_implicit_root_unit`.
- `backend/tests/ingestion/application_source_fixtures.py` does not contain `telethon`.
- `backend/tests/ingestion/test_application_source_provider.py` asserts a non-empty batch has `checkpoint_cursor`.
- `backend/tests/ingestion/test_application_source_provider.py` asserts a later cursor returns deterministic subsequent records or empty records.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Exercise read_unit_window and idempotent fingerprint flow</title>
<name>Exercise read_unit_window and idempotent fingerprint flow</name>
<read_first>
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/application_source_fixtures.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_application_source_provider.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/tests/ingestion/application_source_fixtures.py`
- `backend/tests/ingestion/test_application_source_provider.py`
</files>
<behavior>
- A Telegram-like middle message window returns before, target, and after units in order.
- A document-only source window returns only the implicit root unit.
- Replaying the same fixture batch against source-unit fingerprint helpers can classify unchanged units.
</behavior>
<action>
Add fixture read-window behavior and tests.

Concrete target state:
- `FixtureApplicationSourceProvider.read_unit_window(unit_ref, before, after)` returns `SourceUnitWindow`.
- For ordered message units, it includes up to `before` units before the target and up to `after` units after the target, sorted by `order_key`.
- For an implicit root unit, it returns exactly one unit even when `before` and `after` are positive.
- Unknown `unit_ref` raises `ValueError("Unknown source unit: <unit_ref>")`.
- Malformed fixture cursors such as `"bad"`, `"offset:-1"`, and `"offset:not-an-int"` raise `ValueError("Invalid fixture cursor: <cursor>")`.
- `export_changes(cursor, limit)` raises `ValueError("limit must be positive")` when `limit <= 0`.
- Add a test that writes fixture units through `SQLiteMetadataStore.upsert_source_unit_fingerprint` and proves a replay of the same batch returns unchanged (`False`) for each unit.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/ingestion/application_source_fixtures.py` contains `def read_unit_window`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `Unknown source unit`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `Invalid fixture cursor`.
- `backend/tests/ingestion/test_application_source_provider.py` contains `limit must be positive`.
- `backend/tests/ingestion/test_application_source_provider.py` asserts a three-unit neighboring message window.
- `backend/tests/ingestion/test_application_source_provider.py` asserts an implicit root fallback window has length `1`.
- `backend/tests/ingestion/test_application_source_provider.py` imports or exercises `upsert_source_unit_fingerprint`.
- `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q
```
</verification>

<success_criteria>
- A deterministic fixture provider proves the contract without live Telegram.
- Message-window and document-only fallback behavior are test-covered.
- Replaying unchanged active units is idempotent and does not imply recomputation.
</success_criteria>

## PLANNING COMPLETE
