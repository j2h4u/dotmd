# Phase 5: BM25 Hybrid Fix - Research

**Researched:** 2026-03-27
**Domain:** Search pipeline scoring / cross-encoder reranking
**Confidence:** HIGH

## Summary

The BM25 hybrid fix is a well-scoped bug fix in the search scoring pipeline. The root cause is confirmed by code inspection: two failure points act in series to eliminate BM25-only matches from hybrid search results.

**Failure point 1** (reranker.py:131): The `Reranker.rerank()` method applies a hard score threshold (`score >= -8.0`) that filters out any chunk scoring below -8.0 from the cross-encoder. BM25-only matches (chunks with keyword overlap but no semantic similarity) routinely get low or negative cross-encoder scores because ms-marco-MiniLM-L-6-v2 outputs raw logits with an unbounded range (verified: typical relevant score ~8.6, typical irrelevant score ~-4.3 from official HuggingFace model card examples). For truly keyword-only matches with no semantic relation to the query, scores can easily fall below -8.0.

**Failure point 2** (service.py:229): After reranking, `fused = blended` completely replaces the RRF fusion list with only the survivors from the reranker. Any chunk that was filtered by the threshold in failure point 1 is permanently lost -- it will never appear in `build_search_results()`.

The fix is straightforward: remove the threshold filter from the reranker (it should reorder, not filter), and ensure all RRF fusion candidates survive through to the final result list even if they were not scored by the reranker. Industry consensus from multiple sources confirms that cross-encoder rerankers should reorder a candidate set, never reduce it.

**Primary recommendation:** Remove the score threshold from `Reranker.rerank()`, then merge back any fusion candidates that the reranker did not include (e.g., due to pool_size limits) so no RRF candidate is silently dropped.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions
- **D-01:** Remove the hard score threshold (`-8.0`) from `Reranker.rerank()`. The reranker must reorder results, never filter them. This is the primary cause of BM25 result loss.
- **D-02:** All fusion candidates must survive through reranking. If a candidate from the RRF fusion list is not scored by the reranker (or scores poorly), it should remain in the final list with its original fusion score -- not be silently dropped.
- **D-03:** Keep current blend weights (0.4 fusion + 0.6 reranker) unchanged. No evidence to justify changing them. Revisit only if BM25 results still rank too low after the threshold fix.
- **D-04:** No env-var configurability for thresholds or weights. YAGNI. SEARCH-F2 stays in future requirements.
- **D-05:** Add diagnostic logging to confirm the hypothesis (log BM25 results before/after reranker) as part of the fix -- not as a separate step.

### Claude's Discretion
- Specific implementation approach for preserving fusion candidates through reranking (merge-back, floor score, or other mechanism)
- Test design and validation queries
- Logging format and verbosity

### Deferred Ideas (OUT OF SCOPE)
- Reranker model evaluation (ms-marco-MiniLM-L-6-v2 domain suitability)
- SEARCH-F2: Configurable reranker threshold via env var
- Blend weight tuning
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SEARCH-01 | BM25 results appear in hybrid search mode (diagnose reranker threshold issue, fix scoring pipeline) | Root cause confirmed by code analysis: threshold filter at reranker.py:131 + total replacement at service.py:229. Fix approach validated by IR best practices (rerankers reorder, not filter). |
</phase_requirements>

## Architecture Patterns

### Current Search Pipeline Flow (Hybrid Mode)
```
query --> expand --> [semantic, bm25, graph] --> RRF fuse --> rerank --> blend --> build_search_results --> top-K
```

### Where the Bug Lives
```
reranker.py:128-132    # Threshold filter removes BM25-only matches
    scored = [
        (cid, float(score))
        for (cid, _text), score in zip(id_text_pairs, scores)
        if score >= self._score_threshold    <-- THIS LINE
    ]

service.py:229         # Total replacement loses unscored candidates
    fused = blended                          <-- THIS LINE
```

### Recommended Fix Pattern: Merge-Back

The cleanest approach to satisfy D-01 and D-02 is a two-part fix:

**Part 1 -- Reranker (reranker.py):** Remove the `score >= self._score_threshold` filter entirely. The reranker should score all candidates and return them sorted by score. Keep the `top_k` truncation (it limits how many candidates the cross-encoder processes, which is a performance concern, not a relevance concern).

**Part 2 -- Service blend (service.py):** After blending reranked results, merge back any fusion candidates that were not in the reranked set (due to pool_size truncation). These merge-back candidates keep their original fusion score, normalized to the same 0-1 scale used by blended results. They appear at the bottom of the list (below all reranked results) since they have lower-confidence scores.

