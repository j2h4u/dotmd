# Feature Landscape

**Domain:** Production packaging, background indexing, speed optimization, smoke tests for a markdown knowledgebase search service
**Researched:** 2026-03-27
**Confidence:** HIGH (codebase analysis + domain research on comparable services)

---

## Table Stakes

Features users expect from a self-contained, production-ready search service. Missing any = "not ready for production use."

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| **Self-contained docker-compose stack** | MeiliSearch, Typesense, Qdrant all ship as `docker compose up` with zero external deps. Current dotMD depends on external TEI and graphiti_default network -- fragile and undocumented | MEDIUM | Add TEI and FalkorDB as services in the same compose file. Use `depends_on` with `condition: service_healthy` for startup ordering. Single `.env` for all config. |
| **Health checks on all services** | Standard pattern for multi-service compose. Without them, dotMD starts before TEI/FalkorDB are ready and crashes | LOW | TEI: `curl -f http://localhost:80/health`. FalkorDB: `redis-cli ping`. dotMD API: `curl -f http://localhost:8000/status`. |
| **ENV-based configuration with sane defaults** | Users expect `docker compose up` to work without editing files. Currently `DOTMD_EMBEDDING_URL` is required with no default | LOW | In self-contained compose, TEI URL defaults to `http://tei:80`. FalkorDB URL defaults to `redis://falkordb:6379`. Only data paths need user config. |
| **Background indexing without blocking search** | Core v1.3 deliverable. 13,500 files at ~50min/229 files means ~50 hours for full corpus. Cannot block queries during that time | HIGH | Must handle: concurrent read/write to SQLite (WAL mode), FalkorDB concurrent access (already works), BM25 index rebuild without stalling queries, graceful shutdown mid-index. |
| **Indexing progress visibility** | Users need to know indexing is happening, how far along, and when it will finish. Every comparable service (MeiliSearch, Elasticsearch) shows task progress | LOW | `dotmd status` already shows pending counts. Add: files indexed / total, estimated time remaining, current file being processed. Expose via `/status` API endpoint. |
| **Smoke tests for regression safety** | No tests exist. After 3 milestones of changes (sqlite-vec, TEI, FalkorDB, reranker fix), any code change risks silent regression | MEDIUM | Minimum: each engine returns results, hybrid fusion works, API returns 200, BM25 survives reranker. |
| **Graceful shutdown during background indexing** | SIGTERM during a 50-hour background index must not corrupt data | LOW | FileTracker updates fingerprints AFTER successful ingestion (already implemented). Background loop checks a shutdown flag between files. |

## Differentiators

Features that set dotMD apart or significantly improve the experience. Not expected, but valued.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| **Concurrent TEI requests (2-3 parallel)** | TEI supports request queuing internally. Current pipeline sends sequential HTTP requests, stalling on I/O wait between batches. 2-3 concurrent requests could improve throughput 1.5-2x by keeping TEI's internal queue fed | MEDIUM | Use `asyncio.Semaphore` + `httpx.AsyncClient` + `asyncio.gather()` in `_encode_via_tei`. Semaphore limits concurrency to 2-3. TEI handles backpressure via its own queue. Must preserve batch ordering for vector store alignment. |
| **GLiNER batch inference** | NER currently processes chunks one-at-a-time via `model.predict_entities(chunk.text, ...)`. GLiNER supports `batch_predict_entities()`. Could reduce 15min NER to ~5-8min by amortizing model overhead | MEDIUM | GLiNER batch API exists but has documented quirks -- some users report sequential being faster. Must benchmark on actual data. Bi-encoder GLiNER v2 models (knowledgator/gliner-bi-*) offer dramatically faster batch processing via pre-computed entity embeddings, but require model swap evaluation. |
| **TEI throughput calibration** | Auto-measure texts/sec across batch sizes, persist result to `tei_calibration.json`, reuse on subsequent runs. Avoids manual bs tuning | LOW | Already has batch size probe (halving on 413). Extend: time a few batches at different sizes, pick the fastest, save to disk. Re-calibrate if file is stale (>24h) or TEI returns errors. |
| **`dotmd test` CLI command** | Smoke tests runnable inside the Docker container without pytest dependency. `docker compose exec api dotmd test` -- instant regression check | LOW | Thin wrapper: index a handful of test markdown files, run each search mode, verify results, print pass/fail. No pytest needed in production image. |
| **NER skip for background trickle mode** | NER is 30% of indexing time (~15min for 229 files). For background trickle indexing of 13k files, skipping NER on first pass and backfilling later would make the index searchable via semantic+BM25 much sooner | MEDIUM | Add `--extract-depth structural` for background mode. Graph gets file/section nodes but no NER entities. Run NER backfill as a separate low-priority pass. Requires pipeline support for "enrich existing chunks" without re-embedding. |
| **Configurable background indexing rate** | Not just on/off -- users should control how aggressively background indexing runs (batch size, pause between files, CPU shares) | LOW | Environment variables: `DOTMD_BG_BATCH_SIZE=1`, `DOTMD_BG_PAUSE_SEC=2`, combined with `docker update --cpu-shares 2` for container-level priority. |
| **Index-while-search isolation via SQLite WAL** | SQLite WAL mode allows concurrent readers and one writer. Background indexer writes while search reads snapshots. Without WAL, background indexing would block search queries | LOW | Single pragma: `PRAGMA journal_mode=WAL`. SQLite provides snapshot isolation -- readers see consistent state even during writes. Must ensure WAL checkpointing doesn't grow unbounded during long index runs. |

