# Requirements: dotMD

**Defined:** 2026-03-27
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## v1.3 Requirements

Requirements for v1.3 milestone. Each maps to roadmap phases.

### Production Packaging

- [ ] **PACK-01**: Service deploys via single `docker compose up` with all dependencies declared (dotMD + TEI reference + FalkorDB)
- [x] **PACK-02**: Healthchecks on TEI (`/health`) and FalkorDB (`redis-cli ping`) with `depends_on: condition: service_healthy`
- [ ] **PACK-03**: All configuration via environment variables with documented defaults in example `.env`
- [x] **PACK-04**: SQLite WAL mode enabled on all databases (metadata.db, vec.db) for concurrent read/write safety

### Smoke Tests

- [ ] **TEST-01**: Smoke test verifies semantic search returns results for a known-indexed query
- [ ] **TEST-02**: Smoke test verifies BM25 search returns results for a known-indexed query
- [ ] **TEST-03**: Smoke test verifies graph search returns results for a known-indexed query
- [ ] **TEST-04**: Smoke test verifies hybrid fusion combines results from multiple engines
- [ ] **TEST-05**: Smoke test verifies API returns HTTP 200 with valid JSON on search endpoint

### Speed Optimization

- [ ] **SPEED-01**: Benchmark measures end-to-end texts/sec for concurrent TEI requests (1, 2, 3 parallel) and reports whether concurrency improves throughput
- [ ] **SPEED-02**: Benchmark measures GLiNER batch vs sequential NER throughput and reports whether batching improves speed

### Background Indexer

- [ ] **BGIDX-01**: Background indexer discovers and processes unindexed files one at a time while API serves queries
- [ ] **BGIDX-02**: `dotmd status` reports background indexing progress ("indexing 1,234/13,515 files")
- [ ] **BGIDX-03**: Background indexer shuts down gracefully on SIGTERM (finishes current file, does not corrupt state)
- [ ] **BGIDX-04**: BM25 index rebuilds batched (every N files) with atomic pickle swap to prevent reader corruption
- [ ] **BGIDX-05**: Configurable pause interval between files to control CPU pressure
- [ ] **BGIDX-06**: Background indexer runs at low CPU priority via `docker update --cpu-shares`

## Future Requirements

Deferred to future milestone. Tracked but not in current roadmap.

### Speed Implementation

- **SPEED-03**: Concurrent TEI requests (implement if benchmark shows gain)
- **SPEED-04**: GLiNER batch NER (implement if benchmark shows gain)
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
| PACK-01 | Phase 7 | Pending |
| PACK-02 | Phase 7 | Complete |
| PACK-03 | Phase 7 | Pending |
| PACK-04 | Phase 7 | Complete |
| TEST-01 | Phase 8 | Pending |
| TEST-02 | Phase 8 | Pending |
| TEST-03 | Phase 8 | Pending |
| TEST-04 | Phase 8 | Pending |
| TEST-05 | Phase 8 | Pending |
| SPEED-01 | Phase 9 | Pending |
| SPEED-02 | Phase 9 | Pending |
| BGIDX-01 | Phase 10 | Pending |
| BGIDX-02 | Phase 10 | Pending |
| BGIDX-03 | Phase 10 | Pending |
| BGIDX-04 | Phase 10 | Pending |
| BGIDX-05 | Phase 10 | Pending |
| BGIDX-06 | Phase 10 | Pending |

**Coverage:**
- v1.3 requirements: 17 total
- Mapped to phases: 17
- Unmapped: 0

---
*Requirements defined: 2026-03-27*
*Last updated: 2026-03-27 after roadmap creation — traceability complete*
