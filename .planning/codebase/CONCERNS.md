# Codebase Concerns

**Analysis Date:** 2026-03-23

## Tech Debt

**Broad exception handling without specificity:**
- Issue: Multiple storage and extraction modules use bare `except Exception:` blocks that swallow errors indiscriminately, masking real problems
- Files: `backend/src/dotmd/storage/vector.py` (lines 63, 91, 105), `backend/src/dotmd/storage/sqlite_vec.py` (lines 154, 166, 185, 194), `backend/src/dotmd/storage/graph.py` (lines 92, 243, 248, 269, 292, 310, 324, 337)
- Impact: Silent failures during schema initialization, vector operations, and graph queries make debugging difficult. Failed index operations may leave data in an inconsistent state without warning
- Fix approach: Replace bare `except Exception` with specific exception types (e.g., `sqlite3.OperationalError`, `lb.QueryError`). Log at WARNING level with full traceback. Allow critical errors (disk full, permission denied) to propagate

**Hardcoded score thresholds and weights scattered across config:**
- Issue: Reranker score threshold (-8.0), semantic score floor (0.4), reranker length penalty (0.8–1.0 factor), and RRF weights (k=60, graph_rrf_weight=1.5) are defined in multiple places without clear rationale
- Files: `backend/src/dotmd/core/config.py`, `backend/src/dotmd/api/service.py` (lines 213–225), `backend/src/dotmd/search/reranker.py` (line 123), `backend/src/dotmd/search/fusion.py` (lines 127, 194)
- Impact: Parameter tuning requires changes across multiple files. No easy way to run A/B tests or experiment with different configurations. Constants lack documentation of why they were chosen
- Fix approach: Consolidate all scoring parameters into `Settings` class with docstrings explaining each threshold. Make them overridable via environment variables

**Vector store type annotation mismatch in pipeline accessor:**
- Issue: `IndexingPipeline.vector_store` property returns type-hinted `LanceDBVectorStore` but the actual store is a `VectorStoreProtocol` that can be either LanceDB or SQLiteVec
- Files: `backend/src/dotmd/ingestion/pipeline.py` (line 276–278)
- Impact: Type checkers will complain; callers cannot determine which backend is active at runtime; makes testing with different backends difficult
- Fix approach: Change return type to `VectorStoreProtocol`. Add a runtime property `backend_type()` method to inspect which implementation is active

## Known Bugs

**Graph store connection leaks in read-only mode:**
- Symptoms: When `read_only=True`, `LadybugDBGraphStore._connection()` opens temporary connections but may not clean up if exceptions occur mid-query
- Files: `backend/src/dotmd/storage/graph.py` (lines 74–85)
- Trigger: Call graph store methods in read-only mode, then check resource usage (open file handles, database locks)
- Workaround: Ensure all graph queries complete without exception. Consider explicit connection pooling

**Word position index in snippet extraction can fail silently:**
- Symptoms: Snippet extraction in `_extract_best_snippet()` builds a character position index but uses `text.index()` which raises `ValueError` if a word appears later in the text with different context
- Files: `backend/src/dotmd/search/fusion.py` (line 41)
- Trigger: Text with repeated words or overlapping sequences where `text.index()` finds a different position than expected
- Workaround: None currently; may result in incorrect snippets without error

**Bare schema initialization errors swallowed silently:**
- Symptoms: If a Cypher statement fails during graph schema init, it is logged at DEBUG level and ignored, potentially leaving the graph in a partially-initialized state
- Files: `backend/src/dotmd/storage/graph.py` (lines 87–94)
- Trigger: Malformed SQL, schema conflicts, or disk issues during first graph initialization
- Workaround: Manually inspect `~/.dotmd/graphdb` and delete if corrupted; re-index

## Security Considerations

