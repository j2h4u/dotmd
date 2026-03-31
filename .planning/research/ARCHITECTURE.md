# Architecture Research: v1.3 Production Packaging, Background Indexing, Speed Optimization, Smoke Tests

**Domain:** Production hardening and background processing for existing multi-store search pipeline
**Researched:** 2026-03-27
**Confidence:** HIGH (direct codebase analysis + verified library APIs + infrastructure inspection)

## Current Architecture (Post-v1.2)

```
                         ┌─────────────────────────────────────────────┐
                         │              Entry Points                    │
                         │  CLI (cli.py)  API (server.py)  MCP (mcp)  │
                         └────────────────────┬────────────────────────┘
                                              │
                         ┌────────────────────▼────────────────────────┐
                         │          DotMDService (api/service.py)       │
                         │  Public facade: index(), search(), status()  │
                         └────┬───────────────┬────────────────────────┘
                              │               │
               ┌──────────────▼──┐    ┌───────▼────────────────────┐
               │ IndexingPipeline │    │  Search Stack               │
               │ (pipeline.py)    │    │  SemanticSearchEngine       │
               │                  │    │  BM25SearchEngine           │
               │  discover_files  │    │  GraphSearchEngine          │
               │  chunk_file      │    │  QueryExpander + Reranker   │
               │  encode_batch    │    │  fuse_results (RRF)         │
               │  run_extraction  │    └────────────────────────────┘
               │  populate_graph  │
               └──┬───┬───┬──────┘
                  │   │   │
     ┌────────────▼┐ ┌▼───▼──────────────────────────┐
     │ Extractors   │ │ Storage Backends               │
     │  Structural  │ │  SQLiteVecVectorStore (local)  │
     │  NER/GLiNER  │ │  SQLiteMetadataStore (local)   │
     │  KeyTerms    │ │  FalkorDBGraphStore (network)   │
     └──────────────┘ │  BM25 pickle (local)            │
                      └────────────────────────────────┘

External Services (Docker):
  TEI (embeddings:80) ── embeddings_default network
  FalkorDB (falkordb:6379) ── graphiti_default network
```

### Key Properties for v1.3 Integration

1. **IndexingPipeline.index() is synchronous and blocking.** Called from sync `DotMDService.index()`. The FastAPI endpoints call sync code from async handlers (Starlette runs them in a threadpool).

2. **TEI calls are synchronous httpx.** `_encode_via_tei()` in `semantic.py` uses `httpx.post()` (sync), processes batches sequentially in a for-loop. Each batch blocks until TEI responds.

3. **GLiNER NER is single-chunk.** `NERExtractor.extract()` iterates `for chunk in chunks: model.predict_entities(chunk.text, ...)` -- one chunk per inference call.

4. **BM25 always does full rebuild.** After ingesting new chunks, the pipeline loads ALL chunks from metadata and rebuilds the BM25 index. This is correct but means BM25 rebuild cost grows with corpus size.

5. **FileTracker provides diff but not "untracked" discovery.** `diff()` compares discovered files against stored fingerprints. Files not yet in the fingerprint table appear as "new". This is exactly what a background indexer needs.

6. **Docker compose depends on 2 external networks.** `embeddings_default` (TEI) and `graphiti_default` (FalkorDB) are created by separate compose projects. Not self-contained.

---

## Feature 1: Self-Contained Docker Compose

### What Changes

**Current:** 3 separate compose projects (dotmd, embeddings, graphiti), 2 external networks, manual orchestration.

**Target:** Single `docker-compose.yml` that starts all 3 services. `docker compose up` is the only command needed.

### Architecture Decision: Compose Profiles Over Single File

Use Docker Compose **profiles** to keep the self-contained stack while allowing existing shared-service deployments.

