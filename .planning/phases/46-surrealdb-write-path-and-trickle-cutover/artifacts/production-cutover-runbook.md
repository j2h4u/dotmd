# Phase 46 Production Cutover Runbook

Status: **not production cutover yet**

This is the operator checklist for the final Phase 46 cutover. It records the
remaining action points only. It does not claim production cutover is complete.

## Scope

- No legacy/backcompat work is included here.
- No production cutover is claimed yet.
- Do not run `dotmd index --force` while the container is running.

## Pre-cutover state to verify

- `dotmd` is healthy on the old stack.
- `surrealdb/surrealdb:v3.1.4` is running.
- Phase 43 verify-only passed.
- Rerank-off is the accepted cutover path; rerank-on is follow-up work.
- Surreal FTS child-process smoke has passed without restarting production:
  `2.139s` against `phase43_refresh_20260618g`.
- Old-stack hybrid search is not a clean baseline right now: TEI CPU encode
  logged `93.7s`, Gmail OAuth refresh returns 400, and Falkor graph enrichment
  needed bounding/batching fixes.

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
- database: `phase43_refresh_20260618g` unless a fresher target is explicitly selected
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

1. Health/status.
2. CLI/API/MCP search with no rerank and no expand, or with `rerank=false`
   and `expand=false`.
3. MCP read/drill using a search-returned ref, because API/CLI read endpoints
   are not present.
4. Controlled trickle edit smoke.
5. Optional controlled delete/tombstone smoke.

## Stop or rollback if any of these fail

- Health fails.
- Surreal search is empty or wrong for the controlled smoke.
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
- Before Phase 47, do not delete rollback data.
