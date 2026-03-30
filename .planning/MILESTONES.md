# Milestones

## v1.3 Production Packaging & Background Indexing (Shipped: 2026-03-28)

**Phases completed:** 4 phases, 8 plans, 16 tasks

**Key accomplishments:**

- Production packaging with parameterized docker-compose, bundled profiles (TEI + FalkorDB), health endpoint, WAL mode, and production include-based overlay
- External HTTP smoke tests — 5 tests covering semantic/BM25/graph engines, hybrid fusion, and API structure with skip-on-unavailable
- TEI concurrency and GLiNER batching benchmarks — proved concurrent TEI gives no throughput gain, GLiNER batching slower than sequential (+ OOM at bs=8)
- FTS5 BM25 replacement — SQLite FTS5 replaces rank_bm25+pickle for incremental keyword search with add/remove per chunk
- Background trickle indexer — watchdog inotify + hourly polling, per-file pipeline in asyncio.to_thread, TOML config, progress reporting with rate/ETA

---

## v1.2 FalkorDB Migration & Search Fix (Shipped: 2026-03-27)

**Phases completed:** 3 phases, 4 plans, 6 tasks

**Key accomplishments:**

- FalkorDB graph store adapter with 12 protocol methods, config-driven backend selection, and updated GraphStoreProtocol
- Config-driven graph store factory in pipeline with CLI status reporting of active backend
- Removed cross-encoder score threshold and added merge-back logic so all BM25 fusion candidates survive through reranking

---

## v1.1 Incremental Indexing (Shipped: 2026-03-26)

**Phases completed:** 3 phases, 5 plans, 9 tasks

**Key accomplishments:**

- FileTracker with two-stage mtime+size/MD5 change detection, per-file chunk deletion methods, and extended storage protocols for incremental indexing
- Per-file vector and graph delete methods with LadybugDB DETACH DELETE cascade validation across all 7 REL tables
- Diff-based incremental indexing via FileTracker integration -- modified/deleted files purged from all 3 stores, new files appended, unchanged files skipped entirely
- --force CLI flag threaded through DotMDService to IndexingPipeline, enabling user-triggered full re-index bypass of incremental change detection
- Diff counts threaded from FileDiff through IndexStats to CLI/API output with live change detection in status command

---
