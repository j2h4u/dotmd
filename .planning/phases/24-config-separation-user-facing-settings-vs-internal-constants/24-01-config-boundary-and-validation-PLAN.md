---
phase: "24"
plan: "01-config-boundary-and-validation"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/config.py
  - backend/src/dotmd/ingestion/trickle.py
  - backend/src/dotmd/api/service.py
  - backend/tests/core/test_config_separation.py
  - backend/tests/core/test_config_base_url.py
autonomous: true
requirements: []
requirements_addressed: []
must_haves:
  truths:
    - "D-01: Settings remains the public dotMD configuration surface; Phase 24 does not add environment profiles"
    - "D-02: Deployment-bound values can fail loudly at startup without forcing every local unit test to look like production"
    - "D-03: Internal tuning defaults are named constants or grouped defaults, not undocumented operator checklist items"
    - "D-04: `base_url=None` remains valid and disables remote OAuth"
    - "D-05: `falkordb_url` is required only when `graph_backend` is `falkordb`, and the unsafe Python default `redis://localhost:6379` is rejected for FalkorDB runtime startup"
    - "D-06: Built-in indexing excludes cannot disappear silently when operator excludes are configured"
    - "D-07: Model and index identity values remain visible operator/index-identity configuration because they affect cache keys, index compatibility, extraction cache validity, or ranking behavior"
    - "D-08: `indexing_exclude` has explicit replace-only semantics, `indexing_extra_exclude` is additive, and `effective_indexing_exclude` prevents TOML list replacement from hiding built-in excludes"
    - "D-09: Optional feature configuration stays optional; `base_url=None` disables remote OAuth and only non-empty `base_url` values validate strictly"
  artifacts:
    - path: "backend/src/dotmd/core/config.py"
      provides: "public Settings surface plus internal defaults boundary"
      contains: "DEFAULT_INDEXING_EXCLUDE"
    - path: "backend/src/dotmd/core/config.py"
      provides: "FalkorDB runtime safety guard"
      contains: "DEFAULT_FALKORDB_URL"
    - path: "backend/tests/core/test_config_separation.py"
      provides: "focused config separation regression coverage"
      contains: "test_runtime_validation"
  key_links:
    - from: "load_settings"
      to: "container startup config validation"
      via: "validate_for_runtime"
      pattern: "require_runtime"
---

# Phase 24 Plan 01: Config Boundary and Validation

<objective>
Separate dotMD's operator-facing configuration from implementation defaults in
`backend/src/dotmd/core/config.py`, preserve the existing `Settings` public
surface, and add focused validation/tests so unsafe live deployment defaults
fail loudly without adding environment-profile abstractions.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| The container starts healthy against the wrong data or index volume | HIGH | Add explicit runtime validation for `data_dir`, `index_dir`, and `indexing_paths` through a startup-facing settings construction path. |
| Phase 24 accidentally creates `dev/staging/prod` profiles | HIGH | Keep one `Settings` class and one runtime validation mode; do not add `DOTMD_ENV` or profile-specific defaults. |
| TOML list replacement hides built-in excludes again | HIGH | Define built-in excludes separately and make call sites consume an effective exclude list. |
| Tests become dependent on live TEI/FalkorDB or production paths | HIGH | Keep direct `Settings(...)` and `load_settings(**overrides)` usable with explicit test fixtures; do not require runtime validation for unit construction. |
| Optional OAuth is forced on | MEDIUM | Keep `base_url=None` valid; validate only when a value is provided. |
| FalkorDB URL becomes mandatory for LadybugDB local usage | MEDIUM | Validate `falkordb_url` conditionally only when `graph_backend == "falkordb"`. |
| FalkorDB runtime startup silently uses `redis://localhost:6379` | HIGH | Define `DEFAULT_FALKORDB_URL = "redis://localhost:6379"` and reject that default when `graph_backend == "falkordb"` in `validate_for_runtime()`. |
| Internal tuning values disappear from call sites unexpectedly | MEDIUM | Keep compatibility properties/fields where call sites still read `settings.*`; assign defaults from named constants before migrating broader API shape. |
</threat_model>