```yaml
# docker-compose.yml (in repo, replaces /opt/docker/dotmd/ version)
services:
  api:
    build:
      context: ./backend
    ports:
      - "127.0.0.1:8321:8000"
    volumes:
      - dotmd-index:/dotmd-index
      - dotmd-hf-models:/root/.cache/huggingface
    environment:
      - DOTMD_DATA_DIR=/mnt
      - DOTMD_INDEX_DIR=/dotmd-index
      - DOTMD_EMBEDDING_URL=http://tei:80
      - DOTMD_EMBEDDING_DIM=1024
      - DOTMD_GRAPH_BACKEND=falkordb
      - DOTMD_FALKORDB_URL=redis://falkordb:6379
    depends_on:
      tei:
        condition: service_healthy
      falkordb:
        condition: service_healthy
    command: ["serve", "--host", "0.0.0.0"]

  tei:
    image: ghcr.io/huggingface/text-embeddings-inference:cpu-1.6
    volumes:
      - tei-models:/data
    command: --model-id intfloat/multilingual-e5-large --huggingface-hub-cache /data
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:80/health"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 120s  # TEI model download can be slow on first run
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
      interval: 5s
      timeout: 3s
      retries: 5

volumes:
  dotmd-index:
  dotmd-hf-models:
  tei-models:
  falkordb-data:
```

### Integration Points

| Component | What Changes | What Stays |
|-----------|-------------|------------|
| `docker-compose.yml` | **NEW** self-contained file in repo root (replaces production `/opt/docker/dotmd/` version) | Dockerfile unchanged |
| `Dockerfile` | No changes needed | Multi-stage build, CPU-only PyTorch |
| `core/config.py` | No changes | Env vars already work via pydantic-settings |
| `/opt/docker/dotmd/` | Production deployment uses repo's compose file (symlink or copy) | Volume mounts configured per-deployment |

### Network Simplification

Self-contained compose creates a single default network. All three services (api, tei, falkordb) are on it. No external networks needed.

For deployments where TEI/FalkorDB are shared with other services: override with `docker-compose.override.yml` that adds external networks and removes the bundled tei/falkordb services.

### Healthcheck Dependency Chain

```
falkordb (ready in ~3s)
    ↓ service_healthy
tei (ready in 60-120s, model download on first run)
    ↓ service_healthy
api (starts after both healthy, warmup() loads BM25 + reranker)
```

TEI is the long pole -- first start downloads ~1.2GB model. Subsequent starts load from volume cache (~30s). The `start_period: 120s` prevents premature failure during download.

### Data Volume Mounts

Data directories (`/mnt/voicenotes`, `/mnt/home`) are deployment-specific. Keep them out of the base compose file. Operators add via:
- `docker-compose.override.yml` (production)
- `-v` flag (ad-hoc)
- `.env` file with volume source paths

---

## Feature 2: Background Trickle Indexer

### Architecture Decision: Background Thread in Server Process

Three options considered:

| Option | Mechanism | Pros | Cons |
|--------|-----------|------|------|
| **A: Separate CLI command** | `dotmd index --background` as standalone process | Simple, no server changes | Separate process, can't share DotMDService, concurrent SQLite writes |
| **B: Background thread in server** | Thread started during FastAPI lifespan | Shares DotMDService, no concurrent access issues, progress via API | Tighter coupling, must yield for search requests |
| **C: Celery/external queue** | Worker process + message broker | Proper job queue, retries | Massive overkill for single-server, adds Redis dependency complexity |

**Choose Option B** because:
1. DotMDService is the single facade -- sharing it avoids concurrent SQLite issues.
2. FalkorDB is network-based (concurrent OK), but SQLite metadata/vec stores are file-based. Having one process own them eliminates locking concerns.
3. Progress reporting via `GET /status` is natural -- the background thread updates shared state.
4. `docker update --cpu-shares 2` throttles the entire container, which is what we want.

### New Component: `ingestion/background.py`

```
DotMDService (api/service.py)
    │
    ├── IndexingPipeline        (existing, unchanged)
    │
    └── BackgroundIndexer (NEW)
            │
            ├── uses: IndexingPipeline._ingest_and_finalize() (per-file)
            ├── uses: FileTracker.diff() (discover pending files)
            ├── state: BackgroundIndexerState (progress, is_running, current_file)
            └── control: start(), stop(), pause()
```

