# Architecture

**Analysis Date:** 2026-03-23

## Pattern Overview

**Overall:** Layered service-oriented architecture with Protocol-based abstractions

**Key Characteristics:**
- **Dependency injection**: Storage backends, search engines, and extractors are injected at initialization
- **Protocol-driven design**: All pluggable components implement runtime-checkable protocols for polymorphism
- **UI-agnostic facade**: `DotMDService` provides a single public entry point for indexing and search
- **Search fusion**: Multiple search engines run in parallel, then Reciprocal Rank Fusion merges results
- **Progressive extraction**: Chunks flow through multiple extraction layers (structural → NER → key-terms) → knowledge graph

## Layers

**Service (Presentation):**
- Purpose: High-level API facade for indexing and searching; hides all implementation details
- Location: `src/dotmd/api/service.py`
- Contains: `DotMDService` class with `index()`, `search()`, `warmup()`, `status()`, `clear()` methods
- Depends on: Ingestion pipeline, all search engines, reranker, query expander
- Used by: CLI (`cli.py`), MCP server (`mcp_server.py`), FastAPI server (`api/server.py`)

**API/CLI (User Interface):**
- Purpose: Expose service through Click CLI and HTTP/MCP interfaces
- Location: `src/dotmd/cli.py` (Click), `src/dotmd/mcp_server.py` (MCP/FastMCP), `src/dotmd/api/server.py` (FastAPI)
- Contains: Command definitions, tool decorators, request/response serialization
- Depends on: `DotMDService`
- Used by: End users, AI assistants via MCP, HTTP clients

**Ingestion Pipeline:**
- Purpose: Orchestrate end-to-end indexing: file discovery → chunking → encoding → storage → extraction → graph population
- Location: `src/dotmd/ingestion/pipeline.py`
- Contains: `IndexingPipeline` class that coordinates readers, chunkers, search engines, extractors, and stores
- Depends on: Reader, chunker, storage backends (vector/graph/metadata), search engines, extractors
- Used by: `DotMDService.index()`
- Flow: Discover → Read → Chunk → Save Metadata → Encode & Index Vectors → Build BM25 → Extract Entities/Relations → Populate Graph → Save Stats

**Search Pipeline:**
- Purpose: Process queries through expansion, multiple engines, fusion, and optional reranking
- Location: `src/dotmd/api/service.py` (orchestration), `src/dotmd/search/` (engines)
- Contains: Query expansion, semantic/BM25/graph search engines, RRF fusion, cross-encoder reranking
- Depends on: Query expander, search engines, reranker, metadata store
- Used by: `DotMDService.search()`
- Flow: Expand → Search (semantic + BM25 + graph parallel) → Fuse via RRF → Rerank → Build results → Return top-K

**Extraction Layer:**
- Purpose: Extract named entities, relations, and tags from chunks for knowledge graph population
- Location: `src/dotmd/extraction/`
- Contains: `StructuralExtractor` (wikilinks, tags, YAML, markdown links, headings), `NERExtractor` (GLiNER zero-shot), `KeyTermExtractor` (TF-IDF + acronyms)
- Depends on: Domain models (`Chunk`, `Entity`, `Relation`)
- Used by: `IndexingPipeline`
- All implement `ExtractorProtocol` for consistent interface

**Storage (Data Persistence):**
- Purpose: Persist chunks, embeddings, metadata, and knowledge graph
- Location: `src/dotmd/storage/`
- Contains: Three protocol-based backends:
  - `VectorStoreProtocol` → `LanceDBVectorStore` (default) or `SQLiteVecVectorStore`
  - `GraphStoreProtocol` → `LadybugDBGraphStore` (forked Kuzu)
  - `MetadataStoreProtocol` → `SQLiteMetadataStore`
- Depends on: Domain models
- Used by: Indexing pipeline, search engines

**Search Engines (Information Retrieval):**
- Purpose: Implement retrieval strategies
- Location: `src/dotmd/search/`
- Contains: `SemanticSearchEngine` (dense vectors), `BM25SearchEngine` (sparse keywords), `GraphSearchEngine` (entity/relation traversal)
- All implement `SearchEngineProtocol`
- Semantic supports both local models and remote TEI HTTP endpoints

