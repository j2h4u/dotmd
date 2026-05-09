---
phase: quick
plan: 260510-0nb
subsystem: search
tags: [federated-search, merge-strategy, config, quota]
key-files:
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/api/service.py
    - backend/tests/api/test_service_search.py
decisions:
  - "Quota-based merge over score-based: local uses cosine (0.52-0.96), mcp-telegram returns fused_score=0.0 — unified sort silently drops all federated results"
  - "Adaptive fed_slots = min(fed_quota, len(filtered_fed)) handles daemon-down, sparse results, and normal operation in one code path"
  - "is_low_signal_telegram_text pre-filter reused from trickle ingestion pipeline — no new logic"
metrics:
  completed: "2026-05-10"
  tasks: 2
  commits: 1
---

# Quick Task 260510-0nb: Adaptive Slot Quota for Federated Search

Reserves configurable result slots for federated (Telegram) candidates instead of competing in a unified score sort that always drops zero-score federated results.

## What Was Done

**Task 1: Config field + _merge_with_federated_quota implementation**

Added `federated_result_quota: int = 3` to `Settings` in `config.py` with explanatory docstring covering why score-based merge is impossible across heterogeneous sources.

Added `_merge_with_federated_quota()` as a module-level function in `service.py`:
- Filters fed candidates via `is_low_signal_telegram_text()` before quota math
- `fed_slots = min(fed_quota, len(filtered_fed))` — adaptive, handles daemon-down
- `local_slots = top_k - fed_slots` — local fills remaining positions by fused_score
- Imported `is_low_signal_telegram_text` from `dotmd.ingestion.telegram_provider`

Wired into `search_async`: replaced the `sorted(local + fed)[:top_k]` block with `_merge_with_federated_quota(local_candidates, fed_candidates, top_k, self._settings.federated_result_quota)`. The `else` branch (no fed) now also sorts local by fused_score descending.

**Task 2: Unit tests**

Added `TestMergeWithFederatedQuota` (4 tests) to `test_service_search.py`:
- `test_federated_quota_candidates_appear_when_local_fills_top_k` — 3 fed appear even when 10 local available
- `test_federated_quota_adaptive_slots` — 1 fed result uses 1 slot, local fills remaining 4
- `test_federated_quota_filters_low_signal` — snippet "ok" (2 chars) excluded from results
- `test_federated_quota_empty_fed_returns_sorted_local` — empty fed → sorted local[:top_k]

All 4 pass.

## Commits

| Hash | Message |
|------|---------|
| 654cdf1 | feat(34): adaptive slot quota for federated search merge |

## Deviations from Plan

**[Rule 1 - Bug] Fixed EN DASH in docstrings caught by ruff RUF001**
- Found during: ruff check after implementation
- Issue: Plan template used `–` (EN DASH U+2013) in `0.52–0.96`; ruff RUF001 flags ambiguous Unicode dashes
- Fix: replaced with hyphen-minus `-` in both config.py and service.py docstrings
- Files modified: `backend/src/dotmd/core/config.py`, `backend/src/dotmd/api/service.py`
- Commit: 654cdf1 (included in same atomic commit)

**Pre-existing test failure (out of scope)**
- `TestSearchReturnsFilePaths::test_local_only_search_returns_searchcandidate` was already failing before this task (confirmed by restoring backup and re-running). The test patches `_execute_search` but real Telegram provider candidates bypass that patch via `search_async`. Not caused by this change, not fixed (out of scope per deviation rules).

## Self-Check: PASSED

- `_merge_with_federated_quota` importable: confirmed (4 tests pass via docker exec)
- `federated_result_quota` field in Settings with default 3: confirmed
- Commit 654cdf1 exists: confirmed
- No unexpected file deletions
- ruff check: All checks passed
