---
phase: 24
reviewers: [opencode]
reviewed_at: 2026-05-05T20:38:38+05:00
plans_reviewed:
  - .planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-01-config-boundary-and-validation-PLAN.md
  - .planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-02-startup-docs-and-template-PLAN.md
---

# Cross-AI Plan Review — Phase 24

## OpenCode Review

Let me read the current code to ground the review.
# Cross-AI Plan Review: Phase 24 — Config Separation

## Plan 01: Config Boundary and Validation

### Summary

Well-structured plan with a clean TDD approach. The `validate_for_runtime()` / `load_runtime_settings()` split preserves test ergonomics while adding deployment safety. The `effective_indexing_exclude` property correctly addresses the TOML replacement failure mode. However, there are concrete gaps in the validation logic that would let the exact failure modes this phase claims to prevent slip through.

### Strengths

- **TDD discipline** — Task 1 writes focused RED tests before implementation. Tests name the exact contract (`DEFAULT_INDEXING_EXCLUDE`, `effective_indexing_exclude`, `validate_for_runtime`).
- **Minimal shape** — One `Settings` class, one validation method, one helper function. No framework, no profiles, no new config subsystem. Matches D-01/D-03 decisions.
- **`effective_indexing_exclude` design** — Deduplication with order-preserving merge is correct. The three-way boundary (built-in defaults, legacy replace, additive extras) is documented in code comments.
- **`load_runtime_settings` separation** — Keeps `load_settings` unchanged so existing tests and CLI commands aren't disrupted. The narrow runtime path is opt-in.
- **Conditional FalkorDB validation** — Only requires `falkordb_url` when `graph_backend="falkordb"`, matching D-05.

### Concerns

- **HIGH: `falkordb_url` default passes validation silently.** The current default is `"redis://localhost:6379"` (config.py:182). The plan's `validate_for_runtime()` only checks `falkordb_url` is *empty* when `graph_backend="falkordb"`. Since the default is never empty, a deployment using `graph_backend="falkordb"` without explicitly setting `falkordb_url` would pass validation but silently connect to `localhost` instead of the Docker network hostname. This is the exact "unsafe Python default" failure mode the phase exists to prevent. The validation should also reject `falkordb_url == "redis://localhost:6379"` when `graph_backend="falkordb"`, or better, define `DEFAULT_FALKORDB_URL` as a constant and check against it.

- **MEDIUM: Identity fields with non-empty defaults can never fail validation.** Task 2 says `validate_for_runtime()` should fail when `embedding_model`, `chunk_strategy`, `ner_model_name`, `reranker_name`, `reranker_model`, `reranker_backend`, or `embedding_weights` is empty. But all of these have non-empty Python defaults (e.g., `embedding_model="BAAI/bge-small-en-v1.5"`, line 33). An operator who never sets these will never see a validation failure. The plan conflates "has a default" with "must be explicitly acknowledged." If the goal is visibility (D-07), the validation approach doesn't achieve it — the `.env.example` docs do, but the code-level check is dead code for these fields.

- **MEDIUM: stdio MCP path skipped for runtime validation.** `mcp_server.py` has two `load_settings()` call sites: `init_service()` (stdio path, line 469) and `create_app()` (HTTP path, line 494). The plan says to use `load_runtime_settings` for the "HTTP MCP container path" but the stdio path is also a long-running server (used by Claude Desktop via `docker exec`). Both paths should validate, since both represent live deployments. Missing `init_service()` means a stdio session with misconfigured `data_dir` would start silently.

- **MEDIUM: `indexing_exclude` legacy semantics are underdocumented for operators.** The plan creates three exclude surfaces: `DEFAULT_INDEXING_EXCLUDE` (built-in), `indexing_exclude` (legacy replace-only), and `indexing_extra_exclude` (additive). The code comments document this, but neither `.env.example` nor README (Plan 02) mention `DOTMD_INDEXING_EXCLUDE` or `DOTMD_INDEXING_EXTRA_EXCLUDE` at all. An operator who wants to add excludes has no visible entry point.

- **LOW: Duplicate acceptance criterion.** `backend/src/dotmd/core/config.py does not contain DOTMD_ENV` appears twice in Task 2 acceptance criteria.

### Suggestions

- Fix the `falkordb_url` validation to check against the default constant, not just emptiness. Define `DEFAULT_FALKORDB_URL = "redis://localhost:6379"` alongside the other defaults, then validate `falkordb_url != DEFAULT_FALKORDB_URL` when `graph_backend="falkordb"`.
- Apply `load_runtime_settings()` to `init_service()` in `mcp_server.py` as well, not just `create_app()`. The stdio path is a live deployment.
- Remove the dead empty-string checks for fields that have non-empty defaults. Instead, document those as "selected defaults" in `.env.example` comments (which Plan 02 already does).
- Add `DOTMD_INDEXING_EXTRA_EXCLUDE` to `.env.example` under a "Path filtering" subsection so operators can discover the additive exclude mechanism.

---

