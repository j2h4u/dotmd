---
phase: "24"
plan: "02-startup-docs-and-template"
type: execute
wave: 2
depends_on:
  - "24-01-config-boundary-and-validation"
files_modified:
  - backend/start.sh
  - .env.example
  - README.md
autonomous: true
requirements: []
requirements_addressed: []
must_haves:
  truths:
    - "D-13: The restart-time pre-flight gate in `backend/start.sh` is preserved, including ruff, pyright ratchet, live MCP `/health`, `tests/e2e/`, and non-zero exit on failure"
    - "D-14: The startup gate is documented as an operational safety switch, not a multi-environment profile model"
    - "D-15: `DOTMD_RUN_STARTUP_CHECKS=true` is the primary startup-check switch and `ENVIRONMENT=dev` remains only as a temporary compatibility alias"
    - "D-10: `.env.example` emphasizes operator/deployment config first and moves internal tuning to an advanced section"
    - "D-11: README documents required runtime config, selected identity config, optional features, and advanced tuning separately"
    - "D-12: Additive indexing excludes are discoverable through `DOTMD_INDEXING_EXTRA_EXCLUDE`; legacy `DOTMD_INDEXING_EXCLUDE` is documented as replace-only"
  artifacts:
    - path: "backend/start.sh"
      provides: "container startup check switch"
      contains: "DOTMD_RUN_STARTUP_CHECKS"
    - path: ".env.example"
      provides: "operator config template"
      contains: "Advanced tuning"
    - path: "README.md"
      provides: "configuration documentation"
      contains: "Required deployment configuration"
  key_links:
    - from: "DOTMD_RUN_STARTUP_CHECKS"
      to: "restart-time pre-flight gate"
      via: "backend/start.sh"
      pattern: "ENVIRONMENT=dev"
---

# Phase 24 Plan 02: Startup Docs and Template

<objective>
Preserve the container restart pre-flight gate while renaming it away from
environment-profile language, and update `.env.example` plus `README.md` so the
documented configuration surface matches the Phase 24 public settings boundary.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| The restart safety gate is removed or bypassed by a rename | HIGH | Preserve the existing lint/type/e2e gate and add `DOTMD_RUN_STARTUP_CHECKS=true` as the primary switch with `ENVIRONMENT=dev` alias. |
| Operators copy a template that hides required deployment values | HIGH | Put required deployment-bound config at the top of `.env.example` and README. |
| Docs imply dotMD has multiple environment profiles | MEDIUM | Remove `ENVIRONMENT=dev` as primary wording; describe a startup-check switch instead. |
| Internal tuning remains indistinguishable from required config | MEDIUM | Move tuning variables to an explicitly marked advanced section in both docs and template. |
| Compose/TEI examples drift from selected model names | MEDIUM | Keep `.env.example`, README, and `docker-compose.yml` TEI model defaults aligned. |
| Operators cannot discover additive exclude configuration | MEDIUM | Add a path-filtering subsection to `.env.example` and README covering `DOTMD_INDEXING_EXTRA_EXCLUDE` and the legacy replace-only `DOTMD_INDEXING_EXCLUDE`. |
</threat_model>

<tasks>
<task id="1" type="auto">
<name>Task 1: Rename and preserve startup pre-flight switch</name>
<read_first>
- `backend/start.sh`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-CONTEXT.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-RESEARCH.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-PATTERNS.md`
</read_first>
<files>
- `backend/start.sh`
</files>
<action>
Update `backend/start.sh` so the primary switch for the pre-flight gate is
`DOTMD_RUN_STARTUP_CHECKS=true`.

The shell condition must enable the gate when either condition is true:

- `DOTMD_RUN_STARTUP_CHECKS=true`
- `ENVIRONMENT=dev`

Keep `ENVIRONMENT=dev` only as a compatibility alias. Update comments and error
messages so they say `DOTMD_RUN_STARTUP_CHECKS=true` first and mention
`ENVIRONMENT=dev` only as a legacy alias.

Do not remove any of these existing gate steps:

- `ruff check --cache-dir /tmp/.ruff_cache src/ tests/ devtools/`
- `python3 devtools/pyright_ratchet.py`
- starting `$SERVE_CMD` in the background
- polling `http://localhost:8080/health`
- `env -u DOTMD_BASE_URL pytest -p no:cacheprovider tests/e2e/ --tb=short -q`
- killing the background server and exiting non-zero on failure

