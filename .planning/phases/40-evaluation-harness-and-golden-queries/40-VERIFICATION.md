---
phase: 40-evaluation-harness-and-golden-queries
verified: 2026-06-13T09:49:07Z
status: passed
score: 5/5 must-haves verified
overrides_applied: 0
---

# Phase 40: Evaluation Harness And Golden Queries Verification Report

**Phase Goal:** Build the quality evaluation surface that decides whether SurrealDB search is good enough to cut over.
**Verified:** 2026-06-13T09:49:07Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
| --- | --- | --- | --- |
| 1 | SURR-EVAL-01: maintainers have a golden query corpus covering title-heavy, tag-heavy, body-heavy, semantic, graph/entity, hybrid, source-ref, and mixed RU/EN scenarios. | ✓ VERIFIED | `backend/devtools/surreal_golden_queries.jsonl` has 16 rows, two per category, all using `filesystem:/mnt/...` refs; `graph-entity` rows are `sq-009` and `sq-010`; mixed RU/EN rows are `sq-015` and `sq-016`; `backend/tests/search/test_surreal_eval.py::test_approved_corpus_file_covers_required_categories` enforces the coverage. |
| 2 | SURR-EVAL-02: maintainers can produce machine-readable old-vs-Surreal diff rows classified as improvement, harmless_reorder, regression, or unclear. | ✓ VERIFIED | `backend/src/dotmd/search/surreal_eval.py` defines typed loaders, `classify_difference()`, and JSONL-ready `SurrealEvalDiffRow.to_jsonable()`; `backend/devtools/surreal_eval_runner.py` writes sorted UTF-8 JSONL; focused tests cover all four classifications plus `matched_engines`, `rank_deltas`, lost/gained refs, and malformed input handling. |
| 3 | SURR-EVAL-03: unresolved regressions and unresolved unclear differences block the aggregate cutover gate unless explicitly accepted with `accepted_by` and `accepted_reason`, while raw classification and raw gate stay preserved. | ✓ VERIFIED | `summarize_diffs()` blocks unresolved `CutoverGate.BLOCK` and `CutoverGate.REQUIRES_ACCEPTANCE` rows, but `with_acceptance()` only adds acceptance metadata without mutating raw `classification` or `cutover_gate`; tests assert accepted regressions/unclear rows resolve aggregate blockers while preserving raw values. |
| 4 | The old SQLite/sqlite-vec/FTS5 + FalkorDB stack is baseline/evaluator evidence only, not a compatibility target. | ✓ VERIFIED | `docs/surrealdb-native-retrieval-contract.md` and `docs/surrealdb-evaluation-harness.md` both state the old stack is baseline/evaluator only; the runner consumes operator-supplied captured JSONL instead of implementing dual-runtime compatibility behavior. |
| 5 | Phase 40 introduces only the evaluation harness/corpus/reporting surface; it does not add real Surreal schema/import/retrieval, production shadow execution, reindex/reembed, runtime fallback, or compatibility mode. | ✓ VERIFIED | `backend/src/dotmd/search/surreal_eval.py` and `backend/devtools/surreal_eval_runner.py` are dependency-light JSONL tooling only; no `DotMDService`, Surreal client, TEI, indexing, shell execution, or fallback wiring appears in the implementation; docs repeat the same scope boundary. |

**Score:** 5/5 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
| --- | --- | --- | --- |
| `backend/src/dotmd/search/surreal_eval.py` | Typed golden-query, diff-classification, acceptance, and aggregate-gate logic | ✓ VERIFIED | Exists, substantive (541 lines), imports Phase 39 policy enums, validates JSONL, classifies diffs, and summarizes gates. |
| `backend/devtools/surreal_eval_runner.py` | CLI/devtool runner that compares captured old-stack and candidate result JSONL and writes JSONL plus Markdown reports | ✓ VERIFIED | Exists, substantive (219 lines), bootstraps imports for standalone execution, loads corpus/results/acceptances, writes deterministic outputs, returns exit codes. |
| `backend/devtools/surreal_golden_queries.jsonl` | Golden corpus with at least two reviewed rows for each required category | ✓ VERIFIED | Exists with 16 rows and complete category coverage. |
| `backend/devtools/surreal_golden_queries_review.md` | Human-readable corpus review ledger with category matrix and evidence ledger | ✓ VERIFIED | Exists and records category rationale plus ref/read evidence for every checked-in row. |
| `backend/tests/search/test_surreal_eval.py` | RED/GREEN tests for evaluator types, classification rules, and aggregate gate semantics | ✓ VERIFIED | Exists with 12 focused tests covering loaders, coverage, classifications, contains semantics, and acceptance gating. |
| `backend/tests/devtools/test_surreal_eval_runner.py` | RED/GREEN tests for JSONL loading, runner report writing, and CLI exit behavior | ✓ VERIFIED | Exists with 4 focused tests covering machine-readable output, unresolved blocker exit code, acceptance validation, and malformed acceptance JSON. |
| `docs/surrealdb-evaluation-harness.md` | Durable operator/developer documentation for Phase 40 harness usage and scope boundaries | ✓ VERIFIED | Exists and documents inputs, schema, classification, acceptance metadata, JSONL output, exit semantics, and non-goals. |

### Key Link Verification

