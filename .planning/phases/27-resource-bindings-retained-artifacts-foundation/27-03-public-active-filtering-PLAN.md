---
phase: "27"
plan: "03"
type: tdd
wave: 3
depends_on:
  - "27-01"
  - "27-02"
files_modified:
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/test_fusion.py
  - backend/tests/api/test_service_search.py
  - backend/tests/mcp/test_search_tool.py
autonomous: true
requirements: ["R1", "R2", "R8"]
requirements_addressed: ["R1", "R2", "R8"]
must_haves:
  truths:
    - "D-01: Active bindings are the public visibility gate."
    - "D-03: Diagnostics/counts are allowed; inactive browsing is not."
    - "D-05: Retained inactive artifacts must not leak through normal public output."
    - "D-11: Mandatory visibility filtering belongs in DotMDService result hydration/public output."
    - "D-12: Graph engines may return retained chunks internally; service drops inactive chunks before public output."
    - "D-13: No graph inactive-state schema is required for this public filter."
    - "D-14: Telegram deleted_upstream metadata is not modeled as resource unbind in this phase."
    - "D-15: No Telegram recycle bin or inactive Telegram browsing is added."
    - "Review feedback: active filtering depends on Plan 01 backfill and must reject inactive refs before filesystem fallback."
    - "Review feedback: fixed top_k * 3 over-fetch is replaced by a named active-filter pool policy that filters before reranking and logs underfill."
    - "Full-reindex answer: this plan changes public filtering only and does not rebuild indexes."
---

# Phase 27 Plan 03: Public Active Filtering

<objective>
Enforce active resource bindings at the public search/read/drill boundary so
retained inactive artifacts can remain in storage and internal search engines
without leaking to MCP/API callers.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Semantic/FTS/graph candidates leak inactive refs through fusion hydration | HIGH | Service filters candidate chunk IDs through active provenance before reranking and public `SearchResult` creation. |
| Filtering after fixed top-k starves active results when inactive candidates dominate | HIGH | Use a named active-filter candidate pool policy and log underfill when active candidates are insufficient. |
| `read(ref)` reads an inactive filesystem source because file exists or chunks remain retained | HIGH | Ref resolution requires an active binding before filesystem fallback, frontmatter, or chunk ranges. |
| Phase 26 synthetic filesystem fallback bypasses binding checks | HIGH | Tests cover inactive binding plus present file and missing `source_documents` row. |
| MCP errors become confusing protocol failures | MEDIUM | Preserve existing `ValueError` to tool-level error path with `Action: pass a ref returned by search.` |
| Service calls reload indexes per request | HIGH | Reuse initialized pipeline/stores; do not call `load_index()` from search/read/drill. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Filter search candidates by active bindings before rerank and hydration</title>
<name>Filter search candidates by active bindings before rerank and hydration</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/test_fusion.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_fusion.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Add active-binding filtering to public search result hydration before reranking.

Concrete target state:
- Define `ACTIVE_FILTER_OVERFETCH_FACTOR = 5` in `backend/src/dotmd/api/service.py` or an adjacent search constants location.
- Compute an active-filter candidate pool size as:
  `active_pool_size = max(pool_size, top_k * ACTIVE_FILTER_OVERFETCH_FACTOR, top_k + 50)`.
- Pass `active_pool_size` to the fused candidate collection path so semantic,
  FTS5, and graph-direct engines all get enough candidates for filtering.
- Filter fused candidate chunk IDs through
  `metadata_store.get_active_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`.
- Filtering occurs before reranking and before public `SearchResult` objects are returned.
- Reranker receives only active candidates. If inactive candidates are removed,
  rerank `min(pool_size, len(active_candidates))` candidates.
- `build_search_results()` may accept an optional precomputed `provenance_map`
  or service may pass only active candidate IDs; either way, inactive candidates
  must not hydrate into public results.
- If active results underfill `top_k`, return the active results found and log a
  warning containing `active filter underfilled` plus active/inactive candidate counts.
- If a candidate lacks active provenance because its binding is inactive, skip
  it; if it lacks any provenance due to an invariant violation, preserve the
  existing missing-provenance hard error for active strategy safety.
- Add tests:
  - fused list contains inactive chunks before active chunks and public results
    still return the later active refs;
  - inactive candidate ratio above 80 percent does not return inactive refs and
    logs the underfill warning if fewer than `top_k` active candidates exist;
  - reranker mock receives only active chunk IDs;
  - graph-direct candidate path uses the same filter.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `ACTIVE_FILTER_OVERFETCH_FACTOR`.
