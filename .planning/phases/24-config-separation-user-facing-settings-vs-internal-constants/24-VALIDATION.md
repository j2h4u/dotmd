---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
slug: config-separation-user-facing-settings-vs-internal-constants
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06T21:41:18+05:00
validation_state: reconstructed-from-summaries
gaps_found: 0
gaps_resolved: 0
manual_only: 0
---

# Phase 24 - Validation Strategy

> Retroactive Nyquist validation for the completed configuration-boundary and startup-template phase.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` |
| Full phase command | `just check` |
| Lint command | `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` |
| Estimated runtime | about 20 seconds |

## Discovery

Phase 24 had no pre-existing `24-VALIDATION.md`, so this file reconstructs the validation contract from:

- `24-01-config-boundary-and-validation-PLAN.md`
- `24-01-config-boundary-and-validation-SUMMARY.md`
- `24-02-startup-docs-and-template-PLAN.md`
- `24-02-startup-docs-and-template-SUMMARY.md`
- `24-VERIFICATION.md`
- `24-SECURITY.md`
- Current config, startup, docs, template, and focused tests

Phase 24 has no mapped `.planning/REQUIREMENTS.md` requirement IDs. Validation is therefore keyed to the phase's declared observable truths and task-level acceptance criteria.

## Gap Analysis

No Nyquist validation gaps remain. Existing focused tests cover the executable runtime validation and effective-exclude behavior; shell/doc grep checks cover startup and operator-facing template/doc contracts.

| Contract | Coverage |
|----------|----------|
| Config boundary | `tests/core/test_config_separation.py` covers exported defaults, direct `Settings(...)` construction, additive `indexing_extra_exclude`, `effective_indexing_exclude`, `base_url=None`, runtime validation, FalkorDB default rejection, LadybugDB acceptance, and runtime entrypoint wiring. |
| Startup safety switch | `backend/start.sh` passes shell syntax validation and contains `DOTMD_RUN_STARTUP_CHECKS`, `ENVIRONMENT=dev`, ruff, pyright ratchet, `/health`, and e2e pytest gate commands. |
| Operator docs/template | `.env.example` and README contain required deployment config, index/search identity, optional features, startup safety, advanced tuning, additive vs replace-only indexing excludes, and `DOTMD_SEMANTIC_SCORE_FLOOR=0.85`. |
| Integration surfaces | `tests/ingestion/test_trickle_metrics.py` and `tests/api/test_service_search.py` cover call sites consuming effective excludes. `just check` confirms the full local gate. |

## Per-Task Verification Map

| Task ID | Plan | Wave | Contract | Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|----------|----------|-----------|-------------------|-------------|--------|
| 24-01-01 | 01 | 1 | Config boundary tests | Focused tests cover `DEFAULT_INDEXING_EXCLUDE`, `DEFAULT_FALKORDB_URL`, `indexing_extra_exclude`, `effective_indexing_exclude`, `validate_for_runtime()`, FalkorDB default rejection, and `base_url=None`. | unit | `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` | yes | green |
| 24-01-02 | 01 | 1 | Settings implementation | `Settings` keeps one public surface, named constants feed compatibility fields, runtime validation is opt-in through `load_runtime_settings()`, and no profile model is introduced. | unit + static check | `cd backend && uv run ruff check src/dotmd/core/config.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` | yes | green |
| 24-01-03 | 01 | 1 | Runtime/effective exclude wiring | Long-running MCP/FastAPI startup paths use `load_runtime_settings()`; service/trickle paths consume `effective_indexing_exclude`. | unit/integration-style unit | `cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q` | yes | green |
| 24-02-01 | 02 | 2 | Startup pre-flight switch | Startup gate preserves ruff, pyright ratchet, background server health polling, e2e pytest, and non-zero failure behavior while naming `DOTMD_RUN_STARTUP_CHECKS` first. | shell/static check | `sh -n backend/start.sh && rg --no-heading "DOTMD_RUN_STARTUP_CHECKS\|ENVIRONMENT=dev\|ruff check\|pyright_ratchet\|tests/e2e" backend/start.sh` | yes | green |
| 24-02-02 | 02 | 2 | Env template | `.env.example` separates required deployment config, identity, optional features, startup safety, and advanced tuning; additive excludes are discoverable and stale score floor `0.4` is absent. | artifact check | `rg --no-heading "Required deployment configuration\|Advanced tuning\|DOTMD_INDEXING_EXTRA_EXCLUDE\|DOTMD_SEMANTIC_SCORE_FLOOR=0.85" .env.example && ! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0\\.4" .env.example` | yes | green |
| 24-02-03 | 02 | 2 | README docs | README documents required deployment config, index/search identity, optional features, advanced tuning, FalkorDB runtime safety, indexing exclude semantics, and startup-check semantics. | artifact check | `rg --no-heading "Required deployment configuration\|Advanced tuning\|DOTMD_INDEXING_EXTRA_EXCLUDE\|DOTMD_RUN_STARTUP_CHECKS" README.md` | yes | green |

## Wave 0 Requirements

Existing pytest infrastructure covers all executable Phase 24 behavior. Documentation and template contracts are validated with explicit grep/shell checks because the behavior is artifact content rather than runtime code.

## Manual-Only Verifications

All current Phase 24 closure behavior has automated verification or artifact checks. Production restart was intentionally not performed during validation; Phase 24's startup gate is verified by shell syntax, expected command presence, and focused runtime-setting tests.

## Commands Run

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` | PASS: 28 passed, 26 warnings |
| `cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q` | PASS: 29 passed, 21 warnings |
| `sh -n backend/start.sh && rg --no-heading "DOTMD_RUN_STARTUP_CHECKS\|ENVIRONMENT=dev\|ruff check\|pyright_ratchet\|tests/e2e\|Required deployment configuration\|Advanced tuning\|DOTMD_INDEXING_EXTRA_EXCLUDE\|DOTMD_SEMANTIC_SCORE_FLOOR=0.85" backend/start.sh .env.example README.md && ! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0\\.4\|DOTMD_ENV" .env.example README.md backend/start.sh backend/src/dotmd/core/config.py` | PASS |
| `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` | PASS |
| `just check` | PASS: ruff passed; pyright ratchet 69 errors, baseline 69; 332 passed, 36 deselected |
| `gsd-sdk query validate.health` | PASS: healthy |

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |

## Validation Sign-Off

- [x] All tasks have automated verification or artifact checks
- [x] Sampling continuity restored retroactively
- [x] Wave 0 covers all missing references
- [x] No watch-mode flags
- [x] Feedback latency under 10 seconds for the focused phase suites
- [x] `nyquist_compliant: true` set in frontmatter

Approval: approved 2026-05-06
