# v1.5 Feature Research: Telegram Source Adapter

## Product Goal

After v1.5, Telegram should behave like a first-class dotMD source:

- selected synced Telegram dialogs become searchable through dotMD;
- a search hit can be drilled/read back to the Telegram message context;
- repeated sync avoids recomputing chunks, embeddings, and derived artifacts for
  unchanged content;
- the same adapter pattern can be reused for future application sources.

## Current Capabilities Already Present

dotMD already has:

- public search results with `ref` instead of path-first read keys;
- `read(ref, start, end)` and `drill(ref)` at the MCP facade;
- source document rows and chunk provenance;
- split body/metadata fingerprints for filesystem documents;
- chunk/file-path M2M storage that proves one chunk can belong to more than one
  holder;
- text-hash embedding reuse.

mcp-telegram already has:

- discovery of dialogs and sync status;
- explicit mark-for-sync command;
- local message mirror in SQLite;
- message identity via `(dialog_id, message_id)`;
- dialog/topic/message metadata useful for source refs and context rendering;
- search-to-read workflow via `search_messages` result anchors and
  `list_messages(exact_dialog_id, anchor_message_id)`;
- delete/edit alert surfaces.

## MVP Feature Set

### Application Source Foundation

- Introduce source-resource bindings that are not filesystem-path-specific.
- Separate active resource bindings from retained content/derived artifacts.
- Hide inactive/unbound content from public search/read while retaining it for
  reuse until explicit garbage collection.
- Reuse existing chunks/embeddings/artifacts when the same content unit appears
  under a new binding.
- Preserve existing filesystem behavior during migration.

### Telegram Source Adapter

- Configure a Telegram source namespace backed by existing `mcp-telegram`.
- Discover candidate dialogs and their sync status.
- Select which dialogs are in dotMD scope.
- Ingest Telegram message source units with stable refs and provenance.
- Preserve enough metadata for drill/read: dialog id/name, message id, sent_at,
  sender label/id when available, topic id/title when available, edit/delete
  metadata when available.

### Incremental Sync

- Keep per-source or per-dialog cursors for what dotMD has consumed from the
  source provider.
- On repeat sync, process only new or changed source units.
- Skip chunking and embedding for unchanged source-unit content.
- Report counts for discovered, new, changed, rebound, skipped, hidden, and
  failed units.

### Search And Read

- dotMD `search` returns Telegram-backed refs alongside filesystem refs.
- `drill(ref)` returns Telegram source metadata without assuming filesystem
  frontmatter.
- `read(ref, start, end)` returns message context/chunks for Telegram refs.
- Search-to-read round-trip works in MCP smoke tests.

## Explicit Non-MVP Items

- Full Telegram lifecycle policy for edits/deletes/TTL beyond minimal inactive
  filtering.
- Attachments/media indexing.
- Contact/entity identity catalog shared across sources.
- Direct Telegram API client inside dotMD.
- Bidirectional Telegram actions.
- General app-source plugin marketplace.

## Generalization For Later App Sources

The reusable part is not "Telegram". It is the pattern:

- source namespace;
- resource binding;
- source unit;
- content fingerprint;
- derived artifact reuse;
- sync cursor;
- active/inactive visibility;
- source-specific read/drill renderer.

Telegram should validate this pattern because it has real incremental updates,
renames/identity concerns, edits, deletions, and high recomputation cost.
