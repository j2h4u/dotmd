---
phase: 27-resource-bindings-retained-artifacts-foundation
plan: 01
subsystem: storage
tags: [sqlite, metadata, resource-bindings, provenance, tdd]

requires:
  - phase: 26-source-ref-first-read-search-contract-cleanup
    provides: source-ref-first provenance and public ref identity
provides:
  - ResourceBinding domain model for active/inactive resource visibility state
  - resource_bindings SQLite table with active and fingerprint indexes
  - idempotent source_documents to active resource_bindings backfill
  - active-only chunk provenance helper for public visibility filtering
  - inactive retained chunk count diagnostic helper
affects: [phase-27, phase-28, phase-29, phase-30, phase-31, source-adapters]

tech-stack:
  added: []
  patterns:
    - Caller-owned SQLite mutation helpers
    - Idempotent CREATE TABLE and INSERT ON CONFLICT migrations
    - Source-ref-first active visibility filtering through provenance joins

key-files:
  created:
    - .planning/phases/27-resource-bindings-retained-artifacts-foundation/27-01-SUMMARY.md
  modified:
    - backend/src/dotmd/core/models.py
    - backend/src/dotmd/storage/metadata.py
    - backend/tests/storage/test_metadata_m2m.py

key-decisions:
  - "source_documents remains authoritative for active/current document metadata; resource_bindings stores activity state and fingerprint snapshots for retained lookup."
  - "Existing source_documents rows are backfilled into active resource_bindings during SQLiteMetadataStore readiness using non-overwrite conflict handling."
  - "Active public provenance is resolved by joining chunk_source_provenance_<strategy> to resource_bindings where active = 1, preserving retained inactive rows."

patterns-established:
  - "Active resource binding state is separate from retained chunks, provenance, FTS/vector metadata, and graph-owned artifacts."
  - "Backfills copy already persisted SQLite metadata only and do not read files, call TEI, rebuild FTS/vector tables, or touch graph storage."

requirements-completed: [R1, R2, R8]

duration: 8min
completed: 2026-05-07
---

# Phase 27 Plan 01: Storage Binding State Summary

**SQLite resource binding state with active/inactive visibility, idempotent source-document backfill, and active-only provenance helpers**

## Performance

- **Duration:** 8 min
- **Started:** 2026-05-07T14:34:10Z
- **Completed:** 2026-05-07T14:42:15Z
- **Tasks:** 3
- **Files modified:** 3

## Accomplishments

- Added `ResourceBinding` with canonical `namespace:document_ref` validation and filesystem `resource_ref == document_ref` validation.
- Added `resource_bindings` with active state, retained fingerprint snapshots, lifecycle metadata, and indexes for active document and retained fingerprint lookup.
- Added idempotent startup backfill from existing `source_documents` rows into active bindings using `ON CONFLICT(namespace, resource_ref) DO NOTHING`.
- Added active-only provenance reads that exclude inactive retained resources while leaving normal retained provenance reads intact.
- Added regression coverage for active/inactive counts, backfill idempotence, inactive preservation, active provenance selection, retained row preservation, and the active-binding index path.

## Task Commits

Each task was committed atomically with TDD RED and GREEN commits:

1. **Task 1: Add resource binding domain model and SQLite table helpers**
   - `961f97c` test(27-01): add failing test for resource bindings
   - `0c3256e` feat(27-01): add resource binding storage state
2. **Task 2: Backfill existing source documents into active bindings**
   - `072d134` test(27-01): add failing test for binding backfill
   - `f15c946` feat(27-01): backfill source documents into bindings
3. **Task 3: Add active provenance query helpers without deleting retained rows**
   - `a707255` test(27-01): add failing test for active provenance helpers
   - `d52c839` feat(27-01): add active provenance storage helpers

**Plan metadata:** committed separately in the final docs commit.

## Files Created/Modified

- `backend/src/dotmd/core/models.py` - Added `ResourceBinding` domain model and ref validation.
- `backend/src/dotmd/storage/metadata.py` - Added resource binding DDL, CRUD/count helpers, source-document backfill, active provenance query helper, and inactive retained chunk count helper.
- `backend/tests/storage/test_metadata_m2m.py` - Added storage tests for binding state, backfill, active provenance filtering, retained rows, and query plan index usage.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-01-SUMMARY.md` - Execution summary and verification record.

## Decisions Made

- `source_documents` remains the source of truth for active/current document metadata. `resource_bindings` stores active state, lifecycle metadata, and fingerprint snapshots used for retained lookup.
- Backfill runs from `SQLiteMetadataStore.__init__` after ensuring `resource_bindings`, so existing production `source_documents` rows become active bindings before later public active filtering can hide them.
- Active provenance filtering is a read-only helper over retained provenance rows; inactive rows are not deleted or rebuilt.

## Verification

- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` - PASS, 18 passed.
- Acceptance grep checks confirmed required symbols, table DDL, indexes, non-null fingerprint defaults, backfill SQL, active filter SQL, and test assertions are present.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None. Implementation debugging stayed within planned TDD cycles.

## User Setup Required

None - no external service configuration required.

## TDD Gate Compliance

PASS - RED and GREEN commits exist for each task. No refactor commit was needed.

## Next Phase Readiness

Ready for Plan 27-02. The storage foundation can now represent inactive bindings and active-only provenance without full reindex, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild.

## Self-Check: PASSED

- Summary file exists.
- Task commits exist: `961f97c`, `0c3256e`, `072d134`, `f15c946`, `a707255`, `d52c839`.
- Verification command passed: `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q`.

---
*Phase: 27-resource-bindings-retained-artifacts-foundation*
*Completed: 2026-05-07*
