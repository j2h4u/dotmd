# Technology Stack

**Project:** dotMD v1.3 -- Production Packaging, Background Indexing, Speed Optimization, Smoke Tests
**Researched:** 2026-03-27
**Scope:** NEW additions only. Existing stack (Python 3.12, FastAPI, sqlite-vec, FalkorDB, TEI, GLiNER, rank_bm25, httpx, Click, Pydantic v2) is validated and not re-researched.

---

## Recommended Stack Additions

### 1. Background Indexing -- asyncio in FastAPI lifespan

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `asyncio` (stdlib) | Python 3.12+ | Background task loop for trickle indexer | Already in stdlib. `asyncio.create_task()` in the FastAPI lifespan context is the right pattern for long-running background work. FastAPI's `BackgroundTasks` is designed for fire-and-forget per-request tasks, not persistent loops. |
| `asyncio.to_thread()` (stdlib) | Python 3.12+ | Offload sync pipeline to thread | The indexing pipeline (`IndexingPipeline.index()`) is synchronous and CPU+IO bound. `asyncio.to_thread()` runs it in a thread pool without blocking the event loop, keeping the API responsive. No new dependencies. |

**Pattern:**

```python
# In FastAPI lifespan (server.py)
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _service
    _service = DotMDService(Settings())
    _service.warmup()
    # Start background indexer as a long-lived task
    indexer_task = asyncio.create_task(_background_indexer(_service))
    yield
    indexer_task.cancel()
    _service = None

async def _background_indexer(service: DotMDService) -> None:
    """Trickle-index pending files one at a time."""
    settings = service._settings
    while True:
        try:
            # Run sync pipeline in thread to avoid blocking event loop
            pending = await asyncio.to_thread(
                service._pipeline.file_tracker.count_pending
            )
            if pending > 0:
                await asyncio.to_thread(
                    service.index_one_pending_file
                )
            else:
                await asyncio.sleep(300)  # Check every 5 min when idle
        except asyncio.CancelledError:
            break
        except Exception:
            await asyncio.sleep(60)  # Back off on error
```

**Why NOT `BackgroundTasks`:** FastAPI BackgroundTasks runs after the response is sent and is tied to the request lifecycle. It has no status tracking, no result retrieval, and tasks die with the request. The trickle indexer is a server-lifetime background loop -- `asyncio.create_task()` in the lifespan is the correct abstraction.

**Why NOT Celery/ARQ/Redis queue:** Massive overkill for a single-server, single-worker scenario. The background indexer doesn't need persistence, retries, or horizontal scaling. It just needs to process one file at a time without blocking search requests. Adding a task queue would add Redis dependency complexity (separate from FalkorDB's Redis) for zero benefit.

**Why `asyncio.to_thread()` instead of `run_in_executor()`:** `to_thread()` (Python 3.9+) is the modern, simpler API. It uses the default ThreadPoolExecutor and propagates context variables. Functionally identical to `loop.run_in_executor(None, fn)` but cleaner syntax.

**GIL consideration:** The indexing pipeline is mixed CPU (GLiNER NER) and IO (TEI HTTP, SQLite, FalkorDB). `to_thread()` releases the GIL during IO waits (httpx, sqlite3 C calls) which is the majority of indexing time. CPU-bound NER portions will contend with the GIL but that's acceptable -- the indexer is deliberately low-priority and runs one file at a time.

**Confidence:** HIGH -- `asyncio.create_task()` in FastAPI lifespan is a well-documented pattern. Verified via FastAPI docs and multiple community examples.

---

### 2. Concurrent TEI Requests -- httpx.AsyncClient

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `httpx` (existing) | 0.28.1 (locked) | Async concurrent TEI embedding requests | Already a dependency. Current code uses `httpx.post()` (sync) for sequential batches. Switch to `httpx.AsyncClient` with `asyncio.Semaphore` for 2-3 concurrent requests. No version change needed. |

**Current bottleneck:** `_encode_via_tei()` in `semantic.py` sends batches sequentially via `httpx.post()`. Each batch waits for TEI to process and respond before the next batch is sent. At bs=4 and ~0.5-1.3 texts/sec, the pipeline stalls on IO wait between batches.

