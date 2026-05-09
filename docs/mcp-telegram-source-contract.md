# mcp-telegram Source Contract for dotMD

Phase 28 defined the structured boundary and Phase 29 implements the initial
Telegram ingestion/resolver slice in dotMD.

dotMD does not import Telethon, instantiate a Telegram API client, or read
private `mcp-telegram` SQLite tables. The `mcp-telegram` side owns Telegram
authentication, sync, dialog/message storage, and daemon access. dotMD consumes
only structured provider payloads.

Required provider methods:

- `describe_source()`
- `export_changes(cursor, limit)`
- `read_unit_window(unit_ref, before, after)`

On the `mcp-telegram` daemon API these are exposed as:

- `describe_source`
- `export_source_changes`
- `read_source_unit_window`

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

`export_source_changes(cursor, limit)` returns active records. It carries
documents and units together so dotMD can persist source-document, source-unit
fingerprint, binding/provenance, and index state in one local transaction.

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
  "next_cursor": "telegram:v1:dialog:12345:message:67891",
  "checkpoint_cursor": "telegram:v1:dialog:12345:message:67890"
}
```

`next_cursor` and `checkpoint_cursor` use the daemon identity cursor shape
`telegram:v1:dialog:<dialog_id>:message:<message_id>`. `next_cursor` is only the
provider's continuation hint. dotMD persists `checkpoint_cursor` only after
local source-document, source-unit fingerprint, binding/provenance, and index
persistence succeeds. Saving `next_cursor` before that transaction would risk
losing source units after a crash.

## Unit Window

`read_source_unit_window(unit_ref, before, after)` returns neighboring source
units when the source can provide them. Providers without useful neighbors may
return only the requested unit.

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

Phase 29 does not define a full delete, hidden-message, or tombstone lifecycle
for the common provider contract. That remains source-specific metadata until a
later phase designs public read/drill behavior for deleted upstream content.

Phase 29 also excludes attachments/media, direct Telegram API ownership in
dotMD, and any generic plugin marketplace. There is no direct Telegram API
client in dotMD.

No Phase 29 Telegram provider work requires `dotmd index --force`, a full
reindex, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild.

## Phase 29 Runtime Boundary

dotMD consumes the existing `mcp-telegram` daemon over newline-delimited JSON
on a UNIX socket. Phase 29 supports only:

```text
DOTMD_TELEGRAM_DAEMON_SOCKET=/mcp-telegram-state/daemon.sock
```

There is no HTTP daemon URL setting in this phase. In the current Docker
deployment the source socket is created by the `mcp-telegram` container inside
the `mcp-telegram_state` Docker volume at:

```text
/root/.local/state/mcp-telegram/daemon.sock
```

The production dotMD compose layer should mount that volume into the dotMD
container and set `DOTMD_TELEGRAM_DAEMON_SOCKET` to the in-container path before
running live ingest smoke. dotMD still does not read private `mcp-telegram`
SQLite tables; the mount is for the daemon socket only.

## Phase 34: Federated FTS Search

Phase 34 adds a `search_messages` daemon-socket method to enable federated FTS
search without requiring messages to be indexed locally. The method allows dotMD
to present Telegram search results directly from the daemon's FTS index.

### search_messages Method

Request (daemon method):

```json
{
  "method": "search_messages",
  "query": "kantine",
  "limit": 20,
  "dialog_id": null
}
```

Response:

```json
{
  "ok": true,
  "data": {
    "hits": [
      {
        "dialog_id": 12345,
        "dialog_name": "Project Chat",
        "message_id": 67,
        "text": "The kantine has been refurbished.",
        "sender": "alice",
        "sent_at": "2026-04-12T08:11:00+00:00",
        "score": 0.93
      }
    ]
  }
}
```

### SearchCandidate Mapping

Telegram FTS search results map to `SearchCandidate`:

- **ref:** `"telegram:dialog:<dialog_id>:message:<message_id>"`
- **namespace:** `"telegram"`
- **descriptor_key:** `"telegram"` (identifies the source descriptor)
- **source_kind:** `"chat"`
- **retrieval_kind:** `"tg:fts"`
- **title:** `dialog_name` from the hit
- **snippet:** `text` from the hit (message preview)
- **can_read:** `True` if the provider supports `read_unit_window`
- **can_materialize:** `False` (Phase 34 invariant)
- **source_native_score:** `score` from the hit (FTS score)
- **source_native_rank:** Zero-based rank (0, 1, 2, ... for a 5-hit response)
- **provider_metadata:** Whitelist only `{dialog_id, message_id, sender, sent_at, dialog_name}`. Credentials, phone numbers, auth tokens, session paths, api_id, api_hash MUST NOT appear.

### Read Routing (Local-First)

When `read(ref)` is called for a Telegram ref:

1. Check local store: if the ref exists locally with an **active** binding,
   use the local chunks path (existing behavior).
2. Check local store: if the ref exists locally with an **inactive** binding,
   raise `PermissionError`. Phase 27 visibility gate is preserved; DO NOT
   fall back to the federated provider.
3. No local presence: call `provider.read_unit_window(unit_ref, before, after)`
   to fetch context from the daemon. Returns a `SourceUnitWindow` with units
   and metadata.

Error handling: If `read_unit_window` fails, wrap as:
`RuntimeError("telegram: <original error message>")`

This preserves provider attribution while staying compatible with the Phase 26
public error contract.

### No Materialization in Phase 34

Federated search results have `can_materialize=False`. The Phase 34 contract
does not add write-back semantics. Materialization (storing Telegram messages
into the local index for offline access) is deferred to a future phase.
