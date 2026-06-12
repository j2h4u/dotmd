# Phase 22 Research — Improve Search Snippet Boundaries

## Research Complete

Phase 22 is a local text-processing change. No external web research is needed:
the relevant behavior is fully defined by project feedback, Phase 22 context,
and current code.

## Current Implementation

- Snippets are created in `backend/src/dotmd/search/fusion.py` by
  `_extract_best_snippet(text, query, length=300)`.
- `_extract_best_snippet()` finds the best fixed-width character window based
  on query-token overlap, then adds `...` if the window did not start/end at
  the chunk boundary.
- The current function can start in the middle of a sentence because
  `best_start` is a word boundary, not a sentence boundary.
- The current function can end in the middle of a sentence because truncation
  is word-aware only at the end.
- `build_search_results()` calls `_extract_best_snippet()` with
  `snippet_length=settings.snippet_length`.
- MCP result formatting in `backend/src/dotmd/mcp_server.py` strips frontmatter
  and timestamps from `SearchResult.snippet`. It should not own sentence
  boundary logic.

## Recommended Technical Approach

Keep the existing relevance-window scoring, then boundary-adjust the chosen
window:

1. Select the best fixed-width window exactly as today.
2. Expand left to the nearest sentence/paragraph boundary before the selected
   window, or to chunk start.
3. Expand right to the nearest sentence/paragraph boundary after the selected
   window, or to chunk end.
4. If the expanded snippet length is within the hard cap, return the
   boundary-expanded snippet with appropriate ellipses.
5. If the expanded snippet exceeds the hard cap, fall back to bounded
   word-aware trimming so search output stays bounded.

Recommended hard cap: `2 * snippet_length`.

## Boundary Heuristics

Use deterministic text heuristics only:

- Sentence-ending punctuation: `.`, `?`, `!`.
- Blank lines as paragraph boundaries.
- Chunk start/end as absolute boundaries.

Do not use transcript speaker markers. The user explicitly rejected this
because transcript formats are not stable.

## Testing Strategy

Add focused unit tests for `_extract_best_snippet()` in
`backend/tests/test_fusion.py`:

- A query match inside a sentence should return the whole sentence rather than
  a mid-sentence fragment.
- A query match near paragraph boundaries should not cross blank-line
  boundaries unnecessarily.
- A long sentence should respect the hard cap and fall back to bounded
  word-aware trimming.
- Empty/no-token query should continue using bounded fallback behavior.
- A short chunk shorter than `snippet_length` should still return the full text.

Add a small integration test for `build_search_results()` if needed to prove the
new snippet helper is used through normal search-result construction.

## Verification Strategy

Local gates:

- `cd backend && uv run pytest tests/test_fusion.py -q`
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py`
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py`

Live gate after implementation:

- Restart/recreate `dotmd` if source was changed.
- Run `just test-mcp-remote`.
- Run one live MCP/search or CLI search against a query known to hit a
  transcript and confirm the snippet does not start mid-sentence.

## Risks

- Boundary expansion can make snippets too large. Mitigate with the hard cap.
- Ellipsis behavior can become misleading if boundaries are expanded but the
  result is still trimmed. Tests should pin exact expected strings.
- Existing MCP cleanup strips timestamps after snippet extraction; this may
  slightly alter visible sentence boundaries for transcript snippets. Keep the
  Phase 22 implementation in `fusion.py` and verify through MCP output.

## Validation Architecture

Phase 22 validation should prove:

- `SNIPPET-BOUNDARY-01`: unit tests show snippets avoid mid-sentence start/end
  when nearby boundaries exist.
- `SNIPPET-CONTEXT-01`: tests show the matched/relevant sentence remains present
  with local context.
- `SNIPPET-VERIFY-01`: unit tests plus MCP surface verification are documented
  in the execution summary.