**Pattern:**

```python
async def _encode_via_tei_concurrent(
    self, inputs: list[str], max_concurrent: int = 3
) -> list[list[float]]:
    """Send embedding batches concurrently to TEI."""
    import httpx

    bs = self._tei_batch_size
    batches = [inputs[i:i+bs] for i in range(0, len(inputs), bs)]
    results: list[list[float]] = [[] for _ in batches]
    sem = asyncio.Semaphore(max_concurrent)

    async with httpx.AsyncClient(timeout=120.0) as client:
        async def _send(idx: int, batch: list[str]) -> None:
            async with sem:
                resp = await client.post(
                    f"{self._embedding_url}/embed",
                    json={"inputs": batch, "truncate": True},
                )
                resp.raise_for_status()
                results[idx] = resp.json()

        async with asyncio.TaskGroup() as tg:
            for i, batch in enumerate(batches):
                tg.create_task(_send(i, batch))

    return [vec for batch_result in results for vec in batch_result]
```

**Why `asyncio.Semaphore(3)` not unlimited:** TEI on CPU with `intfloat/multilingual-e5-large` (1024-dim) uses ~2.6GB RAM. Sending too many concurrent requests just fills TEI's internal queue and doesn't increase throughput -- the CPU is the bottleneck. 2-3 concurrent requests keeps the TEI queue fed (one processing, one or two waiting) without wasting memory on queued tensors.

**Why `asyncio.TaskGroup` (Python 3.11+):** Provides structured concurrency with proper error propagation. If any batch fails, all pending tasks are cancelled and the exception surfaces cleanly. Preferred over `asyncio.gather()` which has weaker cancellation semantics.

**Integration challenge:** The calling code (`IndexingPipeline._ingest_and_finalize()`) is synchronous. Two options:
1. **Option A (recommended):** Keep `encode_batch()` sync, add `encode_batch_concurrent()` as async, call from background indexer via `await`.
2. **Option B:** Use `asyncio.run()` inside the sync method -- creates a new event loop, works but prevents nesting if already in an async context.

Recommend Option A: the background indexer is already async, so it can `await` the concurrent encoding directly. The sync `encode_batch()` stays unchanged for CLI use.

**Confidence:** HIGH -- httpx AsyncClient is well-documented. Semaphore pattern for rate limiting is standard asyncio.

---

### 3. Batch NER (GLiNER) -- batch_predict_entities

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `gliner` (existing) | 0.2.26 (locked) | Batch NER inference | Already a dependency. GLiNER has `batch_predict_entities(texts, labels)` since v0.2.x. Current code calls `model.predict_entities()` one chunk at a time in a loop. Batch inference should reduce overhead from repeated model setup per call. |

**Current code (ner.py line 86):**
```python
for chunk in chunks:
    predictions = model.predict_entities(
        chunk.text, self._entity_types, threshold=self._threshold
    )
```

**Proposed change:**
```python
texts = [chunk.text for chunk in chunks]
# Process in batches of 16-32 to manage memory
batch_size = 16
all_predictions = []
for i in range(0, len(texts), batch_size):
    batch = texts[i:i+batch_size]
    batch_preds = model.batch_predict_entities(
        batch, self._entity_types,
        threshold=self._threshold, flat_ner=True,
    )
    all_predictions.extend(batch_preds)
```

**Caveat:** Community reports suggest `batch_predict_entities` may not always be faster than sequential on CPU, depending on text lengths and batch sizes. The overhead savings come from reduced Python loop iterations and potentially better tensor batching. This needs empirical validation on the actual dataset.

**Why batch_size=16 not larger:** On a Xeon E3 V2 with 16GB RAM (TEI already using ~2.6GB, FalkorDB ~0.5GB), GLiNER model + batch tensors need to fit in remaining memory. GLiNER multi-v2.1 is ~0.5GB. Batch of 16 texts at 512 tokens each is manageable; 64+ could cause memory pressure.

**Confidence:** MEDIUM -- `batch_predict_entities` method exists and is documented, but CPU performance improvement is not guaranteed. Needs profiling.

---

