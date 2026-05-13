# AGENTS.md — dotMD

## Project Status

dotMD is a **heavily modified fork** of an upstream markdown knowledgebase search tool.
The upstream project appears inactive — last commit January 2026 ("docs update").
We treat this as our own project with independent development direction.

## Branches

- **`dev`** — our working branch. All development happens here. Significantly diverged from upstream.
- **`main`** — tracks upstream (`remotes/upstream/main`). Synced automatically by `git-sync.timer`. Do not commit directly. Exists only as a reference for upstream changes if they ever resume.

**Always work in `dev`.** Feature branches off `dev` when needed, merge back to `dev`.

## What Changed From Upstream

The fork has been substantially reworked:

- **Unified database**: single `index.db` (was separate `metadata.db` + `vec.db`)
- **Two-dimensional storage**: tables keyed by `(chunk_strategy, embedding_model)` — supports multiple chunking strategies and embedding models simultaneously
- **Content-aware chunking**: speaker-turn splitting for meeting transcripts, paragraph splitting for voicenotes, heading-based for docs
- **Context prefix injection**: document title prepended to embeddings at encode time
- **Graph-first entity retrieval**: entity-direct graph search as RRF peer alongside semantic and FTS5
- **Embedding reuse**: text_hash column enables cross-strategy embedding cache
- **Split fingerprints**: chunk tracking and embed tracking separated (change model → skip re-chunking)
- **Exclusive lock**: `fcntl.flock` prevents parallel indexing
- **Orphan cleanup**: automatic at trickle startup
- **M2M content-addressed schema**: chunks → file_paths many-to-many (Phase 16)
- **sqlite-vec**: replaced LanceDB with sqlite-vec (no AVX2 requirement)
- **FTS5**: replaced rank_bm25 with SQLite FTS5 (incremental, no pickle, column weights)
- **FalkorDB**: production graph backend; LadybugDB kept as embedded local-dev default
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
does not ingest into the local SQLite/FTS/vector index in Phase 37.
`source_native_score=None` is safe because federated candidates bypass RRF and
flow through quota-based `_merge_with_federated_quota()`.

## Tech Stack

| Component | Technology |
|-----------|------------|
| Language | Python 3.12+ |
| Vector store | sqlite-vec |
| Graph DB | FalkorDB (production) / LadybugDB (local dev, no container needed) |
| Metadata + FTS | SQLite + FTS5 |
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
│       ├── storage/      # sqlite-vec (vectors), FalkorDB/LadybugDB (graph), SQLite (metadata + FTS5)
│       ├── search/       # semantic, FTS5, graph_direct, fusion, reranker, query
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
  search/fts5.py          — FTS5 keyword search
  api/service.py          — DotMDService facade
  api/server.py           — FastAPI REST API
  cli.py                  — Click CLI
```

Search pipeline: query → expand → 3 engines parallel (semantic + FTS5 + graph) → RRF fuse → cross-encoder rerank → top-K.

## Storage

Production index lives on docker volume `dotmd_dotmd-index` (mapped to `/dotmd-index/` in container):
- `index.db` — unified database: chunk metadata, FTS5 tables, sqlite-vec embeddings, fingerprints, M2M file_paths

Graph stored externally in FalkorDB (shared `falkordb` Docker network).

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
| `DOTMD_GRAPH_BACKEND` | `falkordb` (prod) or `ladybugdb` (local dev) |
| `DOTMD_FALKORDB_URL` | FalkorDB Redis URL |
| `DOTMD_FALKORDB_GRAPH_NAME` | Graph name in FalkorDB |
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
- FalkorDB (`falkordb`) — knowledge graph (standalone container)

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
