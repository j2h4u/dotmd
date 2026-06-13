---
phase: 40-evaluation-harness-and-golden-queries
plan: 01
subsystem: testing
tags: [surrealdb, evaluation, jsonl, golden-queries, retrieval]
requires:
  - phase: 39-surrealdb-native-retrieval-contract
    provides: "AcceptedDifference/CutoverGate policy vocabulary and cutover semantics"
provides:
  - "Typed golden-query evaluator and aggregate gate logic"
  - "File-driven JSONL diff runner with markdown summaries"
  - "Reviewed 16-row golden corpus grounded in filesystem:/mnt refs"
affects: [phase-41, phase-42, phase-43, surrealdb, search, migration]
tech-stack:
  added: []
  patterns:
    - "Golden query JSONL corpus with separate human review ledger"
    - "Acceptance metadata resolves aggregate gates without mutating raw diff classes"
    - "contains anchors use supplied evidence only and never trigger corpus-path dereferencing"
key-files:
  created:
    - backend/src/dotmd/search/surreal_eval.py
    - backend/devtools/surreal_eval_runner.py
    - backend/devtools/surreal_golden_queries.jsonl
    - backend/devtools/surreal_golden_queries_review.md
    - backend/tests/search/test_surreal_eval.py
    - backend/tests/devtools/test_surreal_eval_runner.py
    - docs/surrealdb-evaluation-harness.md
  modified: []
key-decisions:
  - "GoldenQueryCategory.GRAPH_ENTITY.value is the single serialized graph/entity category label."
  - "contains anchors are checked only against supplied snippets/read evidence and never by dereferencing corpus refs."
  - "Accepted regressions/unclear rows keep raw classification and raw cutover gate while dropping out of unresolved aggregate counts."
patterns-established:
  - "Phase 40 compares captured result JSONL files, not live retrieval implementations."
  - "Operator docs and corpus review stay alongside the harness so future shadow runs reuse the same evidence shape."
requirements-completed: [SURR-EVAL-01, SURR-EVAL-02, SURR-EVAL-03]
duration: 15 min
completed: 2026-06-13
status: complete
---

# Phase 40 Plan 01: Evaluation Harness and Golden Queries Summary

**Typed Surreal cutover evaluator with JSONL diff reports, explicit acceptance gating, and a reviewed 16-query filesystem-backed golden corpus**

## Performance

- **Duration:** 15 min
- **Started:** 2026-06-13T09:15:45Z
- **Completed:** 2026-06-13T09:30:25Z
- **Tasks:** 3 + post-review hardening fix
- **Files modified:** 7

## Accomplishments

- Added RED/GREEN coverage for golden corpus parsing, diff classification, acceptance semantics, JSONL report shape, strict JSONL validation, and runner exit behavior.
- Implemented `surreal_eval.py` and `surreal_eval_runner.py` as dependency-light Phase 40 evaluation surfaces that reuse Phase 39 policy enums instead of duplicating literals.
- Checked in a reviewed 16-row golden corpus plus durable operator docs, all grounded in actual `filesystem:/mnt/...` refs and captured read evidence.

## Task Commits

Each task was committed atomically:

1. **Task 1: Write RED evaluator and runner tests for SURR-EVAL-01 through SURR-EVAL-03** - `e872d78` (test)
2. **Task 2: Implement typed diff classification and report runner** - `8604573` (feat)
3. **Task 3: Add golden corpus, review ledger, and durable harness docs** - `51f3f6e` (docs)
4. **Code review fix: Harden input validation and diff reporting** - `8d53785` (fix)
5. **Format fix: Format the new evaluator module** - `7731129` (style)

## Files Created/Modified

- `backend/src/dotmd/search/surreal_eval.py` - typed golden query loader, diff classifier, acceptance handling, and aggregate summary
- `backend/devtools/surreal_eval_runner.py` - CLI/devtool runner for comparing captured baseline and candidate JSONL files
- `backend/devtools/surreal_golden_queries.jsonl` - 16-row reviewed corpus covering all required Phase 40 categories
- `backend/devtools/surreal_golden_queries_review.md` - category matrix and evidence ledger for every checked-in ref anchor
- `backend/tests/search/test_surreal_eval.py` - evaluator RED/GREEN tests including corpus coverage and acceptance semantics
- `backend/tests/devtools/test_surreal_eval_runner.py` - runner JSONL/markdown/exit-code tests
- `docs/surrealdb-evaluation-harness.md` - durable operator documentation for inputs, outputs, schema, and scope boundaries

## Decisions Made

- `graph-entity` is serialized only through `GoldenQueryCategory.GRAPH_ENTITY.value`, keeping code/tests/corpus on one source of truth.
- Corpus `contains` strings are human/captured-evidence anchors only; the runner never reads arbitrary filesystem paths from label refs during report generation.
- Acceptance metadata (`accepted_by`, `accepted_reason`) resolves aggregate blockers without rewriting the raw `AcceptedDifference` or `CutoverGate` on the affected row.
- Malformed collection fields and acceptance JSON now fail with line-numbered `ValueError`; dropped `maybe` refs no longer appear in `lost_relevant_refs`.

## Deviations from Plan

None - plan executed exactly as written.

---

**Total deviations:** 0 auto-fixed.
**Impact on plan:** No scope change.

## Issues Encountered

- Live baseline search probes emitted Gmail federated 400 warnings from an expired/invalid OAuth refresh flow, but the local `filesystem:/mnt/...` evidence needed for Phase 40 remained available and was used for the checked-in corpus.
- Phase code review initially found three loader/diff-reporting issues. They were fixed in `8d53785`, and `40-REVIEW.md` was refreshed to `status: clean` in `c47dad1`.
- `just verify` initially flagged the new `surreal_eval.py` for formatting; `7731129` fixed that. Optional `just verify` is still red only because unrelated pre-existing files outside this plan fail repo-wide `ruff format --check`. The remaining failures are in `src/dotmd/ingestion/migrate_surreal.py`, `src/dotmd/search/surreal_parity.py`, `src/dotmd/storage/surreal.py`, `src/dotmd/storage/surreal_inventory.py`, `src/dotmd/storage/surreal_ops.py`, `tests/ingestion/test_surreal_transform_only_migration.py`, `tests/search/test_surreal_retrieval_parity.py`, and `tests/storage/test_surreal_storage_contract.py`.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 41 can now keep its migration work measured against a concrete evaluation harness instead of ad hoc parity checks.
- Phase 42 can emit captured candidate JSONL rows in the schema documented here without inventing a second difference vocabulary.
- Phase 43 can layer acceptance ledgers and production-derived runs on top of the checked-in corpus without changing Phase 40’s raw diff semantics.

## Self-Check: PASSED

- Summary file exists on disk.
- All claimed task artifacts exist on disk.
- Task commits `e872d78`, `8604573`, `51f3f6e`, post-review fix `8d53785`, and format fix `7731129` are present in git history.
- `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -x` passed (`16 passed` after post-review hardening).
- `cd backend && just unit tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py` passed (`16 passed` after post-review hardening).
- `cd backend && uv run pytest tests/search/test_surreal_contract.py tests/search/test_surreal_retrieval_parity.py -q` passed (`15 passed`) as the prior-phase Surreal regression gate.
- Optional `cd backend && just verify` remains red only on unrelated pre-existing formatting debt outside this plan’s scope.

---
*Phase: 40-evaluation-harness-and-golden-queries*
*Completed: 2026-06-13*
