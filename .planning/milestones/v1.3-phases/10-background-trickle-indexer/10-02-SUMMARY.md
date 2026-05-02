---
phase: 10-background-trickle-indexer
plan: 02
subsystem: config, ingestion
tags: [pydantic-settings, toml, glob, file-discovery, watchdog]

# Dependency graph
requires:
  - phase: none
    provides: n/a
provides:
  - "Settings with TOML config source (env > toml > defaults)"
  - "indexing_paths / indexing_exclude fields for multi-path discovery"
  - "trickle_pause_seconds / poll_interval_seconds for trickle indexer"
  - "discover_files_multi() for glob + directory file discovery with exclude"
  - "watchdog dependency declared in pyproject.toml"
affects: [10-03-PLAN, 10-04-PLAN]

# Tech tracking
tech-stack:
  added: [pydantic-settings[toml], watchdog]
  patterns: [TomlConfigSettingsSource with conditional loading, os.walk pruning for exclude]

key-files:
  created: []
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/ingestion/reader.py
    - backend/pyproject.toml

key-decisions:
  - "TOML source only loaded when ~/.dotmd/config.toml exists -- no startup failure without config"
  - "Exclude patterns pruned during os.walk (not post-filtered) for performance on large trees"
  - "watchdog dependency added now to avoid pyproject.toml merge conflicts with Plan 03"

patterns-established:
  - "TomlConfigSettingsSource: conditional TOML loading via settings_customise_sources"
  - "Multi-path discovery: directory walk + glob patterns with dedup via resolved paths"

requirements-completed: [BGIDX-05, BGIDX-06]

# Metrics
duration: 2min
completed: 2026-03-27
---

# Phase 10 Plan 02: Config & File Discovery Summary

**TOML config source with env override, multi-path file discovery via glob patterns and exclude filtering, trickle indexer settings**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-27T19:27:32Z
- **Completed:** 2026-03-27T19:29:48Z
- **Tasks:** 2
- **Files modified:** 3

## Accomplishments
- Settings class loads from ~/.dotmd/config.toml with env var override priority
- Multi-path discovery supports both directory paths and glob patterns
- Exclude patterns prune directories during os.walk for performance on large trees (node_modules, .git, __pycache__)
- trickle_pause_seconds and poll_interval_seconds configurable for trickle indexer

## Task Commits

Each task was committed atomically:

1. **Task 1: Add TOML config source and trickle settings to config.py** - `86659be` (feat)
2. **Task 2: Add multi-path file discovery with glob and exclude filtering** - `dbc6a6e` (feat)

## Files Created/Modified
- `backend/src/dotmd/core/config.py` - TomlConfigSettingsSource, indexing_paths/exclude, trickle settings
- `backend/src/dotmd/ingestion/reader.py` - discover_files_multi(), _is_excluded(), _prune_dirs() helpers
- `backend/pyproject.toml` - pydantic-settings[toml] extra, watchdog dependency

## Decisions Made
- TOML source conditionally loaded only when config.toml exists -- avoids startup failure for users without config
- Exclude patterns use os.walk pruning (modifying dirs in-place) rather than post-filtering, per Pitfall 7 from research
- watchdog dependency added in this plan to avoid pyproject.toml merge conflict with Plan 03

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
- python3 not on PATH, used .venv/bin/python for verification (uv-managed venv)
- pydantic-settings emits UserWarning about toml_file config key when TOML source is conditionally added -- harmless and expected behavior

## Known Stubs

None - all functionality fully wired.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness
- Settings fields (indexing_paths, indexing_exclude, trickle_pause_seconds, poll_interval_seconds) ready for Plan 03 (watcher) and Plan 04 (trickle loop)
- discover_files_multi() ready for use by trickle indexer pipeline
- watchdog dependency declared, ready for Plan 03 import

## Self-Check: PASSED

- All 3 modified files exist on disk
- Both task commits verified (86659be, dbc6a6e)
- SUMMARY.md created at expected path

---
*Phase: 10-background-trickle-indexer*
*Completed: 2026-03-27*
