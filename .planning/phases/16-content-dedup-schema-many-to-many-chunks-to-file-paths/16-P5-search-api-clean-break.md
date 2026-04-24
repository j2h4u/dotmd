---
phase: 16-content-dedup-schema
plan: 5
type: execute
wave: 5
depends_on: [16-P1, 16-P4]
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
    - "CLI result printer renders the list as `[i] path1  (+N more: path2, path3)` when N > 0, else `[i] path1` (format locked here and mirrored as a one-line note in CONTEXT.md per Review-LOW)."
    - "CLI rendering output order follows the sorted-lex invariant from Decision #1 (addresses Review-LOW-11)."
    - "MCP server emits `file_paths` as a JSON array of strings."
    - "Search hydration uses BATCH query `SELECT chunk_id, file_path FROM chunk_file_paths_<strategy> WHERE chunk_id IN (:ids)` (single round-trip for top-K) — not per-chunk queries (addresses Review-LOW-12 from opencode)."
    - "P5 lands BEFORE P2 in the wave order so P2 appends its `migrate` group to cli.py without conflicting with P5's search/status edits."
  artifacts:
    - path: backend/src/dotmd/core/models.py
      provides: "SearchResult and Chunk models with file_paths: list[Path]."
    - path: backend/src/dotmd/search/fusion.py
      provides: "_hydrate_results uses batch M2M query to build file_paths lists in sorted order."
    - path: backend/src/dotmd/api/service.py
      provides: "DotMDService.search returns SearchResult with file_paths."
    - path: backend/src/dotmd/cli.py
      provides: "CLI search result printer and status using file_paths; status query reads from chunk_file_paths_<strategy>."
    - path: backend/src/dotmd/mcp_server.py
      provides: "MCP search tool output carrying file_paths array."
  key_links:
    - from: backend/src/dotmd/search/fusion.py
      to: backend/src/dotmd/storage/metadata.py
      via: "get_file_paths_for_chunk_ids (batch, sorted lex) — single SELECT per strategy per search call"
      pattern: "get_file_paths_for_chunk_ids"
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
Replace the singular `file_path: Path` on `SearchResult` and `Chunk` with `file_paths: list[Path]` (sorted lex) as a clean break (Decisions #1 + #2). Update every consumer identified in the Research §Consumer Audit: fusion hydration (batch query, not per-chunk), CLI printer + status, MCP server output, and any internal caller that touches the field.

Purpose: Deliver the user-facing value of this phase — identical content returns one search result with all holders exposed as a list — and honour the no-legacy-compat global rule with a clean break. Sequenced BEFORE P2 in the Wave 5→6 order so P2 can append its `migrate` Click group to cli.py without file-overlap conflict.

Output: Updated models, hydration (batch), CLI/MCP output, service facade tests.
</objective>

<execution_context>
@$HOME/.claude/get-shit-done/workflows/execute-plan.md
@$HOME/.claude/get-shit-done/templates/summary.md
</execution_context>

<context>
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-RESEARCH.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-REVIEWS.md
@.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-01-SUMMARY.md
@backend/src/dotmd/core/models.py
@backend/src/dotmd/search/fusion.py
@backend/src/dotmd/api/service.py
@backend/src/dotmd/cli.py
@backend/src/dotmd/mcp_server.py

<interfaces>
Consumer audit (from Research §Component Responsibilities):
- `cli.py:112`  — `f"[{i}] {r.file_path}"` → must render `r.file_paths` per the locked format
- `cli.py:161` — status: `SELECT COUNT(DISTINCT file_path) FROM chunks_<strategy>` → must read from `chunk_file_paths_<strategy>`
- `service.py:369` — constructs SearchResult; shape update
- `mcp_server.py:118` — `"file_path": str(r.file_path)` → `"file_paths": [str(p) for p in r.file_paths]`
- `mcp_server.py:44` — docstring update
- `core/models.py:78` — Chunk.file_path → file_paths
- `core/models.py:130` — SearchResult.file_path → file_paths
- `fusion.py:202` — _hydrate_results

From P1 metadata (batch hydration helper):
- `get_file_paths_for_chunk_ids(strategy, chunk_ids: Sequence[str]) -> dict[str, list[str]]`
  Returns `{chunk_id: [sorted file_paths]}` via single SELECT with `IN (?, ?, …)` clause.

CLI rendering format (locked here per Review-LOW-11 — also mirrored into CONTEXT.md):
  Single holder:  `[{i}] {path}`
  Multi holder:   `[{i}] {sorted_path_0}  (+{N-1} more: {sorted_path_1}, {sorted_path_2}, …)`
  Rationale: narrow-terminal readable + surfaces full list on demand. Sort order follows Decision #1 (lex). The "more" list is truncated to the first K siblings in its natural sorted-lex order — no top-N selection by mtime / depth.

Wave sequencing: P5 is Wave 5, depends on P1 (metadata helper) + P4 (transaction contract stability). P2 follows in Wave 6 and appends `migrate` subcommand to cli.py.
</interfaces>
</context>

<tasks>

<task type="auto" tdd="true">
  <name>Task 1: Update models and hydration layer (batch query)</name>
  <files>backend/src/dotmd/core/models.py, backend/src/dotmd/search/fusion.py, backend/src/dotmd/api/service.py</files>
  <behavior>
    Core models:
    - `SearchResult.file_paths: list[Path]` (was `file_path: Path`). No alias.
    - `Chunk.file_paths: list[Path]` — single-element at creation time, populated to full set after hydration (per Research Open Q #3 recommendation: one model, wrap-in-list at creation).

    Fusion (_hydrate_results):
    - Collect all chunk_ids returned by fusion for this search call.
    - Call `metadata.get_file_paths_for_chunk_ids(strategy, chunk_ids)` ONCE per strategy per search call — single SELECT with `IN (?, ?, …)` clause (addresses Review-LOW-12 from opencode about avoiding O(K) round-trips).
    - Iterate the returned dict to attach `file_paths` to each SearchResult.
    - Sort order: metadata helper already returns each list sorted lex per D-01. Under DEBUG, fusion additionally asserts `result.file_paths == sorted(result.file_paths)` as a regression guard.
    - Graph-origin hits (graph_direct → chunk_ids) traverse the same batch hydration path — no separate code path.

    Service (`DotMDService.search`):
    - No logic change; only the SearchResult shape flows through. Verify the facade test.

    Tests (tests/api/test_search_result_shape.py — RED skeletons from P6):
    - test_file_paths_field_is_list: SearchResult.file_paths is a list[Path].
    - test_file_paths_sorted_lex: a chunk with holders ["z.md", "a.md", "m.md"] returns ["a.md", "m.md", "z.md"].
    - test_single_holder_returns_single_element_list: non-dup chunk returns [single_path].
    - test_no_file_path_attr: SearchResult has no `file_path` attribute (AttributeError) — guards the clean break.
    - test_graph_direct_hit_also_hydrates: a graph-origin chunk_id still gets file_paths populated via the same batch path.
    - test_batch_hydration_single_query_per_strategy (NEW — Review-LOW-12): hydrate 5 chunk_ids; assert the metadata helper was called exactly ONCE per strategy per search call (spy via unittest.mock or recording wrapper).
  </behavior>
  <action>
    Pydantic v2: update the field definition cleanly; no `@computed_field` alias (Research §Don't Hand-Roll explicitly rejects this).

    Batch hydration: use `get_file_paths_for_chunk_ids` — the metadata helper added in P1 Task 1 precisely for this purpose. Do NOT call `get_file_paths_by_chunk_id` (singular) in a loop.

    Grep gate (strip comments to avoid self-invalidation):
      grep -rn --include='*.py' "\.file_path\b" backend/src/dotmd/ | grep -v file_paths | grep -v '^\s*#'
    Expected: 0 hits in search/api/core code (chunker's internal single-source reference — if any — is acceptable; this is search/api focus).
  </action>
  <verify>
    <automated>cd backend && pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py -x --tb=short</automated>
  </verify>
  <done>
    - Models updated.
    - Hydration uses batch query; single SELECT per strategy per search call proven by test.
    - Six tests green.
    - No `file_path` singular attribute on SearchResult.
  </done>
</task>

<task type="auto" tdd="true">
  <name>Task 2: Update CLI and MCP consumers</name>
  <files>backend/src/dotmd/cli.py, backend/src/dotmd/mcp_server.py, .planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md</files>
  <behavior>
    CLI result printer (cli.py:~112):
    - Render format (locked):
        Single holder: `[{i}] {path}`
        Multi holder:  `[{i}] {path_0}  (+{n-1} more: {path_1}, {path_2}, …)` where `path_0 … path_n-1` are already sorted lex.
    - Preserve existing prefix/metadata columns in the printer unchanged.

    CLI status (cli.py:~161):
    - `SELECT COUNT(DISTINCT file_path) FROM chunk_file_paths_<strategy>` (was `chunks_<strategy>`). Apply across all present strategies.

    MCP server (mcp_server.py:~118, ~44):
    - Output: `"file_paths": [str(p) for p in r.file_paths]` — JSON array of strings.
    - Docstring (line 44) updated to describe the new shape: "Each result has `file_paths: list[str]` — all files whose content hashes to this chunk."

    CONTEXT.md:
    - Append one-line CLI rendering note under Decisions (Review-LOW-11):
      "**CLI rendering — LOCKED (Phase 16 P5):** Multi-holder lines print as `[i] path_0  (+N-1 more: path_1, …)` in sorted-lex order from file_paths. Single holder prints as `[i] path`."

    Tests:
    - tests/cli/test_search_output.py::test_renders_single_holder_no_more_suffix: single-holder fixture → no `+N more` suffix.
    - tests/cli/test_search_output.py::test_renders_multi_holder_with_plus_n_suffix: shared-holder result prints the `+N more` suffix in sorted-lex order.
    - tests/cli/test_status_output.py::test_counts_distinct_paths_from_m2m: status reports correct distinct-path count on a M2M fixture.
    - tests/mcp/test_search_tool.py::test_file_paths_is_json_array: MCP response JSON has `file_paths: [...]` array.
    - tests/mcp/test_search_tool.py::test_docstring_mentions_file_paths: docstring updated.
  </behavior>
  <action>
    Keep CLI printing helpers inline (no new abstraction). Use `click.echo` as elsewhere in the file.

    MCP: preserve existing error handling and response envelope; only the single field shape changes.

    Append the CONTEXT.md locked-decision note as described — one line under the existing Decisions section header. Commit it alongside the code change for traceability (Review-LOW-11).

    File-overlap awareness: P2 follows in Wave 6 and will APPEND a `migrate` group. This plan must not disturb the bottom of cli.py beyond what is strictly needed for search/status edits. If a merge surface emerges, this task owns ONLY search + status lines; P2 owns the `migrate` group.

    Grep gate:
      grep -rn '"file_path"\|\.file_path[^s]' backend/src/dotmd/cli.py backend/src/dotmd/mcp_server.py | grep -v '^\s*#'
    Expected: 0 hits.
  </action>
  <verify>
    <automated>cd backend && pytest tests/cli/test_search_output.py tests/cli/test_status_output.py tests/mcp/test_search_tool.py -x --tb=short</automated>
  </verify>
  <done>
    - CLI printer renders the locked format (single + multi holder) with sorted-lex order.
    - CLI status queries M2M.
    - MCP emits array.
    - CONTEXT.md has the one-line rendering note appended.
    - All five tests green.
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
| T-16-24 | Performance | O(K) per-chunk hydration queries under large top-K | mitigate | batch hydration helper from P1 ensures single SELECT per strategy per search call |
</threat_model>

<verification>
- `pytest tests/api/test_search_result_shape.py tests/cli/test_search_output.py tests/cli/test_status_output.py tests/mcp/test_search_tool.py -x` green.
- Grep: no `\.file_path[^s]` hits in changed files.
- CONTEXT.md diff shows the one-line CLI rendering note.
- Manual smoke (optional): `dotmd search "test"` against a collision fixture prints the `+N more` suffix in sorted-lex order.
</verification>

<success_criteria>
- Clean-break shape propagated through every consumer in the audit.
- Sort-lex invariant proven by test.
- Graph-origin hits hydrate identically to semantic/BM25 hits via the same batch path.
- Single-SELECT-per-strategy-per-search invariant proven by spy test (Review-LOW-12).
- CLI rendering format locked in CONTEXT.md (Review-LOW-11).
</success_criteria>

<output>
Create `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-05-SUMMARY.md` with: final SearchResult schema, chosen CLI rendering format and rationale, MCP response example, confirmation that batch hydration uses single SELECT per strategy per search call.
</output>
</content>
</invoke>