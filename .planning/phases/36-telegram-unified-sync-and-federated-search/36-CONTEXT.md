# Phase 36: Telegram unified sync and federated search - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Wire Telegram's existing incremental sync contract into the server lifecycle
so sync runs automatically in the background, verify TG-04 ref consistency
between local-index results and federated search results, and fill the
remaining gaps in sync reporting.

**The core sync pipeline already exists.** `pipeline._ingest_application_source`
(cursor-read → fingerprint-skip → embed → FTS5 → graph → commit),
`ingest_application_source_runtime`, `ApplicationSourceIngestResult` with 7
counters, and `dotmd telegram ingest` CLI are all shipped. Phase 36 is NOT
building a sync pipeline from scratch.

Concretely, this phase delivers:
1. Auto-polling task in server lifespan that periodically calls
   `ingest_application_source_runtime` for Telegram (user decision: auto in background).
2. TG-04 ref consistency: after local indexing, `resource_binding.ref` for
   each Telegram chunk = `telegram:dialog:<id>:message:<id>` (message-level),
   matching what `search_native` already returns.
3. Binding refresh for unchanged messages so orphan cleanup does not prune
   retained Telegram chunks on unchanged-fingerprint runs.
4. `rebound_units` counter added to `ApplicationSourceIngestResult` (TG-03 gap).

This phase is NOT a new search engine, NOT a new chunking architecture, NOT
a `dotmd telegram` CLI redesign, and NOT Airweave connector work (Phase 37).

</domain>

<decisions>
## Implementation Decisions

### Chunk Granularity

- **D-01:** One `SourceUnit` (Telegram message) = one indexed chunk. Messages
  are already atomic units — no markdown-style chunker needed. The low-signal
  filter (`is_low_signal_telegram_text`) already suppresses "ok"/"да"/emoji-only
  messages from standalone search before they reach embedding. The `text_hash`
  embedding reuse mechanism handles identical-text dedup across sync runs.

### Auto-Sync Trigger

- **D-02:** Telegram auto-sync runs as a **separate asyncio task** in
  `_server_lifespan` (`mcp_server.py`), not inside `TrickleIndexer`. The
  pattern mirrors the existing `indexer_task`: `asyncio.create_task` +
  `shutdown_event` + `asyncio.wait_for` at lifespan exit.
  
  Rationale: TrickleIndexer is inotify-driven (filesystem events); Telegram
  needs cursor-based polling. Conflating them in one class mixes two scheduling
  models and would force `poll_interval_seconds` semantics onto Telegram. The
  separate task approach is directly extensible to future application sources
  (each gets its own poller task sharing the same `shutdown_event` and pipeline).

- **D-03:** Polling interval configurable via a new env var
  (`DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS`, default 300 — 5 minutes). Separate
  from `poll_interval_seconds` which is tuned for filesystem backlog recovery.

### Fingerprint Skip

- **D-04:** Unchanged message detection uses the existing
  `source_unit_fingerprints` table (`get_source_unit_fingerprint` /
  `upsert_source_unit_fingerprint`). Already wired in `_ingest_application_source`
  — no new mechanism. The skip path increments `result.skipped_units`.

### Binding Refresh for Unchanged Messages

- **D-05:** When a unit's fingerprint matches (skip path), the pipeline MUST
  still refresh `resource_bindings` to prevent orphan cleanup from pruning
  retained Telegram chunks. Planner: verify the current skip path handles this
  or add a lightweight `touch_binding` call. If the skip path does nothing to
  bindings today, this is a correctness bug to fix in this phase.

### TG-04 Ref Consistency

- **D-06:** After local indexing, each Telegram chunk's `resource_binding.ref`
  must equal `telegram:dialog:<id>:message:<id>` (message-level public ref),
  matching what `search_native` and the federated search path return. The
  `public_ref_for_unit(unit)` function already computes this ref — planner must
  verify it flows through to `resource_bindings.ref` in the `_ingest_application_source`
  write path. Add a regression test if not already covered.

### Sync Reporting (TG-03)