## Anti-Features

Features to explicitly NOT build in v1.3.

| Anti-Feature | Why Avoid | What to Do Instead |
|--------------|-----------|-------------------|
| **Celery/Redis task queue for background indexing** | Massive dependency increase for a single-user service. FastAPI BackgroundTasks + threading is sufficient for the one-writer-many-readers pattern | Use `threading.Thread` with a shared shutdown `Event` for the background indexer. No message broker needed -- the "queue" is the list of unindexed files from FileTracker. |
| **Multi-worker uvicorn (--workers N)** | Each worker loads its own DotMDService with models (~2.6GB RAM). 16GB server cannot afford duplicated model memory | Single uvicorn worker. Background indexer runs in a separate thread within the same process, sharing the DotMDService instance. |
| **Async rewrite of the indexing pipeline** | Pipeline is inherently sequential (read -> chunk -> embed -> extract -> graph). asyncio adds complexity without enabling true parallelism for CPU-bound NER/extraction | Keep pipeline sync. Only add async for the TEI HTTP calls (I/O-bound). Use `asyncio.run()` from the sync pipeline to dispatch concurrent TEI requests. |
| **Real-time file watching (inotify/watchdog)** | Adds daemon complexity, edge cases with partial writes, Docker volume notification limitations. Overkill for daily voicenote sync | Poll-based: background indexer runs `FileTracker.diff()` periodically (every 5-10 min). Catches all changes with zero daemon overhead. |
| **Distributed indexing across multiple containers** | Single-user, single-server deployment. Horizontal scaling is irrelevant at 13k files | Single container, single indexer thread. Scale-up (faster CPU/GPU) is the path, not scale-out. |
| **pytest-docker / testcontainers for smoke tests** | Requires Docker-in-Docker or socket access. Adds complexity to CI. Smoke tests should run inside the existing containers | `dotmd test` command that runs against live services. For CI, use `docker compose up -d && docker compose exec api dotmd test`. |
| **Production-grade API auth/rate limiting** | Single-user, localhost-only service. Security theater adds no value | Keep `127.0.0.1` binding. If external access is needed later, put behind a reverse proxy (Caddy/nginx). |
| **Separate indexer service container** | A dedicated container for background indexing adds orchestration complexity (shared volumes, locking, separate health checks) | Background indexer runs as a thread inside the API container. Shares DotMDService, avoids SQLite locking issues across processes. |

---

## Feature Dependencies

```
[Self-contained docker-compose]
    |
    +-- TEI service + healthcheck
    |       |
    |       +--required by--> [dotMD API startup (depends_on: service_healthy)]
    |       +--required by--> [Concurrent TEI requests optimization]
    |       +--required by--> [TEI throughput calibration]
    |
    +-- FalkorDB service + healthcheck
    |       |
    |       +--required by--> [dotMD API startup]
    |       +--required by--> [Background indexer graph writes]
    |
    +-- ENV-based config with defaults
            |
            +--required by--> [Background indexer configuration]

[SQLite WAL mode]
    |
    +--required by--> [Background indexing while serving queries]
                           |
                           +-- [FileTracker.diff() for pending file discovery]
                           |       |
                           |       +--required by--> [Progress visibility in /status]
                           |
                           +-- [Graceful shutdown (Event flag)]
                           |
                           +-- [BM25 index swap (atomic replace)]
                           |
                           +-- [Configurable indexing rate]

[Smoke tests] -- INDEPENDENT of packaging/indexing
    |
    +-- [Test fixture markdown files]
    |       |
    |       +--required by--> [Per-engine verification]
    |       +--required by--> [Hybrid fusion verification]
    |       +--required by--> [BM25 regression guard]
    |
    +-- [dotmd test CLI command]
            |
            +--required by--> [API endpoint verification]

[Concurrent TEI requests] -- INDEPENDENT of background indexing
    |
    +-- [async httpx with Semaphore]
    |       |
    |       +--required by--> [Batch ordering preservation]
    |
    +-- Benefits both foreground and background indexing

[GLiNER batch inference] -- INDEPENDENT of everything else
    |
    +-- Must benchmark before committing
```

