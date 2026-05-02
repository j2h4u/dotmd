# Phase 7: Production Packaging - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Service deploys as a self-contained stack with zero manual steps beyond `docker compose up`. Compose in repo is the single source of truth — portable, no secrets, fully parameterized. Production `/opt/docker/dotmd/` uses `include:` to reference repo compose plus server-specific `.env`. Healthchecks gate API startup. SQLite databases operate in WAL mode.

</domain>

<decisions>
## Implementation Decisions

### Compose Architecture
- **D-01:** Single `docker-compose.yml` in repo root — fully parameterized with `${VARIABLE}` syntax, no hardcoded secrets or server-specific paths. Safe for public GitHub.
- **D-02:** TEI and FalkorDB as optional `profiles`. Default mode: external services via `${DOTMD_EMBEDDING_URL}` and `${DOTMD_FALKORDB_URL}`. With `--profile bundled`: TEI and FalkorDB services start inside the same compose stack (for new server "out of the box" setup).
- **D-03:** `.env.example` in repo root with all variables documented and sensible defaults. `.env` in `.gitignore`.

### Production Deployment
- **D-04:** Production lives in `/opt/docker/dotmd/` per server convention. `docker-compose.yml` there uses `include:` directive to reference the repo compose (`/home/j2h4u/repos/j2h4u/dotmd/docker-compose.yml`). No drift — repo compose is the only source of truth for service definitions.
- **D-05:** `/opt/docker/dotmd/.env` contains production-specific values (data paths, TEI URL, FalkorDB URL, embedding dim). Secrets (`env_file: ~/.secrets/huggingface.env`) added in the production compose overlay, not in the repo compose.
- **D-06:** Update workflow: `cd ~/repos/j2h4u/dotmd && git pull` then `cd /opt/docker/dotmd && docker compose up -d --build`. No automation needed yet — manual two-step.

### Health & Startup
- **D-07:** Add `/health` endpoint to FastAPI server — returns HTTP 200 with `{"status": "ok"}` if FastAPI is alive. Does NOT ping TEI or FalkorDB on every request.
- **D-08:** Add `HEALTHCHECK` to Dockerfile using `curl localhost:8000/health`.
- **D-09:** `depends_on` with `condition: service_healthy` gates API startup on TEI and FalkorDB health (only in `--profile bundled` mode where those services exist in the compose). In external mode, healthcheck responsibility is on the external stacks.

### Env Configuration
- **D-10:** `.env.example` documents every `DOTMD_*` variable from `core/config.py` with current defaults. Groups: Paths, Embedding, Vector Store, Graph, Search, Extraction.
- **D-11:** Repo compose uses `env_file: .env` (file is gitignored). No `environment:` block with hardcoded values — everything comes from `.env`.
- **D-12:** Secrets stay in `~/.secrets/` — referenced only from production `/opt/docker/dotmd/docker-compose.yml`, never from repo compose.

### SQLite WAL Mode
- **D-13:** `metadata.db` already has WAL mode (`storage/metadata.py:94`). Add `PRAGMA journal_mode=WAL` to `storage/sqlite_vec.py` for `vec.db`. One-line change.

### Claude's Discretion
- Exact health endpoint response format (beyond `{"status": "ok"}`)
- TEI and FalkorDB service definitions in bundled profile (image versions, resource limits)
- Order of compose services and env var grouping in `.env.example`
- Whether to add a `mcp` service to the new compose (existed in old repo compose)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Current Docker Setup
- `/opt/docker/dotmd/docker-compose.yml` — Current production compose; external networks pattern, env vars, volume mounts
- `docker-compose.yml` (repo root) — Current repo compose (basic skeleton, to be replaced)
- `backend/Dockerfile` — Multi-stage build, no HEALTHCHECK yet

### Application Code
- `backend/src/dotmd/core/config.py` — All `DOTMD_*` settings with defaults; `embedding_url` is required (no default)
- `backend/src/dotmd/api/server.py` — FastAPI app, lifespan, no health endpoint yet
- `backend/src/dotmd/storage/metadata.py:94` — WAL mode already enabled for metadata.db
- `backend/src/dotmd/storage/sqlite_vec.py:48` — `sqlite3.connect()` without WAL mode (needs fix)

### Requirements
- `.planning/REQUIREMENTS.md` — PACK-01 through PACK-04

### Server Conventions
- `~/AGENTS.md` — Docker management conventions, `/opt/docker/` deployment pattern, `~/.secrets/` for env files

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **External network pattern**: Production compose already declares `embeddings_default` and `graphiti_default` as external — pattern for bundled profile to override
- **Pydantic Settings**: `core/config.py` already reads all `DOTMD_*` env vars — compose just needs to pass them through
- **FastAPI lifespan**: `server.py` has `_lifespan()` with warmup — health endpoint hooks into same app

### Established Patterns
- **Environment-driven config**: All settings via `DOTMD_` prefix env vars
- **Named volumes**: `dotmd-index` and `dotmd-hf-models` for persistent data
- **Multi-stage Dockerfile**: builder + runtime layers with cache-friendly ordering

### Integration Points
- `docker-compose.yml` (repo) — complete rewrite to parameterized version
- `/opt/docker/dotmd/docker-compose.yml` — rewrite to `include:` + production overlay
- `backend/src/dotmd/api/server.py` — add `/health` route
- `backend/src/dotmd/storage/sqlite_vec.py` — add WAL pragma
- `backend/Dockerfile` — add HEALTHCHECK instruction

</code_context>

<specifics>
## Specific Ideas

- Production `/opt/docker/dotmd/` must follow server convention — all Docker services live there
- Repo compose must be clean enough for public GitHub — no server-specific paths or secrets
- `--profile bundled` is the "clone and run" experience for a new server
- Default (no profile) assumes external TEI and FalkorDB — the senbonzakura setup

</specifics>

<deferred>
## Deferred Ideas

- **Automated deployment** — git hook or systemd path unit that auto-rebuilds on `git pull`. Not needed now; manual two-step is fine.
- **CI/CD** — GitHub Actions for build/test. Overkill for single server.
- **MCP service in compose** — old repo compose had it; decide during planning whether to include

### Reviewed Todos (not folded)
- **Migrate graph store from LadybugDB to FalkorDB** — completed in v1.2 (Phases 4-6)
- **Background trickle indexer** — Phase 10 scope
- **Smoke tests for search pipeline** — Phase 8 scope
- **Scout other dotmd forks for ideas** — general backlog, not phase-specific

</deferred>

---

*Phase: 07-production-packaging*
*Context gathered: 2026-03-27*
