---
status: partial
phase: 16-content-dedup-schema
source: [16-VERIFICATION.md]
started: 2026-04-25T00:00:00Z
updated: 2026-04-25T00:00:00Z
---

## Current Test

3 human-only verification items from verifier (see 16-VERIFICATION.md frontmatter).
Production migration is an operator-controlled, irreversible step — defer until ready.

## Items

### UAT-1: Multi-holder CLI rendering

**What:** Run `dotmd search "<query>"` against a post-migration KB with at least one
collision group and confirm the printer renders `[N] path_0  (+1 more: path_1)` in
sorted-lex order.

**Why human:** Requires a live post-migration DB with real collision-group content.
Unit-testable in isolation but the rendering invariant under realistic content needs
a quick eyeball.

**Status:** pending

### UAT-2: Production dry-run

**What:** Run `dotmd migrate run --dry-run` against the production `~/.dotmd/index.db`
(pre-migration). Verify divergence preview shows 0 groups (Decision #10 prediction).

**Expected:**
- `payload_divergence_groups=0`
- `would_abort_without_flag=false`
- Exit 0
- DB bytes unchanged (dry-run persists nothing)

**Why human:** Requires production DB access; non-destructive but still operator-gated.

**Status:** pending

### UAT-3: Production migration + status

**What:** When ready, stop trickle, run `dotmd migrate run`, then `dotmd migrate status`.
Confirm all strategies marked complete; `dotmd search` still works on the migrated DB.

**Expected:**
- `migrate status` per-strategy progress: complete
- `needs_migration_v16: False`
- `dotmd search` returns hits with `file_paths` list as expected

**Why human:** Irreversible production operation. Backup first; no automated rollback
beyond the migration_v16 backup it takes itself.

**Status:** pending

## Gaps

(None yet — gaps land here when UAT items fail or surface follow-up issues.)

## Notes

- Code-level WARNING from verifier (not a UAT item, just a follow-up):
  `_index_file` residual — when a file is reindexed (content changed), old chunk's
  FTS/vec/graph entries are cleared via `delete_file_subgraph` even if another file
  still holds that chunk_id. The `chunks_*` row survives (INSERT OR IGNORE). A code
  comment marks this as known: "The M2M-aware cascade (P4) will refine this further."
  Track as future cleanup if it surfaces under real workloads.

- ~~DEDUP-10b xfail~~ — closed 2026-04-25 in commit `48354d6`. Refactored
  the parity test to patch `SemanticSearchEngine.encode` (the real seam)
  at class level. Test now PASSES; full suite has 0 xfails.
