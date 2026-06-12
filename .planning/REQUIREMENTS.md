# v1.7 Requirements: Storage Simplification

This file keeps completed v1.6 source-architecture requirements as historical
traceability and adds the active v1.7 storage requirements below.

## Goal

Unify dotMD source architecture so filesystem, Telegram, federated/native search
providers, and future Airweave-compatible connectors share one source
capability model, lifecycle boundary, public search candidate contract, and
`read(ref)` / `drill(ref)` surface.

This milestone should remove the risk of carrying two source planes: the old
filesystem/Telegram paths and a new connector architecture. Filesystem and
Telegram must be migrated into the same contract before third-party connector
work is considered complete.

## Reference Repository

- Upstream: `https://github.com/airweave-ai/airweave`
- Local checkout: `/home/j2h4u/repos/airweave-ai/airweave`

Use this repository as an architectural reference for source registry,
lifecycle, connector, and federated-search patterns. Do not copy Airweave's
indexing, chunking, Vespa, Temporal, billing, or organization assumptions into
dotMD unless a later phase explicitly justifies it.

## Scope Summary

### Must Have

- A dotMD-native source capability registry seeded with filesystem and Telegram.
- A source lifecycle boundary for config, auth/credentials, cursor state, and
  runtime construction.

- A normalized federated/local `SearchCandidate` contract.
- Filesystem source routed through the unified source contract without breaking
  current trickle/search/read behavior.

- Telegram source routed through the unified source contract, including the
  deferred incremental sync/reuse behavior from v1.5 Phase 30.

- Regression coverage proving callers use the same `search -> ref -> drill/read`
  workflow regardless of whether results came from local dotMD indexes or a
  source-native search.

### Should Have

- MCP Telegram native FTS exposed as the first federated source-search proof.
- A small Airweave connector compatibility spike against one low-ambiguity
  connector or connector-like source.

- Documentation mapping Airweave source concepts to dotMD source contracts
  without adopting Airweave indexing, chunking, Vespa, Temporal, or billing
  assumptions.

### Deferred

- Full connector marketplace.
- Production OAuth UI for arbitrary SaaS apps.
- Full ACL enforcement across sources.
- Attachments/media ingestion beyond a compatibility analysis.
- Bidirectional actions in Telegram, Slack, Notion, Google Drive, or other apps.

## Requirements

### Registry

- [x] **SRC-01**: dotMD can describe every source through a source descriptor
  containing source kind, display metadata, config schema, auth schema, cursor
  schema, and capability flags.

- [x] **SRC-02**: Filesystem and Telegram are registered sources, not special
  cases outside the registry.

- [x] **SRC-03**: Source capability flags distinguish local sync,
  federated/native search, read-unit windows, materialization, browse trees,
  ACL support, and incremental cursors.

- [x] **SRC-04**: Airweave source metadata can be mapped into the dotMD source
  descriptor model without making Airweave a runtime dependency.

### Lifecycle

- [ ] **LIFE-01**: dotMD can construct source runtimes through one lifecycle
  service/factory from registry entry, typed config, credentials, and cursor
  state.

- [ ] **LIFE-02**: Credentials are accessed through a provider interface;
  source adapters do not read raw secret storage directly.

- [ ] **LIFE-03**: Cursor/checkpoint commits happen only after local persistence
  succeeds.

- [ ] **LIFE-04**: Filesystem and Telegram construction paths use the lifecycle
  boundary instead of bespoke adapter setup.

### Search

- [ ] **SEARCH-01**: Local dotMD results and source-native federated results
  can be represented as one `SearchCandidate` shape.

- [ ] **SEARCH-02**: `SearchCandidate` includes stable `ref`, source identity,
  title/snippet, retrieval kind, provenance, source-native score/rank,
  `can_read`, and `can_materialize`.

- [ ] **SEARCH-03**: Federated/native source-search scores are fused without
  pretending every provider score is directly comparable.

- [ ] **SEARCH-04**: MCP Telegram native FTS can participate as a federated
  provider while preserving the same public `read(ref)` / `drill(ref)` flow.

