---
phase: 29
slug: telegram-adapter-mvp-ingestion
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-07
---

# Phase 29 - Validation Strategy

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest via `uv run pytest`; repo checks via `just` |
| **Config file** | `backend/pyproject.toml`, `/home/j2h4u/repos/j2h4u/mcp-telegram/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py -q` |
| **Full suite command** | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q` |
| **Estimated runtime** | ~90 seconds focused, excluding live smoke |

## Sampling Rate

- **After every task commit:** Run the task's focused pytest command.
- **After every plan wave:** Run the full focused suite for dotMD and the focused `mcp-telegram` daemon tests when that repo is touched.
- **Before `$gsd-verify-work`:** Focused suites plus `just typecheck` and `just lint` must pass or document a pre-existing ratchet.
- **Max feedback latency:** 120 seconds for focused local tests.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 29-01-01 | 01 | 1 | R4, R8 | T29-01 | Export API returns structured data, not rendered tool text | unit | `cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q` | ✅ | pending |
| 29-01-02 | 01 | 1 | R4, R5 | T29-02 | Export cursor/checkpoint is deterministic over synced messages | unit | `cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py -q` | ✅ | pending |
| 29-02-01 | 02 | 2 | R4, R5, R8 | T29-03 | dotMD provider maps payloads without Telethon or private DB imports | unit | `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q` | ✅ | pending |
| 29-02-02 | 02 | 2 | R5, R8 | T29-04 | Low-signal units are stored but not standalone indexed hits | unit | `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q` | ✅ | pending |
| 29-03-01 | 03 | 3 | R5, R8 | T29-05 | Ingestion commits checkpoints only after local persistence | integration | `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py -q` | ✅ | pending |
| 29-03-02 | 03 | 3 | R5, R8 | T29-06 | Replay skips unchanged source units and changes edited units | integration | `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py -q` | ✅ | pending |
| 29-04-01 | 04 | 4 | R7, R8 | T29-07 | `read(ref)` and `drill(ref)` resolve Telegram refs without filesystem frontmatter | integration | `cd backend && uv run pytest tests/api/test_service_search.py -q` | ✅ | pending |
| 29-04-02 | 04 | 4 | R4, R8 | T29-08 | Live smoke proves export/import/metadata state only | smoke | `docker exec dotmd dotmd telegram ingest --limit 10 --dry-run` or final CLI chosen by implementation | ⚠ | pending |

## Wave 0 Requirements

Existing pytest infrastructure covers all phase requirements. New tests are introduced in the relevant plans before implementation where TDD applies.

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Live runtime boundary smoke | R4, R8 | Requires deployed `mcp-telegram` daemon and dotMD container/runtime state | Run the final Phase 29 smoke command from Plan 04 and confirm it reports Telegram export/import counts with at least one persisted Telegram document or an explicit no-data reason. |

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or explicit manual smoke instructions.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all MISSING references.
- [x] No watch-mode flags.
- [x] Feedback latency target is under 120 seconds for focused tests.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending execution
