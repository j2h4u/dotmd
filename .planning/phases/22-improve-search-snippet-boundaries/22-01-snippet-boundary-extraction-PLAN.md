---
phase: "22"
plan: "01-snippet-boundary-extraction"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/search/fusion.py
  - backend/tests/test_fusion.py
  - .planning/phases/22-improve-search-snippet-boundaries/22-01-SUMMARY.md
autonomous: true
requirements:
  - SNIPPET-BOUNDARY-01
  - SNIPPET-CONTEXT-01
  - SNIPPET-VERIFY-01
requirements_addressed: [SNIPPET-BOUNDARY-01, SNIPPET-CONTEXT-01, SNIPPET-VERIFY-01]
must_haves:
  truths:
    - "D-01: Snippet expansion stays inside the current chunk only"
    - "D-02: Search does not include neighboring chunks automatically"
    - "D-03: MCP search schema does not add context_window or neighbor-context parameters"
    - "D-04: The selected snippet window expands left and right to sentence boundaries inside the current chunk"
    - "D-05: Sentence boundaries use simple text boundaries: '.', '?', '!', blank line, and chunk boundary"
    - "D-06: Transcript-specific speaker-turn anchors such as '**Speaker N:**' are not implemented"
    - "D-07: No ML, summarization, semantic expansion, or language-specific NLP is added"
    - "D-08: Long sentence expansion is bounded by a hard cap"
    - "D-09: The hard cap defaults to 2 * snippet_length"
    - "D-10: Boundary-expanded snippets over the hard cap fall back to bounded word-aware trimming"
    - "D-11: Match marking is optional and not required for Phase 22"
  artifacts:
    - path: "backend/src/dotmd/search/fusion.py"
      provides: "sentence-boundary snippet extraction"
      contains: "_extract_best_snippet"
    - path: "backend/tests/test_fusion.py"
      provides: "focused snippet extraction regression coverage"
      contains: "test_extract_best_snippet"
  key_links:
    - from: "DotMDService.search"
      to: "build_search_results"
      via: "snippet_length"
      pattern: "_extract_best_snippet"
---

# Phase 22 Plan 01: Snippet Boundary Extraction

<objective>
Update search snippet extraction so snippets avoid mid-sentence starts and
ends when nearby boundaries exist inside the current chunk, while keeping the
search/read split, MCP schema, and bounded output contract unchanged.

This revision incorporates cross-AI review feedback from `22-REVIEWS.md`:
happy-path expansion coverage, boundary-aligned off-by-one coverage, explicit
documentation of naive punctuation limitations, MCP-visible formatting checks,
and unchanged `tools/list` schema verification.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Search output becomes unbounded for very long sentences | HIGH | Enforce a hard cap of `2 * snippet_length`; over-cap snippets use bounded word-aware fallback. |
| Phase accidentally changes retrieval/reranking behavior | HIGH | Modify only snippet helpers in `fusion.py`; tests target snippet strings and existing search-result construction only. |
| Search starts duplicating `read` by adding neighboring chunks | HIGH | Do not fetch or concatenate adjacent chunks; use only `chunk.text` passed to `_extract_best_snippet()`. |
| MCP clients break because search schema changes | HIGH | Do not add MCP parameters or fields; `SearchHit` remains `file_paths`, `heading`, `snippet`, `score`. |
| Transcript-specific parsing creates brittle behavior | MEDIUM | Do not implement speaker-turn anchors such as `**Speaker N:**`; use punctuation/blank-line/chunk boundaries only. |
| Boundary heuristics hide the query match | MEDIUM | Preserve the existing best-window scoring first, then expand around that selected window. |
| MCP visible snippet differs from unit-tested snippet due to cleanup | MEDIUM | Verify through MCP/search surface after unit tests because `_format_result()` strips frontmatter/timestamps. |
| Naive `.` boundary handling misreads abbreviations, initials, versions, or decimals | MEDIUM | Accept this limitation under D-05/D-07; document it and do not add language-specific NLP or abbreviation parsing in Phase 22. |
| Boundary expansion has off-by-one behavior at an existing sentence start | MEDIUM | Add a focused test/criterion proving an already-boundary-aligned window does not pull in previous-sentence punctuation or misleading leading ellipses. |
</threat_model>

<constants>
Phase 22 constants:

- `snippet_hard_cap_multiplier`: `2`
- `snippet_hard_cap`: `2 * snippet_length`
- sentence boundary chars: `.`, `?`, `!`
- paragraph boundary: blank line (`\n\n`)
- absolute boundaries: chunk start and chunk end
- known limitation: punctuation boundaries are intentionally naive and may
  split abbreviations, initials, versions, and decimals; Phase 22 does not add
  language-specific abbreviation handling
