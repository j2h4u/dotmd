# Codebase Structure

**Analysis Date:** 2026-05-10

## Directory Layout

```
dotmd/                              # Repo root
├── backend/                        # Python package (src layout)
│   ├── pyproject.toml              # Package definition, dependencies, tool config
│   ├── start.sh                    # Container entrypoint
│   ├── benchmarks/                 # Performance benchmarks (not part of test suite)
│   ├── devtools/                   # Developer utilities (mcp_client/, reranker bench)
│   │   └── mcp_client/             # Streamable-HTTP MCP test client
│   ├── src/
│   │   └── dotmd/                  # Importable package root
│   │       ├── __init__.py
│   │       ├── __main__.py         # `python -m dotmd` entry
│   │       ├── cli.py              # Click CLI (thin DotMDService wrapper)
│   │       ├── mcp_server.py       # FastMCP server + Starlette ASGI app
│   │       ├── auth.py             # OAuth provider (DotMDOAuthProvider)
│   │       ├── feedback.py         # FeedbackStore (feedback.db)
│   │       ├── api/                # Service facade + FastAPI stubs
│   │       │   ├── service.py      # DotMDService — all business logic
│   │       │   ├── server.py       # FastAPI REST app (thin, wraps service)
│   │       │   └── types.py        # Shared API type aliases
│   │       ├── core/               # Domain models, config, registry
│   │       │   ├── models.py       # All Pydantic domain types
│   │       │   ├── config.py       # Settings (pydantic-settings)
│   │       │   ├── exceptions.py   # IndexingLockError, etc.
│   │       │   └── source_registry.py  # SourceRegistry class
│   │       ├── ingestion/          # Indexing pipeline and source adapters
│   │       │   ├── pipeline.py     # IndexingPipeline (main orchestrator)
│   │       │   ├── trickle.py      # TrickleIndexer (watchdog background indexer)
│   │       │   ├── source_lifecycle.py  # SourceRuntimeFactory + SourceRuntimeBundle
│   │       │   ├── source_registry.py   # default_source_registry() factory
│   │       │   ├── source.py       # FilesystemMarkdownSourceAdapter
│   │       │   ├── source_provider.py   # ApplicationSourceProviderProtocol
│   │       │   ├── telegram_provider.py # TelegramApplicationSourceProvider
│   │       │   ├── chunker.py      # Content-aware chunking strategies
│   │       │   ├── content_handlers.py  # DocKind-specific content handlers
│   │       │   ├── reader.py       # File reading, frontmatter, file discovery
│   │       │   ├── file_tracker.py # FileTracker + FileDiff (mtime/hash diff)
│   │       │   ├── lock.py         # fcntl.flock exclusive indexing lock
│   │       │   ├── migration.py    # Schema migrations
│   │       │   └── migrate_fingerprints_to_blake3.py  # One-time migration script
│   │       ├── extraction/         # Entity/keyword extraction
│   │       │   ├── base.py         # ExtractorProtocol
│   │       │   ├── structural.py   # StructuralExtractor (frontmatter tags)
│   │       │   ├── ner.py          # NERExtractor (GLiNER zero-shot)
│   │       │   ├── acronyms.py     # Acronym extraction from chunks
│   │       │   └── keyterms.py     # KeyTermExtractor
│   │       ├── search/             # Search engines, fusion, reranking
│   │       │   ├── base.py         # SearchEngineProtocol
│   │       │   ├── semantic.py     # SemanticSearchEngine (TEI + sqlite-vec)
│   │       │   ├── fts5.py         # FTS5SearchEngine (SQLite BM25)
│   │       │   ├── graph_direct.py # GraphDirectEngine (entity catalog → chunks)
│   │       │   ├── graph_search.py # GraphSearchEngine (post-fusion enrichment)
│   │       │   ├── federated.py    # LocalEngineOutcome, FederatedEngineOutcome, fanout_federated
│   │       │   ├── fusion.py       # RRF fusion + build_candidates()
│   │       │   ├── reranker.py     # RerankerFactory + cross-encoder scoring
│   │       │   └── query.py        # QueryExpander (acronym expansion)
│   │       ├── storage/            # Persistence backends
│   │       │   ├── base.py         # Protocol definitions (VectorStore, GraphStore, MetadataStore)
│   │       │   ├── metadata.py     # SQLiteMetadataStore (chunks, FTS5, fingerprints, bindings)
│   │       │   ├── sqlite_vec.py   # SQLiteVecVectorStore (sqlite-vec)
│   │       │   ├── vec_components.py  # VecComponentStore (low-level vec table ops)
│   │       │   ├── falkordb_graph.py  # FalkorDBGraphStore
│   │       │   ├── cache.py        # EmbeddingCache + ExtractionCache
│   │       └── utils/              # Shared utilities
│   │           ├── logging.py      # setup_logging()
│   │           └── text.py         # Text manipulation helpers
│   └── tests/                      # Test suite (mirrors src layout)
│       ├── conftest.py             # Shared fixtures
│       ├── api/                    # Service and lifecycle tests
│       ├── cli/                    # CLI output tests
│       ├── core/                   # Config, model tests
│       ├── devtools/               # Reranker bench tests
│       ├── e2e/                    # MCP smoke tests
│       ├── fixtures/               # Test data factories
│       ├── ingestion/              # Pipeline, chunker, provider tests
│       ├── mcp/                    # MCP server tests
│       ├── search/                 # Engine tests (via top-level test_*.py)
│       └── storage/                # Storage backend tests
├── data/                           # Sample markdown files for dev/testing
├── .mcp.json                       # Claude Code MCP config (stdio via docker exec)
├── graphify-out/                   # Generated dependency graph output (not committed normally)
└── AGENTS.md                       # Project documentation for agents
```

