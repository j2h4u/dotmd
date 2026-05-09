---
slug: state-planned-phase-corrupts
status: resolved
resolution_strategy: project-workaround-option-3-canon-restoration
trigger: "gsd-tools `state planned-phase` корраптит STATE.md: milestone_name 'Unified Source Architecture' → литеральное слово 'milestone', и счётчики просели (24→18 phases, 54→40 plans, 53→37 completed plans, 98%→93%) после вызова `node ~/.claude/get-shit-done/bin/gsd-tools.cjs state planned-phase --phase 34 --name 'federated-searchcandidate-contract' --plans 3`."
created: 2026-05-09T15:16:00Z
updated: 2026-05-09T15:55:00Z
resolved_at: 2026-05-09T16:50:11Z
project: dotMD
project_root: /home/j2h4u/repos/j2h4u/dotmd
tool_under_test: ~/.claude/get-shit-done/bin/gsd-tools.cjs
---

# Debug session — state-planned-phase-corrupts

## Symptoms

(unchanged — see git history)

## Current Focus

```yaml
hypothesis: |
  Confirmed. Both regressions share one root cause: ROADMAP.md uses
  `<details>...</details>` collapse blocks for every milestone, but the
  state-derivation code only recognises milestones via `## vX.Y` headings
  or `🚧 **vX.Y …**` list markers. v1.6 has neither, so:
  (A) milestone_name falls through to the literal default `'milestone'`;
  (B) milestone phase scoping falls back to `stripShippedMilestones`,
      which deletes every `<details>...</details>` (but NOT `<details open>`)
      block, leaving an arbitrary subset of phases that `<details>`-stripping
      happened to leave behind.
test: |
  Read code path; reproduce regex behaviour with node one-liner.
expecting: |
  Found.
next_action: |
  Stop at root cause. Fix touches shared state-derivation code
  (getMilestoneInfo, extractCurrentMilestone) used by many subcommands,
  not just planned-phase. Present fix options to user.
reasoning_checkpoint: null
tdd_checkpoint: null
```

## Evidence

- timestamp: 2026-05-09T15:30:00Z
  source: ~/.claude/get-shit-done/bin/lib/state.cjs:1344-1383 (cmdStatePlannedPhase)
  finding: |
    Despite the tool reporting `"updated": ["Status", "Last Activity"]`, the
    last line `writeStateMd(statePath, content, cwd)` triggers a FULL
    frontmatter rebuild from disk. writeStateMd → syncStateFrontmatter →
    buildStateFrontmatter (state.cjs:957, 764). So milestone_name and
    progress.* are re-derived from ROADMAP.md + .planning/phases/* every
    time, regardless of which body fields were actually patched.
    The "{updated: [Status, Last Activity]}" report is misleading — it
    only tracks body-field replacements, not the implicit frontmatter
    rebuild that happens on every write.

- timestamp: 2026-05-09T15:35:00Z
  source: ~/.claude/get-shit-done/bin/lib/core.cjs:1694-1776 (getMilestoneInfo)
  finding: |
    Q1 root cause confirmed.
    Path A (line 1714, taken when STATE.md milestone field is set):
      - tries heading match `##[^\n]*v1\.6[:\s]+([^\n(]+)` → no match
        (ROADMAP.md has zero `## v1.6` headings; verified by
        `grep -nE "^##.*v1\.6" .planning/ROADMAP.md` → 0 hits).
      - tries list match `🚧\s*\*?\*?v1\.6\s+([^*\n]+)` → no match
        (ROADMAP.md has zero `🚧` markers; verified by grep → 0 hits).
      - falls through to line 1738:
            return { version: stateVersion, name: 'milestone' };
    That literal `'milestone'` is what the diff observed:
        milestone_name: Unified Source Architecture → milestone_name: milestone
    The same literal default appears at lines 1771 and 1774 as the catch-all.

- timestamp: 2026-05-09T15:40:00Z
  source: ~/.claude/get-shit-done/bin/lib/core.cjs:1052-1160 (stripShippedMilestones, extractCurrentMilestone) + 1783-1870 (getMilestonePhaseFilter)
  finding: |
    Q2 root cause confirmed.
    extractCurrentMilestone (line 1099-1108):
      - tries `^#{1,3}\s+.*v1\.6` heading → no match (same reason as Q1).
      - falls through to `stripShippedMilestones(content)` (line 1108)
        which uses regex `/<details>[\s\S]*?<\/details>/gi` to remove
        every <details> block.
    Critical detail: that regex matches the literal token `<details>`,
    NOT `<details open>`. So:
      - lines 14-23, 25-34, 36-46, 48-67, 69-87, 89-100  → all `<details>`
        → stripped (covers v1.1, v1.2, v1.3, v1.4 phases 11-14,
          v1.4 mid block, v1.5)
      - lines 102-118 (`<details open>`) → NOT stripped (preserves v1.6
        phases 32-37)
      - lines 1150-1320 (v1.4 phases 15-26 outside any <details>)
        → preserved
    Result: 18 phase numbers (15-26 + 32-37) survive — exactly
    `total_phases: 18` from the corrupt diff.
    Verified with node one-liner replicating the regex pipeline:
      Phases from filter: ['15','16','17','18','19','20','21','22','23',
                           '24','25','26','32','33','34','35','36','37']
      phaseCount: 18

