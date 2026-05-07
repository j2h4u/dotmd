# mcp-telegram Source Contract for dotMD

Phase 28 defines the structured boundary that Phase 29 should implement. It
does not ship Telegram ingestion in dotMD.

dotMD does not import Telethon, instantiate a Telegram API client, or read
private `mcp-telegram` SQLite tables. The `mcp-telegram` side owns Telegram
authentication, sync, dialog/message storage, and daemon access. dotMD consumes
only structured provider payloads.

Required provider methods:

- `describe_source()`
- `export_changes(cursor, limit)`
- `read_unit_window(unit_ref, before, after)`

## Telegram Mapping

```text
namespace = "telegram"
SourceDocument.document_ref = "dialog:<dialog_id>"
SourceDocument.ref = "telegram:dialog:<dialog_id>"
SourceUnit.unit_ref = "dialog:<dialog_id>:message:<message_id>"
```

`SourceDocument` represents a dialog, channel, group, or supergroup. A Telegram
message is a `SourceUnit`. The message unit owns the recomputation boundary for
text, fingerprint, ordering, update time, and source-specific metadata.

## Source Description

```json
{
  "namespace": "telegram",
  "source_kind": "chat",
  "display_name": "Telegram",
  "capabilities": ["incremental-export", "unit-window"],
  "metadata_json": {
    "transport": "mcp-telegram-daemon"
  }
}
```

## Change Export

`export_changes(cursor, limit)` returns active records only in Phase 28. It
carries documents and units together so dotMD can persist source-document,
source-unit fingerprint, binding/provenance, and index state in one local
transaction.

```json
{
  "changes": [
    {
      "document": {
        "namespace": "telegram",
        "document_ref": "dialog:12345",
        "ref": "telegram:dialog:12345",
        "title": "Project Chat",
        "source_uri": "telegram://dialog/12345",
        "media_type": "text/plain",
        "parser_name": "telegram-message",
        "document_type": "dialog",
        "updated_at": "2026-05-07T12:00:00+00:00",
        "content_fingerprint": "dialog-content-12345",
        "metadata_fingerprint": "dialog-meta-12345",
        "metadata_json": {
          "dialog_id": 12345,
          "dialog_type": "supergroup",
          "username": "project_chat"
        }
      },
      "unit": {
        "namespace": "telegram",
        "document_ref": "dialog:12345",
        "unit_ref": "dialog:12345:message:67890",
        "unit_type": "message",
        "text": "The deployment checklist is ready.",
        "order_key": "0000067890",
        "fingerprint": "message-content-67890",
        "updated_at": "2026-05-07T12:00:00+00:00",
        "metadata_json": {
          "sender_id": 111,
          "sender_name": "Alice",
          "topic_id": 7,
          "topic_title": "Deployments",
          "reply_to_msg_id": 67880,
          "edit_date": null
        },
        "chunking_hints": {}
      }
    }
  ],
  "next_cursor": "dialog:12345:message:67891",
  "checkpoint_cursor": "dialog:12345:message:67890"
}
```

`next_cursor` is only the provider's continuation hint. dotMD persists
`checkpoint_cursor` only after local source-document, source-unit fingerprint,
binding/provenance, and index persistence succeeds. Saving `next_cursor` before
that transaction would risk losing source units after a crash.

## Unit Window

`read_unit_window(unit_ref, before, after)` returns neighboring source units
when the source can provide them. Providers without useful neighbors may return
only the requested unit.

```json
{
  "namespace": "telegram",
  "document_ref": "dialog:12345",
  "unit_ref": "dialog:12345:message:67890",
  "units": [
    {
      "namespace": "telegram",
      "document_ref": "dialog:12345",
      "unit_ref": "dialog:12345:message:67889",
      "unit_type": "message",
      "text": "Can someone verify the migration window?",
      "order_key": "0000067889",
      "fingerprint": "message-content-67889",
      "updated_at": "2026-05-07T11:59:00+00:00",
      "metadata_json": {
        "sender_id": 222,
        "sender_name": "Bob",
        "topic_id": 7,
        "reply_to_msg_id": null,
        "edit_date": null
      },
      "chunking_hints": {}
    },
    {
      "namespace": "telegram",
      "document_ref": "dialog:12345",
      "unit_ref": "dialog:12345:message:67890",
      "unit_type": "message",
      "text": "The deployment checklist is ready.",
      "order_key": "0000067890",
      "fingerprint": "message-content-67890",
      "updated_at": "2026-05-07T12:00:00+00:00",
      "metadata_json": {
        "sender_id": 111,
        "sender_name": "Alice",
        "topic_id": 7,
        "reply_to_msg_id": 67880,
        "edit_date": null
      },
      "chunking_hints": {}
    },
    {
      "namespace": "telegram",
      "document_ref": "dialog:12345",
      "unit_ref": "dialog:12345:message:67891",
      "unit_type": "message",
      "text": "I will run the smoke check after restart.",
      "order_key": "0000067891",
      "fingerprint": "message-content-67891",
      "updated_at": "2026-05-07T12:01:00+00:00",
      "metadata_json": {
        "sender_id": 333,
        "sender_name": "Carol",
        "topic_id": 7,
        "reply_to_msg_id": 67890,
        "edit_date": null
      },
      "chunking_hints": {}
    }
  ],
  "metadata_json": {
    "dialog_id": 12345
  }
}
```

## Scope Exclusions

Phase 28 does not define a full delete, hidden-message, or tombstone lifecycle
for the common provider contract. That remains source-specific metadata until a
later phase designs public read/drill behavior for deleted upstream content.

Phase 28 also excludes attachments/media, direct Telegram API ownership in
dotMD, and any generic plugin marketplace. There is no direct Telegram API
client in dotMD.

No Phase 28 provider-contract work requires `dotmd index --force`, a full
reindex, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild.