### How It Integrates with IndexingPipeline

The background indexer does NOT call `pipeline.index()` (which does full diff + bulk ingest). Instead, it:

1. Calls `discover_files(data_dir)` to get all files.
2. Calls `file_tracker.diff(files)` to identify `diff.new` (unindexed files).
3. Processes files **one at a time** through the existing pipeline stages:
   - `read_file()` + `chunk_file()` per file
   - `semantic_engine.encode_batch()` for that file's chunks
   - `_run_extraction()` for that file's chunks
   - `_populate_graph()` for that file's entities/relations
   - `metadata_store.save_chunks()` for that file's chunks
   - `vector_store.add_chunks()` for that file's embeddings
   - `file_tracker.save_fingerprint()` after success
4. Periodically rebuilds BM25 index (every N files, not per-file -- BM25 rebuild is O(total_chunks)).

### What Needs to Be Extracted from Pipeline

Currently, `_ingest_and_finalize()` does everything in bulk. The background indexer needs **per-file granularity**. Two approaches:

**Approach A: Extract a `_process_single_file()` method from pipeline.**
Add a new method to `IndexingPipeline` that processes exactly one file through all stages. The background indexer calls this in a loop. BM25 rebuild happens separately.

**Approach B: Background indexer calls individual pipeline stages directly.**
The background indexer accesses `pipeline.metadata_store`, `pipeline.vector_store`, `pipeline.semantic_engine`, etc. through the existing property accessors and orchestrates them itself.

**Choose Approach A** because it keeps pipeline internals encapsulated. The background indexer only needs:
- `pipeline.process_file(file_info) -> FileIndexResult` (new method)
- `pipeline.rebuild_bm25()` (extract from `_ingest_and_finalize`)
- `pipeline.file_tracker.diff(files)` (existing)

### Data Flow: Background Indexing

```
BackgroundIndexer (thread)
    │
    │  every cycle_interval (e.g. 60s):
    │
    ├─ discover_files(data_dir) → all FileInfo
    ├─ file_tracker.diff(all) → FileDiff
    ├─ for file in diff.new[:batch_size]:
    │      pipeline.process_file(file)
    │      update progress state
    │      sleep(inter_file_delay)
    │
    ├─ if files_since_last_bm25_rebuild >= N:
    │      pipeline.rebuild_bm25()
    │
    └─ sleep(cycle_interval)
```

### State and Progress Reporting

```python
@dataclass
class BackgroundIndexerState:
    is_running: bool = False
    total_pending: int = 0
    files_processed: int = 0
    current_file: str | None = None
    last_error: str | None = None
    started_at: datetime | None = None
```

Exposed via `DotMDService.status()` -- extend `IndexStats` or add a separate field. The API's `GET /status` already returns `IndexStats`; add background indexer fields.

### Server Lifespan Integration

```python
# api/server.py modification
@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    global _service
    _service = DotMDService(Settings())
    _service.warmup()

    # Start background indexer if data_dir is configured
    settings = _service._settings
    if settings.data_dir != Path("."):
        _service.start_background_indexer()

    yield

    _service.stop_background_indexer()
    _service = None
```

### Thread Safety Considerations

| Resource | Thread Safety | Mitigation |
|----------|-------------|------------|
| SQLite metadata | WAL mode allows concurrent reads + single writer | Background indexer is only writer during trickle; API `index()` endpoint should refuse while background is running, or pause background |
| sqlite-vec | Same SQLite file, same WAL rules | Same as above |
| FalkorDB | Fully concurrent (Redis protocol) | No issues |
| BM25 pickle | In-memory dict, rebuilt periodically | Use threading.Lock around BM25 rebuild; search reads are safe (Python GIL protects dict reads) |
| GLiNER model | CPU inference, GIL-bound | Background indexer and search don't compete (search doesn't use GLiNER) |