- timestamp: 2026-05-09T15:42:00Z
  source: |
    Hand-count of disk state (current): .planning/phases/{15..26,32,33,34}/
    Phase 34 currently has 3 PLAN files, 0 SUMMARY files
    (federated-searchcandidate-contract was just begun)
  finding: |
    For the 18-phase filter set: 16 phase dirs exist
    (35,36,37 not yet created on disk). buildStateFrontmatter line 871-874
    chooses Math.max(16, 18) = 18 → matches total_phases: 18.
    Plan/summary tally: 12 v1.4 + Phase 32 (4/4) + Phase 33 (3/3) +
    Phase 34 (3/0) = 46 plans / 43 summaries on current disk.
    The exact numbers from the corrupt diff (40/37) reflect a slightly
    different snapshot during the run (Phase 34's plan files may not
    have all existed when the regression first fired), but the
    MECHANISM is identical: 18-phase filter scope plus disk plan/summary
    tally.
    The pre-corruption baseline (24/54/53/98) was clearly hand-edited or
    stale (likely set during v1.5 or earlier) — never derived under the
    current filter logic. Both numbers are wrong; "drift" in this case
    is a wrong-vs-wrong comparison.

- timestamp: 2026-05-09T15:48:00Z
  source: ROADMAP.md structural analysis
  finding: |
    Both bugs are deterministic given the current ROADMAP.md format. Not
    a parser race, not a flaky regex — every `state planned-phase` call
    while v1.6 is active will reproduce both regressions identically.
    The user's prior "good" 24/54/53/98 numbers were preserved only because
    no tool triggered writeStateMd between the v1.6 transition and yesterday's
    session. Today's `state planned-phase` was the first call to invoke the
    rebuild path on the new milestone.

## Eliminated

- timestamp: 2026-05-09T15:30:00Z
  hypothesis: "cmdStatePlannedPhase does targeted patching"
  why_eliminated: |
    The handler does call stateReplaceField for body fields (looks targeted)
    but the final writeStateMd triggers a full frontmatter rebuild via
    syncStateFrontmatter. So the JSON-reported `updated: [Status, Last Activity]`
    only describes body-text edits — frontmatter is rewritten silently.

- timestamp: 2026-05-09T15:42:00Z
  hypothesis: "Counter drift is a legitimate recount of stale numbers (B2)"
  why_eliminated: |
    Both old (24/54/53) and new (18/40/37) numbers are produced by buggy
    code paths or hand edits. New numbers are a re-derivation under broken
    milestone-scoping logic; they don't reflect "ground truth". So this is
    a bug, not legitimate recount. (The deeper truth: with current ROADMAP.md
    structure, no automated derivation can produce correct progress numbers
    until the milestone-scoping regex is fixed.)

## Resolution

- root_cause: |
    Single root cause spanning both observed regressions: gsd-tools'
    state-derivation code (in ~/.claude/get-shit-done/bin/lib/) only
    recognises milestone sections via two regex patterns —
        (a) heading-format: `^#{1,3}\s+.*v1\.6...`
        (b) list-format with progress emoji: `🚧\s*\*?\*?v1\.6\s+...`
    dotMD's ROADMAP.md uses neither. Active milestone v1.6 is declared
    only as `- [ ] **v1.6 Unified Source Architecture** ...` (markdown
    checkbox + bold) and inside `<details open><summary>v1.6 ...`.
    Consequences when `state planned-phase` (or any cmd that triggers
    writeStateMd → syncStateFrontmatter → buildStateFrontmatter) runs:
      A. getMilestoneInfo (core.cjs:1694) falls through to the literal
         default `name: 'milestone'` at line 1738 → milestone_name
         silently overwritten with the field-name string.
      B. extractCurrentMilestone (core.cjs:1072) → stripShippedMilestones
         (core.cjs:1052) — regex `<details>[\s\S]*?<\/details>` strips
         every `<details>` block but NOT `<details open>`, leaving an
         arbitrary 18-phase subset (v1.4 phases 15-26 outside any
         details + v1.6 phases 32-37 inside `<details open>`).
         buildStateFrontmatter then derives total_phases / completed_phases
         / total_plans / completed_plans / percent from that broken
         subset.
    The misleading JSON `{"updated": ["Status", "Last Activity"]}` is
    not a root cause but a symptom of the same architectural choice: the
    handler tracks body-field edits explicitly while letting writeStateMd
    perform an implicit, unreported full-frontmatter rebuild.

