---
phase: 36-telegram-unified-sync-and-federated-search
reviewed: 2026-05-10T00:00:00Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/test_telegram_sync.py
  - backend/tests/api/test_phase34_gaps.py
  - backend/tests/api/test_telegram_federated_read.py
findings:
  critical: 2
  warning: 3
  info: 2
  total: 7
status: issues_found
---

# Phase 36: Code Review Report

**Reviewed:** 2026-05-10T00:00:00Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Phase 36 adds two concrete deliverables: `rebound_units` field to `ApplicationSourceIngestResult` (TG-03), and the `_run_telegram_poller` background coroutine wired into `_server_lifespan` (TG-01/TG-02). A third bundle of federated read tests (`test_telegram_federated_read.py`) is submitted in TDD RED phase. The config addition (`telegram_sync_interval_seconds`) and CLI output update are clean.

Two blockers were found: (1) the poller creates a **third** `SourceRuntimeBundle` for Telegram in `create_app()` when `DotMDService.__init__` already built one for the same namespace via `_build_federated_bundles()` — the two bundles target the same cursor store but have independent provider instances and are not coordinated; (2) the RED-phase tests in `test_telegram_federated_read.py` have no `@pytest.mark.xfail` and will fail CI unconditionally for every unimplemented path they cover.

Three warnings: `rebound_units` is counted per-message (per batch change), not per-document, so one re-activated dialog with N messages inflates the counter N-fold; `_source_runtime_factory` is accessed as a private attribute of `DotMDService` from `mcp_server.py` (cross-module coupling through an underscore name); and `hidden_units` is silently dropped from the `telegram_sync` log line.

---

## Critical Issues

### CR-01: `create_app()` builds a third Telegram bundle, bypassing the already-built federated bundle in `svc._lifecycle_bundles`

**File:** `backend/src/dotmd/mcp_server.py:545`

**Issue:** `_server_lifespan` calls `svc._source_runtime_factory.build_if_configured("telegram")` to get a bundle for the poller. `DotMDService.__init__` already calls `build_if_configured("telegram")` **twice**: once in `_build_telegram_provider()` (line 281 of service.py) and once in `_build_federated_bundles()` (line 302 of service.py, which iterates all registered namespaces including telegram). The poller therefore holds a **third** `SourceRuntimeBundle` with its own `TelegramApplicationSourceProvider` instance, distinct from the one stored in `svc._lifecycle_bundles["telegram"]` that the federated search fan-out uses.

While `UnixSocketTelegramSourceClient` is stateless per-request (no persistent socket held at init), the duplication creates two independently-observable provider identities: if either is replaced or patched in future code, divergence will occur silently. More importantly, `create_app()` bypasses the already-constructed federated bundle — there is no reason to rebuild it here. The poller should consume the bundle already built by service init, not create a new one.

**Fix:**
```python
# In create_app() / _server_lifespan, use the pre-built bundle from service:
telegram_bundle = svc._lifecycle_bundles.get("telegram")
if telegram_bundle is not None:
    telegram_task = asyncio.create_task(
        _run_telegram_poller(
            svc,
            telegram_bundle,
            settings.telegram_sync_interval_seconds,
            shutdown_event,
        )
    )
```
This eliminates the third build call, reuses the same provider instance the federated search sees, and removes the `svc._source_runtime_factory` private-attribute access from `mcp_server.py` entirely.

---

### CR-02: RED-phase tests in `test_telegram_federated_read.py` will break CI — no `xfail` markers on intentionally-failing tests

**File:** `backend/tests/api/test_telegram_federated_read.py:22`

**Issue:** The file is explicitly labelled "TDD RED" and each test body comments "# RED: This test fails because ... not implemented yet". However, none of the six tests has a `@pytest.mark.xfail` (or `@pytest.mark.skip`) decorator. Pytest will collect and run them. Those that exercise unimplemented behaviour (`service.read()` with federated routing, `service.drill()` for federated refs, `service._resolve_telegram_read_path`, etc.) will raise `AttributeError` or assertion failures and show up as **test failures** in CI output — not as expected-red tests. This creates false CI signal and violates the TDD convention used elsewhere in the codebase.

Affected tests: `test_federated_only_message_round_trip`, `test_federated_drill_returns_provider_metadata`, `test_federated_read_provider_down_attribution`, `test_truly_federated_telegram_ref_routes_to_provider`, `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider`, `test_active_locally_indexed_telegram_ref_uses_local_path`, `test_federated_read_helper_naming`.

**Fix:**
```python
import pytest

class TestFederatedTelegramRead:
    @pytest.mark.xfail(
        reason="TG-03/TG-04 Task 3: federated read routing not yet implemented",
        strict=True,
    )
    def test_federated_only_message_round_trip(self, tmp_path: Path) -> None:
        ...
```
Apply `@pytest.mark.xfail(strict=True)` to every test in the class (or mark the class). Use `strict=True` so that if the implementation lands and the test starts passing unexpectedly, CI also alerts.

