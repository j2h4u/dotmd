---
phase: 24-config-separation-user-facing-settings-vs-internal-constants
plan: 02-startup-docs-and-template
subsystem: config
tags: [settings, startup-checks, docs, env-template]

requires:
  - phase: 24-config-separation-user-facing-settings-vs-internal-constants
    provides: Settings runtime validation and effective indexing excludes from Plan 24-01
provides:
  - DOTMD_RUN_STARTUP_CHECKS startup safety switch with ENVIRONMENT=dev compatibility alias
  - Operator-first .env.example grouped by deployment, identity, optional, startup, and tuning settings
  - README configuration docs matching the Phase 24 public settings boundary
affects: [config, deployment, mcp-runtime, documentation]

tech-stack:
  added: []
  patterns:
    - Startup checks are an explicit operational safety switch, not an environment profile
    - Operator config docs group required deployment values before advanced tuning

key-files:
  created:
    - .planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-02-startup-docs-and-template-SUMMARY.md
  modified:
    - backend/start.sh
    - .env.example
    - README.md

key-decisions:
  - "Use DOTMD_RUN_STARTUP_CHECKS=true as the primary restart-time pre-flight gate switch while preserving ENVIRONMENT=dev as a temporary compatibility alias."
  - "Document DOTMD_INDEXING_EXTRA_EXCLUDE as additive and DOTMD_INDEXING_EXCLUDE as legacy replace-only in both .env.example and README."
  - "Keep tuning variables discoverable under Advanced tuning rather than presenting them as the primary operator checklist."

patterns-established:
  - "Startup safety gate wording should name DOTMD_RUN_STARTUP_CHECKS first and avoid environment-profile language."
  - "Configuration docs should separate required deployment config, index/search identity, optional features, and advanced tuning."

requirements-completed: []

duration: 3 min
completed: 2026-05-05
---

# Phase 24 Plan 02: Startup Docs and Template Summary

**Startup safety switch and operator config docs now match the Phase 24 runtime settings boundary.**

## Performance

- **Duration:** 3 min
- **Started:** 2026-05-05T16:06:34Z
- **Completed:** 2026-05-05T16:09:19Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Renamed the container restart pre-flight gate to `DOTMD_RUN_STARTUP_CHECKS=true` while preserving `ENVIRONMENT=dev` as a compatibility alias.
- Reorganized `.env.example` so required deployment values and index/search identity are visible before optional features and advanced tuning.
- Rewrote README configuration docs to document path filtering, FalkorDB runtime safety, startup checks, and advanced tuning separately.

## Task Commits

Each task was committed atomically:

1. **Task 1: Rename and preserve startup pre-flight switch** - `44c2e05` (fix)
2. **Task 2: Split `.env.example` into operator config and advanced tuning** - `0239bd7` (docs)
3. **Task 3: Update README configuration docs to match the new surface** - `7fe33af` (docs)

**Plan metadata:** pending

## Files Created/Modified

- `backend/start.sh` - Uses `DOTMD_RUN_STARTUP_CHECKS=true` as the primary startup safety gate switch and keeps `ENVIRONMENT=dev` as a temporary alias.
- `.env.example` - Groups deployment config, index/search identity, optional features, startup safety, and advanced tuning; documents additive vs replace-only indexing excludes.
- `README.md` - Documents the same config surface and clarifies FalkorDB runtime URL validation and startup-check semantics.
- `.planning/phases/24-config-separation-user-facing-settings-vs-internal-constants/24-02-startup-docs-and-template-SUMMARY.md` - Captures execution outcome and verification.

## Decisions Made

- `DOTMD_RUN_STARTUP_CHECKS=true` is the primary switch for the restart-time lint/type/live-MCP e2e gate.
- `ENVIRONMENT=dev` remains only as a temporary compatibility alias, explicitly documented as not being an environment profile.
- `DOTMD_INDEXING_EXTRA_EXCLUDE` is the documented additive operator setting; `DOTMD_INDEXING_EXCLUDE` is documented as legacy replace-only.
- `DOTMD_SEMANTIC_SCORE_FLOOR` in `.env.example` now matches the Python default `0.85`.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope was added beyond the planned startup/docs/template alignment.

## Issues Encountered

None.

## Verification

- `sh -n backend/start.sh` - passed.
- `rg --no-heading "DOTMD_RUN_STARTUP_CHECKS|Required deployment configuration|Advanced tuning" backend/start.sh .env.example README.md` - passed.
- `! rg --quiet "DOTMD_SEMANTIC_SCORE_FLOOR=0.4" .env.example` - passed.
- `cd backend && uv run pytest tests/core/test_config_separation.py tests/core/test_config_base_url.py -q` - passed (`21 passed, 18 warnings`).
- `cd backend && uv run ruff check src/dotmd/core/config.py` - passed.

## Known Stubs

None.

## Threat Flags

None.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

Phase 24 is ready for closure: Plan 24-01 established the runtime config boundary, and Plan 24-02 aligned startup behavior, the env template, and README documentation with that boundary.

## Self-Check: PASSED

- Key modified files exist: `backend/start.sh`, `.env.example`, `README.md`.
- Task commits exist in git history: `44c2e05`, `0239bd7`, `7fe33af`.
- Stub scan across modified files found no placeholder/TODO/FIXME patterns.
- Verification commands were run and passed.

---
*Phase: 24-config-separation-user-facing-settings-vs-internal-constants*
*Completed: 2026-05-05*
