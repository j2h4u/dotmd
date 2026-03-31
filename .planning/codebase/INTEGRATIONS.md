# External Integrations

**Analysis Date:** 2026-03-23

## APIs & External Services

**Text Embeddings Inference (TEI):**
- Remote embedding server (optional)
  - HTTP POST to `/embed` endpoint
  - SDK/Client: `httpx` (built-in httpx library)
  - Configuration: `DOTMD_EMBEDDING_URL` (e.g., `http://embeddings:8088`)
  - When set, overrides local `sentence-transformers` model
  - Batching: queries sent in chunks of 4 to avoid 413 Payload Too Large
  - Used by `SemanticSearchEngine._encode_via_tei()` in `search/semantic.py`

**HuggingFace Hub (Model Downloads):**
- Implicit integration via `sentence-transformers` and GLiNER
- Models auto-downloaded on first use:
  - `BAAI/bge-small-en-v1.5` for embeddings
  - `cross-encoder/ms-marco-MiniLM-L-6-v2` for reranking
  - `urchade/gliner_multi-v2.1` for NER
- No explicit auth required (public models)
- Downloaded to `~/.cache/huggingface/` by default

## Data Storage

**Databases:**

- **Vector Store (sqlite-vec)** - Default
  - Type: SQLite + sqlite-vec extension (embedded, file-based)
  - Connection: Local file at `~/.dotmd/vec.db`
  - Client: `sqlite3` (Python stdlib) + `sqlite_vec` extension
  - Schema: two tables (`vec_chunks` virtual table, `vec_meta` metadata)
  - Implementation: `storage/sqlite_vec.py`

- **Vector Store (LanceDB)** - Alternative
  - Type: Embedded columnar DB (Arrow-based)
  - Connection: Local directory at `~/.dotmd/lancedb/`
  - Client: `lancedb` package
  - Schema: single table (`chunks` with id, vector, chunk_id columns)
  - Implementation: `storage/vector.py`
  - Selected via `DOTMD_VECTOR_BACKEND=lancedb` (default is `sqlite-vec`)

- **Knowledge Graph (LadybugDB)**
  - Type: Embedded Cypher graph database (forked from Kuzu)
  - Connection: Local directory at `~/.dotmd/graphdb/`
  - Client: `real_ladybug` package
  - Schema: 4 node types (File, Section, Entity, Tag) + 7 relationship tables
  - Implementation: `storage/graph.py`
  - Supports read-only mode for queries

- **Metadata & Index Info (SQLite)**
  - Type: SQLite database (standard)
  - Connection: Local file at `~/.dotmd/metadata.db`
  - Client: `sqlite3` (Python stdlib)
  - Schema: chunk metadata (file_path, heading_path, text, text_preview, etc.) + index stats
  - Implementation: `storage/metadata.py`

- **BM25 Index**
  - Type: Pickled Python object (serialized)
  - Connection: Local file at `~/.dotmd/bm25_index.pkl`
  - Client: `rank_bm25` package + pickle stdlib
  - Schema: BM25 index state
  - Implementation: `search/bm25.py`

**File Storage:**
- **Local filesystem only** - Markdown source files (indexed by `ingestion/reader.py`)
- No cloud storage integration

**Caching:**
- HuggingFace model cache (~/.cache/huggingface/)
- No distributed caching system
- Indexes persist to `~/.dotmd/` directory

## Authentication & Identity

**Auth Provider:**
- None - No authentication system
- Access is implicit: whoever can access the index directory and binaries can search
- MCP server runs without auth (assumes Claude Desktop or trusted client)
- REST API runs without auth (assumes deployment behind reverse proxy or firewall)

## Monitoring & Observability

**Error Tracking:**
- None configured
- Exceptions logged via Python `logging` module
- Can be integrated with external log aggregators via standard logging handlers

**Logs:**
- Python `logging` module (configured in `utils/logging.py`)
- Console output (stdout/stderr)
- Verbosity controlled by `--verbose` CLI flag or `DOTMD_VERBOSE` env var
- Log level: INFO by default, DEBUG when verbose

## CI/CD & Deployment

**Hosting:**
- Docker container (Dockerfile + docker-compose.yml)
- Can run standalone Python (`dotmd serve`, `dotmd mcp`)
- Multi-stage Docker build optimized for CPU-only systems

**CI Pipeline:**
- Not detected - No GitHub Actions, GitLab CI, or other CI configuration

## Environment Configuration

**Required env vars:**
- `DOTMD_DATA_DIR` - Path to markdown files to index (default: current directory)
- `DOTMD_INDEX_DIR` - Path where indexes are stored (default: `~/.dotmd/`)

**Optional env vars (search & ML):**
- `DOTMD_EMBEDDING_MODEL` - HuggingFace model ID for embeddings (default: `BAAI/bge-small-en-v1.5`)
- `DOTMD_EMBEDDING_URL` - URL to TEI embedding server (default: None, uses local model)
- `DOTMD_VECTOR_BACKEND` - `sqlite-vec` or `lancedb` (default: `sqlite-vec`)
- `DOTMD_EXTRACT_DEPTH` - `structural` or `ner` (default: `ner`)
- `DOTMD_NER_ENTITY_TYPES` - Comma-separated entity types for GLiNER (default: person,organization,technology,concept,location,object,activity,date_time)
- `DOTMD_RERANKER_MODEL` - HuggingFace model for cross-encoder (default: `cross-encoder/ms-marco-MiniLM-L-6-v2`)

**Secrets location:**
- None by default - No secrets management
- Environment variables used for all config
- In Kubernetes/production: mount `.env` via ConfigMap/Secret or inject variables at runtime

## Webhooks & Callbacks

**Incoming:**
- None - dotMD is pull-only (searches initiated by client)

**Outgoing:**
- None - No event callbacks or webhooks emitted

## Integration Patterns

**Query Expansion:**
- Uses acronym dictionary (JSON file at `~/.dotmd/acronyms.json`)
- Loaded on service startup if file exists
- Implementation: `search/query.py` QueryExpander class

**Search Pipeline:**
- 3 search engines run in parallel:
  1. Semantic (embeddings) via `SemanticSearchEngine`
  2. BM25 keyword search via `BM25SearchEngine`
  3. Graph traversal via `GraphSearchEngine`
- Results fused via Reciprocal Rank Fusion (RRF) in `search/fusion.py`
- Optional cross-encoder reranking via `search/reranker.py`
- Implementation: `api/service.py` DotMDService.search()

**Interfaces:**
- REST API: FastAPI in `api/server.py` (port 8000)
- CLI: Click commands in `cli.py`
- MCP: FastMCP server in `mcp_server.py` (stdio-based)

---

*Integration audit: 2026-03-23*
