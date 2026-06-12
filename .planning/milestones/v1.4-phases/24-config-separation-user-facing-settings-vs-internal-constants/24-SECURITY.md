---
phase: "24-config-separation-user-facing-settings-vs-internal-constants"
status: secured
threats_total: 14
threats_closed: 14
threats_open: 0
verified_at: "2026-05-05T16:38:03Z"
asvs_level: 1
---

# Phase 24 Security Verification

Security audit for Phase 24 plans:

- `24-01-config-boundary-and-validation-PLAN.md`
- `24-02-startup-docs-and-template-PLAN.md`

Scope: verify declared threat mitigations only. Implementation files were read
but not modified.

## Threat Verification

| Threat ID | Source | Category | Disposition | Status | Evidence |
|-----------|--------|----------|-------------|--------|----------|
| TH-24-01-01 | Plan 01 | Runtime misconfiguration | mitigate | CLOSED | `validate_for_runtime()` rejects unsafe `data_dir`, `index_dir`, empty/relative `indexing_paths`, and empty `embedding_url`; `load_runtime_settings()` calls it before returning settings. Evidence: `backend/src/dotmd/core/config.py:295`, `backend/src/dotmd/core/config.py:413`; runtime entrypoints call `load_runtime_settings()` in `backend/src/dotmd/api/server.py:21`, `backend/src/dotmd/api/server.py:37`, `backend/src/dotmd/mcp_server.py:469`, `backend/src/dotmd/mcp_server.py:497`. |
| TH-24-01-02 | Plan 01 | Environment profile creep | mitigate | CLOSED | `Settings` remains the single config class and grep found no `DOTMD_ENV` or profile-specific `Literal["local", "dev", "staging", "prod", "production"]` field. Evidence: `backend/src/dotmd/core/config.py:57`; `backend/start.sh:12`, `.env.example:54`, and `README.md:235` describe `ENVIRONMENT=dev` only as a compatibility alias. |
| TH-24-01-03 | Plan 01 | Built-in exclude loss | mitigate | CLOSED | Built-in excludes live in `DEFAULT_INDEXING_EXCLUDE`; `indexing_extra_exclude` is additive; `effective_indexing_exclude` de-duplicates and preserves effective patterns. Evidence: `backend/src/dotmd/core/config.py:12`, `backend/src/dotmd/core/config.py:200`, `backend/src/dotmd/core/config.py:283`. Call sites consume the effective list in `backend/src/dotmd/api/service.py:717`, `backend/src/dotmd/ingestion/trickle.py:253`, `backend/src/dotmd/ingestion/trickle.py:293`, `backend/src/dotmd/ingestion/trickle.py:570`. |
| TH-24-01-04 | Plan 01 | Test dependence on live services | mitigate | CLOSED | Direct `Settings(...)` construction and `load_settings()` remain available without runtime validation; tests construct local settings with explicit `embedding_url` and prove defaults remain usable. Evidence: `backend/src/dotmd/core/config.py:403`, `backend/tests/core/test_config_separation.py:40`. |
| TH-24-01-05 | Plan 01 | Forced OAuth | mitigate | CLOSED | `base_url` defaults to `None`, validator returns `None`, and tests assert `base_url=None` remains valid. Evidence: `backend/src/dotmd/core/config.py:224`, `backend/src/dotmd/core/config.py:226`, `backend/tests/core/test_config_separation.py:152`, `backend/tests/core/test_config_base_url.py:10`. |
| TH-24-01-06 | Plan 01 | FalkorDB URL mandatory for LadybugDB | mitigate | CLOSED | Runtime validation checks `falkordb_url` only when `graph_backend == "falkordb"`; LadybugDB acceptance is covered in tests. Evidence: `backend/src/dotmd/core/config.py:326`, `backend/tests/core/test_config_separation.py:140`. |
| TH-24-01-07 | Plan 01 | Unsafe default FalkorDB URL in runtime | mitigate | CLOSED | `DEFAULT_FALKORDB_URL` is defined as `redis://localhost:6379` and rejected in FalkorDB runtime mode. Evidence: `backend/src/dotmd/core/config.py:27`, `backend/src/dotmd/core/config.py:326`, `backend/tests/core/test_config_separation.py:130`. |
| TH-24-01-08 | Plan 01 | Internal tuning values disappear | mitigate | CLOSED | Tuning defaults are exported as named constants and compatibility `Settings` fields still default from them. Evidence: `backend/src/dotmd/core/config.py:28`, `backend/src/dotmd/core/config.py:95`, `backend/src/dotmd/core/config.py:104`, `backend/src/dotmd/core/config.py:191`, `backend/src/dotmd/core/config.py:206`, `backend/src/dotmd/core/config.py:210`. |
| TH-24-02-01 | Plan 02 | Restart safety gate removed or bypassed | mitigate | CLOSED | Startup gate still enables on `DOTMD_RUN_STARTUP_CHECKS=true` or `ENVIRONMENT=dev`, runs ruff, pyright ratchet, background MCP health polling, e2e pytest, and exits non-zero on failure. Evidence: `backend/start.sh:26`, `backend/start.sh:43`, `backend/start.sh:46`, `backend/start.sh:49`, `backend/start.sh:63`, `backend/start.sh:79`, `backend/start.sh:85`. |
| TH-24-02-02 | Plan 02 | Required deployment values hidden in template/docs | mitigate | CLOSED | `.env.example` and README put required deployment configuration first with `/mnt`, `/dotmd-index`, `["/mnt"]`, TEI URL, graph backend, and FalkorDB URL guidance. Evidence: `.env.example:11`, `.env.example:12`, `.env.example:26`, `.env.example:28`, `.env.example:31`, `README.md:189`, `README.md:195`, `README.md:200`. |
| TH-24-02-03 | Plan 02 | Docs imply multiple environment profiles | mitigate | CLOSED | Startup wording names `DOTMD_RUN_STARTUP_CHECKS`; `ENVIRONMENT=dev` is documented as a temporary compatibility alias and not a profile system. Evidence: `backend/start.sh:4`, `backend/start.sh:12`, `.env.example:50`, `.env.example:54`, `README.md:231`, `README.md:235`. |
| TH-24-02-04 | Plan 02 | Internal tuning indistinguishable from required config | mitigate | CLOSED | `.env.example` and README have explicit advanced tuning sections separated from required deployment configuration. Evidence: `.env.example:58`, `README.md:237`. |
| TH-24-02-05 | Plan 02 | Compose/TEI examples drift from selected model names | mitigate | CLOSED | `.env.example` and README align on `BAAI/bge-small-en-v1.5`, `mmarco-minilm`, and `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`. Evidence: `.env.example:34`, `.env.example:38`, `.env.example:40`, `README.md:217`, `README.md:221`, `README.md:223`. |
| TH-24-02-06 | Plan 02 | Additive exclude config undiscoverable | mitigate | CLOSED | `.env.example` and README document `DOTMD_INDEXING_EXTRA_EXCLUDE` as additive and `DOTMD_INDEXING_EXCLUDE` as legacy replace-only. Evidence: `.env.example:16`, `.env.example:20`, `.env.example:21`, `README.md:204`, `README.md:207`, `README.md:208`. |

## Unregistered Flags

None. Both Phase 24 summaries contain `## Threat Flags` with `None`.

## Accepted Risks Log

No accepted risks.

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By | Notes |
|------------|---------------|--------|------|--------|-------|
| 2026-05-05 | 14 | 14 | 0 | Codex security auditor | Verified declared mitigations from both Phase 24 threat models against live code and phase artifacts. |

## Verification Commands

| Command | Result |
|---------|--------|
| `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` | Passed: `28 passed, 26 warnings` |
| `sh -n backend/start.sh` | Passed |
| `rg --no-heading "DOTMD_RUN_STARTUP_CHECKS|Required deployment configuration|Advanced tuning|DOTMD_INDEXING_EXTRA_EXCLUDE|DOTMD_SEMANTIC_SCORE_FLOOR=0.85" backend/start.sh .env.example README.md` | Passed: expected strings found |
| `! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0\\.4|DOTMD_ENV" .env.example README.md backend/start.sh backend/src/dotmd/core/config.py` | Passed: no matches |

## Result

All declared Phase 24 threat mitigations are present in code, tests, or
operator-facing artifacts. `threats_open: 0`.
