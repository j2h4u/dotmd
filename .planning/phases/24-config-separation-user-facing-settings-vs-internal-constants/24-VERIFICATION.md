---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
verified: 2026-05-05T16:24:30Z
status: passed
score: 15/15 must-haves verified
overrides_applied: 0
---

# Phase 24: Config Separation Verification Report

**Phase Goal:** Split `core/config.py` into explicit user-facing configuration versus internal tuning constants so production misconfiguration fails loudly instead of being hidden by Python defaults.
**Verified:** 2026-05-05T16:24:30Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

Phase 24 is achieved. The code keeps one public `Settings` surface, moves implementation defaults into named constants, adds explicit runtime validation for long-running service startup, wires that validation into MCP/FastAPI runtime entrypoints, preserves local test construction, preserves built-in indexing excludes through `effective_indexing_exclude`, and aligns `.env.example` plus README around the `/mnt` deployment contract and startup-check switch.

## Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | D-01: `Settings` remains the public dotMD configuration surface; Phase 24 does not add environment profiles | VERIFIED | `Settings` remains the single config class in `backend/src/dotmd/core/config.py`; no `DOTMD_ENV` or local/dev/staging/prod profile field found. |
| 2 | D-02: Deployment-bound values can fail loudly at startup without forcing every local unit test to look like production | VERIFIED | `validate_for_runtime()` rejects unsafe runtime paths and empty required values, while direct `Settings(embedding_url=...)` still constructs in tests. |
| 3 | D-03: Internal tuning defaults are named constants or grouped defaults, not undocumented operator checklist items | VERIFIED | Tuning constants such as `DEFAULT_FUSION_K`, `DEFAULT_RERANK_POOL_SIZE`, `DEFAULT_SNIPPET_LENGTH`, and `DEFAULT_POLL_INTERVAL_SECONDS` are module-level constants feeding compatibility fields. |
| 4 | D-04: `base_url=None` remains valid and disables remote OAuth | VERIFIED | `base_url: str \| None = None`; validator returns `None`; test `test_base_url_none_remains_valid` passes. |
| 5 | D-05: `falkordb_url` is required only when `graph_backend` is `falkordb`, and the unsafe Python default is rejected for FalkorDB runtime startup | VERIFIED | `validate_for_runtime()` rejects empty/default `falkordb_url` only in FalkorDB mode; tests cover FalkorDB rejection and LadybugDB acceptance. |
| 6 | D-06: Built-in indexing excludes cannot disappear silently when operator excludes are configured | VERIFIED | `DEFAULT_INDEXING_EXCLUDE`, `indexing_extra_exclude`, and `effective_indexing_exclude` preserve built-ins and append extras; consumed by service/trickle call sites. |
| 7 | D-07: Model and index identity values remain visible operator/index-identity configuration | VERIFIED | Identity fields remain `Settings` fields and are documented in `.env.example` and README under Index/search identity. |
| 8 | D-08: `indexing_exclude` has replace-only semantics, `indexing_extra_exclude` is additive, and `effective_indexing_exclude` prevents TOML list replacement from hiding built-in excludes | VERIFIED | Code comments state replace-only/additive semantics; property de-duplicates built-ins plus extras; tests cover additive behavior at a consumed call boundary. |
| 9 | D-09: Optional feature configuration stays optional; `base_url=None` disables remote OAuth and only non-empty `base_url` values validate strictly | VERIFIED | `validate_base_url()` accepts `None` and validates non-empty values for HTTPS/localhost. |
| 10 | D-13: The restart-time pre-flight gate in `backend/start.sh` is preserved, including ruff, pyright ratchet, live MCP `/health`, `tests/e2e/`, and non-zero exit on failure | VERIFIED | `backend/start.sh` still runs ruff, `devtools/pyright_ratchet.py`, background MCP server, `/health` polling, e2e pytest, and exits non-zero on failures. `sh -n backend/start.sh` passed. |
| 11 | D-14: The startup gate is documented as an operational safety switch, not a multi-environment profile model | VERIFIED | `backend/start.sh`, `.env.example`, and README describe `DOTMD_RUN_STARTUP_CHECKS` as a startup safety/pre-flight gate and explicitly say `ENVIRONMENT=dev` is not an environment profile system. |
| 12 | D-15: `DOTMD_RUN_STARTUP_CHECKS=true` is the primary startup-check switch and `ENVIRONMENT=dev` remains only as a temporary compatibility alias | VERIFIED | `backend/start.sh` gates on `DOTMD_RUN_STARTUP_CHECKS=true` first and accepts `ENVIRONMENT=dev` as legacy alias. |
| 13 | D-10: `.env.example` emphasizes operator/deployment config first and moves internal tuning to an advanced section | VERIFIED | `.env.example` starts with required deployment config, index/search identity, optional features, startup safety, then Advanced tuning. |
| 14 | D-11: README documents required runtime config, selected identity config, optional features, and advanced tuning separately | VERIFIED | README `## Configuration` contains the four requested groups with runtime, identity, optional, and tuning fields. |
| 15 | D-12: Additive indexing excludes are discoverable through `DOTMD_INDEXING_EXTRA_EXCLUDE`; legacy `DOTMD_INDEXING_EXCLUDE` is documented as replace-only | VERIFIED | `.env.example` and README both document additive extra excludes and legacy replace-only excludes. |