### Key Design Constraint: No Concurrent `index()` Calls

The `POST /index` API endpoint and the background indexer must not run simultaneously. The background indexer should **pause** when an explicit `index()` call arrives, and **resume** after it completes. This avoids two writers to SQLite.

Implementation: a `threading.Event` or `threading.Lock` that the background indexer respects.

---

## Feature 3: Concurrent TEI Requests (Speed Optimization)

### Current Bottleneck

```
Pipeline._ingest_and_finalize()
    │
    └── semantic_engine.encode_batch(texts)  # ALL texts at once
            │
            └── _encode_via_tei(texts)
                    │
                    for i in range(0, len(texts), bs):    # sequential batches
                        batch = texts[i:i+bs]
                        httpx.post(TEI_URL, batch)        # BLOCKS until response
                        results.extend(response)
```

With 532 chunks, bs=4: 133 sequential HTTP requests. Each request: ~2-4s (TEI CPU inference). Total: ~30 min. During each request, the pipeline thread is idle waiting for the response.

### Architecture Decision: asyncio.Semaphore + httpx.AsyncClient

TEI already queues requests internally. Sending 2-3 concurrent requests means the next batch starts encoding while the previous is still returning. The pipeline doesn't need to wait for each response sequentially.

**Where the change lives:** `search/semantic.py`, specifically `_encode_via_tei()`.

**What stays the same:** The `encode_batch(texts)` public API remains synchronous. The internal implementation becomes async but is called from sync code via `asyncio.run()`.

### Implementation Pattern

```python
# search/semantic.py -- modified _encode_via_tei

async def _encode_via_tei_async(self, inputs: list[str]) -> list[list[float]]:
    """Concurrent TEI embedding with bounded parallelism."""
    import httpx

    bs = self._tei_batch_size
    semaphore = asyncio.Semaphore(self._tei_concurrency)  # default: 3
    results: list[tuple[int, list[list[float]]]] = []

    async with httpx.AsyncClient(timeout=120.0) as client:
        async def _embed_batch(batch_idx: int, batch: list[str]):
            async with semaphore:
                resp = await client.post(
                    f"{self._embedding_url}/embed",
                    json={"inputs": batch, "truncate": True},
                )
                resp.raise_for_status()
                results.append((batch_idx, resp.json()))

        tasks = []
        for batch_idx, i in enumerate(range(0, len(inputs), bs)):
            batch = inputs[i:i + bs]
            tasks.append(_embed_batch(batch_idx, batch))

        await asyncio.gather(*tasks)

    # Reassemble in order
    results.sort(key=lambda x: x[0])
    return [vec for _, vecs in results for vec in vecs]

def _encode_via_tei(self, inputs: list[str]) -> list[list[float]]:
    """Sync wrapper around async TEI encoding."""
    if isinstance(inputs, str):
        inputs = [inputs]
    # ... probe batch size (existing) ...
    return asyncio.run(self._encode_via_tei_async(inputs))
```

### New Config Field

```python
# core/config.py
tei_concurrency: int = 3  # max concurrent TEI requests
```

Environment variable: `DOTMD_TEI_CONCURRENCY`.

### Expected Speedup

With concurrency=3 and bs=4, 3 batches are in-flight simultaneously. TEI on CPU processes them in a queue. The pipeline waits for the slowest batch in each wave of 3, not for each individually.

Empirical TEI throughput: ~0.5-1.3 texts/sec. With 3x concurrency, expect 1.5-3.9 texts/sec if TEI can parallelize internally (it can -- it uses Rust tokio async). Conservative estimate: **1.5-2x speedup** (TEI CPU is still the bottleneck, but HTTP round-trip overhead is eliminated).

### Integration Points

| Component | Change |
|-----------|--------|
| `search/semantic.py` | Add `_encode_via_tei_async()`, modify `_encode_via_tei()` to use it, add `_tei_concurrency` param |
| `core/config.py` | Add `tei_concurrency: int = 3` |
| `ingestion/pipeline.py` | Pass `tei_concurrency` to SemanticSearchEngine constructor |
| `api/service.py` | Pass `tei_concurrency` to SemanticSearchEngine constructor |

