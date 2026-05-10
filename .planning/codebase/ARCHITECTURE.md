<!-- refreshed: 2026-05-10 -->
# Architecture

**Analysis Date:** 2026-05-10

## System Overview

```text
┌─────────────────────────────────────────────────────────────────────────────┐
│                        Transport Layer                                       │
│  MCP stdio (Claude Code)          MCP HTTP/streamable-http (port 8080)      │
│  `backend/src/dotmd/mcp_server.py`  → `create_app()` → Starlette ASGI app  │
└───────────────────────────┬─────────────────────────────────────────────────┘
                            │ tools: search, read, drill, feedback
                            ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                   DotMDService Facade                                        │
│        `backend/src/dotmd/api/service.py`                                   │
│  search_async() / read() / drill() / index() / status()                    │
└────┬──────────────────────┬────────────────────────────────────────────────┘
     │                      │
     ▼                      ▼
┌────────────────┐  ┌────────────────────────────────────────────────────────┐
│ Search Layer   │  │                 Ingestion Layer                        │
│                │  │  `backend/src/dotmd/ingestion/`                        │
│ semantic.py    │  │  IndexingPipeline   TrickleIndexer   SourceRuntimeFactory│
│ fts5.py        │  │  pipeline.py        trickle.py       source_lifecycle.py │
│ graph_direct.py│  │                                                         │
│ graph_search.py│  │  Sources:                                               │
│ federated.py   │  │  FilesystemMarkdownSourceAdapter (source.py)            │
│ fusion.py      │  │  TelegramApplicationSourceProvider (telegram_provider.py)│
│ reranker.py    │  └────────────────────────────────────────────────────────┘
│ query.py       │
└────────┬───────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    Storage Layer (3 backends)                                │
│  SQLiteMetadataStore   SQLiteVecVectorStore   FalkorDB / LadybugDB          │
│  `storage/metadata.py` `storage/sqlite_vec.py` `storage/falkordb_graph.py` │
│              unified `index.db` (sqlite)       `storage/graph.py`           │
└─────────────────────────────────────────────────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│  External Services                                                           │
│  TEI (port 8088) — embeddings     FalkorDB (standalone container) — graph   │
│  mcp-telegram (unix socket) — Telegram provider                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Component Responsibilities

| Component | Responsibility | File |
|-----------|----------------|------|
| `DotMDService` | High-level facade; wires all components; entry point for all callers | `api/service.py` |
| `IndexingPipeline` | Orchestrates file discovery → chunking → embedding → FTS5 → graph writes | `ingestion/pipeline.py` |
| `TrickleIndexer` | Background watchdog-based file watcher; processes changes one at a time | `ingestion/trickle.py` |
| `SourceRuntimeFactory` | Builds `SourceRuntimeBundle` per source namespace from registry + config | `ingestion/source_lifecycle.py` |
| `SourceRegistry` | In-memory registry of `SourceDescriptor` objects keyed by namespace | `core/source_registry.py` |
| `SemanticSearchEngine` | Encodes query via TEI, runs cosine search via sqlite-vec | `search/semantic.py` |
| `FTS5SearchEngine` | BM25 keyword search via SQLite FTS5 | `search/fts5.py` |
| `GraphDirectEngine` | Entity-name catalog → direct chunk lookup (pre-fusion peer) | `search/graph_direct.py` |
| `GraphSearchEngine` | Post-fusion graph enrichment: seed chunks → graph neighbors | `search/graph_search.py` |
| `SQLiteMetadataStore` | Chunk metadata, FTS5 tables, fingerprints, source_documents, resource_bindings | `storage/metadata.py` |
| `SQLiteVecVectorStore` | sqlite-vec embedding store; two-dimensional `(strategy, model)` tables | `storage/sqlite_vec.py` |
| `FalkorDB / LadybugDB` | Knowledge graph (production/local-dev alternatives) | `storage/falkordb_graph.py`, `storage/graph.py` |
| `FastMCP server` | MCP tool registration (search, read, drill, feedback), OAuth, HTTP middleware | `mcp_server.py` |
| `QueryExpander` | Acronym expansion for query enrichment | `search/query.py` |
| `RerankerFactory` | Loads cross-encoder model; blends reranker score with fusion score (0.6/0.4) | `search/reranker.py` |

## Pattern Overview

**Overall:** Layered service architecture with protocol-based storage backends and federated search fan-out.

**Key Characteristics:**
- All public access goes through `DotMDService` — no caller touches storage or search engines directly
- Storage backends implement `@runtime_checkable` Protocol classes (`VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`) from `storage/base.py`; swapped at init time
- Search engines implement `SearchEngineProtocol` from `search/base.py`
- Two-dimensional table naming: `chunks_{strategy}` and `vec_{strategy}_{model}` enables multi-strategy and multi-model coexistence in one `index.db`
- Source adapters registered via `SourceRegistry` + `SourceRuntimeFactory` (Phase 32/33 lifecycle boundary)
- Local search runs sequentially on a single-worker `ThreadPoolExecutor` (D-LOCAL-SERIALIZED invariant by construction); federated providers run concurrently via `asyncio.gather` with per-source timeout

## Layers

**Core (`core/`):**
- Purpose: Pydantic models, configuration, exceptions, source registry
- Location: `backend/src/dotmd/core/`
- Contains: `models.py` (all domain types), `config.py` (Settings via pydantic-settings), `exceptions.py`, `source_registry.py`
- Depends on: nothing (leaf layer)
- Used by: all other layers

**Ingestion (`ingestion/`):**
- Purpose: File reading, content-aware chunking, fingerprint tracking, pipeline orchestration, source lifecycle
- Location: `backend/src/dotmd/ingestion/`
- Contains: `pipeline.py` (IndexingPipeline), `trickle.py` (background watcher), `chunker.py`, `reader.py`, `source_lifecycle.py` (SourceRuntimeFactory/SourceRuntimeBundle), `source.py` (FilesystemMarkdownSourceAdapter), `telegram_provider.py` (TelegramApplicationSourceProvider), `source_provider.py` (ApplicationSourceProviderProtocol), `file_tracker.py`, `content_handlers.py`
- Depends on: `core/`, `storage/`, `extraction/`, `search/fts5.py`
- Used by: `api/service.py`

**Extraction (`extraction/`):**
- Purpose: Structural entity extraction, NER (GLiNER), acronym parsing, key-term extraction
- Location: `backend/src/dotmd/extraction/`
- Contains: `base.py` (ExtractorProtocol), `structural.py`, `ner.py`, `acronyms.py`, `keyterms.py`
- Depends on: `core/`
- Used by: `ingestion/pipeline.py`

**Storage (`storage/`):**
- Purpose: Persistence for chunks (metadata+FTS5), vectors, and graph
- Location: `backend/src/dotmd/storage/`
- Contains: `base.py` (protocols), `metadata.py` (SQLiteMetadataStore), `sqlite_vec.py` (SQLiteVecVectorStore), `vec_components.py`, `falkordb_graph.py`, `graph.py` (LadybugDB), `cache.py` (EmbeddingCache, ExtractionCache), `vector.py`
- Depends on: `core/`
- Used by: `ingestion/pipeline.py`, `api/service.py`, `search/`

**Search (`search/`):**
- Purpose: Query expansion, semantic/FTS5/graph retrieval, RRF fusion, reranking, federated fan-out
- Location: `backend/src/dotmd/search/`
- Contains: `base.py` (SearchEngineProtocol), `semantic.py`, `fts5.py`, `graph_direct.py`, `graph_search.py`, `federated.py` (LocalEngineOutcome, FederatedEngineOutcome, fanout_federated), `fusion.py` (RRF), `reranker.py`, `query.py`
- Depends on: `core/`, `storage/`
- Used by: `api/service.py`

**API (`api/`):**
- Purpose: Service facade and FastAPI REST stubs
- Location: `backend/src/dotmd/api/`
- Contains: `service.py` (DotMDService), `server.py` (FastAPI, thin), `types.py`
- Depends on: all layers
- Used by: `mcp_server.py`, `cli.py`

**MCP Server (`mcp_server.py`):**
- Purpose: FastMCP tool registration, Starlette ASGI composition, OAuth, access logging
- Location: `backend/src/dotmd/mcp_server.py`
- Contains: `create_app()` (server-wide lifespan + trickle start), `init_service()` (stdio path), tools: search/read/drill/feedback
- Depends on: `api/service.py`, `auth.py`, `feedback.py`

## Data Flow

### Search Request (Hybrid Mode)

1. MCP client calls `search` tool → `mcp_server.py:search()` (`mcp_server.py:595`)
2. `await service.search_async(query, top_k)` — async entry point (`api/service.py:505`)
3. Query expansion via `QueryExpander.expand()` → expanded text (`search/query.py`)
4. Local search dispatched to `self._local_executor` (single-worker) via `loop.run_in_executor`:
   - `SemanticSearchEngine.search()` → TEI HTTP call → sqlite-vec cosine search (`search/semantic.py`)
   - `FTS5SearchEngine.search()` → SQLite FTS5 BM25 query (`search/fts5.py`)
   - `GraphDirectEngine.search()` → entity catalog fuzzy match → chunk IDs (`search/graph_direct.py`)
5. Federated providers (if configured) dispatched concurrently via `fanout_federated()` with per-source soft timeout (`search/federated.py:238`)
6. RRF fusion on local engine results → `fuse_results()` (`search/fusion.py`)
7. Post-fusion graph enrichment: seed chunk IDs → `GraphSearchEngine.search()` → neighbor chunks appended below floor score (`search/graph_search.py`)
8. Active-binding filter: drops chunks whose `resource_bindings` row is INACTIVE
9. Optional cross-encoder reranking: top-N candidates → cross-encoder scores → blended (0.6 reranker + 0.4 fusion) (`search/reranker.py`)
10. Federated candidate quota merge: local top-K minus `fed_quota` slots + federated top-`fed_quota`
11. `build_candidates()` hydrates `(chunk_id, score)` pairs into `SearchCandidate` objects (`search/fusion.py`)
12. `SearchResponse` returned with `candidates` + `source_status`

### Indexing (Trickle Path)

1. `TrickleIndexer.run()` starts on server startup inside `_server_lifespan` (`mcp_server.py:509`)
2. Watchdog observes `DOTMD_DATA_DIR` (locked to `/mnt`); file events enqueued (`ingestion/trickle.py`)
3. `IndexingPipeline.index_single_file()` called per changed file; `fcntl.flock` prevents overlap
4. `reader.py`: reads file, parses frontmatter, determines `DocKind`
5. Content-aware chunking: speaker-turn split (meeting transcripts), paragraph split (voicenotes), heading-based (documents) (`ingestion/chunker.py`, `ingestion/content_handlers.py`)
6. BLAKE3 fingerprint comparison; skip if unchanged; text_hash enables cross-strategy embedding reuse
7. Structural extraction → entities/tags → graph upserts (`extraction/structural.py`)
8. NER extraction if configured (`extraction/ner.py`)
9. Batch TEI call → embeddings → `SQLiteVecVectorStore.add_chunks()` (`storage/sqlite_vec.py`)
10. FTS5 index updated (`search/fts5.py`)
11. `source_documents` + `resource_bindings` rows written (ACTIVE status) via lifecycle path

### Telegram Federated Read Path

1. `service.read(ref)` called with `telegram:dialog:N:message:M` ref
2. `_resolve_telegram_read_path()` checks local `source_documents` + `resource_bindings`
3. Routes to: LOCAL_ACTIVE (use local chunks), LOCAL_INACTIVE (raise PermissionError), or FEDERATED_ONLY (call `TelegramApplicationSourceProvider.read_unit_window()` via unix socket)

**State Management:**
- Module-level singleton `_service: DotMDService | None` in `mcp_server.py` — set at server startup, accessed by tool handlers via `_get_service()`
- `TrickleState` dataclass on `TrickleIndexer` — readable via `DotMDService.status()`
- All persistent state in `index.db` (SQLite) and FalkorDB graph

## Key Abstractions

**`SourceDescriptor` + `SourceRegistry`:**
- Purpose: Declarative description of a data source (namespace, capabilities, auth schema, display metadata)
- Examples: `ingestion/source_registry.py` (default registry with "filesystem" and "telegram"), `core/source_registry.py` (registry class)
- Pattern: `SourceRegistry.register(descriptor)` → `SourceRuntimeFactory.build(namespace)` → `SourceRuntimeBundle`

**`SourceRuntimeBundle`:**
- Purpose: Assembled runtime for one source namespace: descriptor + config + access + cursor_store + optional source adapter or provider
- File: `ingestion/source_lifecycle.py:228`
- Pattern: Pydantic model with `supports_federated_search` computed property; built once at `DotMDService.__init__` and stored in `_lifecycle_bundles`

**`SearchCandidate`:**
- Purpose: Unified result type for local and federated results; federated candidates have `chunk_id=None`, `engine_scores=None` (D-02 invariant)
- File: `core/models.py`
- Pattern: Frozen Pydantic model; `namespace`, `ref`, `fused_score`, `matched_engines`, `provider_metadata`

**`LocalEngineOutcome` / `FederatedEngineOutcome`:**
- Purpose: Split outcome types enforce that local results (have `chunk_id`) and federated results (have `SearchCandidate` objects, no `chunk_id`) never mix in the reranking path
- File: `search/federated.py:38,64`
- Pattern: Frozen dataclasses; dispatched via `isinstance` in orchestrator

**Storage Protocols:**
- Purpose: Swappable backends without changing call sites
- File: `storage/base.py` — `VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`
- Pattern: `@runtime_checkable Protocol`; concrete implementations: `SQLiteVecVectorStore`, `FalkorDBGraphStore`/`LadybugDBGraphStore`, `SQLiteMetadataStore`

## Entry Points

**HTTP/MCP Server:**
- Location: `backend/src/dotmd/mcp_server.py:create_app()`
- Triggers: `backend/start.sh` → `dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`
- Responsibilities: Compose Starlette app, server-wide lifespan, start trickle indexer, register OAuth routes

**stdio MCP (Claude Code):**
- Location: `backend/src/dotmd/mcp_server.py:init_service()` → `mcp.run()`
- Triggers: `docker exec -i dotmd dotmd mcp` (configured in `.mcp.json`)
- Responsibilities: Init DotMDService without warmup (avoids MCP client timeout); no trickle

**CLI:**
- Location: `backend/src/dotmd/cli.py:main`
- Triggers: `dotmd index <dir>`, `dotmd search <query>`, `dotmd status`, `dotmd reindex <store>`
- Responsibilities: Thin Click wrapper over `DotMDService`

## Architectural Constraints

- **Threading:** Single-worker `ThreadPoolExecutor` (`max_workers=1`) for all local search engines (`_local_executor`). This serializes concurrent `search_async()` calls, preserving single-thread SQLite/metadata/graph access invariant (D-LOCAL-SERIALIZED). Federated providers use `asyncio.to_thread` with the default thread pool.
- **Global state:** `_service: DotMDService | None` and `_feedback: FeedbackStore | None` in `mcp_server.py` — module-level singletons set at lifespan startup.
- **SQLite concurrency:** All SQLite access (metadata + FTS5 + vec) happens on the `_local_executor` worker thread. Do not introduce concurrent SQLite access from the event loop or multiple threads.
- **Circular imports:** `api/service.py` imports from `search/federated.py` inside method bodies (deferred import) to avoid circular dependencies at module load time.
- **Indexing lock:** `fcntl.flock` in `ingestion/lock.py` prevents parallel indexing runs. Never run `dotmd index --force` while container is live — trickle holds the lock.
- **DOTMD_DATA_DIR locked to `/mnt`:** Indexing scope is never narrowed. No excludes added. Observability improved instead.

## Anti-Patterns

### Calling `search()` from inside a running event loop

**What happens:** `DotMDService.search()` bridges async→sync via `asyncio.run()`. Inside MCP/FastAPI tool handlers the event loop is already running.
**Why it's wrong:** `asyncio.run()` raises `RuntimeError` if called from an existing event loop.
**Do this instead:** Call `await service.search_async(...)` directly in async contexts (MCP tools, FastAPI handlers). The sync `search()` is only for CLI and test code.

### Loading indexes per-request

**What happens:** Calling `load_index()` or similar inside a search handler.
**Why it's wrong:** Causes disk I/O on every request; indexes must be loaded once at startup and reused.
**Do this instead:** Indexes are loaded in `DotMDService.__init__` (warmup) and kept in memory. Search methods read from already-loaded indexes.

### Concurrent SQLite access via `asyncio.to_thread`

**What happens:** Dispatching local search engines via `asyncio.to_thread()` instead of `self._local_executor`.
**Why it's wrong:** `asyncio.to_thread` uses the default multi-worker executor, allowing two concurrent `search_async()` calls to race on shared SQLite connections (metadata/FTS5/vec). Breaks D-LOCAL-SERIALIZED.
**Do this instead:** Always dispatch local search through `loop.run_in_executor(self._local_executor, ...)` where `_local_executor` has `max_workers=1`.

### Adding a new source without going through the lifecycle boundary

**What happens:** Adding a provider directly to `DotMDService.__init__` without registering a `SourceDescriptor` in `SourceRegistry` and building through `SourceRuntimeFactory`.
**Why it's wrong:** Bypasses capability declarations, config validation, cursor store wiring, and federated bundle tracking.
**Do this instead:** Register a `SourceDescriptor` in `ingestion/source_registry.py`; add a `SourceConfig` subclass; handle the namespace in `SourceRuntimeFactory.build()`; set `SourceCapability.FEDERATED_SEARCH` if it provides federated results.

## Error Handling

**Strategy:** No fail-fast in search. Engine failures are caught, logged as warnings, and returned as `SourceStatus(status="error")` entries in `SearchResponse.source_status`. The main `candidates` list is unaffected. Indexing errors per-file are logged and skipped; the indexing batch continues.

**Patterns:**
- D-12 (no fail-fast): `_run_local_engine()` and `_run_federated_engine()` catch all exceptions and return error outcomes (`search/federated.py`)
- Lifecycle init errors caught in `_build_federated_bundles()` → stored in `_lifecycle_init_errors` → surfaced as persistent `SourceStatus` on every search response
- `ValueError` from `service.read()` / `service.drill()` with bad ref → MCP tool converts to `RuntimeError` with user-facing action hint

## Cross-Cutting Concerns

**Logging:** Standard `logging.getLogger(__name__)` throughout; `dotmd.utils.logging.setup_logging()` configures root handler. Access log middleware writes JSONL to `/dotmd-index/logs/access.log` for HTTP transport.

**Validation:** All domain models are Pydantic v2 with `extra="forbid"` and `strict=True` where appropriate. Config validated at startup via `pydantic-settings`.

**Authentication:** Optional OAuth 2.0 (PKCE + pairing code) via `DotMDOAuthProvider` in `auth.py`. Only active when `DOTMD_BASE_URL` env var is set. stdio transport is unauthenticated (Docker exec boundary provides isolation).

---

*Architecture analysis: 2026-05-10*