**Core Domain (Models & Configuration):**
- Purpose: Shared types and settings
- Location: `src/dotmd/core/`
- Contains: Pydantic models (`Chunk`, `Entity`, `Relation`, `SearchResult`, `IndexStats`), `Settings` config class, exception types
- Used by: All layers

**Ingestion (Input Processing):**
- Purpose: File discovery, content reading, chunking
- Location: `src/dotmd/ingestion/`
- Contains: `discover_files()` (recursive .md search), `read_file()` (content loading), `chunk_file()` (markdown-aware token-based chunking with overlap)
- Depends on: Utilities (text, tokenization)
- Used by: `IndexingPipeline`

**Utilities:**
- Purpose: Shared helpers for text processing, tokenization, logging
- Location: `src/dotmd/utils/`
- Contains: `tokenize()` (whitespace+punctuation splitting), `estimate_tokens()` (approx length), `split_sentences()`, logging setup
- Used by: All layers

## Data Flow

**Indexing Flow:**

1. `discover_files(directory)` → Find all `.md` files recursively
2. For each file: `read_file(path)` → Load content as string
3. `chunk_file(path, content)` → Parse markdown structure, split by heading boundaries + token limits with overlap
4. `metadata_store.save_chunks(all_chunks)` → Persist to SQLite
5. `semantic_engine.encode_batch(texts)` → Local SentenceTransformer or remote TEI server
6. `vector_store.add_chunks(chunks, embeddings)` → LanceDB or SQLite-vec
7. `bm25_engine.build_index(chunks)` → Tokenize & create BM25Okapi, pickle to disk
8. `structural_extractor.extract(chunks)` → Wikilinks, tags, YAML, markdown links, heading hierarchy
9. `ner_extractor.extract(chunks)` (optional) → GLiNER zero-shot entity recognition
10. `keyterm_extractor.extract(chunks)` → TF-IDF + acronyms + heading terms
11. `graph_store.add_entity_node()` → Create entity nodes for all extracted entities
12. `graph_store.add_file_node()` → Create nodes for source files
13. `graph_store.add_section_node()` → Create nodes for chunks/sections
14. `graph_store.add_edge()` → Create edges from extraction + CONTAINS edges from file→chunks
15. Extract acronym dictionary and save to JSON
16. `metadata_store.save_stats()` → Persist index statistics

**Search Flow:**

1. `service.search(query, top_k, mode, rerank, expand)`
2. If `expand=True`: `query_expander.expand(query)` → Expand with synonyms/acronyms
3. Run search engines based on `mode`:
   - **Semantic**: `semantic_engine.search(query, top_k=pool_size)` → Encode query → Vector similarity search
   - **BM25**: `bm25_engine.search(query, top_k=pool_size)` → Tokenize query → BM25 ranking
   - **Graph**: `graph_engine.search(query, seed_chunk_ids)` → Entity/relation traversal from seed chunks
4. `fuse_results(engine_results, k=60, weights)` → Reciprocal Rank Fusion with optional graph weight boost
5. If `rerank=True`: `reranker.rerank(query, chunk_ids, top_k=pool_size)` → Cross-encoder scoring, blend with RRF scores
6. `build_search_results()` → Hydrate with metadata, extract snippets, build final `SearchResult` list
7. Return top `top_k` results sorted by fused score

**State Management:**

- **Index state**: Persisted across invocations in `~/.dotmd/`:
  - `lancedb/` or `vec.db` (embeddings)
  - `graphdb/` (LadybugDB)
  - `metadata.db` (SQLite chunks + stats)
  - `bm25_index.pkl` (pickled BM25 index)
  - `acronyms.json` (extracted acronyms)
- **Runtime state**: Loaded once on service initialization and reused across queries (models, indexes)
- **Lazy initialization**: ML models (SentenceTransformer, cross-encoder) loaded on first use via `_load_model()`

## Key Abstractions

**VectorStoreProtocol:**
- Purpose: Abstraction over vector database backends
- Implementations: `LanceDBVectorStore`, `SQLiteVecVectorStore`
- Methods: `add_chunks()`, `search()`, `delete_all()`, `count()`
- Selected via `Settings.vector_backend` ("lancedb" or "sqlite-vec", default: "sqlite-vec")

