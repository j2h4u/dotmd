---
phase: "26"
plan: "03"
type: execute
wave: 3
depends_on:
  - "26-01"
  - "26-02"
files_modified:
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/mcp/test_search_tool.py
  - backend/tests/e2e/test_mcp_smoke.py
  - docs/source-adapter-architecture.md
  - docs/source-adapter-architecture-panel-review.md
  - docs/architecture.md
  - docs/mcp.md
  - .planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-03: ref is the stable read key and readable filesystem source pointer; no display_path/source_uri/deprecated file_paths field is added to public search just for readability."
    - "D-05: MCP search hit shape is {ref, heading?, snippet, score}."
    - "D-06: Any future human label is neutral title, not a path-shaped public identity."
    - "D-09: Agent workflow search(query) -> ref, drill(ref) -> frontmatter/entities/chunk_count, read(ref,start,end) -> text chunks is documented and smoke-tested."
    - "D-10: drill is not merged into read."
    - "D-13: chunk_file_paths_<strategy> remains internal if still needed for filesystem/content-dedup holders."
    - "D-14: Do not do the aggressive storage/graph rewrite unless an incremental no-full-reindex path is proven."
    - "D-15: Telegram dialogs/messages must not be modeled as File."
    - "D-16: Existing graph File internals are filesystem-only legacy internals, not the universal abstraction for new sources."
    - "D-17: Every implementation summary must state whether full reindex was required."
    - "D-18: Avoid full reindex; no dotmd index --force/full TEI/full FTS/full graph rebuild unless user explicitly decides."
    - "D-21: Any plan proposing full reindex is a major cost/risk item requiring explicit user decision; current full rebuild cost is about three days."
---

# Phase 26 Plan 03: Regression, Documentation, and Live Smoke

<objective>
Close the phase by proving no public path-first contract remains, documenting
the source-ref-first workflow, and running the live MCP smoke that our agents
actually consume.

Full-reindex answer: this plan must record that no full reindex was required.
It only verifies code/docs/runtime behavior after the contract change.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Tests pass locally but live MCP clients still see old schemas | HIGH | Run the live container e2e smoke after one batched restart if needed. |
| Docs still teach `read(file_path)` or `file_paths` as public APIs | HIGH | Use `rg` gates over docs and e2e tests, with explicit allowed internal-holder exceptions. |
| Cleanup accidentally erases the internal holder-path invariants | HIGH | Keep internal holder references documented as internal and preserve ingestion/storage tests for `Chunk.file_paths` and `chunk_file_paths_*`. |
| Future Telegram work inherits graph `File` terminology | MEDIUM | Docs must state Telegram/non-filesystem sources use SourceDocument/SourceUnit semantics and must not be modeled as `File`. |
| A hidden full-reindex requirement is discovered too late | HIGH | Summary must include a no-full-reindex audit and any migration/backfill count evidence. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Run and update focused regression suite</title>
<name>Run and update focused regression suite</name>
<read_first>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-VALIDATION.md`
- `backend/pyproject.toml`
- `justfile`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
- `backend/tests/e2e/test_mcp_smoke.py`
</read_first>
<files>
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
- `backend/tests/e2e/test_mcp_smoke.py`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md`
</files>
<action>
Run the focused regression suite and record results in the summary.

Required commands:

```bash
cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q
just typecheck
```

If any test still asserts public `file_paths`/`file_path`, update it to the
ref-first contract unless it is explicitly testing internal `Chunk.file_paths`
or `chunk_file_paths_<strategy>` holder behavior.

Add `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md`
with the command outputs and `Self-Check: PASSED` only after focused tests and
typecheck pass.
</action>
<acceptance_criteria>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `tests/api/test_search_result_shape.py`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `tests/mcp/test_search_tool.py`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `just typecheck`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `Self-Check: PASSED` if all required commands pass.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Update source-adapter and MCP documentation</title>
<name>Update source-adapter and MCP documentation</name>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`
- `docs/architecture.md`
- `docs/mcp.md`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`
- `docs/architecture.md`
- `docs/mcp.md`
</files>
<action>
Update docs to describe Phase 26 shipped behavior.

Required doc content:
- Public search hits return `ref`, optional `heading`, `snippet`, and `score`.
- Public read workflow is `search(query) -> ref`, then
  `read(ref, start, end)`.
- Public metadata workflow is `drill(ref)`.
- Filesystem refs use `filesystem:<document_ref>` with
  `document_ref = str(Path(file_path).resolve())`.
