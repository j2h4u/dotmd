# Phase 10: Background Trickle Indexer - Context

**Gathered:** 2026-03-27
**Status:** Ready for planning

<domain>
## Phase Boundary

Unindexed files are processed gradually in the background while the API continues serving search queries. The background indexer is built into `dotmd serve` — starts automatically, runs continuously, discovers new files via inotify + polling fallback. Files become searchable across all engines immediately after processing (no BM25 rebuild delays). Progress is visible via API/CLI and logs.

</domain>

<decisions>
## Implementation Decisions

### Activation Model
- **D-01:** Background indexer is built into `dotmd serve` — starts automatically when the server starts. No separate command or flag needed.
- **D-02:** Runs as a continuous loop: processes backlog of unindexed files, then watches for new files. Never stops until SIGTERM.

### File Discovery
- **D-03:** Hybrid detection — inotify (via watchdog library) as primary mechanism for instant reaction to new files, plus rare polling (e.g., once per hour) as fallback for cases where inotify misses events (Docker bind mounts, NFS).
- **D-04:** Initial backlog: on startup, discover all unindexed files via FileTracker diff and process them before switching to watch mode.

### BM25 Engine Replacement
- **D-05:** Replace `rank_bm25` (BM25Okapi + pickle) with SQLite FTS5. Incremental INSERT per file — no batch rebuilds, no pickle, no atomic swap needed. Each file becomes BM25-searchable immediately after indexing.
- **D-06:** FTS5 tokenizer: `unicode61` — handles Cyrillic and other Unicode correctly. Parity with current tokenizer behavior (no stemming). Stemming (Russian + English) deferred to future search quality phase.
- **D-07:** This change makes BGIDX-04 (batched BM25 rebuild with atomic swap) obsolete — the requirement is satisfied by design since FTS5 is inherently incremental.

### Directory Filtering
- **D-08:** Exclude hidden directories (`.*`) and `node_modules/` at any depth. This removes ~5,700 junk .md files (dependency docs, caches, toolchains). Real corpus: ~8,400 markdown files (repos, docs, scripts, voicenotes) instead of ~14,100.
- **D-09:** Exclude patterns are configurable — not hardcoded. Live in config file (see D-14).

### Configuration File
- **D-10:** Introduce `~/.dotmd/config.toml` as the primary configuration source. Hierarchical TOML format — cleaner than flat env vars for structured settings like exclude patterns.
- **D-11:** Priority: env var (`DOTMD_*`) overrides config.toml, config.toml overrides code defaults. Env vars remain useful for Docker compose; config.toml for persistent settings that don't change per deployment.
- **D-12:** `pydantic-settings` v2 supports TOML natively (`TomlConfigSettingsSource`). Minimal code change to existing Settings class.

### File Processing Order
- **D-13:** Sort unindexed files by mtime descending — newest files first. Fresh voicenotes become searchable before old scripts and docs.

### Progress Reporting
- **D-14:** `GET /status` and `dotmd status` return background indexer state: `indexed_files`, `total_files`, `state` (idle/indexing/done), `files_per_hour`, `eta_minutes`.
- **D-15:** Logs: INFO-level log line per processed file with progress counter (e.g., "[trickle] 1,234/8,400 indexed: /path/to/file.md (3.2s)").

### Graceful Shutdown
- **D-16:** On SIGTERM, finish processing the current file, then shut down cleanly. No corrupt state in SQLite (WAL mode from Phase 7) or FTS5 index.

### CPU Control
- **D-17:** Configurable pause interval between files via config.toml (`[indexing] trickle_pause_seconds`) with env var override (`DOTMD_TRICKLE_PAUSE_SECONDS`). CPU priority via `docker update --cpu-shares` as documented in deployment.

### Claude's Discretion
- Threading/asyncio implementation for background loop (whatever fits FastAPI lifespan best)
- inotify event filtering (which events to watch, debouncing)
- Exact FTS5 table schema and migration from rank_bm25
- Polling interval for fallback (suggested: 1 hour)
- How to handle errors on individual files (skip and continue vs retry)
- Whether to keep rank_bm25 as a fallback or remove entirely

### Folded Todos
- **Background trickle indexer** (todo: 2026-03-27) — this todo's scope IS Phase 10's scope. Processing pending files at low priority with progress reporting.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Indexing Pipeline
- `backend/src/dotmd/ingestion/pipeline.py` — IndexingPipeline with `index()`, `_ingest_and_finalize()`, FileTracker integration
- `backend/src/dotmd/ingestion/file_tracker.py` — FileTracker with `diff()`, `save_fingerprint()`, `remove_fingerprint()` — tracks indexed vs unindexed files
- `backend/src/dotmd/ingestion/reader.py` — `discover_files()`, `read_file()`
- `backend/src/dotmd/ingestion/chunker.py` — `chunk_file()`

