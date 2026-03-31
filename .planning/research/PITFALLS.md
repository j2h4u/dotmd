# Pitfalls Research

**Domain:** Production packaging, background indexing, speed optimization, and smoke tests for dotMD v1.3
**Researched:** 2026-03-27
**Confidence:** HIGH (based on codebase analysis, official documentation, and multiple verified sources)

## Critical Pitfalls

### Pitfall 1: Background Indexer Blocks the FastAPI Event Loop

**What goes wrong:**
The current `DotMDService.index()` is fully synchronous -- it calls `IndexingPipeline.index()` which does file I/O, HTTP calls to TEI, GLiNER CPU-bound NER inference, and FalkorDB network writes. If a background trickle indexer is launched from an async context (e.g., FastAPI `BackgroundTasks` or `asyncio.create_task`), the entire event loop freezes for the duration of each file's processing. Search queries queue behind indexing and the API becomes unresponsive. With GLiNER taking ~4 seconds per chunk on this Xeon E3 V2, a single file with 3 chunks blocks the API for 12+ seconds.

**Why it happens:**
FastAPI's `BackgroundTasks` runs sync functions in Starlette's default threadpool, but there are two subtleties:
1. If the background task is defined as `async def` and calls sync code without `run_in_executor`/`run_in_threadpool`, it blocks the event loop directly -- no thread offloading occurs.
2. Even when correctly offloaded to a thread, Python's GIL means CPU-bound work (GLiNER, cross-encoder) in the background thread starves the event loop thread. The GIL is released during I/O (httpx calls to TEI, SQLite writes) but held during tensor operations.

The existing `server.py` lifespan creates a single `DotMDService` instance. If both API handlers and the background indexer use this same instance, they also share the same SQLite connections and in-memory BM25 index (see Pitfall 2).

**How to avoid:**
- Run the background indexer as a **separate process**, not a thread. Options:
  - A second container entrypoint (`dotmd trickle --data-dir /mnt`) sharing the same index volume
  - A subprocess spawned from the lifespan handler via `multiprocessing`
  - Process isolation eliminates GIL contention entirely and is the simplest correct approach
- If using threads (simpler but worse): use `asyncio.to_thread()` or `loop.run_in_executor(ThreadPoolExecutor(max_workers=1), ...)` and insert explicit `time.sleep(0.05)` yield points between files so the GIL releases regularly
- Never define the background indexer as an `async def` that calls sync pipeline code directly

**Warning signs:**
- Search latency spikes from ~200ms to 10+ seconds during active indexing
- API `/health` or `/status` endpoint stops responding during indexing
- `docker logs` shows no search requests completing while indexing is active

**Phase to address:**
Background Trickle Indexer -- the process vs. thread isolation decision must be made before implementation begins.

---

### Pitfall 2: SQLite Concurrent Access Without WAL Mode Causes Locks and Corruption

**What goes wrong:**
The background indexer writes to `metadata.db` (chunks, fingerprints, stats) and `vec.db` (sqlite-vec embeddings). Search queries read from these same databases. Two problems compound:

1. **Shared connection objects**: `SQLiteVecVectorStore._get_conn()` stores a single `sqlite3.Connection` as `self._conn`. SQLite connections are thread-bound by default -- using one from two threads raises `ProgrammingError: SQLite objects created in a thread can only be used in that same thread` or causes silent data corruption.

2. **No WAL mode**: The codebase does not set `PRAGMA journal_mode=WAL` anywhere. SQLite's default rollback journal mode means **any write blocks all readers**. Without WAL, a background indexer writing chunks to metadata.db blocks all search queries from reading metadata until the write transaction commits. With WAL, readers proceed unblocked during writes.

3. **No busy timeout**: Without `PRAGMA busy_timeout`, any lock contention immediately raises `sqlite3.OperationalError: database is locked` instead of retrying.

**Why it happens:**
The codebase was designed for single-threaded CLI usage (`dotmd index` then `dotmd search`, never concurrent). `DotMDService.__init__` creates one set of storage backends and both indexing and search reuse them. Adding background processing to this architecture requires concurrent access that was never anticipated.