## Directory Purposes

**`backend/src/dotmd/api/`:**
- Purpose: Service facade and optional REST API
- Contains: `DotMDService` (the only public API), `server.py` (FastAPI thin layer), `types.py`
- Key files: `service.py` (2035 lines — largest file after pipeline.py)

**`backend/src/dotmd/core/`:**
- Purpose: Shared domain vocabulary; no business logic
- Contains: All Pydantic models, env-var configuration, exceptions, source registry class
- Key files: `models.py` (all enums and domain types), `config.py` (Settings)

**`backend/src/dotmd/ingestion/`:**
- Purpose: Everything that touches files on disk and produces indexed artifacts
- Contains: Pipeline orchestrator, trickle watcher, source adapters, chunking, fingerprinting
- Key files: `pipeline.py` (3777 lines — largest file in the codebase), `source_lifecycle.py`

**`backend/src/dotmd/extraction/`:**
- Purpose: Knowledge extraction from document content (entities, tags, acronyms)
- Contains: Protocol + three concrete extractors
- Key files: `structural.py` (frontmatter-based, always on), `ner.py` (GLiNER, controlled by `DOTMD_EXTRACT_DEPTH=ner`)

**`backend/src/dotmd/search/`:**
- Purpose: All retrieval, ranking, and federated orchestration
- Contains: Four search engines, RRF fusion, cross-encoder reranker, federated outcome types
- Key files: `federated.py` (outcome types and fan-out), `fusion.py` (RRF + candidate hydration)

**`backend/src/dotmd/storage/`:**
- Purpose: Persistence abstractions and concrete backends
- Contains: Three Protocol definitions and their implementations; two graph backends
- Key files: `base.py` (contracts for all backends), `metadata.py` (1705 lines — most complex storage file)

**`backend/tests/`:**
- Purpose: All automated tests, mirroring the `src/dotmd/` package structure
- Contains: Unit tests co-located by domain, integration tests in `ingestion/`, e2e MCP tests in `e2e/`
- Key files: `conftest.py` (shared fixtures), `ingestion/application_source_fixtures.py`

## Key File Locations

**Entry Points:**
- `backend/start.sh`: Container entrypoint — `exec dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`
- `backend/src/dotmd/__main__.py`: `python -m dotmd` entry
- `backend/src/dotmd/cli.py`: Click CLI root group `main`
- `backend/src/dotmd/mcp_server.py`: `create_app()` (HTTP) and `init_service()` (stdio)

**Configuration:**
- `backend/pyproject.toml`: Package metadata, all dependencies, ruff/mypy config
- `/opt/docker/dotmd/.env` (server): Production env vars (not in repo)
- `backend/src/dotmd/core/config.py`: `Settings` class — all env var definitions

**Core Logic:**
- `backend/src/dotmd/api/service.py`: `DotMDService` — all public operations
- `backend/src/dotmd/ingestion/pipeline.py`: `IndexingPipeline` — full indexing orchestration
- `backend/src/dotmd/search/federated.py`: Search concurrency model and outcome types
- `backend/src/dotmd/storage/base.py`: Backend contracts

