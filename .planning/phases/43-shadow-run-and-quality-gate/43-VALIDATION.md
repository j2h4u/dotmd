---
phase: 43
slug: shadow-run-and-quality-gate
status: draft
nyquist_compliant: true
wave_0_complete: false
created: 2026-06-14
---

# Phase 43 - Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest via `uv run` |
| **Config file** | `backend/pyproject.toml`; e2e override in `backend/tests/e2e/pytest.ini` |
| **Quick run command** | `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_shadow_runner.py tests/devtools/test_surreal_eval_runner.py -q` |
| **Full suite command** | `just verify` |
| **Estimated runtime** | Focused gate target under 60 seconds; full suite is repo-dependent |

---

## Sampling Rate

- **After every task commit:** Run the focused test file touched by that task plus the nearest existing invariant test.
- **After every plan wave:** Run `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_shadow_runner.py tests/devtools/test_surreal_eval_runner.py -q`.
- **Before `/gsd-verify-work`:** Run `just verify` when local time allows and always run the Phase 43 artifact verify-only command after all eight artifacts exist.
- **Max feedback latency:** 60 seconds for focused gates; do not use production reindexing, TEI/GLiNER recomputation, or live runtime mutation as validation.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 43-01-01 | 01 | 1 | SURR-CUT-01 | T-43-01 / T-43-02 / T-43-03 | RED tests define scale, memory, guardrail, and deterministic JSON contracts without live services | unit | `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py -q` | W0 | pending |
| 43-01-02 | 01 | 1 | SURR-CUT-01 | T-43-01 / T-43-02 / T-43-03 | Metric helpers reject incomplete build/store/latency/memory/guardrail evidence | unit | `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py tests/search/test_surreal_retrieval_parity.py -q` | W0 | pending |
| 43-02-01 | 02 | 2 | SURR-CUT-01 / SURR-EVAL-03 | T-43-04 / T-43-05 / T-43-06 / T-43-08 | RED tests require copied-rehearsal baseline capture, explicit Surreal candidate overrides, sentinel-aware acceptance ledger validation, and no startup/default mutation | unit | `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py -q` | W0 | pending |
| 43-02-02 | 02 | 2 | SURR-CUT-01 / SURR-EVAL-03 | T-43-04 / T-43-06 / T-43-07 / T-43-08 | Runner validates a full artifact bundle, strips only the Phase 43 metadata sentinel before Phase 40 acceptance loading, and fails missing replay/guardrail evidence | unit/integration | `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_eval_runner.py -q` | W0 | pending |
| 43-02-03 | 02 | 2 | SURR-CUT-01 / SURR-EVAL-03 | T-43-05 / T-43-09 | Runbook documents copied old-stack rehearsal, 16-query quality corpus, larger replay metrics window, non-empty acceptance ledger sentinel, and no live cutover behavior | unit + lint | `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py tests/search/test_surreal_shadow_metrics.py tests/devtools/test_surreal_eval_runner.py -q` | W0 | pending |
| 43-03-01 | 03 | 3 | SURR-CUT-01 / SURR-SEARCH-02 | T-43-09 / T-43-10 / T-43-13 | Source capture plus baseline/candidate JSONL are present and share query ids before full verify-only runs | artifact check | `cd backend && uv run python -c "import json; from pathlib import Path; from dotmd.search.surreal_eval import load_eval_results; p=Path('../.planning/phases/43-shadow-run-and-quality-gate/artifacts'); json.loads((p/'source-capture.json').read_text(encoding='utf-8')); b=[r.query_id for r in load_eval_results(p/'baseline-results.jsonl')]; c=[r.query_id for r in load_eval_results(p/'candidate-results.jsonl')]; assert b and b == c"` | W3 | pending |
| 43-03-02 | 03 | 3 | SURR-CUT-01 / SURR-EVAL-03 / SURR-SEARCH-02 | T-43-10 / T-43-11 / T-43-12 / T-43-13 | All eight artifacts exist, acceptance ledger is non-empty, and verify-only validates quality, scale, memory, replay, and guardrail evidence | artifact check | `cd backend && uv run python devtools/surreal_shadow_runner.py --verify-only --artifacts-dir ../.planning/phases/43-shadow-run-and-quality-gate/artifacts --golden-queries devtools/surreal_golden_queries.jsonl` | W3 | pending |
| 43-03-03 | 03 | 3 | SURR-EVAL-03 | T-43-11 / T-43-12 | Human acceptance rows require explicit reasons and raw diff classifications stay generated, not hand-edited | checkpoint + artifact check | `cd backend && uv run python devtools/surreal_shadow_runner.py --verify-only --artifacts-dir ../.planning/phases/43-shadow-run-and-quality-gate/artifacts --golden-queries devtools/surreal_golden_queries.jsonl` | W3 | pending |

*Status: pending, green, red, flaky*

---

## Wave 0 Requirements

- [ ] `backend/tests/search/test_surreal_shadow_metrics.py` - RED tests for metric fields, memory guardrail constants, fail-closed validation, and deterministic JSON writing.
- [ ] `backend/tests/devtools/test_surreal_shadow_runner.py` - RED tests for full artifact bundle behavior, copied-rehearsal baseline capture, explicit candidate overrides, sentinel-aware ledger loading, and scope guardrails.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Semantic-difference acceptance review | SURR-EVAL-03 | The operator must decide whether material Surreal semantic changes are acceptable before cutover planning | Inspect `shadow-summary.md` and `shadow-diffs.jsonl`; for every accepted material difference, add a real `query_id`, `accepted_by`, and `accepted_reason` row after the Phase 43 sentinel in `accepted-diffs.jsonl`; rerun the verify-only command |

---

## Validation Sign-Off

- [x] All tasks have `<automated>` verify or Wave 0 dependencies
- [x] Sampling continuity: no 3 consecutive tasks without automated verify
- [x] Wave 0 covers all missing test references
- [x] No watch-mode flags
- [x] Feedback latency target is under 60 seconds for focused checks
- [x] `nyquist_compliant: true` set in frontmatter

**Approval:** pending
