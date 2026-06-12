---
phase: 32-source-capability-registry
plan: 04
subsystem: documentation
tags: [airweave, source-registry, architecture, docs]
requires:
  - phase: 32-source-capability-registry
    provides: source descriptor models and default registry seeds
provides:
  - Airweave-to-dotMD source registry mapping
  - Phase 32 registry boundary in source architecture docs
affects: [phase-33-lifecycle, phase-37-airweave-compatibility, source-adapter-architecture]
tech-stack:
  added: []
  patterns:
    - source catalog concepts are mapped as copied, adapted, rejected, or deferred
key-files:
  created:
    - docs/source-registry-airweave-mapping.md
  modified:
    - docs/source-adapter-architecture.md
key-decisions:
  - "Airweave is an engineering reference, not a runtime dependency or schema to copy."
  - "Phase 33 owns runtime construction, credentials, and cursor commit behavior."
  - "Airweave organizations, billing, Temporal orchestration, and marketplace mechanics are rejected for dotMD Phase 32."
patterns-established:
  - "Architecture docs keep the registry/lifecycle boundary explicit before connector compatibility work."
requirements-completed: ["SRC-04"]
duration: 3min
completed: 2026-05-08
---

# Phase 32 Plan 04: Airweave Mapping Documentation Summary

**Airweave source catalog mapping documented with explicit dotMD registry and lifecycle boundaries**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-08T13:39:05Z
- **Completed:** 2026-05-08T13:41:13Z
- **Tasks:** 2
- **Files modified:** 2

## Accomplishments

- Created `docs/source-registry-airweave-mapping.md` with a copied/adapted/rejected/deferred table for the required Airweave concepts.
- Documented that dotMD has no runtime Airweave dependency.
- Recorded the runtime boundary: Phase 33 owns construction, credentials, and cursor commits.
- Updated the main source architecture doc with the Phase 32 source registry section and Airweave mapping pointer.

## Task Commits

1. **Task 1: Create Airweave-to-dotMD mapping document** - `ca57551` (docs)
2. **Task 2: Update architecture docs with registry boundary** - `f2d8fd3` (docs)

## Files Created/Modified

- `docs/source-registry-airweave-mapping.md` - Field-by-field Airweave concept mapping and runtime boundary.
- `docs/source-adapter-architecture.md` - Phase 32 source registry section and mapping link.

## Decisions Made

- Airweave `class_name`, feature flags, Temporal orchestration, organizations, collections, and billing are not part of the Phase 32 dotMD descriptor contract.
- OAuth/BYOC/rate-limit/auth-provider/entity-catalog details are deferred until lifecycle/auth or entity catalog work needs them.
- The architecture doc remains the canonical place for the source registry and lifecycle boundary.

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

None.

## Verification

- `rg -n "dotMD has no runtime Airweave dependency|copied|adapted|rejected|deferred" docs/source-registry-airweave-mapping.md` - passed.
- `rg -n "Phase 32|source registry|Phase 33|mcp-telegram" docs/source-adapter-architecture.md` - passed.
- `rg -n "from airweave|import airweave" backend/src backend/tests` - passed with no matches.
- `rg -n "supports_browse_tree|output_entity_definitions|class_name|feature_flag" backend/src backend/tests` - passed with no matches.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 32 now documents which Airweave source concepts are usable reference material and which lifecycle/runtime topics remain Phase 33 or later scope.

---
*Phase: 32-source-capability-registry*
*Completed: 2026-05-08*
