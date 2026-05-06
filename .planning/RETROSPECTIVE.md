# Retrospective

## Milestone: v1.1 — Incremental Indexing

**Shipped:** 2026-03-26
**Phases:** 3 | **Plans:** 5 | **Tasks:** 9

### What Was Built
- FileTracker with two-stage mtime+size/MD5 change detection
- Per-file delete across all 3 stores (metadata, vectors, graph)
- Diff-based incremental indexing — unchanged files skipped entirely
- `--force` flag for full re-index bypass
- CLI diff summary + live change detection in status command
- Pipeline timing metrics with run_id correlation
- Mandatory TEI embedding server (no local model fallback)

### What Worked
- TDD approach (red → green → refactor) caught edge cases early (no-changes short-circuit, stale diff counts)
- Protocol-based architecture made adding new fields to IndexStats clean — changes threaded through naturally
- GSD phase structure kept scope focused — 3 clean phases with no scope creep
- Existing test infrastructure (conftest fixtures) made new tests fast to write

### What Was Inefficient
- Ran `uv run dotmd index` from host instead of Docker — wasted 10+ minutes on local model loading before killing it
- `seed-fingerprints` command written, fixed for lock, then deleted — could have skipped it entirely
- LadybugDB lock issue hit 3 times before being properly fixed (server.py creating new service per request)
- Phase 3 roadmap table showed "Pending" even after completion — state sync gap

### Patterns Established
- Always test via Docker (`docker compose exec` or API), never from host
- `DOTMD_EMBEDDING_URL` mandatory — prevents silent local model fallback
- Pipeline logs with `[run_id]` prefix for stage-level timing correlation
- Full re-index via API (`POST /index` with `force: true`), not CLI (avoids LadybugDB lock)

### Key Lessons
- Embedded graph DBs with file locks are fundamentally incompatible with server + CLI architecture — FalkorDB migration is necessary, not optional
- Schema migrations via idempotent `ALTER TABLE` + try/except work well for SQLite
- `read_only=True` on the global service was a latent bug — write endpoints need write access

### Cost Observations
- Model mix: 100% Opus 4.6 (1M context)
- Sessions: 2 (planning + execution in one, deployment/testing in another)
- Notable: Single-plan phases execute cleanly with one subagent, no wave overhead

## Milestone: v1.2 — FalkorDB Migration & Search Fix

**Shipped:** 2026-03-27
**Phases:** 3 | **Plans:** 4 | **Tasks:** 6

### What Was Built
- FalkorDB graph store adapter (12 protocol methods, written from scratch)
- Config-driven graph backend selection (`graph_backend`, `falkordb_url`, `falkordb_graph_name`)
- Pipeline factory for backend selection with lazy imports
- BM25 hybrid fix — removed reranker score threshold, added merge-back logic for fusion candidates
- Docker networking to FalkorDB (graphiti_default external network)
- Full re-index on FalkorDB: 229 files → 3520 entities → 20269 edges
- TEI batch size auto-tuning probe (start high, halve on 413)

### What Worked
- Phase 4 (adapter) and Phase 5 (BM25 fix) were independent — could have been parallelized
- FalkorDB adapter from scratch was cleaner than porting from LadybugDB — dialect differences would have been a trap
- Expert panel approach for BM25 diagnosis gave unanimous clear direction (remove threshold, keep weights)
- Auto-advance pipeline (discuss → plan → execute) worked smoothly for Phase 6
- Research agent caught the stale Docker image blocker before execution

### What Was Inefficient
- Full `/mnt` re-index launched without checking file count — discovered 13,515 files (vs expected 227) after 20 minutes of TEI batching
- TEI batch size changed to 32 then back to 4 — should have benchmarked first instead of assuming bigger=faster
- `nice -n 19` on `docker compose run` — doesn't affect container process priority (need `docker update`)
- Three failed re-index attempts before the successful one (scope issue, hung process, wrong batch size)

### Patterns Established
- `docker update --cpu-shares 2` for low-priority container work, not nice/ionice on CLI
- TEI batch size: small (4-8) is faster on CPU due to lower queue_time — measure integral throughput, not per-batch time
- LadybugDB is NOT legacy — keep as alternative embedded backend for upstream compatibility
- Container logs with `--rm` are ephemeral — telemetry needed for auto-tuning must persist to disk

### Key Lessons
- Dataset size assumptions are dangerous — always check `find | wc -l` before `--force` re-index
- Auto-tuning should optimize end-to-end throughput (texts/sec), not just avoid errors (413)
- Background trickle indexing is the right paradigm for large datasets on constrained hardware — heroic one-shot re-index doesn't scale

### Cost Observations
- Model mix: 100% Opus 4.6 (1M context)
- Sessions: 2 (planning in one, execution + debugging in another)
- Notable: Phase 6 execution done inline (no subagent) — simpler for single-plan phases modifying files outside repo

## Milestone: v1.3 — Production Packaging & Background Indexing

**Shipped:** 2026-03-28
**Phases:** 4 | **Plans:** 8 | **Tasks:** 16

