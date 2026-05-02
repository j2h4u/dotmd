# Phase 22 Context — Improve Search Snippet Boundaries

## Promotion

Promoted from backlog item `999.21` on 2026-05-02 via `$gsd-review-backlog 999.21`.

## Goal

Improve `search` snippets so agents can judge whether a hit is worth opening
with `read` without guessing around mid-sentence truncation.

The goal is not to make snippets replace `read`. `search` should remain the
discovery tool, while `read(file_path, start, end)` remains the linear
consumption tool. Snippets should provide enough local context to reduce
false-positive `read` calls and prevent misleading partial quotes.

## Feedback Sources

- `feedback id=6` reported that search snippets often truncate mid-sentence,
  making it ambiguous whether a quoted phrase continues with material that
  changes the meaning.
- `feedback id=10` confirmed that `read` solved the main long-document workflow,
  but snippet truncation remained a low-priority friction point.
- `feedback id=19` refreshed the request after live use: expand snippets with a
  small amount of surrounding context, trim on sentence or paragraph boundaries
  where possible, and optionally mark the matched/relevant span. No ML or
  summarization is requested.
- Fresh Claude.ai web refinement on 2026-05-02 narrowed the scope further:
  fix only mid-sentence truncation inside the current chunk. Do not add
  automatic neighboring-chunk context; that is already covered by
  `read(file_path, start, end)`.

## Backlog Context

Original `999.21` concern:

- Current snippets can start or end in the middle of a sentence.
- Agents use snippets as evidence pointers and triage signals.
- A truncated quote can change meaning depending on the missing continuation.
- Extra `read` calls are possible but wasteful when only local disambiguation is
  needed.

Previously listed solution options before the 2026-05-02 refinement:

- Add a `context_window` parameter to `search` — now out of scope unless
  planning finds a strong reason.
- Include adjacent chunks by default or optionally — explicitly withdrawn by
  the latest feedback because `read` already handles cross-chunk context.
- Expand snippets to sentence boundaries using simple punctuation and paragraph
  heuristics — current preferred direction.
- Return the full chunk instead of a substring — likely too broad for search
  output unless tests show sentence boundaries are insufficient.

## Current Scope Decision

Implement a cheap deterministic fix inside the current chunk:

- When forming the snippet window, expand left and right to a sentence boundary
  (`.`, `?`, `!`, blank line) or chunk boundary.
- For transcripts, prefer structural speaker-turn anchors such as
  `**Speaker N:**` or the end of the previous speaker turn when they are nearby.
- Do not include neighboring chunks automatically in Phase 22.
- Do not add ML, summarization, or semantic context expansion.

## Initial Phase Boundary

- Keep the existing `search`/`read` split.
- Keep snippets within the current chunk.
- Prefer deterministic text-boundary heuristics over ML.
- Preserve bounded snippet size so search results do not become full-document
  reads.
- Add tests around snippet extraction behavior before changing live MCP output.
- Verify through the MCP search surface, not only unit tests.

## Open Questions For Planning

- Should match marking be part of Phase 22 or deferred?
- Should the default snippet behavior improve without adding any new MCP tool
  parameter?