**No input validation on chunk text or user queries:**
- Risk: Chunk text from markdown files is stored and queried without sanitization. Malicious markdown (e.g., with embedded SQL or Cypher injection attempts) could be reflected in snippets or cause injection attacks
- Files: `backend/src/dotmd/ingestion/chunker.py`, `backend/src/dotmd/search/fusion.py`, `backend/src/dotmd/api/service.py`
- Current mitigation: LanceDB, SQLiteVec, and LadybugDB use parameterized queries/bindings, so SQL/Cypher injection is unlikely. Snippets are plain text truncation, not evaluated
- Recommendations: Add unit tests for edge cases (null bytes, very long queries, special characters). Document security assumptions. Consider adding query length limits

**HTTP embedding server has no authentication:**
- Risk: If `DOTMD_EMBEDDING_URL` points to a TEI endpoint, there is no API key or TLS verification. An attacker could intercept or redirect embeddings
- Files: `backend/src/dotmd/search/semantic.py` (lines 74–98)
- Current mitigation: The HTTP call uses httpx with `timeout=120s` but no cert verification or auth headers
- Recommendations: Add `verify_ssl` option to Settings. Support `Authorization` header for bearer tokens. Document that TEI should run on a trusted network or behind a reverse proxy with auth

**Acronym dictionary loaded from disk without validation:**
- Risk: If `~/.dotmd/acronyms.json` is corrupted or tampered with, JSON parsing could fail and suppress the error silently
- Files: `backend/src/dotmd/api/service.py` (lines 257–275)
- Current mitigation: Wrapped in try/except that logs warning and returns None; query expansion gracefully handles None
- Recommendations: Validate acronym dict structure (must be `dict[str, list[str]]`). Add file integrity check (CRC or signature)

## Performance Bottlenecks

**Sequential snippet extraction with O(n²) window scanning:**
- Problem: For each window position, the code scans all query tokens and checks if they appear in the window substring. With long queries and long chunks, this is slow
- Files: `backend/src/dotmd/search/fusion.py` (lines 22–73)
- Cause: `for i, start in enumerate(word_starts): for t in query_tokens: if t in window` is nested loop with substring search
- Improvement path: Use a Aho-Corasick automaton or regex to find all query term positions in advance. Then slide a window and count term hits in O(1) with a counter

**Reranker model loads on every first query:**
- Problem: `Reranker._load_model()` is called in `DotMDService.search()` (line 201) but only caches on first call. After model is loaded, every rerank operation must deserialize cross-encoder and run prediction
- Files: `backend/src/dotmd/api/service.py` (line 201), `backend/src/dotmd/search/reranker.py` (lines 56–63, 112)
- Cause: Model is loaded lazily, which is good for startup, but `warmup()` doesn't pre-load the reranker
- Improvement path: In `warmup()`, call `self._reranker._load_model()` (already done at line 79). Also consider batching rerank calls to amortize model loading

**NER extraction processes all chunks serially:**
- Problem: `NERExtractor.extract()` iterates through chunks one-by-one, calling GLiNER predict for each. GLiNER can batch multiple texts efficiently
- Files: `backend/src/dotmd/extraction/ner.py` (lines 85–90)
- Cause: Each chunk is processed independently with `model.predict_entities(chunk.text, ...)` instead of batching
- Improvement path: Batch chunks into groups (e.g., 8–16 per batch) and call GLiNER with a batch API if available. Fall back to serial processing if no batch API exists

**Graph neighbor queries scan all relationship tables:**
- Problem: `LadybugDBGraphStore.get_neighbors()` runs a single MATCH with variable-length paths, which scans all relationship tables. For large graphs, this can be slow
- Files: `backend/src/dotmd/storage/graph.py` (lines 204–231)
- Cause: Cypher query `MATCH (a:Label {id})-[r* 1..N]-(b)` without indices or early termination
- Improvement path: Add database indices on node IDs. Use LIMIT in Cypher to stop early after finding N neighbors. Consider precomputing k-hop neighborhoods on index time

## Fragile Areas

