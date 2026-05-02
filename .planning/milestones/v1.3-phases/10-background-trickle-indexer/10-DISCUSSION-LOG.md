# Phase 10: Background Trickle Indexer - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-27
**Phase:** 10-background-trickle-indexer
**Areas discussed:** Activation model, BM25 searchability, Status reporting, File processing order

---

## Activation Model

| Option | Description | Selected |
|--------|-------------|----------|
| Built into serve | Starts automatically with `dotmd serve`. Always runs in background | ✓ |
| Separate command | New `dotmd trickle` or `dotmd index --background` command | |
| Flag on serve | `dotmd serve --trickle` or env var to enable | |

**User's choice:** Built into serve
**Notes:** None — straightforward choice, zero extra steps to activate.

### Follow-up: Loop mode

| Option | Description | Selected |
|--------|-------------|----------|
| Continuous loop | Processes backlog, watches for new files, never stops | ✓ |
| One-time pass | Processes backlog, then sleeps until restart | |

**User's choice:** Continuous loop
**Notes:** User suggested inotify instead of polling for detecting new files.

### Follow-up: File detection mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Polling + pause | Simple diff loop with configurable sleep interval | |
| inotify (watchdog) | Watches directories via inotify. Zero CPU when idle | |
| Hybrid | inotify primary + rare polling fallback | ✓ |

**User's choice:** Hybrid (inotify + polling fallback)
**Notes:** inotify for instant reaction, polling as safety net for Docker bind mount edge cases.

---

## BM25 Searchability

| Option | Description | Selected |
|--------|-------------|----------|
| Every N files | Rebuild rank_bm25 pickle every 50-100 files | |
| Time-based | Rebuild every M minutes | |
| After every file | Maximum freshness, very expensive | |

**User's choice:** Asked for expert analysis — unfamiliar with BM25 internals.
**Notes:** User noted this problem has been solved many times in Elasticsearch etc.

### Follow-up: BM25 engine replacement

| Option | Description | Selected |
|--------|-------------|----------|
| SQLite FTS5 | Replace rank_bm25 with FTS5 table. Incremental INSERT, instant searchability | ✓ |
| rank_bm25 + batch | Keep rank_bm25, rebuild periodically with atomic swap | |
| Claude decides | Defer to researcher/planner | |

**User's choice:** SQLite FTS5
**Notes:** User asked about Russian language support. Confirmed FTS5 unicode61 tokenizer handles Cyrillic — parity with current tokenizer (no stemming for any language). Stemming deferred to future phase.

### Follow-up: Stemming timeline

| Option | Description | Selected |
|--------|-------------|----------|
| FTS5 + unicode61 now, stemming later | Baseline first, improve quality later | ✓ |
| Stemming in this phase | Add Russian/English stemming immediately | |

**User's choice:** FTS5 now, stemming later
**Notes:** None.

---

## Status Reporting

**User's initial question:** "What do you mean by status? There's no UI. Do you mean log entries?"

Clarified two channels: API (`/status`) and logs (`docker compose logs`).

| Option | Description | Selected |
|--------|-------------|----------|
| API/CLI + logs | `/status` returns progress JSON, plus per-file log lines | ✓ |
| Logs only | Progress only in stdout/stderr | |
| API only | JSON in `/status`, minimal logs | |

**User's choice:** API/CLI + logs

### Follow-up: Detail level

| Option | Description | Selected |
|--------|-------------|----------|
| Minimum | indexed_files, total_files, state | |
| With speed | Plus files_per_hour and ETA | ✓ |

**User's choice:** With speed (files_per_hour + ETA)
**Notes:** None.

---

## File Processing Order

| Option | Description | Selected |
|--------|-------------|----------|
| Newest first | Sort by mtime desc — fresh voicenotes before old scripts | ✓ |
| By directory | Alphabetical path order | |
| Claude decides | Defer choice | |

**User's choice:** Newest first (mtime desc)
**Notes:** None.

---

## Claude's Discretion

- Threading vs asyncio for background loop
- inotify event filtering and debouncing
- FTS5 table schema and migration strategy
- Polling fallback interval
- Error handling for individual file failures
- Whether to keep rank_bm25 as fallback or remove

## Deferred Ideas

- Russian/English stemming for FTS5 — future search quality phase
- FTS5 trigram tokenizer for substring matching
- Concurrent TEI requests (pending Phase 9 benchmark results)
- GLiNER batch NER (pending Phase 9 benchmark results)
