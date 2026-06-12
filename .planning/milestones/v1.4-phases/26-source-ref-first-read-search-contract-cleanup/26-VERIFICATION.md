---
phase: 26-source-ref-first-read-search-contract-cleanup
verified: 2026-05-06T13:00:57Z
status: passed
score: 12/12 must-haves verified
overrides_applied: 0
---

# Phase 26: Source-ref-first read/search contract cleanup Verification Report

**Phase Goal:** Remove the Phase 25 filesystem-path-first compatibility layer from dotMD's public read/search contract before adding Telegram or other non-filesystem sources. Make `ref` the primary identity for search hits and read/drill-style APIs, while keeping filesystem paths only where still needed internally.
**Verified:** 2026-05-06T13:00:57Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Public search-to-read identity is a single string `ref`, with filesystem refs shaped as `filesystem:<document_ref>`. | VERIFIED | `SearchResult` has required `ref: str` and validates namespace/document_ref split in `backend/src/dotmd/core/models.py:205-227`; filesystem mapping is documented in `docs/source-adapter-architecture.md:21-29`. |
| 2 | Public search result/hit shape is ref-first and no public `file_paths`/`file_path` identity remains. | VERIFIED | `SearchResult` has no path fields; MCP `SearchHit` serializes only `ref`, `snippet`, `score`, optional `heading` in `backend/src/dotmd/mcp_server.py:75-86`; API `/search` delegates to ref-first `SearchResult` in `backend/src/dotmd/api/server.py:139-160`. |
| 3 | Search hydration derives public refs from source provenance, not holder paths. | VERIFIED | `build_search_results()` calls `get_chunk_provenance_for_chunk_ids()` and constructs `SearchResult(ref=provenance.ref)` in `backend/src/dotmd/search/fusion.py:277-319`; missing provenance raises `ValueError` at `fusion.py:296-299`. |
| 4 | Canonical multi-provenance refs are deterministic. | VERIFIED | `MetadataStore.get_chunk_provenance_for_chunk_ids()` orders by `chunk_id, namespace, document_ref` and first-wins populates results in `backend/src/dotmd/storage/metadata.py:416-446`; reverse insertion test asserts `/mnt/a.md` wins in `backend/tests/test_fusion.py:310-338`. |
| 5 | Source provenance is enforced/backfilled before search hydration. | VERIFIED | `DotMDService._execute_search()` calls `_ensure_source_provenance_ready()` before candidate collection in `backend/src/dotmd/api/service.py:348`; the safety gate counts, backfills, and blocks incomplete backfill in `service.py:652-689`; live active count was `contextual_512_50 0`. |
| 6 | `read(ref)` and `drill(ref)` exist and reject arbitrary filesystem refs unless indexed. | VERIFIED | `read(self, ref: str...)` and `drill(self, ref: str)` are implemented in `backend/src/dotmd/api/service.py:756-811`; missing source rows for filesystem refs require active-strategy chunk count > 0 and existing path in `service.py:698-732`; test rejects existing non-indexed file in `backend/tests/api/test_service_search.py:190-212`. |
| 7 | `read` remains content-focused and `drill` remains separate metadata follow-up. | VERIFIED | `read()` returns `ref`, `total_chunks`, `frontmatter`, `chunks`; `drill()` returns metadata fields including `title`, `source_uri`, `document_type`, `parser_name`, `frontmatter`, `total_chunks` in `backend/src/dotmd/api/service.py:787-811`; MCP exposes distinct `read` and `drill` tools in `backend/src/dotmd/mcp_server.py:637-733`. |
| 8 | Public MCP/API/CLI callers pass `ref`, not namespace/document_ref objects or path-first parameters. | VERIFIED | MCP `read` and `drill` parameters are `ref` with "Source ref from a search result" in `backend/src/dotmd/mcp_server.py:647-709`; CLI search prints `r.ref` at `backend/src/dotmd/cli.py:144-150`; no FastAPI read route exists and `/search` returns the service model. |
| 9 | `chunk_file_paths_<strategy>` and `Chunk.file_paths` remain internal holder mechanics only. | VERIFIED | `Chunk.file_paths` remains on `Chunk`, not `SearchResult`, in `backend/src/dotmd/core/models.py:145-163`; metadata helper comments explicitly mark `chunk_file_paths_<strategy>` as internal in `backend/src/dotmd/storage/metadata.py:466-470` and `581-594`; docs repeat the internal-holder rule in `docs/architecture.md:198-202`. |
| 10 | Agent workflow `search(query) -> ref -> drill/read` is documented and smoke-tested. | VERIFIED | MCP instructions and docs describe `search(query) -> ref`, `drill(ref)`, `read(ref,start,end)` in `backend/src/dotmd/mcp_server.py:123-130` and `docs/mcp.md:47-60`; live e2e smoke passed with 36 tests. |
| 11 | Telegram/non-filesystem sources are kept out of filesystem `File` modeling. | VERIFIED | Docs state current graph `File` nodes are filesystem-only legacy internals and Telegram dialogs/messages must not be modeled as `File` in `docs/source-adapter-architecture.md:64-67` and `docs/architecture.md:204-206`. |
| 12 | Phase 26 did not require or run a full reindex / `dotmd index --force`. | VERIFIED | Code uses metadata-only provenance count/backfill helpers in `backend/src/dotmd/storage/metadata.py:448-508`; live count is `contextual_512_50 0`; grep of shell histories and `docker logs dotmd --since 2026-05-06T00:00:00` found no `dotmd index --force` / `index --force` matches; docs record no Phase 26 full rebuild requirement in `docs/architecture.md:208-209`. |

