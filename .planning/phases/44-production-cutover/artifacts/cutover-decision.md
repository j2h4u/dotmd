# Phase 44 Cutover Decision

Decision: **NO-GO: do not cut production over to standalone SurrealDB yet.**

## What Passed

- Standalone SurrealDB target exists and is queryable.
- Populated candidate database verified: `dotmd/phase43_refresh_20260618g`.
- Search-quality evidence shows no material regression in the accepted
  candidate comparisons.
- Reranker-off candidate performance is promising:
  - candidate p50 `1308.1ms`
  - baseline p50 `3224.1ms`

## What Failed

- Production runtime is not yet standalone-SurrealDB-backed.
- MCP/API/CLI/trickle smoke cannot pass honestly because they still initialize
  the old storage stack.
- Reranker-on candidate latency remains too high:
  - full-run candidate p50 `24606.5ms`
  - reranker-on follow-up candidate p50 `14371.0ms`
  - reranker-on follow-up max `94299.7ms`

## Product Interpretation

The migration spike succeeded technically, but the production cutover is not
ready. The next work should implement and verify real standalone runtime wiring
before attempting another cutover decision.

## Next Action

Plan and execute a bounded runtime-wiring phase:

- configure dotMD service startup to use standalone SurrealDB as the retrieval
  backend;
- remove hidden old-stack fallback from that path;
- provide MCP/API/CLI smoke against the Surreal-backed runtime;
- decide whether trickle writes are included in the same cutover or explicitly
  deferred.
