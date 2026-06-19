# Phase 46 Production Cutover Criteria

Decision: **not production cutover yet**.

This artifact updates the Phase 44 no-go criteria after the direct SurrealDB
write-path evidence landed in Phase 46. It does not approve cutover.

## Evidence Already Satisfied

- Direct write path strategy is chosen; no long-lived hybrid sync layer is the
  target.
- Direct pipeline -> SurrealKV smoke counts were observed.
- Native relation inserts are confirmed and the endpoint direction was fixed.
- `vector_rowid` selection is deterministic and integer-based.
- Direct writes are visible to `SurrealFTSSearchEngine`.
- Direct writes are visible through `DotMDService` keyword search.
- Normal Surreal ingest skips local sqlite-vec and FTS writes.
- The focused gate passed: `82 passed`, with `ruff` clean.

Reference:

- `46-01-SUMMARY.md` records the direct-write smoke, service-level visibility,
  and the normal-ingest sqlite-vec/FTS skip decision.

## Remaining Cutover Gates

- Standalone production SurrealDB target must be fresh-migrated, imported, and
  rebuilt if needed.
- API, CLI, MCP, and production smoke must pass against the direct-written
  changes.
- Trickle must pass a live smoke with a controlled file change; no full reindex
  or `index --force` while the container runs.
- Old-stack remaining dependencies outside normal ingest must be removed,
  quarantined, or marked non-authoritative.
- Reranker latency must be decided: rerank off accepted, or rerank on fixed.
- Rollback/restore checkpoint must be updated from Phase 44 to the standalone
  Surreal deployment.

## Explicit Non-Goals

- Phase 47 legacy-stack deletion is not complete.
- `read()` is not claimed to be Surreal-backed.
- The production container has not been restarted for cutover.

## Current References

- Current branch: `milestone/v1.8-standalone-surrealdb-cutover`
- Cutover criteria artifact commit: `acfb513`
- Phase 46 summary commit chain includes `41409a3`, which skips local
  sqlite-vec and FTS writes for the normal Surreal ingest path.

## Status

Keep production on the current stack until the remaining gates are proven in a
fresh standalone Surreal deployment.
