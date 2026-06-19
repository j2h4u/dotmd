# Phase 44 Rollback Boundary

## Current Boundary

No production cutover is approved in this Phase 44 run.

Production remains on the old stack:

- SQLite/sqlite-vec/FTS index volume mounted as `/dotmd-index`;
- FalkorDB graph backend;
- TEI embedding service;
- existing `dotmd` container runtime.

Standalone SurrealDB remains a candidate datastore under:

- `/opt/docker/surrealdb`
- `/srv/surrealdb/data`
- namespace `dotmd`
- populated database `phase43_refresh_20260618g`

## If A Future Cutover Is Approved

Rollback must be restore-based, not a live fallback switch:

1. Snapshot the old `/dotmd-index` volume before cutover.
2. Snapshot `/srv/falkordb` before cutover.
3. Snapshot `/srv/surrealdb/data` before any destructive SurrealDB migration or
   namespace/database cleanup.
4. Record the exact `dotmd` image, compose files, env files, and git commit.
5. If cutover fails, restore the old volume and FalkorDB store, redeploy the old
   runtime config, and verify MCP search/read before retrying.

## Current Decision

Rollback is documented, but not exercised for cutover because cutover is no-go.
