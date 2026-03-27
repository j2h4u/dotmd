# Requirements: dotMD

**Defined:** 2026-03-27
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## v1.3 Requirements

Requirements for v1.3 milestone. Each maps to roadmap phases.

### Production Packaging

- [x] **PACK-01**: Service deploys via single `docker compose up` with all dependencies declared (dotMD + TEI reference + FalkorDB)
- [x] **PACK-02**: Healthchecks on TEI (`/health`) and FalkorDB (`redis-cli ping`) with `depends_on: condition: service_healthy`
- [x] **PACK-03**: All configuration via environment variables with documented defaults in example `.env`
- [x] **PACK-04**: SQLite WAL mode enabled on all databases (metadata.db, vec.db) for concurrent read/write safety

### Smoke Tests

- [ ] **TEST-01**: Smoke test verifies semantic search returns results for a known-indexed query
- [ ] **TEST-02**: Smoke test verifies BM25 search returns results for a known-indexed query
- [ ] **TEST-03**: Smoke test verifies graph search returns results for a known-indexed query
- [ ] **TEST-04**: Smoke test verifies hybrid fusion combines results from multiple engines
- [ ] **TEST-05**: Smoke test verifies API returns HTTP 200 with valid JSON on search endpoint

### Speed Optimization

- [x] **SPEED-01**: Benchmark measures end-to-end texts/sec for concurrent TEI requests (1, 2, 3 parallel) and reports whether concurrency improves throughput — **Result (2026-03-28): No benefit.** workers=1: 0.7 t/s, workers=2: 0.7 t/s, workers=3: 0.8 t/s (within stddev 0.09–0.14). TEI already saturates all cores on a single request.
- [x] **SPEED-02**: Benchmark measures GLiNER batch vs sequential NER throughput and reports whether batching improves speed — **Result (2026-03-28): Batching hurts.** Sequential: 0.72 t/s, batch bs=1: 0.53, bs=4: 0.61, bs=8: killed (OOM, 20GB swap on 16GB server). Overhead exceeds any parallelism gain.

### Background Indexer

- [x] **BGIDX-01**: Background indexer discovers and processes unindexed files one at a time while API serves queries
- [x] **BGIDX-02**: `dotmd status` reports background indexing progress ("indexing 1,234/13,515 files")
- [x] **BGIDX-03**: Background indexer shuts down gracefully on SIGTERM (finishes current file, does not corrupt state)
- [x] **BGIDX-04**: BM25 index rebuilds batched (every N files) with atomic pickle swap to prevent reader corruption
- [x] **BGIDX-05**: Configurable pause interval between files to control CPU pressure
- [x] **BGIDX-06**: Background indexer runs at low CPU priority via `docker update --cpu-shares`

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Speed Implementation

- ~~**SPEED-03**: Concurrent TEI requests~~ — Closed: benchmark showed no gain (1.12x within noise)
- ~~**SPEED-04**: GLiNER batch NER~~ — Closed: benchmark showed batching is slower + OOM at bs=8
- **SPEED-05**: TEI throughput auto-tuning with persistent calibration

### Testing Enhancements

- **TEST-06**: `dotmd test` CLI command for in-container smoke testing
- **TEST-07**: BM25-only matches survive reranker regression guard

### Search Quality

- **SEARCH-01**: Per-engine attribution logging
- **SEARCH-02**: Configurable reranker threshold

## Out of Scope

| Feature | Reason |
|---------|--------|
| LadybugDB removal | Keep as alternative embedded backend and for upstream compatibility |
| GPU acceleration | No GPU on current hardware |
| Bundled TEI instance | Would consume 2.6GB additional RAM on 16GB server — use shared external TEI |
| Search quality tuning | Tune after full corpus indexed |
| Upstream PRs | Fork has diverged too far |

## Traceability

Which phases cover which requirements. Updated during roadmap creation.

| Requirement | Phase | Status |
|-------------|-------|--------|
| PACK-01 | Phase 7 | Complete |
| PACK-02 | Phase 7 | Complete |
| PACK-03 | Phase 7 | Complete |
| PACK-04 | Phase 7 | Complete |
| TEST-01 | Phase 8 | Pending |
| TEST-02 | Phase 8 | Pending |
| TEST-03 | Phase 8 | Pending |
| TEST-04 | Phase 8 | Pending |
| TEST-05 | Phase 8 | Pending |
| SPEED-01 | Phase 9 | Complete |
| SPEED-02 | Phase 9 | Complete |
| BGIDX-01 | Phase 10 | Complete |
| BGIDX-02 | Phase 10 | Complete |
| BGIDX-03 | Phase 10 | Complete |
| BGIDX-04 | Phase 10 | Complete |
| BGIDX-05 | Phase 10 | Complete |
| BGIDX-06 | Phase 10 | Complete |

**Coverage:**
- v1.3 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after roadmap creation — traceability complete*
