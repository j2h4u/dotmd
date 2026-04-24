---
phase: 15-content-addressed-caching
plan: "01"
subsystem: storage/ingestion
tags: [embedding-cache, sqlite, content-addressed, model-invalidation]
dependency_graph:
  requires: []
  provides: [EmbeddingCache, pipeline._embedding_cache]
  affects: [backend/src/dotmd/ingestion/pipeline.py, backend/src/dotmd/storage/cache.py]
tech_stack:
  added: []
  patterns: [composite-pk-cache, model-sentinel-invalidation, insert-or-ignore-idempotent]
key_files:
  created:
    - backend/src/dotmd/storage/cache.py
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
decisions:
  - "Composite PK (text_hash, model_name) — vectors from different models stored separately, cross-use impossible"
  - "INSERT OR IGNORE semantics for store() — first write wins, prevents silent overwrites on cache warm"
  - "setdefault() merge for global cache into existing — vec_meta always wins on overlap"
  - "No commit inside _embed_chunks() — new rows piggyback on caller's existing post-vector-store commit"
  - "should_invalidate() returns False on empty meta table (first run) to avoid spurious clears"
metrics:
  duration: "~10 min"
  completed: "2026-04-24"
  tasks: 2
  files: 2
---

# Phase 15 Plan 01: Global Embedding Cache Summary

**One-liner:** SQLite-backed global embedding cache keyed on (text_hash, model_name) with model-sentinel invalidation — TEI calls skipped for moved/unchanged chunks.

## What Was Built

A new `EmbeddingCache` class in `backend/src/dotmd/storage/cache.py` backed by two SQLite tables in `index.db`:

- `embedding_cache` — composite PK `(text_hash, model_name)`, stores BLOB-serialized float32 vectors
- `embedding_cache_meta` — single-row sentinel tracking which model populated the cache

`IndexingPipeline.__init__()` instantiates the cache with the shared connection and current `settings.embedding_model`. On startup it checks `should_invalidate()`: if the sentinel model differs from the current model, it clears the entire cache and writes a fresh sentinel; otherwise it confirms the sentinel.

Inside `_embed_chunks()`, after the existing `vec_meta` hash lookup, the global cache is consulted for any remaining misses. Results are merged via `setdefault()` so `vec_meta` hits always win. Newly computed embeddings (from `encode_batch()`) are written to the cache via `store()` — no commit is issued; the rows are persisted by the existing caller-level commit that follows `_vector_store.add_chunks()`.

## Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 1 | Create EmbeddingCache in storage/cache.py | 061937c | backend/src/dotmd/storage/cache.py |
| 2 | Wire EmbeddingCache into IndexingPipeline | 576fe7a | backend/src/dotmd/ingestion/pipeline.py |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Model Coverage

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-15-01-02 | should_invalidate() + clear() on model change | Implemented |
| T-15-01-03 | Composite PK (text_hash, model_name) — separate per-model storage | Implemented |

## Known Stubs

None.

## Self-Check: PASSED

- `backend/src/dotmd/storage/cache.py` exists: FOUND
- `backend/src/dotmd/ingestion/pipeline.py` modified: FOUND
- Commit 061937c exists: FOUND
- Commit 576fe7a exists: FOUND
- In-memory smoke test: PASSED (all 7 assertions)
- pipeline.py wiring verify: PASSED (all 6 assertions + ast.parse)
