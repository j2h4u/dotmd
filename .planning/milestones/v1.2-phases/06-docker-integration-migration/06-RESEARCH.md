# Phase 6: Docker Integration + Migration - Research

**Researched:** 2026-03-27
**Domain:** Docker networking, compose configuration, FalkorDB connectivity
**Confidence:** HIGH

## Summary

Phase 6 is a pure infrastructure/config phase requiring zero Python code changes. The FalkorDB adapter (Phase 4) and BM25 fix (Phase 5) are complete. What remains is: (1) add the `graphiti_default` external network to the dotmd compose file, (2) add three FalkorDB environment variables, (3) rebuild the Docker image (required -- the running container does not have the `falkordb` Python package installed), and (4) run a full re-index via `docker compose run`.

A critical discovery: the current running container was built on 2026-03-23, before Phase 4 added the `falkordb` dependency to `pyproject.toml`. The container currently crashes on `dotmd status` with the exact LadybugDB file lock error that motivated this migration. A `docker compose build` is mandatory before any FalkorDB operations.

**Primary recommendation:** Edit `/opt/docker/dotmd/docker-compose.yml` to add the `graphiti_default` network and FalkorDB env vars, rebuild the image, then run the overnight re-index.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Add `graphiti_default` as an external network in the production docker-compose.yml (`/opt/docker/dotmd/docker-compose.yml`), following the exact same pattern already used for `embeddings_default`. This is declarative, survives `docker compose down/up` cycles, and doesn't require manual `docker network connect`.
- **D-02:** The FalkorDB service hostname from dotmd's perspective is `falkordb` (the service name in Graphiti's compose file, resolvable on the shared `graphiti_default` network).
- **D-03:** Add FalkorDB env vars directly to the production compose `environment:` block -- no separate env file. Three vars needed:
  - `DOTMD_GRAPH_BACKEND=falkordb`
  - `DOTMD_FALKORDB_URL=redis://falkordb:6379`
  - `DOTMD_FALKORDB_GRAPH_NAME=dotmd` (explicit, even though it's the default -- clarity for production)
- **D-04:** Keep `DOTMD_EMBEDDING_URL`, `DOTMD_EXTRACT_DEPTH=ner`, and all other existing env vars unchanged.
- **D-05:** Full re-index via one-off `docker compose run` command: `docker compose run --rm api index --force /mnt`. This reuses the same image/volumes/networks as the `api` service -- no separate service definition needed.
- **D-06:** Re-index is an overnight operation (~59 min based on current baseline). Run manually, not automated. The `api` service should be stopped during re-index to avoid concurrent access to the same index files (BM25, sqlite-vec are file-based).
- **D-07:** After re-index completes, start the `api` service normally. It loads the FalkorDB graph on startup via lazy connection.
- **D-08:** Validate with three checks from inside the container:
  1. `dotmd status` -- should report `graph_backend: falkordb`, connection status, entity/edge counts
  2. `dotmd search --mode hybrid "test query"` -- should include results with `graph` in `matched_engines`
  3. `dotmd serve` + `curl /search` -- API returns graph-enriched results, concurrent access works

### Claude's Discretion
- Exact ordering of compose file changes (networks section, environment block)
- Whether to add a health check for FalkorDB connectivity
- Log messages for FalkorDB connection during startup

### Deferred Ideas (OUT OF SCOPE)
- **GRAPH-F1: LadybugDB adapter removal** -- only after FalkorDB proven stable in production
- **GRAPH-F2: pandas to optional dependency** -- only needed by LadybugDB, remove when LadybugDB removed
- **Automated re-index scheduling** -- not needed for now; manual overnight run is sufficient for ~227 files
- **Scout other dotmd forks for ideas** -- general exploration, not specific to Docker integration
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| GRAPH-04 | Docker networking connects dotmd container to `graphiti_default` network for FalkorDB access | Verified: `graphiti_default` network exists, FalkorDB DNS name is `falkordb`, pattern identical to existing `embeddings_default` |
| GRAPH-05 | Full re-index with `--force` populates FalkorDB graph (~59 min, overnight run) | Verified: `docker compose run --rm api index --force /mnt` reuses service networks/volumes; image rebuild needed first |
</phase_requirements>

## Project Constraints (from CLAUDE.md)

- All public APIs go through `api/service.py` -- never expose internals directly
- Never reload indexes per-request (BM25, vector, graph loaded once at startup)
- Protocol-based abstractions: FalkorDB adapter already implements `GraphStoreProtocol`
- Environment-driven config via `DOTMD_` prefix env vars
- Docker compose v2 (`docker compose`, NOT `docker-compose`)

## Standard Stack

No new libraries or tools needed. This phase uses only existing infrastructure:

| Component | Version | Purpose | Status |
|-----------|---------|---------|--------|
| Docker Compose | v5.1.0 | Container orchestration | Installed, verified |
| FalkorDB (server) | latest | Graph database server | Running (`graphiti-falkordb-1`, up 13 days) |
| falkordb (Python) | >=1.6.0 | Python client | In `pyproject.toml`, NOT in current image |
| graphiti_default | bridge | Docker network | Exists, FalkorDB is the only container on it |

## Architecture Patterns

### Existing External Network Pattern (to replicate)

The dotmd compose file already connects to one external network (`embeddings_default`). The `graphiti_default` network follows the identical pattern:

```yaml
# Current state (production compose)
networks:
  embeddings:
    external: true
    name: embeddings_default

# Target state (add graphiti alongside)
networks:
  embeddings:
    external: true
    name: embeddings_default
  graphiti:
    external: true
    name: graphiti_default
```

The `api` service must list all three networks:

```yaml
services:
  api:
    networks:
      - default
      - embeddings
      - graphiti
```

### DNS Resolution on Shared Network

FalkorDB's DNS names on `graphiti_default` (verified via `docker inspect`):
- `falkordb` (service alias -- this is what the URL should use)
- `graphiti-falkordb-1` (container name)
- `dc3fbe06f2e4` (container ID)

The `DOTMD_FALKORDB_URL=redis://falkordb:6379` resolves correctly because both containers will be on the `graphiti_default` network.

### Re-index via `docker compose run`

`docker compose run` creates a one-off container from the `api` service definition. It inherits:
- All networks (default + embeddings + graphiti)
- All volumes (dotmd-index, dotmd-hf-models, bind mounts)
- All environment variables
- The image built from `backend/Dockerfile`

It does NOT inherit:
- Port mappings (use `--service-ports` if needed, but not needed for indexing)
- The `command:` directive -- the command is passed as arguments

Correct invocation: `docker compose run --rm api index --force /mnt`

This works because the Dockerfile sets `ENTRYPOINT ["dotmd"]`, so the arguments `index --force /mnt` are appended to produce `dotmd index --force /mnt`.

### Anti-Patterns to Avoid
- **Manual `docker network connect`:** Fragile, doesn't survive `docker compose down/up`. Use declarative external network in compose file.
- **Separate service definition for indexing:** Unnecessary duplication. `docker compose run` reuses the `api` service's full configuration.
- **Running `api` service during re-index:** BM25 and sqlite-vec are file-based -- concurrent writes from re-index + reads from serve could corrupt data or produce stale results.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Cross-project Docker networking | Manual `docker network connect` scripts | Compose external network declaration | Declarative, survives lifecycle |
| FalkorDB health check | Custom retry loop in Python | Docker Compose `depends_on` with condition (or just catch ConnectionError) | Already handled by FalkorDBGraphStore constructor |
| Concurrent index + serve protection | File locks or coordination daemon | Operator discipline (stop api, run index, start api) | Simple, sufficient for ~59 min manual overnight run |

## Common Pitfalls

### Pitfall 1: Stale Docker Image
**What goes wrong:** The `falkordb` Python package is in `pyproject.toml` but the running container was built before Phase 4 (2026-03-23). Any FalkorDB operation will fail with `ModuleNotFoundError: No module named 'falkordb'`.
**Why it happens:** Docker caches layers. Adding a dependency to `pyproject.toml` doesn't update existing images.
**How to avoid:** `docker compose build` is mandatory before any other step. The compose file uses `build: context: /home/j2h4u/repos/j2h4u/dotmd/backend`, so it will pick up the current `pyproject.toml`.
**Warning signs:** `ModuleNotFoundError` for `falkordb` when running any dotmd command with `graph_backend=falkordb`.

### Pitfall 2: FalkorDB Network Unreachable
**What goes wrong:** dotmd container can't resolve `falkordb` hostname -- connection refused or DNS resolution failure.
**Why it happens:** The `graphiti` network wasn't added to the compose file, or the network name is misspelled, or FalkorDB container isn't running.
**How to avoid:** Verify with `docker network inspect graphiti_default` that FalkorDB is listed. After adding the network to compose, verify with `docker exec dotmd-api-1 getent hosts falkordb`.
**Warning signs:** `ConnectionError: Cannot connect to FalkorDB at redis://falkordb:6379`.

### Pitfall 3: Running API Service During Re-index
**What goes wrong:** BM25 index (pickle file) and sqlite-vec database get corrupted or serve stale data while the re-index is writing to them.
**Why it happens:** File-based stores don't support concurrent write+read from separate processes.
**How to avoid:** `docker compose stop api` before `docker compose run --rm api index --force /mnt`, then `docker compose up -d api` after.
**Warning signs:** Garbled search results, sqlite "database is locked" errors, pickle deserialization errors.

### Pitfall 4: Graph Name Collision with Graphiti
**What goes wrong:** dotmd overwrites Graphiti's knowledge graph data.
**Why it happens:** Both use the same FalkorDB instance. If `falkordb_graph_name` isn't set, the default is `dotmd` (safe). But if someone sets it to `knowledgebase` (Graphiti's graph name), data gets mixed.
**How to avoid:** Explicitly set `DOTMD_FALKORDB_GRAPH_NAME=dotmd` in compose environment (D-03). The default in `config.py` is already `dotmd`, but being explicit prevents accidents.
**Warning signs:** Unexpected node types in graph queries, Graphiti queries returning dotmd entities.