### Caveat: asyncio.run() in Background Thread

If the background indexer runs in a thread and the FastAPI event loop is on the main thread, `asyncio.run()` creates a new event loop per call. This is fine -- `asyncio.run()` is designed for calling async code from sync contexts. Each `encode_batch()` call gets its own temporary event loop.

Alternative: if running inside FastAPI's event loop already, use `await` directly. But since `IndexingPipeline` is sync code called from a thread, `asyncio.run()` is the correct pattern.

---

## Feature 4: Batch NER (GLiNER)

### Current State

```python
# extraction/ner.py line 86
for chunk in chunks:
    predictions = model.predict_entities(chunk.text, self._entity_types, threshold=...)
```

One inference call per chunk. For 532 chunks, 532 forward passes.

### Change: Use `batch_predict_entities`

GLiNER provides `batch_predict_entities(texts, labels, threshold=...)` which processes multiple texts in a single forward pass with padding and batching.

```python
# extraction/ner.py -- modified extract()
def extract(self, chunks: list[Chunk]) -> ExtractionResult:
    model = self._get_model()
    texts = [chunk.text for chunk in chunks]

    # Batch inference
    all_predictions = model.batch_predict_entities(
        texts, self._entity_types, threshold=self._threshold,
    )

    # all_predictions is list[list[dict]] -- one inner list per text
    for chunk, predictions in zip(chunks, all_predictions):
        # ... existing per-chunk entity/relation logic (unchanged) ...
```

### Integration Points

| Component | Change |
|-----------|--------|
| `extraction/ner.py` | Replace per-chunk loop with `batch_predict_entities()` call, keep post-processing logic identical |

### Expected Speedup

GLiNER batch inference uses sequence packing (since v0.2.23). For 532 chunks, batching into groups of 8-16 reduces Python loop overhead and enables GPU-style parallelism even on CPU. Conservative estimate: **2-3x speedup** on the NER stage (~15 min -> ~5-7 min).

### Caveat: Memory

Batch inference loads all chunk texts into memory at once for padding. With 532 chunks averaging ~300 tokens each, this is ~160K tokens -- well within 16GB RAM. For the full 13.5K file corpus (~188K chunks), the background indexer processes one file at a time so this is not a concern.

For explicit `dotmd index --force` on the full corpus, consider chunking the batch_predict call into groups of 64-128 chunks to bound memory.

---

## Feature 5: Smoke Tests

### Architecture Decision: pytest Integration Tests Against Running Stack

Two options:

| Option | Mechanism | Pros | Cons |
|--------|-----------|------|------|
| **A: `dotmd test` CLI command** | Built into CLI, runs inside container | No pytest dependency, tests exactly what's deployed | Limited assertion framework, no parallelism, hard to extend |
| **B: pytest with docker fixtures** | `tests/smoke/` directory, pytest-docker or manual compose | Rich assertions, standard tooling, CI-ready | Requires running stack, slower to set up |

**Choose Option B** because:
1. pytest is already a dev dependency and 9 test files exist.
2. Smoke tests need a running TEI + FalkorDB + indexed data -- this is inherently an integration test.
3. pytest fixtures can manage the lifecycle (or assume stack is already running via `DOTMD_SMOKE_TEST_URL`).

### Test Structure

```
backend/tests/
├── conftest.py              # existing unit test fixtures
├── test_*.py                # existing unit tests (9 files)
└── smoke/
    ├── conftest.py          # smoke test fixtures (API client, skip if stack not running)
    ├── test_search_engines.py   # each engine returns results
    ├── test_hybrid_fusion.py    # hybrid mode fuses multiple engines
    ├── test_api_endpoints.py    # HTTP 200, valid JSON
    ├── test_bm25_survival.py    # BM25-only matches survive reranking
    └── test_status.py           # status reports correct backend and counts
```