**Score:** 15/15 truths verified

## Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/core/config.py` | Public `Settings` surface plus internal defaults boundary | VERIFIED | Contains `DEFAULT_INDEXING_EXCLUDE`, `DEFAULT_FALKORDB_URL`, tuning constants, `effective_indexing_exclude`, `validate_for_runtime()`, and `load_runtime_settings()`. |
| `backend/tests/core/test_config_separation.py` | Focused config separation regression coverage | VERIFIED | Contains runtime validation, FalkorDB default safety, base URL optionality, effective excludes, and runtime-entrypoint tests. |
| `backend/start.sh` | Container startup check switch | VERIFIED | Contains `DOTMD_RUN_STARTUP_CHECKS`, `ENVIRONMENT=dev`, ruff, pyright ratchet, `/health` polling, and e2e pytest. |
| `.env.example` | Operator config template | VERIFIED | Required deployment config uses `/mnt`; startup checks are commented out by default; internal tuning is under Advanced tuning. |
| `README.md` | Configuration documentation | VERIFIED | Documents required deployment config, identity config, optional features, advanced tuning, FalkorDB runtime safety, and indexing exclude semantics. |

## Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Runtime settings construction | Container/server startup validation | `load_runtime_settings()` calls `validate_for_runtime()` | WIRED | `load_runtime_settings()` validates settings; MCP stdio, MCP HTTP, and FastAPI lifespan call it before serving. |
| `DOTMD_RUN_STARTUP_CHECKS` | Restart-time pre-flight gate | `backend/start.sh` condition | WIRED | Shell condition enables the gate for `DOTMD_RUN_STARTUP_CHECKS=true` or legacy `ENVIRONMENT=dev`; default skips bind-mount-dependent checks. |
| Effective excludes | Indexing discovery/watch call sites | `settings.effective_indexing_exclude` | WIRED | `DotMDService.status()` and trickle orphan/backlog/watchdog paths consume effective excludes. |

Note: `gsd-sdk verify.key-links` could not verify the two PLAN key links because those entries use symbolic `from` values instead of file paths. Manual wiring verification above passed.

## Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `backend/src/dotmd/core/config.py` | Runtime settings | `load_settings(**overrides)` plus env/TOML sources, then `validate_for_runtime()` | Yes | VERIFIED |
| `backend/src/dotmd/api/service.py` / `backend/src/dotmd/ingestion/trickle.py` | Exclude patterns | `Settings.effective_indexing_exclude` | Yes | VERIFIED |
| `.env.example` / `README.md` | Operator-facing config surface | Concrete documented env variables matching `Settings` fields | Yes | VERIFIED |

## Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Runtime validation rejects unsafe defaults and accepts explicit runtime values | `cd backend && uv run python - <<'PY' ...` | `unsafe_defaults_fail: PASS`, `default_falkordb_rejected: PASS`, `valid_runtime_accepts: PASS` | PASS |
| Focused config/base URL tests | `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` | `28 passed` | PASS |
| Effective-exclude integration tests | `cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q` | `19 passed` | PASS |
| Startup shell syntax and expected gate commands | `sh -n backend/start.sh && rg ... backend/start.sh` | Exit 0; expected strings found | PASS |
| Phase-scope ruff check | `cd backend && uv run ruff check src/dotmd/core/config.py ... tests/core/test_config_base_url.py` | `All checks passed!` | PASS |
| Local repository gate | `just check` | Ruff passed; pyright ratchet `76 errors (baseline 76)`; `277 passed, 30 deselected` | PASS |

## Requirements Coverage

No Phase 24 requirement IDs are mapped in `.planning/REQUIREMENTS.md`. Requirements coverage is not applicable.

## Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `docker-compose.yml` | 8 | Local compose still mounts sample data at `/data` while Phase 24 runtime docs/template use `/mnt` | INFO | Not a Phase 24 blocker: production contract and `.env.example` are `/mnt`, and the runtime validator fails loudly if a deployment uses the wrong path. Consider aligning local compose in a future deployment-doc cleanup if repo compose is meant to be copy-paste runnable with `.env.example`. |

No blocking TODO/FIXME/placeholder/stub patterns were found in Phase 24 modified runtime files.

## Human Verification Required

None. The phase goal is code/config/docs behavior and was verified with code inspection plus local commands. Production restart was intentionally not performed.

## Gaps Summary

No blocking gaps found. The phase goal is achieved: unsafe runtime defaults now fail loudly at long-running startup boundaries, built-in excludes are preserved through effective excludes, startup checks are renamed without losing the old alias, and the operator-facing docs/template separate required deployment config from advanced tuning.

---

_Verified: 2026-05-05T16:24:30Z_
_Verifier: the agent (gsd-verifier)_
