---
phase: 42-surreal-native-retrieval-implementation
plan: 01
subsystem: database
tags: [surrealdb, python, retrieval, schema, tdd]
requires:
  - phase: 39-surrealdb-native-retrieval-contract
    provides: surreal-native retrieval semantics and accepted-difference policy
  - phase: 41-production-grade-surreal-schema-and-import
    provides: production schema/import baseline and transform-only migration surface
provides:
  - lexical chunk fields for weighted Surreal BM25 retrieval
  - typed Surreal retrieval index-plan and capability-probe helpers
  - shared embedded-Surreal test fixture for later retrieval engine plans
affects: [42-02, 42-03, 42-04, 43]
tech-stack:
  added: []
  patterns: [typed retrieval index planning, scratch-target capability probing, transform-only lexical field materialization]
key-files:
  created:
    - backend/tests/fixtures/surreal_native.py
  modified:
    - backend/src/dotmd/storage/surreal_schema.py
    - backend/src/dotmd/ingestion/migrate_surreal.py
    - backend/tests/storage/test_surreal_schema_definition.py
    - backend/tests/ingestion/test_surreal_production_migration.py
key-decisions:
  - "Phase 42 stays on the locally verified Surreal 2.x runtime surface: SEARCH ANALYZER BM25, HNSW, relation tables, and Python-side fusion."
  - "tags_text is materialized only from source_documents.metadata_json['tags'] and remains transform-only over the copied SQLite snapshot."
  - "The schema version advances to 42.1.0 so Phase 41 targets do not falsely report already-current while missing new retrieval fields."
patterns-established:
  - "Keep retrieval DDL in typed helpers instead of scattering SurrealQL string literals across future engine modules."
  - "Probe required retrieval capabilities on isolated surrealkv scratch targets and treat newer-runtime-only features as observations, not gates."
requirements-completed: [SURR-SEARCH-01, SURR-SEARCH-02, SURR-SEARCH-03]
duration: 6min
completed: 2026-06-14
status: complete
---

# Phase 42 Plan 01: Surreal-native retrieval implementation Summary

**Surreal retrieval foundation with lexical chunk fields, typed BM25/HNSW index planning, relation target lookup indexing, and a scratch-target capability probe**

## Performance

- **Duration:** 6 min
- **Started:** 2026-06-14T12:29:22+05:00
- **Completed:** 2026-06-14T12:35:37+05:00
- **Tasks:** 2
- **Files modified:** 5

## Accomplishments

- Added RED coverage for retrieval-specific chunk fields, Surreal BM25/HNSW index planning, bounded HNSW validation, transform-only lexical field materialization, and scratch-target capability reporting.
- Extended the production Surreal schema/import surface with `chunks.title`, `chunks.tags_text`, `relations_target_id_idx`, typed retrieval-plan helpers, and a fail-closed capability probe.
- Created a reusable `surrealkv://` fixture helper so Plans 42-02 and 42-03 can prove real embedded Surreal retrieval instead of fake-only tests.

## TDD Notes

- **RED:** `36d5340` added failing schema/migration tests plus the shared embedded-Surreal fixture surface.
- **GREEN:** `4c6f98f` implemented lexical materialization, retrieval DDL helpers, bounded validation, capability probing, and the schema-version bump required to apply the new fields safely.
- **REFACTOR:** None.

## Task Commits

| Task | Name | Commit | Type |
| ---- | ---- | ------ | ---- |
| 1 | Write RED tests for retrieval index fields and capability probing | `36d5340` | `test` |
| 2 | Implement retrieval schema fields, index plan, lexical materialization, and capability report | `4c6f98f` | `feat` |

## Files Created/Modified

- `backend/src/dotmd/storage/surreal_schema.py` - Adds retrieval schema fields, target-id indexing, typed BM25/HNSW DDL helpers, validation bounds, and capability reporting.
- `backend/src/dotmd/ingestion/migrate_surreal.py` - Materializes `title` and `tags_text` from copied `source_documents` rows without source-file reads or recomputation.
- `backend/tests/fixtures/surreal_native.py` - Shared isolated embedded-Surreal fixture and schema-application helper for later engine plans.
- `backend/tests/storage/test_surreal_schema_definition.py` - Covers lexical field presence, retrieval DDL shape, HNSW contract bounds, and capability probe reporting.
- `backend/tests/ingestion/test_surreal_production_migration.py` - Verifies transform-only lexical materialization from `source_documents.metadata_json["tags"]`.

## Decisions Made

- Kept retrieval planning on the locally verified Surreal 2.x syntax instead of introducing `FULLTEXT`, `DISKANN`, or built-in hybrid helpers that the current embedded runtime rejects.
- Pinned `tags_text` to `source_documents.metadata_json["tags"]` only, with list/scalar normalization to a space-separated string and empty-string fallback for missing metadata.
- Preferred copied `source_documents.ref` when present so migrated chunk refs stay aligned with stored source identity instead of reconstructed guesses.

## Verification Output

- `cd backend && uv run pytest tests/storage/test_surreal_schema_definition.py tests/ingestion/test_surreal_production_migration.py -q` -> PASS (`21 passed`)
- `cd backend && uv run ruff check src/dotmd/storage/surreal_schema.py src/dotmd/ingestion/migrate_surreal.py tests/fixtures/surreal_native.py tests/storage/test_surreal_schema_definition.py tests/ingestion/test_surreal_production_migration.py` -> PASS

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Advanced the schema version to avoid false already-current targets**
- **Found during:** Task 2
- **Issue:** Keeping `41.1.0` would let existing Phase 41 Surreal targets skip the new `chunks.title` / `chunks.tags_text` fields and relation target-id index.
- **Fix:** Bumped the schema to `42.1.0` and treated `41.1.0` as a compatible upgrade source.
- **Files modified:** `backend/src/dotmd/storage/surreal_schema.py`, `backend/tests/ingestion/test_surreal_production_migration.py`
- **Verification:** Focused pytest and ruff gates passed with the new schema version and upgrade path.
- **Committed in:** `4c6f98f`

---

**Total deviations:** 1 auto-fixed (1 bug fix)
**Impact on plan:** The auto-fix was required for correct schema upgrade semantics. No runtime-cutover or legacy-removal scope was added.

## Issues Encountered

- `AGENTS.md` says dotMD normally works on `main`, but the user explicitly required execution on the current branch/worktree context. Work stayed on `milestone/v1.8-surrealdb-cutover` without rewriting branch state.

## Known Stubs

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 42-02 can build the BM25 and HNSW engines against shared retrieval DDL helpers, query-parameter bounds, and the embedded fixture without editing the fixture file.
- Plan 42-03 can reuse the same fixture and the new `relations_target_id_idx` path for entity/tag lookups.
- Runtime consumption of the capability report remains intentionally deferred to Phase 43 shadow-run gating or Phase 44 startup wiring.

## Self-Check

PASSED

- Found `.planning/phases/42-surreal-native-retrieval-implementation/42-01-SUMMARY.md`
- Found task commits `36d5340` and `4c6f98f` in git history

---
*Phase: 42-surreal-native-retrieval-implementation*
*Completed: 2026-06-14*