### 4. Docker Compose -- Self-Contained Stack

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| Docker Compose (existing) | v2 | Self-contained stack with healthchecks | No new tool. The current production compose depends on external networks (`embeddings_default`, `graphiti_default`). The self-contained stack bundles TEI and FalkorDB as services in the same compose file with proper healthchecks and `depends_on: condition: service_healthy`. |

**Self-contained docker-compose.yml pattern:**

```yaml
services:
  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    volumes:
      - tei-models:/data
    command: --model-id intfloat/multilingual-e5-large --huggingface-hub-cache /data
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:80/health"]
      interval: 15s
      timeout: 10s
      retries: 12
      start_period: 120s  # TEI model loading takes 60-90s on CPU
    deploy:
      resources:
        limits:
          memory: 4G

  falkordb:
    image: falkordb/falkordb:latest
    volumes:
      - falkordb-data:/var/lib/falkordb/data
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 10s

  api:
    build:
      context: ./backend
    depends_on:
      tei:
        condition: service_healthy
      falkordb:
        condition: service_healthy
    environment:
      DOTMD_EMBEDDING_URL: http://tei:80
      DOTMD_GRAPH_BACKEND: falkordb
      DOTMD_FALKORDB_URL: redis://falkordb:6379
      DOTMD_FALKORDB_GRAPH_NAME: dotmd
    # ... volumes, ports, etc.

volumes:
  tei-models:
  falkordb-data:
  dotmd-index:
```

**TEI healthcheck details:**
- Endpoint: `GET /health` returns 200 when ready, 503 otherwise.
- `start_period: 120s` is critical -- TEI needs 60-90s on CPU to download/load the model on first start. Without sufficient start_period, Docker marks it unhealthy and restarts it in a loop.
- Known issue: if `API_KEY` env var is set, `/health` returns 401. Not a concern here (no API key configured).
- `curl` must be available in the TEI image. The `cpu-1.6` image includes it.

**FalkorDB healthcheck details:**
- `redis-cli ping` returns PONG when ready. `redis-cli` is bundled in the FalkorDB image.
- `start_period: 10s` is sufficient -- FalkorDB starts in ~2s.

**`depends_on: condition: service_healthy`:**
- This is the modern Docker Compose v2 approach. Replaces the need for `wait-for-it.sh` or `dockerize` wrapper scripts.
- The `api` service won't start until both `tei` and `falkordb` report healthy.
- This eliminates the ConnectionError on startup when FalkorDB isn't ready yet.

**Why keep the external-network compose as well:** The production deployment on senbonzakura shares TEI and FalkorDB with other services (Graphiti, OpenClaw). The self-contained compose is for portable deployment (new server, CI, etc.). Both configs should be maintained:
- `docker-compose.yml` -- self-contained (repo default)
- `docker-compose.production.yml` -- production override using external networks

**Confidence:** HIGH -- Docker Compose healthcheck + depends_on condition is well-documented and widely used. TEI `/health` endpoint and FalkorDB `redis-cli ping` verified.

---

### 5. Smoke Tests -- pytest + httpx

| Technology | Version | Purpose | Why |
|------------|---------|---------|-----|
| `pytest` (existing) | >=8.0 (already in dev deps) | Test framework | Already a dev dependency. No change needed. |
| `pytest-asyncio` | >=0.24 | Async test support | Needed for testing async endpoints and background tasks. Provides `@pytest.mark.asyncio` and async fixtures. |
| `httpx` (existing) | 0.28.1 | HTTP client for smoke tests against running services | Already a dependency. Use `httpx.Client` (sync) for smoke tests against a running Docker stack. No need for `AsyncClient` in tests -- sync is simpler and sufficient for smoke checks. |

**Why NOT `pytest-docker` or `pytest-docker-compose`:**
The smoke tests target an already-running Docker stack, not a stack spun up per test session. Reasons:
1. TEI takes 60-90s to start on CPU. Spinning up per test run is impractical.
2. Full indexing (needed for meaningful smoke tests) takes minutes even for the small voicenotes corpus.
3. The tests validate a production-like deployment, not isolated units.

**Pattern -- conftest.py:**

