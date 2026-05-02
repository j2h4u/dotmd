# Phase 7: Production Packaging - Research

**Researched:** 2026-03-27
**Domain:** Docker Compose packaging, healthchecks, SQLite WAL, env parameterization
**Confidence:** HIGH

## Summary

Phase 7 packages dotMD as a fully parameterized Docker Compose stack. The existing codebase already has most building blocks: Pydantic Settings reads `DOTMD_*` env vars, metadata.db already uses WAL mode, and a multi-stage Dockerfile exists. The work is primarily compose authoring, one health endpoint, one WAL pragma, and an `.env.example`.

Docker Compose v5.1.0 on this server supports all needed features: `include:` directive (v2.20+), `profiles` (v2.1+), `depends_on: condition: service_healthy` (v2.1+). The `include:` directive's `env_file` attribute handles variable interpolation -- the repo compose uses `${VAR}` placeholders, and the production include provides values through its `env_file` parameter.

**Primary recommendation:** Build a single parameterized `docker-compose.yml` in repo root with `profiles: [bundled]` for TEI/FalkorDB. Production at `/opt/docker/dotmd/` uses `include:` to reference repo compose plus a production `.env` and override for secrets/networks.

<user_constraints>

## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Single `docker-compose.yml` in repo root -- fully parameterized with `${VARIABLE}` syntax, no hardcoded secrets or server-specific paths. Safe for public GitHub.
- **D-02:** TEI and FalkorDB as optional `profiles`. Default mode: external services via `${DOTMD_EMBEDDING_URL}` and `${DOTMD_FALKORDB_URL}`. With `--profile bundled`: TEI and FalkorDB services start inside the same compose stack.
- **D-03:** `.env.example` in repo root with all variables documented and sensible defaults. `.env` in `.gitignore`.
- **D-04:** Production lives in `/opt/docker/dotmd/` per server convention. `docker-compose.yml` there uses `include:` directive to reference the repo compose. No drift -- repo compose is the only source of truth.
- **D-05:** `/opt/docker/dotmd/.env` contains production-specific values. Secrets (`env_file: ~/.secrets/huggingface.env`) added in the production compose overlay, not in the repo compose.
- **D-06:** Update workflow: `cd ~/repos/j2h4u/dotmd && git pull` then `cd /opt/docker/dotmd && docker compose up -d --build`. Manual two-step.
- **D-07:** Add `/health` endpoint to FastAPI -- returns HTTP 200 with `{"status": "ok"}`. Does NOT ping TEI or FalkorDB on every request.
- **D-08:** Add `HEALTHCHECK` to Dockerfile using `curl localhost:8000/health`.
- **D-09:** `depends_on` with `condition: service_healthy` gates API startup on TEI and FalkorDB health (only in `--profile bundled` mode).
- **D-10:** `.env.example` documents every `DOTMD_*` variable from `core/config.py` with current defaults. Groups: Paths, Embedding, Vector Store, Graph, Search, Extraction.
- **D-11:** Repo compose uses `env_file: .env` (file is gitignored). No `environment:` block with hardcoded values.
- **D-12:** Secrets stay in `~/.secrets/` -- referenced only from production compose, never from repo compose.
- **D-13:** `metadata.db` already has WAL mode. Add `PRAGMA journal_mode=WAL` to `storage/sqlite_vec.py` for `vec.db`. One-line change.

### Claude's Discretion
- Exact health endpoint response format (beyond `{"status": "ok"}`)
- TEI and FalkorDB service definitions in bundled profile (image versions, resource limits)
- Order of compose services and env var grouping in `.env.example`
- Whether to add a `mcp` service to the new compose (existed in old repo compose)

### Deferred Ideas (OUT OF SCOPE)
- Automated deployment (git hook or systemd path unit)
- CI/CD (GitHub Actions)
- MCP service in compose (decide during planning, not a requirement)
- Background trickle indexer (Phase 10)
- Smoke tests (Phase 8)

</user_constraints>

<phase_requirements>

## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PACK-01 | Service deploys via single `docker compose up` with all dependencies declared | Compose `profiles` for bundled mode; `include:` for production overlay; full parameterization with `${VAR}` syntax |
| PACK-02 | Healthchecks on TEI (`/health`) and FalkorDB (`redis-cli ping`) with `depends_on: condition: service_healthy` | TEI responds 200 on `/health`; FalkorDB has `redis-cli` at `/usr/local/bin/redis-cli`; `service_healthy` condition supported by compose v5.1 |
| PACK-03 | All configuration via environment variables with documented defaults in example `.env` | `core/config.py` already reads all `DOTMD_*` vars via pydantic-settings; 25 settings identified for `.env.example` |
| PACK-04 | SQLite WAL mode enabled on all databases | `metadata.py:94` already has WAL; `sqlite_vec.py:48` needs one `PRAGMA journal_mode=WAL` line after `connect()` |

</phase_requirements>

## Architecture Patterns

### Compose Architecture (Two-Layer)

**Layer 1: Repo compose** (`docker-compose.yml` in repo root)
- Fully parameterized with `${DOTMD_*}` variables
- Uses `env_file: .env` for variable interpolation (`.env` is gitignored)
- Defines `api` service with build context, volumes, ports
- Defines `tei` and `falkordb` services under `profiles: [bundled]`
- No hardcoded paths, secrets, or server-specific values

**Layer 2: Production compose** (`/opt/docker/dotmd/docker-compose.yml`)
- Uses `include:` to reference repo compose with `env_file` for interpolation
- Adds production-specific overrides: external networks, secrets, volume mounts
- Pattern:

```yaml
include:
  - path:
      - /home/j2h4u/repos/j2h4u/dotmd/docker-compose.yml
      - docker-compose.override.yml   # adds networks, secrets env_file
    env_file: .env                     # provides values for ${VAR} interpolation
```

**Key insight on `include:` env_file:** The `env_file` in the `include` block provides values for `${VAR}` interpolation during compose file parsing -- it is NOT the same as service-level `env_file` which injects env vars into containers at runtime. The production `.env` at `/opt/docker/dotmd/.env` feeds both: interpolation via `include:` env_file, and runtime injection via service-level `env_file:`.

### Recommended File Layout

```
dotmd/                              # repo root
  docker-compose.yml                # parameterized, profiles, public-safe
  .env.example                      # documented defaults
  .env                              # actual values (gitignored)
  backend/
    Dockerfile                      # + HEALTHCHECK instruction
    src/dotmd/
      api/server.py                 # + /health endpoint
      storage/sqlite_vec.py         # + WAL pragma

/opt/docker/dotmd/                  # production (on server)
  docker-compose.yml                # include: + override
  docker-compose.override.yml       # networks, secrets, extra volumes
  .env                              # production values
```

### Health Endpoint Pattern

```python
@app.get("/health")
async def health() -> dict:
    """Liveness probe -- confirms FastAPI is up and responding."""
    return {"status": "ok"}
```

This is a **liveness** check only (D-07 explicitly says "does NOT ping TEI or FalkorDB"). The dependency health gating is done at compose level via `depends_on: condition: service_healthy`, not at application level.

### Dockerfile HEALTHCHECK Pattern

D-08 specifies `curl localhost:8000/health`. Since `python:3.12-slim` does not include curl, two options:

**Option A: Install curl in Dockerfile (recommended -- matches D-08)**
```dockerfile
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1
```

**Option B: Use Python urllib (no extra packages)**
```dockerfile
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')" || exit 1
```

Recommend Option A: curl is conventional for Docker healthchecks, easier to read, and adds only ~3MB. The `start-period=60s` accounts for model loading during warmup.

### Bundled Profile Services

For the `--profile bundled` mode, use the same images running in production:

```yaml
services:
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    profiles: [bundled]
    command: --model-id ${DOTMD_EMBEDDING_MODEL:-BAAI/bge-small-en-v1.5}
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 10s
      timeout: 5s
      start_period: 120s
      retries: 10
    deploy:
      resources:
        limits:
          memory: 4G

  falkordb:
    image: falkordb/falkordb:latest
    profiles: [bundled]
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      start_period: 30s
      retries: 5
    volumes:
      - falkordb-data:/var/lib/falkordb/data
```