### Smoke Test Fixtures

```python
# tests/smoke/conftest.py
import httpx
import pytest

DOTMD_URL = os.environ.get("DOTMD_SMOKE_TEST_URL", "http://localhost:8321")

@pytest.fixture(scope="session")
def api_url():
    """Base URL for the running dotMD API."""
    try:
        resp = httpx.get(f"{DOTMD_URL}/status", timeout=5.0)
        resp.raise_for_status()
    except (httpx.ConnectError, httpx.TimeoutException):
        pytest.skip(f"dotMD API not reachable at {DOTMD_URL}")
    return DOTMD_URL

@pytest.fixture(scope="session")
def api_client(api_url):
    """httpx client pointed at running API."""
    with httpx.Client(base_url=api_url, timeout=30.0) as client:
        yield client
```

### What Each Test Verifies

| Test | What | Guard Against |
|------|------|---------------|
| `test_search_engines` | Each mode (semantic, bm25, graph) returns >0 results for a known query | Engine silently returning empty (warmup bug, index not loaded) |
| `test_hybrid_fusion` | Hybrid returns results with `matched_engines` containing multiple engines | Fusion logic dropping an engine |
| `test_api_endpoints` | GET /status, GET /search, GET /graph return 200 with valid JSON | Serialization errors, startup failures |
| `test_bm25_survival` | A known keyword-only query returns BM25 match in hybrid mode | v1.2 Phase 5 regression -- reranker eliminating BM25 results |
| `test_status` | Status reports `graph: falkordb`, non-zero counts | Config not propagating, metadata store empty |

### Integration Points

| Component | Change |
|-----------|--------|
| `backend/tests/smoke/` | **NEW** directory with 5 test files + conftest |
| `pyproject.toml` | Add pytest mark registration for `smoke` |
| `docker-compose.yml` | Add healthcheck for api service (enables `depends_on: condition: service_healthy` in test orchestration) |

### Running Smoke Tests

```bash
# Against running stack (default: localhost:8321)
cd backend && pytest tests/smoke/ -v

# Against specific URL
DOTMD_SMOKE_TEST_URL=http://192.168.1.10:8321 pytest tests/smoke/ -v

# Skip smoke tests in regular test runs
pytest tests/ --ignore=tests/smoke/
```

---

## Integration Points Summary

### New Files

| File | Purpose | Depends On |
|------|---------|------------|
| `ingestion/background.py` | BackgroundIndexer class (thread-based trickle indexer) | IndexingPipeline, FileTracker |
| `docker-compose.yml` (repo root) | Self-contained stack: api + tei + falkordb | Dockerfile (existing) |
| `tests/smoke/conftest.py` | Smoke test fixtures (API client, skip logic) | Running stack |
| `tests/smoke/test_search_engines.py` | Engine-level smoke tests | conftest.py |
| `tests/smoke/test_hybrid_fusion.py` | Fusion smoke tests | conftest.py |
| `tests/smoke/test_api_endpoints.py` | API endpoint smoke tests | conftest.py |
| `tests/smoke/test_bm25_survival.py` | BM25 regression guard | conftest.py |
| `tests/smoke/test_status.py` | Status endpoint smoke tests | conftest.py |

### Modified Files

| File | Change | Scope |
|------|--------|-------|
| `search/semantic.py` | Add `_encode_via_tei_async()` for concurrent TEI, accept `tei_concurrency` param | ~40 lines added, `_encode_via_tei` refactored |
| `extraction/ner.py` | Replace per-chunk loop with `batch_predict_entities()` | ~10 lines changed in `extract()` |
| `core/config.py` | Add `tei_concurrency: int = 3` | 1 new field |
| `ingestion/pipeline.py` | Extract `process_file()` and `rebuild_bm25()` methods from `_ingest_and_finalize()` | ~60 lines refactored, no logic change |
| `api/service.py` | Add `start_background_indexer()`, `stop_background_indexer()`, extend `status()` with background progress | ~30 lines added |
| `api/server.py` | Start/stop background indexer in lifespan | ~8 lines added |
| `core/models.py` | Add background indexer state fields to `IndexStats` (or new model) | ~10 lines |
| `pyproject.toml` | Add `pytest` marker for smoke, ensure `httpx` in test deps | ~3 lines |