```python
import os
import pytest
import httpx

DOTMD_API_URL = os.environ.get("DOTMD_API_URL", "http://localhost:8321")

@pytest.fixture(scope="session")
def api_url():
    """Base URL of a running dotMD API."""
    return DOTMD_API_URL

@pytest.fixture(scope="session")
def api_client(api_url):
    """httpx client pointed at running dotMD."""
    with httpx.Client(base_url=api_url, timeout=30.0) as client:
        # Verify the service is reachable
        resp = client.get("/status")
        if resp.status_code != 200:
            pytest.skip(f"dotMD API not reachable at {api_url}")
        yield client

def pytest_collection_modifyitems(config, items):
    """Auto-skip smoke tests when API is not available."""
    # Only applies to tests in tests/smoke/
    ...
```

**Pattern -- smoke test:**

```python
# tests/smoke/test_search_engines.py

def test_semantic_search_returns_results(api_client):
    resp = api_client.get("/search", params={"q": "meeting notes", "mode": "semantic"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["count"] > 0

def test_bm25_results_survive_reranker(api_client):
    """Regression guard for Phase 5 BM25 fix."""
    resp = api_client.get("/search", params={"q": "docker compose", "mode": "hybrid"})
    data = resp.json()
    bm25_present = any("bm25" in r["matched_engines"] for r in data["results"])
    assert bm25_present, "BM25 results missing from hybrid search -- Phase 5 regression"
```

**Test directory structure:**

```
backend/
  tests/
    __init__.py
    conftest.py          # shared fixtures (api_url, api_client)
    smoke/
      __init__.py
      test_api.py        # HTTP 200, valid JSON, status endpoint
      test_search.py     # All 3 engines, hybrid fusion, BM25 regression guard
      test_index.py      # Index status reports correct counts
```

**Running:**

```bash
# Against local Docker stack
cd backend && pytest tests/smoke/ -v

# Against custom URL
DOTMD_API_URL=http://192.168.1.100:8321 pytest tests/smoke/ -v

# Skip smoke tests (e.g. in CI without Docker)
pytest tests/ --ignore=tests/smoke/
```

**Why `pytest-asyncio`:** Even though smoke tests themselves are sync (httpx.Client against running API), the background indexer and concurrent TEI code will need async unit tests. Adding `pytest-asyncio` now enables both.

**Confidence:** HIGH -- pytest + httpx against running services is a standard integration test pattern. No exotic dependencies.

---

## What NOT to Add

| Avoid | Why | Use Instead |
|-------|-----|-------------|
| Celery / ARQ / Dramatiq | Overkill for single-server background indexing. Adds Redis queue dependency separate from FalkorDB. | `asyncio.create_task()` in FastAPI lifespan |
| `aiohttp` | Duplicate of httpx which is already a dependency. httpx supports both sync and async. | `httpx.AsyncClient` |
| `pytest-docker` / `pytest-docker-compose` | Spins up containers per test session. TEI takes 90s to start. Tests need pre-indexed data. | `httpx.Client` against already-running stack |
| `testcontainers-python` | Same problem as pytest-docker -- container startup too slow for TEI. | Skip-if-unavailable fixture pattern |
| `concurrent.futures.ProcessPoolExecutor` for NER | GLiNER model can't be pickled across processes easily. GIL contention from `to_thread()` is acceptable since NER is a minority of total indexing time (~30% vs ~60% for TEI). | `asyncio.to_thread()` for background; sequential NER in-thread |
| `asyncio.run()` inside sync methods | Creates nested event loops, conflicts with FastAPI's running loop. | `asyncio.to_thread()` to bridge sync/async boundary |
| `apscheduler` / `schedule` | Over-engineered for "run continuously, sleep between files" pattern. | Simple `while True` + `asyncio.sleep()` in lifespan task |
| `watchdog` (filesystem watcher) | Polling via FileTracker is sufficient. Watchdog adds inotify complexity and doesn't work well across Docker bind mounts. | `FileTracker.diff()` on timer |
| `multiprocessing` | GLiNER model sharing across processes is complex. Single-threaded NER is acceptable at trickle-indexer throughput (1 file at a time). | Single-threaded NER in background thread |

---

## Alternatives Considered

