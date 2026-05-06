---
phase: 26-source-ref-first-read-search-contract-cleanup
reviewed: 2026-05-06T12:46:02Z
depth: standard
files_reviewed: 19
files_reviewed_list:
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/mcp_server.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/storage/metadata.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/api/test_service_search.py
  - backend/tests/cli/test_search_output.py
  - backend/tests/e2e/conftest.py
  - backend/tests/e2e/test_mcp_smoke.py
  - backend/tests/mcp/test_search_tool.py
  - backend/tests/test_fusion.py
  - backend/tests/test_hybrid_bm25.py
  - docs/architecture.md
  - docs/mcp.md
  - docs/reranker-benchmark-methodology.md
  - docs/source-adapter-architecture-panel-review.md
  - docs/source-adapter-architecture.md
findings:
  critical: 2
  warning: 0
  info: 0
  total: 2
status: issues_found
---

# Phase 26: Code Review Report

**Reviewed:** 2026-05-06T12:46:02Z
**Depth:** standard
**Files Reviewed:** 19
**Status:** issues_found

## Summary

Reviewed the Phase 26 ref-first search/read contract changes across service, MCP, fusion, metadata storage, tests, and architecture docs. The main defects are in the new public `ref` boundary: `filesystem:` refs are trusted based on filesystem existence instead of index provenance, and search now hard-fails when old or partially migrated chunks lack source provenance.

## Critical Issues

### CR-01: Arbitrary Existing Filesystem Paths Are Accepted As Source Refs

**Classification:** BLOCKER

**File:** `backend/src/dotmd/api/service.py:666`

**Issue:** `_resolve_source_document()` fabricates a `SourceDocument` for any `filesystem:<path>` ref when `Path(document_ref).exists()` is true. `read()` and `drill()` then call `_read_frontmatter()` on that path before proving the ref came from `source_documents` or any indexed `chunk_file_paths_<strategy>` row. In the MCP/HTTP path, a caller can probe arbitrary files visible to the dotMD process with refs like `filesystem:/etc/passwd`; `drill()` returns metadata for existing non-indexed files, and any file that begins with YAML frontmatter can disclose that frontmatter. This violates the documented contract that `read`/`drill` only accept refs returned by `search`.

**Fix:**

Do not use raw filesystem existence as authorization. Resolve refs only through `source_documents`; if a legacy fallback is still required, first prove the resolved path is present in the active index holder table before reading the file or returning metadata.

```python
def _resolve_source_document(self, ref: str) -> SourceDocument:
    namespace, document_ref = self._parse_ref(ref)
    document = self._pipeline.metadata_store.get_source_document(namespace, document_ref)
    if document is not None:
        return document
    raise ValueError(f"Unknown source ref: {ref}")
```

If keeping a temporary legacy fallback, gate it on indexed rows, not `path.exists()`:

```python
resolved = Path(document_ref).resolve()
count = self._pipeline.metadata_store.get_chunk_count_for_file(
    self._settings.chunk_strategy,
    str(resolved),
)
if count <= 0:
    raise ValueError(f"Unknown source ref: {ref}")
```

### CR-02: Search Crashes On Chunks Without New Source Provenance

**Classification:** BLOCKER

**File:** `backend/src/dotmd/search/fusion.py:296`

**Issue:** `build_search_results()` now raises `ValueError` whenever a top chunk has no `chunk_source_provenance_<strategy>` row. Phase 26 docs explicitly say no full rebuild was required, but unchanged chunks in an existing index can still lack this new provenance table/rows unless they were re-chunked after the source-aware migration. Those chunks can still be returned by semantic, FTS5, or graph retrieval, causing the whole `search()` call to fail instead of returning results. MCP wraps that as `Search failed`, so one unbackfilled top hit can break normal search.

**Fix:**

Add an explicit migration/backfill before enforcing this invariant, and run it at startup or before first search for the active strategy. The existing `backfill_missing_source_provenance_from_file_paths()` helper is the right direction, but it must be invoked and verified before `build_search_results()` treats missing provenance as fatal.

```python
strategy = self._settings.chunk_strategy
store = self._pipeline.metadata_store
missing = store.count_missing_source_provenance(strategy)
if missing:
    inserted = store.backfill_missing_source_provenance_from_file_paths(
        strategy,
        dry_run=False,
    )
    if inserted != missing:
        logger.warning(
            "source provenance backfill incomplete: missing=%d inserted=%d",
            missing,
            inserted,
        )
```

Keep the hard failure after the migration has run, or degrade per-result by skipping only the malformed chunk and logging the invariant violation.

---

_Reviewed: 2026-05-06T12:46:02Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: standard_
