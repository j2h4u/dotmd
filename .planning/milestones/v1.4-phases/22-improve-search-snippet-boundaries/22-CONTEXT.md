# Phase 22: Improve Search Snippet Boundaries - Context

**Gathered:** 2026-05-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Improve `search` snippets so agents can judge whether a hit is worth opening
with `read` without guessing around mid-sentence truncation.

This phase changes snippet extraction only. It does not change retrieval,
reranking, chunking, indexing, or the `read(file_path, start, end)` tool.

</domain>

<decisions>
## Implementation Decisions

### Snippet Scope

- **D-01:** Keep snippet expansion inside the current chunk only.
- **D-02:** Do not include neighboring chunks automatically. Chunks overlap,
  and cross-chunk context is already available through
  `read(file_path, start, end)`.
- **D-03:** Do not add a `context_window` or neighbor-context parameter to the
  MCP `search` tool in this phase.

### Boundary Heuristic

- **D-04:** Implement the minimal deterministic fix: expand the selected
  snippet window left and right to sentence boundaries inside the current
  chunk.
- **D-05:** Sentence boundaries should use simple text boundaries such as `.`,
  `?`, `!`, blank line, and chunk boundary.
- **D-06:** Do not implement transcript-specific speaker-turn anchors. The
  transcript format is not a stable contract, so `**Speaker N:**` or similar
  markers should not drive snippet behavior.
- **D-07:** Do not use ML, summarization, semantic expansion, or language-specific
  NLP for this phase.

### Size Limits

- **D-08:** Use a compromise for long sentences: expand to sentence boundaries,
  but enforce a hard cap so a very long sentence cannot make search output
  unbounded.
- **D-09:** Recommended hard cap for planning: `2 * snippet_length`, unless
  implementation details reveal a better local constant.
- **D-10:** If the boundary-expanded snippet exceeds the hard cap, fall back to
  bounded word-aware trimming rather than returning a huge fragment.

### Match Marking

- **D-11:** Match marking/highlighting is not required for Phase 22 unless the
  planner finds it essentially free and non-disruptive. The primary goal is
  sentence-boundary snippet quality.

### the agent's Discretion

- Choose the exact helper function decomposition and test fixture shape.
- Choose whether the hard-cap fallback preserves ellipses exactly as today or
  adjusts them to better communicate boundary trimming, as long as output stays
  bounded and tests document the behavior.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase Artifacts

- `.planning/ROADMAP.md` — Phase 22 goal, requirements, dependency, and planning input.
- `.planning/REQUIREMENTS.md` — `SNIPPET-BOUNDARY-01`,
  `SNIPPET-CONTEXT-01`, and `SNIPPET-VERIFY-01`.
- `.planning/STATE.md` — current phase focus and recent context.

### Feedback Sources

- Feedback `id=6` — original report that snippets truncate mid-sentence and
  can make quotes ambiguous.
- Feedback `id=10` — confirms `read` solved the long-document workflow but
  snippet truncation remained a lower-priority friction.
- Feedback `id=19` — fresh open request for context expansion, boundary-aware
  trimming, and optional match marking.
- 2026-05-02 Claude.ai web refinement from user message — strong model
  recommendation to fix only mid-sentence truncation within the current chunk
  and avoid neighboring chunks.

### Code

- `backend/src/dotmd/search/fusion.py` — `_extract_best_snippet()` currently
  selects and truncates snippets.
- `backend/src/dotmd/mcp_server.py` — `_format_result()` strips frontmatter and
  timestamps before returning MCP search hits.
- `backend/src/dotmd/core/config.py` — `snippet_length` setting.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `_extract_best_snippet(text, query, length)` in `backend/src/dotmd/search/fusion.py`
  is the main implementation point.
- `_truncate(text, length)` in the same module is the current word-aware
  fallback and can be reused or refactored.

### Established Patterns

- Search result construction happens in `build_search_results()` after fusion
  and reranking. Snippet changes should not affect scoring, ordering, or engine
  matching.
- MCP result formatting is a separate layer: `_format_result()` removes
  frontmatter and timestamps from `r.snippet`. Sentence-boundary behavior should
  be implemented before this presentation cleanup unless tests show otherwise.
- Existing project style favors small private helpers, type hints, and focused
  pure-function unit tests for text-processing logic.

### Integration Points

- `DotMDService.search()` passes `settings.snippet_length` into
  `build_search_results()`.
- MCP `search` returns `SearchHit.snippet`; verification should exercise this
  live tool surface, not only `_extract_best_snippet()` directly.

</code_context>

<specifics>
## Specific Ideas

- Minimal behavior: current best window stays the center of relevance, then the
  visible text expands to sentence boundaries around that window.
- Blank lines count as useful boundaries because many markdown/transcript chunks
  are paragraph-separated.
- The phase should not rely on transcript speaker markers because transcript
  formats vary.

</specifics>

<deferred>
## Deferred Ideas

- Automatic neighboring-chunk context in `search` is deferred. Use
  `read(file_path, start, end)` for cross-chunk context.
- A new MCP `context_window` parameter is deferred.
- Match highlighting may be revisited later if sentence-boundary snippets are
  not enough for triage.

### Reviewed Todos

- `2026-03-27-smoke-tests.md` matched broadly on search/testing. It is not
  folded into Phase 22 because this phase already has a specific verification
  requirement and does not need the older generic smoke-test todo.
- Other matched todos (`pplx-embed-context`, trickle indexer, soft-delete,
  fork scouting, graph migration) are unrelated keyword matches and remain
  pending.

</deferred>

---

*Phase: 22-improve-search-snippet-boundaries*
*Context gathered: 2026-05-02*
