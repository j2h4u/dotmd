---
status: complete
phase: 16-content-dedup-schema
source: [16-VERIFICATION.md]
started: 2026-04-25T00:00:00Z
updated: 2026-05-02T20:06:52+05:00
---

## Current Test

[testing complete]

The original human-only items were closed on 2026-05-02 as stale verification
debt. Phase 16 has already shipped to production; the one-time `dotmd migrate`
flow was removed after soak, and the current live schema/runtime are post-v16.

## Items

### UAT-1: Multi-holder CLI rendering

**What:** Run `dotmd search "<query>"` against a post-migration KB with at least one
collision group and confirm the printer renders `[N] path_0  (+1 more: path_1)` in
sorted-lex order.

**Why human:** Requires a live post-migration DB with real collision-group content.
Unit-testable in isolation but the rendering invariant under realistic content needs
a quick eyeball.

**Status:** skipped

**Reason:** Stale as an operator UAT gate. The migration has already run in
production, the live CLI renders post-v16 search results from `file_paths`, and
the multi-holder formatting is covered by `backend/tests/cli/test_search_output.py`.

### UAT-2: Production dry-run

**What:** Run `dotmd migrate run --dry-run` against the production `~/.dotmd/index.db`
(pre-migration). Verify divergence preview shows 0 groups (Decision #10 prediction).

**Expected:**
- `payload_divergence_groups=0`
- `would_abort_without_flag=false`
- Exit 0
- DB bytes unchanged (dry-run persists nothing)

**Why human:** Requires production DB access; non-destructive but still operator-gated.

**Status:** skipped

**Reason:** Stale. The one-time production migration has already completed, and
the `dotmd migrate` CLI was intentionally removed after soak in Phase 999.7.
Current `dotmd --help` has no `migrate` command.

### UAT-3: Production migration + status

**What:** When ready, stop trickle, run `dotmd migrate run`, then `dotmd migrate status`.
Confirm all strategies marked complete; `dotmd search` still works on the migrated DB.

**Expected:**
- `migrate status` per-strategy progress: complete
- `needs_migration_v16: False`
- `dotmd search` returns hits with `file_paths` list as expected

**Why human:** Irreversible production operation. Backup first; no automated rollback
beyond the migration_v16 backup it takes itself.

**Status:** skipped

**Reason:** Stale. ROADMAP records the production v16 migration as completed on
2026-04-25 with 486 collisions collapsed, 0 divergence, and no override. Current
live `dotmd status` reads the post-v16 database successfully.

## Summary

total: 3
passed: 0
issues: 0
pending: 0
skipped: 3

## Gaps

(None yet — gaps land here when UAT items fail or surface follow-up issues.)

## Closure Evidence

- `docker exec dotmd dotmd --help` on 2026-05-02: no `migrate` command remains.
- `docker exec dotmd dotmd status` on 2026-05-02: live index reports 826 files,
  19575 chunks, 44255 entities, 286367 edges, FalkorDB backend.
- `.planning/ROADMAP.md` Phase 999.7: Phase 16 shipped to production on
  2026-04-25; `dotmd migrate run` succeeded with 486 collisions collapsed,
  0 divergence, no override; migration_v16 code/CLI/tests removed on 2026-04-30.
- Current tests retain the live M2M guarantees:
  `backend/tests/cli/test_search_output.py`,
  `backend/tests/cli/test_status_output.py`, and M2M storage/pipeline tests.

## Notes

- ~~Code-level WARNING from verifier (not a UAT item, just a follow-up):
  `_index_file` residual — when a file is reindexed (content changed), old chunk's
  FTS/vec/graph entries are cleared via `delete_file_subgraph` even if another file
  still holds that chunk_id. The `chunks_*` row survives (INSERT OR IGNORE). A code
  comment marks this as known: "The M2M-aware cascade (P4) will refine this further."
  Track as future cleanup if it surfaces under real workloads.~~ — closed 2026-04-25
  in commits `3b19129` (extract primitive) + `71a5f80` (wire into `_index_file`).
  `_index_file` now uses `_holder_aware_chunk_cleanup` — shared chunks survive reindex.

- ~~DEDUP-10b xfail~~ — closed 2026-04-25 in commit `48354d6`. Refactored
  the parity test to patch `SemanticSearchEngine.encode` (the real seam)
  at class level. Test now PASSES; full suite has 0 xfails.
