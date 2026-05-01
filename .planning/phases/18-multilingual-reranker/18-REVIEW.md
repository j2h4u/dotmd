---
phase: 18-multilingual-reranker
reviewed: 2026-05-01T09:01:45Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - .env.example
  - README.md
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/search/reranker.py
  - backend/tests/test_hybrid_bm25.py
  - backend/tests/test_reranker.py
  - docs/architecture.md
findings:
  critical: 1
  warning: 1
  info: 0
  total: 2
status: issues_found
---

# Phase 18: Code Review Report

**Reviewed:** 2026-05-01T09:01:45Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the multilingual reranker configuration, service integration, reranker implementation, tests, and documentation. The main correctness issue is in the reranker score adjustment path: default length penalty boosts short chunks when the model emits negative scores, which is now an expected path because the Phase 18 default keeps low and negative raw scores instead of filtering them. A secondary observability defect records fallback searches as reranked.

Focused tests were run with `cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py`; they passed, but the negative-score length-penalty case is not covered.

## Critical Issues

### CR-01: BLOCKER - Length Penalty Boosts Short Chunks With Negative Scores

**File:** `backend/src/dotmd/search/reranker.py:145`

**Issue:** The default reranker now preserves negative scores (`reranker_relevance_floor=None`), and tests explicitly assert that negative scores survive. With `reranker_length_penalty=True` by default, the penalty code multiplies scores by a factor between `0.8` and `1.0`. That downranks positive scores, but it up-ranks negative scores because `-10 * 0.8 == -8`. Short, low-relevance chunks therefore become more relevant than longer chunks with the same raw score, which is the opposite of the documented behavior and a search ranking regression for the new default model path.

**Fix:**

Use a penalty that always lowers rank regardless of score sign, or apply the factor in normalized score space. For a local fix in this class:

```python
if text_length < self._min_length:
    penalty = 0.2 * (1.0 - (text_length / self._min_length))
    score = score - penalty
```

Add a test with `length_penalty=True` and negative model scores where the shorter chunk must sort below an otherwise equal longer chunk.

## Warnings

### WR-01: WARNING - Search Log Marks Fallback Results As Reranked

**File:** `backend/src/dotmd/api/service.py:401`

**Issue:** `_reranked = rerank and bool(self._reranker)` is true whenever reranking was requested and the service has a reranker object. After the Phase 18 fallback change, `_reranker.rerank(...)` can return `[]` on provider failure or when an optional relevance floor removes all candidates, and the service correctly falls back to fused ranking. The search log still records `reranked=True`, so operational telemetry and future calibration data cannot distinguish actual reranked results from fallback results.

**Fix:** Track whether reranker scores were actually applied and pass that to `log_search`.

```python
reranked_applied = False
if rerank and fused:
    reranked = self._reranker.rerank(...)
    if reranked:
        reranked_applied = True
        ...

self._pipeline.log_search(
    ...,
    reranked=reranked_applied,
)
```

Add a test for the existing empty-reranker fallback case that asserts `log_search(..., reranked=False)`.

---

_Reviewed: 2026-05-01T09:01:45Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
