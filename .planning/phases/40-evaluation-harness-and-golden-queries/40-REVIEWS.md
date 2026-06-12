# Phase 40 Cross-AI Reviews

**Reviewed:** 2026-06-13
**Reviewer flags:** --opencode
**Cycle:** 1

## OpenCode Review

Let me examine the referenced source files to ground the review in actual code and existing patterns.
Now let me check the marker registration pattern and existing test styles:
---

## Phase 40 Plan Review

### Summary

Phase 40 builds the SurrealDB cutover evaluation surface: a golden-query corpus, a typed diff classifier, a devtool report runner, and TDD-gated tests. The plan is a single plan (40-01) with three tasks in one wave. It correctly gates on user-visible relevance via `AcceptedDifference` rather than exact rank parity, reuses the Phase 39 contract vocabulary, and defers live Surreal retrieval to Phase 42 and shadow execution to Phase 43.

### Strengths

1. **Phase boundary discipline is tight.** The objective, every task action, and the success criteria explicitly forbid real Surreal schema/import/retrieval, production shadow execution, reindexing, TEI reembedding, runtime fallback, and compatibility mode. The scope gate is enforced at every artifact.

2. **Reuse path is well-articulated.** The plan imports `AcceptedDifference`/`CutoverGate`/`RetrievalSurface` from `surreal_contract.py` (not string-literals), borrows callable-adapter patterns from `surreal_parity.py`, and follows the Phase 21 JSONL-label-plus-review-ledger pattern. No reinvention.

3. **TDD ordering is correct.** Task 1 writes RED tests that fail for missing `dotmd.search.surreal_eval` and missing corpus artifacts; Task 2 implements the module and runner; Task 3 adds the real corpus. This ensures no production code ships without tests and no corpus is accepted without schema validation.

4. **Threat model is focused and actionable.** T-40-01 through T-40-05 cover JSONL tampering, acceptance forgery, report-path safety, shell-injection avoidance, and DoS via malformed inputs. Each threat has a concrete mitigation that maps to a test assertion or implementation guard.

5. **Classification rules are deterministic and explained.** The four-class system (`improvement`/`harmless_reorder`/`regression`/`unclear`) has automatic triggers based on public `ref` presence/loss, readability, and engine attribution — no subjective heuristics.

6. **JSONL + separate review ledger** matches the project's established pattern from Phase 21 and keeps canonical scoring mechanically separate from human approval intent.

### Concerns

| # | Severity | Concern |
|---|----------|---------|
| C1 | **HIGH** | **Golden corpus labels may not reference indexable documents.** Task 3 instructs: "Prefer durable dotMD docs/planning refs such as `docs/surrealdb-native-retrieval-contract.md`, `.planning/REQUIREMENTS.md`..." These are project planning files under `/home/j2h4u/repos/`, not files under `/mnt/` that dotMD indexes. The `relevant.ref` field must be a `filesystem:` ref to a file actually in the current index (voicenotes, docs under `/mnt/`). If these docs aren't indexed, the corpus is unusable as evaluation input for any real run. |
| C2 | **MEDIUM** | **`contains` field creates an unresolved tension with T-40-03.** The golden query row includes `contains` text in `relevant` labels implying a content-match check. But T-40-03 mitigation says the runner should "avoid reading arbitrary content from label refs during report generation." If `contains` is never verified, it's dead data. If it is verified, T-40-03 needs an exception or the `contains` field should be replaced with something that doesn't require file reads. |
| C3 | **MEDIUM** | **"Graph/entity" category label is ambiguous for matching.** The golden query JSONL uses `graph-entity` (Task 3 wording says "using `graph-entity` as the JSONL-safe graph/entity category") but the requirement and scenario matrix use `graph/entity`. The code must define `GoldenQueryCategory` explicitly and the corpus, tests, and classification code must agree on a single string. Recommend defining the eight categories as a `StrEnum` in `surreal_eval.py` so there's one source of truth. |
| C4 | **MEDIUM** | **No conftest for shared eval test fixtures.** The test plan creates two test files in two directories (`tests/search/` and `tests/devtools/`). The `SurrealEvalDiffRow` and `EvalResult` test instances will appear in both. A `conftest.py` with shared `pytest.fixture` factories for canonical diff rows (improvement, regression, harmless_reorder, unclear) would reduce duplication and prevent the two test files from drifting in their fake-data shapes. The plan doesn't mention this. |
| C5 | **LOW** | **Minimum corpus size (16 rows, 2 per category) is a warm-start, not a gate-quality set.** Two queries per category is borderline for evaluating retrieval quality. However, the plan correctly treats this as a starting corpus that later phases can expand, and the harness itself works with any number of rows. Acceptable for Phase 40 scope. |
| C6 | **LOW** | **The `matched_engines` diff-row field is specified but no engine-attribution test in Task 1 behavior text.** The diff row schema includes `matched_engines` (keyed by ref, listing `["fts", "semantic", "graph"]`). The Task 1 behavior text doesn't explicitly list a test that `matched_engines` is present in the diff row. The report-shape test covers general row schema; this should be explicit to avoid silent omission. |

