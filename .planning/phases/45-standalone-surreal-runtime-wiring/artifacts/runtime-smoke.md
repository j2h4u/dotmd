# Phase 45 Runtime Smoke Evidence

Date: 2026-06-19

## Scope

Controlled SurrealDB-backed retrieval smoke without switching production MCP
traffic to `search_backend=surreal`.

Production `dotmd` stayed healthy on the default `search_backend=sqlite`.
Surreal mode was enabled only for one-off child processes.

## Safety Guard

Startup destructive repair is gated by
`DOTMD_ALLOW_DESTRUCTIVE_STARTUP_REPAIR=true` and was left unset.

Observed startup log in all smoke runs:

```text
Skipping destructive startup repair checks; set DOTMD_ALLOW_DESTRUCTIVE_STARTUP_REPAIR=true to run them
```

## CLI Smoke

Command shape:

```bash
dotmd search --mode hybrid --no-rerank --no-expand -n 3 "SurrealDB вектора graph"
```

Runtime env was injected only into the child process:

- `DOTMD_SEARCH_BACKEND=surreal`
- `DOTMD_SURREAL_RETRIEVAL_URL=http://surrealdb:8000`
- `DOTMD_SURREAL_RETRIEVAL_NAMESPACE=dotmd`
- `DOTMD_SURREAL_RETRIEVAL_DATABASE=phase43_refresh_20260618g`
- `DOTMD_SURREAL_RETRIEVAL_EMBEDDING_DIMENSION=1024`
- Surreal username/password from `/opt/docker/surrealdb/.env`

Result: PASS.

Evidence:

- exit code `0`
- timestamps: `2026-06-19T11:17:56+00:00` to
  `2026-06-19T11:18:09+00:00`
- returned 3 filesystem refs
- matched engines included Surreal-backed `graph_direct`, `keyword`, and
  `semantic`

## API Smoke

Initial result: FAIL.

`GET /search` returned HTTP 500 because the async FastAPI endpoint called the
sync wrapper `DotMDService.search()` from a running event loop.

Error:

```text
RuntimeError: DotMDService.search() called from a running event loop; use search_async() instead
```

Fix:

- `backend/src/dotmd/api/server.py` now awaits `search_async()`
- focused regression added in `backend/tests/api/test_service_search.py`

Verification:

```bash
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/api/server.py tests/api/test_service_search.py
UV_LINK_MODE=hardlink uv run pytest tests/api/test_service_search.py -q -k 'search_endpoint_awaits_async_service_path or search_endpoint_unknown_reranker_returns_400'
```

Result after fix: PASS.

Evidence:

- temporary API server on `127.0.0.1:8092`
- startup: `2026-06-19T11:22:51+00:00`, application ready at
  `2026-06-19 11:23:13`
- `GET /health` returned HTTP 200 and `{"status":"ok"}`
- `GET /search?q=SurrealDB+вектора+graph&top_k=3&mode=hybrid&rerank=false&expand=false`
  returned HTTP 200, `count=3`
- returned refs included the expected SurrealDB knowledgebase notes
- matched engines included `graph_direct`, `keyword`, and `semantic`

## MCP Smoke

Command shape:

```bash
UV_LINK_MODE=hardlink uv run python -m devtools.mcp_client.cli call-tool \
  --name search \
  --arguments '{"query":"SurrealDB вектора graph","top_k":3}' \
  --timeout 90 \
  --compact \
  -- bash -lc '... docker exec -i ... dotmd dotmd mcp'
```

Result: PASS.

Evidence:

- stdio MCP child process with `DOTMD_SEARCH_BACKEND=surreal`
- `isError=false`
- returned 3 candidates
- matched engines included `graph_direct`, `keyword`, and `semantic`

Note: MCP `search` has no no-rerank option, so the one-off smoke loaded the
cross-encoder and took longer than CLI/API rerank-off smoke.

## Federated Gmail Noise

All smoke paths showed an unrelated federated Gmail failure:

```text
gmail:fts failed: Client error '400 Bad Request' for url 'https://oauth2.googleapis.com/token'
```

This did not block Surreal-backed local retrieval. It should be handled as a
separate federated-source credential issue, not as a Surreal runtime blocker.

## Trickle Decision

Decision: `search_backend=surreal` gates retrieval engines only.

Trickle remains on the existing SQLite/sqlite-vec/FalkorDB write path in Phase
45. Standalone SurrealDB write support is explicitly deferred and remains a
separate cutover blocker until implemented and smoke-tested.

Evidence:

- `DotMDService` swaps semantic, keyword, and graph-direct retrieval engines
  only when `search_backend=surreal`.
- `IndexingPipeline` still constructs and writes through SQLite metadata,
  sqlite-vec, and graph stores.
- `TrickleIndexer` feeds files into `pipeline.index_file()` and does not branch
  on `search_backend`.

## Result

Phase 45 runtime retrieval smoke is accepted for CLI/API/MCP.

Production cutover is still not approved because the write path is not
SurrealDB-native yet and reranker-on latency remains a separate production
quality concern from Phase 44.
