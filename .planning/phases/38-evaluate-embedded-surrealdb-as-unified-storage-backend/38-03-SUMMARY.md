---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
plan: 03
subsystem: database
tags: [surrealdb, retrieval-parity, fts5, rrf, vector]
requires:
  - phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
    provides: "38-01 copied snapshot evidence, 38-02 transform import proof, and 38-05 embedded safety gate"
provides:
  - "Retrieval parity harness for FTS, vector, graph-direct, and hybrid/RRF comparison"
  - "Representative copied-snapshot retrieval evidence with explicit failed migration gate"
  - "Deterministic hybrid tie policy and blocking parity failure taxonomy"
affects: [phase-38, storage, search, migration-recommendation, surrealdb]
tech-stack:
  added: []
  patterns: [retrieval-parity-harness, deterministic-rrf-tie-break, failed-gate-evidence]
key-files:
  created:
    - backend/src/dotmd/search/surreal_parity.py
    - backend/tests/search/test_surreal_retrieval_parity.py
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md
  modified: []
key-decisions:
  - "FTS weighting mismatch is a blocking defer signal, not an informational warning."
  - "Representative parity evidence reuses copied snapshot rows and stored embeddings; no TEI calls or source indexing are allowed."
  - "Hybrid/RRF parity is normalized with deterministic score-then-chunk_id ordering before comparison."
patterns-established:
  - "Parity harness pattern: compare current-stack and Surreal-stack callables on the same stored corpus and emit blocking categories."
  - "Scale gate pattern: missing HNSW timing or equivalent scale evidence forces recommendation_gate=fail."
requirements-completed: [STOR-02]
duration: 21 min
completed: 2026-06-12
status: complete
---

# Phase 38 Plan 03: Retrieval Parity Summary

**Copied-snapshot retrieval parity harness showing vector parity pass but blocking FTS weighting, hybrid attribution, and scale-gate failures**

## Performance

- **Duration:** 21 min
- **Started:** 2026-06-12T15:10:30Z
- **Completed:** 2026-06-12T15:31:27Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added a dedicated parity harness for FTS, vector, graph-direct, and hybrid/RRF comparisons with structured blocking categories.
- Proved vector parity on an imported copied-snapshot sample without TEI, while surfacing explicit failed-gate evidence for FTS weighting and hybrid attribution.
- Wrote `38-03-RETRIEVAL-PARITY.md` with representative sample inputs, deterministic tie policy, scale metrics, and an overall failed migration recommendation gate.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED retrieval parity tests for FTS, vector, graph-direct, and hybrid paths** - `39d97a5` (`test`)
2. **Task 2: Implement the Surreal retrieval parity harness** - `1a95ba5` (`feat`)
3. **Task 3: Run copied-snapshot retrieval parity and write the evidence report** - `0ac25d4` (`fix`)

Plan metadata commits are recorded separately after summary/state close-out.

## Files Created/Modified

- `backend/tests/search/test_surreal_retrieval_parity.py` - RED/GREEN parity contract for blocking categories, vector overlap, graph normalization, and deterministic hybrid ties.
- `backend/src/dotmd/search/surreal_parity.py` - case/result/report types, comparator functions, callable-based harness, and scale gate evaluation.
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-03-RETRIEVAL-PARITY.md` - representative copied-snapshot evidence and failed recommendation gate.

## Decisions Made

- Classified weighted-field FTS mismatch as a blocking `defer`, not as partial parity.
- Kept vector evidence honest by reusing stored snapshot embeddings as fixed queries instead of calling TEI.
- Treated missing HNSW build timing as a scale-gate failure that blocks any migrate-ready recommendation.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Passed graph seed metadata through the callable harness path**
- **Found during:** Task 3 (real parity run on the new harness)
- **Issue:** `SurrealRetrievalParityHarness.run_case()` ignored `seed_chunk_id` metadata for graph-direct cases, so normalized Surreal relation rows could retain the seed section and produce a false graph semantic gap.
- **Fix:** Updated `run_case()` to forward `seed_chunk_id` from `RetrievalParityCase.metadata` into `compare_graph_direct_results()` and preserved query latency reporting even when the scale gate fails.
- **Files modified:** `backend/src/dotmd/search/surreal_parity.py`
- **Verification:** `cd backend && uv run pytest tests/search/test_surreal_retrieval_parity.py tests/test_hybrid_bm25.py tests/storage/test_falkordb_graph.py -x`
- **Committed in:** `0ac25d4`

---

**Total deviations:** 1 auto-fixed (1 bug)
**Impact on plan:** The fix corrected evidence integrity. It did not expand scope or change the failed recommendation outcome.

## Issues Encountered

- Direct host access to `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` was blocked by filesystem permissions, so the representative sample used the already-created container-side copied snapshot from Plan 38-01 and copied that snapshot to host space instead of touching the live volume.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 38-04 can consume a clear failed gate: `defer: FTS weighting`, `reject: hybrid/RRF gap`, and `fail: unavailable scale evidence`.
- Vector import/search parity is strong enough to keep as positive evidence, but it is insufficient on its own to recommend migration.
- Any future migrate recommendation must first close weighted multi-field FTS parity, hybrid engine-attribution parity, and HNSW timing evidence.

## Self-Check: PASSED

- `38-03-SUMMARY.md` exists on disk.
- `38-03-RETRIEVAL-PARITY.md` exists on disk.
- Task commit `39d97a5` is present in git history.
- Task commit `1a95ba5` is present in git history.
- Task commit `0ac25d4` is present in git history.

---
*Phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend*
*Completed: 2026-06-12*