- forbidden scope: neighboring chunks, `context_window`, speaker-turn anchors,
  ML/NLP/summarization
</constants>

<tasks>
<task id="1" type="auto">
<name>Task 1: Add RED snippet boundary tests</name>
<read_first>
- `backend/tests/test_fusion.py`
- `backend/src/dotmd/search/fusion.py`
- `.planning/phases/22-improve-search-snippet-boundaries/22-CONTEXT.md`
- `.planning/phases/22-improve-search-snippet-boundaries/22-RESEARCH.md`
</read_first>
<files>
- `backend/tests/test_fusion.py`
</files>
<action>
Add focused tests for `_extract_best_snippet()` to `backend/tests/test_fusion.py`.

Import the helper explicitly:

```python
from dotmd.search.fusion import _extract_best_snippet
```

Add tests whose names start with `test_extract_best_snippet_` and cover these exact behaviors:

1. A match inside a longer paragraph returns a snippet that starts at the
   beginning of the containing sentence, not at the matched word. Use text with
   at least three sentences and a query term in the middle sentence.
2. A happy-path boundary expansion returns an exact expected sentence-boundary
   snippet that is longer than `length` but no longer than `2 * length + 6`.
   This pins the behavior where boundary expansion succeeds without hard-cap
   fallback.
3. A best window that already begins at a sentence boundary does not pull in the
   previous sentence's terminator and does not add a misleading leading
   ellipsis.
4. A match before a blank line returns a snippet that does not cross the blank
   line when the containing sentence can satisfy the query context.
5. A long single sentence over the hard cap returns a string whose length is no
   greater than `2 * length + 6` to allow leading/trailing ellipses.
6. Empty-token query still returns a bounded fallback no longer than
   `length + 3`.
7. A text shorter than `length` returns the original text exactly.

Do not add abbreviation-, initials-, version-, decimal-, or language-specific
boundary tests that require special parsing. Naive punctuation boundaries are a
known Phase 22 limitation, not a requirement to solve.

The initial test run should fail before Task 2 because current snippet
extraction starts at the best word window and can cut sentence boundaries.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_fusion.py -q</automated>
<automated>cd backend && uv run ruff check tests/test_fusion.py</automated>
</verify>
<acceptance_criteria>
- `backend/tests/test_fusion.py` contains `from dotmd.search.fusion import _extract_best_snippet`.
- `backend/tests/test_fusion.py` contains at least seven functions whose names start with `test_extract_best_snippet_`.
- One test asserts a returned snippet starts with a full sentence start instead of the matched word.
- One test pins an exact happy-path snippet that is longer than `length` and no longer than `2 * length + 6`.
- One test covers the already-at-sentence-boundary/off-by-one case.
- One test asserts `len(snippet) <= 2 * length + 6` for a long single sentence.
</acceptance_criteria>
<done>
Phase 22 has failing regression coverage for sentence-boundary snippets.
</done>
</task>

<task id="2" type="auto">
<name>Task 2: Implement sentence-boundary snippet extraction</name>
<read_first>
- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_fusion.py`
- `.planning/phases/22-improve-search-snippet-boundaries/22-CONTEXT.md`
- `.planning/phases/22-improve-search-snippet-boundaries/22-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/search/fusion.py`
- `backend/tests/test_fusion.py`
</files>
<action>
Refactor `backend/src/dotmd/search/fusion.py` so `_extract_best_snippet(text, query, length=300)` keeps the existing best-window scoring but expands the chosen window to nearby boundaries.

Implement private helpers with these responsibilities:

- Find the nearest left boundary before `best_start` using chunk start, blank
  line, or the character after `.`, `?`, or `!`.
- Treat `best_start` that is already at a boundary as boundary-aligned; do not
  walk left into the previous sentence just to find another terminator.
- Find the nearest right boundary after `best_start + length` using chunk end,
  blank line, or the character after `.`, `?`, or `!`.
- Strip leading/trailing whitespace from the selected snippet text.
- Preserve leading `...` when the final snippet does not start at chunk start.
- Preserve trailing `...` when the final snippet does not end at chunk end.
- Enforce `hard_cap = length * 2`.

Do not use transcript speaker markers. Do not read neighboring chunks. Do not
change `build_search_results()` signature. Do not add MCP `search` parameters.
Do not add abbreviation dictionaries, language-specific sentence parsing, or NLP;
false boundaries around abbreviations, initials, versions, and decimals are
accepted for Phase 22.

If the boundary-expanded snippet body exceeds `hard_cap`, use bounded
word-aware trimming from the current best window. The complete returned string,
including ellipses, must stay within `2 * length + 6`. Preserve the existing
`_truncate()` trailing-ellipsis behavior in this hard-cap fallback unless the
focused tests prove the old behavior violates the new bound.

Run and fix the tests added in Task 1 until they pass.
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_fusion.py -q</automated>
<automated>cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py</automated>
<automated>cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/search/fusion.py` contains no references to `Speaker N`.
- `backend/src/dotmd/search/fusion.py` contains no new parameter named `context_window`.
- `backend/src/dotmd/search/fusion.py` contains no abbreviation dictionary or language-specific sentence parser.
- `_extract_best_snippet()` still accepts exactly `text: str`, `query: str`, and `length: int = 300`.
- Already-boundary-aligned snippets do not gain a misleading leading `...`.
- `cd backend && uv run pytest tests/test_fusion.py -q` exits 0.
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py` exits 0.
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py` exits 0.
</acceptance_criteria>
<done>
Snippet extraction expands to sentence/paragraph boundaries inside the current chunk and remains bounded.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Verify through search result and MCP surfaces</name>
<read_first>
- `backend/src/dotmd/search/fusion.py`
- `backend/src/dotmd/mcp_server.py`
- `backend/tests/mcp/test_search_tool.py`
- `backend/tests/e2e/test_mcp_smoke.py`
- `backend/devtools/mcp_remote_smoke.py`
- `justfile`
</read_first>
<files>
- `backend/tests/test_fusion.py`
- `.planning/phases/22-improve-search-snippet-boundaries/22-01-SUMMARY.md`
</files>
<action>
Verify that the implementation is visible through the normal result path.

