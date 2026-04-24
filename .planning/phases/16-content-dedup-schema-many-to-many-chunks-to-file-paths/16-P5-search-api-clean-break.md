---
phase: 16-content-dedup-schema
plan: 5
type: execute
wave: 3
depends_on: [16-P1]
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/search/fusion.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/cli.py
  - backend/src/dotmd/mcp_server.py
autonomous: true
requirements: [DEDUP-09]
must_haves:
  truths:
    - "`SearchResult.file_paths: list[Path]` replaces `file_path: Path` — no alias, no deprecation shim."
    - "`file_paths` is sorted lexicographically at the hydration layer; caller receives stable ordering."
    - "CLI result printer renders the list readably (format documented in the task)."
    - "MCP server emits `file_paths` as a JSON array of strings."
    - "Search hydration performs one JOIN per chunk_id via `chunk_file_paths_<strategy>` with the (file_path) index."
  artifacts:
    - path: backend/src/dotmd/core/models.py
      provides: "SearchResult and Chunk models with file_paths: list[Path]."
    - path: backend/src/dotmd/search/fusion.py
      provides: "_hydrate_results JOINs M2M to build file_paths list in sorted order."
    - path: backend/src/dotmd/api/service.py
      provides: "DotMDService.search returns SearchResult with file_paths."
    - path: backend/src/dotmd/cli.py
      provides: "CLI search result printer using file_paths."
    - path: backend/src/dotmd/mcp_server.py
      provides: "MCP search tool output carrying file_paths array."
  key_links:
    - from: backend/src/dotmd/search/fusion.py
      to: backend/src/dotmd/storage/metadata.py
      via: "get_file_paths_by_chunk_id (sorted lex)"
      pattern: "get_file_paths_by_chunk_id"
    - from: backend/src/dotmd/cli.py
      to: backend/src/dotmd/core/models.py
      via: "SearchResult.file_paths rendering"
      pattern: "file_paths"
    - from: backend/src/dotmd/mcp_server.py
      to: backend/src/dotmd/core/models.py
      via: "[str(p) for p in r.file_paths]"
      pattern: "file_paths"
---

