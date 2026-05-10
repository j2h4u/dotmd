# External Integrations

**Analysis Date:** 2026-05-10

## APIs & External Services

**Text Embeddings Inference (TEI):**
- HuggingFace TEI server — dense vector encoding for all indexed chunks and search queries
  - SDK/Client: `httpx` (async HTTP POST to `{embedding_url}/embed` and `{embedding_url}/info`)
  - Auth: none (internal Docker network only)
  - Config: `DOTMD_EMBEDDING_URL` (required at runtime)
  - Docker image: `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9`
  - Port: 8088 (senbonzakura deployment, exclusive consumer)
  - Batch tuning: auto-reduces `tei_batch_size` on HTTP 413 errors
  - Model discovery: `/info` endpoint queried at startup to resolve actual model ID (overrides `DOTMD_EMBEDDING_MODEL` config)
  - Prefix handling: E5/BGE models get `"query: "` / `"passage: "` prefixes; Qwen3-Embedding gets instruction prefix; auto-detected from model name
  - Implementation: `backend/src/dotmd/search/semantic.py` (`SemanticSearchEngine`)

**Modal (GPU cloud functions):**
- GPU-accelerated embedding offload — separate workspace, not part of main container
  - SDK/Client: `modal >=0.73` (`modal/` directory, `modal/embed.py`)
  - Auth: Modal account credentials (managed by modal CLI)
  - Package: separate `dotmd-modal` pyproject (`modal/pyproject.toml`)
  - Note: Not active in production deployment; TEI CPU container is the live transport

**mcp-telegram daemon (federated search source):**
- Telegram message search integrated as a federated `ApplicationSourceProvider`
  - Transport: UNIX socket (`DOTMD_TELEGRAM_DAEMON_SOCKET` env var, `Path | None`)
  - Protocol: JSON over socket (TelegramSourceClientProtocol defined in `backend/src/dotmd/ingestion/telegram_provider.py`)
  - Operations: `describe_source`, `export_source_changes` (cursor-based delta pull), `read_source_unit_window`, `search_messages`
  - Used for: (1) ingestion of Telegram messages as `ApplicationSourceChange` objects; (2) federated native search returning `SearchCandidate` objects
  - Metadata surfaced to search: `dialog_id`, `message_id`, `sender`, `sent_at`, `dialog_name`
  - Low-signal filtering: short acknowledgement texts (ok, yes, да, нет, etc.) are suppressed at provider level
  - External daemon: `mcp-telegram` container at `/opt/docker/mcp-telegram/`, exposes UNIX socket

## Data Storage

**Databases:**

**SQLite (unified index database):**
- Stores: chunk metadata, FTS5 full-text search tables, sqlite-vec vector embeddings, fingerprint tracking, M2M file_paths, source lifecycle state
- File: `index.db` in `DOTMD_INDEX_DIR` (`/dotmd-index/` in production)
- Docker volume: `dotmd_dotmd-index`
- Client: Python stdlib `sqlite3` + `sqlite-vec` extension
- Key stores:
  - `backend/src/dotmd/storage/metadata.py` — `SQLiteMetadataStore` (chunks, M2M, stats)
  - `backend/src/dotmd/storage/sqlite_vec.py` — `SQLiteVecVectorStore` (vector tables)
  - `backend/src/dotmd/search/fts5.py` — FTS5 full-text search tables
- Schema: two-dimensional keyed by `(chunk_strategy, embedding_model)` — supports multiple strategies/models simultaneously
- Embedding reuse: `text_hash` column (BLAKE3) — skip re-encoding unchanged content on model switch

**SQLite (feedback database):**
- Stores: agent feedback on search results
- File: `feedback.db` in `DOTMD_INDEX_DIR`
- Client: Python stdlib `sqlite3`
- Implementation: `backend/src/dotmd/feedback.py`
- Access: `dotmd feedback` CLI commands only (never query directly)

**FalkorDB (production graph backend):**
- Stores: knowledge graph — File, Section, Entity, Tag nodes with relationships
- Connection: Redis protocol (`DOTMD_FALKORDB_URL`, e.g. `redis://falkordb:6379`)
- Client: `FalkorDB >=1.6.0` Python SDK
- Docker image: `falkordb/falkordb:latest`
- Docker volume: `falkordb-data`
- Graph name: `DOTMD_FALKORDB_GRAPH_NAME` (default `"dotmd"`)
- Implementation: `backend/src/dotmd/storage/falkordb_graph.py` (`FalkorDBGraphStore`)
- Indexes: range indexes auto-created on startup for `File`, `Section`, `Entity`, `Tag`, `Node` labels
- Shared container: standalone FalkorDB at `/opt/docker/falkordb/` (also used by other services — graph name isolation required)

**LadybugDB (local dev graph backend):**
- Embedded graph DB, no separate container required
- Package: `real_ladybug >=0.1`
- Selected when `DOTMD_GRAPH_BACKEND=ladybugdb` (default)
- Data path: `{index_dir}/graphdb_{chunk_strategy}`
- Implementation: `backend/src/dotmd/storage/graph.py`

**File Storage:**
- Source markdown files: bind-mounted at `/mnt/` inside container (`DOTMD_DATA_DIR=/mnt`, locked — never narrow)
- HuggingFace model cache: Docker volume `dotmd_dotmd-hf-models` → `/root/.cache/huggingface`
- No external object storage

