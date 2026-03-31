# Project Research Summary

**Project:** dotMD v1.3 -- Production Packaging & Background Indexing
**Domain:** Production hardening of a multi-engine markdown knowledgebase search service
**Researched:** 2026-03-27
**Confidence:** HIGH

## Executive Summary

dotMD v1.3 is a production-hardening milestone for an existing, working search service. The core technical challenge is adding background indexing to a codebase designed for single-threaded CLI usage, while simultaneously packaging the Docker deployment for zero-manual-step startup. Research across all four dimensions converges on a clear finding: **the changes are straightforward individually but dangerous in combination** -- concurrent SQLite access, BM25 rebuild scaling, and event loop blocking are the primary risks, all stemming from the same root cause (single-threaded assumptions baked into the storage layer).

The recommended approach is a strict four-phase sequence: Docker packaging first (foundation), smoke tests second (safety net), speed optimization third (independent wins), background indexer last (highest risk, benefits from everything prior). No new runtime dependencies are needed -- everything uses stdlib asyncio, existing httpx, and existing GLiNER APIs. The only new dev dependency is pytest-asyncio. This is a refactoring and integration milestone, not a greenfield build.

The key risk is the TEI "self-contained" decision. Research strongly recommends **not** bundling a second TEI instance -- it would consume an additional 2.6GB on a 16GB server already near capacity. TEI stays as shared external infrastructure; "self-contained" means FalkorDB bundled (dotmd-specific) plus documented dependency on the existing TEI service. The second major risk is concurrent TEI requests -- empirical evidence (bs=4 equals bs=32 throughput) strongly suggests TEI is compute-bound on this CPU, making HTTP concurrency a complexity investment with near-zero return. Benchmark before implementing.

## Key Findings

### Recommended Stack

No new runtime dependencies. The entire v1.3 scope maps to existing capabilities.

**Core additions:**
- `asyncio.create_task()` in FastAPI lifespan: background indexer loop -- stdlib, well-documented pattern for server-lifetime tasks
- `asyncio.to_thread()`: offload sync pipeline to thread without blocking event loop -- stdlib, Python 3.9+
- `httpx.AsyncClient` + `asyncio.Semaphore`: concurrent TEI requests -- already a dependency (0.28.1), conditional on benchmarking
- `gliner.batch_predict_entities()`: batch NER inference -- already a dependency (0.2.26), conditional on profiling
- `pytest-asyncio` (>=0.24): only new dev dependency, for async test support

**Critical version constraints:**
- PyTorch <2.5 (Ivy Bridge, no AVX2) -- already enforced
- Docker Compose v2 with `condition: service_healthy` -- already available on server

See [STACK.md](STACK.md) for full rationale, code patterns, and alternatives considered.

### Expected Features

**Must have (table stakes):**
- Self-contained docker-compose with healthchecks on all services (TEI external, FalkorDB bundled)
- ENV-based configuration with sane defaults -- `docker compose up` works with only data path configured
- Background trickle indexer that does not block search queries
- Indexing progress visibility via `/status` endpoint
- Graceful shutdown mid-index (FileTracker already persists after success)
- Smoke tests covering all 3 search engines, hybrid fusion, and BM25 regression guard

**Should have (differentiators):**
- Concurrent TEI requests (2-3 parallel) -- only if benchmarking shows >15% gain
- TEI throughput calibration (persist optimal batch size to disk)
- Configurable background indexing rate (batch size, pause between files, CPU shares)
- SQLite WAL mode for concurrent read/write isolation (trivial one-liner, massive impact)

**Defer to v1.4+:**
- GLiNER batch inference (community reports mixed CPU results -- needs dedicated benchmarking)
- NER skip + backfill for background mode (optimization on top of working indexer)
- GLiNER v2 bi-encoder model evaluation (significant model change)
- File watching via inotify/watchdog (polling is sufficient)

See [FEATURES.md](FEATURES.md) for full feature landscape, dependency graph, and comparable service analysis.

### Architecture Approach