### Pitfall 5: Forgetting to Start API After Re-index
**What goes wrong:** The API stays down after the overnight re-index completes.
**Why it happens:** `docker compose run` creates a separate container that exits when done. The `api` service was stopped before indexing and needs to be explicitly started.
**How to avoid:** Include `docker compose up -d api` as the final step in the re-index procedure.
**Warning signs:** Port 8321 not responding, `docker ps` shows no dotmd-api container.

## Code Examples

### Target docker-compose.yml (complete)

```yaml
# /opt/docker/dotmd/docker-compose.yml
services:
  api:
    build:
      context: /home/j2h4u/repos/j2h4u/dotmd/backend
    ports:
      - "127.0.0.1:8321:8000"
    volumes:
      - /srv/knowledgebase/voicenotes:/mnt/voicenotes:ro
      - /home/j2h4u:/mnt/home:ro
      - dotmd-index:/dotmd-index
      - dotmd-hf-models:/root/.cache/huggingface
    environment:
      - DOTMD_DATA_DIR=/mnt
      - DOTMD_INDEX_DIR=/dotmd-index
      - DOTMD_EMBEDDING_URL=http://embeddings:80
      - DOTMD_EMBEDDING_DIM=1024
      - DOTMD_EXTRACT_DEPTH=ner
      - DOTMD_GRAPH_BACKEND=falkordb
      - DOTMD_FALKORDB_URL=redis://falkordb:6379
      - DOTMD_FALKORDB_GRAPH_NAME=dotmd
    env_file:
      - /home/j2h4u/.secrets/huggingface.env
    networks:
      - default
      - embeddings
      - graphiti
    command: ["serve", "--host", "0.0.0.0"]

volumes:
  dotmd-index:
  dotmd-hf-models:

networks:
  embeddings:
    external: true
    name: embeddings_default
  graphiti:
    external: true
    name: graphiti_default
```

