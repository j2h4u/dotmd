---
phase: 26-source-ref-first-read-search-contract-cleanup
plan: 03
status: in_progress
---

# Phase 26 Plan 03 Working Summary

## Task 1 Regression Results

- `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q` - PASS, 59 passed, 23 warnings.
- `cd backend && uv run pytest -q --ignore=tests/e2e` - PASS, 324 passed, 130 warnings.
- `just typecheck` - PASS, `pyright ratchet: 69 errors (baseline 76)`, improvements remain below the checked-in baseline.

Focused files covered:

- `tests/api/test_search_result_shape.py`
- `tests/mcp/test_search_tool.py`
- `tests/e2e/test_mcp_smoke.py`

Search result regression tightening:

- Live e2e smoke assertions now check every returned search result for the public `{ ref, heading?, snippet, score }` shape where applicable.
- Every returned result must use `ref`; public `file_path` and `file_paths` remain rejected from search hit assertions.

## Active-Strategy Provenance Safety Evidence

Active strategy: `contextual_512_50`

Real active query:

```sql
SELECT COUNT(*) FROM chunks_contextual_512_50 c
LEFT JOIN chunk_source_provenance_contextual_512_50 p ON c.chunk_id = p.chunk_id
WHERE p.chunk_id IS NULL;
```

Result:

- `missing-provenance count=0`

Plan 01 already found a nonzero live count before implementation and completed the required dry-run/write backfill:

- `dry_run_backfill=19540`
- `write_backfill=19540`
- final `missing_after=0`

No additional backfill was needed in Plan 03.

## Self-Check: PASSED

Task 1 focused tests, non-e2e suite, typecheck, and active-strategy provenance check passed.

## Task 3 Live MCP Smoke

Pytest availability gate:

- `docker exec dotmd python -c "import pytest, sys; print(sys.executable)"` - PASS, `/usr/local/bin/python`.

Restart:

- `docker restart dotmd` - PASS, single batched restart performed after Phase 26 implementation/docs changes.
- Target runtime: running production-style `streamable-http MCP server` in the local `dotmd` container.

Initial smoke attempt:

- `docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"` first exited before running tests with `dotMD MCP server not reachable at http://localhost:8080`.
- Cause: the restarted container was still in its built-in pre-flight gate (`health: starting`), not a schema or contract failure.
- No second restart was run for this reachability race. I waited for the same restart to finish its pre-flight and start the final server.

Container pre-flight result:

- Built-in pre-flight e2e smoke: PASS, `36 passed in 118.93s`.
- Final server startup: PASS, health returned `{"status":"ok"}`.

Explicit live smoke against the final server:

- `docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"` - PASS, `36 passed in 115.27s`.

Contract evidence from the passing smoke:

- `search -> ref`: `TestSearchSmoke::test_result_fields_match_pinned` and `test_ref_is_filesystem_source_ref` passed for both `http` and `stdio`; every returned search hit is checked for `ref`, `snippet`, `score`, and optional `heading`.
- `drill(ref)`: `TestDrillSmoke::test_drill_returns_source_metadata` passed for both `http` and `stdio`, proving source metadata and `total_chunks` are available by ref.
- `read(ref, 0, 3)`: `TestReadSmoke::test_ranged_read_returns_chunks` passed for both `http` and `stdio`, proving chunk text ranges are readable by ref.
- Invalid `read(ref="filesystem:/nonexistent/file.md")`: `TestReadSmoke::test_nonexistent_ref_returns_tool_error` passed for both transports with tool-level `Unknown source ref` and `Action: pass a ref returned by search.`.
- Invalid `read(ref="not-a-ref")`: `TestReadSmoke::test_malformed_ref_returns_tool_error` passed for both transports with tool-level `Unknown source ref` and `Action: pass a ref returned by search.`.
- Invalid `drill(ref="not-a-ref")`: `TestDrillSmoke::test_malformed_ref_returns_tool_error` passed for both transports with tool-level `Unknown source ref` and `Action: pass a ref returned by search.`.

No-full-reindex audit:

- `dotmd index --force was not run`.
- No full TEI re-embedding, full FTS rebuild, vector rebuild, metadata chunk rebuild, or graph rebuild was run.