The architecture adds one new component (`BackgroundIndexer` in `ingestion/background.py`) and modifies four existing files. The key decisions are: (1) background indexer runs as a thread inside the API process sharing `DotMDService` -- avoids duplicate model memory and cross-process SQLite locking; (2) pipeline gets a new `process_file()` method extracted from `_ingest_and_finalize()` for per-file granularity; (3) BM25 rebuild happens periodically (every N files), not per-file; (4) concurrent TEI is internal to `semantic.py` via `asyncio.run()` from the sync pipeline.

**Major components and changes:**
1. `docker-compose.yml` (repo root) -- self-contained stack: api + tei + falkordb with healthchecks
2. `ingestion/background.py` (NEW) -- `BackgroundIndexer` class: thread-based trickle loop, progress state, graceful shutdown
3. `search/semantic.py` (modified) -- `_encode_via_tei_async()` with `asyncio.Semaphore` for concurrent TEI
4. `extraction/ner.py` (modified) -- `batch_predict_entities()` replacing per-chunk loop
5. `tests/smoke/` (NEW) -- 5 test files against running stack with skip-if-unavailable fixtures

**Files unchanged:** All storage backends, BM25 engine, fusion, reranker, query expansion, graph search, CLI, MCP server, Dockerfile.

See [ARCHITECTURE.md](ARCHITECTURE.md) for full component diagrams, data flow, integration points, and anti-patterns.

### Critical Pitfalls

1. **Background indexer blocks the event loop** -- If defined as `async def` calling sync code, it freezes the API. GLiNER alone takes ~4s/chunk on this CPU. **Avoid:** Run in a thread via `asyncio.to_thread()`, never as a direct async function. Insert yield points between files.

2. **SQLite concurrent access without WAL causes locks and corruption** -- The codebase has no WAL mode, no busy_timeout, and stores a single connection per store. Background + search = `database is locked` errors. **Avoid:** Enable WAL mode on all SQLite databases immediately (one-line pragma). Set `busy_timeout=5000`. This should be a prerequisite, not an afterthought.

3. **Docker startup race** -- API starts before FalkorDB/TEI are ready, crashes with `ConnectionError`. **Avoid:** Healthchecks with `depends_on: condition: service_healthy`. Add connection retry logic in the lifespan handler as defense-in-depth.

4. **Bundling TEI doubles RAM** -- A second TEI instance uses ~2.6GB extra on a 16GB server. OOM territory. **Avoid:** Keep TEI as shared external service. FalkorDB is dotmd-specific and should be bundled. Document the TEI dependency clearly.

5. **BM25 full rebuild per trickle-indexed file is O(N^2)** -- At 188k chunks, each rebuild scans the entire metadata table. Per-file rebuilds during 13.5k-file background indexing is catastrophic. **Avoid:** Batch BM25 rebuilds every 50 files or 10 minutes. Use atomic pickle swap (`os.rename`) to prevent corruption.

6. **Concurrent TEI requests likely yield zero gain on CPU** -- Empirical data shows bs=4 and bs=32 have identical throughput. TEI is compute-bound, not I/O-bound. More concurrent HTTP requests just queue inside TEI. **Avoid:** Benchmark 1 vs 2 vs 3 concurrent requests before implementing. Only proceed if >15% throughput gain observed.

See [PITFALLS.md](PITFALLS.md) for full analysis, warning signs, recovery strategies, and "looks done but isn't" checklist.

## Implications for Roadmap

Based on combined research, four phases in strict dependency order. Each phase is independently testable and deployable.

### Phase 1: Production Packaging (Docker Compose + WAL)
**Rationale:** Foundation for everything else. Every other feature needs a running, reliable stack to develop and test against. Healthchecks are prerequisite for reliable smoke tests. WAL mode is a one-line fix that prevents the entire class of concurrent-access bugs in later phases.
**Delivers:** Self-contained docker-compose (FalkorDB bundled, TEI external), healthchecks on all services, ENV defaults, `.env.example`, WAL mode on all SQLite databases, `busy_timeout` pragma.
**Addresses:** Table stakes features (self-contained compose, healthchecks, ENV config). Pitfalls P2 (WAL), P3 (startup race), P4 (TEI RAM).
**Avoids:** Bundling a second TEI instance. Instead: TEI stays external with a startup readiness probe.
**Estimated scope:** Docker config + 2-3 one-line SQLite pragmas. No major code changes.

