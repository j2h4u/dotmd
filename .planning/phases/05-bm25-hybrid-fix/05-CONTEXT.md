# Phase 5: BM25 Hybrid Fix - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Fix the hybrid search scoring pipeline so that BM25 keyword matches survive reranking and appear in final search results. BM25-only matches (chunks matching keywords but not semantically) must not be filtered or buried by the cross-encoder reranker.

</domain>

<decisions>
## Implementation Decisions

### Reranker Role (Expert Panel — unanimous)
- **D-01:** Remove the hard score threshold (`-8.0`) from `Reranker.rerank()`. The reranker must reorder results, never filter them. This is the primary cause of BM25 result loss. Industry consensus: cross-encoder rerankers reorder a candidate set, they don't reduce it.
- **D-02:** All fusion candidates must survive through reranking. If a candidate from the RRF fusion list is not scored by the reranker (or scores poorly), it should remain in the final list with its original fusion score — not be silently dropped.

### Score Blending
- **D-03:** Keep current blend weights (0.4 fusion + 0.6 reranker) unchanged. No evidence to justify changing them. Revisit only if BM25 results still rank too low after the threshold fix.

### Configurable Thresholds
- **D-04:** No env-var configurability for thresholds or weights. YAGNI. SEARCH-F2 stays in future requirements.

### Diagnostic Approach
- **D-05:** Add diagnostic logging to confirm the hypothesis (log BM25 results before/after reranker) as part of the fix — not as a separate step. Validate with a query that matches keywords but not semantics.

### Claude's Discretion
- Specific implementation approach for preserving fusion candidates through reranking (merge-back, floor score, or other mechanism)
- Test design and validation queries
- Logging format and verbosity

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Search Pipeline
- `backend/src/dotmd/search/reranker.py` — Cross-encoder reranker with score threshold (line 131) and length penalty
- `backend/src/dotmd/search/fusion.py` — RRF fusion and result building
- `backend/src/dotmd/search/bm25.py` — BM25 search engine (works correctly standalone)
- `backend/src/dotmd/api/service.py` lines 186-229 — Search orchestration: fusion → reranking → blending

### Codebase Analysis
- `.planning/codebase/ARCHITECTURE.md` — Search pipeline architecture and data flow
- `.planning/codebase/CONCERNS.md` — "Hardcoded score thresholds and weights scattered across config" (tech debt), "No integration tests for mixed search modes" (test gap)

### Requirements
- `.planning/REQUIREMENTS.md` — SEARCH-01 (this phase), SEARCH-F2 (deferred: configurable thresholds)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `BM25SearchEngine.search()` — works correctly, returns `(chunk_id, score)` pairs with `score > 0` filter
- `fuse_results()` — RRF fusion is correct, includes BM25 results properly
- `build_search_results()` — correctly attributes per-engine scores and `matched_engines` field

### Established Patterns
- Protocol-based abstractions (`SearchEngineProtocol`) — no need to change interfaces
- Lazy model loading in Reranker — keep this pattern
- Engine results dict pattern: `engine_results["bm25"] = bm25_hits` only if hits exist

### Integration Points
- `service.py:202-229` — the reranking + blending block is the only code that needs modification
- `reranker.py:128-132` — the score threshold filter to remove
- No changes needed in BM25 engine, fusion, or result building

### Root Cause Analysis
Two failure points in series:
1. **Reranker threshold** (`reranker.py:131`): `score >= -8.0` filter removes BM25-only matches that get low cross-encoder scores
2. **Blend replacement** (`service.py:222-229`): `fused = blended` replaces the entire fusion list with only reranked survivors — any result filtered by the threshold is permanently lost

</code_context>

<specifics>
## Specific Ideas

- Expert panel (ML/IR Engineer, Researcher, Kaizen Master) reviewed the approach — unanimous on removing threshold, keeping weights unchanged
- Researcher noted: ms-marco-MiniLM-L-6-v2 trained on MS MARCO web passages, not markdown/technical docs — relevance judgments may be systematically miscalibrated for this domain
- Kaizen Master: fix only the filter problem (Problem A), don't optimize weights (Problem B) without tuning data

</specifics>

<deferred>
## Deferred Ideas

- **Reranker model evaluation** — ms-marco-MiniLM-L-6-v2 may be poorly suited for markdown/technical content (trained on web passages). Evaluate domain-specific alternatives or fine-tuning in a future phase.
- **SEARCH-F2: Configurable reranker threshold** — env var for threshold/weights. Explicitly deferred as YAGNI.
- **Blend weight tuning** — if BM25 results still rank too low after threshold removal, revisit the 0.4/0.6 blend ratio with empirical data.

</deferred>

---

*Phase: 05-bm25-hybrid-fix*
*Context gathered: 2026-03-27*
