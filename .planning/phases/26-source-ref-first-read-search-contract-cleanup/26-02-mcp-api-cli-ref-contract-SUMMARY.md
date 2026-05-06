---
phase: 26-source-ref-first-read-search-contract-cleanup
plan: 02
subsystem: mcp
tags: [source-ref, mcp, fastapi, cli, e2e, search]

requires:
  - phase: 26-source-ref-first-read-search-contract-cleanup
    provides: Ref-first SearchResult domain contract and service read/drill resolution
provides:
  - MCP search/read/drill public ref contract
  - CLI search output pinned to public refs
  - Live MCP search-ref-drill-read smoke coverage
  - Tool-level invalid-ref errors with actionable guidance
affects: [mcp, cli, api, e2e, search]

tech-stack:
  added: []
  patterns:
    - MCP ValueError wrapping stays in mcp_server.py, not DotMDService
    - Public agent workflow is search(query) -> ref, drill(ref), read(ref,start,end)
    - Live e2e treats invalid refs as tool-level errors, not JSON-RPC errors

key-files:
  created:
    - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-02-mcp-api-cli-ref-contract-SUMMARY.md
  modified:
    - backend/src/dotmd/mcp_server.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/search/fusion.py
    - backend/tests/mcp/test_search_tool.py
    - backend/tests/cli/test_search_output.py
    - backend/tests/e2e/conftest.py
    - backend/tests/e2e/test_mcp_smoke.py
    - backend/tests/api/test_service_search.py
    - backend/tests/api/test_search_result_shape.py
    - backend/tests/test_fusion.py
    - backend/tests/test_hybrid_bm25.py

key-decisions:
  - "MCP read/drill convert service ValueError into tool-level RuntimeError containing Action: pass a ref returned by search."
  - "FastAPI Plan 02 scope is /search only; no read route exists and no new drill route was invented."
  - "Filesystem refs from live backfilled provenance may resolve from an existing file path when source_documents lacks the row."

patterns-established:
  - "MCP tool errors: log ValueError at warning level, include original service message, target ref, and the exact action hint."
  - "E2E MCP smoke pins search -> ref -> drill/read plus invalid-ref tool errors for both HTTP and stdio transports."

requirements-completed: []

duration: 20min
completed: 2026-05-06
---

# Phase 26 Plan 02: MCP/API/CLI Ref Contract Summary

**MCP, CLI, and live smoke now use source refs as the public search-to-read contract, with drill(ref) metadata and actionable invalid-ref tool errors**

## Performance

- **Duration:** 20 min
- **Started:** 2026-05-06T12:01:09Z
- **Completed:** 2026-05-06T12:21:44Z
- **Tasks:** 3
- **Files modified:** 11

## Accomplishments

- Added MCP `drill(ref)` and updated MCP instructions/docstrings to the `search(query) -> ref`, `drill(ref)`, `read(ref,start,end)` workflow.
- Pinned MCP `read`/`drill` `ValueError` conversion so bad refs return tool-level errors containing `Unknown source ref` or the service message plus `Action: pass a ref returned by search.`
- Kept CLI search output ref-first and tightened regression coverage against `file_path`/`file_paths` public output.
- Updated live MCP smoke to exact tools `search`, `read`, `drill`, `feedback`, ref-shaped search hits, ref-shaped read payloads, drill metadata, and invalid-ref tool errors.
- Fixed live legacy-provenance round-trip behavior where search could return a filesystem ref from `chunk_source_provenance_*` that had no matching `source_documents` row.

## Task Commits

1. **Task 1: Change MCP search/read schemas to ref and add drill(ref)** - `0ce0c12` (feat)
2. **Task 2: Update FastAPI and CLI public outputs** - `5a50220` (test)
3. **Task 3: Pin live MCP smoke to search-ref-drill-read workflow** - `2d63b7d` (fix)

**Plan metadata:** captured in the final docs commit for this plan.

## Files Created/Modified

- `backend/src/dotmd/mcp_server.py` - Added `DrillResult`, `drill(ref)`, ref workflow instructions, and MCP-only ValueError wrapping.
- `backend/src/dotmd/api/service.py` - Added filesystem fallback resolution for live provenance refs when `source_documents` lacks a row.
- `backend/tests/mcp/test_search_tool.py` - Added schema/output/error coverage for search/read/drill ref behavior.
- `backend/tests/cli/test_search_output.py` - Tightened CLI public output assertions against path-first fields.
- `backend/tests/e2e/test_mcp_smoke.py` - Re-pinned live smoke to `search -> ref -> drill/read` and invalid-ref tool errors.
- `backend/tests/e2e/conftest.py` - Let HTTP smoke skip OAuth token setup when the local server has no `/register` route.
- `backend/tests/api/test_service_search.py` - Covered legacy filesystem provenance refs without a `source_documents` row.
- `backend/src/dotmd/search/fusion.py`, `backend/tests/api/test_search_result_shape.py`, `backend/tests/test_fusion.py`, `backend/tests/test_hybrid_bm25.py` - Minimal pre-flight type/ruff gate fixes needed for container startup.

