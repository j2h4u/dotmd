---
phase: 25-document-source-abstraction-source-adapter-mvp
plan: 04
subsystem: regression-docs
tags: [source-adapter, filesystem, mcp, regression, documentation]

requires:
  - phase: 25-document-source-abstraction-source-adapter-mvp
    provides: SourceDocument, chunk provenance, source_documents persistence, and file_paths compatibility from Plans 25-01 through 25-03
provides:
  - Cross-surface filesystem Markdown compatibility regression coverage
  - Phase 25 filesystem shim documentation and deferred source boundary
  - Focused verification results for ingestion, storage, API, MCP, and pyright ratchet gates
affects: [ingestion, storage, api, mcp, docs, phase-25]

tech-stack:
  added: []
  patterns:
    - Path-compatible MCP read regression with mocked DotMDService
    - Shipped-state docs separated from future-source architecture
    - Verification summary records repo-standard pyright ratchet separately from raw pyright debt

key-files:
  created:
    - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md
  modified:
    - backend/tests/mcp/test_search_tool.py
    - docs/source-adapter-architecture.md
    - docs/architecture.md

key-decisions:
  - "Phase 25 keeps MCP read(file_path, start, end) as the public filesystem read contract."
  - "The canonical filesystem ref is document_ref = str(Path(file_path).resolve()) and ref = filesystem:<document_ref>."
  - "source_documents is strategy-independent; chunk_source_provenance_<strategy> is strategy-scoped; chunk_file_paths remains compatibility-authoritative."
  - "Telegram read-only, mcp-telegram export, source assets, entity catalogs, transports, TTL, and second-source validation remain deferred."

patterns-established:
  - "Docs must name which source-adapter concepts shipped versus future architecture context."
  - "Regression coverage spans adapter discovery, chunking, provenance persistence, API result shape, MCP search, and MCP read compatibility."

requirements-completed: []

duration: 4min
completed: 2026-05-05
---

# Phase 25 Plan 04: Regression Suite, Documentation, and Phase Verification Summary

**Filesystem source identity is now verified across ingestion, storage, API, and MCP while the public filesystem search/read contract stays path-compatible.**

## Performance

- **Duration:** In progress during verification summary draft
- **Started:** 2026-05-05T20:58:24Z
- **Completed:** In progress
- **Tasks:** 3 of 4 completed at this checkpoint
- **Files modified:** 4

## Accomplishments

- Added an MCP `read` regression proving `read(file_path, start, end)` remains path-based and returns frontmatter plus ranged chunks.
- Documented the shipped Phase 25 filesystem Markdown compatibility shim and future-source boundary.
- Ran the focused verification gate across ingestion, storage, API, MCP, `just typecheck`, touched-file pyright, and raw pyright.

## Verification

- PASS: `backend/tests/ingestion/test_source_filesystem.py` coverage includes `filesystem`, `content_fingerprint`, and `metadata_fingerprint`.
- PASS: `backend/tests/ingestion/test_pipeline_purge.py` coverage includes `source_documents` and `chunk_source_provenance`.
- PASS: `backend/tests/api/test_search_result_shape.py` coverage includes `file_paths`.
- PASS: `backend/tests/mcp/test_search_tool.py` coverage includes `file_paths` and `read` compatibility.
- PASS: `cd backend && uv run pytest tests/mcp/test_search_tool.py -q` -> 3 passed.
- PASS: `just typecheck` -> pyright ratchet reported 75 errors against baseline 76, with 1 improvement; command exited successfully.
- PASS: `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` -> 50 passed, 17 warnings.
- PASS: `cd backend && uv run pyright tests/mcp/test_search_tool.py` -> 0 errors.
- PRE-EXISTING RAW PYRIGHT DEBT: `cd backend && uv run pyright` -> 75 errors in existing service, extraction, pipeline, trickle, graph/storage, and older tests. This matches the known Phase 25 project-wide pyright debt pattern and is out of scope for this regression/docs plan; the repo-standard ratchet gate passed.

## Self-Check: PASSED

- Created summary exists: `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md`.
- Verification mentions `tests/ingestion/test_source_filesystem.py`, `tests/mcp/test_search_tool.py`, and `just typecheck` / `pyright`.
- Focused regression tests pass.
- Repo-standard pyright ratchet passes.
