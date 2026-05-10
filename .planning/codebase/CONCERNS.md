# Codebase Concerns

**Analysis Date:** 2026-05-10

## Tech Debt

**Dead `LanceDBVectorStore` backend:**
- Issue: `LanceDB` was replaced by `sqlite-vec` but the full implementation remains in `storage/vector.py` (129 lines). `delete_vectors_by_chunk_ids` and `lookup_embeddings_by_text_hash` are no-op stubs that silently return `0`/`{}`. The backend can still be activated via `DOTMD_VECTOR_BACKEND=lancedb` in config, and `lancedb` has an optional extras entry in `pyproject.toml`. If someone accidentally sets the env var, incremental deletes and embedding reuse are silently broken.
- Files: `backend/src/dotmd/storage/vector.py`, `backend/src/dotmd/core/config.py:93`, `backend/src/dotmd/ingestion/pipeline.py:240-249`
- Impact: Silent data correctness failure if backend is ever switched. Dead code inflates maintenance surface.
- Fix approach: Delete `storage/vector.py`, remove `vector_backend` config option and the `lancedb` optional extra, hard-code `sqlite-vec` in `pipeline.py`. The `lancedb` path has not been tested since Phase 12.

**Protocol-breaking `hasattr` duck-typing on `VectorStoreProtocol`:**
- Issue: Five call sites in `pipeline.py` use `hasattr()` guards for methods that are part of the protocol contract (`delete_by_chunk_ids`, `set_model_name`, `set_distance_metric`, `_tables_ensured`). This breaks the protocol abstraction and forces callers to have implementation knowledge.
- Files: `backend/src/dotmd/ingestion/pipeline.py:1058`, `1336`, `2005`, `2008`, `2415`, `3152`
- Impact: Adding a new backend requires knowing which `hasattr` guards to satisfy; protocol violations are invisible to the type checker; `# type: ignore[attr-defined]` follows every call.
- Fix approach: Promote `delete_by_chunk_ids`, `set_model_name`, and `set_distance_metric` into `VectorStoreProtocol` in `storage/base.py`. Add no-op default implementations for the LadybugDB graph store.

**`GraphStoreProtocol` missing `delete_frontmatter_edges`:**
- Issue: `pipeline.py:3152` uses `hasattr(self._graph_store, "delete_frontmatter_edges")` before calling it. The method exists on `FalkorDBGraphStore` but is not in `GraphStoreProtocol`. Same `# type: ignore[attr-defined]` pattern.
- Files: `backend/src/dotmd/ingestion/pipeline.py:3152`, `backend/src/dotmd/storage/base.py`
- Impact: FalkorDB-specific graph cleanup is silently skipped when using LadybugDB backend. Protocol is incomplete.
- Fix approach: Add `delete_frontmatter_edges(file_path: str) -> None` to `GraphStoreProtocol` and add a no-op implementation in `LadybugDBGraphStore`.

**Private attribute access across module boundary:**
- Issue: `pipeline.py:2050` accesses `self._ner_extractor._extraction_cache` directly — a private attribute on `NERExtractor`. If `NERExtractor` refactors its internals, this line silently breaks.
- Files: `backend/src/dotmd/ingestion/pipeline.py:2050`, `2063`, `backend/src/dotmd/extraction/ner.py`
- Impact: Fragile coupling; type checker cannot catch this.
- Fix approach: Add a `prune_orphans(live_texts)` public method to `NERExtractor` that delegates to its cache.

**`_ConnProxy` test-spy wrapper baked into production code:**
- Issue: `storage/metadata.py` defines `_ConnProxy`, a Python-level wrapper around `sqlite3.Connection` whose only stated purpose is to allow test spies to reassign `.execute`. It adds a property getter with an `_execute_override` dict-lookup on every `conn.execute()` call in production.
- Files: `backend/src/dotmd/storage/metadata.py:42-76`
- Impact: Unnecessary runtime overhead on every metadata operation. Test concerns leak into production code.
- Fix approach: Remove `_ConnProxy`; refactor the spy test in `test_metadata_m2m.py` to use `unittest.mock.patch` or a protocol-level mock instead.

**`pipeline.py` is 3,777 lines — a God Object:**
- Issue: `IndexingPipeline` handles schema creation, two-phase chunking, embedding, FTS5, graph population, metadata, vector store coordination, orphan cleanup, vacuum scheduling, and application-source ingestion. The class has grown through 35 phases of iterative development.
- Files: `backend/src/dotmd/ingestion/pipeline.py`
- Impact: High cognitive load for every change; testing requires mocking a huge surface; single bugs can cascade across many subsystems.
- Fix approach: Incrementally extract: `_EmbeddingCoordinator` (embedding cache + TEI), `_GraphCoordinator` (frontmatter + NER graph population), `ApplicationSourceIngestor` (the Telegram ingestion path). No need to do all at once.

