---
phase: 15-content-addressed-caching
slug: content-addressed-caching
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06T20:08:34+05:00
validation_state: reconstructed-from-summaries
gaps_found: 3
gaps_resolved: 3
manual_only: 0
---

# Phase 15 — Validation Strategy

> Retroactive Nyquist validation for the completed content-addressed caching phase.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/storage/test_cache.py -q` |
| Full phase command | `cd backend && uv run pytest tests/storage/test_cache.py tests/ingestion/test_chunker.py tests/ingestion/test_pipeline_m2m_insert.py tests/test_incremental_pipeline.py -q` |
| Lint command | `cd backend && uv run ruff check tests/storage/test_cache.py && uv run ruff format --check tests/storage/test_cache.py` |
| Estimated runtime | about 5 seconds |

## Discovery

Phase 15 had no pre-existing `15-VALIDATION.md`, so this file reconstructs the validation contract from:

- `15-01-PLAN.md` and `15-01-SUMMARY.md`
- `15-02-PLAN.md` and `15-02-SUMMARY.md`
- `15-03-PLAN.md` and `15-03-SUMMARY.md`
- `15-VERIFICATION.md`
- Current cache, NER, pipeline, and chunker implementation

## Gap Analysis

| Requirement | Original Gap | Resolution |
|-------------|--------------|------------|
| CACHE-01 | No direct unit test for `EmbeddingCache` model scoping, sentinel invalidation, and lookup/store behavior. | Added `test_embedding_cache_is_model_scoped_and_invalidates_on_model_change` in `backend/tests/storage/test_cache.py`. |
| CACHE-02 | No direct unit test for `ExtractionCache` signature scoping, chunk-id-independent payload shape, cached `MENTIONS` rebuild, or partial miss behavior. | Added three focused extraction-cache/NER cache tests in `backend/tests/storage/test_cache.py`. |
| CACHE-03 | Existing chunker/M2M tests covered current behavior indirectly, but no direct assertion that identical content across paths keeps the same chunk id while strategy changes alter it. | Added `test_chunk_ids_are_path_independent_and_strategy_scoped` in `backend/tests/storage/test_cache.py`. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| 15-01-01 | 01 | 1 | CACHE-01 | `embedding_cache` stores vectors by `(text_hash, model_name)`, does not cross-use models, and invalidates when the model sentinel changes. | unit | `cd backend && uv run pytest tests/storage/test_cache.py -q` | yes | green |
| 15-02-01 | 02 | 2 | CACHE-02 | `extraction_cache` stores separate `entities_json` and `co_occurs_json`, invalidates on model/entity/threshold signature changes, and stores no `relations_json` payload. | unit | `cd backend && uv run pytest tests/storage/test_cache.py -q` | yes | green |
| 15-02-02 | 02 | 2 | CACHE-02 | `NERExtractor.extract_with_cache()` rebuilds `MENTIONS` from the current chunk id when cached rows are reused after chunk-id changes. | unit | `cd backend && uv run pytest tests/storage/test_cache.py -q` | yes | green |
| 15-02-03 | 02 | 2 | CACHE-02 | Partial cache hits run NER only for miss chunks. | unit | `cd backend && uv run pytest tests/storage/test_cache.py -q` | yes | green |
| 15-03-01 | 03 | 3 | CACHE-03 | Chunk IDs are path-independent, 64-character BLAKE3 hexdigests, and strategy-scoped. | unit | `cd backend && uv run pytest tests/storage/test_cache.py -q` | yes | green |
| 15-03-02 | 03 | 3 | CACHE-03 | Later M2M/shared-chunk behavior still preserves shared content across paths. | regression | `cd backend && uv run pytest tests/ingestion/test_chunker.py tests/ingestion/test_pipeline_m2m_insert.py tests/test_incremental_pipeline.py -q` | yes | green |

## Wave 0 Requirements

Existing pytest infrastructure was already present. Wave 0 is considered reconstructed and complete because `backend/tests/storage/test_cache.py` now covers all missing Phase 15 validation references.

## Manual-Only Verifications

All current Phase 15 closure behavior has automated verification.

Historical note: Phase 15 Plan 03 originally included an operator checkpoint for `migration_v15.py`. That migration path was superseded by Phase 16's M2M migration and is not treated as a current manual-only validation requirement.

## Commands Run

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/storage/test_cache.py -q` | PASS: 5 passed |
| `cd backend && uv run pytest tests/storage/test_cache.py tests/ingestion/test_chunker.py tests/ingestion/test_pipeline_m2m_insert.py tests/test_incremental_pipeline.py -q` | PASS: 24 passed |
| `cd backend && uv run ruff check tests/storage/test_cache.py && uv run ruff format --check tests/storage/test_cache.py` | PASS |

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 3 |
| Resolved | 3 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or reconstructed Wave 0 coverage
- [x] Sampling continuity restored retroactively
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 10 seconds for the focused phase suite
- [x] `nyquist_compliant: true` set in frontmatter

Approval: approved 2026-05-06
