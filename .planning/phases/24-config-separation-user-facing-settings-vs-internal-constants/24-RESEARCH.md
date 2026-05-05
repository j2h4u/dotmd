# Phase 24: Config separation - Research

**Researched:** 2026-05-05
**Status:** Complete

## Research Question

What does the executor need to know to plan Phase 24 well: separating dotMD's
operator-facing configuration from internal defaults/constants without adding a
multi-environment framework?

## Key Findings

### Current Configuration Shape

- `backend/src/dotmd/core/config.py` has one `Settings` class that mixes:
  - deployment identity and dependency values: `data_dir`, `index_dir`,
    `indexing_paths`, `embedding_url`, `embedding_model`, `graph_backend`,
    `falkordb_url`, `base_url`;
  - index/search identity values: `chunk_strategy`, `extract_depth`,
    `ner_model_name`, `reranker_name`, `reranker_model`,
    `reranker_compare_names`, `reranker_backend`, `embedding_weights`;
  - internal tuning values: `fusion_k`, `rerank_pool_size`, `default_top_k`,
    `snippet_length`, `semantic_score_floor`, `max_chunk_tokens`,
    `chunk_overlap_tokens`, `poll_interval_seconds`, `tei_batch_size`,
    `graph_max_hops`, `reranker_min_length`, `reranker_length_penalty`.
- `embedding_url` is already required and tests explicitly inject
  `DOTMD_EMBEDDING_URL`, which proves the repo has an accepted pattern for
  fail-loud config plus explicit test fixtures.
- `load_settings(**overrides)` is the best boundary for adding a runtime
  validation mode because it is already used by API, CLI, and MCP entrypoints
  and avoids per-request index loading.

### Required vs Defaulted Fields

Phase 24 should not make every listed setting constructor-required. That would
turn internal convenience defaults into noisy test friction and does not match
the one-container deployment. The useful shape is:

- Keep `Settings` as the public operator surface.
- Introduce explicit deployment validation for values where an unsafe Python
  default can make the live container start against the wrong data, volume,
  model, or dependency.
- Keep safe optional values optional (`base_url=None`) and validate strictly
  when set.
- Move internal tuning defaults into named constants or a grouped defaults
  structure, then assign `Settings` defaults from those constants where call
  sites still read through `settings`.

Recommended runtime-required checks for the container path:

- `data_dir` must be explicitly configured and should equal `/data` or `/mnt`
  depending on the current deployment mount contract.
- `index_dir` must be explicitly configured and should point at `/dotmd-index`.
- `indexing_paths` must be explicit when trickle indexing is expected; an empty
  list should remain valid only for deliberate CLI/test construction. Because
  `indexing_paths` is `list[str]`, env examples should use JSON syntax such as
  `DOTMD_INDEXING_PATHS=["/data"]`.
- `embedding_url` is already required and should stay required.
- `embedding_model`, `chunk_strategy`, `extract_depth`, `ner_model_name`,
  `reranker_name`, `reranker_model`, `reranker_backend`, and
  `embedding_weights` should stay visible operator/index-identity values, with
  defaults documented as selected defaults rather than hidden production facts.
- `falkordb_url` should be required/validated when `graph_backend="falkordb"`,
  but should not be required when `graph_backend="ladybugdb"`.

### `indexing_exclude` Semantics

The original failure mode was TOML list replacement hiding Python defaults.
Plan execution should make the default exclude behavior explicit instead of
only toggling requiredness.

Recommended smallest contract:

- Define `DEFAULT_INDEXING_EXCLUDE` as an internal built-in constant.
- Keep `indexing_exclude` as an operator field for additional or replacement
  patterns only if the semantics are named explicitly.
- Prefer adding `indexing_extra_exclude` for operator additions while preserving
  `indexing_exclude` as the resolved/effective list property or as a deprecated
  replacement field with warnings. If that is too broad for this phase, document
  `indexing_exclude` as replace-only and add a separate
  `effective_indexing_exclude` property that merges built-ins plus user extras.
- Call sites in `trickle.py` and service indexing should use the effective list
  so built-in ignores cannot disappear accidentally.

### Startup Pre-flight Gate

`backend/start.sh` currently uses `ENVIRONMENT=dev` to opt into lint, pyright
ratchet, live MCP server health, and e2e smoke. Phase 24 context says this gate
must stay because it prevents a bad restart from leaving the container healthy.

Recommended change:

- Add `DOTMD_RUN_STARTUP_CHECKS=true` as the primary switch.
- Keep `ENVIRONMENT=dev` as a temporary compatibility alias for the live compose
  override.
- Update error and comments so the switch is a startup safety gate, not an
  environment profile.
- Do not introduce `DOTMD_ENV`, `production`, `staging`, or strict-mode profile
  logic.

### Tests to Plan

Focused tests should cover:

- classification constants are exported from `dotmd.core.config`;
- internal default constants feed existing `Settings` defaults;
- runtime validation fails when required deployment fields are missing or
  unsafe, but ordinary tests can still construct `Settings` through explicit
  overrides;
- `graph_backend="falkordb"` requires a FalkorDB URL while `ladybugdb` does not;
- `base_url=None` remains valid;
- built-in indexing excludes remain effective when operator extra excludes are
  configured;
- `backend/start.sh` recognizes `DOTMD_RUN_STARTUP_CHECKS=true` and preserves
  the `ENVIRONMENT=dev` alias.

### Files Most Likely to Change

- `backend/src/dotmd/core/config.py`
- `backend/src/dotmd/ingestion/trickle.py`
- `backend/src/dotmd/api/service.py`
- `backend/start.sh`
- `.env.example`
- `README.md`
- `backend/tests/core/test_config_base_url.py`
- new focused config tests under `backend/tests/core/`

## Planning Guidance

Plan the phase as two dependent slices:

1. Core config boundary and runtime validation. This should create the constants
   and validation contract, migrate call sites to effective defaults, and add
   focused tests.
2. Startup/docs/template alignment. This should rename/document the startup
   check gate and make `.env.example` and `README.md` show the operator surface
   first with internal tuning in an advanced section.

Avoid:

- environment profiles;
- a large config subsystem;
- removing the startup pre-flight gate;
- making optional disabled features required;
- relying on production data or live containers in local tests.

## RESEARCH COMPLETE