<tasks>
<task id="1" type="auto">
<name>Task 1: Add config separation constants and runtime validation tests</name>
<read_first>
- `backend/src/dotmd/core/config.py`
- `backend/tests/core/test_config_base_url.py`
- `backend/tests/conftest.py`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-CONTEXT.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-RESEARCH.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/core/config.py`
- `backend/tests/core/test_config_separation.py`
</files>
<action>
Create focused RED tests in `backend/tests/core/test_config_separation.py` before
changing production code.

Add tests for these exact contracts:

1. `Settings(embedding_url="http://localhost:8088")` still constructs for unit
   tests and has current defaults for compatibility.
2. `dotmd.core.config.DEFAULT_INDEXING_EXCLUDE` exists and contains
   `"**/node_modules"`, `"**/.git"`, `"**/__pycache__"`, and `"**/.cache"`.
3. `Settings(...).effective_indexing_exclude` includes all
   `DEFAULT_INDEXING_EXCLUDE` entries when no operator extras are supplied.
4. Operator extra excludes are additive: constructing with
   `indexing_extra_exclude=["**/private"]` makes
   `effective_indexing_exclude` contain both `"**/.git"` and `"**/private"`.
5. `dotmd.core.config.DEFAULT_FALKORDB_URL` exists and equals
   `"redis://localhost:6379"`.
6. Runtime validation fails when `data_dir` is `"."`, `index_dir` is
   `Path.home() / ".dotmd"`, or `indexing_paths=[]`. Use the method or helper
   name `validate_for_runtime()` in the test expectation.
7. Runtime validation accepts explicit deployment values:
   `data_dir=Path("/mnt")`, `index_dir=Path("/dotmd-index")`,
   `indexing_paths=["/mnt"]`, `embedding_url="http://tei:80"`,
   `embedding_model="BAAI/bge-small-en-v1.5"`,
   `chunk_strategy="heading_512_50"`, `extract_depth=ExtractDepth.NER`,
   `ner_model_name="urchade/gliner_multi-v2.1"`,
   `reranker_name="mmarco-minilm"`,
   `reranker_model="cross-encoder/mmarco-mMiniLMv2-L12-H384-v1"`,
   `reranker_backend="cross_encoder"`, and
   `embedding_weights="text=0.7,meta=0.3"`.
   `falkordb_url="redis://falkordb:6379"`.
8. Runtime validation fails for `graph_backend="falkordb"` with either
   `falkordb_url=""` or `falkordb_url=DEFAULT_FALKORDB_URL`.
9. Runtime validation passes for `graph_backend="ladybugdb"` with
   `falkordb_url=""` and with `falkordb_url=DEFAULT_FALKORDB_URL`.
10. `base_url=None` remains valid.

The first test run should fail on missing `DEFAULT_INDEXING_EXCLUDE`,
`indexing_extra_exclude`, `effective_indexing_exclude`, and
`validate_for_runtime`.
</action>
<verify>
<automated>cd backend && uv run pytest tests/core/test_config_separation.py -q</automated>
<automated>cd backend && uv run ruff check tests/core/test_config_separation.py</automated>
</verify>
<acceptance_criteria>
- `backend/tests/core/test_config_separation.py` contains `test_runtime_validation`.
- `backend/tests/core/test_config_separation.py` contains `DEFAULT_INDEXING_EXCLUDE`.
- `backend/tests/core/test_config_separation.py` contains `DEFAULT_FALKORDB_URL`.
- `backend/tests/core/test_config_separation.py` contains `effective_indexing_exclude`.
- `backend/tests/core/test_config_separation.py` contains `indexing_extra_exclude`.
- `backend/tests/core/test_config_separation.py` asserts `redis://localhost:6379` fails when `graph_backend="falkordb"`.
- `backend/tests/core/test_config_separation.py` asserts `base_url is None`.
- The initial test run fails before Task 2 because production code has not implemented the new contract.
</acceptance_criteria>
<done>
The phase has focused failing tests for the config boundary and runtime validation contract.
</done>
</task>

<task id="2" type="auto">
<name>Task 2: Implement the Settings boundary and effective defaults</name>
<read_first>
- `backend/src/dotmd/core/config.py`
- `backend/tests/core/test_config_separation.py`
- `backend/tests/conftest.py`
</read_first>
<files>
- `backend/src/dotmd/core/config.py`
- `backend/tests/core/test_config_separation.py`
- `backend/tests/core/test_config_base_url.py`
</files>
<action>
Refactor `backend/src/dotmd/core/config.py` using the smallest shape that makes
the boundary explicit.

Add module-level constants for internal defaults:

- `DEFAULT_INDEXING_EXCLUDE: tuple[str, ...]` with the current built-in exclude
  patterns: `"**/node_modules"`, `"**/.git"`, `"**/__pycache__"`,
  `"**/.pytest_cache"`, `"**/.ruff_cache"`, `"**/.mypy_cache"`, `"**/.tox"`,
  `"**/.nox"`, `"**/.venv"`, `"**/venv"`, `"**/dist"`, `"**/build"`,
  `"**/.cache"`.
