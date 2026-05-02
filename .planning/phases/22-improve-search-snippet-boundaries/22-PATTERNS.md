# Phase 22 Patterns — Improve Search Snippet Boundaries

## Closest Analogs

### `backend/src/dotmd/search/fusion.py`

Role: search result fusion and final result hydration.

Relevant functions:

- `_extract_best_snippet(text, query, length=300)`
- `_truncate(text, length)`
- `build_search_results(...)`

Pattern to preserve:

- Keep snippet extraction as a pure private helper.
- Keep `build_search_results()` responsible for applying the helper to hydrated
  chunk text.
- Do not alter RRF scoring, reranker blending, engine score attribution, or
  `SearchResult` shape.

### `backend/tests/test_fusion.py`

Role: focused tests for search/fusion helper behavior.

Pattern to extend:

- Add pure-function unit tests in this file.
- Import the private helper directly for focused coverage, as existing tests
  already import implementation details when validating internal math.

### `backend/src/dotmd/mcp_server.py`

Role: MCP presentation layer.

Relevant function:

- `_format_result(r)` strips frontmatter and timestamps from `r.snippet`.

Pattern to preserve:

- Keep MCP formatting separate from snippet boundary selection.
- Do not add new MCP `search` parameters for Phase 22.

## Files Expected To Change

- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_fusion.py`
- `.planning/phases/22-improve-search-snippet-boundaries/22-01-snippet-boundary-extraction-SUMMARY.md`

## Verification Commands

- `cd backend && uv run pytest tests/test_fusion.py -q`
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py`
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py`
- `just test-mcp-remote`