**Graph schema depends on exact relationship table naming and ordering:**
- Files: `backend/src/dotmd/storage/graph.py` (lines 20–47)
- Why fragile: The `_REL_TABLE_MAP` dict is a hardcoded lookup. If relationship types are added or removed, the map must be updated manually. `_find_node_label()` iterates through a fixed list of labels, so new node types are not discoverable
- Safe modification: Add a method to dynamically register node and relationship types. Use LadybugDB's schema introspection API if available to discover actual tables instead of hardcoding
- Test coverage: No tests for graph schema migrations or adding new node/relationship types

**Chunk ID determinism depends on file path string representation:**
- Files: `backend/src/dotmd/ingestion/chunker.py` (lines 19–22)
- Why fragile: Chunk IDs are MD5 hashes of `f"{file_path}:{chunk_index}"`. If file paths are normalized differently on Windows vs. POSIX (e.g., `\` vs. `/`), the same logical file produces different chunk IDs, breaking index consistency
- Safe modification: Normalize file paths to POSIX format (`/`) before hashing. Add a test that verifies chunk IDs are identical across platforms
- Test coverage: No cross-platform tests for chunk ID stability

**Reranker score blending uses hardcoded weights:**
- Files: `backend/src/dotmd/api/service.py` (lines 207–225)
- Why fragile: The blend factor (0.4 fusion score, 0.6 reranker score) and min-max normalization have no configuration or rationale. If reranker scores are out-of-range, normalization breaks
- Safe modification: Add `reranker_blend_weight` to Settings. Handle edge cases: if all scores are identical, skip normalization. Document why these weights were chosen (e.g., via ablation study)
- Test coverage: No unit tests for edge cases (all results tied, extreme score distributions)

**Snippet extraction assumes query tokens are valid regex:**
- Files: `backend/src/dotmd/search/fusion.py` (line 27)
- Why fragile: `re.findall(r"\w+", query.lower())` works for most queries but fails if user enters special regex chars (e.g., `[query]` or `(test)`). The code doesn't sanitize or quote the regex pattern
- Safe modification: Use `re.escape()` or implement a simple tokenizer instead of regex. Add tests for edge case queries
- Test coverage: No tests for special characters in queries

## Scaling Limits

**SQLiteVec batch insert deletes all vectors on re-index:**
- Current capacity: Works fine up to ~100k chunks; at 1M chunks, full vector table drop + recreate takes seconds
- Limit: Linear time to rebuild entire vector table scales poorly. If index is called frequently (e.g., incremental indexing), constant full rebuilds are expensive
- Scaling path: Implement incremental append instead of delete-all. Add a `update_chunks()` method that upserts by chunk_id instead of clearing the table. Support partial re-indexing

**LanceDB vs SQLiteVec memory usage:**
- Current capacity: LanceDB loads entire index into memory during ANN search; SQLiteVec streams from disk. At 500k chunks (384-dim), LanceDB uses ~600MB RAM
- Limit: On memory-constrained systems (e.g., RPi, low-cost hosting), LanceDB may exhaust RAM. SQLiteVec is better but slower
- Scaling path: Add a memory budget parameter. Spill to disk if needed. Or use a different vector DB (e.g., Qdrant, Weaviate) that supports indexing strategies beyond brute-force

**Graph database doesn't support concurrent writes:**
- Current capacity: Single MCP server or API server works fine. Multiple processes attempting to index or mutate graph concurrently will lock
- Limit: LadybugDB (like Kuzu) uses table-level locking, so even reads can block writes. No support for distributed graphs
- Scaling path: For multi-server deployments, use a separate graph service (e.g., Neo4j, Weaviate) or add write queuing + deduplication at the application layer

## Dependencies at Risk

**GLiNER zero-shot NER with no fallback:**
- Risk: If `urchade/gliner_multi-v2.1` model becomes unavailable or the HuggingFace hub goes down, NER extraction fails entirely. No graceful degradation
- Impact: Index operation fails if NER is enabled and model can't download
- Migration plan: Make NER optional; fall back to structural extraction only if GLiNER fails. Cache the model locally in `~/.dotmd/` with a checksum to avoid repeated downloads

**LadybugDB forked from Kuzu with custom patches:**
- Risk: `real_ladybug` is a custom fork. If upstream Kuzu receives critical security updates, they won't be backported to LadybugDB unless maintainers actively sync
- Impact: Potential SQL injection vulnerabilities or performance regressions if Kuzu patches aren't merged
- Migration plan: Monitor LadybugDB GitHub for upstream syncs. Consider switching to official Kuzu if LadybugDB maintenance stalls. Add security scanning to CI

**sentence-transformers embedding model pinned to specific version:**
- Risk: Default model `BAAI/bge-small-en-v1.5` is fetched from HuggingFace hub. If it's removed or changed, existing indices become incompatible
- Impact: Re-indexing with a different model produces different embeddings, invalidating the vector store
- Migration plan: Cache embeddings model locally during index. Add a schema version field to track which model was used. Support model migrations (e.g., re-embedding old vectors with new model)

**PyTorch version constraints due to hardware:**
- Risk: PyTorch >=2.5 requires AVX2 CPU support. Some old/embedded hardware doesn't have AVX2, causing SIGILL at runtime
- Impact: dotMD crashes on non-AVX2 hardware (e.g., older Xeons, ARM servers without NEON)
- Migration plan: Test on a range of hardware. Provide fallback pure-Python implementations or use ONNX Runtime which has better hardware support. Document minimum CPU features in README

## Missing Critical Features

**No incremental indexing:**
- Problem: Every call to `index()` deletes and rebuilds all stores. If you add 10 new markdown files to a large vault, the entire index is rebuilt from scratch
- Blocks: Fast re-indexing workflows (e.g., Obsidian vault with daily sync). Continuous indexing setups

**No index versioning or migration support:**
- Problem: If the schema changes (e.g., new embedding model, new extraction type), there's no automated way to migrate old indices. Users must delete and rebuild
- Blocks: Zero-downtime schema upgrades. A/B testing different configurations

**No distributed or cloud-hosted vector store option:**
- Problem: All backends are local files. No support for Pinecone, Weaviate, or other managed services
- Blocks: Cloud-native deployments. Multi-region or high-availability setups

**No audit or change tracking:**
- Problem: If a chunk is modified or deleted, there's no history. No way to know when the index was last updated or by whom
- Blocks: Compliance/audit use cases. Debugging index staleness issues

## Test Coverage Gaps

**No integration tests for mixed search modes:**
- What's not tested: Hybrid search with all three engines (semantic, BM25, graph) returning results; RRF fusion with varying result set sizes; cross-encoder reranking edge cases
- Files: `backend/src/dotmd/search/fusion.py`, `backend/src/dotmd/api/service.py`
- Risk: Bug in result ordering or score blending goes undetected until production
- Priority: High

**No tests for graph schema migrations or corrupted databases:**
- What's not tested: Upgrading from old to new graph schema; recovering from a partially-initialized graph; adding new node or relationship types
- Files: `backend/src/dotmd/storage/graph.py`
- Risk: Silent failures when graph DB is corrupted; no clear error messages for schema incompatibility
- Priority: High

**No tests for very large chunks or pathological markdown:**
- What's not tested: Chunks exceeding max_tokens; markdown with deeply nested headings; chunks with special characters, unicode, or RTL text
- Files: `backend/src/dotmd/ingestion/chunker.py`, `backend/src/dotmd/search/fusion.py`
- Risk: Chunker or snippet extraction may fail or produce invalid results on edge-case inputs
- Priority: Medium

**No performance/benchmark tests:**
- What's not tested: Indexing latency as a function of file count and chunk count; search latency under different query complexities; memory usage with various backends
- Files: All
- Risk: Performance regressions go undetected; scaling properties are unknown
- Priority: Medium

**No tests for HTTP embedding server fallback:**
- What's not tested: TEI server timeout, HTTP 5xx errors, malformed responses; fallback to local embeddings
- Files: `backend/src/dotmd/search/semantic.py`
- Risk: If embedding server is slow or down, the whole index operation times out without graceful fallback
- Priority: Medium

---

*Concerns audit: 2026-03-23*
