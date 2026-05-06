# v1.5 Research Summary: Telegram Source Adapter

## Recommendation

Proceed with v1.5 as a Telegram-backed application-source milestone, but make
the first phase the generic content-addressed resource binding foundation. This
matches the product goal: avoid recomputing already processed content and use
Telegram as the first validation case for future app integrations.

## Key Findings

- dotMD already has `SourceDocument`, `SourceUnit`, `ChunkProvenance`,
  `source_documents`, chunk/source provenance tables, path M2M storage, split
  fingerprints, and embedding text-hash reuse.
- dotMD still resolves public `read(ref)` and `drill(ref)` through filesystem
  paths, so non-filesystem sources need a new read/drill resolver path.
- mcp-telegram already owns the Telegram runtime and sync cache.
- mcp-telegram exposes useful MCP tools for discovery, sync control, search,
  and read-context smoke.
- Existing mcp-telegram tools are probably not enough as an efficient bulk
  indexing source because they are shaped around agent browsing/search.
- A small structured source/export surface in mcp-telegram may be necessary and
  should be treated as part of the application source-provider contract.

## Requirements Direction

The requirements should cover five areas:

1. Resource bindings and retained derived artifacts.
2. Application source-provider contract.
3. Telegram provider/adapter via existing mcp-telegram.
4. Incremental sync with source-unit recomputation boundaries.
5. Search/read/drill round-trip plus live smoke.

## Proposed Active Milestone Phases

1. Resource bindings and retained artifacts foundation.
2. Application source-provider contract with Telegram provider shape.
3. Telegram adapter MVP ingestion.
4. Incremental Telegram sync and recomputation avoidance.
5. Search/read/drill hardening and live smoke.

## Deferred Scope

- full edit/delete/TTL lifecycle policy;
- attachments/media;
- entity/contact catalog shared across sources;
- direct Telegram API client in dotMD;
- generic plugin marketplace or multi-source UI.