### BM25 (to be replaced)
- `backend/src/dotmd/search/bm25.py` — Current BM25SearchEngine using rank_bm25 + pickle. Replace with FTS5 implementation.
- `backend/src/dotmd/utils/text.py` — `tokenize()` function (line 132) — current BM25 tokenizer; FTS5 unicode61 replaces this for BM25

### API / Service
- `backend/src/dotmd/api/server.py` — FastAPI app with `_lifespan()` context manager; background task hooks into this
- `backend/src/dotmd/api/service.py` — DotMDService facade; `index()`, `status()`, `warmup()` methods
- `backend/src/dotmd/cli.py` — CLI `status` command

### Storage
- `backend/src/dotmd/storage/metadata.py` — SQLiteMetadataStore (WAL mode enabled)
- `backend/src/dotmd/storage/sqlite_vec.py` — SQLiteVecVectorStore (WAL mode enabled)
- `backend/src/dotmd/storage/falkordb_graph.py` — FalkorDB adapter (network-based, concurrent access safe)

### Configuration
- `backend/src/dotmd/core/config.py` — Settings class (pydantic-settings); add TOML source + trickle/exclude settings
- `backend/src/dotmd/core/models.py` — IndexStats model; extend with trickle progress fields

### Requirements
- `.planning/REQUIREMENTS.md` — BGIDX-01 through BGIDX-06

### Architecture
- `.planning/codebase/ARCHITECTURE.md` — Layered architecture, data flow, key abstractions
- `.planning/codebase/CONVENTIONS.md` — Coding conventions, naming, error handling patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- **FileTracker.diff()**: Already classifies files as new/modified/deleted/unchanged — core primitive for discovering unindexed files
- **IndexingPipeline._ingest_and_finalize()**: Processes files through full pipeline (chunk → embed → extract → graph). Can be refactored to process single files
- **FastAPI lifespan**: `_lifespan()` context manager in server.py — background task attaches here
- **SQLite WAL mode**: Already enabled on metadata.db and vec.db (Phase 7) — concurrent reads safe during background writes

### Established Patterns
- **Environment-driven config**: All settings via `DOTMD_` prefix env vars (to be extended with config.toml as primary source)
- **Protocol-based search engines**: `SearchEngineProtocol` — FTS5 engine implements same interface
- **Module-level loggers**: `logger = logging.getLogger(__name__)`
- **Lazy model loading**: ML models loaded on first use

### Integration Points
- `search/bm25.py` — replace BM25SearchEngine internals (keep SearchEngineProtocol interface)
- `api/server.py:_lifespan()` — add background task startup/shutdown
- `api/service.py:status()` — extend IndexStats with trickle progress
- `core/config.py` — add TOML config source, `trickle_pause_seconds`, `exclude_dirs` settings
- `core/models.py` — add trickle fields to IndexStats
- `ingestion/pipeline.py` — extract per-file processing from `_ingest_and_finalize()`
- `pyproject.toml` — add `watchdog` dependency, remove `rank_bm25` (if fully replaced), add `pydantic-settings[toml]` extra
- `ingestion/reader.py:discover_files()` — add exclude pattern filtering (currently no filtering at all)

</code_context>

<specifics>
## Specific Ideas

- inotify catches new voicenotes from daily sync immediately — no waiting for poll cycle
- ~8,400 file corpus after filtering (was 14k before excluding node_modules/dotfiles). Newest first means recent voicenotes indexed within hours, old docs at the end
- FTS5 is a significant improvement: eliminates the entire BM25 rebuild problem instead of working around it
- The `watchdog` library is the de facto Python inotify wrapper — widely used, well maintained

</specifics>

<deferred>
## Deferred Ideas

- **Russian/English stemming for BM25** — FTS5 supports custom tokenizers and ICU. Separate search quality improvement phase.
- **FTS5 trigram tokenizer** — enables substring matching. Evaluate after FTS5 baseline works.
- **Concurrent TEI requests** — Phase 9 benchmarks may show throughput gains. Apply to trickle indexer if worthwhile.
- **GLiNER batch NER** — Phase 9 benchmarks may show batching gains. Evaluate for trickle context.

### Reviewed Todos (not folded)
- **Migrate graph store from LadybugDB to FalkorDB** (score: 0.9) — completed in v1.2 (Phases 4-6)
- **Scout other dotmd forks for ideas** (score: 0.6) — general backlog, not phase-specific
- **Smoke tests for search pipeline** (score: 0.6) — Phase 8 scope

</deferred>

---

*Phase: 10-background-trickle-indexer*
*Context gathered: 2026-03-27*