## Plan 02: Startup Docs and Template

### Summary

Clean, focused plan that correctly preserves the pre-flight gate while renaming it. The `.env.example` section split is well-designed. The `SEMANTIC_SCORE_FLOOR=0.4` → `0.85` fix addresses a real drift between template and code defaults.

### Strengths

- **Pre-flight gate preservation** — Keeps all existing gate steps (ruff, pyright ratchet, e2e smoke) and adds the new switch as an OR condition. No gate step is removed.
- **Compatibility alias** — `ENVIRONMENT=dev` survives alongside `DOTMD_RUN_STARTUP_CHECKS=true`, preventing compose breakage during migration.
- **Section organization** — Five clear sections in `.env.example` (Required, Identity, Optional, Startup safety, Advanced) align with the context decisions D-10 through D-12.
- **`SEMANTIC_SCORE_FLOOR` fix** — Catches and corrects the `0.4` vs `0.85` drift between template and code (line 151 in config.py shows `0.85`).

### Concerns

- **MEDIUM: `DOTMD_INDEXING_EXCLUDE` and `DOTMD_INDEXING_EXTRA_EXCLUDE` absent from `.env.example`.** Plan 01 creates `indexing_extra_exclude` as a Settings field, but Plan 02's `.env.example` rewrite doesn't include any exclude-related variables under "Required deployment configuration" or "Optional features." The `indexing_paths` field is included (`DOTMD_INDEXING_PATHS=["/data"]`), but there's no mention of how to add excludes. This means the effective exclude mechanism from Plan 01 is invisible to operators.

- **LOW: `DOTMD_FALKORDB_URL` listed under "Required" but is conditionally required.** The plan puts `DOTMD_FALKORDB_URL=redis://falkordb:6379` under "Required deployment configuration" alongside `DOTMD_GRAPH_BACKEND=ladybugdb`. But when `graph_backend="ladybugdb"`, `falkordb_url` is irrelevant. A comment clarifying the conditional requirement would help.

- **LOW: `DOTMD_NER_MODEL_NAME` missing from `.env.example` "Index/search identity" section.** The plan's Task 2 acceptance criteria mention it, but the "Under index/search identity" list doesn't include `DOTMD_NER_MODEL_NAME` as a line item. It's listed in Plan 01's validation but not in the `.env.example` template items. This is likely an oversight in the plan text since the acceptance criteria do check for it.

### Suggestions

- Add a commented `DOTMD_INDEXING_EXTRA_EXCLUDE` example under "Required deployment configuration" or a new "Path filtering" subsection, e.g., `# DOTMD_INDEXING_EXTRA_EXCLUDE=["**/private","**/drafts"]`.
- Add a comment next to `DOTMD_FALKORDB_URL` noting it's only required when `DOTMD_GRAPH_BACKEND=falkordb`.
- Verify `DOTMD_NER_MODEL_NAME` appears in the actual `.env.example` content even though the "Under index/search identity" bullet list omits it.

---

## Risk Assessment

**Overall risk: MEDIUM**

The plans are well-scoped and avoid over-engineering. The main risk is that `validate_for_runtime()` has a blind spot for `falkordb_url`'s non-empty default, which would pass the exact kind of silent misconfiguration the phase is meant to prevent. A one-line fix (check against the default constant) resolves this. The secondary risk is that the stdio MCP path (`init_service()`) would skip runtime validation, which is a narrow but real gap for `docker exec` sessions. Both are fixable within the plan's existing structure without scope creep.

CYCLE_SUMMARY: current_high=1

## Current HIGH Concerns
- `falkordb_url` validation checks only for empty string but the default is `"redis://localhost:6379"` (never empty), so a production container with `graph_backend="falkordb"` and no explicit `falkordb_url` passes validation while connecting to the wrong host — exactly the failure mode Phase 24 exists to prevent.

---

## Consensus Summary

Only OpenCode was requested and invoked for this review cycle, so there is no multi-reviewer consensus to aggregate. The single reviewer judged the plans mostly sound and focused, with one unresolved HIGH concern and several MEDIUM/LOW polish items.

### Agreed Strengths

- The plans preserve a small implementation shape: one public `Settings` surface, focused runtime validation, and no environment profile abstraction.
- The TDD-first config tests and explicit `effective_indexing_exclude` contract address the original TOML/defaults failure mode.
- The startup gate rename preserves operational safety while keeping `ENVIRONMENT=dev` as a compatibility alias.
- The docs/template split is aligned with the phase goal of separating deployment config from advanced tuning.

### Agreed Concerns

- HIGH: Runtime validation should reject the unsafe default FalkorDB URL, not only an empty string, when `graph_backend="falkordb"`.
- MEDIUM: Runtime validation should cover the stdio MCP service path if that path is considered a live deployment entry point.
- MEDIUM: `.env.example` and README should expose the additive exclude mechanism so operators can discover `DOTMD_INDEXING_EXTRA_EXCLUDE`.

### Divergent Views

- None. Only one external reviewer was used in this cycle.
