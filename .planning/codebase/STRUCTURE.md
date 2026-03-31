# Codebase Structure

**Analysis Date:** 2026-03-23

## Directory Layout

```
dotmd/
├── backend/                    # Python package (main codebase)
│   ├── pyproject.toml          # Package metadata, dependencies, build config
│   ├── src/dotmd/              # Importable package (src layout)
│   │   ├── __init__.py
│   │   ├── __main__.py         # Entry point when run as module: python -m dotmd
│   │   ├── cli.py              # Click CLI commands (index, search, status)
│   │   ├── mcp_server.py       # FastMCP server for Claude integration
│   │   ├── core/               # Domain models and configuration
│   │   │   ├── __init__.py
│   │   │   ├── config.py       # Settings class (DOTMD_* env vars)
│   │   │   ├── exceptions.py   # Custom exception types
│   │   │   └── models.py       # Pydantic models: Chunk, Entity, Relation, SearchResult, IndexStats
│   │   ├── api/                # Service facade and HTTP server
│   │   │   ├── __init__.py
│   │   │   ├── service.py      # DotMDService: main public API
│   │   │   ├── server.py       # FastAPI app (HTTP endpoints)
│   │   │   └── types.py        # API request/response types
│   │   ├── ingestion/          # File discovery, reading, chunking
│   │   │   ├── __init__.py
│   │   │   ├── reader.py       # discover_files(), read_file()
│   │   │   ├── chunker.py      # chunk_file() — markdown-aware token-based chunking
│   │   │   └── pipeline.py     # IndexingPipeline: orchestrates full indexing workflow
│   │   ├── extraction/         # Information extraction (entities, relations)
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # ExtractorProtocol
│   │   │   ├── structural.py   # StructuralExtractor: wikilinks, tags, YAML, links, headings
│   │   │   ├── ner.py          # NERExtractor: GLiNER zero-shot entity recognition
│   │   │   ├── keyterms.py     # KeyTermExtractor: TF-IDF + acronyms + heading terms
│   │   │   └── acronyms.py     # extract_acronyms_from_chunks()
│   │   ├── search/             # Search engines and fusion
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # SearchEngineProtocol
│   │   │   ├── semantic.py     # SemanticSearchEngine: dense vectors (local or remote TEI)
│   │   │   ├── bm25.py         # BM25SearchEngine: sparse keyword ranking
│   │   │   ├── graph_search.py # GraphSearchEngine: entity/relation traversal
│   │   │   ├── query.py        # QueryExpander: synonym/acronym expansion
│   │   │   ├── reranker.py     # Reranker: cross-encoder rescoring
│   │   │   └── fusion.py       # fuse_results(): Reciprocal Rank Fusion, build_search_results()
│   │   ├── storage/            # Storage backends for embeddings, graph, metadata
│   │   │   ├── __init__.py
│   │   │   ├── base.py         # VectorStoreProtocol, GraphStoreProtocol, MetadataStoreProtocol
│   │   │   ├── vector.py       # LanceDBVectorStore: vector similarity search
│   │   │   ├── sqlite_vec.py   # SQLiteVecVectorStore: vector store backed by sqlite-vec
│   │   │   ├── graph.py        # LadybugDBGraphStore: knowledge graph (forked Kuzu)
│   │   │   └── metadata.py     # SQLiteMetadataStore: chunks and index statistics
│   │   └── utils/              # Shared utilities
│   │       ├── __init__.py
│   │       ├── text.py         # tokenize(), estimate_tokens(), split_sentences()
│   │       └── logging.py      # setup_logging()
│   └── eval/                   # Evaluation framework (optional, not core)
│       ├── __init__.py
│       ├── __main__.py
│       ├── metrics.py          # Evaluation metrics
│       ├── run_hotpotqa.py     # HotpotQA benchmark
│       ├── data_prep.py        # Test data preparation
│       └── utils.py            # Evaluation utilities
├── data/                       # Sample markdown files for testing
│   └── *.md
└── README.md                   # Project overview
```

## Directory Purposes

**`backend/`:**
- Purpose: Self-contained Python package with full indexing and search implementation
- Packaging: Standard layout with `pyproject.toml`, `src/dotmd/` as importable package
- Deployment: Installable via `pip install -e .` or published to PyPI

