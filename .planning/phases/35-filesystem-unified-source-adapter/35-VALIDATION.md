---
phase: 35
slug: filesystem-unified-source-adapter
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-10
audited: 2026-05-10
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && .venv/bin/pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_source_lifecycle.py -q` |
| **Full suite command** | `cd backend && .venv/bin/pytest tests/ingestion/ -q` |
| **Estimated runtime** | ~10 seconds (quick), ~9 seconds (full ingestion) |

---

## Sampling Rate

- **After every task commit:** Run quick run command
- **After every plan wave:** Run full suite command
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 35-01-01 | 01 | 1 | FS-03 | — | N/A | unit | `cd backend && .venv/bin/pytest tests/ingestion/test_source_filesystem.py -q` | ✅ | ✅ green |
| 35-01-02 | 01 | 1 | FS-03 | — | N/A | unit | `cd backend && .venv/bin/pytest tests/ingestion/test_source_filesystem.py::test_pipeline_source_document_for_file_info_uses_lifecycle_adapter -q` | ✅ | ✅ green |
| 35-01-03 | 01 | 1 | FS-03 | — | N/A | unit | `cd backend && .venv/bin/pytest tests/ingestion/test_source_filesystem.py -q` | ✅ | ✅ green |
| 35-02-01 | 02 | 2 | FS-01, FS-03 | — | N/A | unit | `cd backend && .venv/bin/pytest tests/ingestion/test_source_filesystem.py::test_filesystem_adapter_document_for_file_info_is_public_and_correct tests/ingestion/test_source_filesystem.py::test_lifecycle_factory_exposes_document_for_file_info_through_bundle tests/ingestion/test_source_filesystem.py::test_document_for_file_info_and_source_document_to_file_info_round_trip -q` | ✅ | ✅ green |
| 35-02-02 | 02 | 2 | FS-01 | — | N/A | unit | `cd backend && .venv/bin/pytest tests/ingestion/ -q` | ✅ | ✅ green |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [x] `backend/tests/ingestion/test_source_filesystem.py` — 29 tests collected; 3 new boundary tests added for D-07/D-04
- [x] No new fixtures needed — existing `tmp_path` and helper patterns suffice

*Wave 0 complete. All test infrastructure in place and green.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions | Result |
|----------|-------------|------------|-------------------|--------|
| No `_from_file_info` references remain in production code | FS-03 | grep check | `rg "_from_file_info" backend/` should return 0 results | ✅ CLEAN (2026-05-10) |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** 2026-05-10 — all 5 tasks covered, 171 ingestion tests green, 0 gaps

---

## Validation Audit 2026-05-10

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Tasks covered | 5/5 |
| Tests verified green | 171 |

**Notes:** VALIDATION.md was in draft state (written pre-execution). Audit confirmed all tasks completed with full test coverage. Task 35-01-03 (`_RecordingLifecycleAdapter` update) was added to per-task map — missing from original draft. Wave 0 stubs marked `❌ W0` now exist and are green. Manual `_from_file_info` check confirmed CLEAN.
