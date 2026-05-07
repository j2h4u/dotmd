---
phase: "29"
plan: "02"
type: tdd
wave: 2
depends_on:
  - "29-01"
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/tests/ingestion/test_telegram_provider.py
autonomous: true
requirements: ["R4", "R5", "R8"]
requirements_addressed: ["R4", "R5", "R8"]
must_haves:
  truths:
    - "D-03: Telegram public refs point to concrete messages: telegram:dialog:<dialog_id>:message:<message_id>."
    - "D-06: A Telegram message remains the durable SourceUnit and recomputation/provenance boundary."
    - "D-08: Substantive messages may be indexed as message-anchored chunks with compact Telegram metadata context."
    - "D-09: Low-signal messages are stored as SourceUnit records but not promoted as standalone normal search hits."
    - "D-10: Any retrieval context remains anchored to one concrete message and records all included source units."
    - "D-11: dotMD provider code must not import Telethon, mcp_telegram.sync_db, or parse rendered list_messages output."
    - "D-16: Fixtures cover short acknowledgements, duplicate short messages, rapid chats, topic/reply metadata, edited fingerprints, and unchanged replay inputs."
    - "Review-HIGH: Edited message fingerprint assertions are valid because Plan 01 now delivers edited existing messages through updated_after."
    - "Full-reindex answer: this plan adds provider mapping and tests only; no live indexing or rebuild."
---

# Phase 29 Plan 02: dotMD Telegram Provider

<objective>
Map the structured `mcp-telegram` source API into dotMD's application-source
provider contract with stable message refs, deterministic fingerprints, and
low-signal message classification.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| dotMD imports Telegram runtime internals | HIGH | Provider depends on a small client protocol and plain JSON payloads only. |
| Public refs anchor dialogs instead of messages | HIGH | Tests assert `telegram:dialog:<dialog_id>:message:<message_id>` as the message public ref. |
| Low-signal messages disappear entirely | HIGH | Tests assert low-signal units still become `SourceUnit` records. |
| Fingerprints ignore edit-relevant metadata | MEDIUM | Fingerprint helper includes normalized text plus sent/edit/delete/topic/reply metadata. |
| Duplicate short messages collapse into one ref | HIGH | Tests include duplicate short messages with different ids/senders/timestamps. |
| RU/EN short acknowledgements classify inconsistently | MEDIUM | Low-signal vocabulary uses `casefold()` and includes conservative English and Russian acknowledgement tokens. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add Telegram provider mapping tests</title>
<name>Add Telegram provider mapping tests</name>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/application_source_fixtures.py`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-RESEARCH.md`
</read_first>
<files>
- `backend/tests/ingestion/test_telegram_provider.py`
</files>
<behavior>
- A structured Telegram export record maps to `SourceDocument(namespace="telegram", document_ref="dialog:<id>")`.
- A message maps to `SourceUnit(unit_ref="dialog:<id>:message:<id>", unit_type="message")`.
- The provider exposes public message refs with shape `telegram:dialog:<dialog_id>:message:<message_id>` for downstream chunk/search hydration.
- Duplicate low-signal messages with different ids remain distinct units.
- Provider batches preserve daemon `updated_after` so ingestion can request edited already-exported messages on the next run.
</behavior>
<action>
Create `backend/tests/ingestion/test_telegram_provider.py`.

Concrete fixture payloads:
- substantive message: dialog `-1001`, message `42`, text `"Deployment checklist is ready"`, sender name/id, topic id/title, reply id, sent_at, edit_date `None`.
- low-signal message: dialog `-1001`, message `43`, text `"ok"`, same topic.
- duplicate low-signal message: dialog `-1001`, message `44`, text `"ok"`, different sender id and sent_at.
- edited message: same unit ref as message `42` with changed text or `edit_date`.

