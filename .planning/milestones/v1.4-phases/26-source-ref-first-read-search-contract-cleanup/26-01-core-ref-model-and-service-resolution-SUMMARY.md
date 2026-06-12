---
phase: 26-source-ref-first-read-search-contract-cleanup
plan: 01
subsystem: search
tags: [source-ref, search, read, sqlite, mcp, cli]

requires:
  - phase: 25-document-source-abstraction-source-adapter-mvp
    provides: source_documents and chunk_source_provenance tables
provides:
  - Ref-first SearchResult domain contract
  - Provenance-backed search result hydration
  - Count-first missing provenance safety helpers
  - Service read(ref) and drill(ref) resolution
affects: [mcp, cli, api, search, storage]

tech-stack:
  added: []
  patterns:
    - Source refs split on the first colon only
    - Search results hydrate public refs from chunk provenance, not holder paths
    - Phase 26 read(ref) uses the active chunk strategy only

key-files:
  created:
    - .planning/phases/26-source-ref-first-read-search-contract-cleanup/deferred-items.md
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/storage/metadata.py
    - backend/src/dotmd/search/fusion.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/cli.py
    - backend/src/dotmd/mcp_server.py
    - backend/tests/api/test_search_result_shape.py
    - backend/tests/api/test_service_search.py
    - backend/tests/test_fusion.py
    - backend/tests/mcp/test_search_tool.py
    - backend/tests/cli/test_search_output.py

key-decisions:
  - "SearchResult exposes ref as the only public search-to-read key; Chunk.file_paths remains internal."
  - "Missing search provenance is a hard ValueError after the count/dry-run/write safety gate."
  - "Canonical multi-provenance refs are selected by SQL ORDER BY chunk_id, namespace, document_ref with first-wins population."
  - "Service read(ref) is active-strategy-only in Phase 26."

patterns-established:
  - "Ref parsing: partition(':') rejects empty namespace or document_ref while preserving colons inside document_ref."
  - "Safety backfill: metadata-only, dry-run/count-first, INSERT OR IGNORE, scoped to missing chunk_source_provenance rows."

requirements-completed: []

duration: 13min
completed: 2026-05-06
---

# Phase 26 Plan 01: Core Ref Model and Service Resolution Summary

**Ref-first search/read core backed by source provenance, with a live count-first backfill gate for active strategy gaps**

## Performance

- **Duration:** 13 min
- **Started:** 2026-05-06T11:41:04Z
- **Completed:** 2026-05-06T11:53:49Z
- **Tasks:** 3
- **Files modified:** 12

## Accomplishments

- Replaced public `SearchResult.file_paths` with validated `SearchResult.ref`.
- Hydrated search result refs from `chunk_source_provenance_<strategy>` and made missing provenance a hard error.
- Added deterministic canonical provenance ordering with reverse-insertion regression coverage.
- Added `count_missing_source_provenance()` and dry-run/write backfill helpers.
- Added service-level `read(ref)` and `drill(ref)` using `source_documents`, active-strategy chunk helpers, and internal filesystem paths.
- Ran the live safety gate on active strategy `contextual_512_50`: missing `19540`, dry-run `19540`, write backfill `19540`, missing after `0`.

## Task Commits

1. **Task 1 RED: SearchResult ref contract test** - `68b0bef` (test)
2. **Task 1 GREEN: SearchResult ref-first model** - `6a273ef` (feat)
3. **Task 2 RED: Provenance hydration and safety tests** - `5b2fcc9` (test)
4. **Task 2 GREEN: Provenance search hydration and helpers** - `2c64a2e` (feat)
5. **Task 3 RED: Service read/drill ref tests** - `0822ae4` (test)
6. **Task 3 GREEN: Service read(ref) and drill(ref)** - `19c40f0` (feat)
7. **Rule 1 fix: Direct CLI/MCP consumers aligned to ref** - `e125fdc` (fix)
8. **Rule 1 fix: Idempotent safety helper table creation** - `8b7e8ac` (fix)

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - `SearchResult` now requires validated `ref`.
- `backend/src/dotmd/search/fusion.py` - Search hydration now reads canonical chunk provenance and raises on missing provenance.
- `backend/src/dotmd/storage/metadata.py` - Canonical provenance ordering plus count/backfill helpers.
- `backend/src/dotmd/api/service.py` - Ref parser/resolver, `read(ref)`, `drill(ref)`.
- `backend/src/dotmd/cli.py` - Search output renders `ref`.
- `backend/src/dotmd/mcp_server.py` - Direct MCP search/read payloads use `ref`.
- `backend/tests/...` - Ref-first model, search, service, MCP, CLI, and backfill regression coverage.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/deferred-items.md` - Out-of-scope pyright ratchet notes.

## Decisions Made

The plan decisions were followed. The only expansion was aligning direct CLI/MCP consumers because the core model/service changes made their path-first assumptions immediately inconsistent.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed direct CLI/MCP consumers after SearchResult/read payload changes**
- **Found during:** Plan verification
- **Issue:** `SearchResult.file_paths` and `ReadPayload.file_path` removal made direct CLI/MCP formatting inconsistent.
- **Fix:** Render CLI and MCP search/read payloads from `ref`; update affected tests.
- **Files modified:** `backend/src/dotmd/cli.py`, `backend/src/dotmd/mcp_server.py`, related tests
- **Verification:** `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q`
- **Committed in:** `e125fdc`

**2. [Rule 1 - Bug] Made provenance safety gate idempotent when the active provenance table is absent**
- **Found during:** Live active-strategy safety gate
- **Issue:** `count_missing_source_provenance("contextual_512_50")` failed when `chunk_source_provenance_contextual_512_50` did not exist.
- **Fix:** Count/backfill helpers now ensure the scoped provenance table before querying or writing.
- **Files modified:** `backend/src/dotmd/storage/metadata.py`
- **Verification:** `cd backend && uv run pytest tests/test_fusion.py -q`; live gate reached `missing_after=0`.
- **Committed in:** `8b7e8ac`

---

**Total deviations:** 2 auto-fixed (2 Rule 1)
**Impact on plan:** Both fixes were required for correctness; no reindex, restart, TEI embedding, FTS rebuild, vector rebuild, or graph rebuild was run.

## Issues Encountered

- `cd backend && uv run pyright` still fails with 69 errors after plan-caused direct ref errors were fixed. Remaining failures are existing ratchet issues outside this plan's scope and are recorded in `deferred-items.md`.

## Verification

- `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q` - PASS, 53 passed.
- `cd backend && uv run pyright` - FAIL, 69 pre-existing/out-of-scope errors remain after direct plan-caused errors were fixed.
- Active strategy safety gate - PASS:
  - `strategy=contextual_512_50`
  - `missing=19540`
  - `dry_run_backfill=19540`
  - `write_backfill=19540`
  - `missing_after=0`

## Known Stubs

None.

## User Setup Required

None.

## Next Phase Readiness

Plan 02 can proceed with public API/MCP/CLI contract cleanup on top of the ref-first core. The active production index has source provenance for the current strategy, so search missing-provenance hard errors should not trigger for existing active chunks.

## Self-Check: PASSED

Verified summary/key source files exist and all task/deviation commits are present in git history.

---
*Phase: 26-source-ref-first-read-search-contract-cleanup*
*Completed: 2026-05-06*
