---
phase: 27
slug: resource-bindings-retained-artifacts-foundation
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-07
---

# Phase 27 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/api/test_service_search.py tests/test_fusion.py -q` |
| **Full suite command** | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py -q` |
| **Estimated runtime** | ~90 seconds |

## Sampling Rate

- **After every task commit:** Run the plan-local pytest command in that task.
- **After every plan wave:** Run the full suite command above.
- **Before `$gsd-verify-work`:** `just typecheck`, `just lint`, and the full focused suite must be green or have documented pre-existing ratchet status.
- **Max feedback latency:** 120 seconds for focused checks.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 27-01-01 | 01 | 1 | R1/R2 | T-27-01 | Active/inactive bindings cannot be confused with retained artifact rows. | unit | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` | yes | pending |
| 27-01-02 | 01 | 1 | R1/R2 | T-27-02 | Existing source_documents and provenance are retained while binding state changes. | unit | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` | yes | pending |
| 27-02-01 | 02 | 2 | R1/R2 | T-27-03 | Missing filesystem paths deactivate active binding instead of hard-purging chunks/vectors/FTS/provenance. | integration | `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q` | yes | pending |
| 27-02-02 | 02 | 2 | R1/R2 | T-27-04 | Equivalent restored content reuses retained artifacts or reports countable reuse evidence. | integration | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q` | yes | pending |
| 27-03-01 | 03 | 3 | R1/R2/R8 | T-27-05 | Public search/read/drill hide inactive refs and never expose retained inactive content. | unit/integration | `cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py -q` | yes | pending |
| 27-04-01 | 04 | 4 | R8 | T-27-06 | Filesystem behavior remains compatible and docs state no Telegram/GC scope. | regression | `just typecheck && just lint` | yes | pending |

## Wave 0 Requirements

Existing infrastructure covers all phase requirements.

## Manual-Only Verifications

All Phase 27 behaviors have automated fixture or integration verification. Live Telegram smoke is explicitly deferred to Phase 31.

## Validation Sign-Off

- [x] All tasks have automated verification or explicit ratchet documentation.
- [x] Sampling continuity: no 3 consecutive tasks without automated verification.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency target under 120s for focused checks.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending execution