**GraphStoreProtocol:**
- Purpose: Abstraction over knowledge graph storage
- Implementation: `LadybugDBGraphStore` (forked Kuzu)
- Methods: `add_file_node()`, `add_section_node()`, `add_entity_node()`, `add_tag_node()`, `add_edge()`, `get_neighbors()`, `delete_all()`
- Stores relationships between files, sections, entities, and tags for graph-based search

**MetadataStoreProtocol:**
- Purpose: Abstraction over chunk and statistics persistence
- Implementation: `SQLiteMetadataStore`
- Methods: `save_chunks()`, `get_chunk()`, `get_chunks()`, `get_all_chunks()`, `save_stats()`, `get_stats()`, `delete_all()`
- Single source of truth for chunk content and index metadata

**SearchEngineProtocol:**
- Purpose: Unified interface for all retrieval strategies
- Implementations: `SemanticSearchEngine`, `BM25SearchEngine`, `GraphSearchEngine`
- Methods: `search(query: str, top_k: int) -> list[tuple[str, float]]`
- Returns `(chunk_id, score)` pairs; enables plug-and-play engine composition

**ExtractorProtocol:**
- Purpose: Unified interface for information extraction
- Implementations: `StructuralExtractor`, `NERExtractor`, `KeyTermExtractor`
- Methods: `extract(chunks: list[Chunk]) -> ExtractionResult`
- Returns entities and relations for graph population

## Entry Points

**CLI:**
- Location: `src/dotmd/cli.py`
- Triggers: User runs `dotmd index <dir>` or `dotmd search <query>`
- Responsibilities: Parse arguments, instantiate service, call service methods, format output

**MCP Server:**
- Location: `src/dotmd/mcp_server.py`
- Triggers: Claude Desktop or other MCP clients call `search`, `index`, or `status` tools
- Responsibilities: Serialize results as JSON dicts, manage global service singleton

**FastAPI Server:**
- Location: `src/dotmd/api/server.py`
- Triggers: HTTP POST to `/search` or `/index` endpoints
- Responsibilities: Parse JSON payloads, call service, return JSON responses

**Python API:**
- Location: `src/dotmd/api/service.py`
- Triggers: Direct import and instantiation of `DotMDService`
- Responsibilities: Provide type-safe interface to indexing and search

## Error Handling

**Strategy:** Minimal exception hierarchy; let errors propagate unless they are expected recovery points

**Patterns:**
- File I/O errors in reader propagate (fail fast on corrupt/missing markdown)
- Storage errors propagate (signal data corruption or permission issues)
- Model loading failures (missing HuggingFace models) propagate as ImportError or network errors
- Query expansion gracefully degrades: if acronym dictionary not found, returns original query
- Reranking failures (model load error) log warning and skip reranking, return RRF-fused results only
- Graph search gracefully handles empty seed chunk lists (returns empty results)

## Cross-Cutting Concerns

**Logging:**
- Framework: Python `logging` module
- Setup: `src/dotmd/utils/logging.py` provides `setup_logging(verbose=bool)`
- Levels: INFO for major milestones (indexing complete, models loaded), DEBUG for lower-level steps (chunks processed, embeddings encoded)
- Used in: Pipeline, service, search engines

**Validation:**
- Type checking: Pydantic v2 models (`Chunk`, `Entity`, `Relation`, `SearchResult`, `IndexStats`, `Settings`)
- At runtime: Protocol checks for storage backends and extractors via `isinstance()`

**Authentication:**
- Not implemented; no auth required (single-user markdown search tool)

**Configuration:**
- Environment variables: `DOTMD_*` prefix (e.g., `DOTMD_DATA_DIR`, `DOTMD_EMBEDDING_MODEL`)
- Centralized in `src/dotmd/core/config.py` as `Settings` class
- Defaults: semantic model = BAAI/bge-small-en-v1.5, reranker = cross-encoder/ms-marco-MiniLM-L-6-v2, vector backend = sqlite-vec

---

*Architecture analysis: 2026-03-23*
