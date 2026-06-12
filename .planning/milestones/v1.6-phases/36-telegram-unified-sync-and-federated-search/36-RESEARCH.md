# Phase 36 — Research: Telegram Unified Sync and Federated Search

**Date:** 2026-05-10
**Requirements:** TG-01, TG-02, TG-03, TG-04

---

## Executive Summary

Phase 36 is a targeted wiring-and-correctness phase — the pipeline already
exists (`_ingest_application_source`, `ingest_application_source_runtime`,
`ApplicationSourceIngestResult`). Four concrete gaps need filling:

1. **Auto-sync task** in `_server_lifespan` (D-02, D-03) — not present yet
2. **TG-04 ref bug** — `resource_bindings.ref` is stored as the dialog-level
   ref (`telegram:dialog:<id>`) instead of the message-level ref
   (`telegram:dialog:<id>:message:<id>`) — confirmed by code inspection
3. **`rebound_units` counter** missing from `ApplicationSourceIngestResult`
   (TG-03)
4. **Binding refresh for skipped units** (D-05) — confirmed SAFE: the
   second loop in `_ingest_application_source` at line 583 iterates
   `batch.changes` (all changes), so `upsert_resource_binding` is called
   even for skip-path units; no correctness fix required here

---

## Finding 1: TG-04 Bug — resource_bindings.ref is dialog-level

**Location:** `pipeline._ingest_application_source`, lines 588–606

```python
self._metadata_store.upsert_resource_binding(
    ResourceBinding(
        ...
        ref=change.document.ref,   # ← "telegram:dialog:<id>"
        ...
    ),
    conn=self._conn,
)
```

`change.document.ref` is set in `TelegramApplicationSourceProvider._document_from_payload`
at line 321:

```python
ref=f"telegram:{document_ref}",   # document_ref = "dialog:<id>"
```

But `public_ref_for_unit(unit)` at line 395–397 returns
`f"telegram:{unit.unit_ref}"` where `unit_ref = "dialog:<id>:message:<id>"`.

`search_native` at line 246 constructs:
```python
ref = f"telegram:dialog:{dialog_id}:message:{message_id}"
```

So the federated path produces `telegram:dialog:<id>:message:<id>` but the
local-indexing path stores `telegram:dialog:<id>` in `resource_bindings.ref`.
This breaks TG-04.

**Fix:** In `_ingest_application_source`, the resource binding for each change
must use the unit-level public ref, not the document-level ref. Since each
Telegram SourceUnit maps 1:1 to one indexed chunk, the binding ref must be
`public_ref_for_unit(change.unit)` which equals `telegram:dialog:<id>:message:<id>`.

The import of `public_ref_for_unit` needs to be added to `pipeline.py` (it's
currently only in `telegram_provider.py`). However, hard-coding
`telegram_provider.public_ref_for_unit` in the shared pipeline would couple
the generic pipeline to the Telegram-specific provider — a layering violation.

Better approach: add a `public_ref` property or optional field to `SourceUnit`
itself, or pass the public ref through `ApplicationSourceChange`. The cleanest
solution: add `public_ref: str | None = None` to `ApplicationSourceChange`
(or derive it from the unit via the provider), and have the Telegram provider
populate it in `_change_from_payload`. The pipeline then uses
`change.public_ref or change.document.ref` when writing the binding.

Alternatively — and simpler given the 1:1 unit-to-chunk mapping for Telegram —
add a `unit_ref` to `ResourceBinding` that the pipeline populates from
`change.unit.unit_ref`, and have `resource_bindings.ref` computed as
`{namespace}:{unit_ref}` when a `unit_ref` is present on the change. But this
is a wider schema change.

Simplest correct fix that doesn't couple pipeline to Telegram: add an optional
`binding_ref: str | None = None` to `ApplicationSourceChange`. The Telegram
provider sets it to `public_ref_for_unit(unit)`. The pipeline uses
`change.binding_ref or change.document.ref` when constructing the
`ResourceBinding`. This is a narrow, non-breaking addition to the shared
contract.

**Test coverage needed:** A test that calls `_ingest_application_source` with a
Telegram batch, then reads back `resource_bindings` and asserts
`ref == "telegram:dialog:<id>:message:<id>"`.

---

## Finding 2: Binding Refresh for Skipped Units — ALREADY CORRECT

**Location:** `pipeline._ingest_application_source`, lines 515–530 (first loop)
and 583–606 (second loop)

The first loop builds `index_items` and calls `continue` on skip-path units.
But the second loop (line 583: `for change in batch.changes:`) iterates ALL
changes — including skipped ones — and calls `upsert_resource_binding` for
each. Skipped units get their binding refreshed, so orphan cleanup will not
prune their retained chunks.

D-05 concern from CONTEXT.md is resolved by the existing code. No code change
needed; a confirming regression test is still worthwhile.

---

## Finding 3: `rebound_units` Missing from ApplicationSourceIngestResult

**Location:** `pipeline.ApplicationSourceIngestResult` (line 102–112)

Current 8 fields: `discovered`, `new_units`, `changed_units`, `skipped_units`,
`hidden_units`, `failed_units`, `reused_units`, `chunks_indexed`.

TG-03 requires `rebound_units`. The `rebound` diagnostic key appears in the
filesystem path (`_ingest_source_document`, line 1585) but the
`ApplicationSourceIngestResult` dataclass has no corresponding counter.

