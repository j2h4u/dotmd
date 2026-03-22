# Technology Stack

**Analysis Date:** 2026-03-23

## Languages

**Primary:**
- Python 3.12+ - Core application, CLI, API, MCP server. Requires Python 3.12 minimum due to Pydantic v2

**Secondary:**
- YAML - Docker Compose configuration
- Markdown - Source documents for indexing

## Runtime

**Environment:**
- Python 3.12-slim (Docker base image)
- No external runtime dependencies beyond Python standard library

**Package Manager:**
- pip (standard Python package manager)
- Lockfile: `pyproject.toml` with `build-system` using hatchling

## Frameworks

**Core:**
- FastAPI 0.110+ - REST API framework for `api/server.py`
- Pydantic v2.0+ - Data models and configuration validation
- Pydantic Settings 2.0+ - Environment variable configuration management
- Click 8.0+ - CLI framework for `cli.py`

**ML/Search:**
- sentence-transformers 3.0+ - Embedding generation (local or via TEI-compatible server)
- GLiNER 0.2+ - Zero-shot named-entity recognition (urchade/gliner_multi-v2.1 model)
- rank-bm25 0.2+ - BM25 keyword search implementation
- cross-encoder/ms-marco-MiniLM-L-6-v2 - Cross-encoder reranking model

**MCP (Model Context Protocol):**
- mcp[cli] 1.0+ - MCP server framework via FastMCP
- httpx 0.27+ - HTTP client for remote embedding server calls

**Testing & Utilities:**
- PyYAML 6.0+ - Configuration file parsing
- pandas 2.0+ - DataFrame operations for graph query results

## Key Dependencies

**Critical:**
- `real_ladybug 0.1` - Embedded knowledge graph store (forked from Kuzu). Cypher-based graph database for entity/relation queries
- `sqlite-vec 0.1.6` - SQLite extension for vector similarity search. CPU-only (no AVX2 required), alternative to LanceDB
- `lancedb 0.6` (optional) - Vector database for embeddings. File-based, embedded. Installed separately via `[lancedb]` extra
- `sentence-transformers 3.0+` - Used by default with model `BAAI/bge-small-en-v1.5` (384-dim embeddings, retrieval-optimized)

**Infrastructure:**
- `uvicorn[standard] 0.29+` - ASGI server for FastAPI
- sqlite3 (Python stdlib) - Metadata storage (`metadata.db`). Built-in, no separate installation

## Configuration

**Environment:**
- All settings use `DOTMD_` prefix (e.g., `DOTMD_DATA_DIR`, `DOTMD_INDEX_DIR`)
- Managed via `pydantic_settings.BaseSettings` in `core/config.py`
- Defaults: index stored in `~/.dotmd/`, data in current directory

**Build:**
- `pyproject.toml` - Project metadata, dependencies, build system (hatchling)
- `Dockerfile` - Multi-stage Docker build (builder + runtime)
  - Layer 1: PyTorch CPU-only pinned to <2.5 (for AVX-only CPUs without AVX2)
  - Layer 2: Dependencies (cache-friendly, rebuilds only on pyproject.toml change)
  - Layer 3: Application code (frequent rebuilds)
- `docker-compose.yml` - Two services: `api` (REST on port 8000), `mcp` (MCP server)

## Platform Requirements

**Development:**
- Python 3.12+
- pip + hatchling
- For embeddings: either local GPU/CPU or HTTP access to TEI-compatible server
- Optional: Docker + Docker Compose for containerized deployment

**Production:**
- Python 3.12+ runtime
- 512MB+ RAM for embedding models (sentence-transformers)
- ~2-3GB disk for vector/graph indexes at typical scale
- For remote embeddings: HTTP connectivity to TEI server (e.g., `http://embeddings:8088`)

**CPU Constraints:**
- PyTorch pinned to <2.5 in Docker to support CPUs with AVX but not AVX2 (e.g., Intel Xeon E3 V2)
- If AVX2 available, PyTorch can be upgraded but SIGILL errors occur with newer versions on AVX-only CPUs

## Model Downloads

**Embeddings:**
- Default: `BAAI/bge-small-en-v1.5` (384-dim, ~33MB, HuggingFace Hub)
- Alternative: `sentence-transformers/all-MiniLM-L6-v2` (384-dim, ~27MB)
- Configurable: `DOTMD_EMBEDDING_MODEL` environment variable

**Reranker:**
- Default: `cross-encoder/ms-marco-MiniLM-L-6-v2` (~32MB, HuggingFace Hub)
- Lazy-loaded on first search if reranking enabled

**NER:**
- Default: `urchade/gliner_multi-v2.1` (multilingual zero-shot NER, ~440MB)
- Lazy-loaded on first index operation with extraction depth "ner"
- Entity types configurable: `DOTMD_NER_ENTITY_TYPES`

## Optional Dependencies

**For evaluation/benchmarking:**
- `openai 1.0+` - For evaluation scripts (optional `[eval]` extra)
- `tqdm 4.60+` - Progress bars (optional `[eval]` extra)

---

*Stack analysis: 2026-03-23*
