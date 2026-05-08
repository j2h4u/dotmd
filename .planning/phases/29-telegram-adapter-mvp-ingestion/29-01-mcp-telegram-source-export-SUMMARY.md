---
phase: "29"
plan: "01"
subsystem: "mcp-telegram source export"
tags: ["telegram", "source-provider", "tdd", "daemon-api"]
dependency_graph:
  requires: ["Phase 28 application source provider contract", "mcp-telegram sync.db daemon boundary"]
  provides: ["structured Telegram source description", "incremental source export API", "source-unit read window API"]
  affects: ["/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py", "/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py", "/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py"]
tech_stack:
  added: ["daemon JSON methods: describe_source, export_source_changes, read_source_unit_window"]
  patterns: ["TDD red/green", "identity cursor plus update watermark", "negative dialog id cursor parser"]
key_files:
  created: []
  modified:
    - "/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py"
    - "/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py"
    - "/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py"
decisions:
  - "Delete lifecycle remains outside this plan; unit_updated_at uses max(sent_at, edit_date) because no separate cache update timestamp exists in the daemon storage."
  - "Source export is daemon/client JSON API only; dotMD still does not read mcp-telegram private SQLite tables or parse rendered list_messages text."
metrics:
  duration: "~17 min"
  completed_at: "2026-05-08T07:48:03Z"
  tasks: 2
  files_changed: 4
---

# Phase 29 Plan 01: mcp-telegram Source Export API Summary

Structured Telegram export for dotMD now flows through the mcp-telegram daemon/client boundary with source description, incremental source changes, and message-window reads.

## Completed Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Add structured export API tests | `f950cfa` | `tests/test_daemon.py` |
| 2 | Implement daemon source export and read-window handlers | `378b4ee` | `src/mcp_telegram/daemon_api.py`, `src/mcp_telegram/daemon_client.py`, `tests/test_daemon.py` |

## What Changed

- Added RED tests for `describe_source`, `export_source_changes`, and `read_source_unit_window`.
- Added daemon routing and handlers for Telegram source description, source export, and source-unit windows.
- Added `DaemonConnection` convenience methods for the new daemon API.
- Export rows now carry structured `document` and `unit` payloads with stable refs, metadata JSON, fingerprints, `checkpoint_cursor`, `updated_after`, and `updated_after_cursor`.
- Cursor parsing uses `rsplit(":message:", 1)` so negative Telegram dialog ids like `telegram:v1:dialog:-1001:message:42` parse correctly.
- Identity/bootstrap rows and update-watermark rows are separate streams in one response; update rows cannot move `checkpoint_cursor` backwards.

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q
# 36 passed in 4.08s
```

```bash
rg -n "export_source_changes|read_source_unit_window|describe_source|telegram:v1:dialog" \
  /home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram \
  /home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py
# Found expected daemon API, daemon client, and test references.
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Corrected RED fixture epoch timestamps**
- **Found during:** Task 2
- **Issue:** The initial RED tests used epoch values that did not match the asserted `2026-02-01T00:01:00.000000Z` watermark.
- **Fix:** Adjusted the fixture `sent_at`/`edit_date` values while preserving the same cursor and watermark behavior under test.
- **Files modified:** `/home/j2h4u/repos/j2h4u/mcp-telegram/tests/test_daemon.py`
- **Commit:** `378b4ee`

## Known Stubs

None.

## Auth Gates

None.

## Threat Flags

| Flag | File | Description |
|---|---|---|
| threat_flag: daemon_api_surface | `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` | New local daemon JSON methods expose structured Telegram source records to dotMD callers. Covered by tests for cursor safety, update-watermark delivery, and no rendered `list_messages` payload use. |

## Self-Check: PASSED

- Summary file exists at `.planning/phases/29-telegram-adapter-mvp-ingestion/29-01-mcp-telegram-source-export-SUMMARY.md`.
- `mcp-telegram` commits exist: `f950cfa`, `378b4ee`.
- Focused pytest and plan `rg` verification passed.
- dotMD `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated by this executor, per orchestrator instructions.
