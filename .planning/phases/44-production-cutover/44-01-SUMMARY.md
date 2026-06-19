---
phase: 44-production-cutover
plan: 01
subsystem: standalone-surrealdb-cutover
status: complete
decision: no-go
completed: 2026-06-19
---

# Phase 44 Plan 01 Summary: Standalone SurrealDB Cutover Decision

## Result

Decision: **NO-GO**.

Do not cut production over to standalone SurrealDB yet.

## What Passed

- Standalone SurrealDB is deployed and reachable.
- Populated candidate database verified: `dotmd/phase43_refresh_20260618g`.
- Search-quality evidence shows no material accepted regression.
- Reranker-off candidate evidence is promising:
  - candidate p50 `1308.1ms`
  - baseline p50 `3224.1ms`
- Storage footprint is acceptable for continued work:
  - old `/dotmd-index` mount: `4.9G`
  - standalone `/srv/surrealdb/data`: `3.8G`

## What Blocked Cutover

1. Runtime wiring is missing. MCP/API/CLI/trickle still initialize the old
   SQLite/sqlite-vec/FalkorDB path; SurrealDB is used through shadow-run
   overrides, not as the production runtime backend.
2. Reranker-on latency is not production-ready:
   - full-run candidate p50 `24606.5ms`
   - reranker-on follow-up p50 `14371.0ms`
   - reranker-on follow-up max `94299.7ms`
3. Trickle writes are not proven against standalone SurrealDB.

## Artifacts

- `artifacts/acceptance-reranker-on.md`
- `artifacts/acceptance-reranker-off.md`
- `artifacts/storage-footprint.md`
- `artifacts/smoke-mcp.md`
- `artifacts/smoke-api.md`
- `artifacts/smoke-cli.md`
- `artifacts/smoke-trickle.md`
- `artifacts/cutover-decision.md`
- `artifacts/cutover-approval.md`
- `artifacts/rollback-boundary.md`

## Next Step

Add a bounded standalone SurrealDB runtime-wiring phase before retrying cutover:

- service startup can use standalone SurrealDB retrieval engines;
- MCP/API/CLI smoke against that runtime;
- trickle write-path decision is explicit;
- reranker-on latency is either fixed or deliberately excluded from the
  production mode.
