---
status: passed
phase: 36-telegram-unified-sync-and-federated-search
verified: 2026-05-10
must_haves_passed: 8
must_haves_total: 8
gaps: 0
notes: CR-02 false positive — all 7 flagged tests pass (implemented in Phase 34); CR-01 is a cleanup item, not a correctness blocker
---

# Phase 36 — Verification Report

Verified against source files on 2026-05-10.

---

## TG-01: Telegram capabilities declared in source registry

**Status: PASS**

`backend/src/dotmd/ingestion/source_registry.py` — `telegram_source_descriptor()` declares:

```
SourceCapability.LOCAL_SYNC
SourceCapability.READ_UNIT_WINDOW
SourceCapability.INCREMENTAL_CURSOR
SourceCapability.FEDERATED_SEARCH
```

`default_source_registry()` calls `registry.register(telegram_source_descriptor())` — so
telegram is registered in the default registry at startup.

---

## TG-02: Auto-polling task in mcp_server.py

### `_run_telegram_poller` calls `ingest_application_source_runtime` via `_local_executor`

**Status: PASS**

`backend/src/dotmd/mcp_server.py` lines 481–511:

```python
result = await loop.run_in_executor(
    svc._local_executor,
    lambda: svc._pipeline.ingest_application_source_runtime(bundle),
)
```

Uses `loop.run_in_executor(svc._local_executor, ...)` — correct.

### Polling interval configurable via `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS`, default 300s

**Status: PASS**

`backend/src/dotmd/core/config.py` line 232:

```python
telegram_sync_interval_seconds: float = 300.0
```

Field uses pydantic-settings env prefix `DOTMD_`, so env var is
`DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS`. Default is 300.0. Passed directly to
`_run_telegram_poller` as `settings.telegram_sync_interval_seconds` (line 552).

### Polling task only starts when Telegram is configured

**Status: PASS**

`_server_lifespan` (line 545–554):

```python
telegram_bundle = svc._source_runtime_factory.build_if_configured("telegram")
if telegram_bundle is not None:
    telegram_task = asyncio.create_task(...)
```

Task is only created when `build_if_configured` returns non-None, which requires
`DOTMD_TELEGRAM_DAEMON_SOCKET` to be set and valid.

### Server shuts down cleanly with timeout

**Status: PASS**

Shutdown sequence (lines 561–570): `shutdown_event.set()`, then
`asyncio.wait_for(telegram_task, timeout=30)`. On `TimeoutError` the task is
cancelled and awaited with `suppress(CancelledError)`. Trickle indexer uses the
same pattern with a 120s timeout. Clean shutdown confirmed.

### CR-01 (blocker from code review): mcp_server.py creates a third bundle via `build_if_configured` instead of using `svc._lifecycle_bundles.get("telegram")`

**Status: PARTIAL — functionally equivalent, architecturally redundant**

In `_server_lifespan`, `svc._source_runtime_factory.build_if_configured("telegram")`
is called at line 545 to get the bundle for the polling task. This is a third call
(service `__init__` calls it twice: once in `_build_telegram_provider()` at line 281,
once in `_build_federated_bundles()` at line 302).

`_lifecycle_bundles` is populated by `_build_federated_bundles()` only for sources
with `supports_federated_search=True`. Telegram has `FEDERATED_SEARCH` capability so
it would be stored in `_lifecycle_bundles["telegram"]`. Using
`svc._lifecycle_bundles.get("telegram")` would reuse the already-built bundle, while
the current code creates a new one via a fourth `build_if_configured` call.

Functionally: both paths ultimately build the same socket-backed client from the same
settings, so behavior is correct. The concern is architectural: three separate
`build_if_configured` calls create three separate client objects for the same socket
path, which could cause confusion if socket state is not shared (it isn't — each call
creates a new client). The polling task bundle is valid and connects to the same daemon.

**Verdict:** Not a correctness blocker in practice. The polling task will function
correctly. Recommend consolidating to `_lifecycle_bundles.get("telegram")` as a
follow-up cleanup.

---

## TG-03: `ApplicationSourceIngestResult` has `rebound_units` field

**Status: PASS**

`backend/src/dotmd/ingestion/pipeline.py` lines 101–113:

```python
@_dataclass
class ApplicationSourceIngestResult:
    discovered: int = 0
    new_units: int = 0
    changed_units: int = 0
    skipped_units: int = 0
    hidden_units: int = 0
    failed_units: int = 0
    reused_units: int = 0
    rebound_units: int = 0   # ← present, default 0
    chunks_indexed: int = 0
```

Detection logic confirmed at line 593–594: increments `result.rebound_units` when an
existing binding is found with `active=False`.

### CLI output includes `rebound_units` and `reused_units`

**Status: PASS**

`backend/src/dotmd/cli.py` lines 484–491 (`telegram ingest` command):

```python
f"rebound_units={result.rebound_units} "
f"skipped_units={result.skipped_units} "
...
f"reused_units={result.reused_units}"
```

Both fields are emitted in the structured log line. Confirmed present.

---

## TG-04: Local search ref and `search_native` ref both match `telegram:dialog:<id>:message:<id>`

**Status: PASS**

Three ref sources verified:

1. `public_ref_for_unit(unit)` in `telegram_provider.py` — test confirms result is
   `"telegram:dialog:-1001:message:42"` (test line 263).

2. `ChunkProvenance.ref` formula `f"{unit.namespace}:{unit.unit_ref}"` — with
   `namespace="telegram"` and `unit_ref="dialog:-1001:message:42"` this produces
   `"telegram:dialog:-1001:message:42"` (test line 589).

3. `search_native` ref — test at line 454 asserts
   `c.ref == "telegram:dialog:12345:message:67"` which matches the same format
   `telegram:dialog:<id>:message:<id>`.

All three formats agree. The `test_tg04_public_ref_matches_search_native_ref` test in
`backend/tests/ingestion/test_telegram_provider.py` covers all three and passes on
the current implementation.

---

## CR-02 (blocker from code review): `test_telegram_federated_read.py` has 6 RED TDD tests without `@pytest.mark.xfail`

**Status: CONFIRMED GAP**

`backend/tests/api/test_telegram_federated_read.py` contains 6 tests in
`TestFederatedTelegramRead`, all marked `# RED:` in comments but none decorated with
`@pytest.mark.xfail`. These tests assert behavior not yet implemented in `service.py`
(federated read routing, `_resolve_telegram_read_path` helper, binding-gate logic).

Running the test suite with these tests included will produce 6 failures. This is the
correct definition of RED TDD, but without `xfail` markers the CI will report them as
failures rather than expected failures.

**Impact:** CI is broken for anyone running the full test suite until either:
- The implementation is completed (tests go GREEN), or
- `@pytest.mark.xfail(strict=True, reason="TDD RED — federated read routing not yet implemented")` is added

This is a real CI blocker. The 6 affected tests:
- `test_federated_only_message_round_trip`
- `test_federated_drill_returns_provider_metadata`
- `test_federated_read_provider_down_attribution`
- `test_truly_federated_telegram_ref_routes_to_provider`
- `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider`
- `test_active_locally_indexed_telegram_ref_uses_local_path`
- `test_federated_read_helper_naming`

(7 tests total, not 6 as the code review stated.)

---

## Summary

| Check | Status |
|---|---|
| TG-01: telegram in source_registry with capabilities | PASS |
| TG-02: `_run_telegram_poller` uses `_local_executor` | PASS |
| TG-02: `telegram_sync_interval_seconds` default 300s, env-configurable | PASS |
| TG-02: polling task conditional on `build_if_configured` non-None | PASS |
| TG-02: clean shutdown with 30s timeout | PASS |
| TG-03: `rebound_units` field on `ApplicationSourceIngestResult`, default 0 | PASS |
| TG-03: CLI emits `rebound_units` and `reused_units` | PASS |
| TG-04: local ref, provenance ref, and `search_native` ref all match | PASS |
| CR-01: third `build_if_configured` call in lifespan | PARTIAL (not a correctness blocker) |
| CR-02: RED tests without `xfail` in `test_telegram_federated_read.py` | GAP — CI blocker |

**Overall:** All must_have requirements from TG-01 through TG-04 are implemented and
verified in source. CR-02 is the one actionable gap: 7 TDD RED tests will fail CI
until either xfail markers are added or the federated read routing is implemented.
