# v1.5 Stack Research: Telegram Source Adapter

## Scope

Milestone v1.5 uses Telegram as the first real application-source adapter, not
as a one-off import script. The foundation should generalize to later
application integrations while staying tested through a concrete Telegram MVP:
incremental sync plus search/read round-trip.

## Existing dotMD Stack

- Python 3.12+ backend, Click CLI, FastAPI/MCP facade.
- SQLite `index.db` stores metadata, FTS5, sqlite-vec vectors, chunk tables,
  source documents, and source provenance.
- Existing source abstraction:
  - `SourceDocument` in `backend/src/dotmd/core/models.py`.
  - `SourceUnit` model exists but is not yet wired into the filesystem path.
  - `ChunkProvenance` records namespace, document ref, parser, and source-unit
    refs per chunk.
  - `FilesystemMarkdownSourceAdapter` emits filesystem `SourceDocument` rows.
- Existing content-dedup substrate:
  - `chunks_<strategy>` is no longer keyed by path alone.
  - `chunk_file_paths_<strategy>` is an M2M holder for filesystem paths.
  - embeddings reuse `text_hash`.
  - body and metadata fingerprints are already split for filesystem Markdown.

## Existing mcp-telegram Stack

- Repo: `/home/j2h4u/repos/j2h4u/mcp-telegram`.
- Current head inspected during research: `c920596 feat: expose telegram MCP over streamable HTTP`.
- Runtime entrypoints:
  - `mcp-telegram sync` runs the sync daemon.
  - `mcp-telegram serve` runs the sync daemon and Streamable HTTP MCP endpoint
    in one process.
  - HTTP transport defaults to port `3100` and exposes `/mcp` plus `/health`.
- Daemon owns TelegramClient and sync cache. dotMD should not create a direct
  Telegram API client for this milestone.
- Existing MCP tools relevant to dotMD:
  - `list_dialogs`
  - `list_topics`
  - `list_messages`
  - `search_messages`
  - `mark_dialog_for_sync`
  - `get_sync_status`
  - `get_sync_alerts`
- Existing sync cache tables include:
  - `dialogs`
  - `synced_dialogs`
  - `messages` keyed by `(dialog_id, message_id)`
  - `message_versions`
  - `topic_metadata`
  - message reaction/entity/forward side tables.

## Integration Boundary

Recommended boundary for v1.5:

1. dotMD treats mcp-telegram as the Telegram source provider.
2. mcp-telegram remains responsible for Telegram auth, FloodWait handling,
   event catch-up, local mirror maintenance, deletions/edits capture, and
   dialog sync state.
3. dotMD owns application-source ingestion, content-addressed retention,
   chunking, embeddings, graph/FTS/vector indexing, search, read, and drill.
4. The durable source contract should be data-oriented, not shaped around
   human MCP rendering.

The current MCP tool surface is enough for live smoke and read-context
round-trip. It is not obviously sufficient as the bulk indexing API because
`list_messages` is paginated for agent browsing and `search_messages` is a
search tool, not a complete corpus export.

## Stack Decision To Carry Into Requirements

Telegram MVP should be allowed to require a small stable source/export surface
in `mcp-telegram` if the current MCP tools cannot provide efficient,
machine-oriented incremental export. That surface can still be exposed through
MCP/HTTP, but it should return structured source records suitable for dotMD
sync rather than formatted reading text.
