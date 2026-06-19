# Phase 46 Production Cutover Criteria

Decision: **production cutover executed; soak in progress**.

This file records the decision state and the evidence already in hand. The
operator procedure lives here:

- [Phase 46 Production Cutover Runbook](./production-cutover-runbook.md)

## Evidence already satisfied

- Direct write path is in place.
- Direct Surreal visibility is working.
- Local API, CLI, and MCP temp smokes passed.
- Local vec, FTS, reindex, and purge fencing passed.
- Surreal FTS adapter no longer performs two client roundtrips for normal
  title/text search; it uses one `query_raw()` roundtrip with two indexed
  SELECTs and Python-side score fusion.
- Falkor graph enrichment is now bounded and batched for the old-stack path,
  removing the earlier unbounded per-seed query loop.
- Live Surreal keyword child-process smoke passed in `2.139s`.
- Phase 43 verify-only passed.
- Devtools gate passed.
- Rerank off is the accepted cutover path.
- Rollback bundle captured before restart.
- DotMD env switch applied and production container restarted once.
- Production/live smoke passed via internal `/health` and the MCP stdio smoke.
- Controlled trickle edit/delete smoke passed.

## Production cutover evidence

- Rollback/config bundle captured at
  `/srv/dotmd-cutover-backups/20260619T232441+0500`.
- `/opt/docker/dotmd/.env` now sets `DOTMD_SEARCH_BACKEND=surreal` and points
  retrieval at the standalone SurrealDB service.
- `dotmd` was recreated once and is healthy.
- Runtime settings inside the container report
  `search_backend=surreal`.
- CLI keyword smoke passed after restart:
  `dotmd search --mode keyword --no-rerank --no-expand -n 3 'SurrealDB вектора graph'`.
- MCP stdio smoke passed against `docker exec -i dotmd dotmd mcp`; the tool
  surface is lowercase `search`, `read`, `drill`, `feedback`, and
  `search.federated` defaults to `false`.
- MCP `search -> drill -> read` round trip passed for the returned SurrealDB
  document ref.
- Controlled trickle edit/delete smoke passed using disposable token
  `dotmd_surreal_cutover_smoke_20260619_232955`; insert indexed in `72.4s`,
  delete purged the file and subsequent keyword search returned no results.

## Remaining soak gates

- Replace the temporary Phase 43 refresh database name with clean database
  `production`; do not make phase/rehearsal names part of the permanent
  deployment contract.
- Watch production search/trickle behavior during soak.
- Do not run Phase 47 deletion until soak is accepted.
- Keep rollback data until Phase 47 is explicitly started.

## Remaining non-Surreal defects

- Gmail federated search currently fails token refresh with OAuth 400.
- Old-stack hybrid with semantic search remains dominated by TEI CPU latency
  (`93.7s` encode observed) and should not be used as a healthy performance
  baseline for the Surreal cutover decision.

## Non-goals

- Phase 47 deletion is not done yet.
- Old SQLite/Falkor data has not been physically deleted yet.
