# Phase 44 Smoke: MCP

## Result

Status: **blocked**

## Finding

The live `dotmd` container is still old-stack wired:

- it mounts `/dotmd-index`;
- it uses FalkorDB for graph backend;
- it does not expose a Surreal-only runtime configuration path.

The current branch has Surreal-native retrieval engines and shadow-run
overrides, but the production MCP runtime is still initialized through the
normal `DotMDService`/`IndexingPipeline` path and therefore still depends on
SQLite/sqlite-vec/FalkorDB.

## Pass Condition Not Met

Phase 44 requires MCP `search` and `read` to pass against the standalone
SurrealDB runtime with no hidden old-stack fallback. That runtime wiring does
not exist yet, so MCP smoke cannot honestly pass.