Do not add `DOTMD_ENV`, `production`, `staging`, or profile-specific branching.
</action>
<verify>
<automated>rg --no-heading "DOTMD_RUN_STARTUP_CHECKS|ENVIRONMENT=dev|ruff check|pyright_ratchet|tests/e2e" backend/start.sh</automated>
<automated>sh -n backend/start.sh</automated>
</verify>
<acceptance_criteria>
- `backend/start.sh` contains `DOTMD_RUN_STARTUP_CHECKS`.
- `backend/start.sh` contains `ENVIRONMENT=dev`.
- `backend/start.sh` contains `ruff check --cache-dir /tmp/.ruff_cache src/ tests/ devtools/`.
- `backend/start.sh` contains `python3 devtools/pyright_ratchet.py`.
- `backend/start.sh` contains `pytest -p no:cacheprovider tests/e2e/ --tb=short -q`.
- `backend/start.sh` does not contain `DOTMD_ENV`.
- `sh -n backend/start.sh` exits 0.
</acceptance_criteria>
<done>
The startup pre-flight gate is preserved and renamed as a startup-check switch.
</done>
</task>

<task id="2" type="auto">
<name>Task 2: Split `.env.example` into operator config and advanced tuning</name>
<read_first>
- `.env.example`
- `backend/src/dotmd/core/config.py`
- `docker-compose.yml`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-CONTEXT.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-RESEARCH.md`
</read_first>
<files>
- `.env.example`
</files>
<action>
Rewrite `.env.example` section headings so required/operator values come first
and internal tuning is clearly marked advanced.

The file must include these headings exactly:

- `# -- Required deployment configuration -------------------------------------`
- `# -- Index/search identity --------------------------------------------------`
- `# -- Optional features ------------------------------------------------------`
- `# -- Startup safety ---------------------------------------------------------`
- `# -- Advanced tuning --------------------------------------------------------`

Under required deployment configuration, include:

- `DOTMD_DATA_DIR=/data`
- `DOTMD_INDEX_DIR=/dotmd-index`
- `DOTMD_INDEXING_PATHS=["/data"]`
- `DOTMD_EMBEDDING_URL=http://tei:80`
- `DOTMD_GRAPH_BACKEND=ladybugdb`
- `DOTMD_FALKORDB_URL=redis://falkordb:6379` with a comment that this value is
  required only when `DOTMD_GRAPH_BACKEND=falkordb`; the Python default
  `redis://localhost:6379` is intentionally unsafe for FalkorDB runtime startup.

Add a `# Path filtering` comment block immediately after
`DOTMD_INDEXING_PATHS=["/data"]`:

- `# DOTMD_INDEXING_EXTRA_EXCLUDE=["**/private","**/drafts"]`
- `# DOTMD_INDEXING_EXCLUDE=["**/node_modules","**/.git"]`

The comments must explain that `DOTMD_INDEXING_EXTRA_EXCLUDE` is the preferred
additive operator setting and preserves built-in excludes, while
`DOTMD_INDEXING_EXCLUDE` is a legacy replace-only setting for replacing the
whole exclude list.

Under index/search identity, include:

- `DOTMD_EMBEDDING_MODEL=BAAI/bge-small-en-v1.5`
- `DOTMD_CHUNK_STRATEGY=heading_512_50`
- `DOTMD_EXTRACT_DEPTH=ner`
- `DOTMD_NER_MODEL_NAME=urchade/gliner_multi-v2.1`
- `DOTMD_RERANKER_NAME=mmarco-minilm`
- `DOTMD_RERANKER_BACKEND=cross_encoder`
- `DOTMD_RERANKER_MODEL=cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`
- `DOTMD_RERANKER_COMPARE_NAMES=mmarco-minilm`
- `DOTMD_EMBEDDING_WEIGHTS=text=0.7,meta=0.3`

Under optional features, include commented examples for:

- `DOTMD_BASE_URL=`
- `DOTMD_PROFILE_INDEXING=false`
- `DOTMD_READ_ONLY=false` only if `read_only` is a real active `Settings` field
  after Plan 01; otherwise do not add it.

