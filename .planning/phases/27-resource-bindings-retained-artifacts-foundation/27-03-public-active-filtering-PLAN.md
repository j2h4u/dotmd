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
| Semantic/FTS/graph candidates leak inactive refs through fusion hydration | HIGH | Service filters candidate chunk IDs through active provenance before public `SearchResult` creation. |
| Filtering after top-k causes empty/underfilled results despite active fallback candidates | MEDIUM | Over-fetch candidates before filtering and cap only after active hydration. |
| `read(ref)` reads an inactive filesystem source because file exists or chunks remain retained | HIGH | Ref resolution requires an active binding before reading frontmatter or chunk ranges. |
| MCP errors become confusing protocol failures | MEDIUM | Preserve existing `ValueError` to tool-level error path with `Action: pass a ref returned by search.` |
| Service calls reload indexes per request | HIGH | Reuse initialized pipeline/stores; do not call `load_index()` from search/read/drill. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Filter search candidates by active bindings before public hydration</title>
<name>Filter search candidates by active bindings before public hydration</name>
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
Add active-binding filtering to public search result hydration.

Concrete target state:
- `DotMDService._execute_search()` or a narrow helper filters fused candidate
  chunk IDs through `metadata_store.get_active_chunk_provenance_for_chunk_ids(strategy, chunk_ids)`.
- Filtering occurs before public `SearchResult` objects are returned.
- `build_search_results()` may accept an optional precomputed `provenance_map`
  or service may pass only active candidate IDs; either way, inactive candidates
  must not hydrate into public results.
- Semantic, FTS5, and graph-direct engines may still return inactive retained
  chunk IDs internally.
- Over-fetch behavior:
  - when filtering is active, collect at least `max(pool_size, top_k * 3)` fused candidates before final active filtering;
  - return at most `top_k` public results after filtering.
- If a candidate lacks active provenance because its binding is inactive, skip
  it; if it lacks any provenance due to an invariant violation, preserve the
  existing missing-provenance hard error for active strategy safety.
- Add tests:
  - fused list contains inactive chunk first and active chunk second;
  - public results contain only the active ref;
  - inactive retained chunk still exists in metadata fixture;
  - graph-direct candidate path uses the same filter.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `get_active_chunk_provenance_for_chunk_ids`.
- `backend/src/dotmd/api/service.py` contains `top_k * 3` or an equivalent over-fetch constant/comment.
- `backend/tests/api/test_service_search.py` contains `inactive` and asserts inactive results are excluded from `service.search`.
- `backend/tests/test_fusion.py` or `backend/tests/api/test_service_search.py` covers an inactive first candidate and active fallback candidate.
- Public `SearchResult` fixtures still contain `ref` and do not contain `file_paths`.
- `cd backend && uv run pytest tests/api/test_service_search.py tests/test_fusion.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Require active bindings for read and drill refs</title>
<name>Require active bindings for read and drill refs</name>
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
- `read(ref)` and `drill(ref)` call this active resolver before reading
  frontmatter, counting chunks, or reading chunk ranges.
- Existing Phase 26 fallback for filesystem refs without `source_documents`
  must not bypass active binding state. If the active binding is missing or
  inactive, raise `ValueError(f"Unknown source ref: {ref}")`.
- Keep unsupported namespaces rejected until later source-specific readers are
  implemented.
- MCP `read` and `drill` continue converting `ValueError` into tool-level
  errors containing:
  `Action: pass a ref returned by search.`
- Do not add inactive browsing flags such as `include_inactive`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` contains `_require_active` or an equivalently named active resolver.
- `backend/src/dotmd/api/service.py` raises `Unknown source ref` for inactive bindings.
- `backend/tests/api/test_service_search.py` contains a test where retained chunks exist but `service.read(ref)` rejects an inactive binding.
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
- `retained` counts retained inactive documents/chunks or returns a clearly
  documented count that tests can assert.
- `reused` may be a cumulative run-local diagnostic from Plan 02 or zero when
  no rebind has happened.
- Do not add `include_inactive`, recycle-bin search, inactive `read`, or a
  list-inactive-content MCP tool.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` or `backend/src/dotmd/storage/metadata.py` contains `active`, `inactive`, `retained`, and `reused` count keys in one diagnostic path.
- Tests assert the diagnostic path returns active/inactive/retained counts.
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
- Read/drill reject inactive refs before loading filesystem content.
- Diagnostics expose counts but no inactive browsing feature exists.
- Public MCP/API behavior remains source-ref-first.
</success_criteria>
