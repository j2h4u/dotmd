---
phase: 15-content-addressed-caching
plan: "02"
subsystem: storage/extraction/ingestion
tags: [extraction-cache, gliner, ner, sqlite, content-addressed, model-invalidation]
dependency_graph:
  requires: [15-01]
  provides: [ExtractionCache, NERExtractor.extract_with_cache, pipeline._extraction_cache]
  affects:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/storage/cache.py
    - backend/src/dotmd/extraction/ner.py
    - backend/src/dotmd/ingestion/pipeline.py
tech_stack:
  added: []
  patterns:
    - blake2b-compound-cache-key
    - chunk-id-independent-cache-payload
    - model-sentinel-invalidation
    - extract-with-cache-wrapper
    - insert-or-ignore-idempotent
key_files:
  created: []
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/storage/cache.py
    - backend/src/dotmd/extraction/ner.py
    - backend/src/dotmd/ingestion/pipeline.py
decisions:
  - "ner_model_name as a top-level Settings field (not a constant) enables DOTMD_NER_MODEL_NAME env var and is accessible to pipeline for cache key derivation"
  - "model_sig = blake2b(model_name + entity_types_hash + str(threshold)) — threshold included so threshold changes trigger full cache clear (D-27)"
  - "Cached payload has no chunk_ids: entities stored as {name,type,source} only; MENTIONS rebuilt at read time from current chunk.chunk_id (chunk-id-independent, safe across Plan 03 migration)"
  - "ensure_table() creates tables only, never writes sentinel — ordering fix so should_invalidate() reads before any write (cannot self-compare)"
  - "extract_with_cache() wraps existing extract() — original unchanged; fallback to extract() when cache is None"
  - "CO_OCCURS per-chunk cache storage uses all CO_OCCURS from miss_result (batch-scoped dedup, same as extract() behavior)"
metrics:
  duration: "~15 min"
  completed: "2026-04-24"
  tasks: 3
  files: 4
---

# Phase 15 Plan 02: GLiNER Extraction Cache Summary

**One-liner:** SQLite extraction cache keyed on blake2b(chunk_text + model_name + entity_types + threshold) — GLiNER inference skipped for unchanged chunks after file moves, storing only chunk-id-independent entity/CO_OCCURS data.

## What Was Built

### Task 0 — ner_model_name in Settings

`ner_model_name: str = "urchade/gliner_multi-v2.1"` added to the `# Extraction` section of `Settings`. Configurable via `DOTMD_NER_MODEL_NAME` env var. Used by pipeline to derive the ExtractionCache model signature and to pass the correct model name to NERExtractor.

### Task 1 — ExtractionCache in storage/cache.py

`ExtractionCache` class appended to `cache.py` alongside `EmbeddingCache` (untouched). Two new SQLite tables:

- `extraction_cache` — PRIMARY KEY `cache_key` (blake2b hash), columns `entities_json` and `co_occurs_json` (separate, per D-28)
- `extraction_cache_meta` — single-row sentinel tracking current `model_sig`

Key design points:
- `model_sig = blake2b(model_name + entity_types_hash + str(threshold))` — all three dimensions included
- `ensure_table()` creates tables only; never writes sentinel (ordering fix from Codex review)
- `should_invalidate()` reads sentinel before any write — cannot self-compare
- `lookup_batch()` batches IN-clause queries (500 max), returns `(hits_dict, miss_chunks)`
- `store_batch()` uses `INSERT OR IGNORE`, no commit (caller commits)
- Cached payload is chunk-id-independent: entities have no `chunk_ids`, only CO_OCCURS stored (MENTIONS excluded)

### Task 2 — Wire into NERExtractor and IndexingPipeline

**ner.py:**
- `NERExtractor.__init__()` gains optional `extraction_cache` parameter stored as `self._extraction_cache`
- New `extract_with_cache()` method added before existing `extract()` (original untouched)
- Cache hit path: restores `Entity` objects from stored `{name, type, source}` dicts, rebuilds MENTIONS at read time using current `chunk.chunk_id`
- Cache miss path: calls `extract()` on miss chunks only, splits batch result into per-chunk payloads for cache storage

**pipeline.py:**
- `ExtractionCache` imported alongside `EmbeddingCache`
- `__init__()` instantiates `ExtractionCache` before `NERExtractor`, checks `should_invalidate()` first (reads sentinel), either clears or confirms sentinel, then passes cache to `NERExtractor`
- `_run_extraction()` calls `extract_with_cache()` instead of `extract()`

## Commits

| Task | Name | Commit | Key Files |
|------|------|--------|-----------|
| 0 | Add ner_model_name to Settings | ae0230e | backend/src/dotmd/core/config.py |
| 1 | Add ExtractionCache to storage/cache.py | c126390 | backend/src/dotmd/storage/cache.py |
| 2 | Wire ExtractionCache into NERExtractor + pipeline | 75e2885 | backend/src/dotmd/extraction/ner.py, backend/src/dotmd/ingestion/pipeline.py |

## Deviations from Plan

None — plan executed exactly as written.

## Threat Model Coverage

| Threat ID | Mitigation | Status |
|-----------|-----------|--------|
| T-15-02-02 | model_sig = blake2b(model_name + entity_types_hash + threshold) — mismatch triggers full clear | Implemented |
| T-15-02-03 | MENTIONS not stored in cache; rebuilt at read time from current chunk.chunk_id | Implemented |

## Known Stubs

None.

## Self-Check: PASSED

- `backend/src/dotmd/core/config.py` contains `ner_model_name`: FOUND
- `backend/src/dotmd/storage/cache.py` contains `class ExtractionCache`: FOUND
- `backend/src/dotmd/extraction/ner.py` contains `def extract_with_cache`: FOUND
- `backend/src/dotmd/ingestion/pipeline.py` contains `ExtractionCache` import + `extract_with_cache` call: FOUND
- Commit ae0230e exists: FOUND
- Commit c126390 exists: FOUND
- Commit 75e2885 exists: FOUND
- Full verification script: PASSED (all assertions, all 4 files parse as valid Python)
