---
created: 2026-03-28T11:20:44.100Z
title: Soft-delete with TTL for removed source files
area: api
files:
  - backend/src/dotmd/ingestion/trickle.py
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/search/bm25.py
  - backend/src/dotmd/storage/sqlite_vec.py
---

## Problem

Trickle indexer only adds and updates files — no deletion path exists. When a source .md file is deleted from disk (or excluded via config), its chunks remain orphaned across all 4 stores:
- metadata.db (chunks table)
- FTS5 (chunks_fts)
- sqlite-vec (embeddings)
- FalkorDB (graph nodes + edges)

Immediate trigger: ~1100 files from .platformio/.npm/.bun were indexed before being added to exclude list. Their data persists in all stores with no cleanup mechanism.

Broader issue: voicenotes or docs deleted by the user leave stale data that pollutes search results and graph traversals — search returns chunks whose source no longer exists, with no way to distinguish live from orphaned.

## Solution

Soft-delete with TTL model:

1. **Detection**: trickle poll cycle checks `diff.deleted` — files in file_tracker but not in discovered set
2. **Mark**: add `deleted_at` timestamp to chunks in metadata.db (new column). Don't remove from FTS5/vectors/graph yet — the knowledge is still valid for context
3. **TTL**: configurable retention period (e.g., `deleted_ttl_days = 30` in config.toml). After TTL expires, hard-purge from all stores
4. **Search**: chunks with `deleted_at` set should be deprioritized or flagged in results ("source deleted") — user can still see the content but knows it's ungrounded
5. **Status**: `dotmd status` shows "N files pending deletion (TTL Xd)"

Design principle: deletion of knowledge should be deliberate and gradual, not instant. The file is gone but the memory persists for a configurable period.
