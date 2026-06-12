---
phase: "29"
plan: "04"
subsystem: "telegram read/drill resolver and smoke"
tags: ["telegram", "read", "drill", "unix-socket", "tdd", "smoke"]
dependency_graph:
  requires: ["29-01 structured mcp-telegram daemon export", "29-03 Telegram ingestion persistence"]
  provides: ["Telegram message read/drill resolver", "bounded telegram ingest CLI smoke command", "Phase 29 delivered-state docs"]
  affects: ["Phase 31 public search/read/drill live smoke"]
tech-stack:
  added: ["DOTMD_TELEGRAM_DAEMON_SOCKET", "UnixSocketTelegramSourceClient", "dotmd telegram ingest --single-batch"]
  patterns: ["dialog-scope active binding check", "message-level target ref", "provider window with indexed-chunk fallback"]
key-files:
  created:
    - ".planning/phases/29-telegram-adapter-mvp-ingestion/29-04-telegram-read-drill-and-smoke-SUMMARY.md"
  modified:
    - "backend/src/dotmd/api/service.py"
    - "backend/src/dotmd/cli.py"
    - "backend/src/dotmd/core/config.py"
    - "backend/src/dotmd/ingestion/source_provider.py"
    - "backend/src/dotmd/ingestion/telegram_provider.py"
    - "backend/tests/api/test_service_search.py"
    - "backend/tests/ingestion/application_source_fixtures.py"
    - "backend/tests/ingestion/test_application_source_provider.py"
    - "backend/tests/ingestion/test_telegram_ingestion.py"
    - "docs/mcp-telegram-source-contract.md"
    - "docs/source-adapter-architecture.md"
decisions:
  - "Telegram message refs resolve active bindings at dialog scope, while read/drill payloads preserve the concrete target message ref."
  - "Phase 29 supports only the existing mcp-telegram UNIX socket daemon transport through DOTMD_TELEGRAM_DAEMON_SOCKET; no URL transport was added."
  - "Live smoke is recorded as runtime-unavailable because the running dotMD container does not expose the mcp-telegram daemon socket."
metrics:
  duration: "~13 min"
  started_at: "2026-05-08T08:06:17Z"
  completed_at: "2026-05-08T08:19:19Z"
  tasks: 3
  files_changed: 12
---

# Phase 29 Plan 04: Telegram Read/Drill Resolver And Smoke Summary

Telegram message refs now resolve through dotMD read/drill without filesystem fallback, with a bounded CLI smoke command for the existing mcp-telegram UNIX socket boundary.

## Completed Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Add Telegram read/drill resolver tests | `3167e89` | `backend/tests/api/test_service_search.py` |
| 2 | Add Telegram ingest CLI/config RED tests | `696be4b` | `backend/tests/ingestion/test_telegram_ingestion.py` |
| 2 | Implement Telegram resolver and bounded ingest smoke command | `87fc977` | `backend/src/dotmd/api/service.py`, `backend/src/dotmd/cli.py`, `backend/src/dotmd/core/config.py`, `backend/src/dotmd/ingestion/telegram_provider.py`, tests |
| 3 | Document Phase 29 boundary and close verification gates | `e32511e` | docs, provider protocol, tests |

## What Changed

- Added `_parse_telegram_message_ref("telegram:dialog:<dialog_id>:message:<message_id>")` and Telegram read/drill branches before filesystem resolution.
- Added dialog-scope active binding enforcement: `telegram:dialog:-1001:message:42` checks `("telegram", "dialog:-1001")`.
- `read(ref)` returns provider `read_unit_window(...)` units when configured, or local indexed chunks via `get_chunks_by_source_unit_ref(...)` when no live provider is configured.
- `drill(ref)` returns Telegram document metadata, target message ref, and empty frontmatter instead of filesystem frontmatter.
- Added `telegram_daemon_socket` / `DOTMD_TELEGRAM_DAEMON_SOCKET`.
- Added `UnixSocketTelegramSourceClient` for newline-delimited JSON over the existing mcp-telegram daemon UNIX socket.
- Added `dotmd telegram ingest --limit N --dry-run --single-batch` and non-dry-run one-batch ingestion output.
- Updated docs to state the Phase 29 delivered boundary and keep full public search/read/drill live smoke in Phase 31.

## Verification

```bash
cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py -q
# 57 passed, 50 warnings in 4.95s
```