<objective>
Replace the singular `file_path: Path` on `SearchResult` and `Chunk` with `file_paths: list[Path]` (sorted lex) as a clean break (Decisions #1 + #2). Update every consumer identified in the Research §Consumer Audit: fusion hydration, CLI printer, MCP server output, and any internal caller that touches the field.

Purpose: Deliver the user-facing value of this phase — identical content returns one search result with all holders exposed as a list — and honour the no-legacy-compat global rule with a clean break.

Output: Updated models, hydration, CLI/MCP output, and service facade tests proving the new shape.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@backend/src/dotmd/core/models.py
@backend/src/dotmd/search/fusion.py
@backend/src/dotmd/api/service.py
@backend/src/dotmd/cli.py
@backend/src/dotmd/mcp_server.py

<interfaces>
Consumer audit (from Research §Component Responsibilities):
- `cli.py:112`  — `f"[{i}] {r.file_path}"` → must render `r.file_paths`
- `cli.py:161` — status: `SELECT COUNT(DISTINCT file_path) FROM chunks_<strategy>` → must read from `chunk_file_paths_<strategy>`
- `service.py:369` — constructs SearchResult; shape update
- `mcp_server.py:118` — `"file_path": str(r.file_path)` → `"file_paths": [str(p) for p in r.file_paths]`
- `mcp_server.py:44` — docstring update
- `core/models.py:78` — Chunk.file_path → file_paths
- `core/models.py:130` — SearchResult.file_path → file_paths
- `fusion.py:202` — _hydrate_results

From P1 metadata: `get_file_paths_by_chunk_id(strategy, chunk_id) -> list[str]` returns paths sorted lex.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Update models and hydration layer</name>
  <files>backend/src/dotmd/core/models.py, backend/src/dotmd/search/fusion.py, backend/src/dotmd/api/service.py</files>
  <behavior>
    Core models:
    - `SearchResult.file_paths: list[Path]` (was `file_path: Path`). No alias.
    - `Chunk.file_paths: list[Path]` — single-element at creation time, populated to full set after hydration (per Research Open Q #3 recommendation: one model, wrap-in-list at creation).

    Fusion (_hydrate_results):
    - For each fused hit (chunk_id): call `metadata.get_file_paths_by_chunk_id(strategy, chunk_id)` and set `SearchResult.file_paths = [Path(p) for p in paths]`.
    - Sort order is enforced at the metadata layer (ORDER BY file_path) per Decision #1; fusion may additionally assert `result.file_paths == sorted(result.file_paths)` under DEBUG.
    - Graph-origin hits (graph_direct → chunk_ids) traverse the same hydration path — no separate code path.

    Service (`DotMDService.search`):
    - No logic change; only the SearchResult shape flows through. Verify the facade test.

    Tests (tests/api/test_search_result_shape.py):
    - test_file_paths_field_is_list: SearchResult.file_paths is a list[Path].
    - test_file_paths_sorted_lex: a chunk with holders ["z.md", "a.md", "m.md"] returns ["a.md", "m.md", "z.md"].
    - test_single_holder_returns_single_element_list: non-dup chunk returns [single_path].
    - test_no_file_path_attr: SearchResult has no `file_path` attribute (AttributeError) — guards the clean break.
    - test_graph_direct_hit_also_hydrates: a graph-origin chunk_id still gets file_paths populated.
  </behavior>
  <action>
    Pydantic v2: update the field definition cleanly; no `@computed_field` alias (Research §Don't Hand-Roll explicitly rejects this).

    Hydration: one SELECT per chunk_id is acceptable for top-K (K ≤ ~20). If profiling later wants a batch JOIN, that's a future optimisation, not this plan's scope.

    Grep gate (after task):
      grep -rn "\.file_path\b" backend/src/dotmd/ --include='*.py' | grep -v file_paths
    Expected: 0 hits in search/api/core code (chunker's internal single-source reference may be named differently).
  </action>
  <verify>
    <automated>cd backend && pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py -x --tb=short</automated>
  </verify>
  <done>
    - Models updated.
    - Hydration JOINs M2M and sorts lex.
    - Five tests green.
    - No `file_path` singular attribute on SearchResult.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Update CLI and MCP consumers</name>
  <files>backend/src/dotmd/cli.py, backend/src/dotmd/mcp_server.py</files>
  <behavior>
    CLI result printer (cli.py:~112):
    - Format decision (within Claude's Discretion per Research §Claude's Discretion): render as `[i] path1  (+N more: path2, path3)` when N > 0, else `[i] path1`. This keeps narrow terminals readable and exposes the full list on demand (document this choice in the SUMMARY).
    - If the operator prefers a flat join, a follow-up issue can revisit — this plan picks ONE and documents it.

    CLI status (cli.py:~161):
    - `SELECT COUNT(DISTINCT file_path) FROM chunk_file_paths_<strategy>` (was `chunks_<strategy>`). Apply across all present strategies.

    MCP server (mcp_server.py:~118, ~44):
    - Output: `"file_paths": [str(p) for p in r.file_paths]` — JSON array of strings.
    - Docstring (line 44) updated to describe the new shape: "Each result has `file_paths: list[str]` — all files whose content hashes to this chunk."

    Tests:
    - tests/cli/test_search_output.py::test_renders_multi_holder → shared-holder result prints the `+N more` suffix.
    - tests/cli/test_status_output.py::test_counts_distinct_paths_from_m2m → status reports correct distinct-path count on a M2M fixture.
    - tests/mcp/test_search_tool.py::test_file_paths_is_json_array → MCP response JSON has `file_paths: [...]` array.
  </behavior>
  <action>
    Keep CLI printing helpers inline (no new abstraction). Use `click.echo` as elsewhere in the file.

    MCP: preserve existing error handling and response envelope; only the single field shape changes.

    Grep gate:
      grep -rn '"file_path"\|\.file_path[^s]' backend/src/dotmd/cli.py backend/src/dotmd/mcp_server.py
    Expected: 0 hits.
  </action>
  <verify>
    <automated>cd backend && pytest tests/cli/test_search_output.py tests/cli/test_status_output.py tests/mcp/test_search_tool.py -x --tb=short</automated>
  </verify>
  <done>
    - CLI printer documented and tested.
    - CLI status queries M2M.
    - MCP emits array.
    - All three tests green.
    - Grep audit clean.
  </done>
</task>

</tasks>

<threat_model>
## Trust Boundaries

| Boundary | Description |
|----------|-------------|
| MCP JSON response → external MCP client | output shape is contract — clean break is intentional per Decision #2 |

## STRIDE Threat Register

| Threat ID | Category | Component | Disposition | Mitigation Plan |
|-----------|----------|-----------|-------------|-----------------|
| T-16-15 | Tampering | CLI line rendering injects control characters if file_path contains newline | accept | file_paths come from filesystem walk; same control surface as before the change |
| T-16-16 | Information disclosure | exposing all holder paths reveals mirrored content locations to the user | accept | localhost single-user; intentional per Decision #1 |
</threat_model>

<verification>
- `pytest tests/api/test_search_result_shape.py tests/cli/test_search_output.py tests/cli/test_status_output.py tests/mcp/test_search_tool.py -x` green.
- Grep: no `\.file_path[^s]` hits in changed files.
- Manual smoke (optional): `dotmd search "test"` against a collision fixture prints the `+N more` suffix.
</verification>

<success_criteria>
- Clean-break shape propagated through every consumer in the audit.
- Sort-lex invariant proven by test.
- Graph-origin hits hydrate identically to semantic/BM25 hits.
- CLI and MCP rendering choices documented in SUMMARY.
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-05-SUMMARY.md` with: final SearchResult schema, chosen CLI rendering format and rationale, MCP response example.
</output>
