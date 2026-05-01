---
phase: 18-multilingual-reranker
plan: "01"
subsystem: search
tags: [reranker, qwen3, cross-encoder, multilingual-search]
requires:
  - phase: 18-multilingual-reranker
    provides: external benchmark and deployment-fit reranker selection research
provides:
  - Qwen3 0.6B default reranker configuration
  - Optional raw-score reranker floor with fused-rank fallback
  - Mocked reranker and hybrid-search regression tests
affects: [search, configuration, documentation]
tech-stack:
  added: []
  patterns:
    - startup-configured reranker provider
    - non-fatal reranker fallback to fused ranking
key-files:
  created:
    - .planning/phases/18-multilingual-reranker/18-01-SUMMARY.md
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/search/reranker.py
    - backend/src/dotmd/api/service.py
    - backend/tests/test_reranker.py
    - backend/tests/test_hybrid_bm25.py
    - .env.example
    - README.md
    - docs/architecture.md
key-decisions:
  - "Selected model: Qwen/Qwen3-Reranker-0.6B"
  - "External benchmark rationale: selection is based on public benchmark, publication-age, and deployment-fit research, not a local dotMD eval harness"
  - "If reranker output is empty or unavailable, dotMD falls back to fused ranking"
patterns-established:
  - "Reranker raw-score filtering is opt-in via reranker_relevance_floor"
  - "Provider errors return no reranked candidates and let the service preserve fused results"
requirements-completed:
  - RERANK-SELECT-01
  - RERANK-SELECT-02
  - RERANK-SELECT-03
  - SCORE-01
duration: 12min
completed: 2026-05-01
---

# Phase 18 Plan 01: Implement Qwen3 0.6B Multilingual Reranker Summary

**Qwen3 0.6B is now the default configurable multilingual CrossEncoder reranker, with empty reranker output falling back to fused semantic/FTS5/graph ranking.**

## Performance

- **Duration:** 12 min
- **Started:** 2026-05-01T08:45:00Z
- **Completed:** 2026-05-01T08:57:26Z
- **Tasks:** 5
- **Files modified:** 8

## Accomplishments

- Selected model: Qwen/Qwen3-Reranker-0.6B.
- Added `reranker_backend`, `reranker_model`, and `reranker_relevance_floor` settings; `None` disables raw-score filtering by default.
- Preserved the local SentenceTransformers CrossEncoder provider path and made provider failures non-fatal.
- Changed service rerank handling so empty reranker output logs `reranker returned no candidates; falling back to fused ranking` and preserves fused results.
- Updated mocked tests for chunk ID score mapping, optional score floor behavior, and empty-rerank fallback.
- Updated `.env.example`, `README.md`, and `docs/architecture.md` with the Qwen3 decision and fallback behavior.

## External Benchmark Rationale

Qwen/Qwen3-Reranker-0.6B won as the first implementation target because the public research ranked it as fresh enough for May 2026 default selection, multilingual, text-only, 0.6B, and documented through SentenceTransformers CrossEncoder usage. ContextualAI rerank-v2 and Jina v3 remain real alternates if Qwen integration or latency fails. Alibaba-NLP/gte-multilingual-reranker-base and BGE are fallback-only because their age disqualifies them from default selection despite easier operational fit.

No local quality benchmark harness, eval-set preparation, or model bake-off was implemented.

## Task Commits

1. **Tasks 1-3 and focused tests:** `3dcdeff` (`feat(18-01): implement qwen3 reranker defaults`)
2. **Task 4 docs/env:** not committed separately because `.env.example`, `README.md`, and `docs/architecture.md` already contained pre-existing uncommitted cleanup changes in this worktree
3. **Task 5 summary and tracking:** this metadata commit (`docs(18-01): complete qwen3 reranker plan`)

## Commands Run

```bash
cd backend && uv run pytest tests/test_reranker.py -q
cd backend && uv run pytest tests/test_hybrid_bm25.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py tests/test_reranker.py tests/test_hybrid_bm25.py
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py -q
```

Result: all focused checks passed. The pytest run emitted existing pydantic-settings `toml_file` warnings.

## Optional Provider Smoke

Skipped. This plan kept the local CrossEncoder path and did not add or configure an HTTP rerank service, so there was no `DOTMD_RERANKER_URL/rerank` endpoint to smoke.

## Files Created/Modified

- `backend/src/dotmd/core/config.py` - Qwen3 default reranker settings and empty env parsing for optional floor.
- `backend/src/dotmd/search/reranker.py` - chunk ID order preservation, optional relevance floor, and provider-error fallback.
- `backend/src/dotmd/api/service.py` - startup provider boundary and empty-rerank fused fallback.
- `backend/tests/test_reranker.py` - mocked CrossEncoder tests for ordering, score mapping, and floor behavior.
- `backend/tests/test_hybrid_bm25.py` - regression test for empty reranker output preserving fused results.
- `.env.example` - Qwen3 reranker env examples.
- `README.md` - selected model, publication-age rationale, and fused fallback docs.
- `docs/architecture.md` - selected provider and non-fatal reranker behavior.

## Decisions Made

- Keep `reranker_backend="cross_encoder"` as the only supported provider boundary for now.
- Do not add an HTTP reranker path before a concrete serving target exists.
- Do not apply a default raw-score floor because Qwen3 score semantics should not inherit the old MS MARCO zero-logit assumption.
- Treat empty reranker output as a provider/filtering failure mode, not as proof that the search has no relevant fused candidates.

## Deviations from Plan

None - plan executed within the requested scope. The only workflow deviation was commit granularity: docs/env changes were left uncommitted because those files already had unrelated uncommitted edits before phase execution.

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No behavioral scope change.

## Issues Encountered

- The new empty-rerank service test initially returned no final results because the test fixture did not hydrate chunks by fused chunk ID. The fixture was corrected to return real `Chunk` objects for `s1` and `b1`.
- The installed `gsd-sdk` rejected the documented compatibility command for clearing `workflow._auto_chain_active`; the config already had that value set to `false`, so execution continued.

## User Setup Required

None - no external service configuration required for the local CrossEncoder path.

## Next Phase Readiness

Phase 18 delivers the Qwen3 default path and preserves fused results when reranking fails or filters everything. Production still needs an operational latency/serving smoke before treating Qwen3 CPU behavior as validated on the target host.

---
*Phase: 18-multilingual-reranker*
*Completed: 2026-05-01*