**How to avoid:**
- **Enable WAL mode immediately** on all SQLite databases: `conn.execute("PRAGMA journal_mode=WAL")` right after opening each connection in `SQLiteVecVectorStore._get_conn()` and `SQLiteMetadataStore.__init__`. WAL allows unlimited concurrent readers during writes. This is a one-line fix with massive impact and no downside.
- **Set busy_timeout**: `conn.execute("PRAGMA busy_timeout=5000")` to retry on lock contention for up to 5 seconds instead of immediately raising an error.
- **Separate connections per thread/process**: If the indexer runs in a different thread, it MUST use its own `DotMDService` instance (which creates fresh storage backends with fresh connections). If it runs as a separate process, SQLite handles this correctly via OS-level file locks.
- **BM25 pickle file**: `bm25_index.pkl` is read by search and written during indexing. Use atomic write pattern: write to temp file, then `os.rename()` (atomic on Linux/ext4). Search should catch `EOFError` on read and retry.

**Warning signs:**
- `sqlite3.OperationalError: database is locked` in API or indexer logs
- `ProgrammingError: SQLite objects created in a thread can only be used in that same thread`
- Intermittent search failures that only occur during active background indexing
- `EOFError` or `UnpicklingError` when loading BM25 index

**Phase to address:**
Background Trickle Indexer phase. WAL mode enablement should be a **prerequisite** -- implement it even in the Production Packaging phase since it improves robustness with zero cost.

---

### Pitfall 3: Docker Compose Startup Race -- API Starts Before Dependencies Are Ready

**What goes wrong:**
Making the stack self-contained means bundling FalkorDB into the dotmd compose file (it IS dotmd-specific, unlike TEI). Without proper healthchecks and `depends_on` conditions, the dotmd API container starts before FalkorDB has loaded its persisted graph data. The `FalkorDBGraphStore.__init__()` immediately tries to connect and create indexes -- if FalkorDB isn't ready, it raises `ConnectionError("Cannot connect to FalkorDB")` and the container exits.

Similarly, TEI (referenced as external service) needs 10-60 seconds for model loading. The API's `_lifespan` handler creates `DotMDService` which creates `SemanticSearchEngine` -- if the first TEI health probe during warmup fails, the API crashes on startup.

**Why it happens:**
Docker Compose `depends_on` without a `condition` only waits for the container to **start**, not for the service inside to be **ready**. FalkorDB (Redis-protocol) needs seconds to load AOF data from disk. The official FalkorDB Docker docs recommend a `start_period` of 30 seconds. Without `condition: service_healthy`, the API container races the dependencies.

**How to avoid:**
- Add healthchecks to FalkorDB (bundled) and verify TEI availability:
  ```yaml
  falkordb:
    image: falkordb/falkordb:latest
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  api:
    depends_on:
      falkordb:
        condition: service_healthy
  ```
- Add **connection retry logic** in the dotmd API startup (lifespan handler) as defense-in-depth. Don't rely solely on Docker healthchecks -- the API should retry FalkorDB and TEI connections 3-5 times with exponential backoff before giving up.
- For TEI (external service): add a startup probe in the lifespan handler that polls `{DOTMD_EMBEDDING_URL}/health` before proceeding. Currently the code has no TEI readiness check at all.

**Warning signs:**
- API container exits immediately on `docker compose up` with `ConnectionError: Cannot connect to FalkorDB`
- Intermittent startup failures that "fix themselves" on retry with `docker compose restart api`
- `docker compose up` works after `docker compose start` (FalkorDB already running) but fails after `docker compose down && docker compose up` (clean start)

**Phase to address:**
Production Packaging phase -- healthchecks and startup ordering are the first things to get right in the compose file.

---

### Pitfall 4: Internalizing TEI Doubles RAM Usage on a 16GB Server

**What goes wrong:**
TEI currently runs as a shared service (`/opt/docker/embeddings/`) used by both dotmd and openclaw via external networks. Its memory limit is 4GB and it typically uses ~2.6GB RSS. If the self-contained dotmd stack bundles its own TEI instance, you have two options:

- **(a) Run a second TEI instance**: Doubles RAM to ~5.2GB just for embeddings. Combined with FalkorDB (~50MB), the dotmd API container (~800MB with GLiNER loaded), and other server services, total memory approaches 14-15GB on a 16GB server. OOM killer territory.
- **(b) Move TEI into dotmd stack, have openclaw reference it**: Creates a dependency inversion -- openclaw now depends on dotmd being up to get embeddings.