```python
# Pseudocode for merge-back approach:
reranked_ids = {cid for cid, _ in blended}
for cid, fused_score in fused:
    if cid not in reranked_ids:
        # Normalize fusion score to same scale, place below reranked
        norm_f = (fused_score - f_min) / f_range
        blended.append((cid, 0.4 * norm_f))  # 0.6 * 0.0 reranker component
blended.sort(key=lambda x: x[1], reverse=True)
fused = blended
```

This ensures:
- No fusion candidate is ever silently dropped
- Reranked candidates always rank above non-reranked ones (they get both fusion + reranker score components)
- BM25-only matches that survive the cross-encoder (most will, without the threshold) get properly blended scores

### Anti-Patterns to Avoid
- **Floor score approach:** Assigning a minimum score to filtered-out candidates adds complexity without benefit. If the threshold is removed, there is nothing to floor.
- **Disabling reranking for BM25 results:** This defeats the purpose of the cross-encoder. BM25 results should be reranked, they just should not be filtered.
- **Separate score pipelines per engine:** Breaks the unified fusion model. All engines feed into one RRF, one reranker, one blend.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Score normalization | Custom normalization logic | Min-max normalization (already in codebase) | Existing pattern at service.py:213-220 works correctly |
| Cross-encoder scoring | Custom relevance model | sentence-transformers CrossEncoder (already used) | Well-tested, industry standard |

## Common Pitfalls

### Pitfall 1: Reranker top_k vs service pool_size confusion
**What goes wrong:** The reranker's `top_k` parameter and the service's `pool_size` (from `rerank_pool_size` setting, default 20) interact. If pool_size sends 20 candidates to the reranker but there were 30 RRF fusion results, 10 candidates are never scored by the reranker.
**Why it happens:** `fused[:pool_size]` in service.py:203 truncates before passing to reranker.
**How to avoid:** The merge-back pattern handles this explicitly. Candidates beyond pool_size keep their fusion scores. This is an existing limitation (not introduced by this fix) -- the merge-back just makes it visible and correct.
**Warning signs:** If `len(fused) > pool_size`, some candidates will only have fusion scores.

### Pitfall 2: Min-max normalization edge case with single result
**What goes wrong:** If only one candidate survives reranking, `re_max == re_min`, and `re_range` becomes the fallback `1.0`. The normalized score becomes `(score - score) / 1.0 = 0.0`, making the reranker component contribute nothing.
**Why it happens:** Single-result edge case in normalization math.
**How to avoid:** The existing code already handles this with `re_range = re_max - re_min if re_max > re_min else 1.0`. This is acceptable -- with only one result, relative ordering doesn't matter. No change needed.
**Warning signs:** Search returning exactly 1 result should still work correctly.

### Pitfall 3: Logging too much in hot path
**What goes wrong:** Adding verbose logging inside the reranking loop (per-candidate scores) creates noise and slows down search.
**Why it happens:** D-05 asks for diagnostic logging, which could be over-implemented.
**How to avoid:** Use `logger.debug()` for per-candidate detail. Use `logger.info()` only for summary (e.g., "Reranked 20 candidates, BM25-only: 5"). Debug-level logging is off by default and only visible with `--verbose`.
**Warning signs:** Log output overwhelming the actual search results in CLI.

### Pitfall 4: Breaking the `score_threshold` constructor parameter
**What goes wrong:** The `Reranker.__init__()` accepts `score_threshold` and `Settings.rerank_score_threshold` exists. Removing the filter but leaving the parameter creates dead code.
**Why it happens:** The threshold was configurable but the decision (D-04) says no env-var configurability.
**How to avoid:** Remove the `score_threshold` parameter from `Reranker.__init__()`, remove `rerank_score_threshold` from `Settings`, and update `DotMDService.__init__()` which passes it. Clean removal, no dead code.
**Warning signs:** Grep for `score_threshold` and `rerank_score_threshold` -- all references must be removed.

## Code Examples

### Current reranker filter (to be removed)
```python
# reranker.py:128-132 -- CURRENT (broken)
scored = [
    (cid, float(score))
    for (cid, _text), score in zip(id_text_pairs, scores)
    if score >= self._score_threshold  # <-- removes BM25-only matches
]
```

### Fixed reranker (no filter)
```python
# reranker.py -- FIXED: score all candidates, no threshold
scored = [
    (cid, float(score))
    for (cid, _text), score in zip(id_text_pairs, scores)
]
scored.sort(key=lambda x: x[1], reverse=True)
return scored[:top_k]
```

### Diagnostic logging (D-05)
```python
# service.py -- inside the reranking block, after getting reranked results
if reranked:
    bm25_only_ids = {cid for cid, _ in bm25_hits} - {cid for cid, _ in semantic_hits}
    bm25_in_reranked = [(cid, s) for cid, s in reranked if cid in bm25_only_ids]
    logger.debug(
        "Reranked %d candidates; %d BM25-only matches survived",
        len(reranked),
        len(bm25_in_reranked),
    )
```

