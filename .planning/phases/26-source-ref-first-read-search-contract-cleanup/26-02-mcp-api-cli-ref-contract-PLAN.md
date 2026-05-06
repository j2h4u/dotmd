---
phase: "26"
plan: "02"
type: execute
wave: 2
depends_on:
  - "26-01"
files_modified:
  - backend/src/dotmd/mcp_server.py
  - backend/src/dotmd/api/server.py
  - backend/src/dotmd/cli.py
  - backend/tests/mcp/test_search_tool.py
  - backend/tests/cli/test_search_output.py
  - backend/tests/e2e/test_mcp_smoke.py
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-02: Public MCP/API callers pass ref, not namespace/document_ref objects."
    - "D-03: Do not add display_path, source_uri, or deprecated file_paths to public search hits just to preserve old readability."
    - "D-04: Public search responses remove file_paths immediately."
    - "D-05: Target MCP search hit shape is {ref, heading?, snippet, score}."
    - "D-06: Future prettier labels should be neutral additive title fields, not filesystem-path-shaped identities."
    - "D-07: MCP/service read input is ref."
    - "D-08: Keep drill separate and expose drill(ref)."
    - "D-09: Intended agent workflow is search(query) -> ref, drill(ref) -> frontmatter/entities/chunk_count, read(ref,start,end) -> text chunks."
    - "D-10: Do not merge drill into read."
    - "D-12: Public MCP/API contracts become source-ref-first."
    - "D-17: This plan does not require a full reindex."
    - "D-18: This plan does not rebuild embeddings, FTS, vectors, metadata chunks, or graph data."
---

# Phase 26 Plan 02: MCP/API/CLI Ref Contract

<objective>
Update all public agent and developer-facing surfaces so the contract is
`search -> ref -> drill/read`, not `search -> file_paths -> read(file_path)`.

Full-reindex answer: this plan is a surface/schema/test change. It must not
touch indexed data or require reindexing.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| MCP tools still teach agents to use file paths | HIGH | Rewrite tool schemas, output models, instructions, and docstrings; tests assert `file_paths`/`file_path` are absent from public MCP surfaces. |
| `read` becomes overloaded with metadata and chunk content | MEDIUM | Keep `read(ref,start,end)` for content ranges and add `drill(ref)` for metadata. |
| API/CLI lag behind MCP and preserve path-first public behavior | MEDIUM | Update FastAPI and CLI outputs in the same wave unless inspection proves a surface is private/internal. |
| Existing e2e smoke fails due pinned tool list drift | HIGH | Update `EXPECTED_TOOLS`, required result fields, read keys, and add drill smoke coverage. |
| Error messages leave callers stuck after breaking change | MEDIUM | Error text should say to pass `ref` from a search result. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Change MCP search/read schemas to ref and add drill(ref)</title>
<name>Change MCP search/read schemas to ref and add drill(ref)</name>
<read_first>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/test_search_tool.py`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-01-core-ref-model-and-service-resolution-PLAN.md`
</read_first>
<files>
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Update MCP output models, tool parameters, instructions, and tests to the
ref-first contract.

Concrete target state:
- `SearchHit` fields are exactly:
  - `ref: str`
  - `heading: str | None = None`
  - `snippet: str`
  - `score: float`
- `SearchHit` serializer emits `ref`, `snippet`, `score`, and optional
  `heading`; it does not emit `file_paths`, `file_path`, `display_path`, or
  `source_uri`.
- `ReadResult` fields are:
  - `ref: str`
  - `total_chunks: int`
  - `frontmatter: dict[str, Any]`
  - `chunks: list[ReadChunk]`
- `read_document` parameter is named `ref` and has description
  `Source ref from a search result.`
- `read_document` calls `service.read(ref, start, end)`.
- Add `DrillResult` with at least `ref`, `title`, `source_uri`,
  `document_type`, `parser_name`, `frontmatter`, and `total_chunks`.
- Add MCP tool named exactly `drill` that accepts `ref` and calls
  `service.drill(ref)`.
- Rewrite `_INSTRUCTIONS` and tool docstrings so they explicitly say:
  `search(query) -> ref`, `drill(ref)`, and `read(ref, start, end)`.
- Error messages for read/drill say: `Action: pass a ref returned by search.`
- Update `backend/tests/mcp/test_search_tool.py` to assert:
  - search output schema has `ref` and no `file_paths`;
  - search tool output has `ref`;
  - search tool output has no `file_paths` and no `file_path`;
  - read input uses `ref`;
  - read output has `ref` and no `file_path`;
  - drill tool exists and returns metadata for `ref`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/mcp_server.py` contains `class SearchHit` and `ref: str`.
- `backend/src/dotmd/mcp_server.py` contains `name="drill"`.
- `backend/src/dotmd/mcp_server.py` contains `service.drill`.
- `backend/src/dotmd/mcp_server.py` contains `search(query) -> ref`.
- `backend/src/dotmd/mcp_server.py` does not contain `Only pass file_paths values from search results`.
- `backend/tests/mcp/test_search_tool.py` contains `payload["ref"]`.
- `backend/tests/mcp/test_search_tool.py` contains `assert "file_paths" not in payload`.
- `backend/tests/mcp/test_search_tool.py` contains `assert "file_path" not in payload`.
- `backend/tests/mcp/test_search_tool.py` contains `"drill"`.
- `cd backend && uv run pytest tests/mcp/test_search_tool.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Update FastAPI and CLI public outputs</title>
<name>Update FastAPI and CLI public outputs</name>
<read_first>
- `backend/src/dotmd/api/server.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/cli.py`
- `backend/tests/cli/test_search_output.py`
</read_first>
<files>
- `backend/src/dotmd/api/server.py`
- `backend/src/dotmd/cli.py`
- `backend/tests/cli/test_search_output.py`
</files>
<action>
Update non-MCP public surfaces so they do not preserve path-first identity.

