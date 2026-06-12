---
phase: 23-fix-dotmd-test-contract
slug: fix-dotmd-test-contract
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06T21:30:58+05:00
validation_state: reconstructed-from-summaries
gaps_found: 0
gaps_resolved: 0
manual_only: 0
---

# Phase 23 - Validation Strategy

> Retroactive Nyquist validation for the completed dotMD test contract cleanup phase.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/ingestion/test_pipeline_metadata.py -q` |
| Full phase command | `just check && just test-e2e` |
| Lint command | `cd backend && uv run ruff check tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/ingestion/test_pipeline_metadata.py tests/e2e/conftest.py` |
| Estimated runtime | about 3 minutes including live e2e |

## Discovery

Phase 23 had no pre-existing `23-VALIDATION.md`, so this file reconstructs the validation contract from:

- `23-01-test-contract-cleanup-PLAN.md`
- `23-01-test-contract-cleanup-SUMMARY.md`
- `23-RESEARCH.md`
- `23-VERIFICATION.md`
- Current `justfile`, README command docs, pytest marker config, e2e fixtures, and behavior-focused tests

Phase 23 is itself a test-infrastructure phase. Its validation focuses on proving the local/live command contract and the replacement of misleading tests with behavior checks.

## Gap Analysis

No Nyquist validation gaps remain. Existing and phase-added tests cover the executable behavior, and live e2e was rerun against the current `dotmd` container.

| Requirement | Coverage |
|-------------|----------|
| TEST-CONTRACT-01 | `just test` runs `pytest -m "not e2e and not smoke"`; `just check` composes lint, typecheck, and local tests. Fresh `just check` passed with 332 local tests and 36 live tests deselected. |
| TEST-CONTRACT-02 | `just test-e2e` runs inside the live `dotmd` container; `_require_live_server` fails explicit e2e runs with `pytest.exit(..., returncode=1)` when `/health` is unreachable. Fresh live e2e passed. |
| TEST-CONTRACT-03 | `backend/tests/smoke` is absent, `just --list` has no `test-smoke`, and the old `9 skipped` green path is gone. |
| TEST-CONTRACT-04 | Focused API/MCP/ingestion tests assert service call contracts, graph/direct result hydration, registered MCP schema/call output, and the real semantic encode boundary. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|----------|-----------|-------------------|-------------|--------|
| 23-01-01 | 01 | 1 | TEST-CONTRACT-01 | Developer command tiers are explicit; local `test` excludes e2e/smoke, `check` remains local-only, and README documents command semantics. | command + docs | `just --list && just test --collect-only -q && just check` | yes | green |
| 23-01-02 | 01 | 1 | TEST-CONTRACT-02, TEST-CONTRACT-03 | Stale smoke suite is deleted; explicit live e2e fails honestly on missing runtime and passes against the healthy live container. | filesystem + live e2e | `test ! -d backend/tests/smoke && ! just --list \| rg "test-smoke" && just test-e2e` | yes | green |
| 23-01-03 | 01 | 1 | TEST-CONTRACT-04 | Low-signal service, graph hydration, and MCP tests now assert observable behavior rather than tautologies, private docstrings, or mock-only outcomes. | unit | `cd backend && uv run pytest tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` | yes | green |
| 23-01-04 | 01 | 1 | TEST-CONTRACT-04 | Embedding encode-boundary coverage bypasses the global semantic mock and asserts the context-prefixed `passage:` text sent to `encode_batch`. | unit | `cd backend && uv run pytest tests/ingestion/test_pipeline_metadata.py -q` | yes | green |
| 23-01-05 | 01 | 1 | TEST-CONTRACT-01, TEST-CONTRACT-04 | Ruff and pyright ratchet remain green after the test contract cleanup. | static analysis | `just check` | yes | green |

## Wave 0 Requirements

Existing pytest infrastructure covers all executable Phase 23 behavior. The live e2e command is intentionally opt-in and was rerun for this validation because Phase 23's contract specifically concerns live command honesty.

## Manual-Only Verifications

All current Phase 23 closure behavior has automated verification or command-level evidence. No unresolved manual-only verification remains.

## Commands Run

| Command | Result |
|---------|--------|
| `just --list` | PASS: no `test-smoke` recipe |
| `test ! -d backend/tests/smoke && ! just --list \| rg "test-smoke"` | PASS |
| `cd backend && uv run pytest tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/ingestion/test_pipeline_metadata.py -q` | PASS: 47 passed, 29 warnings |
| `cd backend && uv run ruff check tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/ingestion/test_pipeline_metadata.py tests/e2e/conftest.py` | PASS |
| `just test --collect-only -q` | PASS: 332/368 collected, 36 deselected |
| `just check` | PASS: ruff passed; pyright ratchet 69 errors, baseline 69; 332 passed, 36 deselected |
| `just test-e2e` | PASS: 36 passed in 130.37s |
| `! just test-smoke 2>&1 \| rg "9 skipped"` | PASS |

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or command-level evidence
- [x] Sampling continuity restored retroactively
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 10 seconds for the focused local suite
- [x] `nyquist_compliant: true` set in frontmatter

Approval: approved 2026-05-06
