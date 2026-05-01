---
phase: 19
slug: reranker-adapter-layer-and-multi-model-comparison
status: verified
threats_open: 0
asvs_level: 1
created: 2026-05-01
verified: 2026-05-01
---

# Phase 19 - Security

Per-phase security contract: threat register, accepted risks, and audit trail.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| CLI/API developer comparison | Developer-selected reranker names enter service selection and comparison paths. | Query strings, CLI options, reranker names |
| Reranker provider boundary | Local CrossEncoder providers are loaded lazily behind the adapter/factory interface. | Query text, chunk IDs, chunk text |
| MCP tool surface | User MCP search/read/feedback tools remain separate from developer-only comparison diagnostics. | MCP tool arguments and search results |

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status | Evidence |
|-----------|----------|-----------|-------------|------------|--------|----------|
| T-19-01 | Reranker registry/factory | Factory/API/CLI | mitigate | Unknown names raise `ValueError` with available names; API/CLI expose client-visible errors. | closed | `backend/src/dotmd/search/reranker.py:259-266`, `backend/src/dotmd/api/server.py:154`, `backend/src/dotmd/api/server.py:181`, `backend/src/dotmd/cli.py:136`, `backend/src/dotmd/cli.py:202` |
| T-19-02 | Tests/model loading | Unit tests | mitigate | Tests patch `sentence_transformers.CrossEncoder`; factory tests inspect metadata/cache without downloads. | closed | `backend/tests/test_reranker.py:33`, `backend/tests/test_reranker.py:61`, `backend/tests/test_reranker.py:80`, `backend/tests/test_reranker.py:99`, `backend/tests/test_reranker.py:123`, `backend/tests/test_reranker.py:155`, `backend/tests/test_reranker.py:178`, `backend/tests/test_reranker.py:200`, `backend/tests/test_reranker.py:313-343` |
| T-19-03 | Production search behavior | Settings/service | mitigate | Single default `reranker_name`; comparison names are separate and only used by `compare_rerankers`. | closed | `backend/src/dotmd/core/config.py:55-56`, `backend/src/dotmd/api/service.py:335`, `backend/src/dotmd/api/service.py:446` |
| T-19-04 | Compatibility | Reranker imports | mitigate | Compatibility alias remains. | closed | `backend/src/dotmd/search/reranker.py:302`, `backend/tests/test_reranker.py:380-384` |
| T-19-05 | Ranking semantics | Hybrid/rerank pipeline | mitigate | Existing hybrid/rerank regression tests pass, including keyword survival and fused fallback behavior. | closed | `backend/tests/test_hybrid_bm25.py:166`, `backend/tests/test_hybrid_bm25.py:395`, `backend/tests/test_hybrid_bm25.py:431`; focused pytest: `53 passed, 33 warnings` |
| T-19-06 | Runtime selection/resource use | RerankerFactory | mitigate | Factory cache is reused for runtime selection. | closed | `backend/src/dotmd/search/reranker.py:287-299`, `backend/tests/test_reranker.py:335-343`, `backend/src/dotmd/api/service.py:116`, `backend/src/dotmd/api/service.py:335` |
| T-19-07 | Search performance/index IO | Candidate pool | mitigate | Candidate pool calls existing engines; no `load_index()` in per-request helper path. | closed | `backend/src/dotmd/api/service.py:505-590`; `rg "load_index\\(" backend/src/dotmd/api/service.py` only found warmup at `backend/src/dotmd/api/service.py:140` |
| T-19-08 | Comparison correctness | Graph enrichment/candidate pool | mitigate | Candidate pool returns after graph enrichment appends candidates and updates `engine_results`. | closed | `backend/src/dotmd/api/service.py:570-580`, `backend/src/dotmd/api/service.py:586`, `backend/tests/test_hybrid_bm25.py:109-132` |
| T-19-09 | Runtime override errors | Service/API/CLI | mitigate | Factory `ValueError` is not swallowed; API maps to 400 and CLI maps to Click errors. | closed | `backend/src/dotmd/search/reranker.py:259-266`, `backend/src/dotmd/api/server.py:154`, `backend/src/dotmd/api/server.py:181`, `backend/src/dotmd/cli.py:136`, `backend/src/dotmd/cli.py:202`, `backend/tests/api/test_service_search.py:355-368`, `backend/tests/test_cli.py:31-49`, `backend/tests/test_cli.py:112-131` |
| T-19-10 | Comparison validity | Shared retrieval | mitigate | Comparison collects retrieval once and tests assert each engine is called once for multi-reranker comparison. | closed | `backend/src/dotmd/api/service.py:439-450`, `backend/tests/api/test_service_search.py:200-235` |
| T-19-11 | Diagnostics reliability | Comparison diagnostics | mitigate | Per-reranker `elapsed_ms` exists; provider errors become partial result rows with `error`. | closed | `backend/src/dotmd/api/service.py:460-481`, `backend/tests/api/test_service_search.py:117-162` |
| T-19-12 | Schema drift | FastAPI response | mitigate | Route validates through Pydantic response model; no unsafe `RerankerComparisonResponse(**...)` unpacking present. | closed | `backend/src/dotmd/api/server.py:89-104`, `backend/src/dotmd/api/server.py:158-182`; `rg "RerankerComparisonResponse\\(\\*\\*" backend/src/dotmd/api/server.py` returned no matches |
| T-19-13 | MCP surface | MCP search tool | mitigate | MCP search schema remains `query, top_k`; developer comparison is absent from MCP. | closed | `backend/src/dotmd/mcp_server.py:518-540`; `backend/src/dotmd/api/server.py:158` and `backend/src/dotmd/cli.py:162-202` show comparison only in API/CLI |
| T-19-14 | API contract | FastAPI models | mitigate | Explicit Pydantic response models cover search and comparison output. | closed | `backend/src/dotmd/api/server.py:80-104`, `backend/src/dotmd/api/server.py:134-158` |
| T-19-15 | Documentation | Developer docs | mitigate | README and architecture docs include exact CLI/API paths and elapsed-time usage. | closed | `README.md:114-124`, `docs/architecture.md:130-136` |
| T-19-16 | Verification safety | Tests/smoke | mitigate | Unit tests use mocks; live CPU smoke is optional and recorded as skipped. | closed | `backend/tests/test_reranker.py:33-360`, `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-latency-docs-verification-SUMMARY.md:92-100` |
| T-19-17 | Operational safety | Documentation | mitigate | Docs state comparison is developer-only and no restart is needed for local/container diagnostic runs. | closed | `README.md:118-124`, `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-latency-docs-verification-SUMMARY.md:64-65` |
| T-19-18 | Latency visibility | Comparison output/docs/summary | mitigate | Comparison output includes `elapsed_ms`; summary contains Qwen-specific latency note. | closed | `backend/src/dotmd/api/service.py:460-481`, `backend/src/dotmd/cli.py:204-210`, `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-latency-docs-verification-SUMMARY.md:98-100` |

Status: closed = mitigation verified in implemented code/tests/docs per declared plan.

## Accepted Risks Log

No accepted risks.

## Unregistered Flags

None. Summary threat flags were reviewed:

| Source | Result |
|--------|--------|
| `19-03-developer-comparison-surfaces-SUMMARY.md:113-115` | Developer FastAPI route mapped to existing threat model; MCP unchanged. |
| `19-04-latency-docs-verification-SUMMARY.md:131-133` | No new network endpoints, auth paths, file access patterns, or schema changes. |

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-01 | 18 | 18 | 0 | Codex security auditor |

## Verification Commands

```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py -q
```

Result: `53 passed, 33 warnings`. Warnings were existing pydantic-settings TOML-source warnings.

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

Approval: verified 2026-05-01
