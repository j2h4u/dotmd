---
quick_id: 260502-scv
status: planned
created: 2026-05-02
---

# Quick Task 260502-scv: Normalize dotMD .planning docs

## Objective

Separate active roadmap phases from backlog/done `999.x` items, reduce safe
GSD health/progress noise, and keep historical artifacts intact.

## Tasks

1. Normalize `ROADMAP.md`
   - Keep active completed phases visible.
   - Rename `### Phase 999.x` backlog headings so GSD analyzers do not treat
     backlog as the next active phase.
   - Preserve all backlog text in place under the backlog section.

2. Fix safe health/audit noise
   - Move completed `999.12` artifacts out of `.planning/phases/` while keeping
     the directory intact under notes.
   - Add missing summary status frontmatter for old quick tasks.
   - Add lightweight `VALIDATION.md` docs for phases where the validation work
     exists but no standalone validation artifact was written.

3. Verify
   - Run `gsd-sdk query validate.health`.
   - Run `gsd-sdk query roadmap.analyze`.
   - Run `gsd-sdk query audit-open --json`.
   - Run `gsd-sdk query audit-uat --raw`.
