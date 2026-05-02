---
phase: "22"
plan: "01-snippet-boundary-extraction"
status: complete
completed_at: "2026-05-02T18:29:40+05:00"
commits:
  - "68dc9b9"
  - "29c325a"
requirements:
  - SNIPPET-BOUNDARY-01
  - SNIPPET-CONTEXT-01
  - SNIPPET-VERIFY-01
---

# Phase 22 Plan 01 Summary: Snippet Boundary Extraction

## What Changed

- Updated `backend/src/dotmd/search/fusion.py` so `_extract_best_snippet()` keeps
  the existing best-window scoring, then expands the chosen query hit to simple
  sentence, paragraph, or chunk boundaries.
- Review follow-up: query-token focus offsets are computed against the original
  text rather than a lowercased copy, so Unicode lowercasing cannot skew snippet
  boundary offsets.
- Added a hard cap of `2 * snippet_length`; over-cap boundary expansion falls
  back to the existing bounded word-aware window behavior.
- Added focused regression coverage in `backend/tests/test_fusion.py` for:
  sentence-start expansion, successful expansion beyond `length`, boundary
  off-by-one behavior, blank-line boundaries, long-sentence hard cap, empty
  query fallback, short text passthrough, normal `build_search_results()` use,
  and MCP-visible cleanup formatting.

## Scope Preserved

- No MCP schema changes.
- No neighboring chunks are read or concatenated.
- No `context_window` or neighbor-context parameter was added.
- No speaker-turn anchors, abbreviation dictionaries, language-specific sentence
  parser, ML, summarization, or NLP were added.
- Known limitation preserved by design: naive punctuation boundaries can still
  split abbreviations, initials, versions, and decimals.

## Verification

- `cd backend && uv run pytest tests/test_fusion.py -q` — passed, 19 tests.
- `cd backend && uv run ruff check src/dotmd/search/fusion.py tests/test_fusion.py` — passed.
- `cd backend && uv run pyright src/dotmd/search/fusion.py tests/test_fusion.py` — passed.
- `cd /opt/docker/dotmd && docker compose up -d --force-recreate dotmd` — completed twice:
  once after implementation and again after the review follow-up.
- `docker inspect -f '{{.State.Health.Status}}' dotmd` — healthy after final recreate.
- `just test-mcp-remote` — passed after final recreate.
- Live `tools/list` search schema checked: properties are `query` and `top_k`;
  `context_window` is absent.
- Live MCP `tools/call` search checked with query `проект`, `top_k=3`; search
  returned successfully and the visible snippet was coherent after MCP
  frontmatter/timestamp cleanup.

## Project-Level Gate Note

- `just check` was run. Ruff passed, but the repository-wide pyright ratchet
  failed on pre-existing/non-phase files:
  `devtools/reranker_latency_bench.py`, `devtools/reranker_quality_bench.py`,
  `tests/devtools/test_reranker_quality_bench.py`, and
  `tests/test_reranker.py`.
- The ratchet total improved from baseline (`107` errors vs baseline `115`), but
  those unrelated files still register as regressions. Phase 22 touched files
  pass direct pyright.

## Live Snippet Observation

Live MCP search returned a transcript result from
`/mnt/knowledgebase/voicenotes/20260107-0934-iDemcTMG/transcript.md`.
The visible snippet began at the formatted chunk/speaker boundary and did not
produce a tool error. MCP-visible formatting after frontmatter/timestamp
stripping was inspected.

`snippet_hard_cap_multiplier = 2` is a Phase 22 constant and can be tuned in a
later phase if live snippets feel too short or too long.

feedback id=19 remains open until implementation is reviewed and accepted.
