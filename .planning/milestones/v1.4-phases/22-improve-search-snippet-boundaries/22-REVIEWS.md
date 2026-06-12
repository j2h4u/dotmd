---
phase: 22
reviewers: [claude, opencode]
reviewed_at: 2026-05-02T13:16:57.361503Z
plans_reviewed: [22-01-snippet-boundary-extraction-PLAN.md]
---

# Cross-AI Plan Review — Phase 22

## Claude Review

## Plan Review: 22-01-snippet-boundary-extraction

---

### Summary

This is a tightly scoped, well-structured plan for a pure text-processing change. The threat model is explicit and covers every boundary the context established. The TDD ordering (RED tests first in Task 1, GREEN implementation in Task 2, live gate in Task 3) is appropriate for this kind of behavioral contract. The plan will achieve all three requirements if executed faithfully. No significant gaps that would cause a failed phase — a few sharpening opportunities below.

---

### Strengths

- **Scope discipline is strong.** Only `fusion.py` and `test_fusion.py` are modified. The threat model actively names what must *not* happen (neighboring chunks, `context_window`, speaker anchors, MCP schema changes) and ties each to a severity — this is better than most plans at this stage.
- **Preserves existing scoring.** Boundary expansion wraps the existing relevance-window selection, not replaces it. Retrieval and reranking are untouched by construction.
- **Hard cap prevents unbounded output.** `2 * snippet_length` is a reasonable default and the `+6` for ellipses is accounted for in the acceptance criterion.
- **Acceptance criteria are machine-checkable.** Each task's criteria are string-grep-able or command-exit-code-verifiable — no "looks good" criteria anywhere.
- **Live gate is correctly specified.** `--force-recreate` is the right Docker command for a bind-mounted source change; restart would silently keep the old Python bytecode.
- **D-11 on match marking** — flagging it as optional rather than deferred-but-committed prevents scope creep mid-execution.

---

### Concerns

**MEDIUM — Naive period detection will misfire on version strings and abbreviations.**
The boundary heuristics use `.` as a sentence boundary. The corpus is bilingual voicenotes transcripts plus docs, which will contain things like `v1.2`, `Fig. 3`, `e.g.`, `т.е.` (Russian abbreviation). A period in these positions will be treated as a sentence end and produce a left expansion that starts mid-phrase. This is acceptable for Phase 22 per D-05, but the plan should explicitly note it so the executor doesn't feel compelled to "fix" it and drift into NLP.

**MEDIUM — The expansion-fits-within-cap case has no test.**
Task 1 specifies five test cases: mid-sentence expansion, blank-line boundary, long-sentence hard cap, empty-query fallback, and short-chunk passthrough. Missing: a case where the sentence boundary expansion *succeeds* (fits within `2 * length`) and produces a snippet *longer than `length`* but shorter than the cap. This is the happy path — expansion works, no fallback needed — and it should be pinned with an exact expected string to prevent regressions.

**MEDIUM — Left-boundary walk-back behavior when `best_start` is already at sentence start.**
If `best_start` happens to land exactly after a `.` (already at a sentence start), the left walk-back should be a no-op and the snippet should not prepend `...`. The plan doesn't have an acceptance criterion or test case for this. Without it, an off-by-one in the walk-back logic (e.g., walking back one extra character into the previous sentence's terminator) could add a leading `...` incorrectly.

**LOW — `_truncate()` unconditionally appends `...` even when text fits.**
`_truncate(text, length)` always returns `truncated + "..."` (line 86). If the hard-cap fallback delegates to `_truncate()` from inside `_extract_best_snippet()`, the returned string will always have a trailing `...` even when the trimmed window ends at the chunk boundary. This is a pre-existing behavior quirk; Phase 22 should either preserve it (easiest) or fix it (clean), but the plan doesn't call it out, so the executor may not notice.

**LOW — Task 1 doesn't lint the new tests.**
Task 1 only runs `pytest` (intentionally, since tests are RED). It doesn't run `ruff` or `pyright` on the test file. A type error in a test fixture won't be caught until Task 2. Low friction to add `ruff check tests/test_fusion.py` to Task 1's verify block.

**LOW — `word_starts` pre-existing bug is invisible to this plan.**
`text.index(w, char_pos)` in the current implementation finds the first match for the word *string* from `char_pos`. For repeated tokens (e.g., `"the the"`) this works because `char_pos` advances. But for identical adjacent words where the first occurrence is in the match window, the index can point to the wrong instance if `text.index()` finds a substring rather than a full word. This is pre-existing and Phase 22 doesn't need to fix it — worth noting in the summary so it's not blamed on the new code.

---

### Suggestions

1. **Add an explicit "expansion succeeds" test case** to Task 1: a 3-sentence chunk where the match is in sentence 2, expansion includes sentences 1+2, total length is between `length` and `2 * length`, and the returned snippet starts at the exact character after the period ending sentence 1. Pin the expected string.