---

## Warnings

### WR-01: `rebound_units` over-counts — increments once per change (message), not once per re-activated document

**File:** `backend/src/dotmd/ingestion/pipeline.py:584-594`

**Issue:** In `_ingest_application_source`, the second `for change in batch.changes:` loop (line 584) iterates every change in the batch and checks `get_resource_binding()` for each one. When a dialog (document) has N messages in the batch and its binding was previously inactive, `result.rebound_units` is incremented N times — once per message — not once per dialog. The counter name and its use in the CLI output (`rebound_units={result.rebound_units}`) implies a document-level count, not a message-level one. The semantic is misleading: a single dialog re-activation can show `rebound_units=50` if 50 messages are ingested.

**Fix:** Track seen document keys to count once per document:
```python
rebound_docs: set[tuple[str, str]] = set()
for change in batch.changes:
    self._metadata_store.upsert_source_document(change.document, conn=self._conn)
    doc_key = (change.document.namespace, change.document.document_ref)
    if doc_key not in rebound_docs:
        existing_binding = self._metadata_store.get_resource_binding(
            change.document.namespace,
            change.document.document_ref,
        )
        if existing_binding is not None and not existing_binding.active:
            result.rebound_units += 1
            rebound_docs.add(doc_key)
    self._metadata_store.upsert_resource_binding(...)
```

---

### WR-02: `mcp_server.py` accesses `svc._source_runtime_factory` — private attribute coupling

**File:** `backend/src/dotmd/mcp_server.py:545`

**Issue:** `create_app()` reaches into `DotMDService` via `svc._source_runtime_factory`, a name-mangled private attribute. `DotMDService` has no public property exposing the factory, and the AGENTS.md convention is to route all public APIs through `api/service.py`. If the attribute is renamed or the factory is inlined, `mcp_server.py` breaks silently (no type-check catches private attribute changes).

This issue is subsumed by the fix for CR-01 (using `svc._lifecycle_bundles.get("telegram")` instead), but if the approach changes, the coupling should still be resolved by adding a public property or method.

**Fix:** (covered by CR-01 fix above, or alternatively):
```python
# In DotMDService, expose a public method:
def get_lifecycle_bundle(self, namespace: str) -> SourceRuntimeBundle | None:
    return self._lifecycle_bundles.get(namespace)
```

---

### WR-03: `hidden_units` is excluded from the `telegram_sync` log line

**File:** `backend/src/dotmd/mcp_server.py:495-505`

**Issue:** The `telegram_sync` log message includes `discovered`, `new`, `changed`, `skipped`, `rebound`, `failed`, `reused` — but omits `hidden_units`. `hidden_units` is a meaningful counter: it tracks low-signal messages (one-word reactions, emoji) that are detected but not indexed. Operators monitoring the sync log will see a gap: `discovered=50 new=50 changed=0 skipped=0` with no indication that 40 of those 50 were filtered as low-signal. This makes the log misleading during debugging.

**Fix:**
```python
logger.info(
    "telegram_sync discovered=%d new=%d changed=%d skipped=%d "
    "hidden=%d rebound=%d failed=%d reused=%d",
    result.discovered,
    result.new_units,
    result.changed_units,
    result.skipped_units,
    result.hidden_units,   # add this
    result.rebound_units,
    result.failed_units,
    result.reused_units,
)
```

---

## Info

### IN-01: `test_tg04_public_ref_matches_search_native_ref` has a weak assertion on `search_native` candidates

**File:** `backend/tests/ingestion/test_telegram_provider.py:577-600`

**Issue:** The third assertion in this test (`if candidates:`) uses a conditional guard rather than asserting that `candidates` is non-empty. If `search_native` returns an empty list (e.g. due to a provider bug), the ref-consistency check silently passes without verifying anything. The test's stated purpose is to confirm all three ref formulas agree — that invariant isn't enforced when `candidates` is empty.

**Fix:**
```python
candidates = provider.search_native("test query", limit=5)
assert len(candidates) > 0, "search_native returned no candidates for default fixture"
search_ref = candidates[0].ref
assert search_ref.startswith("telegram:dialog:")
assert ":message:" in search_ref
assert unit_ref == expected_provenance_ref == search_ref
```

---

### IN-02: `telegram_ingest` CLI command documents Phase 29 caveat in production-facing help text

**File:** `backend/src/dotmd/cli.py:447`

**Issue:** The `--single-batch/--loop` option raises a `ClickException` with the message "Loop mode is not implemented in Phase 29". This internal phase number leaks into operator-visible CLI output. If a user runs `dotmd telegram ingest --loop`, they see "Phase 29" with no actionable meaning.

**Fix:**
```python
raise click.ClickException(
    "Loop mode is not supported for 'telegram ingest'; "
    "use the background MCP server (dotmd mcp) for continuous sync."
)
```

---

_Reviewed: 2026-05-10T00:00:00Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