## FastAPI Route Finding

`rg -n "@app\\.(get|post|put|delete)|@router\\.(get|post|put|delete)" backend/src/dotmd/api/server.py` returned:

```text
68:@app.get("/health")
133:@app.post("/index", response_model=IndexStats)
139:@app.get("/search", response_model=SearchResponse)
163:@app.get("/rerank/compare", response_model=RerankerComparisonResponse)
190:@app.get("/status", response_model=IndexStats)
196:@app.get("/graph", response_model=GraphResponse)
```

`/search` already delegates through the ref-first `SearchResult` model. No FastAPI read route exists, so no `ref` rename was needed there and no new `drill` route was invented.

## Decisions Made

- MCP error wrapping lives in `mcp_server.py`; `DotMDService` keeps domain/service `ValueError` semantics.
- Invalid refs are tool-level errors for agents, not JSON-RPC protocol errors.
- Live filesystem provenance rows without `source_documents` are resolved from an existing filesystem path so `search -> ref -> read` remains round-trippable without a full reindex.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed live search-ref-read round-trip for legacy provenance refs**
- **Found during:** Task 3 live MCP smoke
- **Issue:** Search returned `filesystem:/mnt/...` refs from `chunk_source_provenance_contextual_512_50`, but some live refs had no matching `source_documents` row, so `read(ref)` returned `Unknown source ref`.
- **Fix:** `DotMDService._resolve_source_document()` now synthesizes a filesystem `SourceDocument` from an existing path when the source row is missing.
- **Files modified:** `backend/src/dotmd/api/service.py`, `backend/tests/api/test_service_search.py`
- **Verification:** `docker exec dotmd sh -c 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider'` - PASS, 36 passed.
- **Committed in:** `2d63b7d`

**2. [Rule 3 - Blocking] Fixed pre-flight import ordering and pyright ratchet blocker**
- **Found during:** Task 3 container restart
- **Issue:** Container pre-flight refused to start on ruff import-order failures in prior Phase 26 files, then on a pyright ratchet regression in `tests/test_hybrid_bm25.py`.
- **Fix:** Applied ruff import ordering to the reported files and added a narrow `Connection` cast in the hybrid test.
- **Files modified:** `backend/src/dotmd/search/fusion.py`, `backend/tests/api/test_search_result_shape.py`, `backend/tests/test_fusion.py`, `backend/tests/test_hybrid_bm25.py`
- **Verification:** Container pre-flight passed, including pyright ratchet and e2e smoke.
- **Committed in:** `2d63b7d`

**3. [Rule 3 - Blocking] Made local e2e HTTP auth optional when OAuth routes are absent**
- **Found during:** Task 3 live MCP smoke
- **Issue:** The e2e test process inherited `DOTMD_BASE_URL` and attempted `/register`, but the local live HTTP server returned 404 because auth routes were not enabled.
- **Fix:** `_http_access_token()` treats `/register` 404 as unauthenticated local HTTP and proceeds without a token.
- **Files modified:** `backend/tests/e2e/conftest.py`
- **Verification:** Full live MCP smoke passed for HTTP and stdio transports.
- **Committed in:** `2d63b7d`

---

**Total deviations:** 3 auto-fixed (1 Rule 1, 2 Rule 3)
**Impact on plan:** All fixes were required to prove the public ref workflow live. No reindex, TEI rebuild, FTS rebuild, vector rebuild, metadata chunk rebuild, or graph rebuild was run.

## Issues Encountered

- Raw `cd backend && uv run pyright` still exits 1 with the known project baseline of 69 errors. The container pyright ratchet passed (`69 errors`, baseline `76`) and no new pyright regression remains from this plan.
- The first live e2e rerun overlapped with container pre-flight restart behavior and saw a transient connection refusal. After pre-flight passed and the final server was healthy, the explicit full e2e command passed.

## Verification

- `cd backend && uv run pytest tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q` - PASS, 8 passed.
- `docker exec dotmd sh -c 'cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider'` - PASS, 36 passed.
- `cd backend && uv run ruff check src/dotmd/api/service.py src/dotmd/search/fusion.py tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/e2e/conftest.py tests/e2e/test_mcp_smoke.py tests/test_fusion.py tests/test_hybrid_bm25.py` - PASS.
- `cd backend && uv run pyright` - FAIL, 69 pre-existing baseline errors; container pyright ratchet passed and accepted the reduced baseline state.

## Known Stubs

None. The empty fingerprints in synthesized filesystem fallback documents are internal compatibility metadata for legacy provenance rows and are not public UI/search placeholders.

## User Setup Required

None.

## Next Phase Readiness

Plan 03 can proceed with docs/regression cleanup on top of the source-ref-first public MCP/CLI contract. The live container is healthy after the final restart and its pre-flight gate passed.

## Self-Check: PASSED

- Verified summary and key source/test files exist on disk.
- Verified task commits `0ce0c12`, `5a50220`, and `2d63b7d` exist in git history.

---
*Phase: 26-source-ref-first-read-search-contract-cleanup*
*Completed: 2026-05-06*
