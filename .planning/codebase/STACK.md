# Technology Stack

**Analysis Date:** 2026-05-10

## Languages

**Primary:**
- Python 3.12+ — entire backend (`backend/src/dotmd/`)

**Secondary:**
- TOML — package manifests and optional user config (`~/.dotmd/config.toml`)

## Runtime

**Environment:**
- CPython 3.12 (pinned via `requires-python = ">=3.12"` in `backend/pyproject.toml`)
- CPU-only deployment target (Xeon E3 V2 — AVX but NOT AVX2; constrains PyTorch to `<2.5`)

**Package Manager:**
- `uv` (modal workspace) / `pip` / `hatch` (backend build)
- Lockfile: `modal/uv.lock` present; backend has no lockfile (managed via `.venv` at `backend/.venv/`)

## Frameworks

**Core:**
- FastAPI `>=0.110` — REST API layer (`backend/src/dotmd/api/server.py`)
- Uvicorn `>=0.29` (standard extras) — ASGI server
- FastMCP / `mcp[cli] >=1.0` — MCP server (`backend/src/dotmd/mcp_server.py`); supports stdio and streamable-http transports
- Starlette — used directly in `mcp_server.py` for middleware/routing alongside FastMCP
- Click `>=8.0` — CLI entrypoint (`backend/src/dotmd/cli.py`)
- Pydantic v2 `>=2.0` — all models (`backend/src/dotmd/core/models.py`)
- pydantic-settings `>=2.0` (with toml extras) — settings with env/TOML/init priority chain (`backend/src/dotmd/core/config.py`)

**ML / NLP:**
- `sentence-transformers >=3.0` — local embedding and CrossEncoder reranking (lazy-loaded)
- `transformers >=5.11.0,<6` — backbone for sentence-transformers and GLiNER
- `torch <2.13` — CPU-only runtime dependency
- `einops >=0.8` — tensor ops for transformer models
- `gliner >=0.2` — zero-shot NER via `urchade/gliner_multi-v2.1` (`backend/src/dotmd/extraction/ner.py`)

**Storage:**
- `sqlite-vec >=0.1.6` — SQLite extension for vector similarity search (`backend/src/dotmd/storage/sqlite_vec.py`); no AVX2 requirement
- `FalkorDB >=1.6.0` — Redis-protocol graph database client (`backend/src/dotmd/storage/falkordb_graph.py`)

**Utilities:**
- `blake3 >=1.0` — content hashing for chunk fingerprints (`backend/src/dotmd/ingestion/`)
- `watchdog >=6.0` — filesystem event watcher for trickle indexer (`backend/src/dotmd/ingestion/trickle.py`)
- `pyyaml >=6.0` — YAML frontmatter parsing
- `httpx >=0.27` — async HTTP client for TEI embedding API calls

**Build/Dev:**
- `hatchling` — build backend (`[build-system]` in `backend/pyproject.toml`)
- `ruff >=0.6` — linter + formatter (line-length 100, target py312)
- `pyright >=1.1.380` — type checker (standard mode)
- `pytest >=8.0` — test runner
- `pytest-asyncio >=0.24` — async test support (asyncio_mode = "auto")
- `modal >=0.73` — GPU cloud functions in `modal/` workspace (separate package `dotmd-modal`)

## Key Dependencies

**Critical:**
- `sqlite-vec` — vector storage; no AVX2 needed; embedded in unified `index.db`
- `FalkorDB` — graph backend (Redis protocol, external container)
- `mcp[cli]` — MCP protocol implementation; both stdio and HTTP transports exposed
- `sentence-transformers` + `torch` — local fallback for embeddings (TEI preferred in prod)
- `gliner` — zero-shot NER, loaded lazily on first extraction call

**Infrastructure:**
- `pydantic-settings[toml]` — settings loaded from env vars (`DOTMD_*` prefix), TOML file, or programmatic init
- `blake3` — content fingerprinting enabling embedding reuse via `text_hash` column
- `watchdog` — drives trickle background indexer (poll interval default 3600s)
- `httpx` — TEI HTTP client with auto-tuning batch size (down on 413 errors)

**Optional / Conditional:**
- `modal` — GPU embedding offload (`modal/embed.py`); separate workspace, not part of main package

## Configuration

**Environment:**
- All settings via `DOTMD_*` env vars (prefix defined in `backend/src/dotmd/core/config.py`)
- TOML file fallback: `~/.dotmd/config.toml`
- Priority: programmatic init > env vars > TOML > defaults
- Required at runtime: `DOTMD_EMBEDDING_URL`, `DOTMD_INDEXING_PATHS` (absolute), `data_dir=/mnt`, `index_dir=/dotmd-index`
- Optional OAuth: `DOTMD_BASE_URL` (HTTPS), `DOTMD_OAUTH_ALLOWED_REDIRECT_URI_PREFIXES`
- Telegram source: `DOTMD_TELEGRAM_DAEMON_SOCKET` (UNIX socket path)
- Federated search: `DOTMD_FEDERATED_TIMEOUT_SECONDS` (default 4.0)

**Key config fields** (`backend/src/dotmd/core/config.py`):
- `embedding_model` — HuggingFace model ID (TEI ignores this; TEI determines actual model)
- `embedding_url` — required; TEI server base URL
- `embedding_weights` — dual-encoder fusion weights, format `"text=0.7,meta=0.3"` (must sum to 1.0)
- `chunk_strategy` — default `"heading_512_50"`
- `reranker_model` — default `"cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"`
- `ner_model_name` — default `"urchade/gliner_multi-v2.1"`
- `falkordb_url` — required FalkorDB Redis URL

**Build:**
- `backend/pyproject.toml` — hatchling build, ruff config, pyright config, pytest config
- `docker-compose.yml` — three services: `dotmd`, `tei` (bundled profile), `falkordb` (bundled profile)

## Platform Requirements

**Development:**
- Python 3.12+
- SQLite with sqlite-vec extension loadable
- TEI server required (no embedded fallback in production config)
- FalkorDB for graph; unit tests use an in-memory test double instead of a dev graph backend

**Production:**
- Docker container `dotmd` (bind-mount source for hot-reload without rebuild)
- External TEI container: `ghcr.io/huggingface/text-embeddings-inference:cpu-1.9` on port 8088
- External FalkorDB container: `falkordb/falkordb:latest` (Redis protocol)
- Docker volume `dotmd_dotmd-index` → `/dotmd-index/` (unified `index.db` + `feedback.db`)
- Docker volume `dotmd_dotmd-hf-models` → `/root/.cache/huggingface` (shared HF model cache)
- MCP HTTP entrypoint: `dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`
- Health endpoint: `GET /health` on port 8080
- Source code bind-mounted — restart (not rebuild) for code changes; rebuild only for `pyproject.toml`/`start.sh` changes

---

*Stack analysis: 2026-05-10*
