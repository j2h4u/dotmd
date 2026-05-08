---
phase: "29"
plan: "02"
subsystem: "telegram source provider"
tags: ["telegram", "source-provider", "tdd", "low-signal", "fingerprints"]
dependency_graph:
  requires: ["29-01 structured mcp-telegram source export", "Phase 28 application source provider contract"]
  provides: ["TelegramApplicationSourceProvider", "message-level Telegram public refs", "provider update watermark batch fields"]
  affects: ["29-03-dotmd-telegram-ingestion", "29-04-telegram-read-drill-and-smoke"]
tech-stack:
  added: []
  patterns: ["pure structured JSON provider boundary", "message-level public refs", "explicit-null deterministic fingerprint payloads"]
key-files:
  created:
    - "backend/src/dotmd/ingestion/telegram_provider.py"
    - "backend/tests/ingestion/test_telegram_provider.py"
  modified:
    - "backend/src/dotmd/core/models.py"
decisions:
  - "Telegram provider code consumes a small structured client protocol and does not import Telegram runtime internals."
  - "Low-signal Telegram messages remain SourceUnit records with standalone_search=false rather than disappearing."
  - "Provider fingerprints serialize explicit null optional metadata so edited and same-timestamp replay behavior remains deterministic."
requirements-completed: ["R4", "R5", "R8"]
metrics:
  duration: "~3 min"
  completed_at: "2026-05-08T07:53:46Z"
  tasks: 2
  files_changed: 3
---

# Phase 29 Plan 02: dotMD Telegram Provider Summary

Structured Telegram daemon payloads now map into dotMD application-source batches with message refs, deterministic fingerprints, low-signal markers, and edited-message watermarks.

## Performance

- **Duration:** ~3 min
- **Started:** 2026-05-08T07:50:36Z
- **Completed:** 2026-05-08T07:53:46Z
- **Tasks:** 2
- **Files modified:** 3

## Completed Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Add Telegram provider mapping tests | `016bf0b` | `backend/tests/ingestion/test_telegram_provider.py` |
| 2 | Implement provider/client mapping and low-signal classification | `4a75489` | `backend/src/dotmd/ingestion/telegram_provider.py`, `backend/src/dotmd/core/models.py` |

## What Changed

- Added RED tests for Telegram source description mapping, dialog documents, message source units, message-level public refs, duplicate `ok` messages, edited fingerprints, low-signal RU/EN acknowledgement classification, and update watermark forwarding.
- Added `updated_after` and `updated_after_cursor` fields to `ApplicationSourceChangeBatch`.
- Added `TelegramSourceClientProtocol` and `TelegramApplicationSourceProvider` for structured daemon payloads only.
- Added `public_ref_for_unit(unit) -> telegram:<unit_ref>`.
- Added deterministic message fingerprints over normalized text plus sent/edit/delete/sender/topic/reply/update metadata, with optional fields serialized as explicit JSON null values.
- Added `standalone_search` metadata so low-signal messages can be stored without becoming standalone normal search hits.

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend && uv run pytest tests/ingestion/test_telegram_provider.py -q
# 7 passed in 1.98s
```

```bash
rg -n "telethon|sync_db|list_messages" backend/src/dotmd/ingestion/telegram_provider.py || true
# no matches
```

## Deviations from Plan

None - plan executed exactly as written.

## Known Stubs

None.

## Auth Gates

None.

## Threat Flags

None - the new structured provider boundary is the planned mitigation for the Phase 29 threat model and is covered by the grep guard plus focused provider tests.

## Self-Check: PASSED

- Summary file exists at `.planning/phases/29-telegram-adapter-mvp-ingestion/29-02-dotmd-telegram-provider-SUMMARY.md`.
- dotMD commits exist: `016bf0b`, `4a75489`.
- Focused pytest and forbidden-runtime grep guard passed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated by this executor, per orchestrator instructions.
