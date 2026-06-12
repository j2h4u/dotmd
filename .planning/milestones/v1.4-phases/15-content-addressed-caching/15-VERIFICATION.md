---
phase: 15-content-addressed-caching
verified: 2026-05-06T19:56:26+05:00
status: passed
score: 88
---

# Phase 15 Verification: Content-Addressed Caching

## Goal Achievement

**Goal:** Prevent expensive reindexing (GLiNER + TEI) when files move or mount paths change by adding embedding cache, extraction cache, and content-based chunk IDs/migration support.

**Result:** PASSED, with supersession noted.

Phase 15 delivered durable embedding and extraction caches, path-independent chunk ID generation, and the migration plan/artifacts that were later superseded by the Phase 16 many-to-many content-addressed schema. The current codebase keeps the durable cache and path-independent chunking behavior; the standalone Phase 15 migration script is no longer present because the later Phase 16 migration became the active migration path.

## Observable Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| Embedding cache exists and is model-scoped | VERIFIED | `backend/src/dotmd/storage/cache.py:31` defines `EmbeddingCache`; `backend/src/dotmd/ingestion/pipeline.py:282` wires it with `settings.embedding_model`. |
| Embedding cache invalidates on model changes | VERIFIED | `backend/src/dotmd/storage/cache.py:83` implements `should_invalidate()`; `backend/src/dotmd/ingestion/pipeline.py:283` clears/updates the cache sentinel when needed. |
| Extraction cache exists and is model/signature-scoped | VERIFIED | `backend/src/dotmd/storage/cache.py:185` defines `ExtractionCache`; `backend/src/dotmd/ingestion/pipeline.py:259` wires it into NER extraction. |
| Extraction cache is used before GLiNER extraction | VERIFIED | `backend/src/dotmd/extraction/ner.py:85` checks cache availability; `backend/src/dotmd/extraction/ner.py:88` calls `lookup_batch()`; `backend/src/dotmd/extraction/ner.py:166` stores miss results. |
| Chunk IDs are path-independent and content/strategy addressed | VERIFIED | `backend/src/dotmd/ingestion/chunker.py:23` defines `_make_chunk_id(body_checksum, chunk_index, chunk_strategy)`, and chunk creation calls it with body checksum and strategy. |
| Later M2M behavior preserves shared chunks across paths | VERIFIED | Current regression tests for M2M/shared-chunk behavior pass. |

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| Plan 01 summary | VERIFIED | `15-01-SUMMARY.md` records `EmbeddingCache` implementation and pipeline wiring. |
| Plan 02 summary | VERIFIED | `15-02-SUMMARY.md` records `ExtractionCache`, NER wrapper, and pipeline wiring. |
| Plan 03 summary | VERIFIED WITH SUPERSESSION | `15-03-SUMMARY.md` records content-addressed chunk ID migration work and checkpoint; Phase 16 superseded the migration path where needed. |
| Current implementation | VERIFIED | Cache/chunker code remains present in the current codebase. |

## Key Link Verification

`IndexingPipeline` wires both cache layers during initialization. Embedding work checks local vector metadata first, then the global embedding cache, and only then calls the semantic encoder. NER extraction routes through `NERExtractor.extract_with_cache()`, which rebuilds chunk mentions from current chunk IDs so cached extraction payloads remain path-independent.

## Requirements Coverage

Phase 15 has no current `REQUIREMENTS.md` IDs. The roadmap goal is satisfied by durable cache behavior and the later Phase 16 schema supersession for migration/storage shape.

## Anti-Patterns Checked

| Anti-pattern | Result |
|--------------|--------|
| Cache keyed only by path | ABSENT; embedding and extraction caches use content/model-derived keys. |
| Cross-model embedding reuse | ABSENT; embedding cache is scoped by model name. |
| Chunk identity tied to moved file path | ABSENT in current chunker; IDs derive from checksum/index/strategy. |
| Stale migration path treated as active production code | ABSENT; supersession by Phase 16 is explicitly noted. |

## Human Verification Required

None for current phase closure. The old Phase 15 Plan 03 operator checkpoint is historical and superseded by Phase 16's M2M migration path.

## Gaps Summary

No blocking gaps remain for milestone traceability. Historical caveat: `backend/src/dotmd/ingestion/migration_v15.py` is no longer present in the current tree, so verification is against the durable behavior that remains plus the recorded Phase 15 summaries.

## Verification Metadata

- Verification type: retroactive goal-backward phase verification
- Evidence checked: Phase 15 summaries, current cache/chunker/pipeline code, current M2M regression tests
- Current checks run:
  - PASS: `cd backend && uv run pytest tests/ingestion/test_chunker.py tests/ingestion/test_pipeline_m2m_insert.py tests/test_incremental_pipeline.py -q` (`19 passed`)

