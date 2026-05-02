---
quick_id: 260502-scv
status: complete
date: 2026-05-02
---

# Quick Task 260502-scv: Normalize dotMD .planning docs

## What Changed

- Backlog `999.x` entries in `ROADMAP.md` were renamed from `### Phase 999.x`
  to `### Backlog 999.x`, so GSD roadmap/progress analyzers no longer treat
  backlog items as the next active phases.
- Completed backlog implementation `999.12` was moved intact from
  `.planning/phases/` to `.planning/notes/completed-backlog/`.
- Shipped v1.2/v1.3 phase artifacts `04` through `10` were moved intact from
  active `.planning/phases/` into `.planning/milestones/v1.2-phases/` and
  `.planning/milestones/v1.3-phases/`.
- Summary filenames for phases 12, 13, 20, 21, and 22 were normalized to match
  the plan/summary pairing expected by `gsd-health`.
- Lightweight `VALIDATION.md` markers were added for phases 16, 19, 21, and 22
  where validation had already happened but no standalone validation artifact
  existed.
- Old quick task summaries now include `status: complete` in frontmatter.
- `STATE.md` was updated to remove stale active-phase references and record the
  backlog/phase-archive split.

## Verification

- `gsd-sdk query validate.health` -> healthy, no warnings.
- `gsd-sdk query roadmap.analyze` -> 8 phases, 8 complete, no next phase.
- `gsd-sdk query progress.bar --raw` -> `26/26 plans (100%)`.
- `gsd-sdk query audit-uat --raw` -> zero UAT items.
- Legacy `gsd-tools.cjs audit-open --json` -> no UAT gaps, no verification
  gaps, no context questions; remaining items are old pending todos and one
  dormant seed.

## Notes

- `gsd-sdk query audit-open --json` still appears to use an older scanner in
  this environment; the legacy CJS scanner correctly recognizes completed
  quick summaries. This task records the legacy scanner output because the GSD
  workflow itself marks `audit-open` as CJS-only in several places.
