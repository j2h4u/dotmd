---
phase: 35-filesystem-unified-source-adapter
plan: "01"
subsystem: ingestion/source-adapter
tags: [refactor, source-adapter, public-api]
dependency_graph:
  requires: []
  provides: [document_for_file_info public method]
  affects: [source.py, pipeline.py, test_source_filesystem.py]
tech_stack:
  added: []
  patterns: [public method rename, private-to-public promotion]
key_files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/source.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/tests/ingestion/test_source_filesystem.py
decisions:
  - "document_for_file_info promoted to public — removes private bypass pattern from pipeline and test double"
metrics:
  duration: "~2 min"
  completed: "2026-05-10"
  tasks: 3
  files_modified: 3
---

# Phase 35 Plan 01: Rename _from_file_info to document_for_file_info Summary

Renamed `FilesystemMarkdownSourceAdapter._from_file_info` to the public `document_for_file_info`, updated the two internal call sites in `discover()` and `discover_multi()`, the pipeline call site in `_source_document_for_file_info`, and the `_RecordingLifecycleAdapter` test double override and super() dispatch.

## Tasks Completed

| Task | Name | Commit | Files |
|------|------|--------|-------|
| 35-01-01 | Rename _from_file_info in source.py | d2066e3 | source.py |
| 35-01-02 | Update pipeline.py call site | 9163b5f | pipeline.py |
| 35-01-03 | Update _RecordingLifecycleAdapter test double | d6a1241 | test_source_filesystem.py |

## Verification Results

1. `rg "_from_file_info" backend/` — returns no output (all private references removed)
2. `grep "def document_for_file_info" source.py` — returns exactly 1 line (line 63)
3. `grep "bundle.source.document_for_file_info" pipeline.py` — returns exactly 1 line (line 1371)
4. Full test suite: 39 passed, 0 failed (test_source_filesystem.py + test_source_lifecycle.py)

## Deviations from Plan

None - plan executed exactly as written.

## Self-Check: PASSED

- `backend/src/dotmd/ingestion/source.py` — exists and modified
- `backend/src/dotmd/ingestion/pipeline.py` — exists and modified
- `backend/tests/ingestion/test_source_filesystem.py` — exists and modified
- Commits d2066e3, 9163b5f, d6a1241 — all present in git log
