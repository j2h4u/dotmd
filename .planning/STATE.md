---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Search Quality Evaluations
status: defining
last_updated: "2026-03-30T16:30:00.000Z"
last_activity: 2026-03-30
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
  percent: 0
---

# GSD State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-30)

**Core value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Current focus:** Defining requirements for v1.4

## Current Milestone

**v1.4 — Search Quality Evaluations**

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-03-30 — Milestone v1.4 started

## Performance Metrics

**Velocity:**

- Total plans completed: 10 (across v1.1 + v1.2)
- Average duration: —
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1-6 (v1.1+v1.2) | 10 | — | — |
| Phase 07 P02 | 5min | 2 tasks | 5 files |
| Phase 09-speed-benchmarks P01 | 3min | 2 tasks | 2 files |
| Phase 10 P02 | 2min | 2 tasks | 3 files |
| Phase 10 P01 | 4min | 2 tasks | 5 files |
| Phase 10 P03 | 4min | 2 tasks | 3 files |
| Phase 10 P04 | 2min | 2 tasks | 4 files |

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.2]: FalkorDB is production graph backend, LadybugDB kept as alternative
- [v1.2]: Removed cross-encoder score threshold — all fusion candidates survive reranking
- [Research]: Do NOT bundle second TEI instance — reuse shared TEI, document dependency
- [Research]: Benchmark TEI concurrency before implementing — bs=4 equals bs=32 suggests compute-bound
- [Phase 07]: Compose profiles for optional bundled services (TEI, FalkorDB) -- depends_on removed due to v5.1 profile incompatibility
- [Phase 07]: Production uses include: directive referencing repo compose as single source of truth
- [Phase 07]: Port override via DOTMD_PORT env var (not compose override ports) to avoid list merge
- [Phase 09-speed-benchmarks]: Standalone benchmark scripts with no dotmd imports -- test TEI HTTP and GLiNER model directly
- [Phase 10 P02]: TOML config loaded conditionally (only when file exists) -- no startup failure without config
- [Phase 10 P02]: Exclude patterns pruned during os.walk (not post-filtered) for performance on large directory trees
- [Phase 10]: FTS5 shares metadata store SQLite connection (WAL mode) instead of separate file
- [Phase 10]: unicode61 tokenizer for FTS5 to handle bilingual RU/EN content
- [Phase 10]: Per-file processing in thread pool via asyncio.to_thread to avoid blocking event loop
- [Phase 10]: Watchdog events bridged to asyncio via loop.call_soon_threadsafe with 2s debounce
- [Phase 10]: Service.status() always returns IndexStats (never None) so trickle progress is available pre-index

### Pending Todos

- Background trickle indexer (.planning/todos/pending/2026-03-27-background-trickle-indexer.md)
- Smoke tests (.planning/todos/pending/2026-03-27-smoke-tests.md)

### Blockers/Concerns

None yet.

---
*Last updated: 2026-03-27*
