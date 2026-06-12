# SECURITY.md — Phase 36: Telegram Unified Sync and Federated Search

**Audit date:** 2026-05-10
**ASVS Level:** 1
**Mode:** retroactive-STRIDE (no plan-time threat model)
**block_on:** critical
**Deployment context:** Single-user localhost Docker container. No external-facing endpoints added by this phase.

---

## Phase 36 Attack Surface

Phase 36 added the following new code paths:

| Component | Description |
|-----------|-------------|
| `ApplicationSourceIngestResult.rebound_units` | New `int = 0` counter field on result dataclass |
| Rebound detection in `_ingest_application_source` | Calls `get_resource_binding` before `upsert_resource_binding`; increments counter if binding was inactive |
| `Settings.telegram_sync_interval_seconds` | New `float = 300.0` config field, env-mapped to `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS` |
| `_run_telegram_poller` coroutine | Background asyncio task; calls `ingest_application_source_runtime` via `loop.run_in_executor(_local_executor, ...)` |
| `_server_lifespan` wiring | Conditional task creation (`build_if_configured("telegram")`); 30s shutdown with `wait_for` + cancel + `suppress(CancelledError)` |

No new network endpoints, auth paths, file access patterns, or schema changes were introduced.

---

## Retroactive STRIDE Register

### TH-36-01 — Tampering / DoS: Unclamped polling interval allows tight busy-loop

| Field | Value |
|-------|-------|
| **Category** | Tampering / Denial of Service |
| **Disposition** | accept |
| **STRIDE** | T, D |
| **Attack** | Operator sets `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS=0` or a negative value. `asyncio.wait_for(shutdown_event.wait(), timeout=0)` raises `TimeoutError` immediately on every iteration, producing a tight busy-loop that saturates the event loop and `_local_executor` thread pool. |
| **Where** | `mcp_server.py:509` (`await asyncio.wait_for(shutdown_event.wait(), timeout=interval_seconds)`), `config.py:232` (no lower-bound validator) |
| **Verification** | `grep -n "gt.*0\|Field.*telegram_sync\|validator.*telegram_sync" config.py` — no match. Field is bare `float = 300.0`. |
| **Severity** | LOW — operator-only attack surface (env var requires system access). No remote exploit path. Single-user localhost deployment. |
| **Accepted risk rationale** | Requires operator-level access to the Docker env to exploit. Default value (300.0) is safe. A misconfigured interval is observable immediately from CPU metrics and logs. The fix (add `Field(gt=0)` or a `@field_validator`) is low-risk but deferred as non-critical in a single-user deployment. Document here so it is not forgotten. |

### TH-36-02 — Information Disclosure: Telegram credentials in env

| Field | Value |
|-------|-------|
| **Category** | Information Disclosure |
| **Disposition** | accept |
| **STRIDE** | I |
| **Attack** | Telegram daemon socket path and any associated credentials are loaded from environment variables (`DOTMD_TELEGRAM_DAEMON_SOCKET`). If the container's env is leaked (e.g., via `docker inspect` by a local user), socket path is exposed. |
| **Where** | `config.py` — `telegram_daemon_socket: Path | None = None` (pre-existing, not new in Phase 36) |
| **Severity** | LOW — pre-existing, not introduced by Phase 36. Socket path is not a credential; daemon socket is on the server-local filesystem. |
| **Accepted risk rationale** | Pre-existing surface. Phase 36 does not add new credential fields. Operator controls secret storage via `~/.secrets/`. Accepted as-is; same posture as all other dotMD daemon connections. |

### TH-36-03 — DoS: Exception in poller coroutine swallowed without backoff

| Field | Value |
|-------|-------|
| **Category** | Denial of Service (amplification) |
| **Disposition** | accept |
| **STRIDE** | D |
| **Attack** | If `ingest_application_source_runtime` raises persistently (e.g., Telegram daemon is down), the poller logs an ERROR and immediately retries after `interval_seconds`. At the default 300s interval this is benign, but at a short interval it could amplify errors. |
| **Where** | `mcp_server.py:506-511` — `except Exception: logger.exception(...)` with no backoff or failure counter |
| **Severity** | LOW — self-throttled by `interval_seconds`. At default 300s, 12 calls/hour maximum. |
| **Accepted risk rationale** | The retry-on-error behavior is intentional (keep trying when Telegram daemon recovers). Error amplification is bounded by the configured interval. No exponential backoff is warranted at ASVS L1 / single-user deployment. |

