---
phase: 41-production-grade-surreal-schema-and-import
plan: 01
subsystem: database
tags: [surrealdb, python, schema, migration, tdd]
requires:
  - phase: 39-surrealdb-native-retrieval-contract
    provides: retrieval reuse boundaries and no-recompute migration policy
  - phase: 40-evaluation-harness-and-golden-queries
    provides: phase-level acceptance context for later migration evidence
provides:
  - versioned Surreal schema catalog with structured table, field, and index metadata
  - explicit schema apply-status outcomes for offline planning and guarded target mutation
  - focused RED/GREEN schema contract coverage for SURR-MIG-01
affects: [41-02, 41-03, 42, surreal migration runner, retrieval cutover]
tech-stack:
  added: []
  patterns: [versioned schema catalog, offline schema inspection, centralized record-id encoding]
key-files:
  created:
    - backend/src/dotmd/storage/surreal_schema.py
    - backend/tests/storage/test_surreal_schema_definition.py
  modified:
    - backend/src/dotmd/storage/surreal.py
    - backend/tests/storage/test_surreal_storage_contract.py
key-decisions:
  - "Schema planning lives in surreal_schema.py and returns structured metadata plus deterministic DDL without requiring a live Surreal target."
  - "relations stays a metadata-carrying relation table without default ENFORCED endpoint rejection, preserving rel_type and endpoint hints for migration safety."
  - "Schema apply writes only on compatible targets and reports explicit not-applied/already-current/applied/replace-required outcomes."
patterns-established:
  - "Build plan first, validate required categories/fields, then optionally apply in statement order."
  - "Reuse the schema catalog from surreal.py for apply decisions and table enumeration instead of duplicating literals."
requirements-completed: [SURR-MIG-01]
duration: 6min
completed: 2026-06-13
status: complete
---

# Phase 41 Plan 01: Production-grade Surreal schema and import Summary

**Versioned Surreal schema metadata and guarded apply-status wiring for documents, chunks, bindings, graph relations, and migration-state categories**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-13T23:23:23+05:00
- **Completed:** 2026-06-13T23:29:02+05:00
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments

- Added RED coverage for the Phase 41 schema catalog, required migration categories, relation metadata, and fail-closed apply statuses.
- Implemented `surreal_schema.py` with versioned table/field/index metadata, deterministic DDL generation, and schema validation helpers.
- Rewired `surreal.py` to reuse the production schema catalog for apply decisions and schema-table enumeration while preserving `SurrealRecordIdCodec` as the only record-ID encoding path.

## TDD Notes

- **RED:** `38fe211` added failing schema-catalog tests and updated the storage contract to reject the Phase 38 thin prototype surface.
- **GREEN:** `e80bb0e` introduced the production schema catalog and passed the focused schema/storage suite.
- **REFACTOR:** None - GREEN implementation was kept as the final task commit.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED schema catalog tests for SURR-MIG-01 | `38fe211` | `test` |
| 2 | Implement the production schema catalog and wire storage helpers | `e80bb0e` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/storage/surreal_schema.py` - Production schema catalog, apply-status dataclass, validation helpers, and generated DDL metadata.
- `backend/src/dotmd/storage/surreal.py` - Reuses the schema catalog for inspection and table clearing while preserving existing record-ID and store helper surfaces.
- `backend/tests/storage/test_surreal_schema_definition.py` - RED/GREEN coverage for schema categories, fields, relation metadata, and fail-closed apply statuses.
- `backend/tests/storage/test_surreal_storage_contract.py` - Updated schema contract assertions to expect the Phase 41 production surface instead of the Phase 38 prototype note.

## Schema Fields Locked

- `schema_version`
- `original_chunk_id`
- `chunk_strategy`
- `embedding_model`
- `text_hash`
- `vector_rowid`
- `namespace`
- `document_ref`
- `ref`
- `active`
- `bound_at`
- `unbound_at`
- `content_fingerprint`
- `metadata_fingerprint`
- `source_unit_refs`
- `checkpoint_cursor`
- `rel_type`
- `weight`
- `source_id`
- `target_id`
- `source_table`
- `target_table`
- `metadata`
- `properties`

## Decisions Made

- Used a dedicated `schema_meta` sentinel row to support explicit schema-version status reporting without pushing runtime retrieval work into Phase 41.
- Kept `stats`, `search_log`, and cache categories outside the required migration-success path while still documenting them as unsupported/noncanonical.
- Treated `vector_components` as optional derived physical storage and not a prerequisite for later retrieval phases.

## Verification Output

- `cd backend && uv run pytest tests/storage/test_surreal_schema_definition.py tests/storage/test_surreal_storage_contract.py -x` -> PASS (`16 passed`)
- `cd backend && uv run ruff check src/dotmd/storage/surreal_schema.py src/dotmd/storage/surreal.py tests/storage/test_surreal_schema_definition.py tests/storage/test_surreal_storage_contract.py` -> PASS
- `cd backend && uv run python -c "from dotmd.storage.surreal import define_dotmd_surreal_schema; ..."` -> PASS (`41.1.0`, `chunk_file_bindings=True`, relation table present, `ENFORCED=False`)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Known Stubs

- `backend/src/dotmd/storage/surreal.py:779` - `file_path=\"\"` remains in the existing relation-import helper when synthesizing placeholder section nodes; this is legacy fallback data outside Phase 41 schema scope.
- `backend/src/dotmd/storage/surreal.py:780` - `text_preview=\"\"` remains in the same placeholder section-node path for imported relations; unchanged here because retrieval/graph-shape cleanup belongs to later phases.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 41-02 can build the migration runner against explicit required/unsupported category metadata, guarded apply statuses, and stable table ordering.
- No blocker remains for schema/import runner work within the planned Phase 41 scope.

## Self-Check

PASSED

- Found `.planning/phases/41-production-grade-surreal-schema-and-import/41-01-SUMMARY.md`
- Found task commits `38fe211` and `e80bb0e` in git history

---
*Phase: 41-production-grade-surreal-schema-and-import*
*Completed: 2026-06-13*
