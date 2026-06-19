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
- Phase 43 verify-only passed.
- Devtools gate passed.
- Rerank off is the accepted cutover path.

## Remaining cutover gates

- Rollback bundle captured before restart.
- DotMD env switch applied and production container restarted once.
- Production/live smoke passed.
- Controlled trickle edit/delete smoke passed.
- Stop and rollback conditions are clear and tested.
- Phase 47 deletion happens only after soak.

## Non-goals

- Phase 47 deletion is not done yet.
- Production container has not been restarted for cutover yet.