### Suggestions

1. **S1 (for C1):** In Task 3, replace "Prefer durable dotMD docs/planning refs" with: "Prefer refs to files under `/mnt/voicenotes/` or other `filesystem:/mnt/...` paths that exist in the current index. The `relevant.ref` must resolve to a file that `dotmd read` can retrieve." This keeps corpus labels grounded in actual indexed content.

2. **S2 (for C2):** Decide whether `contains` is checked or not. If checked: add a note to T-40-03 exception path. If not checked: rename `contains` to `description` or `rationale` to clarify it's human annotation only, and update the classification rules to not reference it as an automatic trigger.

3. **S3 (for C3):** Define `GoldenQueryCategory` as a `StrEnum` in `surreal_eval.py` with values `TITLE_HEAVY = "title-heavy"`, `TAG_HEAVY = "tag-heavy"`, `BODY_HEAVY = "body-heavy"`, `SEMANTIC = "semantic"`, `GRAPH_ENTITY = "graph-entity"`, `HYBRID = "hybrid"`, `SOURCE_REF = "source-ref"`, `MIXED_RU_EN = "mixed-ru-en"`. Then both corpus and tests use `GoldenQueryCategory.GRAPH_ENTITY.value`.

4. **S4 (for C4):** Add a `backend/tests/search/conftest.py` or `backend/tests/conftest.py` entry with `@pytest.fixture` factories for `canonical_improvement_diff_row`, `canonical_regression_diff_row`, etc. Both test files import from one place.

5. **S5 (for C6):** Add a bullet to Task 1's behavior text: "Test that diff rows include `matched_engines` keyed by ref with engine-name arrays when engine attribution data is available."

6. **S6:** The `surreal_eval_runner.py` acceptance-JSONL injection path is mentioned once ("an optional acceptance JSONL path") but not modeled in the runner behavior text. Add a sentence: "When an acceptance JSONL is provided, accepted rows list `accepted_by` and `accepted_reason` and do not contribute to unresolved-blocker count."

### Risk Assessment

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|-----------|
| Corpus labels reference non-indexed files, making Phase 43 unable to run the harness on real results | Medium | High — corpus is useless for the shadow run | Fix C1 (S1) now |
| `contains` vs. T-40-03 leads to either dead code or accidental file reads | Medium | Medium — either dead field or unexpected I/O | Resolve C2 (S2) before Task 3 |
| Category string mismatch between corpus, tests, and code | Low | Medium — tests that validate `category` fail spuriously | Apply S3 (enum) in Task 2 |
| Corpus too small for confident cutover decision | Low | Medium — Phase 43 may need corpus expansion | Acceptable for Phase 40; note in review ledger |
| Tests drift apart without shared fixtures | Low | Low — duplicated test setup only | Apply S4 optionally |
| `matched_engines` silently missing from diff rows | Low | Low — may be caught by schema tests, but fragile | Apply S5 |

### Verdict

**Approved with one blocking issue (C1) and one required resolution (C2).** The plan is well-structured, correctly scoped, and reuses existing vocabulary. Fix the golden-corpus ref guidance so labels point to actual indexed content, resolve the `contains`/T-40-03 tension, and the plan is ready to execute.