### What Was Built
- Production docker-compose with parameterized env vars, bundled profiles (TEI + FalkorDB), health endpoint
- Production overlay via compose `include:` directive at /opt/docker/dotmd/
- SQLite WAL mode on all databases for concurrent access
- External HTTP smoke tests (5 tests, skip-on-unavailable)
- TEI concurrency benchmark and GLiNER batching benchmark (both closed optimization paths)
- FTS5 BM25 replacement — SQLite FTS5 replaces rank_bm25+pickle, incremental add/remove
- Background trickle indexer — watchdog inotify + hourly polling, per-file pipeline, TOML config
- Trickle progress reporting (rate, ETA) in CLI status and API /status

### What Worked
- Benchmark-first approach for SPEED-01/02 — avoided implementing optimizations that wouldn't help (concurrent TEI, GLiNER batching)
- FTS5 sharing metadata store SQLite connection — clean architecture, no separate DB file
- Compose `include:` pattern for production overlay — single source of truth in repo
- Worktree isolation for parallel plan execution (Plans 10-01 through 10-04)

### What Was Inefficient
- Compose v5.1 `depends_on` + profiles interaction undocumented — hit errors that research didn't predict
- Compose port list merge behavior (append, not replace) — had to discover through debugging
- Worktrees branched from main missing other plans' changes — required fast-forward merges before starting
- SPEED-01/02 requirements initially scoped as "optimize" — rescoped to "benchmark and decide" after results

### Patterns Established
- Benchmark script pattern: synthetic data → warmup → N iterations → stats table → CONCLUSION
- Smoke tests: external HTTP-only, no dotmd imports, pytest.ini isolation
- Compose profile pattern: `--profile bundled` for optional bundled services
- TomlConfigSettingsSource: conditional TOML loading when config.toml exists
- Watchdog-to-asyncio bridge via loop.call_soon_threadsafe into asyncio.Queue

### Key Lessons
- Always benchmark before optimizing — both TEI concurrency and GLiNER batching were net negatives
- Compose `include:` auto-discovers .env at included file directory — use `required: false` on env_file
- Compose port lists merge by append — use env var interpolation for port overrides, not override files
- FTS5 unicode61 tokenizer handles bilingual RU/EN well for keyword search

### Cost Observations
- Model mix: 100% Opus 4.6 (1M context)
- Sessions: 3 (packaging, benchmarks, trickle indexer)
- Notable: Phase 10 (4 plans) executed with worktree parallelization — fastest multi-plan phase yet

## Milestone: v1.4 — Search Quality & Architecture

**Shipped:** 2026-05-06
**Phases:** 12 | **Plans:** 30 | **Tasks:** 61

### What Was Built
- Content-addressed caching and M2M content-dedup schema groundwork
- Reranker selection, adapter/factory boundary, comparison surfaces, latency and quality benchmarks
- Honest local/live test contract and cleaned smoke behavior
- Operator config boundary with runtime validation and explicit internal defaults
- Filesystem source abstraction MVP with persisted source provenance
- Source-ref-first public MCP search/read contract, with filesystem paths kept internal

### What Worked
- Benchmark-first reranker work prevented CPU-unusable candidates from becoming production defaults.
- The Phase 25 then Phase 26 bridge was the right order: first preserve filesystem behavior through source models, then remove the public path-first contract before non-filesystem sources.
- Nyquist validation surfaced mostly documentation/artifact debt after implementation, not major product gaps.

### What Was Inefficient
- ROADMAP and milestone prose drifted while phases continued; milestone close needed manual cleanup to avoid stale phase boundaries.
- Some GSD health info entries are naming-shape noise (`25-01-SUMMARY.md` vs `SUMMARY.md`) and should not be treated as blocking.
- Plan summaries sometimes leaked review noise into generated milestone accomplishments, requiring human cleanup.

### Patterns Established
- Treat `999.x` as backlog until explicitly promoted.
- For source-adapter work, separate source identity, parser/content behavior, and layered metadata.
- Every source/refactor plan should answer whether it requires full reindex; default to incremental/backfill paths.

### Key Lessons
- Milestone boundaries can be product boundaries even when the last phases are bridge work for the next milestone; document the bridge explicitly instead of reopening shipped scope.
- Source refs are now the public contract. Future Telegram/source phases should build on `search -> ref -> drill/read`, not path-shaped compatibility.
- Closing a milestone should run open-artifact audit first, then record acknowledged deferred items in STATE.md so backlog noise does not masquerade as unfinished phase work.

### Cost Observations
- Model mix: mixed Codex/OpenCode/GSD review tooling
- Sessions: multiple phase execution, validation, security, and audit sessions
- Notable: Late milestone validation paid down artifact confidence without requiring broad implementation rewrites.

## Cross-Milestone Trends

| Milestone | Phases | Plans | Duration | Key Metric |
|-----------|--------|-------|----------|------------|
| v1.1 | 3 | 5 | 2 days | Incremental index: <1s (was 50min) |
| v1.2 | 3 | 4 | 2 days | FalkorDB: concurrent CLI+API, 3520 entities |
| v1.3 | 4 | 8 | 2 days | Production deploy, trickle indexer live |
| v1.4 | 12 | 30 | 13 days | Source-ref-first MCP contract, reranker benchmarks, source-adapter bridge |
