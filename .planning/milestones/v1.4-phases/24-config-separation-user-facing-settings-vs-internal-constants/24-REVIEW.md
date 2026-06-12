---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
reviewed: 2026-05-05T16:19:07Z
depth: standard
files_reviewed: 7
files_reviewed_list:
  - backend/src/dotmd/core/config.py
  - backend/tests/core/test_config_separation.py
  - .env.example
  - README.md
  - backend/start.sh
  - backend/src/dotmd/mcp_server.py
  - backend/src/dotmd/api/server.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
---

# Phase 24: Code Review Report

**Reviewed:** 2026-05-05T16:19:07Z
**Depth:** standard
**Files Reviewed:** 7
**Status:** clean

## Summary

Re-reviewed Phase 24 after fix commit `d7b879b2657ba715d8166ba567c3e0bde3148236`, focused on the prior review findings and a quick regression scan across the same runtime configuration surface. All previously reported Critical and Warning findings are resolved. No new correctness, security, or maintainability regressions were found in the reviewed scope.

## Review Cycle 2 Result

Previous findings:

- CR-01: BLOCKER - Runtime validation unsafe relative/wrong runtime paths - resolved. `Settings.validate_for_runtime()` now rejects relative `data_dir`, relative `index_dir`, relative `indexing_paths`, non-`/mnt` runtime data roots, and non-`/dotmd-index` runtime index directories.
- CR-02: BLOCKER - `.env.example` startup checks enabled by default - resolved. `.env.example` now leaves `DOTMD_RUN_STARTUP_CHECKS=true` commented out and documents it as an opt-in gate for deployments with the expected source bind mount.
- WR-01: WARNING - `/data` docs/template drift against `/mnt` production contract - resolved. `.env.example` and README now use `/mnt` and `["/mnt"]` for deployment-facing runtime configuration.
- WR-02: WARNING - brittle source-string runtime entrypoint test - resolved. The test now patches and executes the MCP stdio path and FastAPI lifespan path to assert both call `load_runtime_settings()` behaviorally.

Regression scan:

- `backend/src/dotmd/core/config.py` - runtime validator and path-spec helper reviewed.
- `backend/tests/core/test_config_separation.py` - behavioral regression tests reviewed.
- `.env.example` and `README.md` - deployment values reviewed for `/mnt` consistency and startup-gate default.
- `backend/start.sh` - gate behavior reviewed; default path still bypasses bind-mount-dependent checks unless explicitly enabled.
- `backend/src/dotmd/mcp_server.py` and `backend/src/dotmd/api/server.py` - runtime entry points reviewed for validated settings loading.

Verification run during re-review:

- `cd backend && uv run pytest tests/core/test_config_separation.py -q` - passed, `23 passed`.
- `cd backend && uv run ruff check src/dotmd/core/config.py tests/core/test_config_separation.py src/dotmd/mcp_server.py src/dotmd/api/server.py` - passed.
- `sh -n backend/start.sh` - passed.
- `rg -n '^DOTMD_RUN_STARTUP_CHECKS=' .env.example` - no uncommented default found.

All reviewed files meet quality standards. No issues found.

---

_Reviewed: 2026-05-05T16:19:07Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