**Testing:**
- `backend/tests/conftest.py`: Shared pytest fixtures
- `backend/tests/ingestion/application_source_fixtures.py`: Source adapter test factories
- `backend/tests/e2e/test_mcp_smoke.py`: Full MCP integration smoke test

## Naming Conventions

**Files:**
- `snake_case.py` throughout — no exceptions
- Protocols/interfaces: `*_protocol.py` suffix not used; instead the Protocol class is defined in a `base.py` file per package (e.g., `storage/base.py`, `search/base.py`, `extraction/base.py`, `ingestion/source_provider.py`)
- Test files: `test_<domain>.py` or `test_<feature>.py`

**Classes:**
- Concrete implementations: `<Backend><Domain>` (e.g., `SQLiteMetadataStore`, `FalkorDBGraphStore`, `SQLiteVecVectorStore`)
- Protocols: `<Domain>Protocol` (e.g., `MetadataStoreProtocol`, `GraphStoreProtocol`, `SearchEngineProtocol`)
- Pydantic models: PascalCase noun (e.g., `SearchCandidate`, `SourceDocument`, `SourceRuntimeBundle`)
- Enums: `StrEnum` subclasses with UPPER_CASE members (e.g., `SearchMode.HYBRID`, `DocKind.MEETING_TRANSCRIPT`)

**Directories:**
- Flat package structure — one directory per domain layer, no nesting within a layer
- Test directories mirror source: `tests/ingestion/` mirrors `src/dotmd/ingestion/`

## Where to Add New Code

**New search engine:**
- Implement `SearchEngineProtocol` from `backend/src/dotmd/search/base.py`
- Place implementation in `backend/src/dotmd/search/<name>.py`
- Wire into `DotMDService.__init__` in `backend/src/dotmd/api/service.py`
- Add to `_collect_candidate_pool()` and the local search sequence in `service.py`
- Tests: `backend/tests/search/` or `backend/tests/api/`

**New source adapter (ingestion):**
1. Register a `SourceDescriptor` in `backend/src/dotmd/ingestion/source_registry.py` → `default_source_registry()`
2. Add a `SourceConfig` subclass in `backend/src/dotmd/ingestion/source_lifecycle.py`
3. Implement `ApplicationSourceProviderProtocol` (for federated) or `SourceAdapterProtocol` (for local sync) in a new file under `backend/src/dotmd/ingestion/`
4. Handle the namespace branch in `SourceRuntimeFactory.build()` in `source_lifecycle.py`
5. If federated search: add `SourceCapability.FEDERATED_SEARCH` to the descriptor's `capabilities`
6. Tests: `backend/tests/ingestion/`

**Storage changes:**
- The active storage stack is SQLite/FTS5/sqlite-vec plus FalkorDB.
- New storage backend work should be treated as an architecture phase, not an
  ad-hoc config switch.
- Protocols live in `backend/src/dotmd/storage/base.py`; concrete stores live
  under `backend/src/dotmd/storage/`.

**New extractor:**
- Implement `ExtractorProtocol` from `backend/src/dotmd/extraction/base.py`
- Place in `backend/src/dotmd/extraction/<name>.py`
- Call from `IndexingPipeline._extract()` in `backend/src/dotmd/ingestion/pipeline.py`
- Tests: `backend/tests/ingestion/` or a new `backend/tests/extraction/`

**New MCP tool:**
- Add `@mcp.tool(name="...")` decorated async function in `backend/src/dotmd/mcp_server.py`
- Add corresponding method to `DotMDService` in `backend/src/dotmd/api/service.py`
- Tests: `backend/tests/mcp/`

**New domain model:**
- Add Pydantic class to `backend/src/dotmd/core/models.py`
- Export via `core/__init__.py` if needed by multiple layers

**New utility:**
- Shared text/string helpers: `backend/src/dotmd/utils/text.py`
- Logging helpers: `backend/src/dotmd/utils/logging.py`

## Special Directories

**`backend/devtools/`:**
- Purpose: Developer-only scripts and utilities (MCP test client, reranker latency/quality benchmarks)
- Generated: No
- Committed: Yes

**`backend/benchmarks/`:**
- Purpose: Performance benchmarks not run in CI
- Generated: No
- Committed: Yes

**`graphify-out/`:**
- Purpose: Output from the `graphify` dependency graph tool
- Generated: Yes (by `/graphify` skill)
- Committed: Partially (in `.gitignore` or ignored in working tree)

**`data/`:**
- Purpose: Sample markdown files for local development and testing
- Generated: No
- Committed: Yes

---

*Structure analysis: 2026-05-10*