Under startup safety, include:

- `DOTMD_RUN_STARTUP_CHECKS=true`
- a comment that `ENVIRONMENT=dev` is a temporary compatibility alias, not a
  profile system.

Under advanced tuning, move these values:

- `DOTMD_TEI_BATCH_SIZE=4`
- `DOTMD_VECTOR_BACKEND=sqlite-vec`
- `DOTMD_GRAPH_MAX_HOPS=2`
- `DOTMD_DEFAULT_TOP_K=10`
- `DOTMD_FUSION_K=60`
- `DOTMD_RERANK_POOL_SIZE=20`
- `DOTMD_SEMANTIC_SCORE_FLOOR=0.85`
- `DOTMD_SNIPPET_LENGTH=300`
- `DOTMD_RERANKER_RELEVANCE_FLOOR=`
- `DOTMD_RERANKER_LENGTH_PENALTY=true`
- `DOTMD_RERANKER_MIN_LENGTH=50`
- `DOTMD_MAX_CHUNK_TOKENS=512`
- `DOTMD_CHUNK_OVERLAP_TOKENS=50`
- `DOTMD_POLL_INTERVAL_SECONDS=3600.0`

Do not leave `DOTMD_SEMANTIC_SCORE_FLOOR=0.4`; the current Python default is
`0.85`, so the template must either use `0.85` or explain any intentional
override. Prefer `0.85`.
</action>
<verify>
<automated>rg --no-heading "Required deployment configuration|Index/search identity|Optional features|Startup safety|Advanced tuning" .env.example</automated>
<automated>rg --no-heading "DOTMD_INDEXING_PATHS=\\[\"/data\"\\]|DOTMD_RUN_STARTUP_CHECKS=true|DOTMD_SEMANTIC_SCORE_FLOOR=0.85" .env.example</automated>
<automated>! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0.4" .env.example</automated>
</verify>
<acceptance_criteria>
- `.env.example` contains `# -- Required deployment configuration`.
- `.env.example` contains `DOTMD_INDEXING_PATHS=["/data"]`.
- `.env.example` contains `DOTMD_INDEXING_EXTRA_EXCLUDE`.
- `.env.example` contains `DOTMD_INDEXING_EXCLUDE`.
- `.env.example` describes `DOTMD_INDEXING_EXTRA_EXCLUDE` as additive.
- `.env.example` describes `DOTMD_FALKORDB_URL` as required only when `DOTMD_GRAPH_BACKEND=falkordb`.
- `.env.example` contains `DOTMD_RUN_STARTUP_CHECKS=true`.
- `.env.example` contains `ENVIRONMENT=dev`.
- `.env.example` contains `# -- Advanced tuning`.
- `.env.example` contains `DOTMD_SEMANTIC_SCORE_FLOOR=0.85`.
- `.env.example` does not contain `DOTMD_SEMANTIC_SCORE_FLOOR=0.4`.
</acceptance_criteria>
<done>
The env template distinguishes deployment config from advanced internal tuning.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Update README configuration docs to match the new surface</name>
<read_first>
- `README.md`
- `.env.example`
- `backend/src/dotmd/core/config.py`
- `backend/start.sh`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-CONTEXT.md`
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-RESEARCH.md`
</read_first>
<files>
- `README.md`
</files>
<action>
Rewrite the README `## Configuration` section so it names four groups:

- `### Required deployment configuration`
- `### Index/search identity`
- `### Optional features`
- `### Advanced tuning`

In required deployment configuration, state that the live container should set:

- `DOTMD_DATA_DIR`
- `DOTMD_INDEX_DIR`
- `DOTMD_INDEXING_PATHS`
- `DOTMD_EMBEDDING_URL`
- `DOTMD_GRAPH_BACKEND`
- `DOTMD_FALKORDB_URL` when `DOTMD_GRAPH_BACKEND=falkordb`

Add a path-filtering subsection under required deployment configuration that
documents:

- `DOTMD_INDEXING_PATHS` selects the roots to index.
- `DOTMD_INDEXING_EXTRA_EXCLUDE` is the preferred additive way to add operator
  ignore patterns while preserving built-in excludes such as `**/.git`.
