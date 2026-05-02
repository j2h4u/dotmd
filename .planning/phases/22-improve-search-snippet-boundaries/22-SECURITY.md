---
phase: 22
slug: improve-search-snippet-boundaries
status: verified
threats_open: 0
asvs_level: 1
created: "2026-05-02"
verified_at: "2026-05-02T18:52:00+05:00"
---

# Phase 22 — Security

Per-phase security contract: threat register, accepted risks, and audit trail.

## Trust Boundaries

| Boundary | Description | Data Crossing |
|----------|-------------|---------------|
| MCP search response | Internal indexed chunk text is converted into MCP-visible search snippets. | Markdown/transcript text leaves the service through the `search` tool. |
| Search/read separation | `search` returns bounded snippets; full document context remains behind explicit `read`. | Local chunk text must not silently expand into neighboring chunks. |
| MCP tool schema | Hosted MCP clients call the stable `search` schema. | JSON schema parameters and output fields exposed through `tools/list`. |

## Threat Register

| Threat ID | Category | Component | Disposition | Mitigation | Status |
|-----------|----------|-----------|-------------|------------|--------|
| T-22-01 | Denial of Service / Information Exposure | `backend/src/dotmd/search/fusion.py` | mitigate | Boundary-expanded snippets enforce `hard_cap = length * 2`; over-cap snippets use bounded word-aware fallback. Covered by `test_extract_best_snippet_long_single_sentence_is_hard_capped`. | closed |
| T-22-02 | Integrity | Retrieval/reranking pipeline | mitigate | Change is limited to snippet extraction helpers and result construction tests; no retrieval or reranking engine behavior changed. `build_search_results()` still calls `_extract_best_snippet(chunk.text, query, snippet_length)`. | closed |
| T-22-03 | Information Exposure | Search/read contract | mitigate | `_extract_best_snippet()` only receives and processes the current `chunk.text`; no neighboring chunks are fetched or concatenated. Summary and verification record this scope. | closed |
| T-22-04 | Compatibility / Availability | MCP `search` schema | mitigate | No MCP parameter or output field changed. Live `tools/list` verification shows `search` input properties are only `query` and `top_k`; `context_window` is absent. | closed |
| T-22-05 | Reliability | Transcript formatting | mitigate | No speaker-turn anchor parsing was added; implementation uses only punctuation, blank-line, and chunk boundaries. | closed |
| T-22-06 | Integrity | Snippet relevance window | mitigate | Existing best-window scoring is preserved, then query-token focus inside that window is expanded to nearby boundaries. Covered by sentence-start and `build_search_results()` tests. | closed |
| T-22-07 | Compatibility / Presentation | MCP-visible cleanup | mitigate | `_format_result()` cleanup path is covered by `test_format_result_keeps_clean_visible_snippet_after_cleanup` and live MCP search inspection. | closed |
| T-22-08 | Accepted limitation | Naive punctuation boundaries | accept | False boundaries around abbreviations, initials, versions, and decimals are documented as accepted Phase 22 scope; no NLP or language-specific parser is introduced. | closed |
| T-22-09 | Integrity | Boundary off-by-one | mitigate | `test_extract_best_snippet_already_at_sentence_boundary_has_no_leading_ellipsis` verifies boundary-aligned windows do not pull previous punctuation or add misleading leading ellipses. | closed |

## Accepted Risks Log

| Risk ID | Threat Ref | Rationale | Accepted By | Date |
|---------|------------|-----------|-------------|------|
| AR-22-01 | T-22-08 | Phase 22 deliberately uses simple deterministic punctuation boundaries. Abbreviation/version false positives are preferable to adding brittle NLP or language-specific parsing. | project owner via Phase 22 plan/context | 2026-05-02 |

## Security Audit Trail

| Audit Date | Threats Total | Closed | Open | Run By |
|------------|---------------|--------|------|--------|
| 2026-05-02 | 9 | 9 | 0 | Codex |

## Evidence

- `backend/src/dotmd/search/fusion.py` implements `_expand_snippet_to_boundaries()`,
  `_find_left_boundary()`, `_find_right_boundary()`, and bounded fallback.
- `backend/tests/test_fusion.py` covers hard cap, blank-line boundary, boundary
  off-by-one, normal result construction, and MCP-visible cleanup formatting.
- `22-01-SUMMARY.md` records passing targeted pytest, ruff, pyright, final
  container recreate, live `just test-mcp-remote`, live `tools/list`, and live
  MCP `search`.
- `22-VERIFICATION.md` records all 11 must-haves as passed.

## Sign-Off

- [x] All threats have a disposition (mitigate / accept / transfer)
- [x] Accepted risks documented in Accepted Risks Log
- [x] `threats_open: 0` confirmed
- [x] `status: verified` set in frontmatter

**Approval:** verified 2026-05-02
