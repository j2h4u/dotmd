---
phase: 36
slug: telegram-unified-sync-and-federated-search
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-10
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/ingestion/test_telegram_provider.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ingestion/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/ingestion/test_telegram_provider.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ingestion/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| 36-01-01 | 01 | 1 | TG-03 | TDD | `cd backend && python -m pytest tests/ingestion/ -k "rebound" -x -q` | ⬜ pending |
| 36-01-02 | 01 | 1 | TG-04 | TDD | `cd backend && python -m pytest tests/ingestion/ -k "binding_ref or resource_binding" -x -q` | ⬜ pending |
| 36-01-03 | 01 | 1 | TG-04 | TDD | `cd backend && python -m pytest tests/ingestion/test_telegram_provider.py -x -q` | ⬜ pending |
| 36-02-01 | 02 | 2 | TG-02 | unit | `cd backend && python -m pytest tests/ingestion/ -x -q` | ⬜ pending |
| 36-02-02 | 02 | 2 | TG-01, TG-02 | unit | `cd backend && python -m pytest tests/ -k "telegram_poller or telegram_sync" -x -q` | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/ingestion/test_telegram_provider.py` — extend with TG-04 binding ref tests and `rebound_units` counter tests
- [ ] `backend/tests/ingestion/test_telegram_sync.py` — new file for polling task and config tests

*Existing infrastructure (pytest, conftest.py) covers all phase requirements — no framework installs needed.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Polling task starts when `DOTMD_TELEGRAM_DAEMON_SOCKET` is set at server startup | TG-01 | Requires live container + mcp-telegram daemon | Check logs for `telegram_sync` entries 5 min after server start |
| Auto-sync runs every `DOTMD_TELEGRAM_SYNC_INTERVAL_SECONDS` seconds | TG-02 | Requires live container timing | Set interval to 30s, watch logs for repeated `telegram_sync discovered=` entries |
| Server shuts down cleanly when polling task is active | TG-02 | Requires live container | `docker compose stop dotmd` — verify no timeout/cancel errors in logs |
