---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
reviewed: 2026-05-05T16:13:56Z
depth: standard
files_reviewed: 8
files_reviewed_list:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/ingestion/trickle.py
  - backend/src/dotmd/api/service.py
  - backend/start.sh
  - .env.example
  - README.md
  - backend/tests/core/test_config_separation.py
  - backend/tests/core/test_config_base_url.py
findings:
  critical: 2
  warning: 2
  info: 0
  total: 4
status: issues_found
---

# Phase 24: Code Review Report

**Reviewed:** 2026-05-05T16:13:56Z
**Depth:** standard
**Files Reviewed:** 8
**Status:** issues_found

## Summary

Reviewed the Phase 24 configuration boundary, effective indexing excludes, startup gate switch, docs/template changes, and focused config tests. The implementation compiles and targeted tests pass, but the runtime validation still permits unsafe deployment paths and the example environment now breaks the documented Docker quick-start by enabling startup checks without the required source bind mount.

Verification run during review:

- `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` - passed, `21 passed`.
- `cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` - passed.
- `sh -n backend/start.sh` - passed.

## Critical Issues

### CR-01: BLOCKER - Runtime Validation Still Allows Unsafe Runtime Paths

**File:** `backend/src/dotmd/core/config.py:283`

**Issue:** `validate_for_runtime()` only rejects `data_dir == Path(".")`, `index_dir == Path.home() / ".dotmd"`, and an empty `indexing_paths` list. Relative or wrong absolute runtime paths such as `data_dir=Path("data")`, `index_dir=Path("idx")`, or `indexing_paths=["data"]` pass validation, so a long-running server can still start healthy against the wrong source root or index location. This misses the phase's main safety goal and the project rule that production `DOTMD_DATA_DIR` must not be accidentally narrowed.

**Fix:**

```python
def validate_for_runtime(self) -> None:
    errors: list[str] = []
    if not self.data_dir.is_absolute():
        errors.append("data_dir must be absolute for runtime startup")
    if not self.index_dir.is_absolute():
        errors.append("index_dir must be absolute for runtime startup")
    if not self.indexing_paths:
        errors.append("indexing_paths must not be empty for runtime startup")
    for path_spec in self.indexing_paths:
        root = Path(path_spec.split("*", 1)[0] or path_spec)
        if not root.is_absolute():
            errors.append("indexing_paths must contain absolute paths for runtime startup")
            break
    ...
```

Add regression tests that `data_dir=Path("data")`, `index_dir=Path("idx")`, and `indexing_paths=["data"]` fail runtime validation. If the production contract is strictly `/mnt`, add an explicit `/mnt` check or a production deployment test against the live env template.

### CR-02: BLOCKER - Example Env Enables Startup Gate That Refuses The Documented Compose Path

**File:** `.env.example:52`

**Issue:** `.env.example` now sets `DOTMD_RUN_STARTUP_CHECKS=true` by default. README Quick Start tells users to copy `.env.example` to `.env`, and `docker-compose.yml` loads that file, but the compose service does not bind-mount the source tree at `/mnt/home/repos/j2h4u/dotmd/backend`. With this template copied, `backend/start.sh` reaches the guard at lines 30-33 and exits before serving. This makes the documented local compose path fail.

**Fix:**

```dotenv
# -- Startup safety ---------------------------------------------------------
# Run restart-time lint/type/live-MCP e2e checks before serving. Enable only in
# deployments that bind-mount the source tree expected by backend/start.sh.
# DOTMD_RUN_STARTUP_CHECKS=true
```

Alternatively set `DOTMD_RUN_STARTUP_CHECKS=false` in the example and keep the true value only in the live deployment override that has the required bind mount.

## Warnings

### WR-01: WARNING - Template And README Conflict With The Production Data Root Contract

**File:** `.env.example:12`

**Issue:** The project instructions say production `DOTMD_DATA_DIR` is locked to `/mnt` and must never be narrowed, but `.env.example` and README document `/data` and `["/data"]` as the required deployment values. That drift increases the chance of copying the template into the real deployment and indexing only a mounted subdirectory instead of the intended source root.

**Fix:** Split local compose examples from production deployment values. For production-facing docs/templates, use `DOTMD_DATA_DIR=/mnt` and `DOTMD_INDEXING_PATHS=["/mnt"]`; keep `/data` only in a clearly labeled bundled local compose example if that path is still needed.

### WR-02: WARNING - Runtime Entrypoint Coverage Uses Source-String Assertions

**File:** `backend/tests/core/test_config_separation.py:171`

**Issue:** `test_mcp_runtime_paths_use_runtime_settings_helper()` checks `inspect.getsource()` for the literal string `load_runtime_settings()`. This does not execute the MCP startup paths, misses the FastAPI runtime path, and would pass if the helper call exists in dead code or is wrapped incorrectly. It also did not catch the `.env.example` startup-gate regression.

**Fix:** Replace the source-string assertion with behavioral tests that patch `dotmd.mcp_server.load_runtime_settings` and `dotmd.api.server.load_runtime_settings`, then call `init_service()` and the server lifespan enough to assert the patched helper is used. Add a separate template/startup test that verifies the default `.env.example` does not enable the bind-mount-dependent gate.

---

_Reviewed: 2026-05-05T16:13:56Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