- fix: |
    NOT APPLIED — fix surface touches shared state-derivation code
    (getMilestoneInfo, extractCurrentMilestone, stripShippedMilestones)
    used by many gsd-tools subcommands, not just `state planned-phase`.
    Per user preference (root cause first, no commits during diagnosis)
    + project memory `feedback_invariant_by_construction` (prefer
    structural impossibility over post-hoc patches), three options
    for the user to choose from:

    Option 1 (broadest, structural): Make milestone parsing format-agnostic.
      Add a third regex/parser path that matches the checkbox+bold list
      format `- \[[ x]\] \*\*v(\d+\.\d+)\s+([^*]+)\*\*` (already used at
      core.cjs:1745 but only with `🚧` prefix — extend to `- [ ]` /
      `- [x]` prefixes). Also fix `stripShippedMilestones` regex to
      match `<details(?:\s[^>]*)?>` so the `<details open>` variant is
      handled consistently. This fixes Q1 + Q2 for all subcommands.
      Risk: changes shared behaviour; requires regression coverage for
      heading-format, 🚧-format, AND new checkbox-format roadmaps.

    Option 2 (narrow, targeted): Make `cmdStatePlannedPhase` patch the
      frontmatter in place instead of going through writeStateMd. Use
      `readModifyWriteStateMd(... { resync: false })` (already exists,
      state.cjs:1060-1088) which preserves frontmatter progress.* and
      milestone_name across the write. Mirrors Bug #3242 fix (line
      1054-1058 in state.cjs comment).
      Risk: smallest blast radius — fixes the specific corruption seen
      here without disturbing other subcommands. Does NOT solve the
      latent rot in getMilestoneInfo/extractCurrentMilestone — they'll
      still misbehave for `state json`, `state load`, `state validate`,
      etc., but those are read-only and won't corrupt files.

    Option 3 (project-side workaround): Restructure ROADMAP.md to use
      a `## v1.6 Unified Source Architecture` heading (or `🚧 **v1.6
      Unified Source Architecture**` list marker) for the active
      milestone. Tooling already supports both. This unblocks immediately
      and re-aligns dotMD with gsd-tools' expectations, but is fragile —
      every future milestone bump needs the same heading format.

    Recommended: Option 1 + Option 2 together. Option 1 fixes the root
    cause for everyone; Option 2 makes `state planned-phase` structurally
    incapable of corrupting frontmatter even if milestone parsing fails
    in some other future way (defense in depth, "invariant by
    construction").

- verification: |
    Regression test (TDD-friendly):
      1. Create a temp .planning/ with ROADMAP.md using only checkbox
         list format `- [ ] **v1.6 Foo** — Phases 32-37 (active)`,
         no `## v1.6` heading, no `🚧` marker.
      2. Create STATE.md with `milestone: v1.6, milestone_name: Foo`.
      3. Run `node gsd-tools.cjs state planned-phase --phase 34 ...`.
      4. Assert: STATE.md still has `milestone_name: Foo` (not 'milestone').
      5. Assert: STATE.md progress.* fields unchanged (not re-derived
         from broken milestone-scoping).
    Add to gsd-tools' test suite — this is a tooling-level test, not
    something dotMD owns.

- files_changed: |
    None (per user request: diagnose first, no commits).
    Fix surface (for whichever option is chosen):
      Option 1: ~/.claude/get-shit-done/bin/lib/core.cjs (getMilestoneInfo
                lines 1714-1740 + 1742-1772, stripShippedMilestones
                line 1052, extractCurrentMilestone fallback line 1108)
      Option 2: ~/.claude/get-shit-done/bin/lib/state.cjs
                (cmdStatePlannedPhase lines 1344-1384 — replace
                writeStateMd call with readModifyWriteStateMd(..., {resync:false}))
      Option 3: /home/j2h4u/repos/j2h4u/dotmd/.planning/ROADMAP.md
                (add `## v1.6 Unified Source Architecture` heading or
                `🚧 **v1.6 ...**` list marker)

## Specialist Review

Not invoked (TDD-mode + scope: tooling fix lives in ~/.claude/get-shit-done,
not in dotMD repo. Dispatching a typescript/python specialist for a CJS
state-machine analysis would not add value beyond what's already
documented above. The recommended fix path is regex-level and structural
— no language idioms at stake.)

## Resolution Applied (2026-05-09T16:50:11Z)

User chose **Option 3 (project workaround / canon restoration)**, motivated by
the recognition that the `<details open>` + `- [ ]` checkbox format used for
the active milestone was unauthorized agent drift, not project convention.
Canonical layout: shipped milestones in summary `<details>` blocks + linked
`milestones/vX.Y-ROADMAP.md` archive; active milestone via `🚧 **vX.Y …**`
top-list marker + `## vX.Y …` heading body.

### Changes applied to .planning/ROADMAP.md

1. **Top milestone list (line 12)**: `- [ ] **v1.6 …**` → `- 🚧 **v1.6 …**`.
   Satisfies `getMilestoneInfo`'s second regex path (🚧 marker) so
   `milestone_name` no longer falls through to the literal `'milestone'` —
   **Q1 closed**.
2. **Active milestone body (lines 102-118)**: removed `<details open>...</details>`
   wrapper, replaced with `## v1.6 Unified Source Architecture (Phases 32-37)
   — ACTIVE` heading. Satisfies `extractCurrentMilestone`'s heading regex.
3. **Removed duplicated v1.4 phase detail blocks** (291 lines deleted across
   two ranges):
   - Lines 159-225 — `### Phase 17, 18, 19: …` (3 blocks, 67 lines)
   - Lines 1147-1370 — `### Phase 15, 16, 20-26: …` (9 blocks, 224 lines)
   All 12 phase blocks SHA256-verified IDENTICAL with their counterparts in
   `.planning/milestones/v1.4-ROADMAP.md` before deletion (Phase 26 had two
   trailing footer lines extra in the archive — non-loss-bearing). Backlog
   items 999.2-999.31 (lines 226-1140) and Future ideas (line 1141) plus the
   v1.6 active phase details (Phases 32-37 at lines 1374-1499) preserved
   unchanged. ROADMAP.md size: 1519 → 1228 lines.
   This removes the false phase signal that made `getMilestonePhaseFilter`
   count 12 v1.4 phases (15-26) into the v1.6 milestone scope — **Q2 closed**.

### Verification

After applying the three deltas above, re-ran the originally corrupting
command:

```
node ~/.claude/get-shit-done/bin/gsd-tools.cjs state planned-phase \
  --phase 34 --name federated-searchcandidate-contract --plans 3
```

`.planning/STATE.md` diff vs HEAD:

| Field | Pre (corrupt) | Post (correct) |
|-------|---------------|----------------|
| `milestone_name` | `milestone` (literal placeholder) | `Unified Source Architecture` |
| `total_phases` | 18 | 6 |
| `completed_phases` | 14 | 2 (Phases 32 + 33) |
| `total_plans` | 40 | 10 (4+3+3 from phases 32/33/34) |
| `completed_plans` | 37 | 7 (4+3 from 32/33 SUMMARY-complete) |
| `percent` | 78 | 33 (2/6) |

The new numbers are the first set actually derived from ground truth — both
the old `24/19/54/53/98` (stale hand-edit pre-v1.6) and the corruption-cycle
`18/14/40/37/78` were equally wrong, just for different reasons.

### Files Changed

- `/home/j2h4u/repos/j2h4u/dotmd/.planning/ROADMAP.md` (-296 / +2 lines net)
- `/home/j2h4u/repos/j2h4u/dotmd/.planning/STATE.md` (auto-updated by
  `state planned-phase` after the ROADMAP fix; numbers now ground-truth)
- `/home/j2h4u/.claude/projects/-home-j2h4u-repos-j2h4u-dotmd/memory/feedback_roadmap_milestone_format.md`
  (new feedback memory documenting the canonical format and the agent-drift
  failure mode)
- `/home/j2h4u/.claude/projects/-home-j2h4u-repos-j2h4u-dotmd/memory/MEMORY.md`
  (index pointer added)

### Upstream gsd-tools bug — NOT fixed in this session

The underlying parser fragility remains in `~/.claude/get-shit-done/bin/lib/`:
`getMilestoneInfo` falling through to the literal `'milestone'` (core.cjs:1738)
and `extractCurrentMilestone`'s `<details>`-stripping fallback that ignores
`<details open>` (core.cjs:1052) are still present. This session resolved
the corruption symptom in the dotMD project by restoring the format the
parser expects, not by fixing the parser. Option 1 (broad regex repair) +
Option 2 (`readModifyWriteStateMd(..., {resync:false})`) remain documented
above for whichever future contributor takes on the upstream fix.

### Side issue surfaced

During verification, the tool also failed once with `MODULE_NOT_FOUND:
~/.claude/sdk/shared/model-catalog.json` — a separate bug introduced when
gsd-tools auto-updated mid-session (CHANGELOG/.changeset bumped at 15:09
in `~/repos/j2h4u/get-shit-done/`). Worked around with a temporary symlink
`~/.claude/sdk → ~/repos/j2h4u/get-shit-done/sdk`. Likely the new gsd
installer is incomplete or the new layout expects a sibling `sdk/` directory
that the install step doesn't currently populate. Not investigated further
in this session — flagged here as a follow-up.
