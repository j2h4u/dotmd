---
phase: 26-source-ref-first-read-search-contract-cleanup
plan: 03
subsystem: mcp
tags: [source-ref, mcp, docs, e2e, regression]

requires:
  - phase: 26-source-ref-first-read-search-contract-cleanup
    provides: ref-first SearchResult, service read(ref), drill(ref), and MCP/CLI ref contract
provides:
  - Ref-first regression suite coverage across local and live MCP surfaces
  - Source-ref-first architecture and MCP documentation
  - Live streamable-http MCP smoke evidence for search -> ref -> drill/read
  - No-full-reindex and deferred-scope audit for Phase 26
affects: [mcp, docs, search, source-adapter, testing]

tech-stack:
  added: []
  patterns:
    - Live smoke covers both HTTP and stdio transports with identical ref-first assertions
    - Documentation treats chunk_file_paths_<strategy> and Chunk.file_paths as internal holder mechanics only

key-files:
  created:
    - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md
  modified:
    - backend/tests/e2e/test_mcp_smoke.py
    - docs/source-adapter-architecture.md
    - docs/source-adapter-architecture-panel-review.md
    - docs/architecture.md
    - docs/mcp.md
    - docs/reranker-benchmark-methodology.md

key-decisions:
  - "Plan 03 documentation records Phase 26 as source-ref-first: public search hits are { ref, heading?, snippet, score } and public reads use read(ref, start, end)."
  - "Optional graph/entity enrichment remains deferred from drill(ref) until a stable non-filesystem shape exists."
  - "The first post-restart smoke failure was a startup/pre-flight reachability race, not a contract regression; no second restart was needed."

patterns-established:
  - "Docs grep gates may retain file_path wording only for canonical filesystem ref construction or explicit internal/non-public holder notes."
  - "E2E search shape assertions check all returned hits where applicable, not only the first result."

requirements-completed: []

duration: 11min
completed: 2026-05-06
---

# Phase 26 Plan 03: Regression, Documentation, and Live Smoke Summary

**Source-ref-first MCP contract verified locally and live, with docs updated to keep filesystem paths internal and no full reindex required**

## Performance

- **Duration:** 11 min
- **Started:** 2026-05-06T12:25:50Z
- **Completed:** 2026-05-06T12:37:09Z
- **Tasks:** 4
- **Files modified:** 7

## Accomplishments

- Tightened live smoke assertions so every returned search hit is checked for the public ref-first shape.
- Updated MCP and architecture docs to teach `search(query) -> ref`, `drill(ref)`, and `read(ref, start, end)`.
- Verified the live running `streamable-http MCP server` after a single batched `docker restart dotmd`.
- Proved invalid `read` and `drill` refs are tool-level errors containing `Unknown source ref` and `Action: pass a ref returned by search.`
- Recorded the Phase 26 no-full-reindex audit and deferred non-filesystem scope.

## Final Contract

- Public search hit shape: `{ ref, heading?, snippet, score }`.
- `SearchResult.ref` is the only public search-to-read identity.
- Filesystem refs use `filesystem:<document_ref>`, with `document_ref = str(Path(file_path).resolve())`.
- Multi-provenance chunks use the lexicographically first `(namespace, document_ref)` provenance row as the canonical public ref.
- Missing search provenance is a hard service/search invariant: `ValueError("missing source provenance for chunk_id=...")`.
- `read(ref, start, end)` resolves the source document and returns `ref`, `frontmatter`, `total_chunks`, and requested chunks.
- Phase 26 `read(ref)` uses the active `self._settings.chunk_strategy`; it does not discover or scan alternate strategy holder tables.
- `drill(ref)` returns source metadata and chunk count. Optional graph/entity enrichment is deferred because it is not stable for non-filesystem sources yet.
- MCP `ValueError` wrapping lives in `backend/src/dotmd/mcp_server.py`, converting service errors into actionable tool-level errors with `Action: pass a ref returned by search.`

## Provenance Safety

Active strategy: `contextual_512_50`

Real active query:

```sql
SELECT COUNT(*) FROM chunks_contextual_512_50 c
LEFT JOIN chunk_source_provenance_contextual_512_50 p ON c.chunk_id = p.chunk_id
WHERE p.chunk_id IS NULL;
```

- Plan 01 initial missing-provenance count: `19540`
- Plan 01 dry-run backfill: `19540`
- Plan 01 write backfill: `19540`
- Plan 01 final missing-provenance count: `0`
- Plan 03 verified missing-provenance count: `0`

## Task Commits

1. **Task 1: Run and update focused regression suite** - `d2a7f5e` (test)
2. **Task 2: Update source-adapter and MCP documentation** - `8865189` (docs)
3. **Task 3: Run live MCP smoke after batched restart if needed** - `3e82727` (test)
4. **Task 4: Write final phase summary and deferred-scope audit** - committed with plan metadata

## Files Created/Modified