**Score:** 12/12 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/core/models.py` | Ref-first `SearchResult`, internal `Chunk.file_paths` retained | VERIFIED | `SearchResult.ref` exists; `SearchResult.file_paths`/`file_path` absent; `Chunk.file_paths` still exists. |
| `backend/src/dotmd/search/fusion.py` | Provenance-backed search hydration | VERIFIED | Calls provenance batch helper, sets `ref=provenance.ref`, raises on missing provenance. |
| `backend/src/dotmd/storage/metadata.py` | Canonical provenance, count/backfill helpers, holder comments | VERIFIED | Ordering/first-wins, `count_missing_source_provenance()`, `backfill_missing_source_provenance_from_file_paths()`, and internal-holder notes all present. |
| `backend/src/dotmd/api/service.py` | `read(ref)`, `drill(ref)`, active-strategy source resolution | VERIFIED | Ref parser/resolver, indexed-filesystem fallback check, active strategy rule, and metadata/content split implemented. |
| `backend/src/dotmd/mcp_server.py` | MCP `search/read/drill` ref contract and error wrapper | VERIFIED | `SearchHit`, `ReadResult`, `DrillResult`, `read(ref)`, `drill(ref)`, `_ref_tool_error()` implemented. |
| `backend/src/dotmd/cli.py` | CLI search prints refs | VERIFIED | Search header uses `r.ref`; old multi-holder public formatting removed. |
| Tests | Model/service/fusion/MCP/CLI/e2e regressions | VERIFIED | Focused local suite passed: 62 passed. Live e2e smoke passed: 36 passed. |
| Docs | Source-ref-first MCP/source-adapter docs | VERIFIED | `docs/mcp.md`, `docs/source-adapter-architecture.md`, and `docs/architecture.md` document ref workflow and internal holder paths. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| Search engines/fusion | `SearchResult.ref` | `build_search_results()` -> `get_chunk_provenance_for_chunk_ids()` | WIRED | Search result data source is provenance, not holder paths. |
| `DotMDService.search()` | provenance safety gate | `_execute_search()` -> `_ensure_source_provenance_ready()` | WIRED | Gate runs before candidate collection/hydration. |
| MCP `search` | service search | `service.search()` then `_format_result()` | WIRED | MCP hit payload carries `ref` only for identity. |
| MCP `read` | service read | `service.read(ref,start,end)` | WIRED | ValueError converted to tool-level actionable error. |
| MCP `drill` | service drill | `service.drill(ref)` | WIRED | Metadata payload exposed separately from read. |
| API `/search` | service search | FastAPI route returns `SearchResponse(results=SearchResult...)` | WIRED | No separate path-first API shape. |
| CLI `search` | service search | `r.ref` output | WIRED | Public CLI display uses source ref. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| Search result hydration | `SearchResult.ref` | `chunk_source_provenance_<strategy>` via `SQLiteMetadataStore.get_chunk_provenance_for_chunk_ids()` | Yes - SQL query over provenance table, canonical ordered rows | FLOWING |
| Source provenance safety | `missing` count | `chunks_<strategy>` LEFT JOIN `chunk_source_provenance_<strategy>` | Yes - live `contextual_512_50 0` | FLOWING |
| `read(ref)` | `ReadPayload.chunks` | `source_documents`/indexed fallback -> active `get_chunks_for_file_range()` | Yes - live smoke reads chunk text from search ref | FLOWING |
| `drill(ref)` | metadata payload | resolved `SourceDocument` + frontmatter + active chunk count | Yes - live smoke gets metadata from search ref | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused ref contract regressions | `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q` | `62 passed, 26 warnings in 3.52s` | PASS |
| Live MCP search/ref/drill/read and invalid-ref errors | `docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider"` | `36 passed in 125.81s` | PASS |
| Docs do not retain old public MCP path-first wording | `rg 'read\(file_path|Only pass file_paths|Returns ranked hits with source \`file_paths\`' docs backend/src/dotmd/mcp_server.py` | no matches | PASS |
| Internal holder docs still present | `rg 'chunk_file_paths|Chunk\.file_paths' docs/source-adapter-architecture.md docs/architecture.md` | only explicit internal-holder mentions | PASS |
| Active provenance count | container Python check using `SQLiteMetadataStore.count_missing_source_provenance()` | `contextual_512_50 0` | PASS |
| No observed full reindex command | grep shell histories and `docker logs dotmd --since 2026-05-06T00:00:00` for `dotmd index --force` / `index --force` | no matches | PASS |

### Requirements Coverage

Phase 26 declares no mapped requirement IDs. All three PLAN frontmatters contain `requirements: []`, and `.planning/REQUIREMENTS.md` has no Phase 26 traceability row. No requirement traceability is invented for this verification.

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| none | 26-01 / 26-02 / 26-03 | Phase 26 has no requirement IDs | SATISFIED | PLAN frontmatters contain `requirements: []`; REQUIREMENTS traceability stops at Phase 23. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| None | - | - | - | No blocking placeholder, path-first public search/read, orphaned contract, or hardcoded empty public data pattern found in the verified scope. |

### Human Verification Required

None.

### Gaps Summary

No gaps found. The phase goal is achieved: public search/read/drill contracts are source-ref-first, read/drill reject arbitrary unindexed filesystem refs, provenance is enforced before search hydration, filesystem holder tables remain internal, live MCP smoke passes, and no evidence of a Phase 26 full reindex command was found.

---

_Verified: 2026-05-06T13:00:57Z_
_Verifier: the agent (gsd-verifier)_
