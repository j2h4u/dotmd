# Airweave Adapter Playbook

dotMD can use Airweave connectors as adapter donor code, not as an Airweave
runtime dependency.

The Gmail spike proved the pattern: Airweave's connector metadata, entity
schemas, auth/config shape, and constructor style can be adapted into dotMD's
source lifecycle. dotMD still owns search, read, indexing, storage, ranking,
and operational behavior.

## Supported Integration Modes

dotMD supports two adapter modes:

| Mode | What happens | Good for |
|---|---|---|
| Federated search | dotMD asks the external source at query time and returns source-native refs. `read(ref)` fetches the original item on demand. | Gmail, remote APIs, sources where local sync is unnecessary or expensive. |
| Local ingestion | dotMD exports source documents/units, stores them locally, chunks them, embeds them, indexes FTS/vector data, and extracts graph entities inside dotMD. | Telegram-style sync, durable offline search, sources that need cross-source ranking and local retention. |

Both modes use the same public source-ref contract:

```text
search(query) -> ref
read(ref) -> source content
```

The difference is where retrieval happens. Federated sources stay external
until read time. Ingested sources become normal dotMD corpus material and go
through local chunking, vectorization, keyword indexing, graph extraction,
fusion, and reranking.

## What We Reuse

- Connector metadata: name, description, auth fields, config fields,
  capabilities such as federated search or incremental sync.
- Entity schemas as mapping references for source identity, metadata, body
  fields, attachments, and deletion events.
- Constructor/dependency-injection shape: auth provider, logger, HTTP client,
  and source config.
- OAuth/token refresh patterns when they can be isolated from Airweave's
  platform runtime.

## What We Do Not Reuse

- Airweave's runtime stack: Temporal, Celery, Redis orchestration, Vespa,
  organizations, collections, billing, marketplace feature flags.
- Airweave persistence contracts for chunks, embeddings, sync state, or
  system metadata.
- Runtime imports from `airweave`. Vendored adapter slices must be standalone
  and wired through dotMD source descriptors and lifecycle bundles.

## Adapter Checklist

For each new Airweave-derived adapter, check:

1. Does the connector expose native search, or only sync/export?
2. What auth material is required, and can it be stored in dotMD env/secrets?
3. What is the stable source identity: document ref, unit ref, and display metadata?
4. Can results map cleanly to `SearchCandidate` for federated search?
5. Can exported records map cleanly to `SourceDocument` and `SourceUnit` for local ingestion?
6. Are attachments or deletions present, and do they need deferred asset or binding behavior?

## Current Evidence

Gmail is the first proven adapter. It uses a personal Gmail OAuth client,
stores a refresh token in dotMD secrets, performs live Gmail API search, and
supports `search -> read` without importing Airweave runtime services.

This proves the compatibility pattern, not universal drop-in compatibility.
Each new connector still needs a small spike to decide whether it should be
federated, locally ingested, or both.