## Verification Coverage

Source-grounding authority: grep. The reviewer independently read the plan prompt, `backend/src/dotmd/search/surreal_contract.py`, `backend/src/dotmd/search/surreal_parity.py`, `.planning/REQUIREMENTS.md`, `backend/devtools/reranker_quality_bench.py`, `.planning/codebase/TESTING.md`, `40-RESEARCH.md`, and `backend/tests/search/test_surreal_contract.py`.

| Symbol / path | Verdict | Evidence |
|---------------|---------|----------|
| `AcceptedDifference` | VERIFIED | `backend/src/dotmd/search/surreal_contract.py` |
| `CutoverGate` | VERIFIED | `backend/src/dotmd/search/surreal_contract.py` |
| `RetrievalSurface` | VERIFIED | `backend/src/dotmd/search/surreal_contract.py` |
| `default_surreal_retrieval_contract` | VERIFIED | `backend/src/dotmd/search/surreal_contract.py` |
| `backend/src/dotmd/search/surreal_parity.py` | VERIFIED | existing Phase 38 helper file |
| `backend/devtools/reranker_quality_bench.py` | VERIFIED | existing devtool file |
| planned new symbols in `surreal_eval.py` | SKIPPED | new Phase 40 artifacts, not existing source |

## Cycle Summary

CYCLE_SUMMARY: current_high=1 current_actionable=5

## Current HIGH Concerns

- C1: Golden corpus label guidance may point to repo planning docs rather than actual indexed `filesystem:/mnt/...` refs, making the corpus unusable for real evaluation runs.

## Current Actionable Non-HIGH Concerns

- C2: Resolve whether `contains` is automatically checked or human annotation, without violating the no-arbitrary-file-read threat mitigation.
- C3: Make `graph-entity` the single enum-backed category string across code, corpus, and tests.
- C4: Consider shared fixtures if fake diff rows duplicate between test files, or explicitly keep duplication small.
- C6: Add explicit test coverage for `matched_engines` in diff rows.
- S6: Specify acceptance JSONL behavior in runner task text.


---

# Cycle 2 OpenCode Review

Let me verify the cited source files exist and understand the contract module.
# Phase 40 Plan Review — Cycle 2

## Verdict: APPROVED

All six Cycle 1 concerns (C1, C2, C3, C4, C6, S6) are resolved or adequately addressed in the revised PLAN.md. No new HIGH or actionable MEDIUM concerns remain outside the plan.

---

## Prior Concern Resolution

| Concern | Severity | Status | Evidence |
|---------|----------|--------|----------|
| **C1** — corpus labels reference non-indexed planning docs | HIGH | **RESOLVED** | Task 3 action now requires "actual indexed public `ref` anchors, preferably `filesystem:/mnt/...` refs" and explicitly forbids "fixed repo-local planning or source-file names as corpus labels unless those exact refs are present in the active index and read-resolvable". Success criteria reinforce: review ledger records read-resolvability in the active old-stack baseline. |
| **C2** — `contains` field tension with T-40-03 | MEDIUM | **RESOLVED** | Task 1 behavior: `contains` is checked "only against supplied captured result snippets or read-evidence fields when present; without supplied evidence they remain review metadata and do not trigger automatic classification." Task 2: "when no evidence is supplied, `contains` remains review metadata and is not an automatic classification trigger." No filesystem reads during report generation. |
| **C3** — `graph-entity` as single enum-backed category string | MEDIUM | **RESOLVED** | Task 2 defines `GoldenQueryCategory` enum with `GRAPH_ENTITY = "graph-entity"` as single source of truth. Task 1, Task 2, and Task 3 all reference `GoldenQueryCategory.GRAPH_ENTITY.value`. Source audit confirms. |
| **C4** — shared fixtures / conftest for test deduplication | MEDIUM | **ADDRESSED** | Task 1 permits a shared `conftest.py` "only if repeated helper setup across both test files makes the tests harder to read." Gives executor pragmatic discretion without over-specifying. |
| **C6** — `matched_engines` test coverage | LOW | **RESOLVED** | Task 1 report-shape behavior now explicitly includes "`matched_engines` keyed by public result ref with engine-name arrays" in the field checklist. |
| **S6** — acceptance JSONL behavior specification | LOW | **RESOLVED** | Task 1: "accepted rows require `accepted_by` and `accepted_reason`, preserve raw classification and raw gate, and do not count as unresolved blockers." Task 2: "the runner exits nonzero when unresolved blocking rows remain." |

