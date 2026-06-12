# Milestones

## v1.7 Storage Simplification (Shipped: 2026-06-12)

**Phases completed:** 1 phases, 5 plans, 14 tasks

**Key accomplishments:**

- WAL-safe copied SQLite snapshots plus live Falkor/feedback inventory evidence for transform-first Surreal migration planning
- Thin Surreal storage adapters with gate-checked transform-only import of chunks, vectors, graph rows, and feedback evidence
- Copied-snapshot retrieval parity harness showing vector parity pass but blocking FTS weighting, hybrid attribution, and scale-gate failures
- Copied-store operations rehearsal and final reject recommendation for Embedded SurrealDB storage migration
- Verified the official `surrealdb` SDK, proved embedded `surrealkv://` commit/rollback semantics on local stores, and added a writer-safety gate before Plan 38-02 schema/import work

**Decision at close:** Phase 38 rejected the first compatibility/parity-style
SurrealDB replacement prototype as migrate-ready, but established that data
movement and operations are plausible. The next milestone continues with a
SurrealDB-native architecture, quality evaluation, production cutover, and
legacy stack removal.

**Known deferred items at close:** 8 old quick/todo/seed artifacts acknowledged
as unrelated to v1.7 closeout; see `.planning/STATE.md`.

---

## v1.6 Unified Source Architecture (Shipped: 2026-05-13)

**Phases completed:** 6 phases complete, 18 plans complete

**Key accomplishments:**

- Source descriptors now describe source kind, display metadata, config/auth,
  cursor schema, and capability flags.

- Source lifecycle construction now flows through one registry/config/auth/cursor
  boundary for filesystem and Telegram.

- Local and source-native results now share a federated `SearchCandidate`
  contract with ref-first read/drill behavior.

- Filesystem and Telegram were unified on the source contract, including
  Telegram sync/reuse and native federated search.

- Airweave connector compatibility was proven through a Gmail bridge without
  adopting Airweave's indexing/runtime stack.

**Known deferred items at close:** broader third-party connector rollout and
storage consolidation, now continued as Phase 38.

---

## v1.5 Telegram Source Adapter (Shipped: 2026-05-08)

**Phases completed:** 4 phases complete, 1 phase deferred, 13 plans complete

**Key accomplishments:**

- Resource bindings now separate active public source visibility from retained
  content and derived artifacts.

- Application source provider contracts now model source documents, source
  units, cursors, fingerprints, and neighboring source-unit reads.

- Telegram ingestion now flows through the existing `mcp-telegram` runtime
  without dotMD owning Telegram auth or a Telethon client.

- Telegram source units persist into dotMD search indexes with stable
  message-shaped refs and source-unit provenance.

- Public Telegram `search -> drill/read` round-trip was verified against live
  containers and real Telegram messages.

- Phase 30 incremental sync/reuse was intentionally deferred to Backlog 999.30
  so it can land through the unified source architecture rather than a
  Telegram-only legacy path.

**Known deferred items at close:** 11 old planning inbox artifacts ignored for
closeout, plus Phase 30 carried to Backlog 999.30.

---

## v1.4 Search Quality & Architecture (Shipped: 2026-05-06)

**Phases completed:** 12 phases, 30 plans, 61 tasks

**Key accomplishments:**

- Search quality evaluation infrastructure and reranker selection/refactor work completed, including Qwen3 candidate support, shared-pool comparison, latency diagnostics, and benchmark methodology cleanup.
- Test contract and live smoke behavior tightened so local tests stay local, MCP e2e failures are honest, and stale smoke coverage no longer hides integration problems.
- Configuration boundary clarified: operator-facing settings are explicit and validated, while internal tuning constants are named defaults rather than public config.
- Filesystem source abstraction introduced as the source-adapter MVP, with SourceDocument identity, ingestion routing, provenance persistence, and metadata-only refresh behavior preserved.
- Public read/search contract moved to source refs: search returns ref-first results, MCP/CLI use drill(ref) and read(ref), and docs keep filesystem paths internal.
- Milestone boundary documented as a bridge: Phase 25/26 enable the next source-adapter milestone, while Telegram and other non-filesystem sources remain future work.

**Known deferred items at close:** 10 (see STATE.md Deferred Items)

---

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
