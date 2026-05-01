# dotMD

**Local markdown knowledgebase search for humans and AI agents.**

dotMD indexes markdown files and exposes hybrid retrieval through a CLI, REST API, and MCP server. It combines semantic search, SQLite FTS5 keyword search, and graph-based entity retrieval, then fuses and reranks results for higher precision.

Everything runs against local or self-hosted services. No hosted LLM API key is required for normal indexing or search.

The default reranker is `Qwen/Qwen3-Reranker-0.6B` through the local
SentenceTransformers CrossEncoder path. It was selected from public benchmark,
publication-age, and deployment-fit research rather than a dotMD-specific local
benchmark harness: by May 2026 it is fresh enough for default selection, text-only,
0.6B, multilingual, and operationally simpler than the heavier Qwen3-VL rerankers.
ContextualAI rerank-v2 and Jina v3 remain alternates if Qwen integration or
latency fails; older GTE/BGE rerankers are fallback-only despite easier serving.

## Features

- Hybrid search across semantic vectors, FTS5 keywords, and knowledge graph entities
- MCP server for Claude Code, Cursor, VS Code, OpenCode, and other MCP clients
- Content-aware markdown chunking for docs, meeting transcripts, and voicenotes
- Unified SQLite `index.db` for metadata, FTS5, fingerprints, and sqlite-vec vectors
- Multiple chunk strategies and embedding models in the same index
- External TEI embedding server support
- FalkorDB production graph backend with LadybugDB as the embedded local default
- Background trickle indexer for incremental file changes

## Requirements

| Requirement | Purpose |
|-------------|---------|
| Python 3.12+ | Runtime |
| uv | Recommended local dependency manager |
| Docker and Docker Compose | Containerized runtime and bundled services |
| just | Development task runner |
| TEI | Required embedding server for normal indexing/search |
| FalkorDB | Production graph backend when `DOTMD_GRAPH_BACKEND=falkordb` |

Optional tools:

- Pandoc, Docling, or Markitdown for converting non-markdown sources before indexing

## Quick Start

Install dependencies and run the local quality gate:

```bash
just setup
cp .env.example .env  # optional, if you need local overrides
just check
```

Run the service stack:

```bash
just docker-up-bundled
```

For local CLI development without Docker, set `DOTMD_EMBEDDING_URL` to a running TEI-compatible server before indexing:

```bash
cd backend
uv run dotmd index ../data
uv run dotmd search "how do we deploy this service?"
```

## Common Commands

```bash
just               # show available project commands
just test          # run backend tests
just test-smoke    # run smoke tests
just lint          # run Ruff checks
just fmt           # format and auto-fix with Ruff
just typecheck     # run Pyright ratchet
just check         # lint + typecheck ratchet + tests
```

## Usage

### Index Markdown

```bash
cd backend
uv run dotmd index /path/to/markdown
```

Use custom entity types for GLiNER NER:

```bash
uv run dotmd index /path/to/markdown --entity-types "person,technology,concept,project"
```

Manual indexing is mainly for development and debugging. In normal service mode, the background trickle indexer detects new, changed, and deleted files.

### Search

```bash
uv run dotmd search "how to deploy to production"
```

Search modes:

```bash
uv run dotmd search "query" --mode hybrid     # semantic + keyword + graph
uv run dotmd search "query" --mode semantic   # vector similarity
uv run dotmd search "query" --mode keyword    # SQLite FTS5 keyword search
uv run dotmd search "query" --mode graph      # graph retrieval
uv run dotmd search "query" --no-rerank       # skip cross-encoder reranking
uv run dotmd search "query" --no-expand       # skip query expansion
uv run dotmd search "query" --top 5           # limit results
```

### REST API

```bash
cd backend
uv run dotmd serve
uv run dotmd serve --host 0.0.0.0 --port 9000
```

### MCP Server

stdio transport:

```bash
cd backend
uv run dotmd mcp
```

HTTP transport:

```bash
cd backend
uv run dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

Generate a local MCP client config:

```bash
cd backend
uv run dotmd mcp-config
```

Production uses streamable HTTP on port `8080` inside the Docker network. Health is exposed at `GET /health`.

## Docker

```bash
just docker-build
just docker-up
```

To start bundled local dependencies:

```bash
just docker-up-bundled
```

The compose profile starts:

- `dotmd` - MCP HTTP server
- `tei` - Hugging Face Text Embeddings Inference
- `falkordb` - graph database

Index data is stored in the `dotmd-index` Docker volume.

## Configuration

Configuration comes from `DOTMD_` environment variables, explicit `Settings(...)` overrides, and `~/.dotmd/config.toml`.

| Variable | Default | Description |
|----------|---------|-------------|
| `DOTMD_DATA_DIR` | `.` | Markdown source root |
| `DOTMD_INDEX_DIR` | `~/.dotmd` | Index directory |
| `DOTMD_EMBEDDING_URL` | required | TEI-compatible embedding endpoint |
| `DOTMD_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Model name used for local settings and TEI metadata |
| `DOTMD_TEI_BATCH_SIZE` | `4` | Embedding batch size |
| `DOTMD_VECTOR_BACKEND` | `sqlite-vec` | Vector backend; LanceDB remains legacy/optional |
| `DOTMD_GRAPH_BACKEND` | `ladybugdb` | `ladybugdb` or `falkordb` |
| `DOTMD_FALKORDB_URL` | `redis://localhost:6379` | FalkorDB Redis URL |
| `DOTMD_EXTRACT_DEPTH` | `ner` | `structural` or `ner` |
| `DOTMD_BASE_URL` | unset | Public HTTPS base URL for OAuth-enabled MCP deployments |
| `DOTMD_RERANKER_BACKEND` | `cross_encoder` | Reranker provider boundary; currently local CrossEncoder |
| `DOTMD_RERANKER_MODEL` | `Qwen/Qwen3-Reranker-0.6B` | Selected multilingual reranker model |
| `DOTMD_RERANKER_RELEVANCE_FLOOR` | unset | Optional raw-score floor; unset keeps all reranked candidates |

## Architecture

```
backend/src/dotmd/
├── core/          # Pydantic models, settings, exceptions
├── ingestion/     # Reader, chunker, pipeline, trickle indexer, migration
├── extraction/    # Structural extraction and GLiNER NER
├── storage/       # SQLite metadata/FTS5/sqlite-vec, FalkorDB, LadybugDB
├── search/        # Semantic, FTS5, graph-direct, fusion, reranker
├── api/           # DotMDService facade and FastAPI server
├── mcp_server.py  # FastMCP server
└── cli.py         # Click CLI
```

Search pipeline:

```text
query -> expand -> semantic + FTS5 + graph-direct -> RRF fusion -> cross-encoder rerank
```

If the reranker is unavailable, errors, or returns no surviving candidates after
an optional score floor, search falls back to fused semantic/FTS5/graph ranking.
Use `--no-rerank` to skip reranking explicitly.

## MCP Tools

| Tool | Description |
|------|-------------|
| `search` | Search indexed markdown content |
| `read` | Read indexed file content by chunk range |
| `feedback` | Submit agent feedback for later review |

## Development Notes

- Public API entry points should go through `dotmd.api.service.DotMDService`.
- Do not reload indexes per request; stores are loaded once and reused.
- Do not run `dotmd index --force` while the production container is running; the trickle indexer holds the `fcntl` lock.
- Batch small production changes and restart once.

## License

MIT