**`migrate_fingerprints_to_blake3.py` one-time script left in tree:**
- Issue: `ingestion/migrate_fingerprints_to_blake3.py` is a one-time migration script for a Phase-era schema change. It is not called by any production code path.
- Files: `backend/src/dotmd/ingestion/migrate_fingerprints_to_blake3.py`
- Impact: Dead code, confusing for future readers.
- Fix approach: Delete the file; the migration it performs is already complete on all instances.

**`modal` listed as core dependency but never imported:**
- Issue: `modal>=0.73` is in `[project.dependencies]` in `pyproject.toml` (not optional extras). Grep across all `.py` source files finds zero `import modal` or `from modal` statements. Modal is a ~60MB cloud compute SDK installed in every environment unnecessarily.
- Files: `backend/pyproject.toml`
- Impact: Inflates container image, installs a cloud SDK with network credentials support in a container that doesn't need it.
- Fix approach: Remove from `[project.dependencies]`. If modal was used for a dev experiment, move to `[project.optional-dependencies]` dev.

**`pandas` listed as core dependency, used only through LadybugDB `.get_as_df()`:**
- Issue: `pandas>=2.0` is in `[project.dependencies]`. The only usage is via `result.get_as_df()` in `storage/graph.py` — a LadybugDB-internal call that returns a DataFrame, which `graph.py` then iterates row by row. `pandas` is not used directly in dotMD source code.
- Files: `backend/src/dotmd/storage/graph.py`, `backend/pyproject.toml`
- Impact: Unnecessary ~35MB dependency. LadybugDB (real_ladybug) likely pulls it transitively anyway, so this may be harmless, but the explicit pin creates a false impression that dotMD directly uses pandas.
- Fix approach: Remove from `pyproject.toml`; if real_ladybug requires it, it will pull it transitively.

**`descriptor_key` hardcoded as `"filesystem-mnt"` in fusion:**
- Issue: `search/fusion.py:373` hardcodes `descriptor_key="filesystem-mnt"` for all local chunks. This is a source-registry identifier that should come from the source descriptor, not be baked into the search path.
- Files: `backend/src/dotmd/search/fusion.py:373`
- Impact: Adding a second local filesystem source would assign wrong descriptor keys to search results.
- Fix approach: Pass descriptor key through `ChunkProvenance` or as a parameter to `build_candidates`.

## Known Bugs

**`is_low_signal_telegram_text` has redundant dead condition:**
- Issue: The function at `telegram_provider.py:400-412` checks `not any(ch.isalnum() for ch in stripped)` on line 407, returns `True` if that holds, then line 409-411 unconditionally re-evaluates the same condition in the `return` expression. The second clause `any(unicodedata.category(ch).startswith("S") for ch in stripped)` (detecting symbol-only text) is thus unreachable for any string that made it past line 407 — because if `stripped` has no alnum chars, we already returned `True`; if it has alnum chars, the first part of the `or` is `False`.
- Files: `backend/src/dotmd/ingestion/telegram_provider.py:409-412`
- Impact: Symbol-only text that contains at least one alnum character (e.g. `"3 ♠♠♠"`) is incorrectly classified as NOT low-signal.
- Fix approach: Replace lines 409-411 with just `return any(unicodedata.category(ch).startswith("S") for ch in stripped)`.

**`UnixSocketTelegramSourceClient._request` accumulates entire response in memory:**
- Issue: The loop at `telegram_provider.py:159-163` calls `sock.recv(1024 * 1024)` (1 MB per call) and appends to `data` until `data.endswith(b"\n")`. For a large export batch, the entire JSON response is buffered before parsing.
- Files: `backend/src/dotmd/ingestion/telegram_provider.py:153-176`
- Impact: Memory spike proportional to batch size; a single large export response (many messages) allocates the full payload multiple times (buffer + JSON parse + Python dicts). Under 30-second timeout; large batches may time out.
- Fix approach: Use `sock.makefile()` and `readline()` for line-framed JSON protocol; avoids both the 1 MB chunk granularity and the manual `endswith` detection.

## Performance Bottlenecks

