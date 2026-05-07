---
phase: "29"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py
  - /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py
  - /home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py
autonomous: true
requirements: ["R4", "R5", "R8"]
requirements_addressed: ["R4", "R5", "R8"]
must_haves:
  truths:
    - "D-01: Export covers all dialogs already available/synced through mcp-telegram; no dotMD allowlist is added."
    - "D-02: mcp-telegram remains the source of Telegram coverage and sync state."
    - "D-11: dotMD must not read private mcp-telegram SQLite tables and must not parse rendered list_messages text."
    - "D-12: Phase 29 includes the minimal mcp-telegram change needed for a structured export/source API."
    - "D-13: API shape stays aligned with describe_source, export_changes(cursor, limit), checkpoint cursor semantics, and read_unit_window."
    - "D-14: Live smoke scope is export -> dotMD ingest -> Telegram records in dotMD state, not full public search quality."
    - "Review-HIGH: Phase 29 export must deliver edits to already-exported messages via an update watermark; cursor-only identity pagination is not sufficient."
    - "Full-reindex answer: this plan changes mcp-telegram daemon/client API only; no dotMD index force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild."
---

# Phase 29 Plan 01: mcp-telegram Source Export API

<objective>
Add the structured `mcp-telegram` source export/read-window API that dotMD can
consume without reading private SQLite tables or parsing human-rendered tool
output.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| dotMD couples to private `mcp-telegram` SQLite schema | HIGH | Expose a daemon/client JSON API and test that dotMD plans target that API, not `sync.db`. |
| Export cursor skips messages after a crash | HIGH | Return `checkpoint_cursor` as the last emitted unit and leave commit ownership to dotMD. |
| Edited existing messages never reach dotMD | HIGH | Add `updated_after` to `export_source_changes`; export rows whose `unit_updated_at` is newer than the caller watermark even when their message id is before the identity cursor. |
| Export accidentally uses rendered `list_messages` text | HIGH | Add tests asserting structured fields such as `document`, `unit`, `unit_ref`, and `checkpoint_cursor`. |
| Unsynced or unavailable dialogs leak into export | MEDIUM | Export only stored rows from synced/syncing/access_lost dialogs with messages. |
| Message metadata needed for provenance is omitted | MEDIUM | Include dialog id/name/type, message id, sent_at, sender, topic, reply, edit/delete fields. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add structured export API tests</title>
<name>Add structured export API tests</name>
<read_first>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/models.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/sync_db.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py`
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md`
- `docs/mcp-telegram-source-contract.md`
</read_first>
<files>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py`
</files>
<behavior>
- `describe_source` returns namespace `telegram`, source kind `chat`, display name `Telegram`, and capabilities containing `incremental-export` and `unit-window`.
- `export_source_changes(cursor=None, limit=2)` returns structured records sorted by `(dialog_id, message_id)` over stored synced dialogs.
- `export_source_changes(cursor=None, limit=10, updated_after=<timestamp>)` returns edited already-exported records whose `unit_updated_at` is newer than the watermark.
- Each record has `document` and `unit` objects with refs matching `telegram:dialog:<dialog_id>` and `dialog:<dialog_id>:message:<message_id>`.
- The response includes `checkpoint_cursor` for the last emitted unit and `next_cursor` only when more records exist.
- The response includes `updated_after` as the max exported `unit_updated_at` watermark for dotMD to persist in checkpoint metadata.
</behavior>
<action>
Add failing tests in `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` for three new daemon methods:

- `describe_source`
- `export_source_changes`
- `read_source_unit_window`

Concrete test fixtures:
- Insert two synced dialogs into `synced_dialogs` with statuses `synced` and `access_lost`, plus one `not_synced` dialog that must not be exported.
- Insert messages with `dialog_id`, `message_id`, `sent_at`, `text`, `sender_id`, `sender_first_name`, `reply_to_msg_id`, `forum_topic_id`, `edit_date`, `is_deleted`, and `topic_title` where the schema/test helper supports it.
- Assert exported unit refs are exactly `dialog:<dialog_id>:message:<message_id>`.
- Assert no exported payload contains formatted lines such as `[resolved:` or `next_navigation`.
- Assert `checkpoint_cursor` has shape `telegram:v1:dialog:<dialog_id>:message:<message_id>`.
- Assert negative dialog cursor parsing uses a parser equivalent to `rsplit(":message:", 1)` so `telegram:v1:dialog:-1001:message:42` is valid.
- Assert an edited message with `message_id` lower than the current cursor is returned when `updated_after` is older than its `edit_date`.
- Assert exported record `unit.metadata_json.topic_title` is present with a string or `None`; do not leave topic title storage as an executor decision.
</action>
<verify>
<automated>cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q</automated>
</verify>
<acceptance_criteria>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `describe_source`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `export_source_changes`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `read_source_unit_window`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `checkpoint_cursor`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `updated_after`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `rsplit(":message:", 1)` or asserts the equivalent negative-dialog cursor parser behavior.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` contains `telegram:v1:dialog:`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` asserts a `not_synced` dialog is excluded.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` asserts an edited existing message is exported through `updated_after`.
- The focused pytest command initially fails before implementation and exits 0 after implementation.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Implement daemon source export and read-window handlers</title>
<name>Implement daemon source export and read-window handlers</name>
<read_first>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/models.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py`
</read_first>
<files>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py`
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py`
</files>
<behavior>
- Daemon handlers return stable JSON payloads suitable for dotMD provider mapping.
- Cursor parsing rejects malformed cursors with `{"ok": false, "error": "invalid_cursor"}`.
- Edit delivery uses an update watermark in addition to identity cursor pagination.
- `read_source_unit_window(unit_ref, before, after)` returns neighboring messages around the target from stored sync DB rows.
</behavior>
<action>
Implement the daemon/client API.

Concrete target state:
- Add `_describe_source(self, req)` returning:
  - `namespace: "telegram"`
  - `source_kind: "chat"`
  - `display_name: "Telegram"`
  - `capabilities: ["incremental-export", "unit-window"]`
  - `metadata_json.transport: "mcp-telegram-daemon"`
- Add `_export_source_changes(self, req)`:
  - clamps `limit` to `1..500`;
  - accepts `cursor` as `None` or `telegram:v1:dialog:<dialog_id>:message:<message_id>`;
  - parses the cursor with `rsplit(":message:", 1)` and then strips prefix `telegram:v1:dialog:` so negative dialog ids are valid;
  - accepts optional `updated_after` as an ISO timestamp or integer epoch string;
  - selects stored messages from `synced_dialogs.status IN ('synced', 'syncing', 'access_lost')`;
  - computes `unit_updated_at` for every exported row as the greatest available timestamp among `sent_at`, `edit_date`, and any sync/cache update timestamp available in the daemon storage; if no cache update timestamp exists, use `max(sent_at, edit_date)` and document that delete lifecycle remains Phase 30;
  - emits rows matching either `(dialog_id, message_id)` after `cursor` OR `unit_updated_at > updated_after`;
  - orders primary bootstrap rows by `dialog_id ASC, message_id ASC` and edited/update-watermark rows by `unit_updated_at ASC, dialog_id ASC, message_id ASC`;
  - emits `document` and `unit` dicts matching `docs/mcp-telegram-source-contract.md`;
  - uses `document_ref = "dialog:<dialog_id>"`;
  - uses `unit_ref = "dialog:<dialog_id>:message:<message_id>"`;
  - sets `checkpoint_cursor` to the last emitted unit cursor for non-empty batches;
  - sets response `updated_after` to the maximum emitted `unit_updated_at` for non-empty batches;
  - sets `next_cursor` when there are more stored rows after the current batch.
- Add `_read_source_unit_window(self, req)`:
  - parses `unit_ref`;
  - clamps `before` and `after` to `0..50`;
  - returns units before/target/after sorted by message id;
  - returns `not_found` if target does not exist in stored messages.
- Route the three methods from `_dispatch`.
- Add `DaemonConnection.describe_source()`, `DaemonConnection.export_source_changes(cursor, limit, updated_after=None)`, and `DaemonConnection.read_source_unit_window(unit_ref, before, after)`.
</action>
<verify>
<automated>cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q</automated>
<automated>rg -n "export_source_changes|read_source_unit_window|describe_source|telegram:v1:dialog" /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram /home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py</automated>
</verify>
<acceptance_criteria>
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` contains `def _export_source_changes`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` contains `def _read_source_unit_window`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` routes method `export_source_changes`.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py` contains `async def export_source_changes`.
- Exported payloads contain `document`, `unit`, `checkpoint_cursor`, and `metadata_json`.
- Exported payloads contain `unit_updated_at` on each unit metadata payload and batch-level `updated_after`.
- No implementation path returns rendered `list_messages` text as the export body.
- `cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q
```
</verification>

<success_criteria>
- `mcp-telegram` exposes structured source description, source changes, and source-unit windows through the daemon/client boundary.
- Exported units use stable dialog/message identity and checkpoint cursors.
- dotMD can consume Telegram data through this API without importing Telegram runtime internals.
</success_criteria>

## PLANNING COMPLETE
