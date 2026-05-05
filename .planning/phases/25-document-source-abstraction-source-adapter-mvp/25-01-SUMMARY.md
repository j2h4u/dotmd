---
phase: 25-document-source-abstraction-source-adapter-mvp
plan: 01
subsystem: ingestion
tags: [source-adapter, filesystem, markdown, pydantic, ingestion]

requires:
  - phase: 25-document-source-abstraction-source-adapter-mvp
    provides: Phase 25 context, research, and architecture panel contract
provides:
  - SourceDocument, SourceUnit, and ChunkProvenance domain models
  - FilesystemMarkdownSourceAdapter for current markdown discovery
  - Filesystem SourceDocument to FileInfo compatibility conversion
  - Focused filesystem adapter contract tests
affects: [ingestion, source-adapter, reader-compatibility, phase-25]

tech-stack:
  added: []
  patterns:
    - Pydantic v2 source domain models with extra fields forbidden
    - Protocol-style source adapter boundary
    - Filesystem compatibility wrapper preserving FileInfo

key-files:
  created:
    - backend/src/dotmd/ingestion/source.py
    - backend/tests/ingestion/test_source_filesystem.py
    - .planning/phases/25-document-source-abstraction-source-adapter-mvp/deferred-items.md
  modified:
    - backend/src/dotmd/core/models.py

key-decisions:
  - "Filesystem document_ref is str(Path(file_path).resolve()) and ref is filesystem:<document_ref>."
  - "Filesystem source documents retain file_path only as a compatibility bridge to current reader callers."
  - "Frontmatter remains document metadata in SourceDocument.metadata_json and continues to feed current title, kind, and checksum behavior."
  - "Telegram, source assets, source entities, adapter transports, TTL policy, and second-source validation remain deferred."

patterns-established:
  - "Source models forbid unknown fields to prevent accidental future-source surface from entering the shim."
  - "Filesystem adapter reuses reader chunk_checksum and meta_checksum rather than duplicating fingerprint formulas."
  - "Compatibility conversion validates filesystem document_ref before producing FileInfo."

requirements-completed: []

duration: 4 min
completed: 2026-05-05
---

# Phase 25 Plan 01: Domain Models and Filesystem Adapter Summary

**Filesystem Markdown source identity now exists as explicit SourceDocument models and an in-process adapter while preserving FileInfo compatibility.**

## Performance

- **Duration:** 4 min
- **Started:** 2026-05-05T20:30:18Z
- **Completed:** 2026-05-05T20:35:01Z
- **Tasks:** 4
- **Files modified:** 5

## Accomplishments

- Added source-aware Pydantic models: `SourceDocument`, `SourceUnit`, and `ChunkProvenance`.
- Added `FilesystemMarkdownSourceAdapter` with deterministic filesystem document refs and current checksum semantics.
- Preserved existing reader compatibility through `source_document_to_file_info()`.
- Added focused tests for frontmatter mapping, canonical refs, fingerprint split, exclusions, and deferred runtime scope.

## Task Commits

Each task was committed atomically:

1. **Task 1: Add source-aware domain models** - `ef7b0a0` (feat)
2. **Task 2: Implement filesystem Markdown source adapter** - `aeff3d6` (feat)
3. **Task 3: Preserve reader compatibility wrappers** - `f65e5f2` (feat)
4. **Task 4: Test filesystem adapter contract and explicit deferrals** - `6e97db9` (test)

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - Adds source-aware domain models and filesystem ref validation.
- `backend/src/dotmd/ingestion/source.py` - Adds source adapter protocol, filesystem markdown adapter, canonical ref helper, and FileInfo compatibility conversion.
- `backend/tests/ingestion/test_source_filesystem.py` - Adds filesystem source adapter contract coverage.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/deferred-items.md` - Records out-of-scope repo-wide pyright failures found during verification.

## Decisions Made

- Filesystem identity is canonicalized as `document_ref == str(Path(file_path).resolve())`.
- `ref` is validated as `f"{namespace}:{document_ref}"`.
- `file_path` remains on filesystem `SourceDocument` only as compatibility data for current readers and search/read surfaces.
- The adapter stays in-process and filesystem/Markdown-only for this plan.

## Deviations from Plan

None - plan executed as written.

## Issues Encountered

- `cd backend && uv run pyright` still fails on pre-existing project-wide type errors outside this plan's changed files. The changed-file pyright check passes for `src/dotmd/core/models.py`, `src/dotmd/ingestion/source.py`, and `tests/ingestion/test_source_filesystem.py`. Details are recorded in `deferred-items.md`.

## Verification

- PASS: `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` -> 5 passed before Task 4.
- PASS: `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_meta_checksum.py -q` -> 18 passed.
- PASS: `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/ingestion/source.py tests/ingestion/test_source_filesystem.py` -> 0 errors.
- PRE-EXISTING FAILURES: `cd backend && uv run pyright` -> 76 errors in existing service, pipeline, trickle, storage, and older tests.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Ready for Plan 25-02 to route current Markdown indexing through the adapter-backed path and attach chunk provenance without changing user-visible search/read behavior.

## Self-Check: PASSED

- Created files exist: `backend/src/dotmd/ingestion/source.py`, `backend/tests/ingestion/test_source_filesystem.py`, `.planning/phases/25-document-source-abstraction-source-adapter-mvp/deferred-items.md`.
- Modified model file exists: `backend/src/dotmd/core/models.py`.
- Task commits exist: `ef7b0a0`, `aeff3d6`, `f65e5f2`, `6e97db9`.

---
*Phase: 25-document-source-abstraction-source-adapter-mvp*
*Completed: 2026-05-05*