| From | To | Via | Status | Details |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/search/surreal_eval.py` | `backend/src/dotmd/search/surreal_contract.py` | imports `AcceptedDifference`, `CutoverGate`, `RetrievalSurface`, and `default_surreal_retrieval_contract` | ✓ WIRED | Manual check: multiline import at lines 11-16; `default_surreal_retrieval_contract().cutover_gate_for(...)` used at lines 483-495. The helper query missed this because its regex expected a single-line import. |
| `backend/devtools/surreal_eval_runner.py` | `backend/src/dotmd/search/surreal_eval.py` | loads corpus/result rows, calls `classify_difference()` and `summarize_diffs()`, then writes reports | ✓ WIRED | Manual check: multiline import at lines 14-21; `run_eval()` calls `load_golden_queries()`, `load_eval_results()`, `classify_difference()`, and `summarize_diffs()` at lines 155-175. |
| `backend/tests/search/test_surreal_eval.py` | `backend/src/dotmd/search/surreal_eval.py` | behavior-first TDD coverage for SURR-EVAL-01, SURR-EVAL-02, and SURR-EVAL-03 | ✓ WIRED | Imports evaluator symbols at lines 10-18 and exercises loaders, classifier, and summary logic across 12 tests. |
| `backend/tests/devtools/test_surreal_eval_runner.py` | `backend/devtools/surreal_eval_runner.py` | tmp-path JSONL fixtures prove report shape without live old-stack or Surreal runtime wiring | ✓ WIRED | Imports `EvalRunnerConfig`, `main`, and `run_eval` at line 10 and exercises runner behavior across 4 tests. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/search/surreal_eval.py` | `classification`, `cutover_gate`, `lost_relevant_refs`, `gained_relevant_refs` | Parsed golden/result JSONL -> `_matched_approved_refs()` -> `classify_difference()` -> `default_surreal_retrieval_contract().cutover_gate_for()` | Yes | ✓ FLOWING |
| `backend/devtools/surreal_eval_runner.py` | `summary.rows`, `summary.passed`, output JSONL/Markdown | `load_golden_queries()` + `load_eval_results()` + `_load_acceptances()` -> `classify_difference()` -> `summarize_diffs()` -> `_write_jsonl()` / `_build_summary_markdown()` | Yes | ✓ FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
| --- | --- | --- | --- |
| Focused Phase 40 evaluator/runner suite passes | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -q` | `16 passed in 0.49s` | ✓ PASS |
| Focused Phase 40 suite passes through repo alias | `cd backend && just unit tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py` | `16 passed in 0.52s` | ✓ PASS |
| Prior Surreal regression suite still passes | `cd backend && uv run pytest tests/search/test_surreal_contract.py tests/search/test_surreal_retrieval_parity.py -q` | `15 passed in 0.28s` | ✓ PASS |
| The focused suite actually contains the claimed 16 tests | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py --collect-only -q` | `16 tests collected` | ✓ PASS |
| CLI entrypoint is runnable and exposes the documented interface | `cd backend && uv run python devtools/surreal_eval_runner.py --help` | Usage output includes `--golden-queries`, `--baseline-results`, `--candidate-results`, `--acceptance`, `--output-jsonl`, and `--summary-markdown` | ✓ PASS |

### Probe Execution

| Probe | Command | Result | Status |
| --- | --- | --- | --- |
| None documented for this phase | `find scripts -path '*/tests/probe-*.sh' -type f 2>/dev/null | sort` | No probe scripts found | ? SKIP |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
| --- | --- | --- | --- | --- |
| `SURR-EVAL-01` | `40-01-PLAN.md` | Golden query set covers title-heavy, tag-heavy, body-heavy, semantic, graph/entity, hybrid, source-ref, and mixed RU/EN queries. | ✓ SATISFIED | 16-row corpus, two-per-category coverage test, `graph-entity` enum-backed rows, and review ledger evidence for each ref. |
| `SURR-EVAL-02` | `40-01-PLAN.md` | Old-vs-Surreal diff reports classify changed results as improvement, harmless reorder, regression, or unclear. | ✓ SATISFIED | `classify_difference()` uses Phase 39 enums; runner writes machine-readable JSONL rows with `matched_engines`, `rank_deltas`, lost/gained refs, and rationale codes; tests assert the exact classes. |
| `SURR-EVAL-03` | `40-01-PLAN.md` | Regressions block cutover unless fixed or explicitly accepted as deliberate search semantics changes. | ✓ SATISFIED | `summarize_diffs()` blocks unresolved blockers/unclear rows, requires `accepted_by` and `accepted_reason`, and preserves raw classification/gate fields when accepted. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
| --- | --- | --- | --- | --- |
| `backend/src/dotmd/search/surreal_eval.py` | n/a | `ruff format --check` would reformat this phase file | ℹ️ Info | The phase goal is still achieved, but the 40-01 summary claim that repo-wide `just verify` fails only on unrelated pre-existing files is not confirmed by the current checkout. |

### Gaps Summary

No goal-blocking gaps found. Phase 40's evaluation harness, corpus, diff classification, acceptance gating, focused tests, prior regression compatibility, and durable docs are all present and working in the codebase. The only discrepancy found is documentary: `40-01-SUMMARY.md` says repo-wide `just verify` is red only for unrelated files, but the current formatter check also flags `src/dotmd/search/surreal_eval.py`.

---

_Verified: 2026-06-13T09:49:07Z_
_Verifier: the agent (gsd-verifier)_