Concrete target state:
- Enumerate `backend/src/dotmd/api/server.py` route decorators with:
  `rg -n "@app\\.(get|post|put|delete)|@router\\.(get|post|put|delete)" backend/src/dotmd/api/server.py`.
- Current Phase 26 API scope is:
  - search route, if present: response items must use `ref`, not `file_path` or
    `file_paths`;
  - read route, if present: request parameter/body key must be `ref`, not
    `file_path`;
  - no new FastAPI route should be invented solely for `drill` unless
    `api/server.py` already exposes a matching service facade pattern.
- If no FastAPI read/search routes exist, record that finding in the Plan 02
  implementation summary and leave FastAPI unchanged.
- CLI `dotmd search` prints the ref on the result header line:
  `[{i}] {r.ref}`.
- CLI search no longer formats `(+N more: ...)` holder paths in public output.
- CLI can still show heading, score, engines, and snippet.
- Update `backend/tests/cli/test_search_output.py` so fixture
  `SearchResult` objects use `ref`.
- If API server has no read route or only delegates through service without
  custom schemas, add a short test/doc note in the implementation summary rather
  than inventing a new API surface.
</action>
<acceptance_criteria>
- `backend/src/dotmd/cli.py` contains `r.ref`.
- `backend/src/dotmd/cli.py` does not contain `(+{len(paths) - 1} more`.
- `backend/tests/cli/test_search_output.py` contains `ref=`.
- `backend/tests/cli/test_search_output.py` does not construct `SearchResult(file_paths=`.
- Plan 02 implementation summary contains the output or finding from `rg -n "@app\\.(get|post|put|delete)|@router\\.(get|post|put|delete)" backend/src/dotmd/api/server.py`.
- `rg "file_paths|file_path" backend/src/dotmd/api/server.py backend/src/dotmd/cli.py backend/tests/cli/test_search_output.py` shows no public search/read contract uses, except comments explicitly saying internal holder paths are not public.
- `cd backend && uv run pytest tests/cli/test_search_output.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Pin live MCP smoke to search-ref-drill-read workflow</title>
<name>Pin live MCP smoke to search-ref-drill-read workflow</name>
<read_first>
- `backend/tests/e2e/test_mcp_smoke.py`
- `backend/tests/e2e/conftest.py`
- `backend/src/dotmd/mcp_server.py`
</read_first>
<files>
- `backend/tests/e2e/test_mcp_smoke.py`
</files>
<action>
Update the e2e MCP smoke contract to match the new public surface.

Concrete target state:
- `EXPECTED_TOOLS` is exactly `{"search", "read", "drill", "feedback"}`.
- `REQUIRED_SEARCH_RESULT_FIELDS` is exactly `{"ref", "snippet", "score"}`.
- `EXPECTED_READ_KEYS` is exactly `{"ref", "total_chunks", "frontmatter", "chunks"}`.
- Search tests assert `results[0]["ref"]` is a string and starts with
  `filesystem:` for the current production filesystem source.
- Metadata-only read uses:
  `{"name": "read", "arguments": {"ref": ref}}`.
- Ranged read uses:
  `{"name": "read", "arguments": {"ref": ref, "start": 0, "end": 3}}`.
- Add a drill smoke class that calls `drill(ref)` and asserts:
  - no tool error;
  - structured result is a dict;
  - keys include `ref`, `frontmatter`, and `total_chunks`;
  - returned `ref` equals the input ref.
- Invalid/nonexistent ref smoke is deterministic:
  - `read(ref="filesystem:/nonexistent/file.md")` returns a tool-level error,
    not a JSON-RPC/protocol-level error;
  - the tool-level error text contains `Unknown source ref`;
  - the tool-level error text contains
    `Action: pass a ref returned by search.`;
  - malformed `read(ref="not-a-ref")` follows the same tool-level error
    contract and contains `Unknown source ref`.
</action>
<acceptance_criteria>
- `backend/tests/e2e/test_mcp_smoke.py` contains `"drill"`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `REQUIRED_SEARCH_RESULT_FIELDS: frozenset[str] = frozenset({"ref", "snippet", "score"})`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `{"ref": ref`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `filesystem:/nonexistent/file.md`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `not-a-ref`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `Unknown source ref`.
- `backend/tests/e2e/test_mcp_smoke.py` contains `Action: pass a ref returned by search.`
- `backend/tests/e2e/test_mcp_smoke.py` does not contain `results[0]["file_paths"]`.
- `backend/tests/e2e/test_mcp_smoke.py` does not contain `"file_path": file_path`.
- `cd backend && uv run pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider` exits 0 when run against a live container/test harness.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q
cd backend && uv run pytest tests/e2e/test_mcp_smoke.py -q -p no:cacheprovider
cd backend && uv run pyright
```

If the e2e test requires refreshed container code, batch the restart once after
all implementation changes, then rerun the smoke.
</verification>

<success_criteria>
- MCP search results expose `ref`, not `file_paths`.
- MCP read accepts and returns `ref`, not `file_path`.
- MCP exposes `drill(ref)`.
- CLI/API public search/read surfaces no longer preserve path-first identity.
- Live MCP smoke is pinned to `search -> ref -> drill/read`.
</success_criteria>