### Merge-back for non-reranked fusion candidates
```python
# service.py -- after blending, before fused = blended
reranked_ids = {cid for cid, _ in blended}
for cid, fused_score in fused:
    if cid not in reranked_ids:
        norm_f = (fused_score - f_min) / f_range
        blended.append((cid, 0.4 * norm_f))
blended.sort(key=lambda x: x[1], reverse=True)
fused = blended
```

## Files to Modify

| File | Change | Lines |
|------|--------|-------|
| `backend/src/dotmd/search/reranker.py` | Remove score threshold filter, remove `score_threshold` param | 44, 50, 128-132 |
| `backend/src/dotmd/api/service.py` | Add merge-back logic, add diagnostic logging, remove threshold kwarg | 64-69, 201-229 |
| `backend/src/dotmd/core/config.py` | Remove `rerank_score_threshold` setting | 63 |

**Files NOT to modify** (confirmed working correctly):
- `search/bm25.py` -- BM25 engine works correctly
- `search/fusion.py` -- RRF fusion and `build_search_results()` work correctly
- `core/models.py` -- `SearchResult.matched_engines` already handles BM25 attribution

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Cross-encoder as filter (threshold cutoff) | Cross-encoder as reorderer only | Always was best practice, but codebases often add thresholds as premature optimization | Removing threshold improves recall without hurting precision (reranker still reorders) |
| Single-stage fusion | Two-stage: fusion + reranker blend | Standard since ~2023 | Already implemented correctly except for the threshold bug |

**Key insight from IR literature:** The ms-marco-MiniLM-L-6-v2 cross-encoder outputs raw logits (not probabilities). The score range is unbounded -- official examples show +8.6 for relevant and -4.3 for irrelevant pairs. Using a fixed threshold like -8.0 on raw logits is fundamentally wrong because the distribution shifts with query/corpus characteristics. The correct use is relative ordering within a candidate set.

## Open Questions

1. **How many BM25-only matches typically exist in hybrid results?**
   - What we know: BM25 returns keyword matches that may have zero semantic overlap with the query embedding
   - What's unclear: In the production dotMD corpus (markdown knowledgebase), what fraction of BM25 hits are BM25-only vs also matched semantically?
   - Recommendation: The diagnostic logging (D-05) will answer this empirically. No action needed pre-implementation.

2. **Will removing the threshold cause low-quality results to appear?**
   - What we know: The threshold was likely added to filter truly irrelevant results. With a pool_size of 20 and top_k of 10, the reranker processes 20 candidates and the user sees 10.
   - What's unclear: Whether removing the threshold will surface noisy results in the top 10.
   - Recommendation: Unlikely to be a problem. RRF fusion already filters by rank (low-ranked candidates have tiny RRF scores). The cross-encoder reorders correctly even without filtering. If noise appears, it belongs in blend weight tuning (deferred per D-03).

## Sources

### Primary (HIGH confidence)
- [HuggingFace model card: cross-encoder/ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) - Score range (raw logits, unbounded), example values (+8.6 relevant, -4.3 irrelevant)
- [Sentence-Transformers docs: MS MARCO Cross-Encoders](https://www.sbert.net/docs/pretrained-models/ce-msmarco.html) - Model performance benchmarks, usage patterns
- Direct codebase analysis of reranker.py, service.py, fusion.py, bm25.py, config.py, models.py

### Secondary (MEDIUM confidence)
- [DEV.to: Integrating BM25 in Hybrid Search and Reranking Pipelines](https://dev.to/negitamaai/integrating-bm25-in-hybrid-search-and-reranking-pipelines-strategies-and-applications-4joi) - Industry patterns for BM25 + reranker integration
- [VectorHub: Optimizing RAG with Hybrid Search & Reranking](https://superlinked.com/vectorhub/articles/optimizing-rag-with-hybrid-search-reranking) - Best practices for cross-encoder in hybrid pipelines
- [ZeroEntropy: Ultimate Guide to Choosing the Best Reranking Model in 2026](https://www.zeroentropy.dev/articles/ultimate-guide-to-choosing-the-best-reranking-model-in-2025) - Current reranker landscape

## Metadata

**Confidence breakdown:**
- Root cause analysis: HIGH - Confirmed by direct code reading, two failure points identified with exact line numbers
- Fix approach: HIGH - Industry consensus (rerankers reorder, not filter) + straightforward code change
- Pitfalls: HIGH - Edge cases identified from existing code patterns (normalization, pool_size truncation)

**Research date:** 2026-03-27
**Valid until:** 2026-04-27 (stable domain, no moving parts)
