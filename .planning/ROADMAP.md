# Roadmap: dotMD

**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Milestones

- [x] **v1.1 Incremental Indexing** — Phases 1-3 (shipped 2026-03-26)
- [x] **v1.2 FalkorDB Migration & Search Fix** — Phases 4-6 (shipped 2026-03-27)
- [ ] **v1.3 Production Packaging & Background Indexing** — Phases 7-10 (in progress)

<details>
<summary>v1.1 Incremental Indexing (Phases 1-3) — SHIPPED 2026-03-26</summary>

- [x] Phase 1: sqlite-vec Migration (2/2 plans) — completed 2026-03-26
- [x] Phase 2: Incremental Pipeline (2/2 plans) — completed 2026-03-26
- [x] Phase 3: CLI & API Polish (2/2 plans) — completed 2026-03-26

See: `.planning/milestones/v1.1-ROADMAP.md`

</details>

<details>
<summary>v1.2 FalkorDB Migration & Search Fix (Phases 4-6) — SHIPPED 2026-03-27</summary>

- [x] Phase 4: FalkorDB Adapter + Config (2/2 plans) — completed 2026-03-27
- [x] Phase 5: BM25 Hybrid Fix (1/1 plan) — completed 2026-03-27
- [x] Phase 6: Docker Integration + Migration (1/1 plan) — completed 2026-03-27

See: `.planning/milestones/v1.2-ROADMAP.md`

</details>

## v1.3 Production Packaging & Background Indexing

**Milestone Goal:** Turn dotMD from a developer prototype into a self-contained production service -- docker compose up, point at paths, it indexes and serves search. Plus background indexing for large corpora and smoke tests for regression safety.

## Phases

- [x] **Phase 7: Production Packaging** - Self-contained docker-compose stack with healthchecks, env config, and WAL mode (completed 2026-03-27)
- [ ] **Phase 8: Smoke Tests** - Automated regression safety net covering all search engines and API
- [ ] **Phase 9: Speed Benchmarks** - Empirical measurement of TEI concurrency and NER batching gains
- [ ] **Phase 10: Background Trickle Indexer** - Gradual indexing of full 13,500-file corpus at low priority

## Phase Details

### Phase 7: Production Packaging
**Goal**: Service deploys as a self-contained stack with zero manual steps beyond `docker compose up`
**Depends on**: Phase 6 (Docker Integration from v1.2)
**Requirements**: PACK-01, PACK-02, PACK-03, PACK-04
**Success Criteria** (what must be TRUE):
  1. Running `docker compose up` starts dotMD, FalkorDB, and references TEI -- all healthy before API accepts requests
  2. Healthchecks on TEI and FalkorDB gate service startup -- API does not start until dependencies report healthy
  3. All configuration lives in environment variables with an `.env.example` documenting every option and its default
  4. SQLite databases operate in WAL mode -- concurrent reads during writes do not return "database is locked"
**Plans:** 2/2 plans complete
Plans:
- [x] 07-01-PLAN.md — Health endpoint, WAL pragma, Dockerfile HEALTHCHECK
- [x] 07-02-PLAN.md — Parameterized compose stack, .env.example, production deployment

### Phase 8: Smoke Tests
**Goal**: Automated tests verify all search engines and API work correctly against the running stack
**Depends on**: Phase 7 (reliable stack to test against)
**Requirements**: TEST-01, TEST-02, TEST-03, TEST-04, TEST-05
**Success Criteria** (what must be TRUE):
  1. `pytest tests/smoke/` passes against a running stack with indexed data, covering semantic, BM25, and graph search
  2. Hybrid fusion test confirms results from multiple engines are combined (not just one engine returning results)
  3. API smoke test verifies HTTP 200 with valid JSON structure on the search endpoint
  4. Tests skip gracefully (not fail) when the stack is unavailable, so they work in CI-less dev workflow
**Plans:** 1 plan
Plans:
- [x] 08-01-PLAN.md — Smoke test suite: conftest skip logic, search engine tests, hybrid fusion, API validation

### Phase 9: Speed Benchmarks
**Goal**: Empirical data on whether TEI concurrency and NER batching improve throughput on this hardware
**Depends on**: Phase 8 (smoke tests catch regressions if benchmark code touches pipeline)
**Requirements**: SPEED-01, SPEED-02
**Success Criteria** (what must be TRUE):
  1. Benchmark script reports texts/sec for 1, 2, and 3 concurrent TEI requests with a clear conclusion on whether concurrency helps
  2. Benchmark script reports GLiNER throughput for batch vs sequential NER with a clear conclusion on whether batching helps
**Plans:** 1 plan
Plans:
- [x] 09-01-PLAN.md — TEI concurrency benchmark + GLiNER batching benchmark scripts

### Phase 10: Background Trickle Indexer
**Goal**: Unindexed files are processed gradually in the background while the API continues serving search queries
**Depends on**: Phase 7 (WAL mode for concurrent SQLite access), Phase 9 (speed optimizations benefit per-file throughput)
**Requirements**: BGIDX-01, BGIDX-02, BGIDX-03, BGIDX-04, BGIDX-05, BGIDX-06
**Success Criteria** (what must be TRUE):
  1. Background indexer discovers and processes unindexed files one at a time while search queries continue returning results
  2. `dotmd status` shows background indexing progress (e.g., "indexing 1,234/13,515 files")
  3. Sending SIGTERM to the container finishes the current file and shuts down cleanly -- no corrupt state in SQLite or FTS5
  4. BM25 search is incremental via FTS5 -- each file becomes searchable immediately after indexing (no batch rebuild needed)
  5. CPU pressure is controllable via configurable pause interval and docker cpu-shares
**Plans:** 1/4 plans executed
Plans:
- [ ] 10-01-PLAN.md — Replace rank_bm25 with SQLite FTS5 for incremental BM25 search
- [x] 10-02-PLAN.md — Config.toml support + multi-path file discovery with glob/exclude
- [ ] 10-03-PLAN.md — TrickleIndexer background loop with watchdog filesystem watching
- [ ] 10-04-PLAN.md — Trickle progress reporting via status API and CLI

## Progress

**Execution Order:** Phase 7 -> 8 -> 9 -> 10

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. sqlite-vec Migration | v1.1 | 2/2 | Complete | 2026-03-26 |
| 2. Incremental Pipeline | v1.1 | 2/2 | Complete | 2026-03-26 |
| 3. CLI & API Polish | v1.1 | 2/2 | Complete | 2026-03-26 |
| 4. FalkorDB Adapter + Config | v1.2 | 2/2 | Complete | 2026-03-27 |
| 5. BM25 Hybrid Fix | v1.2 | 1/1 | Complete | 2026-03-27 |
| 6. Docker Integration + Migration | v1.2 | 1/1 | Complete | 2026-03-27 |
| 7. Production Packaging | v1.3 | 2/2 | Complete   | 2026-03-27 |
| 8. Smoke Tests | v1.3 | 0/1 | Planned | - |
| 9. Speed Benchmarks | v1.3 | 0/1 | Planned | - |
| 10. Background Trickle Indexer | v1.3 | 1/4 | In Progress|  |

---
*Roadmap created: 2026-03-26*
*Last updated: 2026-03-28 after Phase 10 planning complete*
