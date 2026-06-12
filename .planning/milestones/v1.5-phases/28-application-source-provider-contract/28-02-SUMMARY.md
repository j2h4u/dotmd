---
phase: "28-application-source-provider-contract"
plan: "02"
subsystem: storage
tags: [sqlite, source-state, checkpoint-cursor, source-unit-fingerprints]
requires:
  - phase: "28-01"
    provides: SourceUnit model with updated_at
provides:
  - source checkpoint cursor persistence
  - source-unit fingerprint idempotency helpers
affects: [phase-29-telegram-source-adapter]
tech-stack:
  added: []
  patterns: [caller-owned-sqlite-transactions, additive-source-state-tables]
key-files:
  created: []
  modified:
    - backend/src/dotmd/storage/metadata.py
    - backend/tests/storage/test_metadata_m2m.py
key-decisions:
  - "checkpoint_cursor is durable only inside the caller-owned persistence transaction."
  - "source_unit_fingerprints has no deleted_at or lifecycle status in Phase 28."
requirements-completed: ["R3", "R8"]
duration: 14 min
completed: 2026-05-07
---

# Phase 28 Plan 02: Source State and Fingerprint Storage Summary

**Additive SQLite checkpoint and source-unit fingerprint helpers for safe incremental provider sync**

## Performance

- **Duration:** 14 min
- **Started:** 2026-05-07T17:38:00Z
- **Completed:** 2026-05-07T17:52:00Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Added `source_checkpoints` and helper methods for checkpoint commit, lookup, and error recording.
- Added `source_unit_fingerprints` and helper methods for idempotent active unit replay.
- Covered rollback behavior, standalone diagnostic error persistence, unchanged replay, changed fingerprints, and metadata JSON round-trip.

## Task Commits

1. **Source checkpoint and fingerprint storage** - `b0d0cff` (`feat(28-02)`)

## Files Created/Modified

- `backend/src/dotmd/storage/metadata.py` - Additive source-state schema and helpers.
- `backend/tests/storage/test_metadata_m2m.py` - Storage contract regression tests.

## Decisions Made

Followed the existing metadata-store convention: transaction-coupled writes require caller-owned `conn` and do not call `commit()`, while standalone diagnostic error recording commits only when no `conn` is supplied.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `rg -n "def (upsert_source_document|upsert_resource_binding|set_resource_binding_active|delete_m2m_for_file|backfill_resource_bindings_from_source_documents|commit_source_checkpoint|record_source_checkpoint_error)" backend/src/dotmd/storage/metadata.py` confirmed helper placement and transaction signatures.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` passed: 23 passed.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Plan 03 could exercise the provider protocol and storage idempotency through deterministic fixtures.

---
*Phase: 28-application-source-provider-contract*
*Completed: 2026-05-07*
