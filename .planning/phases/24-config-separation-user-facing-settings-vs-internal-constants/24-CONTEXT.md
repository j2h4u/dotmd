# Phase 24: Config separation - user-facing settings vs internal constants - Context

**Gathered:** 2026-05-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Separate dotMD's configuration surface from implementation defaults in
`backend/src/dotmd/core/config.py`.

This phase is about making the single live container deployment explicit and
hard to misconfigure. It is not a general environment-profile system and should
not introduce `dev/staging/prod` abstractions unless the code already needs
them for the existing container startup path.

</domain>

<decisions>
## Implementation Decisions

### Configuration Vocabulary

- **D-01:** Do not describe these values as "external settings." They are dotMD
  configuration. The useful distinction is:
  - operator / deployment-bound configuration: values supplied through env,
    TOML, or compose because they describe this concrete dotMD deployment;
  - internal defaults / constants: implementation behavior that should not look
    like required server configuration.
- **D-02:** Phase 24 should avoid adding an environment-profile abstraction.
  dotMD currently has one real operating environment: the running container on
  the server, used by the same person who develops it.

### Single Deployment Assumption

- **D-03:** Do not introduce `DOTMD_ENV=production`, `local/dev/prod` profiles,
  or a separate strict-mode framework in this phase.
- **D-04:** Container startup should fail loudly when required configuration for
  the one real deployment is missing or unsafe. Tests remain tests: they should
  provide explicit fixtures/overrides rather than relying on production-style
  config.
- **D-05:** Required deployment-bound config should cover values where a Python
  default can make the service appear healthy while using the wrong data,
  volume, model, or dependency.

### Operator / Deployment-Bound Configuration

- **D-06:** Keep these as user-facing configuration in `Settings` or an
  equivalent public config surface: `data_dir`, `index_dir`, `indexing_paths`,
  `indexing_exclude`, `embedding_url`, `embedding_model`, `graph_backend`,
  `falkordb_url` when FalkorDB is selected, `base_url`, `chunk_strategy`,
  `extract_depth`, `ner_model_name`, `reranker_name`, `reranker_model`,
  `reranker_compare_names`, `reranker_backend`, and `embedding_weights`.
- **D-07:** Model and index identity values are not just tuning knobs. Values
  such as `embedding_model`, `chunk_strategy`, `ner_model_name`,
  `reranker_model`, and `embedding_weights` affect cache keys, index
  compatibility, extraction cache validity, or ranking behavior. Missing or
  accidental defaults should be visible in container startup/docs.
- **D-08:** `indexing_exclude` needs explicit semantics, not only a
  required/not-required decision. The original failure mode was that TOML list
  overrides could hide Python defaults, so planning should decide whether
  excludes are replace-only, merged with built-in excludes, or split into
  built-in excludes plus user extra excludes.
- **D-09:** Optional feature configuration stays optional when `None` means the
  feature is disabled. `base_url=None` is valid because it disables remote OAuth;
  if set, it must still validate strictly.

### Internal Defaults and Tuning

- **D-10:** Tuning knobs that have never been used operationally should move
  deeper than the primary operator config surface. They may remain overridable
  for advanced experiments, but should not look like mandatory deployment
  settings.
- **D-11:** Candidates to move to internal constants or grouped defaults include
  `fusion_k`, `rerank_pool_size`, `default_top_k`, `snippet_length`,
  `semantic_score_floor`, `max_chunk_tokens`, `chunk_overlap_tokens`,
  `poll_interval_seconds`, `tei_batch_size`, `graph_max_hops`,
  `reranker_min_length`, and `reranker_length_penalty`.
- **D-12:** Documentation should still mention that fine-tuning is possible, but
  the main README/config template should emphasize the stable operator surface
  first and keep tuning in a clearly marked advanced section.

### Startup Smoke Gate

- **D-13:** Preserve the restart-time pre-flight gate in `backend/start.sh`.
  `ENVIRONMENT=dev` currently opts into ruff, pyright ratchet, live MCP server
  startup, `/health`, and `tests/e2e/`; this is valuable because dotMD is under
  continuous development and the container should not stay running after a bad
  restart.
- **D-14:** Treat this gate as an operational safety switch, not as a full
  multi-environment config model. Phase 24 may rename/document it if useful, but
  should not remove or bury it as a mere internal tuning knob.