### TH-36-04 — Tampering: Rebound counter uses dialog-level key, not unit-level

| Field | Value |
|-------|-------|
| **Category** | Tampering (incorrect counter) |
| **Disposition** | accept |
| **STRIDE** | T |
| **Attack** | `get_resource_binding` is called with `change.document.document_ref` (dialog-level). If multiple units in one dialog were rebounded, the counter increments once per dialog change, not per unit. The counter may undercount rebound events. |
| **Where** | `pipeline.py:589-594` |
| **Severity** | INFORMATIONAL — `rebound_units` is a reporting counter only; no security control depends on its value. Plan 01 explicitly documented this design choice. |
| **Accepted risk rationale** | Counter semantics match the upsert key used for bindings. Undercounting is a known design trade-off, not a security control bypass. Logged here for completeness. |

---

## Threat Verification Table

| Threat ID | Category | Disposition | Status | Evidence / Notes |
|-----------|----------|-------------|--------|-----------------|
| TH-36-01 | T/D — unclamped interval | accept | CLOSED (accepted) | No `Field(gt=0)` validator found. Accepted: operator-only surface, default safe. |
| TH-36-02 | I — env credential exposure | accept | CLOSED (accepted) | Pre-existing surface. Phase 36 adds no new credential fields. |
| TH-36-03 | D — no backoff on error | accept | CLOSED (accepted) | Self-throttled by interval. Intentional design for daemon recovery. |
| TH-36-04 | T — dialog-level rebound key | accept | CLOSED (accepted) | Counter only, no security control. Documented design decision. |

**Closed: 4/4 | Open: 0/4**

---

## D-LOCAL-SERIALIZED Verification (Plan 02 design constraint)

> Constraint: pipeline write path must use `loop.run_in_executor(_local_executor, ...)`, never `asyncio.to_thread`.

**Verified CLOSED.**

- `mcp_server.py:491-493`: `_run_telegram_poller` uses `loop.run_in_executor(svc._local_executor, lambda: svc._pipeline.ingest_application_source_runtime(bundle))`.
- All `asyncio.to_thread` calls in `mcp_server.py` are for read-only operations (`service.read`, `service.drill`, `fb.submit`, `svc.warmup`) — none are in the Telegram write path.

---

## Unregistered Threat Flags

Both SUMMARY.md files (`36-01-SUMMARY.md`, `36-02-SUMMARY.md`) report **"Threat Flags: None"** for their respective plans. No new threat flags were raised by the executor during implementation.

No unregistered flags to log.

---

## Shutdown Safety Verification

| Check | Evidence | Status |
|-------|----------|--------|
| Conditional task creation | `mcp_server.py:544-554`: `telegram_task` only created when `build_if_configured("telegram")` returns non-None | CLOSED |
| 30s shutdown timeout | `mcp_server.py:564`: `await asyncio.wait_for(telegram_task, timeout=30)` | CLOSED |
| Cancel on timeout | `mcp_server.py:567-569`: `telegram_task.cancel()` + `with suppress(asyncio.CancelledError): await telegram_task` | CLOSED |
| Telegram shutdown before trickle | `mcp_server.py:562-580`: telegram_task shutdown block precedes `indexer_task` wait block | CLOSED |

---

## Accepted Risks Log

| Risk ID | Description | Severity | Rationale |
|---------|-------------|----------|-----------|
| TH-36-01 | `telegram_sync_interval_seconds` has no lower-bound validator; zero/negative value causes tight busy-loop | LOW | Operator-only surface; default 300.0 is safe; observable via CPU metrics |
| TH-36-02 | Telegram daemon socket path in env vars | LOW | Pre-existing; operator controls secret storage; socket is not a credential |
| TH-36-03 | Poller retries immediately after exception with no backoff | LOW | Bounded by interval; intentional for daemon recovery |
| TH-36-04 | `rebound_units` counter uses dialog-level key (may undercount) | INFO | Reporting counter only; no security control depends on it |
