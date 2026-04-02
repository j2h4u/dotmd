---
phase: 14-frontmatter-driven-indexing
plan: 01
subsystem: ingestion, search
tags: [frontmatter, fts5, graph, embeddings, metadata]
dependency_graph:
  requires: []
  provides: [structured-frontmatter-indexing, fts5-column-weights, graph-tag-entities]
  affects: [search-ranking, embedding-quality, graph-coverage]
tech_stack:
  added: []
  patterns: [column-weighted-bm25, namespace-typed-entities, embedding-prefix-enrichment]
key_files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/chunker.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/extraction/structural.py
    - backend/src/dotmd/search/fts5.py
    - backend/src/dotmd/ingestion/content_handlers.py
decisions:
  - "FTS5 bm25 weights: text 1x, title 5x, tags 3x"
  - "Tags bypass NER -- go directly to graph as typed entities"
  - "Frontmatter stripped in chunker, not structural extractor"
metrics:
  duration: 3min
  completed: 2026-04-02
  tasks: 3
  files: 5
---

# Phase 14 Plan 01: Frontmatter-Driven Indexing Summary

Structured frontmatter metadata feeding into all three search engines via native channels instead of leaking as raw YAML in chunk text.

## Changes

### Task 1: Frontmatter strip + graph injection (5f0797f)
- `chunker.py`: calls `parse_frontmatter()` to strip YAML before `_parse_sections()`
- `pipeline.py`: new `_frontmatter_to_graph()` injects typed entities from tags (colon namespace: `person:Alice` -> PERSON/Alice) and kind-specific fields (meeting_transcript participants)
- `structural.py`: removed `_extract_frontmatter()` method, `_FRONTMATTER_RE` regex, and yaml import -- frontmatter now handled at pipeline level

### Task 2: FTS5 column-weighted ranking (568d05a)
- `fts5.py`: added `title` and `tags` columns to FTS5 virtual table
- `fts5.py`: search uses `bm25(table, 1.0, 5.0, 3.0)` -- title 5x boost, tags 3x, text baseline
- `fts5.py`: `_ensure_fts5_schema()` auto-migrates old tables (drop+recreate since FTS5 lacks ALTER TABLE)
- `pipeline.py`: builds `file_meta` dict from FileInfo and passes to `add_chunks()` in both batch and trickle paths

### Task 3: Embedding enrichment with tags (b63112f)
- `content_handlers.py`: renamed `enrich_with_title` to `enrich_with_title_and_tags`
- Prepends `"title\ntags_csv\n\n"` to chunk text before embedding
- All handlers (default, meeting_transcript, voicenote) updated

## Deviations from Plan

None -- plan executed exactly as written.

## Known Stubs

None.

## Self-Check: PASSED