### Phase 2: Smoke Tests
**Rationale:** Establishes regression safety net before touching pipeline code in Phases 3-4. Tests catch if speed optimization or background indexer break search. No production code changes -- only test code.
**Delivers:** `tests/smoke/` directory with 5 test files, conftest with skip-if-unavailable pattern, BM25 regression guard, pytest marker registration.
**Addresses:** Table stakes (smoke tests, regression safety). Pitfall P7 (flaky tests -- use poll-based readiness, session fixtures, separate graph name).
**Avoids:** pytest-docker / testcontainers (TEI takes 90s to start, impractical per-session). Tests run against already-deployed stack.
**Estimated scope:** ~150 lines of test code + conftest.

### Phase 3: Speed Optimization
**Rationale:** Independent, lower-risk changes in `semantic.py` and `ner.py`. Directly benefits Phase 4 (background indexer processes files faster). Smoke tests from Phase 2 catch regressions. Must be preceded by **empirical benchmarking** of concurrent TEI -- do not assume it helps.
**Delivers:** `tei_concurrency` config field, `_encode_via_tei_async()` (conditional on benchmark), `batch_predict_entities()` in NER, TEI throughput calibration (persist optimal batch size).
**Addresses:** Differentiator features (concurrent TEI, batch NER, calibration). Pitfall P5 (benchmark before implementing concurrency).
**Avoids:** Full async rewrite of pipeline. Only TEI HTTP calls go async; everything else stays sync.
**Estimated scope:** ~80 lines changed across 3 files. Gated on benchmark results.

### Phase 4: Background Trickle Indexer
**Rationale:** Highest complexity, depends on all prior phases. Refactors pipeline internals (extract `process_file()`). Benefits from speed optimizations and has smoke tests as safety net.
**Delivers:** `BackgroundIndexer` class (thread-based), `process_file()` and `rebuild_bm25()` extracted from pipeline, lifespan integration, progress reporting in `/status`, graceful shutdown, batched BM25 rebuilds with atomic swap.
**Addresses:** Core v1.3 deliverable (background indexing), table stakes (progress visibility, graceful shutdown, configurable rate). Pitfalls P1 (event loop blocking), P6 (BM25 O(N^2)).
**Avoids:** Separate process/container (memory budget), Celery/Redis (overkill), per-file BM25 rebuild (O(N^2)), shared DotMDService without thread safety.
**Estimated scope:** 1 new file (~150 lines), 4 modified files (~100 lines total).

### Phase Ordering Rationale

- **Phase 1 before all:** Docker packaging and WAL mode are prerequisites. You cannot test or develop anything reliably without a self-contained stack and concurrent-safe SQLite.
- **Phase 2 before 3-4:** Smoke tests provide the safety net for pipeline refactoring. Without them, speed optimization and background indexer changes risk silent regressions (exactly what happened with BM25 in v1.2).
- **Phase 3 before 4:** Speed optimizations are self-contained changes to `semantic.py` and `ner.py`. The background indexer benefits from faster per-file processing. Doing speed optimization inside the background indexer phase would mix concerns.
- **Phase 4 last:** Touches the most files, highest risk of breaking search. With Phases 1-3 in place, it has: a reliable stack (Phase 1), regression detection (Phase 2), and faster processing (Phase 3).

### Research Flags

**Phases likely needing deeper research during planning:**
- **Phase 3 (Speed Optimization):** Concurrent TEI benefit is uncertain. Empirical benchmarking (1 vs 2 vs 3 concurrent requests) must happen before implementation. GLiNER batch performance on CPU is also unverified. Both are "benchmark first, code second" tasks.
- **Phase 4 (Background Indexer):** Thread safety around shared `DotMDService` needs careful design. The pipeline refactoring (extracting `process_file()`) affects the core indexing path. May benefit from `/gsd:research-phase` for the thread isolation and BM25 batching strategy.