```bash
rg -n "telegram.*ingest|_parse_telegram_message_ref|read_unit_window|target_unit_ref|DOTMD_TELEGRAM_DAEMON_SOCKET|get_chunks_by_source_unit_ref|single-batch" backend/src/dotmd/api/service.py backend/src/dotmd/cli.py backend/src/dotmd/core/config.py backend/tests/api/test_service_search.py
# Found expected implementation and test references.
```

```bash
! rg -n "DOTMD_TELEGRAM_DAEMON_URL|telegram_daemon_url" backend/src/dotmd backend/tests
# No matches.
```

```bash
just typecheck
# pyright ratchet: 66 errors (baseline 69)
# improvements: -3 across 2 files
```

```bash
just lint
# All checks passed.
```

## Smoke Result

Live bounded smoke did not run because the running dotMD container does not expose the mcp-telegram daemon socket.

Evidence:

```bash
docker exec dotmd sh -lc 'printf "DOTMD_TELEGRAM_DAEMON_SOCKET=%s\n" "${DOTMD_TELEGRAM_DAEMON_SOCKET-}"; test -n "${DOTMD_TELEGRAM_DAEMON_SOCKET-}" && test -S "$DOTMD_TELEGRAM_DAEMON_SOCKET"'
# DOTMD_TELEGRAM_DAEMON_SOCKET=
```

```bash
docker exec dotmd dotmd telegram ingest --limit 10 --dry-run --single-batch
# Error: Telegram daemon socket is not configured
```

The mcp-telegram runtime itself is available and has a daemon socket:

```bash
docker exec mcp-telegram sh -lc 'test -S /root/.local/state/mcp-telegram/daemon.sock && ls -l /root/.local/state/mcp-telegram/daemon.sock'
# srw------- 1 root root 0 May  5 18:58 /root/.local/state/mcp-telegram/daemon.sock
```

Current deployment path notes:

- Host Docker volume source: `/var/lib/docker/volumes/mcp-telegram_state/_data`
- mcp-telegram container socket path: `/root/.local/state/mcp-telegram/daemon.sock`
- Proposed dotMD in-container socket path documented for deployment: `/mcp-telegram-state/daemon.sock`
- dotMD container currently has no `mcp-telegram_state` mount and no `DOTMD_TELEGRAM_DAEMON_SOCKET`.

Production was not restarted and `/opt/docker/dotmd` was not edited in this execution, because the currently configured dotMD restart pre-flight runs broad lint/type/e2e gates and socket deployment should be batched deliberately with the compose/env mount change.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Closed type/lint gate regressions introduced by Telegram provider arguments**
- **Found during:** Task 3 verification
- **Issue:** `just typecheck` flagged the provider protocol as missing `updated_after` / `updated_after_cursor`, and tests needed casts for new dynamic read/drill payload keys.
- **Fix:** Updated `ApplicationSourceProviderProtocol`, fixtures, and service payload typing; kept intentional Cyrillic low-signal strings lint-clean with targeted `RUF001` noqa comments.
- **Files modified:** `backend/src/dotmd/api/service.py`, `backend/src/dotmd/ingestion/source_provider.py`, `backend/src/dotmd/ingestion/telegram_provider.py`, `backend/tests/api/test_service_search.py`, `backend/tests/ingestion/application_source_fixtures.py`, `backend/tests/ingestion/test_application_source_provider.py`, `backend/tests/ingestion/test_telegram_ingestion.py`
- **Verification:** `just typecheck`, `just lint`, and focused pytest passed.
- **Commit:** `e32511e`

## Known Stubs

None. The empty fixture/default values found by the stub scan are existing test/default patterns or intentional filesystem fallback placeholders, not user-visible Telegram stubs.

## Auth Gates

None.

## Threat Flags

| Flag | File | Description |
|---|---|---|
| threat_flag: local_daemon_socket | `backend/src/dotmd/ingestion/telegram_provider.py` | New local UNIX-socket client reads structured Telegram source data from the mcp-telegram daemon. It is local-only, configured by `DOTMD_TELEGRAM_DAEMON_SOCKET`, and covered by tests plus the negative URL grep. |

## Self-Check: PASSED

- Summary file exists at `.planning/phases/29-telegram-adapter-mvp-ingestion/29-04-telegram-read-drill-and-smoke-SUMMARY.md`.
- Task commits exist: `3167e89`, `696be4b`, `87fc977`, `e32511e`.
- Focused pytest, required positive/negative `rg` checks, `just typecheck`, and `just lint` passed.
- Live smoke was attempted and recorded as runtime-unavailable with exact commands and socket evidence.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated by this executor, per orchestrator instructions.