**Verified:** `redis-cli` exists at `/usr/local/bin/redis-cli` inside `falkordb/falkordb:latest`. TEI has curl and responds HTTP 200 on `/health` (empty body). TEI `start_period` needs to be generous (120s) because model download + loading can take minutes on first run.

### depends_on Gating

In bundled profile, API waits for dependencies:
```yaml
  api:
    depends_on:
      tei:
        condition: service_healthy
      falkordb:
        condition: service_healthy
```

In default (external) mode, these services don't exist in the compose, so no `depends_on` applies. The external stacks handle their own health. This is the correct behavior per D-09.

**Important:** `depends_on` with `condition: service_healthy` only works when the depended service is in the same compose project. Services with `profiles: [bundled]` are only started when `--profile bundled` is active, so the `depends_on` references to `tei` and `falkordb` must also be conditional. Compose handles this correctly: if a dependency is not started (not in active profile), `depends_on` is ignored for that dependency.

### SQLite WAL Mode

**What needs to change:** One line in `sqlite_vec.py` after `sqlite3.connect()`:

```python
self._conn = sqlite3.connect(str(self._db_path))
self._conn.execute("PRAGMA journal_mode=WAL")  # <-- add this
```

This matches the pattern already used in `metadata.py:94`.

**Why WAL matters:** Default SQLite journal mode (`DELETE`) locks the entire database during writes, causing "database is locked" errors on concurrent reads. WAL (Write-Ahead Logging) allows concurrent readers during writes. This is critical for the future background indexer (Phase 10) which writes while the API reads.

**WAL is persistent per-database:** Once set, the journal mode persists across connections. The PRAGMA is idempotent -- running it on a database already in WAL mode is a no-op.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Config management | Custom config parser | pydantic-settings `BaseSettings` | Already used in `core/config.py`; handles env vars, defaults, validation |
| Healthcheck logic | Complex readiness probes | Simple HTTP 200 liveness + compose `depends_on` | D-07 explicitly rules out dependency pinging on health endpoint |
| Compose profiles | Separate compose files per environment | `profiles:` attribute on services | Built into compose spec, cleanest way to make services optional |
| Compose layering | Shell scripts to merge configs | `include:` directive with override files | Native compose feature, supported in v5.1 |

## Common Pitfalls

### Pitfall 1: include env_file vs service env_file confusion
**What goes wrong:** Putting runtime container env vars in the `include:` level `env_file` expecting them to be injected into containers, or vice versa.
**Why it happens:** Two different `env_file` mechanisms with the same name serve different purposes.
**How to avoid:** `include:` level `env_file` = compose file interpolation (resolves `${VAR}` in YAML). Service-level `env_file:` = runtime injection into container.
**Warning signs:** Variables visible in `docker compose config` output but not inside running container, or vice versa.

### Pitfall 2: depends_on with profiled services
**What goes wrong:** API service has `depends_on: tei` but tei is only in `profiles: [bundled]`. Running without profile fails because dependency is missing.
**Why it happens:** Compose v2 resolves `depends_on` targets at parse time.
**How to avoid:** Compose v2 handles this correctly -- if a profiled service is not activated, its `depends_on` reference is silently ignored. Verify with `docker compose config` (no profile) and `docker compose --profile bundled config`.
**Warning signs:** Error messages about undefined services when running without `--profile bundled`.

### Pitfall 3: HEALTHCHECK start_period too short
**What goes wrong:** Container marked unhealthy during initial model loading, causing dependent services to not start or causing restarts.
**Why it happens:** dotMD warmup loads sentence-transformers, GLiNER, cross-encoder models (~30-60s). TEI downloads and loads embedding model (~60-180s on first run).
**How to avoid:** Set generous `start_period` values: 60s for dotMD API, 120s for TEI, 30s for FalkorDB.
**Warning signs:** Container stuck in "starting" state, then transitioning to "unhealthy" before app is ready.