| Category | Recommended | Alternative | Why Not |
|----------|-------------|-------------|---------|
| Background tasks | `asyncio.create_task()` in lifespan | Celery + Redis | Single server, no horizontal scaling needed. Celery adds broker dependency and operational complexity. |
| Background tasks | `asyncio.create_task()` in lifespan | FastAPI `BackgroundTasks` | BackgroundTasks is per-request, not per-server-lifetime. No status tracking. Can't run a persistent loop. |
| Concurrent HTTP | `httpx.AsyncClient` + `Semaphore` | `aiohttp.ClientSession` | httpx already a dependency. Same async capabilities. Adding aiohttp duplicates HTTP client. |
| Concurrent HTTP | `asyncio.Semaphore(3)` | `httpx.Limits(max_connections=3)` | Semaphore gives explicit control per code path. httpx.Limits is connection-pool-level -- affects all requests through that client, not just TEI batches. |
| NER batching | `batch_predict_entities` | Keep sequential | Sequential is a known quantity. Batch may or may not be faster on CPU. Try batch, fall back to sequential if no improvement. |
| Test framework | pytest + httpx against running stack | `pytest-docker` spinning up stack | TEI startup (90s), indexing time (minutes) make per-session container lifecycle impractical. |
| Test framework | Skip-if-unavailable pattern | Hard requirement on running Docker | Tests should be runnable in any environment. Skip gracefully when services unavailable. |

---

## Installation Changes

### pyproject.toml additions

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

**That's it.** No new runtime dependencies. Everything else is stdlib (`asyncio`) or already installed (`httpx`, `gliner`).

### Why no new runtime dependencies

The four features map to existing capabilities:
1. **Background indexing:** `asyncio` (stdlib) + existing `IndexingPipeline`
2. **Concurrent TEI:** `httpx.AsyncClient` (already installed as 0.28.1)
3. **Batch NER:** `gliner.batch_predict_entities` (already installed as 0.2.26)
4. **Docker packaging:** Docker Compose config changes, not Python deps
5. **Smoke tests:** `pytest` + `httpx` (both already deps)

The only new pip install is `pytest-asyncio` in dev dependencies.

---

## Version Compatibility

| Package | Current Version | Required For | Compatible With Constraints |
|---------|----------------|--------------|----------------------------|
| `httpx` | 0.28.1 (locked) | AsyncClient for concurrent TEI | Yes -- AsyncClient stable since 0.23+ |
| `gliner` | 0.2.26 (locked) | `batch_predict_entities` | Yes -- method exists since 0.2.x |
| `pytest` | 9.0.2 (locked) | Smoke test framework | Yes -- no constraints |
| `pytest-asyncio` | >=0.24 (new dev dep) | Async test support | Yes -- requires pytest>=7.0, anyio>=3.0 (both satisfied) |
| `asyncio` | Python 3.12 stdlib | TaskGroup, to_thread, Semaphore | Yes -- TaskGroup since 3.11, to_thread since 3.9 |
| Docker Compose | v2 (system) | Healthchecks, depends_on conditions | Yes -- `condition: service_healthy` is Compose Spec |
| TEI | cpu-1.6 (production) | `/health` endpoint for healthcheck | Yes -- `/health` available since TEI 1.0 |
| FalkorDB | latest (production) | `redis-cli ping` for healthcheck | Yes -- Redis protocol, always available |

---

## Integration Points

### Background indexer <-> FastAPI API

The background indexer and API endpoints share the same `DotMDService` instance. Key considerations:

- **SQLite concurrent access:** sqlite3 in WAL mode supports concurrent readers + one writer. The indexer writes, API reads. No conflict as long as connections are on separate threads (which `to_thread()` ensures).
- **sqlite-vec:** Same SQLite connection concern. The vector store should use WAL mode.
- **FalkorDB:** Network-based, concurrent-safe. No issues.
- **BM25 index:** Currently a pickle file rebuilt on every index run. The background indexer must hold a lock or use atomic file replacement to avoid the API reading a partially-written pickle. Recommend: write to temp file, then `os.rename()` (atomic on Linux).
- **Status reporting:** `DotMDService.status()` already reads from metadata store. Background indexer progress can be exposed via the same mechanism -- add `background_indexing: bool` and `background_progress: str` fields to `IndexStats`.

