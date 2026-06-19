# Phase 44 Cutover Approval

Decision: **NO-GO**

## Reasons

1. Standalone SurrealDB runtime wiring is not implemented for MCP/API/CLI/trickle.
2. Current production `dotmd` still runs the old SQLite/sqlite-vec/FalkorDB
   stack.
3. Reranker-on candidate latency is too high and unstable for production
   cutover.
4. Reranker-off evidence is promising, but Phase 44 requires the full runtime
   surface and both reranker modes.

## Required Before Retrying Cutover

- Add a real standalone SurrealDB runtime backend switch for MCP/API/CLI.
- Add trickle write-path support for standalone SurrealDB or explicitly defer
  trickle cutover with a documented product decision.
- Add a reusable reranker-off acceptance runner instead of relying on manual
  candidate-only artifacts.
- Re-run Phase 44 smoke against the real standalone runtime.
