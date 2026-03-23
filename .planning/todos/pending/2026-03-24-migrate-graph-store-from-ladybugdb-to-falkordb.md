---
created: 2026-03-24T00:00:00Z
title: Migrate graph store from LadybugDB to FalkorDB
area: api
files:
  - backend/src/dotmd/storage/graph.py
  - backend/src/dotmd/core/config.py
---

## Problem

LadybugDB uses a single-connection file lock — any CLI command (`dotmd index`, `seed-fingerprints`) conflicts with the running `dotmd serve` process. Already caused multiple issues during this session. FalkorDB is already running on this server (graphiti-falkordb-1 container) and supports concurrent access.

## Solution

Write a `FalkorDBGraphStore` adapter implementing the same interface as `LadybugDBGraphStore`:
- Connect to existing FalkorDB container (`graphiti-falkordb-1`, port 6379)
- Use separate graph name `"dotmd"` (FalkorDB supports multiple named graphs via `GRAPH.QUERY graphname "..."`)
- Check Cypher dialect compatibility — FalkorDB uses openCypher, current queries use MERGE, DETACH DELETE which should work but need testing
- Add `graph_backend` setting to config (similar to `vector_backend`)
- Keep LadybugDB adapter as fallback

Benefits:
- No more lock conflicts
- Reuses existing infrastructure
- Concurrent read/write from serve + CLI
- FalkorDB is actively maintained (vs LadybugDB which is a Kuzu fork)
