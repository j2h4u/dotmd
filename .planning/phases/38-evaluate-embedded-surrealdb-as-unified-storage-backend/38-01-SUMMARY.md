---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
plan: 01
subsystem: database
tags: [surrealdb, sqlite, sqlite-vec, falkordb, migration, inventory]
requires: []
provides:
  - "Read-only snapshot and inventory helpers for current SQLite/Falkor/feedback storage"
  - "Copied-snapshot evidence for index.db and feedback.db with WAL-safe backup discipline"
  - "Explicit D-01 migration map for transform-first Surreal import planning"
affects: [38-02, 38-03, 38-04, 38-05]
tech-stack:
  added: []
  patterns:
    - "SQLite backup API for WAL-safe read-only snapshots"
    - "Transform-first migration evidence before any Surreal import work"
    - "Exporter-only feedback counting to avoid direct feedback.db SQL"
key-files:
  created:
    - backend/src/dotmd/storage/surreal_inventory.py
    - backend/tests/storage/test_surreal_storage_contract.py
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-SUMMARY.md
  modified:
    - backend/src/dotmd/storage/surreal_inventory.py
    - backend/tests/storage/test_surreal_storage_contract.py
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md
    - .planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md
key-decisions:
  - "Phase 38 inventory snapshots use the SQLite backup API so WAL-mode sources become standalone copies without mutating live files."
  - "Feedback counts stay on the supported CLI exporter path; feedback.db snapshots are file-level evidence only."
  - "Falkor relation semantics must preserve semantic edge type in rel_type plus numeric weight, not only aggregate edge totals."
patterns-established:
  - "Inventory helpers accept caller-provided paths only and expose drift through unmapped_tables."
  - "Graph inventory records relation labels, metadata keys, and sampled property value types before any Surreal schema work."
requirements-completed: [STOR-01, STOR-03]
duration: 21min
completed: 2026-06-12
status: complete
---

# Phase 38 Plan 01: Storage Inventory Evidence Summary

**WAL-safe copied SQLite snapshots plus live Falkor/feedback inventory evidence for transform-first Surreal migration planning**

## Performance

- **Duration:** 21 min
- **Started:** 2026-06-12T13:59:00Z
- **Completed:** 2026-06-12T14:20:33Z
- **Tasks:** 3
- **Files modified:** 4

## Accomplishments

- Added RED/GREEN storage contract coverage for snapshot copying, WAL handling, SQLite inventory, graph relation metadata, feedback inventory, and migration-map classification.
- Implemented `surreal_inventory.py` with read-only SQLite snapshot/inventory helpers, Falkor and feedback abstractions, and an explicit migration-map builder.
- Captured real Phase 38 evidence from copied `index.db` / `feedback.db` snapshots plus live Falkor exporter output in `38-01-INVENTORY.md` and `38-01-MIGRATION-MAP.md`.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED inventory contract tests for current storage state** - `23e212c` (`test`)
2. **Task 2: Implement read-only inventory and migration-map helpers** - `5e5738a` (`feat`)
3. **Task 3: Capture copied-snapshot inventory and migration-map evidence** - `5f92731` (`docs`)

## Files Created/Modified

- `backend/src/dotmd/storage/surreal_inventory.py` - read-only snapshot, SQLite inventory, graph inventory, feedback inventory, and migration-map helpers
- `backend/tests/storage/test_surreal_storage_contract.py` - TDD contract coverage for Phase 38 storage evidence behavior
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-INVENTORY.md` - copied snapshot evidence with live counts, WAL handling, and graph relation summaries
- `.planning/phases/38-evaluate-embedded-surrealdb-as-unified-storage-backend/38-01-MIGRATION-MAP.md` - D-01 migration disposition table and transform-first caveats

## Decisions Made

- Used SQLite backup API as the canonical snapshot strategy so WAL state is captured without mutating the live source database.
- Kept feedback counting on the supported `dotmd feedback list --all` path; `feedback.db` snapshot metadata is evidence, not an alternate query surface.
- Treated Falkor `REL.rel_type` + `weight` as the minimum graph semantics Phase 38-02 must preserve during import planning.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed WAL RED fixture so sidecars actually remain live during the snapshot test**
- **Found during:** Task 2
- **Issue:** The initial RED fixture closed the SQLite connection before the sidecar assertion, so the test was checking for a WAL/SHM state that SQLite had already cleaned up.
- **Fix:** Held the fixture connection open and disabled auto-checkpoint during the WAL snapshot test.
- **Files modified:** `backend/tests/storage/test_surreal_storage_contract.py`
- **Verification:** `cd backend && uv run pytest tests/storage/test_surreal_storage_contract.py -x`
- **Committed in:** `5e5738a`

**2. [Rule 1 - Bug] Excluded FTS5 shadow tables from `fts_rows` inventory counts**
- **Found during:** Task 2
- **Issue:** Counting every `chunks_fts_*` SQLite object inflated the FTS row total because SQLite exposes FTS5 shadow tables alongside the real virtual table.
- **Fix:** Count only virtual `chunks_fts_*` tables discovered through `sqlite_master` entries whose SQL starts with `CREATE VIRTUAL TABLE`.
- **Files modified:** `backend/src/dotmd/storage/surreal_inventory.py`
- **Verification:** `cd backend && uv run pytest tests/storage/test_surreal_storage_contract.py -x`
- **Committed in:** `5e5738a`

---

**Total deviations:** 2 auto-fixed (`Rule 1`: 2)
**Impact on plan:** Both fixes tightened evidence correctness without expanding scope. No extra features or dependency changes were introduced.

## Issues Encountered

- Direct host access to `/var/lib/docker/volumes/dotmd_dotmd-index/_data` was permission-blocked, so live evidence capture used container-internal copied snapshots and read-only exporter probes instead. This stayed within the plan’s read-only boundary.
- Snapshot queries against the copied `index.db` needed `sqlite_vec` loaded before opening vec0-backed tables. The probe was retried with the extension loaded and then succeeded.

## Known Stubs

- `backend/src/dotmd/storage/surreal_inventory.py` returns empty dict/list defaults for unavailable Falkor or feedback inventory reads. These are intentional unavailable-state sentinels, not missing wiring.

## User Setup Required

None - no external service configuration was added in this plan.

## Next Phase Readiness

- Ready for Plan 38-02 transform-only import work against the copied snapshot surfaces.
- The imported graph path should preserve `rel_type` and `weight` exactly as captured here.
- Graph property type evidence is sample-based per relation label, not an exhaustive full-edge payload scan.
- Feedback counts are validated, but any future row-level migration logic must continue to use supported exporter surfaces or an explicitly approved abstraction.

## Self-Check: PASSED

- Summary file exists on disk.
- All claimed task artifacts exist on disk.
- All three task commits are present in `git log --oneline --all`.
