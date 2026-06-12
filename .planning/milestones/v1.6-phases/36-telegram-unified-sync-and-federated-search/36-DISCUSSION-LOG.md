# Phase 36: Telegram unified sync and federated search - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 36-telegram-unified-sync-and-federated-search
**Areas discussed:** Sync trigger surface, Message chunk granularity, Sync orchestrator shape (advisor panel), Unchanged message skip strategy (advisor panel), Trickle integration for application sources (advisor panel)

---

## Sync Trigger Surface

| Option | Description | Selected |
|--------|-------------|----------|
| CLI only | `dotmd sync telegram` — manual trigger, no background processes | |
| Auto in background | Trickle adds Telegram sync to its cycle | ✓ |
| Both | CLI for manual run + trickle for periodic auto-sync | |

**User's choice:** Автоматически в фоне (Auto in background)
**Notes:** User preference was clear — Telegram sync should run without user intervention, same operational model as filesystem trickle.

---

## Message Chunk Granularity

| Option | Description | Selected |
|--------|-------------|----------|
| One message = one chunk | Each SourceUnit becomes exactly one indexed chunk | ✓ |
| Grouped context windows | N adjacent messages → one chunk (better semantic context) | |

**User's choice:** Одно сообщение = один чанк (One message = one chunk)
**Notes:** Simpler, faster sync, direct ref mapping. Low-signal messages (ok/да/👍) already filtered by `is_low_signal_telegram_text` before embedding.

---

## Sync Orchestrator Shape (Advisor Panel)

| Option | Description | Selected |
|--------|-------------|----------|
| Method(s) on DotMDService | `service.sync_telegram()` — thin coordinator using existing pipeline | |
| Dedicated TelegramSyncPipeline | New class in `ingestion/`, mirrors IndexingPipeline | |
| Separate asyncio task | Thin poller task drives `pipeline.ingest_application_source_runtime()` | ✓ |

**User's choice:** Delegated to advisor panel
**Notes:** Research revealed that `_ingest_application_source` already fully implements the sync loop. Phase 36 only needs a polling task that drives it. Decision: separate asyncio task in `_server_lifespan`, not a new class and not a DotMDService method. Mirrors `indexer_task` pattern exactly.

---

## Unchanged Message Skip Strategy (Advisor Panel)

| Option | Description | Selected |
|--------|-------------|----------|
| chunk_source_provenance lookup | Query per-strategy provenance tables | |
| source_unit_fingerprints table | Dedicated unit-level table, strategy-agnostic | ✓ |
| Trust provider cursor | No local fingerprint comparison | |

**User's choice:** Delegated to advisor panel
**Notes:** Research confirmed `source_unit_fingerprints` table already exists and is already wired in `_ingest_application_source`. No new mechanism needed. Provider cursor replay on restart means cursor-trust alone is unsafe.

---

## Trickle Integration for Application Sources (Advisor Panel)

| Option | Description | Selected |
|--------|-------------|----------|
| Inside TrickleIndexer | Polling loop added to existing TrickleIndexer class | |
| Separate asyncio task, same lifespan | Independent task, shares shutdown_event | ✓ |
| External systemd timer | `dotmd telegram ingest` on a schedule outside container | |

**User's choice:** Delegated to advisor panel
**Notes:** `fcntl` exclusive lock in `_run_locked` makes external timer problematic (would silently fail to acquire lock while server is running). TrickleIndexer conflation mixes inotify semantics with cursor-poll semantics. Separate asyncio task is the clean path — scalable to future app sources.

---

## Claude's Discretion

- Whether polling task is a standalone class or plain coroutine — either acceptable
- Exact env var name for Telegram sync interval
- Whether `dotmd status` surfaces last-sync timestamp and result counts
- Whether `dotmd telegram ingest` CLI output shows `rebound_units` after it's added

## Deferred Ideas

- `dotmd telegram list-dialogs` — browse indexed dialogs (new capability, Phase 37+)
- Materialization on demand — deferred in Phase 34 (D-14), still deferred
- Per-dialog sync filtering — not in TG-01–TG-04 scope
- Full TTL-based soft-delete for Telegram messages — `soft-delete-with-ttl` todo remains dormant