- `backend/src/dotmd/api/service.py` contains `top_k + 50` or an equivalent non-fixed minimum candidate cushion.
- `backend/src/dotmd/api/service.py` contains `get_active_chunk_provenance_for_chunk_ids`.
- `backend/src/dotmd/api/service.py` filters active candidates before calling `rerank`.
- `backend/src/dotmd/api/service.py` contains `active filter underfilled`.
- `backend/tests/api/test_service_search.py` contains `inactive` and asserts inactive results are excluded from `service.search`.
- `backend/tests/api/test_service_search.py` covers an inactive-skewed candidate pool with active fallback candidates beyond the first `top_k * 3` positions or explicitly asserts the new pool policy.
- `backend/tests/api/test_service_search.py` asserts the reranker mock only sees active chunk IDs.
- Public `SearchResult` fixtures still contain `ref` and do not contain `file_paths`.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Require active bindings for read and drill refs before filesystem fallback</title>
<name>Require active bindings for read and drill refs before filesystem fallback</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/mcp/test_search_tool.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/api/test_service_search.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Make `read(ref)` and `drill(ref)` reject inactive bindings even when retained
chunks and filesystem files still exist.

Concrete target state:
- Add service helper such as `_require_active_source_document(ref: str) -> SourceDocument`.
- It must parse the ref, resolve `source_documents`, and require an active
  resource binding for `(namespace, document_ref)` or equivalent resource ref.
- The active binding check happens before:
  - `_resolve_source_document()` synthetic filesystem fallback;
  - `_filesystem_path_for_source()` `Path.exists()` checks;
  - frontmatter reads;
  - chunk range reads;
  - drill metadata assembly.
- If `source_documents` has a row but the binding is missing or inactive, raise
  `ValueError(f"Unknown source ref: {ref}")`.
- If `source_documents` has no row and the ref is a filesystem ref whose file is
  present on disk, first check for an active binding. If the binding is missing
  or inactive, raise `ValueError(f"Unknown source ref: {ref}")` and do not create
  a synthetic `SourceDocument`.
- Active backfilled filesystem refs with active bindings may still use the
  Phase 26 filesystem fallback for source-document reconstruction when needed.
- Keep unsupported namespaces rejected until later source-specific readers are implemented.
- MCP `read` and `drill` continue converting `ValueError` into tool-level errors containing:
  `Action: pass a ref returned by search.`
- Do not add inactive browsing flags such as `include_inactive`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `_require_active` or an equivalently named active resolver.
- `backend/src/dotmd/api/service.py` raises `Unknown source ref` for inactive bindings.
- `backend/tests/api/test_service_search.py` contains a test where retained chunks exist but `service.read(ref)` rejects an inactive binding.
- `backend/tests/api/test_service_search.py` contains a test where an inactive filesystem binding and present on-disk file still make `service.read(ref)` raise `ValueError`.
- `backend/tests/api/test_service_search.py` contains a test where no `source_documents` row exists, the file exists, and a missing/inactive binding prevents synthetic fallback.
- `backend/tests/api/test_service_search.py` contains a test where `service.drill(ref)` rejects an inactive binding.
- `backend/tests/mcp/test_search_tool.py` still asserts `Action: pass a ref returned by search.` for rejected read/drill refs.
- `backend/src/dotmd/api/service.py` does not contain `load_index(` inside `search`, `read`, or `drill`.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/mcp/test_search_tool.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="tdd">
<title>Expose binding diagnostics without inactive content browsing</title>
<name>Expose binding diagnostics without inactive content browsing</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Add the Phase 27 diagnostics/counts allowed by D-03 without adding any public
inactive-content retrieval mode.

Concrete target state:
- Add a service diagnostic method or extend existing status output with counts
  keyed exactly:
  `active`, `inactive`, `retained`, `reused`.
- `active` and `inactive` derive from resource binding counts.
- `retained` counts inactive bindings with retained provenance/chunks or returns
  a clearly documented retained-artifact count that tests can assert.
- `reused` comes from the Plan 02 rebind diagnostic when available and is `0`
  when no rebind has happened.
- Do not duplicate `source_documents` metadata into public diagnostics. The
  diagnostic source-of-truth rule is:
  - binding activity from `resource_bindings`;
  - current document metadata/fingerprints from `source_documents`;
  - retained artifact counts from provenance/chunk/vector/FTS tables.
- Do not add `include_inactive`, recycle-bin search, inactive `read`, or a
  list-inactive-content MCP tool.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` or `backend/src/dotmd/storage/metadata.py` contains `active`, `inactive`, `retained`, and `reused` count keys in one diagnostic path.
- Tests assert the diagnostic path returns active/inactive/retained counts.
- Diagnostics tests assert `source_documents` metadata values are not duplicated from `resource_bindings.metadata_json`.
- `rg "include_inactive|recycle|inactive search|list_inactive" backend/src/dotmd backend/tests` returns no new public inactive browsing surface except tests/comments explicitly asserting absence.
- `cd backend && uv run pytest tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q
```
</verification>

<success_criteria>
- Search hides inactive retained chunks even if engines produce them internally.
- Active filtering runs before reranking and public hydration.
- Read/drill reject inactive refs before loading filesystem content.
- Phase 26 filesystem fallback cannot bypass active-binding enforcement.
- Diagnostics expose counts but no inactive browsing feature exists.
- Public MCP/API behavior remains source-ref-first.
</success_criteria>