- **D-15:** Prefer renaming the switch away from `ENVIRONMENT=dev` because that
  name implies environment profiles. Candidate names: `DOTMD_RUN_STARTUP_CHECKS`
  or `DOTMD_PREFLIGHT_CHECKS`. `DOTMD_RUN_STARTUP_CHECKS=true` is the clearest
  option because the gate runs lint/type/e2e startup checks, not just smoke
  tests. Keep `ENVIRONMENT=dev` as a temporary compatibility alias if the live
  compose override already uses it.

### the agent's Discretion

- Choose the smallest code shape that makes the boundary obvious. A single
  `Settings` class plus named constants and explicit validation may be enough;
  do not create a large config subsystem unless the implementation proves it is
  necessary.
- Choose exact naming for any constants modules or grouped defaults, as long as
  the public config surface becomes clear and documented.
- Decide whether legacy values such as `vector_backend` are still real
  operator config or should be marked/deprecated based on live code usage.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Definition

- `.planning/ROADMAP.md` - Phase 24 goal, scope, and backlog source 999.6.
- `.planning/STATE.md` - current workflow state and Phase 24 promotion note.
- `.planning/REQUIREMENTS.md` - broader v1.4 requirements context; no dedicated
  Phase 24 requirement is currently mapped.

### Config and Startup Surface

- `backend/src/dotmd/core/config.py` - current mixed `Settings` surface,
  validators, derived paths, and default values.
- `backend/start.sh` - container entrypoint and `ENVIRONMENT=dev` pre-flight
  smoke gate.
- `docker-compose.yml` - compose env-file loading, data/index volumes, TEI and
  FalkorDB service defaults.
- `.env.example` - current primary env template; currently mixes deployment
  values and tuning knobs.
- `README.md` - current configuration table and developer command docs.

### Test Contract

- `.planning/phases/23-fix-dotmd-test-contract/23-CONTEXT.md` - local tests
  must not require live containers or production data; explicit live e2e must
  fail when runtime is unavailable.
- `backend/tests/conftest.py` - current local-test settings injection boundary.
- `backend/tests/core/test_config_base_url.py` - existing focused config
  validation pattern.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `Settings` in `backend/src/dotmd/core/config.py` already centralizes env,
  TOML, and explicit override loading through `pydantic-settings`.
- Existing validators for `embedding_weights`, `reranker_relevance_floor`, and
  `base_url` show the local pattern for fail-fast config checks.
- `load_settings(**overrides)` is a potential construction boundary for adding
  explicit runtime validation without forcing every test to use production
  config.

### Established Patterns

- Public APIs and runtime entry points consume `Settings` through service,
  pipeline, CLI, MCP, and FastAPI layers.
- Derived paths such as `index_db_path`, `graph_db_path`, and `acronyms_path`
  are properties from `index_dir`; they should remain derived rather than
  becoming separate config fields.
- Tests already use fixtures/env overrides for cheap local construction instead
  of live TEI/FalkorDB.

### Integration Points

- `backend/start.sh` is the container startup point and the natural place to
  enforce startup-safety behavior for the live deployment.
- `.env.example` and `README.md` must be updated together with code so the
  documented config surface matches what `Settings` actually accepts.
- Search, ingestion, reranker, and graph code read many current fields directly
  from `settings`, so planning must account for call-site migration if fields
  move to constants.

</code_context>

<specifics>
## Specific Ideas

- Keep the main config template focused on the values a server operator must
  understand: mounted data, index volume, TEI URL/model, graph backend, indexing
  paths/excludes, OAuth base URL, and selected models/strategies.
- Put seldom-used tuning values in an advanced documentation section or an
  internal defaults module. They should remain discoverable for experiments but
  should not clutter the required deployment checklist.
- The term `ENVIRONMENT=dev` is misleading because the current live deployment
  uses it as a restart safety gate. Recommended replacement:
  `DOTMD_RUN_STARTUP_CHECKS=true`, with `DOTMD_PREFLIGHT_CHECKS=true` as an
  acceptable shorter alternative.

</specifics>

<deferred>
## Deferred Ideas

- A real multi-environment configuration model is deferred until dotMD actually
  has multiple operating environments.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` matched on
  FalkorDB/config keywords but remains its own graph-backend migration concern.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` matched
  on model/config keywords but remains embedding-model work.
- `2026-03-27-background-trickle-indexer.md` matched on index keywords but is
  not folded into this config-surface phase.
- `2026-03-27-smoke-tests.md` matched on TOML/testing keywords but Phase 23
  already handled the test-contract cleanup.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` matched on
  source keywords but is unrelated to config separation.

</deferred>

---

*Phase: 24-config-separation-user-facing-settings-vs-internal-constants*
*Context gathered: 2026-05-05*