### Key Insight: Four independent workstreams

1. **Production packaging** (compose, healthchecks, config) -- foundational, do first
2. **Background indexing** (threading, WAL, progress, shutdown) -- depends on packaging
3. **Speed optimization** (concurrent TEI, GLiNER batch, calibration) -- independent, benefits all indexing
4. **Smoke tests** -- fully independent, can be done at any point

---

## MVP Recommendation

### Must Ship (v1.3 complete criteria)

**Priority 1 -- Production packaging:**
1. **Self-contained docker-compose.yml** -- TEI + FalkorDB + dotMD in one file
2. **Health checks** on all three services with `depends_on: condition: service_healthy`
3. **ENV defaults** -- `docker compose up` works with only data path configured
4. **`.env.example`** -- documented configuration template

**Priority 2 -- Background indexing:**
5. **Background trickle indexer** -- thread in API process, processes pending files
6. **SQLite WAL mode** -- concurrent read/write isolation
7. **BM25 index swap** -- atomic replacement so search queries get consistent results
8. **Progress reporting** -- `/status` endpoint shows indexing progress
9. **Graceful shutdown** -- clean stop mid-index on SIGTERM

**Priority 3 -- Speed optimization:**
10. **Concurrent TEI requests** -- 2-3 parallel via async httpx + semaphore
11. **TEI throughput calibration** -- auto-tune and persist best batch size

**Priority 4 -- Smoke tests:**
12. **`dotmd test` CLI command** -- verify all engines, fusion, API
13. **BM25 regression guard** -- specific test for the Phase 5 fix

### Defer to v1.4+

- GLiNER batch inference (needs benchmarking, may not help -- documented quirks)
- NER skip + backfill for background mode (optimization on top of working background indexer)
- GLiNER v2 bi-encoder model evaluation (significant model change, separate investigation)
- File watching via inotify/watchdog (polling is sufficient)
- `reranker_score` field on SearchResult (diagnostic, not user-facing)
- Graph-only re-index command (optimization, full re-index works)

---

## Comparison: Background Indexing Approaches

The key design decision for v1.3 is how the background indexer coexists with the API server.

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Thread in API process** | Shares DotMDService, no IPC, no SQLite cross-process locking, simplest deployment | GIL limits CPU parallelism (but indexing is I/O-bound on TEI calls), thread crash affects API | **Use this** -- GIL is a non-issue because the bottleneck is TEI HTTP I/O, not CPU |
| **Separate process (multiprocessing)** | True CPU parallelism, crash isolation | SQLite cross-process WAL coordination, FalkorDB connection sharing, doubled model memory (~2.6GB) | Reject -- memory budget cannot afford it |
| **Separate container** | Full isolation, independent scaling | Shared volume locking, duplicate model loading, orchestration complexity | Reject -- overkill for single-user |
| **Celery + Redis** | Production-grade queuing, retry, monitoring | Massive dependency, operational complexity, Redis already used by FalkorDB | Reject -- wrong abstraction for "process files from a list" |
| **FastAPI BackgroundTasks** | Zero setup, built-in | Runs in event loop, blocks other async handlers during CPU work, no progress tracking | Reject -- blocks API responses during NER/extraction |

### BM25 Index Swap Detail

The BM25 index is a pickle file loaded into memory. During background indexing, the index must be rebuilt after each batch of new files. The safe pattern:

1. Background thread builds new BM25 index from all chunks (including new ones)
2. Atomically swap the in-memory reference: `self._bm25_engine = new_engine`
3. Search threads that were mid-query still hold reference to old engine (safe -- Python GC)
4. Old engine is garbage collected when last reference drops

This is the same pattern MeiliSearch uses for index updates -- readers see a consistent snapshot, writers prepare the new version, swap is atomic.

