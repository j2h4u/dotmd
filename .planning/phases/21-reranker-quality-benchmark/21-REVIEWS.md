---
phase: 21
reviewers: [opencode]
reviewed_at: 2026-05-02T00:30:57+05:00
plans_reviewed:
  - 21-01-quality-benchmark-PLAN.md
---

# Cross-AI Plan Review — Phase 21

## OpenCode Review

Let me check the key source files referenced in the plan to validate assumptions.
Now I have enough context. Here's the review:

---

## Plan Review: 21-01-quality-benchmark-PLAN.md

### Summary

This is a well-structured benchmark plan that correctly builds on the Phase 20 latency infrastructure and leverages the existing `compare_rerankers()` shared-pool API. The task decomposition is logical (labels → runner → execute → summarize), constants are locked down, and the threat model addresses the main risks. The plan will achieve the phase goal if executed as written. A few medium-severity gaps deserve attention before execution.

### Strengths

- **Shared candidate pool is structurally guaranteed.** The plan routes through `compare_rerankers()` which already calls `_collect_candidate_pool()` once and reuses `chunk_ids` for each model. This is architecturally sound — no risk of retrieval variance leaking into quality comparisons.
- **Label resolution design is practical.** Supporting both `chunk_id` and `file_path + contains` forms with a fail-loud resolver is the right call. Users don't know chunk IDs, and strict resolution prevents silent mislabeling.
- **Negative control is explicit and enforced.** `msmarco-minilm` as a lower bound is mentioned in the constants, threat model, ledger spec, summary template, and acceptance criteria. This won't be forgotten.
- **Metric choice is appropriate.** Hit@K/MRR/nDCG are standard IR metrics; using rank-based metrics only (ignoring raw cross-encoder scores) avoids the known pitfall of incomparable score scales.
- **Operational pattern matches Phase 20.** Reusing the `devtools/` directory, `docker exec`, and JSONL+markdown output pattern means the runner will work in the same proven deployment shape.

### Concerns

- **MEDIUM — `get_chunks_for_file_range()` requires `strategy` parameter.** The plan says the label resolver should use `service._pipeline.metadata_store.get_chunks_for_file_range()`, but that method signature at `metadata.py:396-401` requires a `strategy` argument and positional `[start, end)` slice. The plan's label format `{"file_path": "...", "contains": "..."}` doesn't include strategy or range. The runner will need to either (a) query all chunks for a file path across the current chunking strategy, or (b) add a helper method that does substring matching without requiring start/end bounds. This is an implementation gap that should be clarified before coding.
- **MEDIUM — Label authoring happens autonomously in Task 1.** The plan marks Task 1 as `type: auto` and expects 30+ Russian/mixed queries with correct relevance labels against the live index. Writing high-quality relevance labels requires human judgment about which chunks are actually relevant to a query. An autonomous agent cannot meaningfully judge Russian-language query relevance without ground truth from the user. The labels will likely be plausible-looking but wrong, making the entire benchmark's quality scores unreliable.
- **MEDIUM — No pool-miss handling for quality scoring.** The plan mentions `pool_miss` as an output field, but doesn't specify what happens to quality metrics when none of the labeled relevant chunks appear in the shared candidate pool. If retrieval never surfaces the relevant chunks, the reranker has nothing to promote, and the quality score becomes 0.0 through no fault of the model. The plan should specify whether pool-miss queries are excluded from per-model scoring or counted as failures.
- **LOW — `compare_rerankers()` sorts output by `(error, rerank_ms)`.** At `service.py:528`, the method sorts `runs` by error status then latency. The quality runner should ignore this ordering and re-sort by model name or canonical order for consistent output rows. Not a blocker, but worth noting.
- **LOW — Task 3 assumes `/app/devtools` is writable in the container.** The plan says "copy the committed runner to `/app/devtools/reranker_quality_bench.py`" if not mounted. The latency bench presumably works because the devtools directory is bind-mounted. If it isn't, copying into a container filesystem requires `docker cp` and the file disappears on restart. The plan should confirm the mount situation rather than handling it reactively.

### Suggestions

- **Require human review of labels before Task 3.** Split Task 1 into 1a (generate candidate labels) and 1b (human review checkpoint). Without this, you're benchmarking rerankers against labels an LLM guessed. Alternatively, reduce to 10-15 queries that the user can verify quickly during execution, and add the rest iteratively.
- **Add a `get_chunks_for_file` helper to the runner** (not to the metadata store) that queries all chunks for a given file path using the current strategy from settings, then does substring matching. This avoids the `strategy`/`start`/`end` parameter mismatch.
- **Define pool-miss semantics explicitly.** Recommend: exclude pool-miss queries from per-model nDCG/MRR computation, but report them separately in the summary as "retrieval gaps, not reranker quality gaps."
- **Store `strategy` in the benchmark ledger.** The plan records commit, model list, pool size, etc., but not which chunking strategy the index was built with. Since chunk IDs depend on strategy, this should be in the ledger for reproducibility.

### Risk Assessment

**MEDIUM**

The architecture is sound and the shared-pool invariant is structurally guaranteed by existing code. The primary risk is **label quality** — autonomous generation of 30+ Russian-language relevance judgments is the weakest link. If labels are noisy, the benchmark produces confident-looking numbers that don't reflect real quality. The secondary risk is the `get_chunks_for_file_range` API mismatch, which is a straightforward implementation gap but could cause confusion during Task 2 if not resolved upfront.

The plan will achieve its structural goals (runner, artifacts, recommendation) but the *trustworthiness* of the recommendation depends entirely on label quality, which the plan doesn't sufficiently safeguard.

---

## Consensus Summary

Only OpenCode was invoked for this review by request.

### Agreed Strengths

- Shared candidate pool design is sound.
- Rank-based IR metrics are appropriate.
- Negative historical control is explicit.

### Agreed Concerns

- Label quality needs a human review checkpoint before canonical scoring.
- Label resolution needs a concrete implementation path for file-path labels.
- Pool-miss semantics need to be defined before execution.

### Divergent Views

None; only one reviewer was used.
