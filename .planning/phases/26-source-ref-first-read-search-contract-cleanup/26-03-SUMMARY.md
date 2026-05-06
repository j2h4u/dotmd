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