**Caching:**
- Extraction cache: SQLite table in `index.db` (`backend/src/dotmd/storage/cache.py`) — caches GLiNER NER results keyed by content hash + model name
- Embedding reuse: `text_hash` (BLAKE3) in `index.db` — cross-strategy embedding cache without re-encoding
- No external cache service (no Redis used by dotMD directly, only FalkorDB uses the Redis protocol)

## Authentication & Identity

**MCP OAuth 2.0 (optional, for external/Tailscale access):**
- Provider: custom JSON-backed OAuth AS (`backend/src/dotmd/auth.py`, `DotMDOAuthProvider`)
- Implements: `OAuthAuthorizationServerProvider` from `mcp.server.auth`
- Tokens stored: JSON files in `DOTMD_INDEX_DIR`
- Token lifetime: 30 days (access), 5 minutes (auth code)
- Pairing: 8-character codes, max 5 failed attempts, rate-limited
- Config: `DOTMD_BASE_URL` (must be HTTPS except localhost), `DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES`
- Tailscale integration: base URL points to `senbonzakura.tailf87223.ts.net/dotmd`; Tailscale Serve strips `/dotmd` prefix before forwarding to container

**stdio / internal Docker network:**
- No auth — MCP stdio (Claude Code via `.mcp.json`) and HTTP on internal Docker network require no credentials
- `.mcp.json`: `docker exec -i dotmd dotmd mcp` (stdio per-session subprocess)

## Monitoring & Observability

**Error Tracking:**
- None (no Sentry or equivalent)

**Logs:**
- Structured Python logging via stdlib (`backend/src/dotmd/utils/logging.py`)
- Collected by Grafana Alloy (Docker log collection from container stdout)
- Profiling: `DOTMD_PROFILE_INDEXING=true` enables per-phase timing logs in pipeline
- Request logging: middleware in `backend/src/dotmd/api/server.py` logs method/path/status/duration for every HTTP request

**Agent Feedback:**
- Agents submit feedback via MCP `feedback` tool → stored in `feedback.db`
- Review via `dotmd feedback` CLI (`backend/src/dotmd/feedback.py`)

## CI/CD & Deployment

**Hosting:**
- Single Docker container `dotmd` on senbonzakura server
- Compose config: `/opt/docker/dotmd/` (production) and `docker-compose.yml` (repo, for bundled local dev)
- Source bind-mounted → code changes require only container restart, not image rebuild

**CI Pipeline:**
- None detected (no `.github/workflows/`, no CI config in repo)

**Image builds:**
- `docker compose build` (context: `./backend/`)
- Rebuild required only when `backend/pyproject.toml` or `backend/start.sh` changes

## Environment Configuration

**Required env vars (production runtime):**
- `DOTMD_EMBEDDING_URL` — TEI server base URL (e.g. `http://embeddings:8088`)
- `DOTMD_DATA_DIR` — source markdown root (locked to `/mnt`)
- `DOTMD_INDEX_DIR` — index directory (locked to `/dotmd-index`)
- `DOTMD_INDEXING_PATHS` — absolute path specs for markdown discovery (comma-separated)
- `DOTMD_GRAPH_BACKEND` — `falkordb` (prod) or `ladybugdb` (dev)
- `DOTMD_FALKORDB_URL` — FalkorDB Redis URL (required when `graph_backend=falkordb`)
- `DOTMD_FALKORDB_GRAPH_NAME` — graph name in FalkorDB instance

**Optional env vars:**
- `DOTMD_EMBEDDING_MODEL` — model name hint (TEI auto-detects actual model via `/info`)
- `DOTMD_EMBEDDING_WEIGHTS` — dual-encoder fusion weights (default `"text=0.7,meta=0.3"`)
- `DOTMD_TEI_BATCH_SIZE` — initial TEI batch size (auto-tunes down on 413)
- `DOTMD_BASE_URL` — public HTTPS URL for OAuth 2.0 (enables OAuth when set)
- `DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES` — comma-separated URI prefix whitelist
- `DOTMD_TELEGRAM_DAEMON_SOCKET` — UNIX socket path to mcp-telegram daemon
- `DOTMD_FEDERATED_TIMEOUT_SECONDS` — per-source federated search timeout (default 4.0)
- `DOTMD_PROFILE_INDEXING` — `true` to enable pipeline timing logs
- `DOTMD_EXTRACT_DEPTH` — `structural` or `ner` (default `ner`)
- `DOTMD_RERANKER_MODEL` — reranker model ID
- `DOTMD_CHUNK_STRATEGY` — chunking strategy key (default `heading_512_50`)

**Secrets location:**
- `/opt/docker/dotmd/.env` (sourced via `env_file:` in production compose)
- Never stored adjacent to repo — convention: `~/.secrets/` or `/opt/docker/<project>/.env`

## Webhooks & Callbacks

**Incoming:**
- None (no inbound webhooks)

**Outgoing:**
- None (no outbound webhooks)

## MCP Interface

**stdio transport** — for Claude Code in this project:
- Config: `.mcp.json` at repo root
- Command: `docker exec -i dotmd dotmd mcp` (each Claude Code session spawns fresh subprocess)
- No auth required

**HTTP (streamable-http) transport** — for other containers on Docker network:
- Endpoint: `http://dotmd:8080/mcp`
- Access: join `dotmd_default` Docker network
- OAuth optional (enabled via `DOTMD_BASE_URL`)

**Exposed tools:** `search(query, top_k)`, `read(file_path, start, end)`, `feedback(...)`

---

*Integration audit: 2026-05-10*