- `chunk_file_paths_<strategy>` and `Chunk.file_paths` are internal
  filesystem/content-dedup holder mechanics, not public search/read identity.
- Existing graph `File` nodes are filesystem-only legacy internals.
- Telegram dialogs/messages must not be modeled as `File`; future Telegram work
  should use `SourceDocument`/`SourceUnit` semantics.
- No Phase 26 step requires `dotmd index --force`; full rebuild remains a
  three-day cost/risk requiring explicit user decision.

Run doc grep checks:

```bash
rg "read\\(file_path|Only pass file_paths|Returns ranked hits with source `file_paths`" docs backend/src/dotmd/mcp_server.py
rg "chunk_file_paths|Chunk.file_paths" docs/source-adapter-architecture.md docs/architecture.md
```

The first command should return no public-contract hits. The second command
should return internal-holder wording.
</action>
<acceptance_criteria>
- `docs/mcp.md` contains `read(ref`.
- `docs/mcp.md` contains `drill`.
- `docs/mcp.md` contains `{ ref, heading?, snippet, score }` or equivalent field list.
- `docs/source-adapter-architecture.md` contains `filesystem:<document_ref>`.
- `docs/source-adapter-architecture.md` contains `Telegram dialogs/messages must not be modeled as File` or equivalent wording.
- `docs/architecture.md` contains `source-ref-first`.
- `rg "read\\(file_path|Only pass file_paths|Returns ranked hits with source `file_paths`" docs backend/src/dotmd/mcp_server.py` returns no public-contract hits.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Run live MCP smoke after batched restart if needed</title>
<name>Run live MCP smoke after batched restart if needed</name>
<read_first>
- `backend/tests/e2e/test_mcp_smoke.py`
- `.mcp.json`
- `backend/start.sh`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-VALIDATION.md`
</read_first>
<files>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md`
</files>
<action>
Run the live MCP smoke against the local container after implementation.

First try without restarting if code is already loaded:

```bash
docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"
```

If the smoke still sees the old tool schema because the running process has not
loaded the bind-mounted code, restart once after all Phase 26 changes are
complete, then rerun the same command. Do not restart production repeatedly for
individual tasks.

Record in `26-03-SUMMARY.md`:
- whether a restart was needed;
- exact smoke command;
- pass/fail output summary;
- evidence that `search` returned `ref`;
- evidence that `drill(ref)` returned metadata;
- evidence that `read(ref, 0, 3)` returned chunks;
- no-full-reindex audit: `dotmd index --force` was not run.
</action>
<acceptance_criteria>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `python -m pytest tests/e2e/ -v -p no:cacheprovider`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `search -> ref`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `drill(ref)`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `read(ref`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `dotmd index --force was not run`.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Write final phase summary and deferred-scope audit</title>
<name>Write final phase summary and deferred-scope audit</name>
<read_first>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-RESEARCH.md`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-01-core-ref-model-and-service-resolution-PLAN.md`
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-02-mcp-api-cli-ref-contract-PLAN.md`
</read_first>
<files>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md`
</files>
<action>
Finish `26-03-SUMMARY.md` with:

- the final public search hit shape;
- the final `read(ref, start, end)` behavior;
- the final `drill(ref)` behavior;
- where filesystem paths remain internal;
- which tests and type checks ran;
- live MCP smoke outcome;
- no-full-reindex audit;
- deferred scope audit:
  - Telegram adapter implementation remains deferred;
  - source-unit emission for non-filesystem sources remains deferred;
  - graph `File` node rewrite remains deferred;
  - replacing `chunk_file_paths_<strategy>` holder tables remains deferred;
  - pretty `title` labels for search hits remain deferred unless added as neutral metadata.
</action>
<acceptance_criteria>
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `SearchResult.ref`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `read(ref`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `drill(ref)`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `Telegram adapter implementation remains deferred`.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-03-SUMMARY.md` contains `Self-Check: PASSED` only when verification passed.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/api/test_search_result_shape.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py tests/cli/test_search_output.py -q
just typecheck
docker exec dotmd sh -c "cd /mnt/home/repos/j2h4u/dotmd/backend && python -m pytest tests/e2e/ -v -p no:cacheprovider"
rg "read\\(file_path|Only pass file_paths|Returns ranked hits with source `file_paths`" docs backend/src/dotmd/mcp_server.py
```
</verification>

<success_criteria>
- Focused local tests and typecheck pass.
- Live MCP smoke proves `search -> ref -> drill/read`.
- Docs describe source-ref-first public behavior and internal holder paths.
- The final summary records no full reindex and deferred non-filesystem scope.
</success_criteria>