2. **Add a note to Task 1** that `.` boundary detection is intentionally naive (abbreviations/version strings accepted as false boundaries per D-05). This prevents the executor from over-engineering.

3. **Add `ruff check tests/test_fusion.py`** to Task 1's verify block so lint errors surface before Task 2.

4. **Task 2 acceptance criterion: `_truncate()` handling.** Add one line: "When the hard-cap fallback is used, `_truncate()` behavior for the trailing `...` is preserved unchanged." This pins the decision either way.

5. **Task 3 integration test condition**: The "if unit coverage does not already prove..." phrasing is fine, but consider making the bar explicit: "Skip the `build_search_results()` integration test if the unit tests for `_extract_best_snippet()` include the happy-path expansion case (concern above)."

---

### Risk Assessment: **LOW**

The change is fully contained to one helper function, the threat model explicitly forbids the most dangerous drift vectors (neighboring chunks, MCP schema), and the live gate is concretely specified. The missing "expansion succeeds" test case is the most likely source of a regression — without it, a future change could silently revert to word-only trimming and pass all the other tests. Adding it in Task 1 closes the loop.

---

## OpenCode Review

Let me examine the current implementation to ground my review.
Now I have full context. Here's my review:

---

## Plan Review: 22-01-snippet-boundary-extraction-PLAN.md

### Summary

A well-scoped, tightly bounded plan that addresses the specific problem (mid-sentence snippet truncation) with a deterministic, bounded solution. The TDD structure (RED → GREEN → VERIFY) is sound, the phase boundary is clearly enforced with negative constraints, and the implementation surface is exactly one function in one module. The plan correctly identifies that the current `_extract_best_snippet` already does the hard part (finding the best relevance window) and only needs post-selection boundary adjustment.

### Strengths

- **Excellent scope control.** The plan explicitly forbids neighboring chunks, `context_window`, speaker-turn anchors, ML/NLP, and MCP schema changes — with HIGH-severity threats in the threat model guarding each boundary. This is exactly right for a phase that's fundamentally "fix a text-processing bug."
- **Correct algorithmic approach.** Preserving existing best-window scoring, then expanding around it, avoids the risk of changing retrieval relevance. The expand-then-cap strategy is the simplest correct fix.
- **Hard cap with `2 * length + 6` allowance for ellipses.** The plan accounts for the fact that `...` markers inflate the returned string length, which is a detail many plans would miss.
- **Test-first structure.** Five specific test cases cover the critical behaviors (mid-sentence fix, paragraph boundary, long-sentence cap, empty query fallback, short text passthrough).
- **Threat model is substantive.** Each threat maps to a real risk with a concrete mitigation, not generic boilerplate.
- **Verification through MCP surface.** Task 3 correctly doesn't stop at unit tests — it verifies through `_format_result()` and the live MCP endpoint, accounting for the frontmatter/timestamp stripping that happens after snippet extraction.

### Concerns

- **MEDIUM — Ellipsis accounting interacts with `_format_result()`.** The plan sets the hard cap at `2 * snippet_length` and tests for `len(snippet) <= 2 * length + 6`. But `_format_result()` at `mcp_server.py:749` runs `re.sub(_FRONTMATTER_RE, ...)` and `.strip()` on the snippet *after* `_extract_best_snippet()` has already added `...` markers. If frontmatter stripping removes content from the middle of the boundary-expanded snippet, the visible output could look odd (mid-sentence with no ellipsis indicator). The research notes this risk (line "MCP visible snippet differs from unit-tested snippet") but the plan doesn't include a test for this interaction.

- **MEDIUM — Sentence boundary detection is naive for Russian text.** The codebase serves bilingual RU/EN content (~13,500 markdown files, RU voicenotes). Russian uses the same sentence-ending punctuation (`.`, `?`, `!`), but Russian abbreviations like initials ("А. Б. Иванов"), ordinal markers, and decimal numbers will create false sentence boundaries. The plan correctly avoids NLP, but doesn't acknowledge this tradeoff in tests or the hard-cap logic.

- **LOW — `_format_result()` also strips `[HH:MM:SS]` timestamps.** For voicenote transcripts, this stripping happens *after* boundary expansion. If a sentence boundary was placed right after a `[00:15:32]` marker, the visible snippet could start with a space or look slightly off. Minor cosmetic risk, but worth a test case.

- **LOW — `text.index(w, char_pos)` in the existing window-scoring loop (line 46) is O(n²) for chunks with many repeated words.** The plan doesn't touch this loop, which is correct (scope), but the window scoring could become a bottleneck if boundary expansion causes `_extract_best_snippet` to be called on much longer effective strings. Not a real concern at current corpus size (532 chunks).

- **LOW — Task 1 test assertion `len(snippet) <= 2 * length + 6` allows 306 chars on default `length=300`.** This is generous enough to be correct, but the exact constant `+6` (two `...` markers = 6 chars) assumes ellipses are always `...` (3 chars each). If implementation uses `…` (single char) or `… ` the constant changes. Minor — the implementation will define this.