**Synchronous TEI HTTP calls block the trickle thread:**
- Issue: `semantic.py` makes synchronous `httpx.post()` calls (no `async`) with a 600-second timeout. These run inside `asyncio.to_thread()` in `trickle.py`, which is correct, but each batch blocks one thread-pool worker for the entire TEI round-trip. During initial backlog (many files), only one file is processed at a time — this is by design (D-LOCAL-SEQUENTIAL) — but TEI latency directly multiplies into total indexing time.
- Files: `backend/src/dotmd/search/semantic.py:154`, `backend/src/dotmd/ingestion/trickle.py:386`
- Impact: Indexing throughput is bounded by TEI latency × sequential file processing. Not a bug, but no async TEI path exists.
- Fix approach: No change needed for correctness; if throughput becomes an issue, consider a mini-batch path that groups N files before calling TEI in a single request.

**`prune_extraction_cache` loads all chunk texts into memory:**
- Issue: `pipeline.py:2054-2058` iterates every strategy, runs `SELECT text FROM chunks_{strategy}`, and loads all text into a Python list before calling `prune_orphans`. With tens of thousands of chunks, this is a full table scan with all text content in memory.
- Files: `backend/src/dotmd/ingestion/pipeline.py:2054-2058`
- Impact: Memory spike on every deferred maintenance cycle (post-deletion). Only relevant at scale (thousands of files), but the pattern does not scale.
- Fix approach: Prune by `blake3(text)` rather than raw text — store text hashes in the extraction cache and compare hashes with a SQL `NOT IN` subquery.

**`_extract_best_snippet` is O(N×M) on large documents:**
- Issue: `fusion.py:40-80` slides a window across every word start, scoring each position against all query tokens. For a 10,000-word document with a 20-token query, this is 200,000 membership checks per search result.
- Files: `backend/src/dotmd/search/fusion.py:40-80`
- Impact: Snippet extraction adds measurable latency for large documents in the search hot path. Called once per result per search.
- Fix approach: Build a pre-indexed `{token: [positions]}` map, compute window scores in a single O(N) sweep.

## Fragile Areas

**SQLite connection `check_same_thread=False` with multi-threaded access:**
- Issue: `pipeline.py:205-208` opens the unified SQLite connection with `check_same_thread=False` and `isolation_level=None` (autocommit). The trickle indexer runs indexing in `asyncio.to_thread()` and search queries come from FastAPI's thread pool. Multiple threads share one connection.
- Files: `backend/src/dotmd/ingestion/pipeline.py:205-208`, `backend/src/dotmd/ingestion/trickle.py:386`
- Impact: SQLite WAL mode allows concurrent reads, and write serialization through the single connection avoids most races, but simultaneous write transactions from two threads could deadlock or corrupt if the `BEGIN`/`COMMIT` pattern is broken by an exception at the wrong moment. Currently mitigated by the `fcntl` lock and single-worker executor, but the invariant is implicit.
- Safe modification: Never add a second thread that writes to `self._conn` without reviewing all existing transaction boundaries. All callers of `BEGIN`/`COMMIT` must be audited before adding concurrency.

**`source_runtime_factory.build()` hardcodes two namespaces:**
- Issue: `source_lifecycle.py:279-313` has explicit `if namespace == "filesystem"` / `if namespace == "telegram"` branches. Adding a new source type requires modifying this method rather than registering a factory.
- Files: `backend/src/dotmd/ingestion/source_lifecycle.py:279-313`
- Impact: Every new source is a modification to a central factory. The source registry (`SourceRegistry`) exists but the factory doesn't use it for dispatch.
- Safe modification: Any new source type currently requires forking this method; test coverage for the build path is in `test_source_lifecycle.py`.

**`_model_to_table_suffix` strips version numbers from model names:**
- Issue: `pipeline.py:137-156` strips version suffixes (e.g., `-v2.1`, `-0.6B`) from model names when deriving table suffixes. Comment says: "Version stripping kept for now (removal deferred to migration phase when tables are renamed)." Switching between `model-v1` and `model-v2` maps to the same table suffix and silently reuses the old table.
- Files: `backend/src/dotmd/ingestion/pipeline.py:137-156`
- Impact: Model version changes that use the same base name (e.g., `bge-small-en-v1.5` → `bge-small-en-v2.0`) share a table and do not trigger a dimension change unless vector dimensionality differs. Embedding quality drift is silent.
- Fix approach: Remove version-stripping from `_model_to_table_suffix`. Requires a migration that renames existing tables in production index.db.

## Test Coverage Gaps

