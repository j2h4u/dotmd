# Phase 24: Pattern Map

**Mapped:** 2026-05-05
**Status:** Complete

## Target Files and Existing Patterns

### `backend/src/dotmd/core/config.py`

Role: central `pydantic-settings` boundary for env, TOML, and explicit
overrides.

Patterns to reuse:

- Keep all public runtime config reachable through `Settings` or
  `load_settings(**overrides)`.
- Use `field_validator` for fail-fast value validation, as already done for
  `embedding_weights`, `reranker_relevance_floor`, and `base_url`.
- Keep derived paths as properties from `index_dir`; do not turn
  `index_db_path`, `graph_db_path`, `sqlite_path`, or `acronyms_path` into env
  fields.
- Keep TOML/env source ordering in `settings_customise_sources`.

Important current code shape:

```python
class Settings(BaseSettings):
    model_config = {
        "env_prefix": "DOTMD_",
        "toml_file": str(Path.home() / ".dotmd" / "config.toml"),
    }
```

```python
def load_settings(**overrides: object) -> Settings:
    return Settings(**overrides)  # type: ignore[call-arg]
```

### `backend/src/dotmd/ingestion/trickle.py`

Role: background indexing loop that consumes `indexing_paths`,
`indexing_exclude`, and `poll_interval_seconds`.

Patterns to preserve:

- Do not index when `settings.indexing_paths` is empty.
- Keep indexing lock behavior through `indexing_lock(self._settings.index_dir)`.
- Use a single effective exclude list in watcher and indexing calls so the
  built-in ignore patterns and operator additions cannot diverge.

### `backend/src/dotmd/api/service.py`

Role: service facade and indexing/search orchestration.

Patterns to preserve:

- Service stores settings once as `self._settings`; do not reload indexes or
  settings per request.
- Search tuning values are read from `self._settings` in one service instance:
  `semantic_score_floor`, `tei_batch_size`, `rerank_pool_size`,
  `snippet_length`, `fusion_k`, and parsed reranker/model lists.
- Indexing path discovery currently passes `indexing_paths` and
  `indexing_exclude`; this should switch to an effective excludes property if
  Phase 24 adds one.

### `backend/start.sh`

Role: container entrypoint and restart-time pre-flight gate.

Patterns to preserve:

- Single serving command:
  `dotmd mcp --transport streamable-http --host 0.0.0.0 --port 8080`.
- When the safety gate is enabled, run ruff, pyright ratchet, start the MCP
  server in background, wait for `/health`, then run `tests/e2e/`.
- If the gate fails, kill the background server and exit non-zero.

Change pattern:

- Replace primary switch text from `ENVIRONMENT=dev` to
  `DOTMD_RUN_STARTUP_CHECKS=true`.
- Keep `ENVIRONMENT=dev` as a compatibility alias in the shell condition.

### `.env.example` and `README.md`

Role: operator-facing config template and docs.

Patterns to preserve:

- `.env.example` is the concrete copy-to-`.env` template.
- README's configuration section is a table of `DOTMD_` variables and defaults.

Change pattern:

- Split the visible config surface into required deployment values, selected
  index/search identity values, optional features, and advanced tuning.
- Avoid calling internal tuning values required server configuration.

### Tests

Closest existing tests:

- `backend/tests/core/test_config_base_url.py` shows focused `Settings`
  validation tests with direct `Settings(...)` construction.
- `backend/tests/conftest.py` shows explicit test env injection for required
  runtime fields and should stay the local test boundary.

Recommended new/changed tests:

- Add `backend/tests/core/test_config_separation.py` for constants, effective
  excludes, runtime validation, and graph URL conditional validation.
- Extend `test_config_base_url.py` only if base URL validation changes.

## PATTERN MAPPING COMPLETE
