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
  - "Canonical filesystem ref: document_ref = str(Path(file_path).resolve()) and ref = filesystem:<document_ref>."
  - "file_path is preserved only as filesystem compatibility data, not as the future universal source identity."
  - "source_documents is strategy-independent; chunk_source_provenance_<strategy> is strategy-scoped; chunk_file_paths remains compatibility-authoritative."
  - "Telegram read-only, mcp-telegram export, source assets, entity catalogs, transports, TTL, and second-source validation remain deferred."

patterns-established:
  - "Docs must name which source-adapter concepts shipped versus future architecture context."
  - "Regression coverage spans adapter discovery, chunking, provenance persistence, API result shape, MCP search, and MCP read compatibility."

requirements-completed: []

duration: 6min
completed: 2026-05-05
---

# Phase 25 Plan 04: Regression Suite, Documentation, and Phase Verification Summary

**Filesystem source identity is verified across ingestion, storage, API, and MCP while the public filesystem search/read contract stays path-compatible.**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-05T20:58:24Z
- **Completed:** 2026-05-05T21:04:00Z
- **Tasks:** 4
- **Files modified:** 4

## Accomplishments

- Added an MCP `read` regression proving `read(file_path, start, end)` remains path-based and returns frontmatter plus ranged chunks.
- Documented the shipped Phase 25 filesystem Markdown compatibility shim and future-source boundary in the source-adapter architecture docs.
- Ran the focused verification gate across ingestion, storage, API, MCP, `just typecheck`, touched-file pyright, and raw pyright.
- Answered the architecture panel acceptance gate in one final phase summary.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add cross-surface filesystem compatibility regression tests** - `c77edb1` (test)
2. **Task 2: Document the shipped filesystem shim and future-source boundary** - `27e7bcc` (docs)
3. **Task 3: Run full focused verification gate** - `75bc0be` (docs)
4. **Task 4: Write final phase summary with deferred scope audit** - `f6f92a0` (docs)

## Files Created/Modified

- `backend/tests/mcp/test_search_tool.py` - Adds path-based MCP `read` compatibility coverage for frontmatter and ranged chunk output.
- `docs/source-adapter-architecture.md` - Adds the Phase 25 delivered-state section, exact filesystem mapping, storage split, public compatibility contract, and deferred-source boundary.
- `docs/architecture.md` - References the Phase 25 filesystem Markdown compatibility shim from the top-level architecture overview.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` - Final verification and deferred scope audit.

## Architecture Panel Answers

- **Canonical filesystem ref:** `document_ref = str(Path(file_path).resolve())`; `ref = filesystem:<document_ref>`.
- **Where file_path is preserved:** `file_path is preserved` on filesystem `SourceDocument` as a compatibility field and remains public through `SearchResult.file_paths`, `chunk_file_paths_<strategy>`, and MCP `read(file_path, start, end)`.
- **SourceDocument invariant:** when `SourceDocument.namespace == "filesystem"` and `SourceDocument.file_path` is present, `SourceDocument.file_path.resolve()` must equal `document_ref`.
- **Frontmatter metadata owner:** Frontmatter metadata owner is `SourceDocument.metadata_json`, with normalized `title` and `document_type/kind`; current `title`, `kind`, `tags`, and `participants` semantics continue to feed chunking, metadata embeddings, FTS metadata, and graph extraction.
- **Source-unit refs:** Source-unit refs are attached through `Chunk.provenance.source_unit_refs`; Phase 25 filesystem Markdown chunks intentionally persist `[]` because durable parser-emitted source units are deferred.
- **Storage changes:** `source_documents` is global and keyed by `(namespace, document_ref)`. `chunk_source_provenance_<strategy>` is strategy-scoped. `chunk_file_paths_<strategy>` stays authoritative for filesystem search/read compatibility.
- **Bulk and trickle path:** bulk `index(directory)` and trickle `index_file(path)` both route through the filesystem adapter bridge and attach identical filesystem provenance before persisting chunks.
- **Metadata-only behavior:** content/kind fingerprints and metadata fingerprints remain split, so title/tag-only changes still use the metadata-only path and avoid full re-chunking.

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

## Deferred Scope Audit

- Telegram read-only adapter not implemented.
- `mcp-telegram` export API not implemented.
- Source assets not implemented.
- Entity catalogs/canonical identity not implemented.
- Out-of-process transports not implemented.
- TTL policy not implemented.
- Second-source validation not implemented.
- PDF/DOCX/HTML parser support not implemented.

## Decisions Made

- Kept `read(file_path, start, end)` as the Phase 25 public filesystem read contract.
- Treated raw `uv run pyright` failures as pre-existing project-wide debt while relying on the repo-standard `just typecheck` pyright ratchet gate for plan verification.
- Kept future source concepts in docs only; no runtime Telegram, SourceAsset, SourceEntity, transport, TTL, or second-source validation implementation was added.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Raw `cd backend && uv run pyright` still reports 75 project-wide errors. This is the known baseline debt already documented by Plans 25-01 through 25-03. `just typecheck` passed and reported an improvement from the baseline.

## Known Stubs

None. The stub-pattern scan found only intentional empty filesystem `source_unit_refs=[]` and no placeholder implementation that blocks Phase 25's filesystem shim goal.

## Threat Flags

None. This plan added tests and documentation only; no new network endpoint, auth path, file access boundary, or schema trust boundary was introduced.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 25 is ready for completion. Current filesystem Markdown search/read behavior is regression-covered through ingestion, storage, API, and MCP surfaces. Future Telegram, source assets, entity catalogs, transports, TTL, and second-source validation remain explicitly deferred.

## Self-Check: PASSED

- Created summary exists: `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md`.
- Modified files exist: `backend/tests/mcp/test_search_tool.py`, `docs/source-adapter-architecture.md`, `docs/architecture.md`.
- Summary contains `Canonical filesystem ref`, `str(Path(file_path).resolve())`, `file_path is preserved`, `index_file(path)`, `source_documents`, `Frontmatter metadata owner`, `Source-unit refs`, `Telegram read-only adapter not implemented`, and `Self-Check: PASSED`.
- Task commits exist: `c77edb1`, `27e7bcc`, `75bc0be`, `f6f92a0`.
- Focused regression tests pass and repo-standard pyright ratchet passes.

---
*Phase: 25-document-source-abstraction-source-adapter-mvp*
*Completed: 2026-05-05*