---

## Plan Quality Assessment

**Strengths retained from Cycle 1:**
- TDD ordering (RED → GREEN → corpus) remains correct
- Phase boundary discipline enforced at every artifact — no Surreal implementation, no shadow execution, no reindexing, no TEI reembedding, no compatibility mode, no runtime fallback
- Reuses Phase 39 `AcceptedDifference`/`CutoverGate`/`RetrievalSurface` via import, not string literals
- Threat model covers JSONL tampering (T-40-01), acceptance forgery (T-40-02), path safety (T-40-03), shell injection (T-40-04), DoS (T-40-05)
- `surreal_contract.py` verified present with correct exports (`AccepedDifference`, `CutoverGate`, `RetrievalSurface`, `default_surreal_retrieval_contract`, `SurrealRetrievalContract.cutover_gate_for()`)

**Improvements in Cycle 2 plan:**
- `GoldenQueryCategory` enum now the single source of truth for all eight categories, eliminating the `graph/entity` vs `graph-entity` ambiguity
- `contains` semantics now fully defined as captured-evidence-only, closing the T-40-03 gap
- Corpus guidance inverted from "use planning docs" to "prefer indexed `/mnt/` refs" with explicit prohibition on hardcoding non-indexed paths
- All six prior concerns addressed in explicit `<review_feedback_addressed>` table for traceability

---

## New Observations (LOW, non-blocking)

| # | Severity | Observation |
|---|----------|-------------|
| N1 | LOW | Corpus creation (Task 3) requires a running dotMD instance to discover "actual indexed public refs" and verify read-resolvability. The plan does not explicitly state this dependency. The executor will discover it naturally. |
| N2 | LOW | `matched_engines` schema described at different granularity: PLAN.md says "keyed by public result ref with engine-name arrays"; RESEARCH.md nests under `baseline`/`candidate` keys. Both are consistent (PLAN describes the inner ref→engines structure, RESEARCH provides the outer grouping). The executor should reconcile against the authoritative Task 1 behavior text. |

---

## Threat Model Completeness

All five Phase 40 threats have concrete mitigations mapped to test assertions:

| Threat | Mitigation | Tested? |
|--------|-----------|---------|
| T-40-01 (JSONL tampering) | Strict field/enum/duplicate validation | Task 1 validate/load tests |
| T-40-02 (acceptance forgery) | Require `accepted_by` + `accepted_reason`, preserve raw gate | Task 1 acceptance behavior test |
| T-40-03 (path traversal reads) | No dereferencing label refs; `contains` only against supplied evidence | Task 1 scope boundary test |
| T-40-04 (shell injection) | No shell interpolation; runner consumes JSONL through Python | Task 1 scope boundary test |
| T-40-05 (DoS) | Stream JSONL row-by-row, fail fast with `ValueError` | Task 1 malformed-input tests |

---

## Summary

The revised Phase 40 plan correctly addresses all Cycle 1 blocking and actionable concerns. The scope boundary is enforced, the TDD flow is sound, the contract vocabulary is correctly reused from Phase 39, and the threat mitigations are comprehensive. Ready for execution.


## Cycle 2 Verification Coverage

Source-grounding authority: grep/OpenCode file reads. Reviewer re-read revised `40-01-PLAN.md`, `40-RESEARCH.md`, `40-REVIEWS.md`, `backend/src/dotmd/search/surreal_contract.py`, and `backend/src/dotmd/search/surreal_parity.py`. Planned new symbols in `surreal_eval.py` remain skipped as new artifacts.

CYCLE_SUMMARY: current_high=0 current_actionable=0

## Current HIGH Concerns
None.

## Current Actionable Non-HIGH Concerns
None.