**`src/dotmd/`:**
- Purpose: Root of importable package (src-layout pattern)
- Convention: All imports are `from dotmd.X import Y`, never relative imports

**`src/dotmd/core/`:**
- Purpose: Shared domain layer — types and configuration
- Stability: Very stable; changes here affect all layers
- Key exports: `Chunk`, `Entity`, `Relation`, `SearchResult`, `IndexStats`, `Settings`

**`src/dotmd/api/`:**
- Purpose: Public-facing interfaces (DotMDService, HTTP server, types)
- Stability: Stable — main API boundary
- Used by: CLI, MCP server, FastAPI, direct Python imports

**`src/dotmd/ingestion/`:**
- Purpose: One-directional input processing: files → chunks
- Dependencies: Core models, utilities (text processing)
- Used by: Indexing pipeline only

**`src/dotmd/extraction/`:**
- Purpose: Post-chunking information extraction
- Pattern: Multiple extractors (structural, NER, key-terms) run independently, results combined
- Extensibility: Implement `ExtractorProtocol` to add new extraction strategies

**`src/dotmd/search/`:**
- Purpose: Retrieval strategies and query processing
- Pattern: Engines run in parallel, fused via RRF, optionally reranked
- Extensibility: Implement `SearchEngineProtocol` to add new search engines (e.g., hybrid BM25+semantic fusion within single engine)

**`src/dotmd/storage/`:**
- Purpose: Data persistence abstractions and implementations
- Pattern: Three independent storage concerns (vectors, graph, metadata) with protocol-based backends
- Extensibility: Implement protocols to swap backends (e.g., Pinecone instead of LanceDB for vectors)

**`src/dotmd/utils/`:**
- Purpose: Shared utilities — text processing, tokenization, logging
- Stability: Very stable; used everywhere
- No dependencies on other `dotmd.*` modules (only stdlib + external libs)

**`eval/`:**
- Purpose: Evaluation framework for benchmarking retrieval quality
- Stability: Separate from core; can be refactored independently
- Entry: Run `python -m dotmd.eval --help` for benchmark commands

## Key File Locations

**Entry Points:**
- `src/dotmd/__main__.py` — Module execution: `python -m dotmd`
- `src/dotmd/cli.py` — CLI commands: `dotmd index`, `dotmd search`
- `src/dotmd/mcp_server.py` — MCP tools for Claude
- `src/dotmd/api/server.py` — FastAPI HTTP server

**Configuration:**
- `src/dotmd/core/config.py` — `Settings` class (environment variables, defaults)
- `pyproject.toml` — Package metadata, dependencies, build config, script entry points

**Core Logic:**
- `src/dotmd/api/service.py` — `DotMDService` (main facade)
- `src/dotmd/ingestion/pipeline.py` — `IndexingPipeline` (orchestrates indexing)
- `src/dotmd/search/fusion.py` — `fuse_results()` (RRF merging)

**Domain Models:**
- `src/dotmd/core/models.py` — All Pydantic models (Chunk, Entity, Relation, SearchResult, IndexStats, ExpandedQuery, FileInfo)

**Storage Protocols:**
- `src/dotmd/storage/base.py` — `VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`

**Search Protocols:**
- `src/dotmd/search/base.py` — `SearchEngineProtocol`

**Extraction Protocols:**
- `src/dotmd/extraction/base.py` — `ExtractorProtocol`

## Naming Conventions

**Files:**
- Lowercase with underscores: `reader.py`, `bm25.py`, `graph_search.py`
- Protocol definitions: `*_protocol.py` or `base.py` (e.g., `base.py` for protocols, used in search/, storage/, extraction/)
- Implementation files match concrete class names: `LanceDBVectorStore` → `vector.py` (generic), `SQLiteVecVectorStore` → `sqlite_vec.py` (specific backend)

**Directories:**
- Lowercase plural for packages containing multiple related modules: `search/`, `storage/`, `extraction/`, `ingestion/`
- Single-module packages use singular: `core/`, `api/`, `utils/`

