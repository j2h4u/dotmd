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
    - "Review-HIGH: Cursor pagination and update-watermark pagination are separate streams: checkpoint_cursor advances only from identity/bootstrap rows, while updated_after and updated_after_cursor advance only from update rows."
    - "Review-HIGH: unit_updated_at precision, equality, and tie-break behavior are pinned: UTC ISO-8601 microseconds where available, strict timestamp plus cursor tie-break comparisons when precision is only seconds."
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
| Export cursor skips messages after a crash | HIGH | Return `checkpoint_cursor` as the highest identity/bootstrap row emitted, never as a lower-id update-watermark row. |
| Edited existing messages never reach dotMD | HIGH | Add `updated_after` to `export_source_changes`; export rows whose `unit_updated_at` is newer than the caller watermark even when their message id is before the identity cursor. |
| Mixed cursor and watermark rows produce ambiguous ordering | HIGH | Treat identity rows and update rows as separate streams in one response: identity rows advance `checkpoint_cursor`, update rows advance `updated_after` plus `updated_after_cursor`; tests cover interleaved batches. |
| Same-second edits are missed by strict watermark comparison | HIGH | Normalize `unit_updated_at` to UTC ISO-8601 with microseconds where available and use `(unit_updated_at, dialog_id, message_id)` tie-break semantics through `updated_after_cursor`. |
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
- `export_source_changes(cursor=<identity cursor>, limit=10, updated_after=<timestamp>, updated_after_cursor=<watermark cursor>)` returns both identity/bootstrap rows and update rows without letting a lower-id update row move `checkpoint_cursor` backwards.
- Watermark equality is deterministic: rows with `unit_updated_at == updated_after` are exported only when their `(dialog_id, message_id)` is greater than `updated_after_cursor`; rows at or before that tie-break cursor are not exported again.
- Each record has `document` and `unit` objects with refs matching `telegram:dialog:<dialog_id>` and `dialog:<dialog_id>:message:<message_id>`.
- The response includes `checkpoint_cursor` for the highest emitted identity/bootstrap unit and `next_cursor` only when more identity/bootstrap records exist.
- The response includes `updated_after` as the max exported `unit_updated_at` watermark for dotMD to persist in checkpoint metadata.
- The response includes `updated_after_cursor` as the cursor of the last row at the returned `updated_after` timestamp, so second-precision stores cannot drop same-second edits.
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
- Add a mixed-stream fixture:
  - caller sends `cursor="telegram:v1:dialog:-1001:message:50"`, `updated_after="2026-05-08T00:00:00.000000Z"`, and `updated_after_cursor="telegram:v1:dialog:-1001:message:20"`;
  - stored identity/bootstrap candidate exists at `dialog:-1001:message:51`;
  - edited already-exported update candidate exists at `dialog:-1001:message:30` with `unit_updated_at="2026-05-08T00:01:00.000000Z"`;
  - response includes both messages when limit permits;
  - response `checkpoint_cursor` is `telegram:v1:dialog:-1001:message:51`, not the lower update row cursor for message `30`;
  - response `updated_after` is `2026-05-08T00:01:00.000000Z`;
  - response `updated_after_cursor` is `telegram:v1:dialog:-1001:message:30`.
- Add an equality fixture with two edited rows sharing `unit_updated_at="2026-05-08T00:01:00.000000Z"`:
  - with `updated_after` equal to that timestamp and `updated_after_cursor` at the first row, only the second row is returned;
  - with `updated_after_cursor` at the second row, neither equal-timestamp row is returned.
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
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` asserts mixed identity/update batches keep `checkpoint_cursor` on the highest identity row rather than the last update row.
- `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py` asserts same-timestamp update rows use `updated_after_cursor` tie-break semantics.
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
  - accepts optional `updated_after_cursor` as `None` or `telegram:v1:dialog:<dialog_id>:message:<message_id>` and parses it with the same negative-dialog-safe parser as `cursor`;
  - selects stored messages from `synced_dialogs.status IN ('synced', 'syncing', 'access_lost')`;
  - computes `unit_updated_at` for every exported row as the greatest available timestamp among `sent_at`, `edit_date`, and any sync/cache update timestamp available in the daemon storage; normalize it to UTC ISO-8601 with microseconds when the source value has microseconds, otherwise zero-fill microseconds and rely on `updated_after_cursor` for same-second ties; if no cache update timestamp exists, use `max(sent_at, edit_date)` and document that delete lifecycle remains Phase 30;
  - builds identity/bootstrap rows from stored messages where `(dialog_id, message_id)` is after `cursor`, ordered by `dialog_id ASC, message_id ASC`;
  - builds update-watermark rows from stored messages where `unit_updated_at > updated_after OR (unit_updated_at = updated_after AND (dialog_id, message_id) > parsed(updated_after_cursor))`, ordered by `unit_updated_at ASC, dialog_id ASC, message_id ASC`;
  - excludes update-watermark rows that are also in the identity row set for the current response so a new message is emitted once;
  - merges the two streams as identity rows first, then update rows, and clamps the combined response to `limit`; the limit applies to the total combined response, not per stream;
  - emits `document` and `unit` dicts matching `docs/mcp-telegram-source-contract.md`;
  - uses `document_ref = "dialog:<dialog_id>"`;
  - uses `unit_ref = "dialog:<dialog_id>:message:<message_id>"`;
  - sets `checkpoint_cursor` to the highest emitted identity/bootstrap row cursor; if the response contains only update-watermark rows, keep the incoming `cursor` as `checkpoint_cursor` so identity pagination cannot move backwards or skip ahead;
  - sets response `updated_after` to the maximum emitted update-watermark row `unit_updated_at`; if the response contains no update rows, preserve the incoming `updated_after`;
  - sets response `updated_after_cursor` to the last emitted update-watermark row cursor at the response `updated_after`; if the response contains no update rows, preserve the incoming `updated_after_cursor`;
  - sets `next_cursor` when there are more stored identity/bootstrap rows after the returned `checkpoint_cursor`.
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
- Exported payloads contain batch-level `updated_after_cursor`.
- Mixed identity/update export tests prove the worked example `cursor=...message:50` plus update row `message:30` returns `checkpoint_cursor=...message:51` and `updated_after_cursor=...message:30`.
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