**Phases with standard patterns (skip research):**
- **Phase 1 (Production Packaging):** Docker Compose healthchecks, `depends_on: condition: service_healthy`, and SQLite WAL mode are thoroughly documented with high-confidence sources. Standard configuration work.
- **Phase 2 (Smoke Tests):** pytest + httpx against running services is a standard integration test pattern. Skip-if-unavailable fixture pattern is well-established.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | Zero new runtime dependencies. All APIs verified (asyncio.create_task, httpx.AsyncClient, batch_predict_entities). Only new dev dep is pytest-asyncio. |
| Features | HIGH | Feature landscape grounded in codebase analysis and comparable service patterns (MeiliSearch, Typesense, Qdrant). Four independent workstreams clearly identified. |
| Architecture | HIGH | Direct codebase inspection. Component boundaries and data flow verified against actual code. Build order driven by real dependency analysis. |
| Pitfalls | HIGH | Pitfalls derived from actual codebase gaps (no WAL, no busy_timeout, single SQLite connection, sequential TEI). Empirical evidence (bs=4 = bs=32) informs concurrency skepticism. |

**Overall confidence:** HIGH

### Gaps to Address

- **Concurrent TEI throughput:** Empirical benchmark needed. The existing bs=4 vs bs=32 data strongly suggests no benefit, but a direct 1-vs-3 concurrent request test would confirm. Gate Phase 3 implementation on this benchmark.
- **GLiNER batch_predict_entities CPU performance:** Community reports are mixed. Some users see no improvement on CPU. Must profile on actual voicenotes data before committing to the batch approach. If no gain, keep sequential (simpler, known quantity).
- **BM25 rebuild memory at scale:** At 188k chunks, loading all chunk texts for BM25 rebuild may strain memory. No measurements exist yet. Monitor during Phase 4 initial deployment with the full corpus.
- **Background indexer + explicit index() mutual exclusion:** The design calls for pausing the background indexer when `POST /index` arrives. The exact locking mechanism (threading.Event vs Lock) needs implementation-time validation.

## Sources

### Primary (HIGH confidence)
- Direct codebase analysis: `pipeline.py`, `service.py`, `server.py`, `semantic.py`, `ner.py`, `file_tracker.py`, `config.py`, `sqlite_vec.py`, `cli.py`
- Production deployment: `/opt/docker/dotmd/`, `/opt/docker/embeddings/`, `/opt/docker/graphiti/`
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) -- depends_on conditions
- [SQLite WAL mode](https://www.sqlite.org/wal.html) -- concurrent read/write isolation
- [HTTPX async docs](https://www.python-httpx.org/async/) -- AsyncClient API
- [Python asyncio docs](https://docs.python.org/3/library/asyncio-task.html) -- create_task, to_thread, TaskGroup, Semaphore
- [FalkorDB Docker docs](https://docs.falkordb.com/operations/docker.html) -- healthcheck, persistence
- [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) -- background task patterns

### Secondary (MEDIUM confidence)
- [GLiNER batch_predict_entities](https://github.com/urchade/GLiNER/discussions/73) -- API confirmed, CPU performance uncertain
- [TEI healthcheck issue #427](https://github.com/huggingface/text-embeddings-inference/issues/427) -- `/health` endpoint behavior
- [FastAPI BackgroundTasks limitations](https://github.com/fastapi/fastapi/discussions/11210) -- event loop blocking
- [SQLite concurrent writes](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) -- WAL vs rollback journal

### Tertiary (LOW confidence)
- GLiNER batch inference CPU speedup -- community reports inconsistent, needs local benchmarking
- TEI concurrent request throughput on CPU -- inference suggests no benefit but not empirically verified for dotMD's specific workload

---
*Research completed: 2026-03-27*
*Ready for roadmap: yes*
