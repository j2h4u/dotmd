# AGENTS.md — dotMD

## Project Status

dotMD is an **independent markdown knowledgebase search service** descended from
an older upstream project. GitHub fork-network linkage has been removed; this is
now a standalone repository with its own product and architecture direction.

## Branches

- **`main`** — default and working branch. All development happens here.

**Always work in `main`.** Feature branches off `main` when needed, merge back to `main`.

## Major Product Changes Since Origin

The project has been substantially reworked:

- **Standalone SurrealDB cutover**: production storage and retrieval target
  the standalone SurrealDB database `dotmd/production`
- **Internal cache database**: `index.db` remains migration/internal-cache
  scaffolding; it is not a production retrieval backend
- **Two-dimensional storage**: tables keyed by `(chunk_strategy, embedding_model)` — supports multiple chunking strategies and embedding models simultaneously
- **Content-aware chunking**: speaker-turn splitting for meeting transcripts, paragraph splitting for voicenotes, heading-based for docs
- **Context prefix injection**: document title prepended to embeddings at encode time
- **Graph-first entity retrieval**: entity-direct graph search as RRF peer alongside semantic and keyword retrieval
- **Embedding reuse**: text_hash column enables cross-strategy embedding cache
- **Split fingerprints**: chunk tracking and embed tracking separated (change model → skip re-chunking)
- **Exclusive lock**: `fcntl.flock` prevents parallel indexing
- **Orphan cleanup**: automatic at trickle startup
- **M2M content-addressed schema**: chunks → file_paths many-to-many (Phase 16)
- **SurrealDB-native retrieval**: semantic, keyword, and graph-direct retrieval
  run through standalone SurrealDB
- **Retired storage backends**: SQLite/sqlite-vec/FTS5/FalkorDB/LadybugDB are retired and must not be described as production runtime choices
- **TEI**: external embedding server (Text Embeddings Inference), CPU-only

## Phase 37: Airweave Connector Compatibility

**Decision: vendored Airweave platform slice**
Airweave is not pip-installed because the full package pulls in runtime and
platform dependencies dotMD does not use. Only the platform slice needed for
Gmail compatibility is vendored into `backend/src/dotmd/vendor/airweave/`.
See `VENDOR_VERSION` and `VENDOR_NOTES.md` for source tracking and local deltas.

**Decision: direct Gmail API search, not `GmailSource.search()`**
Airweave's GmailSource does not implement `search()`. The Gmail bridge calls
the Gmail API directly. Future connectors must check whether `search()` exists
before assuming the source can be wrapped directly.

**Decision: `BaseConnectorBridge` ABC**
`backend/src/dotmd/ingestion/gmail_provider.py` defines the generic bridge
contract: `search_native()`, `read_unit_window()`, and `to_search_candidate()`.
`GmailBridge` is the first implementation.

**Decision: OAuth token caching with `threading.Lock`**
`GmailOAuthTokenProvider` uses margin-based expiry (`expires_in - 300`) and
`threading.Lock` to serialize concurrent refresh calls. The refresh token lives
in `GmailSourceConfig.refresh_token`, not `SourceAccess.delegated_to`.

**Decision: Gmail is federated-only**
Gmail participates through live federated search and readable message refs. It
does not ingest into the local SurrealDB-backed index.
`source_native_score=None` is safe because federated candidates bypass RRF and
flow through quota-based `_merge_with_federated_quota()`.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| Storage + retrieval | Standalone SurrealDB |
| Vector index | SurrealDB HNSW |
| Metadata + graph + keyword | SurrealDB tables/indexes |
| Embeddings | TEI (Text Embeddings Inference) — external container |
| Reranker | cross-encoder/ms-marco-MiniLM-L-6-v2 |
| NER | GLiNER (urchade/gliner_multi-v2.1) — zero-shot |
| CLI | Click |
| Models | Pydantic v2 |

## Monorepo Structure

```
dotMD/
├── backend/              # Python package (src layout)
│   ├── pyproject.toml
│   ├── start.sh          # container entrypoint — single process: MCP HTTP (streamable-http, port 8080)
│   └── src/dotmd/        # importable package
│       ├── core/         # models, config, exceptions
│       ├── ingestion/    # reader, chunker, pipeline, trickle, migration
│       ├── extraction/   # structural, GLiNER NER
│       ├── storage/      # SurrealDB plus temporary migration/cache scaffolding
│       ├── search/       # semantic, Surreal keyword/graph_direct, fusion, reranker, query
│       ├── api/          # DotMDService facade + FastAPI server
│       ├── mcp_server.py # FastMCP server (search, read, feedback tools)
│       └── cli.py        # Click CLI (thin wrapper over api/service.py)
├── .mcp.json             # Claude Code MCP config (stdio via docker exec)
├── data/                 # Sample markdown files for testing
└── README.md
```

