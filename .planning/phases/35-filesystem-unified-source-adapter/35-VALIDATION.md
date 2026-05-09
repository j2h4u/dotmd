---
phase: 35
slug: filesystem-unified-source-adapter
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-10
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_source_lifecycle.py -q` |
| **Full suite command** | `cd backend && python -m pytest -q` |
| **Estimated runtime** | ~30 seconds |

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
| 35-01-01 | 01 | 1 | FS-03 | — | N/A | unit | `cd backend && python -m pytest tests/ingestion/test_source_filesystem.py -q` | ✅ | ⬜ pending |
| 35-01-02 | 01 | 1 | FS-03 | — | N/A | unit | `cd backend && python -m pytest tests/ingestion/test_source_filesystem.py::test_pipeline_source_document_for_file_info_uses_lifecycle_adapter -q` | ✅ | ⬜ pending |
| 35-02-01 | 02 | 2 | FS-01, FS-03 | — | N/A | unit | `cd backend && python -m pytest tests/ingestion/ -q` | ❌ W0 | ⬜ pending |
| 35-02-02 | 02 | 2 | FS-01 | — | N/A | unit | `cd backend && python -m pytest tests/ingestion/ -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/ingestion/test_source_filesystem.py` — existing; new test stubs for D-07 boundary tests
- [ ] No new fixtures needed — existing `tmp_path` and helper patterns suffice

*Existing infrastructure covers all phase requirements. Wave 0 = add test stubs in Plan 02 before GREEN phase.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| No `_from_file_info` references remain in production code | FS-03 | grep check | `grep -rn "_from_file_info" backend/src/` should return 0 results |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