### Pitfall 4: Missing embedding_url in default mode
**What goes wrong:** `DOTMD_EMBEDDING_URL` has no default in `core/config.py` (it's required). Running `docker compose up` without `.env` fails immediately.
**Why it happens:** Field is `embedding_url: str` with no default value -- pydantic raises `ValidationError` at startup.
**How to avoid:** `.env.example` must document this as REQUIRED (no default). The repo compose must have `env_file: .env` so users must create `.env` from `.env.example`.
**Warning signs:** `pydantic_core._pydantic_core.ValidationError: 1 validation error for Settings` at startup.

### Pitfall 5: Production override not adding external networks
**What goes wrong:** dotMD container can't reach external TEI or FalkorDB because it's not on the right Docker networks.
**Why it happens:** Repo compose doesn't declare external networks (they're server-specific). Production override must add them.
**How to avoid:** Production `docker-compose.override.yml` adds `networks:` section with external network references (`embeddings_default`, `graphiti_default`).
**Warning signs:** Connection refused errors when API tries to reach TEI or FalkorDB URLs.

## Code Examples

### Complete .env.example structure

Based on `core/config.py` analysis, all 25+ settings grouped:

```bash
# =============================================================================
# dotMD Configuration
# =============================================================================
# Copy to .env and adjust values. Variables without defaults are REQUIRED.

# -- Paths -------------------------------------------------------------------
DOTMD_DATA_DIR=/data
DOTMD_INDEX_DIR=/dotmd-index

# -- Embedding ---------------------------------------------------------------
# REQUIRED: URL to TEI-compatible embedding server
DOTMD_EMBEDDING_URL=http://tei:80
DOTMD_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5
DOTMD_EMBEDDING_DIM=384
DOTMD_TEI_BATCH_SIZE=4

# -- Vector Store ------------------------------------------------------------
DOTMD_VECTOR_BACKEND=sqlite-vec

# -- Graph -------------------------------------------------------------------
DOTMD_GRAPH_BACKEND=ladybugdb
DOTMD_FALKORDB_URL=redis://falkordb:6379
DOTMD_FALKORDB_GRAPH_NAME=dotmd
DOTMD_GRAPH_MAX_HOPS=2

# -- Extraction --------------------------------------------------------------
DOTMD_EXTRACT_DEPTH=ner
# DOTMD_NER_ENTITY_TYPES=person,organization,technology,concept,location,object,activity,date_time

# -- Search ------------------------------------------------------------------
DOTMD_DEFAULT_TOP_K=10
DOTMD_FUSION_K=60
DOTMD_GRAPH_RRF_WEIGHT=1.5
DOTMD_RERANK_POOL_SIZE=20
DOTMD_SEMANTIC_SCORE_FLOOR=0.4
DOTMD_SNIPPET_LENGTH=300

# -- Reranker ----------------------------------------------------------------
DOTMD_RERANKER_MODEL=cross-encoder/ms-marco-MiniLM-L-6-v2
DOTMD_RERANKER_LENGTH_PENALTY=true
DOTMD_RERANKER_MIN_LENGTH=50

# -- Chunking ----------------------------------------------------------------
DOTMD_MAX_CHUNK_TOKENS=512
DOTMD_CHUNK_OVERLAP_TOKENS=50
```

### Production compose pattern

```yaml
# /opt/docker/dotmd/docker-compose.yml
include:
  - path:
      - /home/j2h4u/repos/j2h4u/dotmd/docker-compose.yml
      - docker-compose.override.yml
    env_file: .env
```

```yaml
# /opt/docker/dotmd/docker-compose.override.yml
services:
  api:
    volumes:
      - /srv/knowledgebase/voicenotes:/mnt/voicenotes:ro
      - /home/j2h4u:/mnt/home:ro
    env_file:
      - /home/j2h4u/.secrets/huggingface.env
    networks:
      - default
      - embeddings
      - graphiti

networks:
  embeddings:
    external: true
    name: embeddings_default
  graphiti:
    external: true
    name: graphiti_default
```