First, ensure `build_search_results()` still calls `_extract_best_snippet(chunk.text, query, snippet_length)`.

If unit coverage does not already prove `build_search_results()` returns the new boundary-aware snippet, add one focused test using a fake metadata store and a chunk with multi-sentence text. The test must assert the `SearchResult.snippet` starts at the sentence boundary and contains the query term.

Also verify the MCP-visible formatting path. `_format_result()` strips
frontmatter and timestamps after snippet extraction, so the execution summary
must record whether the visible snippet remains coherent after that cleanup.

Then run:

- `cd backend && uv run pytest tests/test_fusion.py -q`
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py`
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py`

For live verification after implementation:

1. Recreate the running `dotmd` container because Python source changed:
   `cd /opt/docker/dotmd && docker compose up -d --force-recreate dotmd`
2. Wait until `docker inspect -f '{{.State.Health.Status}}' dotmd` returns `healthy`.
3. Run `just test-mcp-remote`.
4. Confirm the live MCP `tools/list` schema for `search` is unchanged: no
   `context_window` or neighbor-context parameter exists.
5. Run one live MCP or CLI search against a query that returns a transcript
   snippet and record whether the visible snippet starts at a sentence/paragraph
   boundary.

Write `.planning/phases/22-improve-search-snippet-boundaries/22-01-SUMMARY.md`
with:

- files changed
- tests run and pass/fail status
- live verification result
- note that no MCP schema changes were made
- note that MCP-visible formatting after frontmatter/timestamp stripping was inspected
- note that `snippet_hard_cap_multiplier = 2` is a Phase 22 constant that can be tuned in a later phase if live snippets feel too short or too long
- note that feedback id=19 remains open until implementation is verified and reviewed
</action>
<verify>
<automated>cd backend && uv run pytest tests/test_fusion.py -q</automated>
<automated>just test-mcp-remote</automated>
<manual>Live search snippet inspected and summary records the observed snippet behavior.</manual>
</verify>
<acceptance_criteria>
- `22-01-SUMMARY.md` exists.
- `22-01-SUMMARY.md` contains `just test-mcp-remote`.
- `22-01-SUMMARY.md` contains `No MCP schema changes`.
- `22-01-SUMMARY.md` records that live `tools/list` search schema was checked.
- `22-01-SUMMARY.md` records whether MCP-visible snippet formatting after cleanup remained coherent.
- `22-01-SUMMARY.md` contains `feedback id=19`.
- `22-01-SUMMARY.md` records whether live search snippet inspection passed.
</acceptance_criteria>
<done>
Phase 22 implementation is verified locally and through the live MCP surface.
</done>
</task>
</tasks>

<verification>
## Phase Verification

Run:

```bash
cd backend && uv run pytest tests/test_fusion.py -q
cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py
cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py
just test-mcp-remote
```

Manual/live:

- Inspect one live transcript search result and confirm the visible snippet does
  not start in the middle of a sentence when a nearby boundary exists.
- Confirm MCP `tools/list` schema is unchanged for `search`; no
  `context_window` parameter exists.
</verification>
