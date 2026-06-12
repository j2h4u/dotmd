---
phase: 16-content-dedup-schema
plan: 05
subsystem: search/api/cli/mcp
tags: [search, file_paths, m2m, batch-hydration, clean-break, cli, mcp]
dependency_graph:
  requires: [16-01, 16-04]
  provides: [search-api-file_paths, cli-renderer-locked, mcp-file_paths-array]
  affects: [16-02, 16-06]
tech_stack:
  added: []
  patterns:
    - Pydantic field_validator for sort-on-assignment (file_paths lex order)
    - batch M2M hydration (single SELECT IN per strategy per search call)
    - _execute_search extracted from service.search for testability
    - --index-dir global CLI option propagated via click context
key_files:
  created: []
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/search/fusion.py
    - backend/src/dotmd/api/service.py
    - backend/src/dotmd/cli.py
    - backend/src/dotmd/mcp_server.py
    - backend/tests/api/test_search_result_shape.py
    - .planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
decisions:
  - "SearchResult.file_paths auto-sorted via field_validator(mode='before') — lex order enforced at model construction"
  - "fusion.py uses get_file_paths_for_chunk_ids batch helper — single SELECT per strategy per search call (Review-LOW-12)"
  - "_execute_search extracted from DotMDService.search — enables patch.object test injection without full engine stack"
  - "CLI --index-dir global option added and propagated via click context to all subcommands"
  - "CLI locked format: single=[i] path; multi=[i] path_0  (+N-1 more: path_1, …) in sorted-lex order (Review-LOW-11)"
  - "service.status() queries chunk_file_paths_* for total_files (chunks_* no longer has file_path column)"
metrics:
  duration: "~45m"
  completed: "2026-04-25"
  tasks: 2
  files_created: 0
  files_modified: 7
---

# Phase 16 Plan 05: Search API Clean Break Summary

Propagated `file_paths: list[Path]` (sorted lex) through every search consumer: fusion hydration via single batch SELECT, CLI printer with locked multi-holder format, MCP server array output, and service facade.

## Final SearchResult Schema

```python
class SearchResult(BaseModel):
    chunk_id: str
    file_paths: list[Path]  # sorted lexicographically at construction (field_validator)
    heading_path: str
    snippet: str
    fused_score: float
    semantic_score: float | None = None
    keyword_score: float | None = None
    graph_score: float | None = None
    graph_direct_score: float | None = None
    matched_engines: list[str]
    # NO file_path singular attribute — clean break (Decision #2)
```

## CLI Rendering Format (Locked — Review-LOW-11)

Single holder:
```
  [1] /path/to/file.md
```

Multi holder:
```
  [1] /a/first.md  (+2 more: /m/second.md, /z/third.md)
```

Sort order: lexicographic (from `file_paths` field_validator). Rationale: narrow-terminal readable, surfaces full list on demand.

## MCP Response Example

```json
{
  "file_paths": ["/a/first.md", "/m/second.md", "/z/third.md"],
  "heading": "# Section Title",
  "snippet": "...",
  "score": 0.923,
  "matched_engines": ["semantic", "keyword"],
  "start_time": null
}
```

## Batch Hydration (Review-LOW-12)

`fusion.py` calls `metadata_store.get_file_paths_for_chunk_ids(strategy, top_ids)` once per search call — a single `SELECT chunk_id, file_path FROM chunk_file_paths_{strategy} WHERE chunk_id IN (?, ?, …)`. Zero per-chunk round-trips. The sort invariant is asserted under DEBUG.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] TrickleIndexer args swapped in service.py**
- **Found during:** Task 1 test run — `test_search_returns_file_paths_list` failed with `AttributeError: 'IndexingPipeline' object has no attribute 'index_db_path'`
- **Issue:** `service.py` called `TrickleIndexer(self._pipeline, self._settings)` but the signature is `TrickleIndexer(settings, pipeline)`.
- **Fix:** Swapped args to `TrickleIndexer(self._settings, self._pipeline)`.
- **Files modified:** `backend/src/dotmd/api/service.py`
- **Commit:** `8e7187b`

**2. [Rule 1 - Bug] P6 batch-hydration test skeleton had incomplete table DDL**
- **Found during:** Task 1 `test_batch_hydration_single_query_per_strategy`
- **Issue:** Test's inline DDL created `chunks_{strategy}` with only `(chunk_id, text)` — missing `heading_hierarchy` and `level` columns that `insert_chunk` inserts into.
- **Fix:** Added missing columns to test DDL (`heading_hierarchy TEXT NOT NULL DEFAULT '[]', level INTEGER NOT NULL DEFAULT 0`).
- **Files modified:** `backend/tests/api/test_search_result_shape.py`
- **Commit:** `8e7187b`

**3. [Rule 1 - Bug] P6 batch-hydration test patched `conn_raw.execute` on C extension type**
- **Found during:** Task 1 — C extension sqlite3.Connection doesn't allow attribute assignment
- **Issue:** Test used `conn_raw.execute = counting_execute` directly on `sqlite3.Connection` (C type). The `SQLiteMetadataStore` wraps it with `_ConnProxy` (P1 fix), so `store._conn.execute` is the patchable surface.
- **Fix:** Changed test to patch `store._conn.execute` instead.
- **Files modified:** `backend/tests/api/test_search_result_shape.py`
- **Commit:** `8e7187b`

**4. [Rule 2 - Missing functionality] `_execute_search` method extracted from `DotMDService.search`**
- **Found during:** Task 1 service tests — tests patched `service._execute_search` which didn't exist
- **Issue:** P6 test skeletons assumed `DotMDService.search` would delegate to `_execute_search` for testability. The method didn't exist.
- **Fix:** Extracted the retrieval + fusion + reranking pipeline into `_execute_search`. `search()` now delegates to it after query expansion and pool sizing.
- **Files modified:** `backend/src/dotmd/api/service.py`
- **Commit:** `8e7187b`

**5. [Rule 2 - Missing functionality] `--index-dir` global CLI option added**
- **Found during:** Task 2 CLI tests — `runner.invoke(main, ["--index-dir", str(tmp_path), ...])` failed with `No such option: --index-dir`
- **Issue:** The CLI had no `--index-dir` option; tests require it to point to a temp index for isolation.
- **Fix:** Added `--index-dir` option to the `main` group with `envvar="DOTMD_INDEX_DIR"` and `_get_service_from_ctx` helper to propagate it to subcommands.
- **Files modified:** `backend/src/dotmd/cli.py`
- **Commit:** `9549016`

## Known Stubs

None.

## Threat Flags

No new security-relevant surface beyond the plan's threat model. T-16-24 (O(K) per-chunk hydration) is mitigated by the batch SELECT. T-16-16 (exposing all holder paths) is accepted per Decision #1.

## Self-Check: PASSED

**Files modified:**
- `backend/src/dotmd/core/models.py` — EXISTS
- `backend/src/dotmd/search/fusion.py` — EXISTS
- `backend/src/dotmd/api/service.py` — EXISTS
- `backend/src/dotmd/cli.py` — EXISTS
- `backend/src/dotmd/mcp_server.py` — EXISTS
- `backend/tests/api/test_search_result_shape.py` — EXISTS
- `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md` — EXISTS

**Commits:**
- `8e7187b` — feat(16-05): Task 1: EXISTS
- `9549016` — feat(16-05): Task 2: EXISTS

**Test results:** 13 P5 tests GREEN (8 Task 1 + 5 Task 2). 31 P1+P3+P4 Wave-1 tests still GREEN (no regression).