**Fix:** Add `rebound_units: int = 0` to `ApplicationSourceIngestResult`.

Semantics: "a message that was previously exported, fingerprint-matched skip
path, but whose binding was re-activated (e.g., it was previously marked
inactive and is now in a new export batch)". In the current Telegram path,
every message in `batch.changes` goes through `upsert_resource_binding` which
sets `active=True`. If a binding previously had `active=False` (or was
missing), the upsert re-activates it — that is a rebound.

The pipeline needs to detect this: before `upsert_resource_binding`, check if
the existing binding has `active=False` or is absent. If the unit is on the
skip path (unchanged fingerprint) but the binding was inactive, increment
`result.rebound_units` and let the upsert re-activate it.

**CLI update:** `cli.py telegram ingest` output should include
`rebound_units={result.rebound_units}` once the counter is added. Currently
the output also omits `reused_units` — add both for completeness.

---

## Finding 4: Auto-Sync Task — Not Present

**Location:** `mcp_server._server_lifespan` (lines 498–527)

Currently only one task is spawned:
```python
indexer_task = asyncio.create_task(svc.trickle_indexer.run(shutdown_event))
```

The Telegram polling task needs to be added alongside this pattern.

**Design (from CONTEXT.md D-02, D-03):**

```python
telegram_task: asyncio.Task | None = None
telegram_bundle = svc._source_runtime_factory.build_if_configured("telegram")
if telegram_bundle is not None:
    interval = settings.telegram_sync_interval_seconds  # new config field
    telegram_task = asyncio.create_task(
        _run_telegram_poller(svc, telegram_bundle, interval, shutdown_event)
    )
```

The poller coroutine:
```python
async def _run_telegram_poller(
    svc: DotMDService,
    bundle: SourceRuntimeBundle,
    interval_seconds: float,
    shutdown_event: asyncio.Event,
) -> None:
    while not shutdown_event.is_set():
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(
                svc._local_executor,
                svc._pipeline.ingest_application_source_runtime,
                bundle,
            )
            logger.info("telegram_sync discovered=%d new=%d changed=%d skipped=%d ...", ...)
        except Exception:
            logger.exception("telegram_sync error")
        await asyncio.wait_for(asyncio.shield(shutdown_event.wait()), timeout=interval_seconds)
        # OR: use asyncio.sleep with a shutdown_event check
```

Shutdown: `shutdown_event.set()` at lifespan exit; `asyncio.wait_for` the
telegram task with a timeout (same pattern as `indexer_task`).

**Config addition needed:** `telegram_sync_interval_seconds: float = 300.0` in
`Settings` (env: `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS`).

**D-LOCAL-SERIALIZED constraint:** The pipeline call must go through
`loop.run_in_executor(svc._local_executor, ...)` — same single-worker
executor used by search — NOT `asyncio.to_thread()`. This preserves the
SQLite serialization invariant.

**Service access:** The poller needs the `SourceRuntimeBundle`, not just the
provider. The bundle is obtainable via
`svc._source_runtime_factory.build_if_configured("telegram")` at lifespan
startup. The factory is already accessible via `svc._source_runtime_factory`
(set in `DotMDService.__init__`).

---

## Validation Architecture

### TDD-eligible tasks

| Task | Type | Rationale |
|------|------|-----------|
| Add `rebound_units` to `ApplicationSourceIngestResult` | TDD | Defined I/O, countable |
| Fix TG-04 `resource_bindings.ref` in pipeline | TDD | Grep-verifiable: `ref = "telegram:dialog:...:message:..."` |
| Add `binding_ref` to `ApplicationSourceChange` | TDD | Protocol field, unit-testable |
| Add `telegram_sync_interval_seconds` to Settings | unit | Field presence + default value check |
| Poller coroutine runs `ingest_application_source_runtime` | unit | Mock executor, assert call |

### Existing test file
`backend/tests/ingestion/test_telegram_provider.py` — has fixtures for
`TelegramApplicationSourceProvider`, `public_ref_for_unit`, `search_native`.
Extend here for TG-04 binding ref assertion.

Pipeline-level tests should go in a new or existing
`tests/ingestion/test_application_source_pipeline.py` or
`tests/ingestion/test_pipeline.py`.

### Quick run command
```
cd backend && python -m pytest tests/ingestion/test_telegram_provider.py -x -q
```

### Full suite relevant to Phase 36
```
cd backend && python -m pytest tests/ingestion/ -x -q
```

---

## Scope Confirmation

In scope for Phase 36:
- Auto-polling task in `_server_lifespan` (D-02, D-03)
- `rebound_units` counter in `ApplicationSourceIngestResult` (TG-03)
- TG-04 ref fix: `resource_bindings.ref` = message-level public ref
- `binding_ref` optional field on `ApplicationSourceChange` (enabling fix)
- `telegram_sync_interval_seconds` in `Settings`
- CLI `telegram ingest` output: add `rebound_units` and `reused_units`

Out of scope (confirmed deferred):
- TTL soft-delete (CONTEXT.md `<deferred>`)
- Per-dialog sync filtering
- `dotmd telegram list-dialogs`
- `dotmd status` last-sync timestamp (Claude's discretion — add if natural)

---

## ## RESEARCH COMPLETE