Tests must assert:
- `TelegramApplicationSourceProvider.describe_source().namespace == "telegram"`.
- `export_changes(None, 10)` returns `ApplicationSourceChangeBatch`.
- `change.document.ref == "telegram:dialog:-1001"`.
- `change.unit.unit_ref == "dialog:-1001:message:42"`.
- `public_ref_for_unit(change.unit) == "telegram:dialog:-1001:message:42"`.
- low-signal units have metadata marker `standalone_search == false` or equivalent concrete key chosen by implementation.
- duplicate low-signal units have different `unit_ref` and different fingerprints.
- edited payload changes the fingerprint.
- `public_ref_for_unit(change.unit)` is defined by the provider module and returns `f"telegram:{unit.unit_ref}"`.
- missing optional fields such as `edit_date`, `topic_id`, and `reply_to_msg_id` fingerprint as explicit `null` values, not omitted keys.
- `batch.updated_after` equals the daemon response watermark when present.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/ingestion/test_telegram_provider.py` contains `TelegramApplicationSourceProvider`.
- `backend/tests/ingestion/test_telegram_provider.py` contains `telegram:dialog:-1001:message:42`.
- `backend/tests/ingestion/test_telegram_provider.py` contains `dialog:-1001:message:43`.
- `backend/tests/ingestion/test_telegram_provider.py` asserts duplicate `ok` messages remain distinct.
- `backend/tests/ingestion/test_telegram_provider.py` asserts edited content changes fingerprint.
- `backend/tests/ingestion/test_telegram_provider.py` imports or calls `public_ref_for_unit`.
- `backend/tests/ingestion/test_telegram_provider.py` contains at least one Russian acknowledgement such as `спасибо` or `да`.
- `backend/tests/ingestion/test_telegram_provider.py` asserts `updated_after`.
- The focused pytest command initially fails before implementation and exits 0 after implementation.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement provider/client mapping and low-signal classification</title>
<name>Implement provider/client mapping and low-signal classification</name>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/tests/ingestion/test_telegram_provider.py`
- `docs/mcp-telegram-source-contract.md`
</read_first>
<files>
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_telegram_provider.py`
</files>
<behavior>
- dotMD provider consumes structured source payloads via a protocol, not Telegram internals.
- The mapping is deterministic and Pydantic-validated.
- Low-signal classification is conservative and visible in unit metadata for ingestion.
</behavior>
<action>
Add provider mapping and the minimal batch-contract extension needed for edit delivery.

Concrete target state:
- In `backend/src/dotmd/core/models.py`, add `updated_after: str | None = None` to `ApplicationSourceChangeBatch`.
- Define `TelegramSourceClientProtocol` with:
  - `describe_source() -> dict`
  - `export_source_changes(cursor: str | None, limit: int, updated_after: str | None = None) -> dict`
  - `read_source_unit_window(unit_ref: str, before: int, after: int) -> dict`
- Define `TelegramApplicationSourceProvider(ApplicationSourceProviderProtocol)` with constructor signature `__init__(self, client: TelegramSourceClientProtocol) -> None`.
- Define `public_ref_for_unit(unit: SourceUnit) -> str` returning `f"telegram:{unit.unit_ref}"`.
- Map source description dicts to `ApplicationSourceDescription`.
- Map export payloads to `ApplicationSourceChangeBatch`, including `checkpoint_cursor`, `next_cursor`, and `updated_after`.
- Build document fields:
  - `namespace="telegram"`
  - `document_ref="dialog:<dialog_id>"`
  - `ref="telegram:dialog:<dialog_id>"`
  - `source_uri="telegram://dialog/<dialog_id>"`
  - `media_type="text/plain"`
  - `parser_name="telegram-message"`
  - `document_type="dialog"`
- Build unit fields:
  - `unit_ref="dialog:<dialog_id>:message:<message_id>"`
  - `unit_type="message"`
  - `order_key=f"{message_id:020d}"`; Telegram message ids inside one dialog are non-negative, and tests assert a negative dialog id does not affect the order key.
  - `metadata_json` includes `dialog_id`, `dialog_name`, `message_id`, `sent_at`, `sender_id`, `sender_name`, `topic_id`, `topic_title`, `reply_to_msg_id`, `edit_date`, `is_deleted`, and `standalone_search`.
- Implement `is_low_signal_telegram_text(text: str) -> bool` with conservative rules:
  - empty/whitespace is low signal;
  - casefolded text in `{"ok", "yes", "yep", "no", "+1", "thanks", "thx", "да", "нет", "ок", "окей", "спасибо", "ага", "угу"}` is low signal;
  - punctuation-only text is low signal using `not any(ch.isalnum() for ch in text)`;
  - emoji-only text is low signal by treating text with no alphanumeric characters and at least one non-ASCII symbol category as low signal; implement this with `unicodedata.category(ch).startswith("S")` and no new dependency.
  - otherwise not low signal.
- Implement deterministic fingerprinting over normalized text plus `sent_at`, `edit_date`, `is_deleted`, `sender_id`, `topic_id`, `reply_to_msg_id`, and `unit_updated_at`.
- Fingerprinting must serialize optional metadata with sorted JSON keys and explicit `None`/`null` values for missing optional fields.
- Add a grep-proven guard in tests that `telegram_provider.py` does not contain `telethon`, `sync_db`, or `list_messages`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q</automated>
<automated>rg -n "telethon|sync_db|list_messages" backend/src/dotmd/ingestion/telegram_provider.py || true</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `class TelegramApplicationSourceProvider`.
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `class TelegramSourceClientProtocol` or `TelegramSourceClientProtocol`.
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `def is_low_signal_telegram_text`.
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `def public_ref_for_unit`.
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `unicodedata`.
- `backend/src/dotmd/ingestion/telegram_provider.py` contains `standalone_search`.
- `backend/src/dotmd/core/models.py` contains `updated_after: str | None = None`.
- `backend/src/dotmd/ingestion/telegram_provider.py` does not contain `telethon`.
- `backend/src/dotmd/ingestion/telegram_provider.py` does not contain `sync_db`.
- `backend/src/dotmd/ingestion/telegram_provider.py` does not contain `list_messages`.
- `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q
```
</verification>

<success_criteria>
- dotMD can consume structured Telegram source payloads through the Phase 28 provider protocol.
- Message refs, fingerprints, metadata, and low-signal classification are deterministic and fixture-tested.
- No dotMD provider code depends on Telethon, private sync DB tables, or rendered Telegram tool output.
</success_criteria>

## PLANNING COMPLETE