### Filesystem

- [x] **FS-01**: Filesystem discovery, trickle indexing, local file reads,
  delete detection, parser routing, and content-addressed reuse continue to
  work through the unified source contract.

- [x] **FS-02**: Filesystem internals keep paths only where they are still
  required for discovery, holder semantics, local reads, display, and delete
  detection.

- [x] **FS-03**: The filesystem adapter no longer bypasses source registry or
  lifecycle when participating in indexing/search/read.

### Telegram

- [x] **TG-01**: Telegram registers sync/export, read-unit-window,
  incremental-cursor, and federated-search capabilities where available.

- [x] **TG-02**: Repeated Telegram sync processes only new or changed source
  units; unchanged history is not rechunked/reembedded.

- [x] **TG-03**: Telegram sync reporting exposes discovered, new, changed,
  rebound, skipped, hidden, failed, and reused counts where practical.

- [x] **TG-04**: A Telegram result has the same API shape whether it came from
  local dotMD indexing or MCP Telegram native search.

### Compatibility

- [x] **AIR-01**: dotMD can run one compatibility spike that adapts third-party
  Airweave connector-style output into dotMD `SourceDocument`, `SourceUnit`,
  optional `SourceAsset`, and `SearchCandidate` contracts.

- [x] **AIR-02**: The spike identifies which Airweave pieces are reusable
  directly, which require shims, and which should be avoided.

- [x] **AIR-03**: The compatibility spike does not introduce an Airweave-only
  integration lane separate from filesystem and Telegram.

### Storage

- [x] **STOR-01**: dotMD can model its current persistent data in embedded
  SurrealDB: documents, source units, chunks, embeddings, entities, relations,
  feedback, cursors, and checkpoints.

- [ ] **STOR-02**: The SurrealDB prototype can execute the retrieval paths dotMD
  depends on: full-text, vector, graph-direct entity retrieval, and hybrid/RRF
  fusion.

- [x] **STOR-03**: The spike measures how much current production data can be
  migrated from SQLite/sqlite-vec/FalkorDB without CPU-heavy rechunking,
  reembedding, or re-extraction.

- [x] **STOR-04**: The spike produces a recommendation to migrate, defer, or
  reject SurrealDB, including operational notes for backup/restore,
  locking/concurrency, and rollback.

## Out Of Scope

- Replacing dotMD's local chunking, embeddings, FTS5, graph retrieval, or
  reranking stack with Airweave's stack.

- Building production support for every Airweave connector.
- Adding connector UI or multi-tenant billing/organization concepts.
- Full full-text ACL correctness across third-party SaaS sources.

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SRC-01 | Phase 32 | Complete |
| SRC-02 | Phase 32 | Complete |
| SRC-03 | Phase 32 | Complete |
| SRC-04 | Phase 32 | Complete |
| LIFE-01 | Phase 33 | Complete |
| LIFE-02 | Phase 33 | Complete |
| LIFE-03 | Phase 33 | Complete |
| LIFE-04 | Phase 33 | Complete |
| SEARCH-01 | Phase 34 | Complete |
| SEARCH-02 | Phase 34 | Complete |
| SEARCH-03 | Phase 34 | Complete |
| SEARCH-04 | Phase 34 | Complete |
| FS-01 | Phase 35 | Complete |
| FS-02 | Phase 35 | Complete |
| FS-03 | Phase 35 | Complete |
| TG-01 | Phase 36 | Complete |
| TG-02 | Phase 36 | Complete |
| TG-03 | Phase 36 | Complete |
| TG-04 | Phase 36 | Complete |
| AIR-01 | Phase 37 | Complete |
| AIR-02 | Phase 37 | Complete |
| AIR-03 | Phase 37 | Complete |
| STOR-01 | Phase 38 | Complete |
| STOR-02 | Phase 38 | Planned |
| STOR-03 | Phase 38 | Complete |
| STOR-04 | Phase 38 | Complete |