**Why it happens:**
"Self-contained" is interpreted as "everything in one compose file." But TEI is shared infrastructure, not a dotmd-specific dependency. Bundling shared infra into one consumer's stack is an architectural mistake.

**How to avoid:**
- **Keep TEI as a separate shared service** at `/opt/docker/embeddings/`. Reference it via the existing `embeddings_default` external network. This is the architecturally correct pattern for shared infrastructure.
- "Self-contained" for dotmd means: FalkorDB bundled (dotmd-specific), TEI referenced as external dependency with a startup readiness check, all env vars documented with sensible defaults, `docker compose up` works assuming TEI is running.
- Document the dependency clearly in the compose file with comments and a startup error message if TEI is unreachable.
- For portability (running on a different server): use a Docker Compose profile (`--profile standalone`) that optionally starts a local TEI. Not the default.

**Warning signs:**
- `docker stats` shows total memory >14GB
- OOM killer starts killing containers (check `dmesg | grep -i oom`)
- Two TEI containers competing for CPU during embedding requests, halving throughput for both dotmd and openclaw

**Phase to address:**
Production Packaging phase -- this architecture decision must be made before writing the compose file. The wrong choice here wastes the 16GB RAM budget.

---

### Pitfall 5: Concurrent TEI Requests Don't Improve Throughput When CPU-Bound

**What goes wrong:**
The v1.3 plan calls for "concurrent TEI requests (2-3 parallel)" to speed up embedding. On this server, TEI runs on CPU with `intfloat/multilingual-e5-large` (560M params, `cpu-1.6` image). Existing benchmarks show bs=4 and bs=32 give roughly the same throughput (~0.5-1.3 texts/sec). Sending multiple concurrent HTTP requests to TEI doesn't create parallelism in model inference -- TEI's internal token-based dynamic batching (`max_batch_tokens=16384` default) already handles this. The requests just queue inside TEI's internal batch scheduler. Worse, adding concurrency on the dotmd side (asyncio/threading for httpx) introduces complexity and bug surface for zero throughput gain.

**Why it happens:**
TEI uses token-based dynamic batching internally. When the model is compute-bound on CPU (which this Xeon E3 V2 absolutely is for a 560M parameter model), adding more concurrent requests fills the internal queue faster but the model still processes one batch at a time through matrix multiplication. The bottleneck is FLOPS, not I/O wait between requests. This is fundamentally different from GPU deployment where concurrent requests enable better utilization of thousands of parallel compute units.

The empirical evidence already exists: bs=4 and bs=32 have the same throughput. This means TEI is compute-bound even at bs=4. More requests in flight won't help.

**How to avoid:**
- **Benchmark before implementing**: Send 1, 2, 3 concurrent requests from dotmd and measure actual end-to-end texts/sec. If they're the same (which the bs=4 vs bs=32 evidence strongly predicts), don't add concurrency code.
- **Pipeline HTTP overhead instead**: If there IS measurable gap between "response received" and "next request sent" (HTTP round-trip overhead ~5-10ms), use a simple prefetch (send request N+1 while processing response N) rather than full concurrent fan-out. This is simpler and lower-risk.
- **Reduce total work instead**: Skip NER for background trickle indexing (`extract_depth=structural`). NER (GLiNER) is the 15-minute bottleneck in a 50-minute full index. Eliminating it gives 30% speedup with zero concurrency complexity. NER can be run as a separate enrichment pass later.
- **Optimize batch size**: The real lever is finding the optimal `tei_batch_size` for this specific hardware. The auto-tuning probe already exists -- persist its result to avoid re-probing on every restart.

**Warning signs:**
- Concurrent TEI requests show identical throughput to sequential in benchmarks
- Adding concurrency introduces httpx connection pool errors or timeout issues
- TEI memory usage spikes when multiple large batches queue simultaneously

**Phase to address:**
Speed Optimization phase. Must be preceded by empirical benchmarking. Do not assume concurrency helps -- the existing data suggests it won't.

---

### Pitfall 6: Full BM25 Rebuild Per File During Background Indexing

**What goes wrong:**
The pipeline always does a full BM25 rebuild: `_ingest_and_finalize()` calls `self._metadata_store.get_all_chunks()` then `self._bm25_engine.build_index(all_chunks)`. For the current 532 chunks, this takes <1 second. For the target 13,500-file corpus (~188k estimated chunks), this takes significant time and memory -- loading 188k chunk texts into memory, tokenizing all of them, and rebuilding the BM25Okapi index. If the trickle indexer triggers this after every single file, it becomes O(N) per file indexed, making total background indexing O(N^2).

