---
quick_id: 260425-rel
status: complete
date: 2026-04-25
---

# Quick Task 260425-rel: Collapse two-process start.sh into single MCP process

## What was done

Consolidated the container from two processes (`dotmd mcp` bg + `dotmd serve` fg) into a single foreground `dotmd mcp` process owning all production responsibilities.

**mcp_server.py:**
- Added `_lifespan` async context manager (identical logic to old `api/server.py` lifespan) — initializes service, warms up, starts trickle indexer task, graceful 120s shutdown
- Passed `lifespan=_lifespan` to `FastMCP(...)` constructor (FastMCP 1.27.0 native support)
- Added `@mcp.custom_route("/health", methods=["GET"])` returning `{"status": "ok"}` via `starlette.responses.JSONResponse`
- Simplified `_get_service()` from lazy-init to assert (service guaranteed by lifespan)

**api/server.py:**
- Stripped trickle start/stop from `_lifespan`; now only init, warmup, yield, clear
- Removed unused `asyncio` import

**start.sh:**
- Reduced from 2-line (bg + fg) to single `exec dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`

**Dockerfile:**
- Healthcheck target: `localhost:8000/health` → `localhost:8080/health`

## Verification

- Container rebuilt and started cleanly: `Application startup complete.`
- `docker exec dotmd curl -sf http://localhost:8080/health` → `{"status":"ok"}`
- Docker healthcheck: container status `(healthy)`
- No errors in startup logs; lifespan ran to yield without exception

## Notes

- `docker-compose.yml` still has `${DOTMD_PORT:-8000}:8000` port mapping — now a dead mapping since port 8000 is no longer listening. Harmless; cleanup is a separate concern.
- `dotmd serve` command still works if invoked manually (has its own lean lifespan without trickle).