### Unchanged Files

| File | Why Unchanged |
|------|---------------|
| `Dockerfile` | Multi-stage build works as-is, no new system deps needed |
| `storage/*.py` | All storage backends unchanged -- background indexer uses them through pipeline |
| `search/bm25.py` | BM25 engine unchanged -- rebuild called from pipeline |
| `search/fusion.py` | RRF fusion unchanged |
| `search/graph_search.py` | Graph search unchanged |
| `search/reranker.py` | Reranker unchanged |
| `search/query.py` | Query expansion unchanged |
| `ingestion/reader.py` | File discovery unchanged |
| `ingestion/chunker.py` | Chunking unchanged |
| `ingestion/file_tracker.py` | FileTracker unchanged -- background indexer uses existing `diff()` and `save_fingerprint()` |
| `extraction/structural.py` | Structural extractor unchanged |
| `extraction/keyterms.py` | Key term extractor unchanged |
| `cli.py` | No CLI changes needed (background indexer is server-only) |
| `mcp_server.py` | MCP server unchanged |

---

## Suggested Build Order

Dependencies drive the order. Each phase is independently testable and deployable.

```
Phase 1: Self-Contained Docker Compose (foundation, unblocks everything else)
    1a. Create repo-root docker-compose.yml with api + tei + falkordb
    1b. Add healthchecks for all 3 services
    1c. Add docker-compose.override.yml.example for production volume mounts
    1d. Test: docker compose up from clean state, verify all services healthy
    1e. Deploy: replace /opt/docker/dotmd/ with new compose

    WHY FIRST: Every other feature needs a running stack to test against.
    Healthchecks are prerequisite for reliable smoke tests.
    No code changes -- only Docker configuration.

Phase 2: Smoke Tests (safety net before refactoring)
    2a. Create tests/smoke/ directory with conftest.py
    2b. Implement 5 test files against running API
    2c. Verify all pass against current deployment
    2d. Add pytest marker registration to pyproject.toml

    WHY SECOND: Establishes regression safety before touching pipeline code.
    Tests catch if Phases 3-4 break anything.
    No production code changes -- only test code.

Phase 3: Speed Optimization (independent, lower risk)
    3a. Add tei_concurrency config field
    3b. Implement _encode_via_tei_async() with asyncio.Semaphore
    3c. Refactor _encode_via_tei() to use async version
    3d. Replace GLiNER per-chunk loop with batch_predict_entities()
    3e. Run smoke tests to verify no regressions
    3f. Benchmark: full re-index before/after

    WHY THIRD: Self-contained changes in semantic.py and ner.py.
    Directly benefits Phase 4 (background indexer processes files faster).
    Smoke tests from Phase 2 catch regressions.

Phase 4: Background Trickle Indexer (highest complexity)
    4a. Extract process_file() and rebuild_bm25() from IndexingPipeline
    4b. Implement BackgroundIndexer in ingestion/background.py
    4c. Add start/stop methods to DotMDService
    4d. Integrate into FastAPI lifespan
    4e. Extend status() with background progress
    4f. Run smoke tests to verify search still works during background indexing
    4g. Start trickle indexing of full 13.5K file corpus

    WHY LAST: Depends on Phase 1 (stack running), Phase 2 (tests), Phase 3 (speed).
    Highest risk -- refactors pipeline internals.
    Benefits from speed optimizations already being in place.
```

### Phase Dependencies

```
Phase 1 (Docker Compose)
    ↓
Phase 2 (Smoke Tests) ── uses running stack from Phase 1
    ↓
Phase 3 (Speed Optimization) ── tested by Phase 2 smoke tests
    ↓
Phase 4 (Background Indexer) ── uses speed from Phase 3, tested by Phase 2
```

