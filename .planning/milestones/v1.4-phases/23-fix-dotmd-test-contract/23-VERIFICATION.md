---
phase: 23-fix-dotmd-test-contract
verified: 2026-05-06T19:56:26+05:00
status: passed
score: 96
---

# Phase 23 Verification: Fix dotMD Test Contract

## Goal Achievement

**Goal:** Make dotMD's test commands and tests honest by separating local and live test tiers, removing stale smoke coverage, making explicit live commands fail on missing runtime, and replacing misleading low-signal tests with behavior checks.

**Result:** PASSED.

The phase delivered local-only default gates, an explicit live e2e command, no stale `test-smoke` command surface, no stale `backend/tests/smoke` directory, fail-fast live runtime checks, and behavior-focused tests for MCP/search/embedding boundaries.

## Observable Truths

| Truth | Status | Evidence |
|-------|--------|----------|
| Local tests do not require live Docker, TEI, external ports, or production data | VERIFIED | `justfile:13` runs `pytest -m "not e2e and not smoke"` for `just test`; `just check` composes lint, typecheck, and local tests. |
| Explicit live commands fail non-zero when runtime is missing | VERIFIED | `backend/tests/e2e/conftest.py:326` defines `_require_live_server`; `backend/tests/e2e/conftest.py:336` exits pytest with `returncode=1` when `/health` is unavailable. |
| `just test` and `just check` exclude e2e/smoke by default | VERIFIED | `justfile:13` excludes `e2e` and `smoke`; `justfile:38` calls local `test`. |
| Stale smoke suite and `test-smoke` recipe are removed | VERIFIED | `backend/tests/smoke` is absent and `just --list` has no `test-smoke`. |
| HTTP e2e cases do not start stdio MCP subprocess | VERIFIED | `backend/tests/e2e/conftest.py:312` parametrizes HTTP/stdio; `backend/tests/e2e/conftest.py:316` returns `_http_call` directly for HTTP; `_stdio_session` is resolved lazily only at `backend/tests/e2e/conftest.py:318`. |
| Low-signal tests are replaced by behavior checks | VERIFIED | Search and MCP tests assert service call contracts, hydrated result shape, registered tool schema, and stubbed tool-call output. |
| Embedding boundary coverage is explicit | VERIFIED | `backend/pyproject.toml` registers `real_semantic_encode_batch`; `backend/tests/ingestion/test_pipeline_metadata.py:128` uses it and `backend/tests/ingestion/test_pipeline_metadata.py:162` asserts the context-prefixed `passage:` boundary. |
| Developer docs state command semantics | VERIFIED | `README.md:71` through `README.md:78` documents `just test`, `just test-e2e`, `just typecheck`, and `just check`. |
| Pyright ratchet was lowered opportunistically during the phase | VERIFIED | Phase summary records baseline reduction from 91 to 76; later Phase 26 work lowered the current baseline further to 69. |

## Required Artifacts

| Artifact | Status | Evidence |
|----------|--------|----------|
| `justfile` local/live command split | VERIFIED | `just test`, `just test-e2e`, `just typecheck`, and `just check` are present. |
| E2E transport fixture | VERIFIED | `backend/tests/e2e/conftest.py` contains `mcp_call` and lazy stdio fixture access. |
| README command docs | VERIFIED | `README.md` documents `just check` and the local/live command split. |
| Phase summary traceability | VERIFIED | `23-01-test-contract-cleanup-SUMMARY.md` records all four `TEST-CONTRACT-*` requirements as completed. |

## Key Link Verification

`just check` remains a local-only quality gate because it depends on `lint`, `typecheck`, and `test`, while `just test` applies `pytest -m "not e2e and not smoke"`. The live MCP path is isolated behind `just test-e2e`, which runs inside the `dotmd` container and uses the e2e fail-fast fixture.

## Requirements Coverage

| Requirement | Status | Evidence |
|-------------|--------|----------|
| TEST-CONTRACT-01 | SATISFIED | Local command marker exclusion and current targeted local pytest pass. |
| TEST-CONTRACT-02 | SATISFIED | Live e2e command plus `_require_live_server` hard failure on missing runtime. |
| TEST-CONTRACT-03 | SATISFIED | `backend/tests/smoke` is deleted and `test-smoke` is absent from the just command surface. |
| TEST-CONTRACT-04 | SATISFIED | Behavior tests cover command tiers, MCP contracts, result hydration, and embedding input boundaries. |

## Anti-Patterns Checked

| Anti-pattern | Result |
|--------------|--------|
| Skip-all live tests produce green builds | ABSENT; explicit e2e exits non-zero on missing runtime. |
| Local default tests depend on live services | ABSENT; local tests exclude `e2e` and `smoke`. |
| Old smoke command remains as ambiguous alias | ABSENT; `test-smoke` is removed. |
| Tests only assert private implementation trivia | ABSENT; updated tests assert observable contracts. |

## Human Verification Required

None for phase closure.

## Gaps Summary

No blocking gaps remain.

## Verification Metadata

- Verification type: goal-backward phase verification
- Evidence checked: plan, summary, justfile, README, e2e fixtures, pytest markers, behavior tests, current command surface
- Current checks run:
  - PASS: `just --list`
  - PASS: `! just --list | rg 'test-smoke'`
  - PASS: `test ! -d backend/tests/smoke`
  - PASS: `cd backend && uv run pytest tests/api/test_service_search.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/ingestion/test_pipeline_metadata.py -q` (`47 passed`)
- Historical phase checks: `23-01-test-contract-cleanup-SUMMARY.md` records `just test`, `just test-e2e`, and `just check` passing at phase completion.
