# Phase 46 Production Cutover Criteria

Decision: **not production cutover yet**.

This file records the decision state and the evidence already in hand. The
exact operator procedure lives here:

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
- Live Surreal keyword child-process smoke passed in `2.139s` against
  `phase43_refresh_20260618g`.
- Phase 43 verify-only passed.
- Devtools gate passed.
- Rerank off is the accepted cutover path.

## Remaining cutover gates

- Rollback bundle captured before restart.
- DotMD env switch applied and production container restarted once.
- Production/live smoke passed via internal `/health` and the MCP stdio smoke.
- Controlled trickle edit/delete smoke passed.
- Stop and rollback conditions are clear and tested.
- Phase 47 deletion happens only after soak.

## Remaining non-Surreal defects

- Gmail federated search currently fails token refresh with OAuth 400.
- Old-stack hybrid with semantic search remains dominated by TEI CPU latency
  (`93.7s` encode observed) and should not be used as a healthy performance
  baseline for the Surreal cutover decision.

## Non-goals

- Phase 47 deletion is not done yet.
- Production container has not been restarted for cutover yet.