### Re-index Procedure (operator commands)

```bash
# 1. Rebuild image (picks up falkordb dependency + all Phase 4/5 code)
cd /opt/docker/dotmd
docker compose build

# 2. Stop the running API service
docker compose stop api

# 3. Run full re-index (overnight, ~59 min)
docker compose run --rm api index --force /mnt

# 4. Start API service
docker compose up -d api
```

### Validation Commands

```bash
# Check 1: Status shows falkordb backend with entity/edge counts
docker exec dotmd-api-1 dotmd status

# Check 2: Hybrid search includes graph results
docker exec dotmd-api-1 dotmd search --mode hybrid "test query"

# Check 3: API serves results (concurrent access works)
curl -s "http://localhost:8321/search?q=test&mode=hybrid" | python3 -m json.tool | head -20

# Check 4: Verify network connectivity
docker exec dotmd-api-1 getent hosts falkordb

# Check 5: FalkorDB graph has data (direct check)
docker exec graphiti-falkordb-1 redis-cli GRAPH.QUERY dotmd "MATCH (n) RETURN count(n)"
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| LadybugDB (embedded, file-based) | FalkorDB (network, Redis protocol) | Phase 4, 2026-03-26 | Concurrent CLI + API access now possible |
| Manual `docker network connect` | Compose external network declaration | Docker Compose v2 standard | Declarative, lifecycle-safe |

## Open Questions

1. **FalkorDB health check in compose**
   - What we know: The FalkorDBGraphStore constructor raises `ConnectionError` if FalkorDB is unreachable. The API server's lifespan handler creates the service, so it would fail to start if FalkorDB is down.
   - What's unclear: Should we add a `depends_on` with health check condition, or is the Python-level error handling sufficient?
   - Recommendation (Claude's discretion): Not needed for this phase. FalkorDB has been running for 13 days without issues. The Python error gives a clear message. A health check can be added later if stability issues arise.

2. **Image rebuild time**
   - What we know: The Dockerfile uses multi-stage build. Layer 1 (PyTorch) is cached. Layer 2 (pyproject.toml dependencies) will be invalidated because `falkordb` was added.
   - What's unclear: Exact rebuild time. The `falkordb` package is lightweight (Redis client), but all deps reinstall when `pyproject.toml` changes.
   - Recommendation: Run `docker compose build` during daytime, then do the re-index overnight.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Docker Compose | Container orchestration | Yes | v5.1.0 | -- |
| FalkorDB container | Graph storage | Yes | latest (running 13 days) | -- |
| `graphiti_default` network | Container connectivity | Yes | bridge driver | -- |
| `embeddings_default` network | Embedding server access | Yes | bridge driver | -- |
| `falkordb` Python package | FalkorDB adapter | In pyproject.toml, NOT in current image | >=1.6.0 | Image rebuild required |

**Missing dependencies with no fallback:**
- `falkordb` Python package in container image -- resolved by `docker compose build`

**Missing dependencies with fallback:**
- None

## Sources

### Primary (HIGH confidence)
- Live Docker inspection: `docker inspect graphiti-falkordb-1`, `docker inspect dotmd-api-1`, `docker network inspect graphiti_default` -- verified network membership, DNS aliases, IP addresses
- `/opt/docker/dotmd/docker-compose.yml` -- current production compose file (read directly)
- `/opt/docker/graphiti/docker-compose.yml` -- FalkorDB service definition (read directly)
- `backend/src/dotmd/storage/falkordb_graph.py` -- FalkorDB adapter implementation (read directly)
- `backend/src/dotmd/core/config.py` -- Settings with graph_backend, falkordb_url, falkordb_graph_name (read directly)
- `backend/pyproject.toml` -- confirms `FalkorDB>=1.6.0` dependency (grepped)
- Container runtime test: `docker exec dotmd-api-1 pip show falkordb` -- confirmed NOT installed in current image

### Secondary (MEDIUM confidence)
- Docker Compose v5 documentation for `docker compose run` network inheritance behavior (from training data, consistent with observed behavior)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all components verified via live Docker inspection
- Architecture: HIGH -- external network pattern already exists in the same compose file, just replicating it
- Pitfalls: HIGH -- stale image issue discovered empirically (tested import failure in container)

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable infrastructure, no moving targets)