- **LOW — No test for multi-paragraph chunks where the best window spans a paragraph boundary.** The plan tests "don't cross blank line" but doesn't test "what if the query match is in the last sentence before a blank line — does expansion correctly stop at the blank line?"

### Suggestions

1. **Add one test case for RU text with initials/abbreviations.** Something like `"Иванов А. Б. сказал что проект готов. Нужно проверить."` with query `"проект"` — verify the snippet doesn't split at "А." or "Б.". This would document the known limitation and prevent regressions.

2. **Add one test for the `_format_result()` interaction.** A minimal test in `test_fusion.py` or alongside the MCP tests that passes a snippet containing frontmatter through `_format_result()` and verifies the output still has coherent boundaries. This addresses the MEDIUM concern above.

3. **Clarify the boundary expansion for the case where `best_start` is already at a sentence boundary.** The plan says "expand left to nearest boundary" but doesn't explicitly say "if already at a boundary, don't move." This is probably obvious to the implementer, but a one-liner in the task description would prevent unnecessary searching.

4. **Consider making the hard-cap multiplier configurable later (not now).** The plan hardcodes `2 * snippet_length`. This is fine for Phase 22, but if agents consistently get snippets that feel too short after boundary capping, the multiplier may need tuning. Mention in the SUMMARY that this is a tunable constant.

5. **Task 3 should explicitly verify `tools/list` schema is unchanged.** The plan mentions this in the verification section but not in Task 3's acceptance criteria. Add "Confirm `tools/list` returns `search` with unchanged parameter schema" to the acceptance criteria for completeness.

### Risk Assessment

**LOW**

This is a textbook scoped bugfix. The change touches one private function in one module, preserves the existing function signature, doesn't affect scoring or retrieval, has a hard cap to prevent unbounded output, and is covered by targeted unit tests plus live MCP verification. The main residual risk is cosmetic (Russian abbreviations, frontmatter/timestamp stripping interactions), none of which would cause functional breakage. The plan's negative constraints (no schema changes, no neighboring chunks, no ML) are well-guarded and testable.

---

## Consensus Summary

Both reviewers rated the plan as low risk and correctly scoped. They agreed that the implementation surface is narrow, that preserving the current best-window scoring before sentence-boundary expansion is the right approach, and that the negative constraints around neighboring chunks, MCP schema changes, speaker-turn parsing, and ML/NLP expansion are important and well captured.

### Agreed Strengths

- Strong scope control: one private snippet helper plus focused tests, with explicit exclusions for neighboring chunks, `context_window`, speaker-turn anchors, and ML/NLP.
- Correct algorithm shape: keep the existing relevance-window selection, then expand the chosen window to local sentence boundaries, then enforce the hard cap.
- Test-first execution is appropriate for a deterministic text-processing behavior.
- Live verification through the MCP surface is necessary and already included in the plan.

### Agreed Concerns

- **MEDIUM:** The plan should pin the happy path where boundary expansion succeeds, returns text longer than `snippet_length`, and remains below the `2 * snippet_length` cap. Without this, a regression could keep word-window trimming behavior while still passing other tests.
- **MEDIUM:** Naive `.` sentence-boundary detection will misfire on abbreviations, initials, versions, and decimals in Russian and English text. This is acceptable under Phase 22's minimal deterministic scope, but the plan should document it explicitly so implementation does not drift into NLP.
- **LOW/MEDIUM:** The MCP-visible formatting path can change snippets after extraction by stripping frontmatter and timestamps. Task 3 should explicitly verify the visible MCP output and unchanged `tools/list` search schema.
- **LOW:** Boundary off-by-one cases deserve coverage: when the selected best window already starts at a sentence boundary, expansion should not incorrectly prepend previous-sentence punctuation or add misleading ellipses.

### Divergent Views

- Claude recommended preserving the current `_truncate()` trailing ellipsis behavior explicitly. OpenCode focused more on `_format_result()` stripping and visible MCP output. These are compatible: the revised plan should pin internal hard-cap behavior and separately verify the post-format MCP display.
- OpenCode suggested an abbreviation/initials test. Claude framed abbreviation handling as a known limitation to document rather than fix. The safer Phase 22 interpretation is to document the limitation and avoid implementing language-specific abbreviation logic unless a simple regression test can be written without expanding scope.

### Planner Follow-Up

Revise the Phase 22 plan before execution to add:

1. A happy-path expansion test where the returned snippet is longer than `snippet_length` but below the hard cap.
2. A boundary-start/off-by-one test or acceptance criterion.
3. An explicit note that naive punctuation boundaries are intentional and known to have abbreviation/version false positives.
4. Task 3 acceptance criteria for MCP-visible snippet coherence and unchanged `tools/list` search schema.
5. A clear decision on preserving existing `_truncate()` ellipsis behavior in the hard-cap fallback.