## Architecture Overview

Key paths:

```
backend/src/dotmd/
  ingestion/pipeline.py   — IndexingPipeline (orchestrates everything)
  ingestion/trickle.py    — background file watcher + indexer
  ingestion/chunker.py    — content-aware chunking
  search/semantic.py      — TEI embedding + vector search
  search/graph_direct.py  — entity-direct graph retrieval
  search/surreal_fts.py   — SurrealDB keyword search
  api/service.py          — DotMDService facade
  api/server.py           — FastAPI REST API
  cli.py                  — Click CLI
```

Search pipeline: query → expand → 3 Surreal-backed engines parallel
(semantic + keyword + graph) → RRF fuse → cross-encoder rerank → top-K.

## Storage

Production storage lives in standalone SurrealDB:
- namespace: `dotmd`
- database: `production`
- data directory: `/srv/surrealdb/data`

`/dotmd-index/index.db` remains migration/cache scaffolding.

## Configuration

Production env vars (source: `/opt/docker/dotmd/.env`):

| Variable | Purpose |
|----------|---------|
| `DOTMD_DATA_DIR` | Markdown source root — **locked to `/mnt`**, never narrow |
| `DOTMD_INDEX_DIR` | Index directory (docker volume mount) |
| `DOTMD_EMBEDDING_URL` | TEI server URL |
| `DOTMD_EMBEDDING_MODEL` | Model name passed to TEI |
| `DOTMD_TEI_BATCH_SIZE` | TEI call batch size |
| `DOTMD_EXTRACT_DEPTH` | `structural` or `ner` |
| `DOTMD_SURREAL_RETRIEVAL_URL` | Standalone SurrealDB URL |
| `DOTMD_SURREAL_RETRIEVAL_NAMESPACE` | SurrealDB namespace, normally `dotmd` |
| `DOTMD_SURREAL_RETRIEVAL_DATABASE` | SurrealDB database, normally `production` |
| `DOTMD_SURREAL_RETRIEVAL_EMBEDDING_DIMENSION` | Embedding dimension, currently `1024` |
| `DOTMD_SURREAL_RETRIEVAL_VECTOR_INDEX_TYPE` | HNSW vector type, currently `F16` |
| `DOTMD_PROFILE_INDEXING` | Enable pipeline timing logs |

## Deployment

Single container `dotmd` (container_name: dotmd) on senbonzakura. See `/opt/docker/dotmd/` for compose config.

`backend/start.sh` is the ENTRYPOINT — single process:
```sh
exec dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080
```

- **MCP HTTP**: port 8080, internal Docker network only (no external mapping)
- **Health**: `GET /health` on port 8080 → `{"status":"ok"}` (used by Docker healthcheck)

External dependencies (separate containers):
- TEI (`embeddings` service, port 8088) — embedding server
- SurrealDB (`surrealdb`, host port 8000) — storage and retrieval database

Source code is bind-mounted into the container — code changes take effect on container restart, no image rebuild needed. Rebuild only when `pyproject.toml` or `start.sh` changes.

## MCP Interface

Two transports available:

**stdio** — for Claude Code in this project. Configured in `.mcp.json`:
```json
{"command": "docker", "args": ["exec", "-i", "dotmd", "dotmd", "mcp"]}
```
Each session spawns a fresh `dotmd mcp` subprocess inside the running container.

**HTTP (streamable-http)** — for other containers on the Docker network. Endpoint: `http://dotmd:8080/mcp`. Connect by joining the `dotmd_default` network.

Tools exposed: `search(query, top_k)`, `read(file_path, start, end)`, `feedback(...)`.

## Agent Feedback

Agents submit feedback via the `feedback` MCP tool. To review:

```bash
docker exec dotmd dotmd feedback list        # open + in_progress
docker exec dotmd dotmd feedback list --all  # include done/dismissed
docker exec dotmd dotmd feedback status <id> done --reason "..."
docker exec dotmd dotmd feedback delete <id>
```

Feedback lives in `/dotmd-index/feedback.db` (inside the docker volume). Never query it directly — use the CLI.

## When Modifying Code

- New storage backends: implement the Protocol from `storage/base.py`
- New extractors: implement `ExtractorProtocol` from `extraction/base.py`
- New search engines: implement `SearchEngineProtocol` from `search/base.py`
- All public APIs go through `api/service.py` — never expose internals directly
- **Never reload indexes per-request.** Indexes must be loaded once at startup and reused. Calling `load_index()` inside search methods causes disk I/O on every request.
- **Never run `dotmd index --force` while the container is running** — trickle holds the fcntl lock. Stop the container first.
- **Never restart production on small changes** — batch changes, deploy once.
