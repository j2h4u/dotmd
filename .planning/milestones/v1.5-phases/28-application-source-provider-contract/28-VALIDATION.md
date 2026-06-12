---
phase: 28
slug: application-source-provider-contract
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-07
---

# Phase 28 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py -q` |
| **Full suite command** | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py tests/api/test_service_search.py -q` |
| **Estimated runtime** | ~90 seconds |

## Sampling Rate

- **After every task commit:** Run the plan-local pytest command in that task.
- **After every plan wave:** Run the full suite command above.
- **Before `$gsd-verify-work`:** `just typecheck`, `just lint`, and the focused suite must pass or have documented pre-existing ratchet status.
- **Max feedback latency:** 120 seconds for focused checks.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 28-01-01 | 01 | 1 | R3/R8 | T-28-01 | Provider payloads reject malformed refs and require D-14 unit fields. | unit | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q` | new | pending |
| 28-01-02 | 01 | 1 | R3/R8 | T-28-02 | `export_changes` carries documents and units without extra export methods. | unit | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q` | new | pending |
| 28-02-01 | 02 | 2 | R3/R8 | T-28-03 | Durable checkpoints use `checkpoint_cursor` and source-unit fingerprints are idempotent. | unit | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` | yes | pending |
| 28-02-02 | 02 | 2 | R3/R8 | T-28-04 | Duplicate unchanged source units can be detected without forcing recomputation. | unit | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` | yes | pending |
| 28-03-01 | 03 | 3 | R3/R4/R8 | T-28-05 | Fixture provider proves message windows and document-only fallback without live Telegram. | integration | `cd backend && uv run pytest tests/ingestion/test_application_source_provider.py -q` | new | pending |
| 28-04-01 | 04 | 4 | R4/R8 | T-28-06 | Docs define structured mcp-telegram payloads and forbid private SQLite reads. | docs/regression | `rg "checkpoint_cursor|read_unit_window|SourceDocument|SourceUnit|private SQLite" docs/mcp-telegram-source-contract.md docs/source-adapter-architecture.md` | new | pending |

## Wave 0 Requirements

Existing pytest infrastructure covers all Phase 28 requirements. `tests/ingestion/test_application_source_provider.py` is created by Plan 01 as the first RED test file.

## Manual-Only Verifications

All Phase 28 behaviors have automated fixture, storage, or documentation verification. Live Telegram runtime smoke is deferred to Phase 31.

## Validation Sign-Off

- [x] All tasks have automated verification or explicit ratchet documentation.
- [x] Sampling continuity: no 3 consecutive tasks without automated verification.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency target under 120s for focused checks.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending execution
