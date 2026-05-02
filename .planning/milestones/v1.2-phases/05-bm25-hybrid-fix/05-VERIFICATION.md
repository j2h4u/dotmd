---
phase: 05-bm25-hybrid-fix
verified: 2026-03-27T04:15:00Z
status: passed
score: 5/5 must-haves verified
re_verification: false
---

# Phase 5: BM25 Hybrid Fix Verification Report

**Phase Goal:** BM25 keyword matches survive the scoring pipeline and appear in hybrid search results
**Verified:** 2026-03-27T04:15:00Z
**Status:** passed
**Re-verification:** No -- initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|-------|--------|----------|
| 1 | BM25-only matches are not filtered by the cross-encoder reranker | VERIFIED | `reranker.py` has no `score_threshold` parameter, no threshold comparison, list comprehension has no `if` filter clause (lines 129-132). Test `test_all_candidates_returned_regardless_of_score` passes proving all 5 candidates survive including score -20.0 |
| 2 | All RRF fusion candidates survive through reranking to the final result list | VERIFIED | `service.py` merge-back loop at lines 229-235 appends unscored candidates. Test `test_candidates_beyond_pool_size_preserved` passes proving >20 candidates survive when pool_size=20 |
| 3 | Reranker reorders candidates by cross-encoder score without applying any score threshold | VERIFIED | `reranker.py` line 133: `scored.sort(key=lambda x: x[1], reverse=True)` followed by `return scored[:top_k]`. No threshold filter exists anywhere in the file. `grep score_threshold backend/src/dotmd/` returns 0 matches |
| 4 | Fusion candidates not scored by the reranker (due to pool_size) retain their fusion score in the final list | VERIFIED | `service.py` line 235: `blended.append((cid, 0.4 * norm_f))` gives fusion-only weight to unscored candidates. `fused_scores` dict (line 204) indexes ALL fused results, not just pool_size |
| 5 | Diagnostic logging reports how many BM25-only matches survived reranking | VERIFIED | `service.py` lines 245-252: `logger.debug("Reranked %d candidates ... %d BM25-only matches in final list", ...)`. Test `test_bm25_survival_logged_at_debug` passes proving log message emitted |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|----------|----------|--------|---------|
| `backend/src/dotmd/search/reranker.py` | Cross-encoder reranker without score threshold filter | VERIFIED | Contains `scored.sort(key=lambda` (line 133), no `score_threshold` anywhere in file, no `if` filter in list comprehension |
| `backend/src/dotmd/core/config.py` | Settings without rerank_score_threshold | VERIFIED | `grep rerank_score_threshold` returns 0 matches. Setting fully removed |
| `backend/src/dotmd/api/service.py` | Blend + merge-back logic preserving all fusion candidates | VERIFIED | Contains `reranked_ids` (line 231), merge-back loop (lines 232-235), fusion-only score assignment, BM25 diagnostic logging |
| `backend/tests/test_reranker.py` | Unit tests for reranker without threshold filtering | VERIFIED | 5 test methods, all passing. Tests no-filter behavior, top_k truncation, empty input, rejected score_threshold param, removed config setting |
| `backend/tests/test_hybrid_bm25.py` | Integration test for BM25 survival through hybrid pipeline | VERIFIED | 3 test methods, all passing. Tests merge-back beyond pool_size, BM25-only survival with low reranker score, diagnostic logging |

### Key Link Verification

| From | To | Via | Status | Details |
|------|----|-----|--------|---------|
| `reranker.py` | `service.py` | `Reranker.rerank()` returns all scored candidates (no filtering) | WIRED | `service.py` line 19: `from dotmd.search.reranker import Reranker`; line 64-68: constructor call without `score_threshold`; line 205: `self._reranker.rerank(...)` |
| `service.py` | `fusion.py` | Merge-back appends unscored fusion candidates after blending | WIRED | `fused_scores` indexes all fused results (line 204), merge-back loop iterates `fused` (line 232), appends to `blended` (line 235), re-sorts (line 237), replaces `fused` (line 238) |

### Data-Flow Trace (Level 4)

Not applicable -- this phase modifies the scoring pipeline logic, not a data-rendering artifact.

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|----------|---------|--------|--------|
| All 8 phase tests pass | `uv run python -m pytest tests/test_reranker.py tests/test_hybrid_bm25.py -v` | 8 passed in 5.29s | PASS |
| Full suite (65 tests) no regressions | `uv run python -m pytest tests/ -v` | 65 passed in 7.91s | PASS |
| score_threshold fully removed from source | `grep -r score_threshold backend/src/dotmd/` | 0 matches | PASS |
| reranked_ids merge-back present | `grep reranked_ids backend/src/dotmd/api/service.py` | 2 matches (lines 231, 233) | PASS |
| BM25-only diagnostic logging present | `grep "BM25-only" backend/src/dotmd/api/service.py` | 1 match (line 247) | PASS |
| Commit 96f6ef1 (Task 1) exists | `git show 96f6ef1 --stat` | 4 files changed, 101 insertions | PASS |
| Commit d09fb08 (Task 2) exists | `git show d09fb08 --stat` | 2 files changed, 218 insertions | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|-------------|------------|-------------|--------|----------|
| SEARCH-01 | 05-01-PLAN | BM25 results appear in hybrid search mode (diagnose reranker threshold issue, fix scoring pipeline) | SATISFIED | Score threshold removed (reranker.py), merge-back logic added (service.py), 8 tests proving BM25 survival, 0 regressions in full suite |

No orphaned requirements. REQUIREMENTS.md maps SEARCH-01 to Phase 5 (line 20, marked complete on line 52). Plan 05-01 declares `requirements: [SEARCH-01]`. Full alignment.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|------|------|---------|----------|--------|
| reranker.py | 102, 106 | `return []` | Info | Legitimate guard clauses for empty input (no chunk_ids, no chunks from store). Not stubs |

No TODOs, FIXMEs, placeholders, or stub implementations found in any modified file.

### Human Verification Required

### 1. Empirical BM25 Hybrid Search

**Test:** Run `dotmd search --mode hybrid "some specific keyword"` against the production index and verify results include entries with `bm25` in `matched_engines`.
**Expected:** At least one result shows BM25 attribution, confirming the fix works end-to-end with real data.
**Why human:** Requires a running service with indexed data. Unit tests mock the engines; real-world confirmation needs actual BM25 index and semantic embeddings.

### 2. Result Quality Sanity

**Test:** Compare hybrid search results before and after the fix for a query that was previously missing BM25 matches.
**Expected:** Results are more complete (BM25 matches appear) without degrading relevance ordering for semantic-heavy queries.
**Why human:** Relevance quality is subjective and requires domain knowledge of the indexed content.

### Gaps Summary

No gaps found. All 5 observable truths verified. All 5 artifacts pass existence, substantive, and wiring checks. Both key links verified. SEARCH-01 requirement satisfied. Full test suite (65 tests) passes with zero regressions. Both commits (96f6ef1, d09fb08) verified in git history.

---

_Verified: 2026-03-27T04:15:00Z_
_Verifier: Claude (gsd-verifier)_