Additionally, the BM25 index is persisted as `bm25_index.pkl`. If the background indexer writes this pickle while a concurrent search reads it, the pickle can be corrupted (partial write visible to reader).

**Why it happens:**
BM25 (rank_bm25) does not support incremental updates -- you can't add a document to an existing BM25Okapi instance. The full rebuild was acceptable for batch indexing of a small corpus. The pipeline comment even notes this: `# BM25 always full rebuild (IP-04)`.

**How to avoid:**
- **Batch BM25 rebuilds**: Don't rebuild after every single file. The trickle indexer should accumulate a batch (e.g., 10-50 files or 5-minute intervals) then rebuild once. New files are searchable via semantic and graph search immediately; BM25 catches up periodically.
- **Atomic pickle swap**: Write to a temp file (`bm25_index.pkl.tmp`), then `os.rename()` to final path. `os.rename()` is atomic on Linux/ext4. Search always reads a complete index. Add `EOFError` catch in `BM25SearchEngine.load_index()` with a short retry.
- **Consider append-only BM25**: Maintain a small secondary BM25 index for newly-indexed documents. At search time, query both and merge results. Periodically (e.g., once per hour), rebuild the full index and clear the secondary. This avoids O(N^2) entirely.
- **Memory guard**: For 188k chunks, estimate memory before loading. If the full BM25 rebuild would exceed available RAM, defer it or run it when the API is idle.

**Warning signs:**
- Memory spikes visible in `docker stats` during background indexing (loading all chunks for BM25)
- `EOFError` or `UnpicklingError` in search logs for `bm25_index.pkl`
- BM25 search results disappear intermittently during active indexing
- Background indexing throughput degrades as corpus grows (O(N) rebuild visible in timing logs)

**Phase to address:**
Background Trickle Indexer phase. The batch interval and atomic swap are design decisions that affect implementation. Must be decided before coding the trickle loop.

---

### Pitfall 7: Smoke Tests That Depend on Running Services Are Inherently Flaky

**What goes wrong:**
Smoke tests verifying "all 3 search engines return results" need a running TEI server, a running FalkorDB instance, and an indexed corpus. Common failure modes:
1. **Service startup timing**: TEI needs 10-60s to load the model, FalkorDB needs 5-30s to load data. Tests that don't wait long enough fail intermittently.
2. **Model download on first run**: TEI downloads 1.2GB model on first start. In CI or on a clean test run, this causes a timeout.
3. **Port/resource conflicts**: On this server, TEI already runs on port 8088 and FalkorDB on graphiti_default. Starting duplicate test instances conflicts with production.
4. **Test isolation**: If tests use the production FalkorDB graph name (`dotmd`), they corrupt production data. If they use the production TEI, they're not truly isolated.
5. **Cleanup**: Tests that create Docker containers/volumes and don't clean up waste disk space over time.

**Why it happens:**
Integration tests that require external services are fundamentally different from unit tests. Developers often write them as if they're fast and deterministic -- no explicit readiness polling, hardcoded `time.sleep(30)`, shared state between test runs, no cleanup fixtures.

**How to avoid:**
- **Layer the test strategy**:
  - **Unit tests** (no Docker, fast): Mock TEI responses (`httpx_mock`) and FalkorDB (in-memory dict). Test fusion logic, BM25 ranking, pipeline orchestration, query expansion. Run in <5 seconds. These catch most regressions.
  - **Smoke tests** (Docker required, slow): Test real service integration. Accept they're slow (30-120s). Mark with `@pytest.mark.smoke` and run separately.