Phase 3 could technically run in parallel with Phase 2, but having smoke tests first provides the safety net for the semantic.py and ner.py refactors.

---

## Anti-Patterns to Avoid

### Anti-Pattern 1: Background Indexer as Separate Process

**What people do:** Run a second `dotmd index --background` process alongside `dotmd serve`.
**Why it's wrong:** Two processes writing to the same SQLite database causes SQLITE_BUSY errors. Even with WAL mode, only one writer can hold the write lock. The metadata store and sqlite-vec store share a connection, so concurrent writes from two processes risk corruption.
**Do this instead:** Run background indexer as a thread within the server process, sharing the same DotMDService and its single set of storage connections.

### Anti-Pattern 2: Making the Entire Pipeline Async

**What people do:** Convert IndexingPipeline to async to support concurrent TEI.
**Why it's wrong:** Only TEI calls benefit from async (network I/O). GLiNER inference, graph population, metadata writes are all CPU-bound or local I/O. Converting everything to async adds complexity with no benefit for most stages.
**Do this instead:** Keep pipeline sync. Only the TEI embedding step uses async internally (via `asyncio.run()`). This is a targeted optimization, not an architecture change.

### Anti-Pattern 3: BM25 Rebuild Per File in Background Mode

**What people do:** Rebuild BM25 after every file in the background indexer.
**Why it's wrong:** BM25 rebuild loads ALL chunks from metadata (O(total_chunks)). At 188K chunks, each rebuild reads the entire SQLite table. Doing this per-file means 13.5K full table scans.
**Do this instead:** Rebuild BM25 every N files (e.g., 50) or on a timer (e.g., every 10 minutes). New files are searchable via semantic and graph immediately; BM25 catches up periodically.

### Anti-Pattern 4: Using `asyncio.run()` Inside FastAPI's Event Loop

**What people do:** Call `asyncio.run()` from an `async def` endpoint handler.
**Why it's wrong:** `asyncio.run()` creates a new event loop, which fails if there's already a running loop (RuntimeError).
**Do this instead:** The background indexer runs in a thread (not in the event loop). `asyncio.run()` is called from sync code in that thread, which correctly creates a temporary event loop. FastAPI endpoints remain sync `def` (Starlette runs them in threadpool) so they also work with `asyncio.run()`.

---

## Sources

- FastAPI background tasks patterns: [FastAPI docs](https://fastapi.tiangolo.com/tutorial/background-tasks/), [Discussion #7930](https://github.com/fastapi/fastapi/discussions/7930) -- MEDIUM confidence (general patterns, not dotMD-specific)
- httpx async concurrent requests: [HTTPX async docs](https://www.python-httpx.org/async/), [Async Batch Requests pattern](https://davidgasquez.com/async-batch-requests-python/) -- HIGH confidence (well-documented API)
- GLiNER batch_predict_entities: [Discussion #73](https://github.com/urchade/GLiNER/discussions/73) -- HIGH confidence (maintainer-confirmed API)
- Docker Compose profiles: [Docker Compose profiles docs](https://docs.docker.com/reference/compose-file/profiles/) -- HIGH confidence
- FalkorDB Docker: [FalkorDB Docker docs](https://docs.falkordb.com/operations/docker.html) -- HIGH confidence
- TEI healthcheck: [TEI README](https://github.com/huggingface/text-embeddings-inference) -- MEDIUM confidence (healthcheck endpoint inferred from standard practice)
- Direct codebase analysis: `pipeline.py`, `semantic.py`, `ner.py`, `server.py`, `service.py`, `config.py`, `file_tracker.py`, `docker-compose.yml` -- HIGH confidence
- Production infrastructure: `/opt/docker/dotmd/`, `/opt/docker/embeddings/`, `/opt/docker/graphiti/` -- HIGH confidence

---
*Architecture research for: dotMD v1.3 Production Packaging, Background Indexing, Speed Optimization, Smoke Tests*
*Researched: 2026-03-27*