- `DEFAULT_FALKORDB_URL = "redis://localhost:6379"` and use it as the
  `Settings.falkordb_url` default.
- `DEFAULT_MAX_CHUNK_TOKENS = 512`
- `DEFAULT_CHUNK_OVERLAP_TOKENS = 50`
- `DEFAULT_TEI_BATCH_SIZE = 4`
- `DEFAULT_DEFAULT_TOP_K = 10`
- `DEFAULT_FUSION_K = 60`
- `DEFAULT_RERANK_POOL_SIZE = 20`
- `DEFAULT_SEMANTIC_SCORE_FLOOR = 0.85`
- `DEFAULT_SNIPPET_LENGTH = 300`
- `DEFAULT_POLL_INTERVAL_SECONDS = 3600.0`
- `DEFAULT_GRAPH_MAX_HOPS = 2`
- `DEFAULT_RERANKER_MIN_LENGTH = 50`
- `DEFAULT_RERANKER_LENGTH_PENALTY = True`

Update `Settings` so internal tuning fields default from those constants. Keep
the field names for compatibility in Phase 24; do not migrate the whole codebase
to a new settings object.

Add `indexing_extra_exclude: list[str] = []`.

Keep `indexing_exclude` as a backwards-compatible operator override field, but
make its semantics explicit in code comments:

- `indexing_exclude` is legacy replace-only config.
- `indexing_extra_exclude` is the preferred additive operator config.
- `effective_indexing_exclude` is the list call sites should use.

Implement:

```python
@property
def effective_indexing_exclude(self) -> list[str]:
    ...
```

The property must return a de-duplicated list preserving order:

- If `indexing_exclude` is non-empty, start with `indexing_exclude`;
  otherwise start with `DEFAULT_INDEXING_EXCLUDE`.
- Append `indexing_extra_exclude`.
- Remove duplicate strings while preserving first occurrence.

Add:

```python
def validate_for_runtime(self) -> None:
    ...
```

This method must raise `ValueError` with field names in the message when:

- `data_dir == Path(".")`
- `index_dir == Path.home() / ".dotmd"`
- `indexing_paths` is empty
- `embedding_url` is empty
- any of `embedding_model`, `chunk_strategy`, `ner_model_name`,
  `reranker_name`, `reranker_model`, `reranker_backend`, or
  `embedding_weights` is explicitly empty. Do not reject the selected Python
  defaults for these identity fields as unsafe; visibility for selected
  defaults is handled by `.env.example` and README in Plan 02.
- `graph_backend == "falkordb"` and `falkordb_url` is empty
- `graph_backend == "falkordb"` and `falkordb_url == DEFAULT_FALKORDB_URL`
  (`"redis://localhost:6379"`). This is a blocking deployment safety check:
  the unsafe Python default must not pass in FalkorDB runtime mode.

Do not make `base_url` required. Do not add `DOTMD_ENV`, `production`, `dev`,
`staging`, or profile-specific settings.

Add a helper:

```python
def load_runtime_settings(**overrides: object) -> Settings:
    settings = load_settings(**overrides)
    settings.validate_for_runtime()
    return settings
```

Keep `load_settings(**overrides)` unchanged as the general construction helper.
</action>
<verify>
<automated>cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q</automated>
<automated>cd backend && uv run ruff check src/dotmd/core/config.py tests/core/test_config_separation.py tests/core/test_config_base_url.py</automated>
<automated>cd backend && uv run pyright src/dotmd/core/config.py tests/core/test_config_separation.py tests/core/test_config_base_url.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/core/config.py` contains `DEFAULT_INDEXING_EXCLUDE`.
- `backend/src/dotmd/core/config.py` contains `DEFAULT_FALKORDB_URL = "redis://localhost:6379"`.
- `backend/src/dotmd/core/config.py` contains `indexing_extra_exclude`.
- `backend/src/dotmd/core/config.py` contains `def effective_indexing_exclude`.
- `backend/src/dotmd/core/config.py` contains `def validate_for_runtime`.
- `backend/src/dotmd/core/config.py` contains `def load_runtime_settings`.
- `backend/src/dotmd/core/config.py` does not contain `DOTMD_ENV`.
- `backend/src/dotmd/core/config.py` rejects `DEFAULT_FALKORDB_URL` when `graph_backend == "falkordb"`.
- `backend/src/dotmd/core/config.py` does not contain a `Literal["local", "dev", "staging", "prod", "production"]` profile field.
- `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` exits 0.
- `cd backend && uv run ruff check src/dotmd/core/config.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` exits 0.
- `cd backend && uv run pyright src/dotmd/core/config.py tests/core/test_config_separation.py tests/core/test_config_base_url.py` exits 0.
</acceptance_criteria>
<done>
The config module exposes a clear public settings surface, internal default constants, effective excludes, and runtime validation.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Migrate call sites to effective excludes and runtime settings where appropriate</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/trickle.py`
- `backend/src/dotmd/api/server.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/src/dotmd/cli.py`
- `backend/src/dotmd/core/config.py`
- `backend/tests/core/test_config_separation.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/trickle.py`
- `backend/src/dotmd/api/server.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/src/dotmd/cli.py`
- `backend/tests/core/test_config_separation.py`
</files>
<action>
Update runtime call sites narrowly:

1. In `backend/src/dotmd/ingestion/trickle.py`, replace every call that passes
   `self._settings.indexing_exclude` into path discovery or watcher filtering
   with `self._settings.effective_indexing_exclude`.
2. In `backend/src/dotmd/api/service.py`, replace indexing path discovery usage
   of `self._settings.indexing_exclude` with
   `self._settings.effective_indexing_exclude`.
3. In the container/server startup path only, use `load_runtime_settings()` so
   the live service fails before serving when runtime-required values are
   missing. The runtime-validation target is both long-running MCP server
   paths:
   - `backend/src/dotmd/mcp_server.py` `create_app()` for streamable-HTTP MCP
     container startup.
   - `backend/src/dotmd/mcp_server.py` `init_service()` for stdio MCP sessions
     launched through `docker exec dotmd dotmd mcp`.

   Check `backend/src/dotmd/api/server.py` and `backend/src/dotmd/cli.py` for
   any additional long-running serving path that constructs `Settings`, but do
   not broaden validation to short-lived CLI maintenance commands unless they
   serve live traffic.

Do not call `load_runtime_settings()` inside every CLI command. Development CLI
commands and tests should continue to use explicit overrides and `load_settings`
unless they are the long-running server path.

Add or adjust tests to prove effective excludes are consumed by at least one
call boundary. A mock-based test is acceptable if it asserts that the value
passed to discovery/filtering contains both `"**/.git"` and an extra exclude
from `indexing_extra_exclude=["**/private"]`.

Add runtime-path coverage for stdio MCP construction. A focused test may mock
`load_runtime_settings()` in `backend/src/dotmd/mcp_server.py` and assert that
`init_service()` calls it, while a separate check asserts `create_app()` also
uses the same helper. The test must not require a live MCP client, TEI, or
FalkorDB container.
</action>
<verify>
<automated>rg --no-heading "indexing_exclude" backend/src/dotmd/api/service.py backend/src/dotmd/ingestion/trickle.py</automated>
<automated>cd backend && uv run pytest tests/core/test_config_separation.py -q</automated>
<automated>cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q</automated>
<automated>cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py</automated>
<automated>cd backend && uv run pyright src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/trickle.py` contains `effective_indexing_exclude`.
- `backend/src/dotmd/api/service.py` contains `effective_indexing_exclude`.
- Runtime server construction imports or calls `load_runtime_settings`.
- `backend/src/dotmd/mcp_server.py` uses `load_runtime_settings()` in both `init_service()` and `create_app()`.
- No call site invokes `load_settings()` from inside a search method.
- A test proves effective excludes include both `"**/.git"` and `"**/private"` at a consumed call boundary.
- A test or grep-verifiable assertion proves the stdio MCP path (`init_service()`) uses runtime validation.
- `cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
<done>
Runtime services use the explicit config boundary and indexing call sites consume effective excludes.
</done>
</task>
</tasks>

<verification>
Run these commands after completing all tasks in this plan:

```bash
cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q
cd backend && uv run pytest tests/ingestion/test_trickle_metrics.py tests/api/test_service_search.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py tests/core/test_config_base_url.py
cd backend && uv run pyright src/dotmd/core/config.py src/dotmd/api/service.py src/dotmd/ingestion/trickle.py src/dotmd/api/server.py src/dotmd/mcp_server.py src/dotmd/cli.py tests/core/test_config_separation.py tests/core/test_config_base_url.py
```
</verification>

<success_criteria>
- `Settings` remains the public config surface and no environment-profile system is introduced.
- Runtime validation exists and fails loudly for missing deployment-bound values.
- Internal tuning defaults are named constants.
- Built-in indexing excludes remain effective when operator extras are configured.
- Local tests can still construct settings with explicit overrides.
</success_criteria>

## PLANNING COMPLETE
