---
phase: 45-standalone-surreal-runtime-wiring
plan: 01
subsystem: standalone-surrealdb-cutover
status: complete
completed_at: 2026-06-19
---

# Phase 45 Plan 01 Summary

## Outcome

Standalone SurrealDB is now a real config-gated runtime retrieval backend for
dotMD search.

The phase did not cut production traffic over. It proved the runtime surface
with one-off child processes while production stayed on the default SQLite
runtime.

## Delivered

- Config-gated `search_backend=surreal` service wiring.
- Surreal-backed semantic, keyword, and graph-direct retrieval engines wired
  into `DotMDService`.
- Legacy seed-based graph enrichment disabled in Surreal retrieval mode.
- Surreal auth passed through runtime config.
- Startup destructive repair gated behind explicit
  `DOTMD_ALLOW_DESTRUCTIVE_STARTUP_REPAIR=true`.
- CLI, API, and MCP smoke evidence recorded in `artifacts/runtime-smoke.md`.
- API `/search` fixed to use `search_async()` from the async FastAPI endpoint.
- Trickle write-path decision recorded.

## Decision

`search_backend=surreal` is retrieval-only in Phase 45.

Trickle remains old-stack-only and is not Surreal-write-ready. A production
cutover still requires either Surreal-native write support or an explicit
product decision to operate with old-stack writes during a bounded transition.

## Verification

```bash
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/api/server.py tests/api/test_service_search.py
UV_LINK_MODE=hardlink uv run pytest tests/api/test_service_search.py -q -k 'search_endpoint_awaits_async_service_path or search_endpoint_unknown_reranker_returns_400'
```

Additional earlier verification for the runtime wiring commit:

- focused service/config/storage tests passed
- full non-live backend suite passed with `tests/e2e` excluded

## Remaining Blockers

- Surreal-native write path / trickle cutover is not implemented.
- Reranker-on latency remains too high and unstable for a production cutover
  decision.
- Gmail federated search currently returns OAuth 400 and should be treated as a
  separate federated-source credential issue.
