---
phase: 37
slug: airweave-connector-compatibility-spike
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-05-11
---

# Phase 37 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && python -m pytest tests/test_gmail_bridge.py -x -q` |
| **Full suite command** | `cd backend && python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd backend && python -m pytest tests/test_gmail_bridge.py -x -q`
- **After every plan wave:** Run `cd backend && python -m pytest tests/ -x -q`
- **Before `/gsd-verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | Status |
|---------|------|------|-------------|-----------|-------------------|--------|
| Vendor slice | 37-01 | 1 | AIR-01 | import smoke | `python -c "from dotmd.vendor.airweave import entities_base"` | pending |
| Shim DI types | 37-01 | 1 | AIR-01 | unit | `pytest tests/test_gmail_bridge.py::test_shim_construction` | pending |
| Bridge search_native | 37-02 | 2 | AIR-01 | unit (mock httpx) | `pytest tests/test_gmail_bridge.py::test_search_native_returns_candidates` | pending |
| SearchCandidate shape | 37-02 | 2 | AIR-01 | model validation | `pytest tests/test_gmail_bridge.py::test_search_candidate_ref_format` | pending |
| read_unit_window | 37-02 | 2 | AIR-01 | unit (mock httpx) | `pytest tests/test_gmail_bridge.py::test_read_unit_window` | pending |
| gmail descriptor | 37-03 | 2 | AIR-03 | unit | `pytest tests/test_gmail_bridge.py::test_gmail_descriptor` | pending |
| lifecycle build | 37-03 | 2 | AIR-03 | unit | `pytest tests/test_gmail_bridge.py::test_lifecycle_build_missing_config_raises` | pending |
| AIR-02 report | 37-04 | 3 | AIR-02 | file exists | `test -f docs/airweave-compatibility.md` | pending |
