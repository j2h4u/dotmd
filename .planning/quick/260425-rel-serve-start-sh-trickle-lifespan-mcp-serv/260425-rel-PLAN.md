---
quick_id: 260425-rel
slug: serve-start-sh-trickle-lifespan-mcp-serv
description: "Убрать serve из start.sh — trickle lifespan в mcp_server.py, /health на 8080, Dockerfile healthcheck → 8080"
date: 2026-04-25
must_haves:
  truths:
    - mcp_server.py has a /health GET route returning {"status":"ok"} on port 8080
    - mcp_server.py lifespan starts and stops the trickle indexer
    - api/server.py lifespan no longer manages the trickle indexer
    - start.sh runs only dotmd mcp (no dotmd serve)
    - Dockerfile HEALTHCHECK points to localhost:8080/health
  artifacts:
    - backend/src/dotmd/mcp_server.py
    - backend/src/dotmd/api/server.py
    - backend/start.sh
    - backend/Dockerfile
---

# Quick Task 260425-rel: Collapse two-process start.sh into single MCP process

## Task 1: Add lifespan + /health to mcp_server.py

**files:** `backend/src/dotmd/mcp_server.py`
**action:**
- Import `asyncio`, `asynccontextmanager`, `AsyncIterator` from stdlib; `Request`/`JSONResponse` from starlette
- Add `_lifespan` async context manager: init service, warmup, start trickle task, yield, stop trickle with 120s timeout
- Pass `lifespan=_lifespan` to `FastMCP(...)` constructor
- Simplify `_get_service()` to assert (no more lazy init — lifespan owns it)
- Add `@mcp.custom_route("/health", methods=["GET"])` returning `JSONResponse({"status": "ok"})`
**verify:** file has both lifespan and /health route
**done:** mcp_server.py has trickle management and health endpoint

## Task 2: Remove trickle from api/server.py lifespan

**files:** `backend/src/dotmd/api/server.py`
**action:**
- Strip asyncio task creation and shutdown logic for trickle indexer from `_lifespan`
- Keep: service init, warmup, yield, `_service = None`
- Remove unused imports if any (asyncio, asynccontextmanager stay if still needed)
**verify:** no `trickle_indexer` references in server.py
**done:** server.py lifespan is lean (service only)

## Task 3: Update start.sh and Dockerfile

**files:** `backend/start.sh`, `backend/Dockerfile`
**action:**
- start.sh: replace two-line script with `exec dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`
- Dockerfile: change HEALTHCHECK URL from `localhost:8000/health` to `localhost:8080/health`
**verify:** start.sh has single exec line; Dockerfile has 8080 in healthcheck
**done:** container starts one process, healthcheck targets MCP port
