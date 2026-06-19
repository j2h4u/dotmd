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
- Direct writes are visible through safe local temporary `surrealkv://`
  API, CLI, and MCP public-entrypoint smokes.
- Normal Surreal ingest skips local sqlite-vec and FTS writes.
- Manual reindex paths in Surreal mode now skip legacy sqlite-vec and FTS5
  writes instead of mutating local legacy stores.
- Destructive admin/public purge methods fail fast in Surreal mode, and
  `_purge_file`/`purge_orphaned_files` stay tombstone-only.
- Phase 46 reranker decision is now explicit: cutover proceeds with rerank off
  / no-rerank; rerank-on latency optimization is follow-up work, not a Phase 46
  blocker.
- The focused gate passed: `85 passed`, with `ruff` clean.
- Expanded orchestrator validation passed: `94 passed, 1 warning`, with `ruff`
  clean.
- Devtools runner gate passed: `67 passed in 1.08s`.
- Phase 43 shadow bundle verify-only passed with explicit required args.
- Artifact summary still reports `passed=true`, `regression=0`, and no
  unresolved blockers or unclear items.

Reference:

- `46-01-SUMMARY.md` records the direct-write smoke, service-level visibility,
  the normal-ingest sqlite-vec/FTS skip decision, and the manual reindex guard.
- `46-01-SUMMARY.md` also records the public-entrypoint smokes and tombstone
  fencing for purge/orphan handling.

## Remaining Cutover Gates

- Standalone production SurrealDB target must be fresh-migrated, imported, and
  rebuilt if needed.
- Local API, CLI, and MCP smoke is satisfied; production/live smoke must pass
  against the direct-written changes.
- Trickle must pass a live smoke with a controlled file change; no full reindex
  or `index --force` while the container runs.
- Old-stack remaining dependencies outside normal ingest must be removed,
  quarantined, or marked non-authoritative.
- Reranker latency is not a blocker for Phase 46 cutover acceptance now that
  rerank off / no-rerank is the accepted path; rerank-on optimization is
  follow-up work.
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
- Commit `06e8179` guards manual reindex paths in Surreal mode so they no-op
  instead of mutating sqlite-vec or FTS5.
- Commits `c9fa512`, `5542938`, and `231f531` fence Surreal purge/orphan paths
  to tombstone-only behavior.

## Status

Keep production on the current stack until the remaining gates are proven in a
fresh standalone Surreal deployment.