- **D-07:** Add `rebound_units: int = 0` to `ApplicationSourceIngestResult`.
  "Rebound" = a message that was previously inactive/retained and is re-activated
  by a new export batch. Planner to confirm whether `_ingest_application_source`
  already detects this case or whether it needs new logic.

### Claude's Discretion

- Whether the polling task is a standalone class (`ApplicationSourcePoller`)
  or a plain coroutine function — either is fine as long as it follows the
  `indexer_task` lifecycle pattern.
- Exact name of the new env var for the Telegram sync interval — any clear,
  consistent name is fine.
- Whether `dotmd status` should surface last-sync timestamp and result counts
  for Telegram — planner should add this if it fits naturally.
- Whether `dotmd telegram ingest` CLI output should display `rebound_units`
  once the counter is added.

### Reviewed Todos (not folded)

- `background-trickle-indexer.md` — not folded; trickle is unchanged; this
  phase adds a separate polling task, not changes to trickle's event model.
- `soft-delete-with-ttl-for-removed-source-files.md` — not folded; Telegram
  orphan prevention (D-05) handles inactivity, not TTL-based soft-delete.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Definition

- `.planning/ROADMAP.md` — Phase 36 goal, requirements TG-01–TG-04, success
  criteria (capability declaration, incremental skip/reuse, sync reporting,
  same API shape for local vs. federated results).
- `.planning/REQUIREMENTS.md` — TG-01 through TG-04 v1.6 Telegram
  requirements. Read exact requirement text before planning.
- `.planning/STATE.md` — current workflow state and milestone progress.

### Prior Architecture Decisions

- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
  — D-12 (checkpoint commits only after local persistence), D-13 (filesystem
  does not own cursor commits), D-15 (Telegram remains delegated to
  mcp-telegram; dotMD must not become a direct Telegram API client).
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
  — D-16 (Telegram ref = `telegram:dialog:<id>:message:<id>`, round-trips
  through `read(ref)`), D-17 (all Telegram access through lifecycle bundle),
  D-13 (`can_read: True` when provider exposes `read_unit_window`).
- `.planning/phases/35-filesystem-unified-source-adapter/35-CONTEXT.md`
  — D-03 (Telegram has no `FileInfo`; `SourceAdapterProtocol` stays minimal).

### Current Code Surfaces

- `backend/src/dotmd/ingestion/pipeline.py` — `_ingest_application_source`
  (core sync loop, lines ~457–620), `ingest_application_source_runtime` (Phase 36
  primary entry point), `ApplicationSourceIngestResult` (7 existing counters),
  `source_unit_fingerprints` table usage (fingerprint skip, lines ~516–530).
