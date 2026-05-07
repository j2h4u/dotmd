---
phase: 27-resource-bindings-retained-artifacts-foundation
plan: 03
subsystem: api
tags: [search, mcp, resource-bindings, active-filtering, tdd]

requires:
  - phase: 27-resource-bindings-retained-artifacts-foundation
    provides: resource_bindings storage helpers and filesystem unbind/rebind lifecycle from Plans 01-02
provides:
  - Public search filtering through active resource bindings before rerank and hydration
  - Named active-filter candidate pool policy with underfill logging
  - Active binding enforcement for read(ref) and drill(ref) before filesystem fallback
  - Binding count diagnostics for active, inactive, retained, and reused artifacts
affects: [phase-27, phase-28, phase-29, phase-30, phase-31, source-adapters, mcp]

tech-stack:
  added: []
  patterns:
    - Public visibility gate in DotMDService over active chunk provenance
    - Search hydration can receive prevalidated provenance maps
    - Count-only retained-artifact diagnostics without inactive browsing

key-files:
  created:
    - .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-03-SUMMARY.md
  modified:
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/search/fusion.py
    - backend/src/dotmd/storage/metadata.py
    - backend/tests/api/test_service_search.py

key-decisions:
  - "Public search uses ACTIVE_FILTER_OVERFETCH_FACTOR=5 plus a top_k + 50 cushion before active filtering, replacing the prior fixed top_k-sized retrieval path for non-reranked calls."
  - "Inactive retained chunks are filtered in DotMDService before reranking and SearchResult hydration; internal engines may still return retained candidates."
  - "read(ref) and drill(ref) require active resource bindings before source-document resolution, filesystem existence checks, frontmatter reads, chunk counts, or synthetic filesystem fallback."
  - "Diagnostics expose only counts keyed active, inactive, retained, and reused; no inactive browsing or recycle-bin surface was added."

patterns-established:
  - "Build public SearchResult objects from an active provenance map when the service has already enforced visibility."
  - "Treat missing source provenance as a hard invariant failure, while inactive provenance is a public-output skip."

requirements-completed: [R1, R2, R8]

duration: 7min
completed: 2026-05-07
---

# Phase 27 Plan 03: Public Active Filtering Summary

**Active resource bindings now gate public search/read/drill output while retained inactive artifacts remain internal and count-diagnosable**

## Performance

- **Duration:** 7 min
- **Started:** 2026-05-07T15:00:41Z
- **Completed:** 2026-05-07T15:07:22Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added active-binding filtering for fused search candidates before reranking and public `SearchResult` hydration.
- Added `ACTIVE_FILTER_OVERFETCH_FACTOR` and a `top_k + 50` minimum candidate cushion, with `active filter underfilled` warning logs when active candidates cannot fill `top_k`.
- Changed `read(ref)` and `drill(ref)` to require an active binding before filesystem fallback, file existence checks, frontmatter reads, or chunk reads.
- Added count-only binding diagnostics with `active`, `inactive`, `retained`, and `reused` keys, without exposing inactive content browsing.

## Task Commits

Each behavior task was committed with RED and GREEN TDD commits:

1. **Task 1: Filter search candidates by active bindings before rerank and hydration**
   - `fcc461e` test(27-03): add failing test for active search filtering
   - `8fe5a65` feat(27-03): filter public search to active bindings
2. **Task 2: Require active bindings for read and drill refs before filesystem fallback**
   - `7adf53a` test(27-03): add failing test for active read refs
   - `263d5ab` feat(27-03): require active refs for read and drill
3. **Task 3: Expose binding diagnostics without inactive content browsing**
   - `b665dee` test(27-03): add failing test for binding diagnostics
   - `006bc40` feat(27-03): expose binding count diagnostics

**Plan metadata:** committed separately in the final docs commit.

## Files Created/Modified

- `backend/src/dotmd/api/service.py` - Added active-filter pool policy, active candidate filtering before rerank/hydration, active read/drill resolver, and count diagnostics.
- `backend/src/dotmd/search/fusion.py` - Added optional precomputed provenance hydration map for already-filtered public results.
- `backend/src/dotmd/storage/metadata.py` - Added retained inactive chunk count helper for diagnostics.
- `backend/tests/api/test_service_search.py` - Added TDD coverage for inactive search filtering, active pool policy, reranker inputs, read/drill rejection, and diagnostics.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-03-SUMMARY.md` - Execution summary and verification record.

## Decisions Made

- Active filtering happens in `DotMDService`, not individual search engines, so semantic/FTS/graph-direct engines can still return retained chunks internally.
- The reranker only receives active chunk IDs. If inactive candidates dominate, search returns the active subset and logs underfill instead of leaking inactive refs.
- Missing provenance remains a hard invariant error; inactive provenance is skipped as normal visibility filtering.
- Diagnostics are deliberately count-only. No `include_inactive`, recycle-bin search, inactive read, or inactive list tool was added.

## Verification

- `cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py -q` - PASS, 53 passed, 29 warnings.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/mcp/test_search_tool.py -q` - PASS, 41 passed, 28 warnings.
- `cd backend && uv run pytest tests/api/test_service_search.py -q` - PASS, 36 passed, 30 warnings.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q` - PASS, 66 passed, 35 warnings.
- Acceptance greps confirmed `ACTIVE_FILTER_OVERFETCH_FACTOR`, `top_k + 50`, `get_active_chunk_provenance_for_chunk_ids`, `active filter underfilled`, `_require_active_source_document`, `binding_diagnostics`, and `count_retained_inactive_chunks` are present.
- `rg "include_inactive|recycle|inactive search|list_inactive" backend/src/dotmd backend/tests` returned no matches.
- `python3` block scan confirmed `load_index(` is not called inside `search`, `read`, or `drill`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- The same Pydantic settings warning appeared during API/fusion/MCP tests: `Config key toml_file is set in model_config but will be ignored...`. This is pre-existing test noise and did not affect pass/fail results.

## User Setup Required

None - no external service configuration required.

## Known Stubs

None. The existing synthetic filesystem fallback uses empty fingerprint fields only when reconstructing legacy filesystem `SourceDocument` rows after active binding approval; this is intentional Phase 26 compatibility and does not expose inactive content.

## TDD Gate Compliance

PASS - RED and GREEN commits exist for each behavior task. No refactor commit was needed.

## Threat Flags

None. The plan added visibility checks and count diagnostics but no new network endpoints, auth paths, file access patterns, or schema trust-boundary changes beyond the planned public filtering surface.

## Next Phase Readiness

Ready for Plan 27-04. Public search/read/drill now enforce active bindings without rebuilding indexes, while retained inactive artifacts remain available internally for reuse and count diagnostics.

## Self-Check: PASSED

- Summary file exists.
- Task commits exist: `fcc461e`, `8fe5a65`, `7adf53a`, `263d5ab`, `b665dee`, `006bc40`.
- Required verification command passed.
- Unrelated dirty work remained unstaged: `.opencode/opencode.json`, `.opencode/plugins/`, `.planning/graphs/`, `graphify-out/`.

---
*Phase: 27-resource-bindings-retained-artifacts-foundation*
*Completed: 2026-05-07*