**Federated search async/concurrency invariants are unwritten stubs:**
- What's not tested: 11 tests in `tests/search/test_federated.py:428-510` are `@pytest.mark.skip(reason="Deferred to Task 3 - service integration")` and contain only `pass`. These cover D-LOCAL-SEQUENTIAL (local engines don't run concurrently), D-LOOP-SAFE (sync search raises in event loop), D-LOCAL-SERIALIZED (single worker thread), lifecycle init failure surfacing as SourceStatus, and federated timeout isolation.
- Files: `backend/tests/search/test_federated.py:428-510`
- Risk: Regressions in the async/concurrency model (single executor, event-loop safety) would not be caught. These invariants were established in Phases 33-35 but have no behavioral tests.
- Priority: High

**`is_low_signal_telegram_text` logic is not tested for the dead branch:**
- What's not tested: The symbol-detection branch (`unicodedata.category`) in `telegram_provider.py:411`. No existing test checks mixed alnum+symbol text like `"3 ♠♠♠"`.
- Files: `backend/tests/ingestion/test_telegram_provider.py`
- Risk: The bug (see Known Bugs above) exists silently.
- Priority: Medium

**`LanceDB` backend code paths have zero test coverage:**
- What's not tested: `storage/vector.py` methods (`delete_vectors_by_chunk_ids`, `lookup_embeddings_by_text_hash` stubs). No test exercises `vector_backend=lancedb`.
- Files: `backend/src/dotmd/storage/vector.py`
- Risk: Low (backend is default-off) but the silent no-op stubs mean any accidental activation corrupts incremental indexes without error.
- Priority: Low (resolve by deleting the backend entirely)

**`_ConnProxy` spy behavior is not tested directly:**
- What's not tested: The `_execute_override` mechanism in `_ConnProxy` — only tested indirectly through `test_metadata_m2m.py`. The proxy's `__getattr__`/`__setattr__` paths under error conditions are untested.
- Files: `backend/src/dotmd/storage/metadata.py:42-76`
- Risk: Proxy breakage would silently degrade test accuracy rather than fail explicitly.
- Priority: Low (resolve by removing `_ConnProxy`)

## Dependencies at Risk

**`torch<2.5` hard upper bound:**
- Risk: The `<2.5` pin exists because the production server's Xeon E3 V2 CPU lacks AVX2, and PyTorch 2.5+ requires AVX2. This is documented in memory (`hardware_cpu_limits.md`). The pin will block `sentence-transformers`, `gliner`, and other torch-dependent packages from receiving upstream fixes.
- Impact: Security and bug fix updates to the torch ecosystem are blocked.
- Migration plan: This is a hardware constraint. Resolution requires either: (a) CPU upgrade, (b) migrating NER/reranker to ONNX Runtime (no AVX2 requirement), or (c) containerizing the torch workload on a separate host.

**`real_ladybug` is an unlisted/private package:**
- Risk: `real_ladybug>=0.1` in `pyproject.toml` is the embedded LadybugDB graph backend. It has no PyPI entry and appears to be an internal build or private fork. `import real_ladybug as lb` with `type: ignore[import-untyped]` signals no stubs. Version pinning is only a lower bound.
- Impact: No upstream security disclosures, no changelog, no reliable update mechanism.
- Migration plan: Ensure the package source is tracked; add an explicit version pin (not just `>=0.1`). Production uses FalkorDB so the immediate risk is low (LadybugDB is dev-only default).

**`mcp[cli]>=1.0` broad version range:**
- Risk: The MCP SDK is at an early major version (1.x). Breaking protocol changes in minor releases are likely. The `>=1.0` pin with no upper bound accepts any future 1.x or 2.x release.
- Impact: Container image rebuild could pick up a breaking MCP version that changes SSE/streamable-http framing.
- Migration plan: Add an upper bound `mcp[cli]>=1.0,<2.0` and pin the tested minor version in the lockfile.

## Scaling Limits

**Search log table grows unbounded:**
- `pipeline.py:279-296` creates a `search_log` table with `AUTOINCREMENT` and a separate index. There is no trim or rotation logic in the visible codebase. Every search appends one row forever.
- Current capacity: Disk-bounded. At ~1 KB per row and 100 searches/day, this is ~35 MB/year — negligible currently.
- Limit: No hard limit, but on a 238 GB SSD shared with everything else, unbounded growth in `/dotmd-index/index.db` is a long-term concern.
- Scaling path: Add a trim statement (e.g., `DELETE FROM search_log WHERE id < (SELECT MAX(id) - 10000 FROM search_log)`) after each insert, or a scheduled vacuum of the log table.

---

*Concerns audit: 2026-05-10*