- `backend/tests/e2e/test_mcp_smoke.py` - Checks all returned search hits for ref-first fields; live smoke proves ref, drill/read, and invalid-ref tool errors.
- `docs/mcp.md` - Documents the public MCP workflow and tool shapes.
- `docs/architecture.md` - Updates top-level architecture to source-ref-first search/read and internal holder paths.
- `docs/source-adapter-architecture.md` - Records Phase 26 delivered state, Telegram/File boundary, active-strategy read rule, and deferred scope.
- `docs/source-adapter-architecture-panel-review.md` - Updates review notes to reflect the settled `read(ref)` contract.
- `docs/reranker-benchmark-methodology.md` - Removes stale literal path-first selector wording from the docs grep surface.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` - Final verification, smoke, and audit record.

## Verification

- `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q` - PASS, 59 passed.
- `cd backend && uv run pytest -q --ignore=tests/e2e` - PASS, 324 passed.
- `just typecheck` - PASS, `pyright ratchet: 69 errors (baseline 76)`.
- `docker exec dotmd python -c "import pytest, sys; print(sys.executable)"` - PASS, `/usr/local/bin/python`.
- `docker restart dotmd` - PASS, one batched restart.
- Container pre-flight smoke - PASS, `36 passed in 118.93s`.
- `docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"` - PASS, `36 passed in 115.27s`.
- `rg 'read\(file_path|Only pass file_paths|Returns ranked hits with source \`file_paths\`' docs backend/src/dotmd/mcp_server.py` - PASS, no matches.

Live smoke evidence:

- `search -> ref`: `TestSearchSmoke::test_result_fields_match_pinned` and `test_ref_is_filesystem_source_ref` passed for both `http` and `stdio`.
- `drill(ref)`: `TestDrillSmoke::test_drill_returns_source_metadata` passed for both transports.
- `read(ref, 0, 3)`: `TestReadSmoke::test_ranged_read_returns_chunks` passed for both transports.
- Invalid `read(ref="filesystem:/nonexistent/file.md")`: tool-level `Unknown source ref` plus `Action: pass a ref returned by search.` passed for both transports.
- Invalid `read(ref="not-a-ref")`: tool-level `Unknown source ref` plus `Action: pass a ref returned by search.` passed for both transports.
- Invalid `drill(ref="not-a-ref")`: tool-level `Unknown source ref` plus `Action: pass a ref returned by search.` passed for both transports.

## Decisions Made

- Kept public search hits minimal: `ref`, optional `heading`, `snippet`, and `score`; no `display_path`, `source_uri`, or deprecated public `file_paths` was added for readability.
- Left graph/entity enrichment out of `drill(ref)` documentation and smoke assertions until a non-filesystem-safe shape is designed.
- Treated the first live smoke failure as a startup race while the restarted container was still in its pre-flight gate. The same restart completed successfully; no extra restart loop was used.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 3 - Blocking] Waited out container pre-flight before rerunning explicit smoke**
- **Found during:** Task 3 (Run live MCP smoke after batched restart if needed)
- **Issue:** The first explicit smoke command ran before the restarted container finished startup and exited with `dotMD MCP server not reachable at http://localhost:8080`.
- **Fix:** Inspected container state/logs, confirmed the same restart was still in pre-flight, waited for pre-flight to pass, then reran the same smoke command against the final server without another restart.
- **Files modified:** `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md`
- **Verification:** Final explicit smoke passed, `36 passed in 115.27s`.
- **Committed in:** `3e82727`

---

**Total deviations:** 1 auto-fixed (1 Rule 3)
**Impact on plan:** Verification became more precise. No scope creep, no second restart loop, and no reindex.

## Issues Encountered

- The container entrypoint runs a pre-flight gate on restart in this environment. Running the explicit smoke immediately after `docker restart dotmd` can race final server readiness. Waiting for the same restart's pre-flight to finish resolved it.

## Known Stubs

None. The only empty-list pattern found was the intentional e2e assertion that metadata-only `read(ref)` returns no chunk text.

## Threat Flags

None. Plan 03 changed tests and docs only; it introduced no new network endpoints, auth paths, file access patterns, schema changes, or trust-boundary behavior.

## User Setup Required

None.

## Deferred Scope Audit

- Telegram adapter implementation remains deferred.
- Source-unit emission for non-filesystem sources remains deferred.
- Graph `File` node rewrite remains deferred; existing graph `File` internals are filesystem-only legacy internals.
- Replacing `chunk_file_paths_<strategy>` holder tables remains deferred; they remain internal filesystem/content-dedup mechanics.
- Pretty `title` labels for search hits remain deferred unless added later as neutral metadata, not as a path-shaped public identity.

## No-Full-Reindex Audit

- `dotmd index --force was not run`.
- No full TEI re-embedding was run.
- No full FTS rebuild was run.
- No vector rebuild was run.
- No metadata chunk rebuild was run.
- No graph rebuild was run.
- Full rebuild remains a three-day cost/risk item requiring explicit user decision.

## Next Phase Readiness

Phase 26 is complete. Future Telegram/non-filesystem work can build on a public source-ref-first MCP contract without inheriting `File` or filesystem path-shaped search/read APIs.

## Self-Check: PASSED

- Verified summary and key files exist on disk.
- Verified task commits `d2a7f5e`, `8865189`, and `3e82727` exist in git history.
- Verified final local pytest, typecheck, live e2e, docs grep, provenance safety, active strategy behavior, and tool-level invalid-ref errors.

---
*Phase: 26-source-ref-first-read-search-contract-cleanup*
*Completed: 2026-05-06*
