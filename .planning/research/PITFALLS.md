# v1.5 Pitfalls: Telegram Source Adapter

## Pitfall 1: Treating Telegram As A One-Off Import

If the adapter stores Telegram rows directly into path-shaped assumptions, the
next app source will repeat the same work. The milestone should explicitly
separate the generic application-source model from Telegram-specific mapping.

## Pitfall 2: Hashing Whole Dialogs As The Recompute Boundary

A chat-level hash changes on every new message. That would cause repeated
reprocessing of unchanged history. The recompute boundary must be the source
unit, usually a message or a bounded message segment, with dialog-level state
used for sync/catalog decisions only.

## Pitfall 3: Using `search_messages` As An Indexing Source

`search_messages` returns relevant hits for a query, not the complete source
corpus. It is useful for live smoke and read comparison, but not for dotMD
index construction.

## Pitfall 4: Using Human-Rendered `list_messages` As The Bulk API

`list_messages` is optimized for agents reading Telegram context. It returns
formatted text and navigation. Bulk sync needs structured records, stable
cursors, and deterministic ordering. Using rendered output would make parsing
fragile and would mix display policy with indexing policy.

## Pitfall 5: Coupling dotMD To Private mcp-telegram Tables

Direct read-only access to `sync.db` is tempting because it is efficient, but
it couples dotMD to mcp-telegram internals. If used at all, it should be behind
an explicit source-provider contract or exported view whose schema is treated
as stable.

## Pitfall 6: Leaking Inactive Content Through Search

Retaining unbound content for reuse is only safe if public search/read filter
through active bindings. Removed resources can stay in retained storage, but
must not keep appearing as current results.

## Pitfall 7: Deleting Derived Artifacts Too Early

Immediate purge on missing binding defeats the user's goal: avoid spending CPU
again for content that may reappear under another resource. Deactivation and
garbage collection must be separate operations.

## Pitfall 8: Ignoring Telegram Edits And Deletes

mcp-telegram already tracks delete/edit signals. The MVP can keep lifecycle
policy narrow, but the source model must not make edits/deletes impossible to
represent later.

## Pitfall 9: Accidentally Owning Telegram Runtime Complexity In dotMD

FloodWaits, Telethon session state, live events, catch-up, and auth belong in
mcp-telegram. dotMD should consume a local/source-provider surface and keep
its own responsibility to indexing and retrieval.

## Pitfall 10: Overbuilding A Generic Plugin Framework First

The architecture should be generalizable, but the implementation should be
driven by Telegram search+sync. Build the smallest generic foundation that
Telegram proves, then extend from actual second-source pressure.