### Concurrent TEI <-> Background indexer

The concurrent TEI encoding is called from within the background indexer's thread. Since the indexer runs in `asyncio.to_thread()`, it's in a non-async context. Two integration options:

1. **Recommended:** Background indexer loop is async. It calls `await _encode_via_tei_concurrent()` directly. The pipeline's sync methods are wrapped individually with `to_thread()` for the non-async parts (chunking, NER, graph population).
2. **Alternative:** Keep entire pipeline sync in one thread. Concurrent TEI is not used in background mode (trickle processes one file at a time -- batch concurrency is less impactful for small batches). Reserve concurrent TEI for `POST /index` endpoint for bulk re-indexing.

Recommend option 2 for v1.3 simplicity: the trickle indexer processes one file at a time (typically 2-5 chunks), so concurrent TEI offers minimal speedup. Concurrent TEI benefits large batch indexing (`dotmd index --force`) which is a separate code path.

### Smoke tests <-> Docker stack

Tests assume a running stack. The `conftest.py` uses a session-scoped fixture that checks service availability and skips all smoke tests if the API is unreachable. This means:
- `pytest tests/smoke/` works against production Docker stack
- `pytest tests/` in a clean environment skips smoke tests gracefully
- CI can run smoke tests by starting the self-contained compose first

---

## Sources

- [FastAPI Background Tasks docs](https://fastapi.tiangolo.com/tutorial/background-tasks/) -- BackgroundTasks limitations: per-request, no status tracking -- HIGH confidence
- [FastAPI BackgroundTasks vs Threads vs Async](https://hussainwali.medium.com/fastapi-backgroundtasks-vs-threads-vs-async-f0020540bb87) -- asyncio.create_task in lifespan for persistent loops -- MEDIUM confidence
- [How to Build Background Task Processing in FastAPI](https://oneuptime.com/blog/post/2026-01-25-background-task-processing-fastapi/view) -- confirms lifespan pattern -- MEDIUM confidence
- [HTTPX Async Support](https://www.python-httpx.org/async/) -- AsyncClient API, connection limits -- HIGH confidence
- [Limit concurrency with semaphore in Python asyncio](https://rednafi.com/python/limit_concurrency_with_semaphore/) -- Semaphore pattern for rate limiting concurrent requests -- HIGH confidence
- [Python asyncio.to_thread docs](https://docs.python.org/3/library/asyncio-task.html) -- bridges sync code to async context -- HIGH confidence
- [Python asyncio.TaskGroup docs](https://docs.python.org/3/library/asyncio-task.html) -- structured concurrency, Python 3.11+ -- HIGH confidence
- [GLiNER batch_predict_entities](https://github.com/urchade/GLiNER/discussions/73) -- batch method exists, community performance reports mixed on CPU -- MEDIUM confidence
- [GLiNER README](https://github.com/urchade/GLiNER) -- `batch_predict_entities(texts, labels, flat_ner, threshold)` signature -- HIGH confidence
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) -- depends_on with condition: service_healthy -- HIGH confidence
- [FalkorDB Docker docs](https://docs.falkordb.com/operations/docker.html) -- healthcheck with redis-cli ping -- HIGH confidence
- [TEI healthcheck issue #427](https://github.com/huggingface/text-embeddings-inference/issues/427) -- `/health` endpoint, API_KEY blocking concern -- HIGH confidence
- [FastAPI Async Tests docs](https://fastapi.tiangolo.com/advanced/async-tests/) -- httpx.AsyncClient with ASGITransport for in-process testing -- HIGH confidence
- [pytest-docker (avast)](https://github.com/avast/pytest-docker) -- v3.2.2, spins up containers per session -- considered and rejected for this project -- MEDIUM confidence
- Codebase inspection: `api/server.py`, `api/service.py`, `search/semantic.py`, `extraction/ner.py`, `ingestion/pipeline.py`, `core/config.py`, production docker-compose files -- PRIMARY source

---

*Stack research for: dotMD v1.3 Production Packaging, Background Indexing, Speed Optimization, Smoke Tests*
*Researched: 2026-03-27*
