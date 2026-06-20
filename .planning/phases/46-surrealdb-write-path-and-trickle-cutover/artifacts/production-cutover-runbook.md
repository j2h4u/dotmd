# Phase 46 Production Cutover Runbook

Status: **cutover executed; soak accepted**

This is the operator checklist and evidence note for the Phase 46 production
cutover.

## Scope

- No legacy/backcompat work is included here.
- Do not run `dotmd index --force` while the container is running.
- Phase 47 physical deletion is out of scope until soak is accepted.

## Pre-cutover state to verify

- `dotmd` is healthy on the old stack.
- `surrealdb/surrealdb:v3.1.4` is running.
- Phase 43 verify-only passed.
- Rerank-off is the accepted cutover path; rerank-on is follow-up work.
- Surreal FTS child-process smoke has passed without restarting production.
- Old-stack hybrid search is not a clean baseline right now: TEI CPU encode
  logged `93.7s`, Gmail OAuth refresh returns 400, and Falkor graph enrichment
  needed bounding/batching fixes.

Verify production health from inside the container:

```bash
docker exec dotmd curl -fsS http://127.0.0.1:8080/health
```

## Rollback bundle before restart

Record or snapshot all of the following before any production restart:

- `/dotmd-index` Docker volume
- `/srv/falkordb`
- `/srv/surrealdb/data`
- `/opt/docker/dotmd` compose/env/config
- `/opt/docker/surrealdb` compose/env
- current `dotmd` image digest
- current git SHA

## DotMD cutover env changes

Apply these `dotmd` environment changes for the cutover restart:

- `DOTMD_SEARCH_BACKEND=surreal`
- `DOTMD_SURREAL_RETRIEVAL_URL=http://surrealdb:8000`
- namespace: `dotmd`
- database: `production`
- username/password from `/opt/docker/surrealdb/.env`
- embedding dimension: `1024`
- `hnsw_ef=40`
- shard count: `1`

Do not print secrets.

## Restart boundary

- Make exactly one deliberate `dotmd` recreate/restart.
- Do this only after the rollback bundle above is captured.
- Do not chain a second restart before the smoke checks below complete.

## Live smoke after restart

Run these checks in order:

1. Health from inside the container:
   `docker exec dotmd curl -fsS http://127.0.0.1:8080/health`
2. MCP stdio smoke:
   `cd backend && uv run python -m devtools.mcp_client.cli script --file devtools/mcp_client/smoke.json --timeout 120 -- docker exec -i dotmd dotmd mcp`
3. Controlled trickle edit smoke.
4. Optional controlled delete/tombstone smoke.

## Executed cutover evidence

- Rollback/config bundle:
  `/srv/dotmd-cutover-backups/20260619T232441+0500`
- DotMD env switch: `DOTMD_SEARCH_BACKEND=surreal`,
  initially pointed at the Phase 43 refresh database.
- Restart boundary: one `docker compose up -d --no-deps --force-recreate dotmd`.
- Health after restart:
  `docker exec dotmd curl -fsS http://127.0.0.1:8080/health` -> `{"status":"ok"}`.
- Runtime settings inside container:
  `search_backend=surreal`.
- CLI keyword smoke passed:
  `docker exec dotmd dotmd search --mode keyword --no-rerank --no-expand -n 3 'SurrealDB вектора graph'`.
- MCP stdio smoke passed:
  `cd backend && UV_LINK_MODE=hardlink uv run python -m devtools.mcp_client.cli script --file devtools/mcp_client/smoke.json --timeout 120 -- docker exec -i dotmd dotmd mcp`.
- MCP `search -> drill -> read` passed for the returned SurrealDB document ref.
- Controlled trickle edit/delete smoke passed for
  `dotmd_surreal_cutover_smoke_20260619_232955`; insert indexed in `72.4s`
  and delete was logged as `Watch: purged deleted ...`.

## Final soak acceptance

- Production now targets clean database `production`, not a Phase 43 rehearsal
  database name.
- Runtime env inside `dotmd` reports `DOTMD_SEARCH_BACKEND=surreal` and
  `DOTMD_SURREAL_RETRIEVAL_DATABASE=production`.
- `/opt/docker/dotmd/.env` records
  `DOTMD_SURREAL_RETRIEVAL_VECTOR_INDEX_TYPE=F16` for the next planned restart.
- Live health returned `{"status":"ok"}`.
- Live Surreal counts on 2026-06-20: documents=1441, files=1083,
  chunks=149882, embeddings=149872, entities=81822, relations=343561,
  feedback=5.
- `INFO FOR INDEX embeddings_vector_hnsw ON embeddings` reports
  `status=ready`, `pending=0`, `initial=149872`.
- Hybrid no-rerank CLI smoke returned Surreal-backed semantic/graph results.

## Observed follow-up risks

- `dotmd status --verbose` is a poor cutover smoke: it took `47.651s` and
  mostly exercises filesystem discovery/status rather than proving Surreal
  search.
- The current MCP `search` tool has no `mode`/`rerank` knobs, so MCP smoke
  exercises full hybrid+rerank and can spend tens of seconds loading the
  cross-encoder in a fresh stdio process.
- The controlled one-file trickle insert was dominated by extraction/graph
  work: `extract 25.85s`, `graph 44.40s`, `embed 2.05s`.

## Stop or rollback if any of these fail

- Health fails.
- MCP stdio smoke fails or the search hit is wrong for the controlled smoke.
- Trickle update is missing.
- Tombstone delete is missing.
- Repeated query latency is unacceptable even with no-rerank enabled.

## Known non-blockers

- Gmail federated OAuth 400 is a separate issue unless Gmail is included in the
  acceptance scope.
- Rerank-on is follow-up work, not a cutover blocker for Phase 46.
- Old-stack TEI/Falkor latency must not be treated as proof that Surreal is
  slow; compare no-rerank/no-expand cutover smoke and then handle rerank/TEI as
  a separate optimization track.

## After successful soak

- Phase 47 may physically remove SQLite, sqlite-vec, FTS5, FalkorDB, LadybugDB,
  and related code/config/data.
- Before Phase 47 starts, do not delete rollback data.
