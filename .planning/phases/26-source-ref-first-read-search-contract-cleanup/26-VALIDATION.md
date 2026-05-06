---
phase: 26
slug: source-ref-first-read-search-contract-cleanup
status: draft
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06
---

# Phase 26 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest + pyright |
| **Config file** | `backend/pyproject.toml` |
| **Quick run command** | `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` |
| **Full suite command** | `just typecheck && cd backend && uv run pytest tests/e2e/ -q -p no:cacheprovider` |
| **Estimated runtime** | ~120 seconds local focused tests; live e2e depends on container/model state |

---

## Sampling Rate

- **After every task commit:** Run the task's focused pytest command.
- **After every plan wave:** Run `just typecheck` plus the focused pytest files
  named by that plan.
- **Before `$gsd-verify-work`:** `just typecheck` and live MCP smoke must be
  green or the summary must record the exact blocker.
- **Max feedback latency:** one task.

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 26-01-01 | 01 | 1 | D-01/D-02/D-04/D-11/D-12/D-17/D-19 | T-26-01 | Public search identity comes from provenance refs, not holder paths | unit | `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/test_fusion.py -q` | ✅ | pending |
| 26-01-02 | 01 | 1 | D-07/D-08/D-09/D-10/D-13/D-18/D-20 | T-26-02 | Read/drill resolve refs without full reindex or per-request index reload | unit/service | `cd backend && uv run pytest tests/api/test_service_search.py tests/mcp/test_search_tool.py -q` | ✅ | pending |
| 26-02-01 | 02 | 2 | D-02/D-03/D-04/D-05/D-06/D-07/D-08/D-09 | T-26-03 | MCP/API/CLI expose refs and reject path-first public arguments | api/mcp/cli | `cd backend && uv run pytest tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q` | ✅ | pending |
| 26-03-01 | 03 | 3 | D-14/D-15/D-16/D-17/D-18/D-21 | T-26-04 | Docs/tests prevent Telegram from inheriting File/path-shaped contract | docs/e2e | `rg "read\\(file_path|file_paths" docs backend/tests/e2e/test_mcp_smoke.py` | ✅ | pending |
| 26-03-02 | 03 | 3 | phase smoke | T-26-05 | Live MCP consumer sees `search -> ref -> drill/read` | e2e | `docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"` | ✅ | pending |

---

## Wave 0 Requirements

Existing infrastructure covers all Phase 26 requirements. No framework install
or new shared fixture is required before implementation.

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Production restart batching | D-17/D-18/D-21 | The repo instruction says not to restart production for small changes; restart timing is an operator decision | Batch implementation changes, restart once only if live MCP smoke requires code reload, and record the command in the summary |

---

## Validation Sign-Off

- [x] All tasks have automated verify commands or explicit manual-only reason.
- [x] Sampling continuity: no 3 consecutive tasks without automated verify.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is one task.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** pending execution
