# v1.5 Architecture Research: Application Source Adapter Through Telegram

## Architectural Intent

This milestone should move dotMD from "filesystem Markdown with source refs" to
"application sources with reusable content-addressed indexing." Telegram is the
first proving source, but the storage and sync model should not bake in
Telegram-only assumptions.

## Current Model

Current dotMD source identity is document-level:

- `SourceDocument(namespace, document_ref, ref, ...)`
- `ChunkProvenance(namespace, document_ref, source_unit_refs, ...)`
- filesystem refs use `filesystem:<absolute_path>`
- `read(ref)` still resolves to a filesystem path internally

This was enough for Phase 25/26, but not enough for application sources where a
document may be a dialog, topic, export slice, or logical resource, and content
units may be individual messages/events.

## Target Model

### Resource Binding

A resource binding says: "this active source resource currently points to this
content identity or content unit set."

Examples:

- filesystem path `/mnt/docs/a.md`
- Telegram dialog `dialog_id=-100...`
- Telegram message `dialog_id=-100..., message_id=123`
- future app source item such as a Linear issue, Slack message, GitHub issue, or
  Notion page

Bindings are visible-state. If a resource disappears, the active binding is
removed or marked inactive immediately.

### Retained Content/Derived Artifact

Retained content is content-addressed and not deleted just because one binding
disappears. Derived artifacts include parsed units, chunks, embeddings, graph
extractions, and FTS/vector rows when they can be safely reused.

This is the Borg-like property the user wants: identity/binding churn should
not force recomputation of already processed content.

### Source Unit

For Telegram, a source unit should be close to a message, not the whole chat.
The whole dialog hash changes whenever a new message appears, but most previous
message units stay unchanged. Therefore:

- dialog/document fingerprint is useful for sync/catalog metadata;
- message/source-unit fingerprint is the recomputation boundary;
- chunk fingerprint and embedding text hash remain the lower-level reuse keys.

## Telegram Reference Shape

Candidate durable refs:

- dialog document ref: `telegram:dialog:<dialog_id>`
- topic document ref when needed: `telegram:dialog:<dialog_id>:topic:<topic_id>`
- message source unit ref: `message:<message_id>`

The public `ref` returned by search can point at a logical Telegram document or
a more specific message-context document, but it must remain resolvable through
`drill(ref)` and `read(ref, ...)`.

The first implementation should choose the smallest ref shape that supports:

- source metadata in `drill`;
- ranged/contextual `read`;
- stable search result refs;
- later edit/delete handling without public API churn.

## mcp-telegram Contract Options

### Option A: Use Existing MCP Tools Only

Pros:

- no cross-repo API work before dotMD implementation;
- live smoke is easy;
- works with current deployed runtime.

Cons:

- `list_messages` is a browsing/read API with human-oriented rendering and
  pagination semantics;
- complete corpus export would be slow and awkward;
- incremental sync would depend on opaque navigation tokens or repeated
  scanning;
- not a clean reusable application-source contract.

### Option B: Add A Structured Source Export Surface To mcp-telegram

Pros:

- stable machine contract for dotMD and future consumers;
- can expose `dialogs`, `messages_since`, `changes_since`, or equivalent cursor
  APIs;
- keeps Telegram-specific sync complexity in mcp-telegram;
- gives dotMD a provider-agnostic ingestion shape.

Cons:

- requires small cross-repo work;
- needs versioned schema discipline;
- must not expose mutable private DB details accidentally.

Recommended path: plan for Option B if current tools cannot satisfy efficient
incremental export. Keep existing tools for read-context fallback and smoke
tests.

## Proposed Phase Order

1. Content-addressed resource bindings and retained artifacts foundation.
2. Application source-provider contract and Telegram provider shape.
3. Telegram adapter MVP: ingest selected synced dialogs/messages into dotMD.
4. Incremental sync and search/read/drill hardening.
5. Live smoke and regression pass across filesystem plus Telegram.

This order puts the recomputation boundary before Telegram ingestion, which
avoids building a Telegram-specific rename/reindex workaround that later has to
be replaced.