- `backend/src/dotmd/ingestion/telegram_provider.py` —
  `TelegramApplicationSourceProvider`, `search_native`, `export_changes`,
  `public_ref_for_unit`, `is_low_signal_telegram_text`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` — `SourceRuntimeFactory.build("telegram")`,
  `SourceRuntimeBundle`, `TelegramSourceConfig`, `SQLiteSourceCursorStore`.
- `backend/src/dotmd/ingestion/source_registry.py` — `telegram_source_descriptor()`
  (already declares `LOCAL_SYNC`, `READ_UNIT_WINDOW`, `INCREMENTAL_CURSOR`,
  `FEDERATED_SEARCH` — TG-01 already satisfied).
- `backend/src/dotmd/mcp_server.py` — `_server_lifespan`, `indexer_task`
  (exact pattern to follow for the new Telegram polling task).
- `backend/src/dotmd/cli.py` — `telegram` command group, `telegram ingest`,
  `telegram reset-index` (already exist; Phase 36 may add output enhancements).
- `backend/src/dotmd/core/models.py` — `ApplicationSourceIngestResult` (add
  `rebound_units`), `SourceCapability` enum.
- `backend/tests/ingestion/test_telegram_provider.py` — existing federated
  search tests; extend for TG-04 local ref consistency.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `pipeline.ingest_application_source_runtime(bundle, limit=500)` — full
  cursor-read → fingerprint-skip → embed → FTS5 → graph → cursor-commit
  cycle. Phase 36 polling task calls this, does not reimplement it.
- `indexer_task` in `mcp_server._server_lifespan` — exact async task lifecycle
  pattern (create_task, shutdown_event, wait_for at exit). Copy this for the
  Telegram poller.
- `source_unit_fingerprints` table — already handles unit-level dedup across
  cursor replays. Strategy-agnostic; survives restart.
- `public_ref_for_unit(unit: SourceUnit) -> str` in `telegram_provider.py` —
  returns `telegram:dialog:<id>:message:<id>`. Must flow through to
  `resource_bindings.ref` for TG-04 to hold.
- `is_low_signal_telegram_text(text)` — already filters short/emoji-only
  messages before embedding. One-message-one-chunk decision is safe because
  of this pre-filter.
- `ApplicationSourceIngestResult` with 7 counters — add `rebound_units` to
  complete TG-03 coverage.

### Established Patterns

- **Cursor semantics**: `checkpoint_cursor` is durable (commit after local
  write succeeds); `next_cursor` is continuation hint only. Phase 28 rule.
- **Lifecycle boundary**: All Telegram construction goes through
  `SourceRuntimeFactory.build_if_configured("telegram")` or `build("telegram")`.
  No direct `TelegramApplicationSourceProvider()` outside lifecycle.
- **D-LOCAL-SERIALIZED**: All SQLite writes (including Telegram chunk indexing)
  run on the single-worker `_local_executor`. Do not introduce concurrent
  SQLite writes from the polling task.
- **No fail-fast**: Polling task errors are logged and reported as
  `SourceStatus(status="error")`; they do not crash the server.

### Integration Points

- `_server_lifespan` in `mcp_server.py` — add the Telegram polling
  `asyncio.create_task` alongside the existing `indexer_task`.
- `DotMDService.__init__` — already calls `_build_telegram_provider()` and
  `_build_federated_bundles()`; the polling task uses the existing lifecycle
  bundle, not a new construction path.
- `ApplicationSourceIngestResult` — add `rebound_units`; update `cli.py`
  output and test fixtures.

### Anti-Patterns To Avoid

- Do not add Telegram polling inside `TrickleIndexer` — different scheduling
  model (cursor poll vs. inotify), class concern creep.
- Do not call `asyncio.to_thread()` for the pipeline write path — use
  `loop.run_in_executor(self._local_executor, ...)` to preserve
  D-LOCAL-SERIALIZED.
- Do not use `next_cursor` for durable checkpoint state — only
  `checkpoint_cursor` is safe after crash/restart.
- Do not rebuild `TelegramApplicationSourceProvider` inside the polling task —
  reuse the lifecycle bundle built at service init.

</code_context>

<specifics>
## Specific Ideas

- Keep the Telegram poller simple: a plain `while not shutdown_event.is_set()`
  loop with `await asyncio.sleep(interval)` between ticks, calling
  `run_in_executor(_local_executor, pipeline.ingest_application_source_runtime, bundle)`.
- The polling task and `indexer_task` both share `shutdown_event` — clean
  shutdown should wait for both tasks.
- Sync reporting in `dotmd status` output (alongside trickle state) would be
  a clean operator signal: last sync time, last result counts (new/skipped/failed).

</specifics>

<deferred>
## Deferred Ideas

- **`dotmd telegram list-dialogs`** — CLI for browsing indexed dialogs.
  New capability, Phase 37+ territory.
- **Materialization on demand** — D-14 from Phase 34: `can_materialize: False`
  for now; deferred past Phase 36.
- **Per-dialog sync filtering** — allow syncing only specific dialog IDs.
  New capability, not in TG-01–TG-04 scope.
- **Full TTL-based soft-delete for Telegram messages** — separate from the
  binding refresh (D-05). The `soft-delete-with-ttl` todo remains dormant.

</deferred>

---

*Phase: 36-telegram-unified-sync-and-federated-search*
*Context gathered: 2026-05-10*
