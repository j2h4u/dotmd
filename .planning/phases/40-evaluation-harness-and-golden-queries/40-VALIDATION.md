---
phase: 40
slug: evaluation-harness-and-golden-queries
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-13
---

# Phase 40 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest via `uv run` |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` |
| **Full suite command** | `cd backend && just unit tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py` |
| **Estimated runtime** | ~10 seconds |

## Sampling Rate

- **After every task commit:** Run `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x`
- **After every plan wave:** Run `cd backend && just unit tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py`
- **Before `/gsd-verify-work`:** Focused unit gate must be green; run `just verify` if local time allows.
- **Max feedback latency:** 30 seconds for the focused gate.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 40-01-01 | 01 | 1 | SURR-EVAL-01 / SURR-EVAL-02 / SURR-EVAL-03 | T-40-01 / T-40-02 / T-40-04 | RED tests define strict JSONL parsing, enum-backed classification, acceptance gating, and no shell interpolation | unit | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` | W0 | pending |
| 40-01-02 | 01 | 1 | SURR-EVAL-02 / SURR-EVAL-03 | T-40-01 / T-40-02 / T-40-03 / T-40-05 | Typed evaluator and runner reject malformed inputs, preserve raw gates, and fail unresolved blockers | unit | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -k "not approved_corpus_file" -x` | W0 | pending |
| 40-01-03 | 01 | 1 | SURR-EVAL-01 / SURR-EVAL-02 / SURR-EVAL-03 | T-40-01 / T-40-02 | Checked-in corpus covers all required categories and docs explain scope/gate semantics | unit + doc grep | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` | W0 | pending |

*Status: pending · green · red · flaky*

## Wave 0 Requirements

- [ ] `backend/tests/search/test_surreal_eval.py` — RED tests for evaluator contracts.
- [ ] `backend/tests/devtools/test_surreal_eval_runner.py` — RED tests for runner/report contracts.

## Manual-Only Verifications

All phase behaviors have automated verification. Human review is captured in
`backend/devtools/surreal_golden_queries_review.md`, but the corpus shape and
coverage still have automated tests.

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all MISSING references
- [x] No watch-mode flags
- [x] Feedback latency < 30s
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** approved 2026-06-13