---

## How Comparable Services Handle This

### Self-Contained Deployment

| Service | Pattern | What dotMD Should Copy |
|---------|---------|----------------------|
| **MeiliSearch** | Single binary, zero deps, `docker compose up` with one service | The aspiration -- but dotMD has 3 services (TEI, FalkorDB, API). Copy the "one compose file, one `.env`" UX. |
| **Typesense** | Single binary, zero deps, persistent volume for `/data` | Same as MeiliSearch. Confirms: users expect zero-config startup. |
| **Qdrant** | Single service + optional embedding sidecar. REST + gRPC | Closest to dotMD's architecture. Qdrant ships compose with the DB only; embedding is external. dotMD should go further and include TEI. |

### Background Indexing

| Service | Pattern | Applicable to dotMD? |
|---------|---------|---------------------|
| **Elasticsearch** | Bulk API accepts docs async, returns immediately, indexes in background. Segments merged independently. | Too complex for single-user. But the UX is right: submit docs, get immediate response, check progress. |
| **MeiliSearch** | POST /documents returns task ID immediately. Indexing happens async. GET /tasks/:id for progress. | Good UX model. dotMD could: POST /index returns immediately with task status, background thread processes, /status shows progress. |
| **Typesense** | Synchronous indexing via API, but very fast (no embeddings). | Not applicable -- dotMD's bottleneck is TEI embedding, not document parsing. |

### What "Production-Ready" Means

Based on MeiliSearch, Typesense, and Qdrant deployment patterns:

1. **Single command startup** -- `docker compose up -d` with zero manual steps
2. **Health endpoint** -- `/health` or `/status` for monitoring
3. **Data persistence** -- named volumes survive container recreation
4. **Graceful shutdown** -- SIGTERM handled, data flushed
5. **Configuration via ENV** -- no config files to mount
6. **Startup validation** -- verify deps (TEI, FalkorDB) reachable before accepting requests
7. **Logging** -- structured logs with correlation IDs (dotMD already has `run_id`)

dotMD already has items 2-5, 7. Missing: item 1 (self-contained compose) and item 6 (startup validation).

---

## Sources

- Direct codebase analysis: `pipeline.py` (indexing flow), `service.py` (DotMDService), `server.py` (FastAPI lifespan), `semantic.py` (TEI integration), `ner.py` (GLiNER per-chunk processing), `file_tracker.py` (change detection), `config.py` (Settings), `cli.py` (commands)
- Production deployment: `/opt/docker/dotmd/docker-compose.yml` (current external network deps)
- [MeiliSearch Docker deployment](https://meilisearch.com/docs/guides/docker) -- self-contained compose pattern
- [Typesense Docker deployment](https://typesense.org/docs/guide/install-typesense.html) -- single-binary deployment model
- [Qdrant self-hosted](https://github.com/AiratTop/qdrant-self-hosted) -- compose with management scripts
- [Docker Compose healthcheck + depends_on](https://docs.docker.com/compose/how-tos/startup-order/) -- service_healthy pattern
- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/) -- limitations for CPU-bound work
- [FastAPI background tasks discussion #11210](https://github.com/fastapi/fastapi/discussions/11210) -- blocks event loop
- [SQLite WAL mode](https://www.sqlite.org/wal.html) -- concurrent read/write isolation
- [SQLite WAL read concurrency](https://fly.io/blog/sqlite-internals-wal/) -- snapshot isolation details
- [HuggingFace TEI](https://github.com/huggingface/text-embeddings-inference) -- request queuing, CPU performance
- [TEI CPU slow inference #31](https://github.com/huggingface/text-embeddings-inference/issues/31) -- CPU throughput limitations
- [GLiNER batch processing discussion #73](https://github.com/urchade/GLiNER/discussions/73) -- batch API, sequential-may-be-faster caveat
- [GLiNER inference speedup #88](https://github.com/urchade/GLiNER/issues/88) -- optimization strategies
- [httpx async with semaphore](https://www.python-httpx.org/async/) -- concurrent HTTP pattern
- [pytest-docker](https://github.com/avast/pytest-docker) -- evaluated and rejected for smoke tests
- v1.3 memory notes: `project_v13_plans.md`, `dotmd_deployment.md`
- v1.3 todos: `2026-03-27-background-trickle-indexer.md`, `2026-03-27-smoke-tests.md`

---
*Feature research for: dotMD v1.3 Production Packaging & Background Indexing*
*Researched: 2026-03-27*
