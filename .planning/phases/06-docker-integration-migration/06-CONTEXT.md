# Phase 6: Docker Integration + Migration - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Connect the dotmd production Docker container to the FalkorDB instance (running in the Graphiti stack on `graphiti_default` network) and run a full re-index to populate the FalkorDB knowledge graph. After this phase, `dotmd search` and `dotmd serve` both return graph results from FalkorDB, and concurrent CLI + API access works without LadybugDB file lock conflicts.

</domain>

<decisions>
## Implementation Decisions

### Docker Networking
- **D-01:** Add `graphiti_default` as an external network in the production docker-compose.yml (`/opt/docker/dotmd/docker-compose.yml`), following the exact same pattern already used for `embeddings_default`. This is declarative, survives `docker compose down/up` cycles, and doesn't require manual `docker network connect`.
- **D-02:** The FalkorDB service hostname from dotmd's perspective is `falkordb` (the service name in Graphiti's compose file, resolvable on the shared `graphiti_default` network).

### Environment Config
- **D-03:** Add FalkorDB env vars directly to the production compose `environment:` block — no separate env file. Three vars needed:
  - `DOTMD_GRAPH_BACKEND=falkordb`
  - `DOTMD_FALKORDB_URL=redis://falkordb:6379`
  - `DOTMD_FALKORDB_GRAPH_NAME=dotmd` (explicit, even though it's the default — clarity for production)
- **D-04:** Keep `DOTMD_EMBEDDING_URL`, `DOTMD_EXTRACT_DEPTH=ner`, and all other existing env vars unchanged.

### Re-index Strategy
- **D-05:** Full re-index via one-off `docker compose run` command: `docker compose run --rm api index --force /mnt`. This reuses the same image/volumes/networks as the `api` service — no separate service definition needed.
- **D-06:** Re-index is an overnight operation (~59 min based on current baseline). Run manually, not automated. The `api` service should be stopped during re-index to avoid concurrent access to the same index files (BM25, sqlite-vec are file-based).
- **D-07:** After re-index completes, start the `api` service normally. It loads the FalkorDB graph on startup via lazy connection.

### Validation Approach
- **D-08:** Validate with three checks from inside the container:
  1. `dotmd status` — should report `graph_backend: falkordb`, connection status, entity/edge counts
  2. `dotmd search --mode hybrid "test query"` — should include results with `graph` in `matched_engines`
  3. `dotmd serve` + `curl /search` — API returns graph-enriched results, concurrent access works (the whole reason for FalkorDB)

### Claude's Discretion
- Exact ordering of compose file changes (networks section, environment block)
- Whether to add a health check for FalkorDB connectivity
- Log messages for FalkorDB connection during startup

### Folded Todos
- **Migrate graph store from LadybugDB to FalkorDB** (score: 0.9) — this todo's scope is exactly Phase 6's scope. The adapter (Phase 4) is done; this phase completes the migration by connecting Docker networking and running re-index.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Docker Configuration
- `/opt/docker/dotmd/docker-compose.yml` — Production compose file; currently has `embeddings_default` external network pattern to follow
- `/opt/docker/graphiti/docker-compose.yml` — FalkorDB service definition; service name `falkordb` is the DNS hostname on `graphiti_default`

### FalkorDB Adapter
- `backend/src/dotmd/storage/falkordb_graph.py` — FalkorDB adapter (Phase 4 output), connects via Redis URL
- `backend/src/dotmd/core/config.py` — Settings with `graph_backend`, `falkordb_url`, `falkordb_graph_name` fields

### Pipeline
- `backend/src/dotmd/ingestion/pipeline.py` — Indexing pipeline; graph backend selection via factory
- `backend/src/dotmd/cli.py` — CLI `index` and `status` commands; `status` reads graph config directly

### Requirements
- `.planning/REQUIREMENTS.md` — GRAPH-04 (Docker networking), GRAPH-05 (full re-index with --force)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **External network pattern**: Production compose already declares `embeddings_default` as external — identical pattern for `graphiti_default`
- **FalkorDBGraphStore**: Complete adapter from Phase 4, accepts `url` and `graph_name` params, connects via Redis protocol
- **Graph factory** (`pipeline.py`): Already selects backend based on `settings.graph_backend` — no code changes needed for pipeline
- **CLI status**: Already reports graph backend type and connection status via direct config read

### Established Patterns
- **Environment-driven config**: All settings via `DOTMD_` prefix env vars in compose `environment:` block
- **Named volumes**: `dotmd-index` and `dotmd-hf-models` for persistent data across container rebuilds
- **Multi-network containers**: `api` service already on `default` + `embeddings` networks; adding a third is the same pattern

### Integration Points
- `/opt/docker/dotmd/docker-compose.yml` — the only file that needs editing (add network + env vars)
- No code changes expected — Phase 4 adapter + Phase 5 BM25 fix handle everything in the application layer
- FalkorDB container (`graphiti-falkordb-1`) is already running on `graphiti_default` at `172.25.0.2`

</code_context>

<specifics>
## Specific Ideas

- This is a pure infrastructure/config phase — no Python code changes expected
- The `dotmd` graph in FalkorDB must be separate from Graphiti's `knowledgebase` graph (config default already handles this)
- After migration, LadybugDB stays as fallback — removal is future requirement GRAPH-F1

</specifics>

<deferred>
## Deferred Ideas

- **GRAPH-F1: LadybugDB adapter removal** — only after FalkorDB proven stable in production
- **GRAPH-F2: pandas to optional dependency** — only needed by LadybugDB, remove when LadybugDB removed
- **Automated re-index scheduling** — not needed for now; manual overnight run is sufficient for ~227 files

### Reviewed Todos (not folded)
- **Scout other dotmd forks for ideas** (score: 0.6) — general exploration, not specific to Docker integration. Belongs in backlog.

</deferred>

---

*Phase: 06-docker-integration-migration*
*Context gathered: 2026-03-27*
