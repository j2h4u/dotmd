# dotMD

**Local markdown knowledgebase search for humans and AI agents.**

dotMD indexes markdown files and exposes hybrid retrieval through a CLI, REST API, and MCP server. Production retrieval now runs through standalone SurrealDB for semantic vectors, keyword search, and graph-backed entity retrieval, then fuses and reranks results for higher precision. SurrealDB is the only production storage and retrieval backend; `index.db` is leftover cutover debt kept only until the removal slice lands.

Everything runs against local or self-hosted services. No hosted LLM API key is required for normal indexing or search.

The production default is one selected reranker, not multi-reranker serving:
`DOTMD_RERANKER_NAME=mmarco-minilm` maps to
`cross-encoder/mmarco-mMiniLMv2-L12-H384-v1` through the local
SentenceTransformers CrossEncoder path. Phase 20/21 established the staged
reranker benchmark process: first eliminate slow models by latency, then compare
quality on live Russian/mixed dotMD queries. The current production registry
keeps only `mmarco-minilm`; rejected historical candidates remain documented in
[`docs/reranker-benchmark-methodology.md`](docs/reranker-benchmark-methodology.md).

## Features

- Hybrid search across semantic vectors, keyword search, and knowledge graph entities
- MCP server for Claude Code, Cursor, VS Code, OpenCode, and other MCP clients
- Content-aware markdown chunking for docs, meeting transcripts, and voicenotes
- Standalone SurrealDB is the only production storage and retrieval backend
- Multiple chunk strategies and embedding models in the same index
- External TEI embedding server support
- Background trickle indexer for incremental file changes

## Requirements

| Requirement | Purpose |
|-------------|---------|
| Python 3.12+ | Runtime |
| uv | Recommended local dependency manager |
| Docker and Docker Compose | Containerized runtime and bundled services |
| just | Development task runner |
| TEI | Required embedding server for normal indexing/search |
| SurrealDB | Required production storage and retrieval database; single production backend |

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

For local CLI development without Docker, set `DOTMD_EMBEDDING__URL` to a running TEI-compatible server before indexing:

```bash
cd backend
uv run dotmd index ../data
uv run dotmd search "how do we deploy this service?"
```

## Common Commands

```bash
just               # show available project commands
just test          # run local backend tests only; excludes live MCP e2e/smoke
just test-e2e      # run live MCP e2e inside the running dotMD container
just test-mcp-remote # run production/Funnel MCP connectivity smoke
just lint          # run Ruff checks
just fmt           # format and auto-fix with Ruff
just typecheck     # run Pyright ratchet
just check         # lint + typecheck ratchet + local tests
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
uv run dotmd search "query" --mode keyword    # SurrealDB keyword search
uv run dotmd search "query" --mode graph      # graph retrieval
uv run dotmd search "query" --no-rerank       # skip cross-encoder reranking
uv run dotmd search "query" --no-expand       # skip query expansion
uv run dotmd search "query" --top 5           # limit results
uv run dotmd search "пример запроса" --reranker mmarco-minilm
uv run dotmd rerank compare "пример запроса" --rerankers mmarco-minilm
```

`dotmd rerank compare` is a developer diagnostic command. It runs query
expansion, retrieval, graph enrichment, and fusion once, then sends the same
ordered candidate IDs to each selected reranker. The output reports per-reranker
`elapsed_ms`, human-readable `elapsed`, cold `load_ms`, hot `rerank_ms`,
returned ordering, scores, and top-ID overlap, sorted by fastest successful hot
rerank time with failures last, so CPU latency can be compared against
alternates without changing production behavior. It does not make production
search serve multiple rerankers and does not require a production restart when
run locally or inside the
container against the current code/config. Future candidates should be added
temporarily and evaluated with the staged benchmark methodology before they are
kept in the registry.

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

To start the bundled container stack with a running external SurrealDB instance:

```bash
just docker-up-bundled
```

The compose profile starts:

- `dotmd` - MCP HTTP server
- `tei` - Hugging Face Text Embeddings Inference

The production storage and retrieval backend is the external SurrealDB deployment. `index.db` is temporary cutover debt, not a desired permanent backend.

Index data is stored in the `dotmd-index` Docker volume.

## Configuration

Configuration comes from `~/.dotmd/config.toml`, nested `DOTMD_*__*` environment
variables, and explicit `Settings(...)` overrides. Use TOML for product
defaults. Use env vars for runtime URLs and secrets.

Example `~/.dotmd/config.toml`:

```toml
data_dir = "/mnt"
index_dir = "/dotmd-index"

[embedding]
model = "BAAI/bge-small-en-v1.5"
tei_batch_size = 4
weights = "text=0.7,meta=0.3"

[indexing]
paths = ["/mnt"]
chunk_strategy = "heading_512_50"
max_chunk_tokens = 512
chunk_overlap_tokens = 50

[extraction]
depth = "ner"
ner_model_name = "urchade/gliner_multi-v2.1"

[surreal_retrieval]
namespace = "dotmd"
database = "production"
embedding_dimension = 1024
hnsw_ef = 40
vector_index_type = "F16"
embedding_shard_count = 1

reranker_name = "mmarco-minilm"
reranker_backend = "cross_encoder"
reranker_model = "cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"
reranker_compare_names = "mmarco-minilm"
reranker_length_penalty = true
reranker_min_length = 50
default_top_k = 10
fusion_k = 60
rerank_pool_size = 20
semantic_score_floor = 0.85
snippet_length = 300
graph_max_hops = 2
```

Nested env overrides for runtime URLs and secrets:

```bash
DOTMD_EMBEDDING__URL=http://tei:80
DOTMD_SURREAL_RETRIEVAL__URL=http://surrealdb:8000
DOTMD_SURREAL_RETRIEVAL__USERNAME=root
DOTMD_SURREAL_RETRIEVAL__PASSWORD=change-me
```

The production retrieval stack is SurrealDB-only; `index.db` is temporary
cutover debt scheduled for removal.

## Architecture

```
backend/src/dotmd/
├── core/          # Pydantic models, settings, exceptions
├── ingestion/     # Reader, chunker, pipeline, trickle indexer, migration
├── extraction/    # Structural extraction and GLiNER NER
├── storage/       # SurrealDB plus temporary migration/cache scaffolding
├── search/        # Semantic, Surreal keyword/graph-direct, fusion, reranker
├── api/           # DotMDService facade and FastAPI server
├── mcp_server.py  # FastMCP server
└── cli.py         # Click CLI
```

Search pipeline:

```text
query -> expand -> semantic + keyword + graph-direct -> RRF fusion -> shared candidate pool -> cross-encoder rerank
```

If the reranker is unavailable, errors, or returns no surviving candidates after
an optional score floor, search falls back to fused semantic/keyword/graph ranking.
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
