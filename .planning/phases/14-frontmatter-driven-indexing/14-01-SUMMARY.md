---
phase: 14-frontmatter-driven-indexing
plan: 01
subsystem: ingestion, search
tags: [frontmatter, fts5, graph, embeddings, metadata, bridge-artifact]

# Dependency graph
requires:
  - phase: 13-hierarchical-chunking
    provides: "Content-aware chunking and context prefix injection"
provides:
  - "Structured frontmatter indexing"
  - "FTS5 column-weighted ranking"
  - "Graph tag entities"
affects:
  - backend/src/dotmd/ingestion/chunker.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/extraction/structural.py
  - backend/src/dotmd/search/fts5.py
  - backend/src/dotmd/ingestion/content_handlers.py

# Tech tracking
tech-stack:
  added: []
  patterns: [column-weighted-bm25, namespace-typed-entities, embedding-prefix-enrichment]

key-files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/extraction/structural.py
    - backend/src/dotmd/search/fts5.py
    - backend/src/dotmd/ingestion/content_handlers.py

key-decisions:
  - "FTS5 bm25 weights: text 1x, title 5x, tags 3x."
  - "Tags bypass NER and go directly to graph as typed entities."
  - "Frontmatter is stripped in the chunker, not the structural extractor."

requirements-completed: [FRONTMATTER-01]

# Metrics
completed: 2026-04-02
status: complete
---

# Phase 14 Plan 01: Frontmatter-Driven Indexing Summary

This is the phase-directory copy of the completed quick-task summary at
`.planning/quick/260402-vua-phase-14-frontmatter-driven-indexing/260402-vua-SUMMARY.md`.
It closes the local GSD accounting gap where Phase 14 was shipped but the phase
directory had no plan/summary pair.

## Implementation Evidence

- `5f0797f feat(14-01): strip frontmatter from chunks + graph injection from tags`
- `568d05a feat(14-01): FTS5 title + tags columns with weighted bm25 ranking`
- `b63112f feat(14-01): extend embedding enrichment to include tags in prefix`
- `bbf17fb docs: mark Phase 14 complete — was already shipped 2026-04-02`
- `.planning/quick/260402-vua-phase-14-frontmatter-driven-indexing/260402-vua-SUMMARY.md`

## Outcomes

- YAML frontmatter is stripped before chunk parsing.
- Title and tags flow into FTS5 as weighted columns.
- Tags are injected into the graph as typed entities.
- Embedding enrichment includes title and tags.

## Deviations from Plan

None. The implementation already existed; this artifact reconciles local
documentation only.

## Known Stubs

None for Phase 14.

## Self-Check: PASSED

- ROADMAP.md marks Phase 14 complete under v1.4.
- The quick-task summary records the completed work.
- This bridge plan/summary pair prevents GSD progress from reporting a shipped
  phase as pending.