- `DOTMD_INDEXING_EXCLUDE` is the legacy replace-only setting for replacing the
  whole exclude list and should be used only when replacement is intentional.
- Example: `DOTMD_INDEXING_EXTRA_EXCLUDE=["**/private","**/drafts"]`.

State that `DOTMD_FALKORDB_URL=redis://falkordb:6379` is required only when
`DOTMD_GRAPH_BACKEND=falkordb`; the runtime validator rejects the unsafe
`redis://localhost:6379` default in FalkorDB mode.

In index/search identity, include:

- `DOTMD_EMBEDDING_MODEL`
- `DOTMD_CHUNK_STRATEGY`
- `DOTMD_EXTRACT_DEPTH`
- `DOTMD_NER_MODEL_NAME`
- `DOTMD_RERANKER_NAME`
- `DOTMD_RERANKER_BACKEND`
- `DOTMD_RERANKER_MODEL`
- `DOTMD_RERANKER_COMPARE_NAMES`
- `DOTMD_EMBEDDING_WEIGHTS`

In optional features, include:

- `DOTMD_BASE_URL` with the existing HTTPS/localhost OAuth rule.
- `DOTMD_PROFILE_INDEXING`.
- `DOTMD_RUN_STARTUP_CHECKS` as a startup safety gate. Explain that
  `ENVIRONMENT=dev` is a temporary compatibility alias and not an environment
  profile.

In advanced tuning, include the same tuning variables from `.env.example` and
state that these values can be changed for experiments but are not the primary
operator checklist.

Update any README defaults that conflict with `backend/src/dotmd/core/config.py`.
At minimum, `DOTMD_DATA_DIR` and `DOTMD_INDEX_DIR` should no longer be presented
as safe production defaults if runtime validation requires explicit deployment
values.
</action>
<verify>
<automated>rg --no-heading "Required deployment configuration|Index/search identity|Optional features|Advanced tuning|DOTMD_RUN_STARTUP_CHECKS|ENVIRONMENT=dev" README.md</automated>
<automated>rg --no-heading "DOTMD_INDEXING_PATHS|DOTMD_EMBEDDING_WEIGHTS|DOTMD_NER_MODEL_NAME" README.md</automated>
<automated>cd backend && uv run ruff check src/dotmd/core/config.py</automated>
</verify>
<acceptance_criteria>
- `README.md` contains `### Required deployment configuration`.
- `README.md` contains `DOTMD_INDEXING_PATHS`.
- `README.md` contains `DOTMD_INDEXING_EXTRA_EXCLUDE`.
- `README.md` contains `DOTMD_INDEXING_EXCLUDE`.
- README describes `DOTMD_INDEXING_EXTRA_EXCLUDE` as additive.
- README says `DOTMD_FALKORDB_URL` is required only when `DOTMD_GRAPH_BACKEND=falkordb`.
- `README.md` contains `DOTMD_EMBEDDING_WEIGHTS`.
- `README.md` contains `DOTMD_NER_MODEL_NAME`.
- `README.md` contains `DOTMD_RUN_STARTUP_CHECKS`.
- `README.md` contains `ENVIRONMENT=dev`.
- `README.md` contains `### Advanced tuning`.
- README does not describe `DOTMD_RUN_STARTUP_CHECKS` as an environment profile.
</acceptance_criteria>
<done>
The README config docs match the code and template surface from Phase 24.
</done>
</task>
</tasks>

<verification>
Run these commands after completing all tasks in this plan:

```bash
sh -n backend/start.sh
rg --no-heading "DOTMD_RUN_STARTUP_CHECKS|Required deployment configuration|Advanced tuning" backend/start.sh .env.example README.md
! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0.4" .env.example
cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q
cd backend && uv run ruff check src/dotmd/core/config.py
```
</verification>

<success_criteria>
- The restart-time pre-flight gate remains intact and uses `DOTMD_RUN_STARTUP_CHECKS=true`.
- `ENVIRONMENT=dev` survives only as a compatibility alias.
- `.env.example` and README separate deployment config from advanced tuning.
- Docs and template include the full operator-facing surface named in Phase 24 context.
</success_criteria>

## PLANNING COMPLETE
