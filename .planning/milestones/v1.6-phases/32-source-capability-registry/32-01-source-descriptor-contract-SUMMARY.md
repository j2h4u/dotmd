---
phase: 32-source-capability-registry
plan: 01
subsystem: source-registry
tags: [pydantic, source-descriptors, registry, capabilities]
requires:
  - phase: 31-telegram-search-read-drill-smoke
    provides: live Telegram source refs and source-unit read smoke
provides:
  - typed declarative source descriptor models
  - closed source capability enum
  - in-memory source descriptor registry
affects: [source-registry, unified-source-architecture, phase-33-lifecycle]
tech-stack:
  added: []
  patterns:
    - strict Pydantic descriptor models with forbidden extra fields
    - registry returns deep copies to protect descriptor internals
key-files:
  created:
    - backend/src/dotmd/core/source_registry.py
    - backend/tests/ingestion/test_source_registry.py
  modified:
    - backend/src/dotmd/core/models.py
key-decisions:
  - "Source descriptors are declarative Pydantic models, not runtime factories."
  - "Source capability names are a closed enum for Phase 32."
  - "SourceRegistry returns deep copies so callers cannot mutate registered descriptors."
patterns-established:
  - "Descriptor schemas use ConfigDict(extra=\"forbid\") and Field(default_factory=...) for all mutable defaults."
  - "Capability comparison should use SourceCapability enum values or their canonical string values."
requirements-completed: ["SRC-01", "SRC-03"]
duration: 6min
completed: 2026-05-08
---

# Phase 32 Plan 01: Source Descriptor Contract Summary

**Typed declarative source descriptors with a closed capability enum and mutation-safe registry container**

## Performance

- **Duration:** 6 min
- **Started:** 2026-05-08T13:29:00Z
- **Completed:** 2026-05-08T13:35:11Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments

- Added `SourceCapability` with the exact Phase 32 vocabulary: local sync, federated search, read-unit windows, materialization, browse trees, ACL, and incremental cursors.
- Added strict descriptor schema models for display metadata, config schema, auth schema, cursor schema, and `SourceDescriptor`.
- Added `SourceRegistry` with duplicate namespace rejection and deep-copy reads.
- Added regression tests for enum closure, strict schemas, mutable-default safety, unknown capability rejection, and duplicate namespace rejection.

## Task Commits

1. **Task 1: Add descriptor model tests first** - `2e09fed` (test)
2. **Task 2: Implement typed descriptor models and registry container** - `ea272a6` (feat)

## Files Created/Modified

- `backend/tests/ingestion/test_source_registry.py` - Descriptor contract and registry tests.
- `backend/src/dotmd/core/models.py` - Source capability enum and strict descriptor Pydantic models.
- `backend/src/dotmd/core/source_registry.py` - Declarative descriptor registry keyed by namespace.

## Decisions Made

- Kept the registry in `core` and free of provider construction, credentials, cursor writes, Airweave imports, and lifecycle behavior.
- Used `dict[str, Any]` only for descriptor metadata payloads; the source schemas themselves remain typed structural models.
- `SourceRegistry.require()` raises `KeyError` for missing namespaces while duplicate registration raises the planned `ValueError`.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Repo-wide `uv run pyright` still fails on pre-existing unrelated type errors in `service.py`, `trickle.py`, `graph.py`, and legacy tests. Scoped pyright on the new/changed descriptor files passed.

## Verification

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py -q` - passed.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/source_registry.py tests/ingestion/test_source_registry.py` - passed.
- `cd backend && uv run pyright` - failed on pre-existing unrelated repo-wide errors.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

The descriptor contract and registry container are ready for filesystem and Telegram seed descriptors in Plan 32-02 and descriptor-to-description compatibility in Plan 32-03.

---
*Phase: 32-source-capability-registry*
*Completed: 2026-05-08*