- **For smoke tests on this server**:
  - Reuse the running production TEI (it's shared infra, no point duplicating). Don't start a separate TEI container.
  - Use a **separate FalkorDB graph name** (`dotmd_test`) and **separate index directory** (`/tmp/dotmd-test-index/`) to isolate from production data.
  - Use `session`-scoped pytest fixtures so service readiness checks run once, not per test.
  - Poll TEI `/health` and FalkorDB `redis-cli ping` with exponential backoff (100ms, 200ms, 400ms, ..., up to 60s) instead of `time.sleep(30)`.
  - Pre-index a small test corpus (5-10 markdown files) as a fixture.
  - Clean up the test graph and test index directory in the fixture teardown.
- **For CI (if ever needed)**: Use `pytest-docker` with a test-specific compose file that starts FalkorDB on a different port and uses a mock/small TEI or pre-computed embeddings.

**Warning signs:**
- Tests pass locally but fail on a different machine (or after `docker compose down`)
- Tests pass individually but fail when run together (shared state)
- Test suite takes >120 seconds and developers stop running it
- `docker volume ls` shows growing number of orphaned test volumes

**Phase to address:**
Smoke Tests phase. The test architecture (what's mocked vs. real, unit vs. integration) must be decided before writing any tests.

---

## Technical Debt Patterns

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
|----------|-------------------|----------------|-----------------|
| Single `DotMDService` shared between API and indexer threads | Simple, no data duplication | Thread safety bugs, SQLite connection sharing, hard-to-reproduce races | Never -- always use separate instances or process boundary |
| Full BM25 rebuild on every trickle-indexed file | Correct results, simple code path | O(N) per file, O(N^2) total for background indexing of large corpus | Only for batch indexing of <100 files |
| Skip WAL mode on SQLite databases | No code changes needed | Readers blocked by writers, "database is locked" under any concurrency | Only when single-threaded CLI usage is guaranteed |
| `time.sleep(30)` for service readiness in tests | Quick to write, usually works | Flaky on slow machines, wastes 30s on fast machines, non-deterministic | Never -- use poll-based readiness checks |
| Bundling a second TEI instance for "self-contained" | True isolation | 2.6GB extra RAM on 16GB server, CPU contention | Only on servers with 32GB+ RAM |
| Skip NER in background trickle indexer | 30% faster indexing, less CPU contention | Knowledge graph has fewer entities for those files | Acceptable as deliberate tradeoff -- run NER enrichment pass later |
| No connection retry in FalkorDB adapter | Simpler code | Single transient failure kills entire index run | Never for network services -- always add retry |

## Integration Gotchas

| Integration | Common Mistake | Correct Approach |
|-------------|----------------|------------------|
| FalkorDB in compose | No healthcheck; API starts before FalkorDB is ready | `healthcheck: redis-cli ping` + `depends_on: condition: service_healthy` + `start_period: 30s` |
| TEI as external dep | Including TEI as a bundled service, doubling RAM | Keep as external shared service; add startup readiness probe in API lifespan handler |
| TEI healthcheck | Hitting `/` (HTML page, always 200) | Hit `/health` which returns actual model readiness status |
| Docker Compose `include` | Assuming included services share parent's default network | Included files have their own project directory and network namespace; need explicit shared network config |
| FalkorDB persistence | No volume mount; graph data lost on container restart | Mount `/data` to a named volume; enable `--appendonly yes` for AOF persistence |
| SQLite shared between threads | Single connection from `__init__` used across threads | One connection per thread, WAL mode, `busy_timeout=5000` |
| BM25 pickle file | Read and write from different threads without coordination | Atomic write via temp file + `os.rename()`; reader retries on `EOFError` |
| FalkorDB graph name in tests | Using `dotmd` (production) instead of `dotmd_test` | Always use separate graph name for test fixtures via env var |
| Background indexer resume | Assume indexer starts from scratch after restart | FileTracker fingerprints persist to SQLite; indexer must resume from last indexed file |

## Performance Traps

| Trap | Symptoms | Prevention | When It Breaks |
|------|----------|------------|----------------|
| Full BM25 rebuild per trickle-indexed file | RAM spikes, indexing slows as corpus grows | Batch rebuilds every N files or time interval | Noticeable at ~10k chunks (>1s rebuild), painful at 100k+ |
| Concurrent TEI requests on CPU-bound server | No throughput gain, added code complexity | Benchmark first; pipeline HTTP overlap only if measurable gap | Immediately -- TEI is already compute-bound at bs=4 |
| GLiNER NER on every background-indexed file | CPU pegged 100% for hours, API search degrades | Skip NER for trickle indexing or use lowest CPU priority | At ~50+ files when NER takes ~4s/chunk |
| Loading all 188k chunks into memory for BM25 | Memory usage proportional to total corpus size | Stream chunks or cap in-memory size | At ~100k+ chunks, memory may exceed container limit |
| Background indexer and search competing for CPU | Both run GLiNER/reranker (CPU-bound) simultaneously | Indexer skips reranker (it's search-only); use `--cpu-shares 2` for indexer container | Any time background indexer runs NER while searches use cross-encoder |

## Security Mistakes

| Mistake | Risk | Prevention |
|---------|------|------------|
| TEI exposed externally in self-contained stack | TEI has no auth; anyone can embed arbitrary text, potential DoS | Bind TEI to internal Docker network only; never expose port to host |
| FalkorDB without password | Any container on shared network can read/write graph | Acceptable on single-user server. Add `--requirepass` if stack is ever exposed |
| Test fixtures with production data paths | Tests could accidentally modify or delete production index | Test compose uses separate volumes, separate graph name, separate index dir |
| Smoke tests leaving test data in production FalkorDB | Orphaned test nodes pollute production graph search | Always use separate `DOTMD_FALKORDB_GRAPH_NAME=dotmd_test`; clean up in teardown |

## UX Pitfalls

| Pitfall | User Impact | Better Approach |
|---------|-------------|-----------------|
| Background indexer with no progress visibility | User doesn't know if indexing is running, stuck, or finished | `dotmd status` shows "Background indexing: 1,234/13,515 files (9.1%), ~6h remaining" |
| Silent failure when TEI is unreachable | Container starts, appears healthy, but search returns empty results | Fail loudly at startup. Log `CRITICAL: TEI unreachable at {url}`. Add `/health` endpoint that checks all dependencies |
| Smoke test output shows only pass/fail | Developer has no idea which engine or fusion step broke | Tests log actual search results, scores, and engine attribution on failure |
| Background indexer restarts from scratch after container restart | Hours of progress lost | FileTracker fingerprints persist on disk volume; verify resume works across restarts |
| `docker compose up` fails with cryptic network error | User doesn't know TEI needs to be running separately | Clear error message: "TEI service not found on embeddings_default network. Start it with: cd /opt/docker/embeddings && docker compose up -d" |

## "Looks Done But Isn't" Checklist

- [ ] **Self-contained compose:** `docker compose down && docker compose up` from clean state -- API starts successfully with no manual intervention (except TEI running separately)
- [ ] **Self-contained compose:** FalkorDB data survives container restart -- `docker compose restart falkordb`, then `/status` shows same entity/edge counts
- [ ] **Self-contained compose:** TEI model cached in named volume -- second start (no download) completes in <30 seconds
- [ ] **WAL mode:** Enabled on ALL SQLite databases -- verify with `PRAGMA journal_mode` on both `metadata.db` and `vec.db`
- [ ] **Background indexer:** Survives container restart -- stop and restart, verify indexer resumes from last indexed file
- [ ] **Background indexer:** Doesn't block search -- run search query WHILE background indexing is active, verify response in <500ms
- [ ] **Background indexer:** BM25 stays consistent -- search for a term only in recently-indexed files during active indexing
- [ ] **Background indexer:** Handles individual file failures -- corrupt markdown file doesn't crash the entire indexer
- [ ] **Speed optimization:** Actually faster -- measure end-to-end throughput before and after. If concurrent TEI shows <10% improvement, revert the complexity
- [ ] **Smoke tests:** Run without affecting production -- verify tests use separate FalkorDB graph name and index directory
- [ ] **Smoke tests:** Pass 10/10 times in a row -- no timing-dependent flakiness
- [ ] **Smoke tests:** Complete in <120 seconds -- slow enough to be thorough, fast enough to actually run

## Recovery Strategies

| Pitfall | Recovery Cost | Recovery Steps |
|---------|---------------|----------------|
| SQLite corruption from concurrent access | MEDIUM | Delete `metadata.db` and `vec.db`, run `dotmd index --force`. Index data is derived from source files |
| BM25 pickle corruption | LOW | Delete `bm25_index.pkl`, restart API or run any index operation (triggers full rebuild) |
| FalkorDB graph inconsistency | MEDIUM | `dotmd clear` then `dotmd index --force`. Graph is rebuilt from source files |
| Container OOM from duplicate TEI | LOW | Remove bundled TEI, revert to external network reference. `docker compose down && docker compose up` |
| Flaky tests polluting production graph | HIGH if undetected | Check `DOTMD_FALKORDB_GRAPH_NAME` in test config. If tests used `dotmd`, manually drop test data via `redis-cli GRAPH.DELETE dotmd_test` |
| Background indexer stuck in crash loop | LOW | Check logs for failing file path. Skip it or fix parsing. Indexer should log file path on failure and continue to next |
| Event loop blocked by sync indexer | LOW | Restart container. Fix: move indexer to separate process or thread with proper isolation |
| BM25 rebuild OOM at scale | MEDIUM | Reduce batch commit interval (rebuild less frequently). Set container memory limit with swap. Consider streaming BM25 rebuild |

## Pitfall-to-Phase Mapping

| Pitfall | Prevention Phase | Verification |
|---------|------------------|--------------|
| Event loop blocking (P1) | Background Trickle Indexer | Search query returns in <500ms during active background indexing |
| SQLite write contention (P2) | Production Packaging (WAL) + Background Indexer (isolation) | `PRAGMA journal_mode` returns `wal` on all databases; concurrent read+write test passes |
| Startup ordering race (P3) | Production Packaging | `docker compose down && docker compose up` succeeds on first try from clean state |
| TEI RAM duplication (P4) | Production Packaging | `docker stats` shows only one TEI container; total RAM <12GB |
| Pointless TEI concurrency (P5) | Speed Optimization | Benchmark 1 vs 2 vs 3 concurrent requests; only add concurrency if >15% throughput gain |
| BM25 full rebuild per file (P6) | Background Trickle Indexer | No `EOFError` in logs during 1-hour indexing run; BM25 results present throughout |
| Flaky smoke tests (P7) | Smoke Tests | Tests pass 10/10 consecutive runs; complete in <120 seconds |

## Sources

- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) -- `depends_on` conditions: `service_started`, `service_healthy`, `service_completed_successfully`
- [Docker Compose Include](https://docs.docker.com/compose/how-tos/multiple-compose-files/include/) -- modular compose, project directory isolation, resource merging
- [FalkorDB Docker docs](https://docs.falkordb.com/operations/docker.html) -- healthcheck (`redis-cli ping`), persistence (`--appendonly yes`), `start_period: 30s`
- [TEI CLI arguments](https://huggingface.co/docs/text-embeddings-inference/en/cli_arguments) -- `max_concurrent_requests=512`, `max_batch_tokens=16384`, token-based dynamic batching
- [SQLite WAL mode](https://www.sqlite.org/wal.html) -- concurrent readers during writes, checkpoint starvation risk with long-running readers
- [SQLite concurrent writes and "database is locked"](https://tenthousandmeters.com/blog/sqlite-concurrent-writes-and-database-is-locked-errors/) -- WAL vs rollback journal, busy_timeout, write lock scope
- [FastAPI BackgroundTasks event loop blocking](https://github.com/fastapi/fastapi/discussions/11210) -- sync tasks in async context, `run_in_threadpool` vs `run_in_executor`
- [FastAPI concurrency and async/await](https://fastapi.tiangolo.com/async/) -- GIL, def vs async def behavior
- [GLiNER inference speedup](https://github.com/urchade/GLiNER/issues/88) -- batch processing, `model.to('cuda')` vs `.cuda()`, CPU can be 3x faster than V100
- [GLiNER CPU performance (300x slower)](https://github.com/theirstory/gliner-spacy/discussions/28) -- CPU reality for NER workloads
- [pytest-docker](https://github.com/avast/pytest-docker) -- Docker-based integration test fixtures
- [pytest flaky tests](https://docs.pytest.org/en/stable/explanation/flaky.html) -- insufficient environment isolation as root cause
- Codebase analysis: `service.py` (shared DotMDService singleton), `pipeline.py` (sync pipeline, BM25 full rebuild), `semantic.py` (sequential TEI calls), `sqlite_vec.py` (no WAL, single connection), `server.py` (lifespan handler), `config.py` (Settings)
- Production deployment: `/opt/docker/dotmd/docker-compose.yml` (external networks), `/opt/docker/embeddings/docker-compose.yml` (TEI cpu-1.6, 4GB limit, shared service)
- v1.3 plans: `.claude/projects/.../memory/project_v13_plans.md` -- bs=4 same as bs=32 empirical finding

---
*Pitfalls research for: dotMD v1.3 -- Production Packaging, Background Indexing, Speed Optimization, Smoke Tests*
*Researched: 2026-03-27*
