---
phase: 09-speed-benchmarks
plan: 01
subsystem: benchmarking
tags: [tei, gliner, concurrency, batching, benchmark, httpx, threadpool]

# Dependency graph
requires:
  - phase: 04-falkordb-adapter-config
    provides: TEI integration pattern (semantic.py _encode_via_tei)
provides:
  - TEI concurrency benchmark script (bench_tei_concurrency.py)
  - GLiNER batching benchmark script (bench_gliner_batching.py)
affects: [10-background-indexer, speed-optimization]

# Tech tracking
tech-stack:
  added: []
  patterns: [standalone benchmark scripts in backend/benchmarks/, synthetic test data generation, ThreadPoolExecutor for I/O concurrency measurement]

key-files:
  created:
    - backend/benchmarks/bench_tei_concurrency.py
    - backend/benchmarks/bench_gliner_batching.py
  modified: []

key-decisions:
  - "Standalone scripts with no dotmd imports -- benchmarks bypass the service layer and test TEI HTTP / GLiNER model directly"
  - "Fixed batch_size from env (DOTMD_TEI_BATCH_SIZE) to isolate concurrency variable in TEI benchmark"
  - "Capped GLiNER batch_size at 8 to avoid OOM on 16GB server"

patterns-established:
  - "Benchmark script pattern: generate synthetic data, warmup, N iterations, stats table, CONCLUSION line"

requirements-completed: [SPEED-01, SPEED-02]

# Metrics
duration: 3min
completed: 2026-03-27
---

# Phase 09 Plan 01: Speed Benchmarks Summary

**Two standalone benchmark scripts measuring TEI concurrent embedding throughput (1/2/3 workers) and GLiNER sequential-vs-batch NER performance (bs=1/4/8 + packing)**

## Performance

- **Duration:** 3 min
- **Started:** 2026-03-27T18:03:16Z
- **Completed:** 2026-03-27T18:06:43Z
- **Tasks:** 2
- **Files created:** 2

## Accomplishments
- TEI concurrency benchmark: measures texts/sec for 1, 2, 3 concurrent HTTP workers with fixed batch_size matching production
- GLiNER batching benchmark: measures sequential predict_entities vs batch inference (bs=1,4,8) vs sequence packing (bs=8)
- Both scripts generate synthetic test data (100/50 texts), include warmup, run 3 iterations, and print human-readable comparison tables with CONCLUSION lines

## Task Commits

Each task was committed atomically:

1. **Task 1: TEI concurrency benchmark script** - `d6465aa` (feat)
2. **Task 2: GLiNER batching benchmark script** - `2a344a8` (feat)

## Files Created/Modified
- `backend/benchmarks/bench_tei_concurrency.py` - Measures texts/sec for 1/2/3 concurrent TEI request workers (151 lines)
- `backend/benchmarks/bench_gliner_batching.py` - Measures sequential vs batch vs packed GLiNER NER throughput (200 lines)

## Decisions Made
- Used ThreadPoolExecutor (not asyncio) for TEI concurrency -- 1-3 workers of I/O-bound HTTP calls don't benefit from async complexity
- Fixed batch_size from DOTMD_TEI_BATCH_SIZE env var to isolate the concurrency variable (not batch size) in TEI benchmark
- Capped GLiNER batch_size at 8 to stay safe on 16GB RAM
- Graceful fallback for sequence packing (returns N/A if InferencePackingConfig unavailable)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Benchmark scripts ready to run inside dotMD container against live TEI instance
- Results will inform Phase 10 (background trickle indexer) concurrency/batching parameters
- Run with: `docker exec dotmd-app-1 python benchmarks/bench_tei_concurrency.py` and `docker exec dotmd-app-1 python benchmarks/bench_gliner_batching.py`

## Self-Check: PASSED

All files created and all commits verified.

---
*Phase: 09-speed-benchmarks*
*Completed: 2026-03-27*