### SQLite WAL mode addition

```python
# storage/sqlite_vec.py, in _get_conn() method, after connect():
self._conn = sqlite3.connect(str(self._db_path))
self._conn.execute("PRAGMA journal_mode=WAL")  # concurrent read/write safety
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `docker-compose` (v1 CLI) | `docker compose` (v2 plugin) | 2023 | Already using v2 on server |
| Separate compose files per env | `include:` + `profiles` | Compose v2.20 (2023) | Single source of truth, no drift |
| `links:` for inter-service networking | `depends_on:` + shared network | Compose v2 | Cleaner dependency declaration |
| `condition: service_healthy` requires long_syntax | Short syntax supported | Compose v2.1 | Simpler healthcheck gating |

## Open Questions

1. **MCP service in repo compose**
   - What we know: Old repo compose had an `mcp` service. Current CONTEXT.md defers this decision.
   - What's unclear: Whether MCP service should be included in the new parameterized compose.
   - Recommendation: Include it -- it already existed, uses the same build context and volumes. Add `profiles: [mcp]` so it's opt-in. Low cost, high convenience.

2. **TEI model mismatch between bundled and production**
   - What we know: Production uses `intfloat/multilingual-e5-large` (1024-dim). Default in config.py is `BAAI/bge-small-en-v1.5` (384-dim).
   - What's unclear: Whether bundled profile should default to the small or large model.
   - Recommendation: Bundled profile uses `${DOTMD_EMBEDDING_MODEL}` from `.env`, defaulting to the small model for "clone and run" experience. Production `.env` overrides to the large model. Dimension is configured via `DOTMD_EMBEDDING_DIM`.

3. **Port mapping in repo compose**
   - What we know: Current repo compose maps `8000:8000`. Production maps `127.0.0.1:8321:8000`.
   - What's unclear: What the repo compose default port mapping should be.
   - Recommendation: Repo compose uses `${DOTMD_PORT:-8000}:8000`. Production `.env` sets `DOTMD_PORT=127.0.0.1:8321`. This keeps the port configurable without hardcoding server-specific bindings.

## Project Constraints (from CLAUDE.md)

- All public APIs go through `api/service.py` -- never expose internals directly
- Never reload indexes per-request
- Protocol-based abstractions for storage, extractors, and search engines
- Docker convention: `docker compose` (v2), NOT `docker-compose`
- Server convention: Docker services in `/opt/docker/`, secrets in `~/.secrets/`
- Container naming: `<project>-<service>-1`

## Sources

### Primary (HIGH confidence)
- Docker Compose v5.1.0 installed on server -- features verified locally
- `core/config.py` -- all settings enumerated directly from source
- `metadata.py:94` -- WAL mode pattern verified in existing code
- `sqlite_vec.py:48` -- confirmed missing WAL pragma
- `server.py` -- confirmed no `/health` endpoint exists
- `Dockerfile` -- confirmed no HEALTHCHECK instruction
- FalkorDB container -- `redis-cli` at `/usr/local/bin/redis-cli`, `ping` returns `PONG`
- TEI container -- `/health` endpoint returns HTTP 200, `curl` available at `/usr/bin/curl`
- `python:3.12-slim` -- confirmed curl NOT included, but `urllib` available

### Secondary (MEDIUM confidence)
- [Docker Compose include reference](https://docs.docker.com/reference/compose-file/include/) -- `env_file` attribute for interpolation
- [Docker Compose services reference](https://docs.docker.com/reference/compose-file/services/) -- `depends_on`, `profiles`, `healthcheck` syntax
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) -- `service_healthy` condition behavior

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all components already exist, just wiring them together
- Architecture: HIGH -- compose `include:` and `profiles` verified on installed version, patterns confirmed with official docs
- Pitfalls: HIGH -- verified through direct container inspection and image testing
- WAL mode: HIGH -- one-line change matching existing pattern in codebase

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain, no fast-moving dependencies)
