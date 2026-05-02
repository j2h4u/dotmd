# Phase 22: Improve Search Snippet Boundaries - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-02
**Phase:** 22-improve-search-snippet-boundaries
**Areas discussed:** Snippet scope, boundary heuristic, size limits

---

## Snippet Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Current chunk only | Expand snippets only within the retrieved chunk. | ✓ |
| Neighboring chunks | Include adjacent chunks or add `context_window`. | |
| Full chunk | Return the full chunk instead of a selected snippet. | |

**User's choice:** Current chunk only.
**Notes:** User explicitly rejected neighboring chunks because chunks overlap
and `read(file_path, start, end)` already solves cross-chunk context.

---

## Boundary Heuristic

| Option | Description | Selected |
|--------|-------------|----------|
| Sentence boundaries | Expand left/right to sentence or paragraph boundaries. | ✓ |
| Speaker-turn anchors | Use transcript markers such as `**Speaker N:**`. | |
| ML/NLP boundary detection | Use language-aware NLP or model-based segmentation. | |

**User's choice:** Sentence boundaries only.
**Notes:** User rejected speaker-turn logic because transcript format is not a
stable contract. The desired implementation is minimalist and deterministic.

---

## Size Limits

| Option | Description | Selected |
|--------|-------------|----------|
| Whole sentence over limit | Preserve full boundary-expanded sentence even if long. | |
| Strict current limit | Never exceed `snippet_length`; fall back to old trimming. | |
| Hard-cap compromise | Expand to boundaries, but cap pathological long snippets. | ✓ |

**User's choice:** Hard-cap compromise.
**Notes:** The recommended planning default is a hard cap around
`2 * snippet_length`, with bounded word-aware fallback when exceeded.

---

## the agent's Discretion

- Exact helper decomposition.
- Exact fallback details for ellipses and word-aware trimming within the hard cap.
- Whether match marking is cheap enough to include, though it is not required.

## Deferred Ideas

- Neighboring chunk context in search.
- MCP `context_window` parameter.
- Transcript speaker-turn parsing.
- Match highlighting as a future enhancement if needed.