**Classes:**
- PascalCase: `DotMDService`, `LanceDBVectorStore`, `StructuralExtractor`
- Protocols: `VectorStoreProtocol`, `SearchEngineProtocol`, `ExtractorProtocol`
- Implementation classes: `LanceDBVectorStore`, `SQLiteVecVectorStore`, `LadybugDBGraphStore`, `SQLiteMetadataStore`

**Functions:**
- Snake_case: `chunk_file()`, `discover_files()`, `fuse_results()`, `tokenize()`
- Private (internal) functions: `_split_with_overlap()`, `_make_chunk_id()`, `_extract_best_snippet()`

**Variables:**
- Module-level constants (regex, SQL): `_HEADING_RE`, `_CREATE_CHUNKS`, `_ENGINE_SCORE_FIELDS`
- Private module data: `_service` (in mcp_server.py for singleton)

## Where to Add New Code

**New Feature (end-to-end):**
- Primary code: Implement in logical layer (e.g., new search mode in `search/`, new extraction strategy in `extraction/`)
- Tests: Add `test_feature.py` or extend existing test in `/tests/`
- Models: If new domain types needed, add to `core/models.py`

**New Search Engine:**
- Implementation: Create class in `src/dotmd/search/` implementing `SearchEngineProtocol`
- Example: `class MySearchEngine: def search(self, query: str, top_k: int) -> list[tuple[str, float]]: ...`
- Integration: Import in `api/service.py`, instantiate in `DotMDService.__init__()`, add to search pipeline in `search()` method
- File naming: If simple/experimental: add method to existing file (e.g., `semantic.py`). If complex: new file `my_search.py`

**New Extractor:**
- Implementation: Create class in `src/dotmd/extraction/` implementing `ExtractorProtocol`
- Example: `class MyExtractor: def extract(self, chunks: list[Chunk]) -> ExtractionResult: ...`
- Integration: Instantiate in `IndexingPipeline.__init__()`, call in `index()` method, combine results with other extractors
- File naming: `my_extractor.py` or add to `structural.py` if closely related

**New Storage Backend:**
- Implementation: Create class in `src/dotmd/storage/` implementing relevant protocol (`VectorStoreProtocol`, `GraphStoreProtocol`, `MetadataStoreProtocol`)
- Example for vector store: `class PineconeVectorStore: def add_chunks(...): ... def search(...): ...`
- Integration: Import in `ingestion/pipeline.py`, instantiate in `_create_vector_store()` based on `Settings.vector_backend`
- File naming: `my_backend.py` (e.g., `pinecone.py`, `milvus.py`)

**Utilities:**
- Shared helpers: `src/dotmd/utils/text.py` (text processing), `src/dotmd/utils/logging.py` (setup)
- Avoid circular imports: utilities should not depend on other `dotmd.*` modules

**Configuration:**
- New settings: Add fields to `Settings` class in `src/dotmd/core/config.py`
- Environment variables: Auto-prefixed with `DOTMD_` by pydantic-settings
- Defaults: Set directly in class definition
- Example: `my_option: str = "default_value"` becomes `DOTMD_MY_OPTION=value`

## Special Directories

**`~/.dotmd/` (Runtime Index Storage):**
- Purpose: Persists all indexed data across sessions
- Generated: Yes (created by `IndexingPipeline` if not exists)
- Committed: No (user data, not source code)
- Contents:
  - `lancedb/` or `vec.db` — Vector embeddings (depends on `Settings.vector_backend`)
  - `graphdb/` — Knowledge graph (LadybugDB)
  - `metadata.db` — SQLite chunks and statistics
  - `bm25_index.pkl` — Pickled BM25 index
  - `acronyms.json` — Extracted acronym dictionary

**`eval/` (Evaluation/Benchmarking):**
- Purpose: Separate benchmark suite for retrieval quality assessment
- Generated: No (source code)
- Committed: Yes (part of repo)
- Used for: Testing on HotpotQA, measuring MRR/NDCG/etc.
- Entry: `python -m dotmd.eval`

**`data/` (Test Data):**
- Purpose: Sample markdown files for testing and demos
- Generated: No (hand-written examples)
- Committed: Yes
- Used by: Tests, examples, manual verification

---

*Structure analysis: 2026-03-23*
