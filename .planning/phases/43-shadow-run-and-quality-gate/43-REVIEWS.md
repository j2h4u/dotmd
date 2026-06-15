---
phase: 43
cycle: 6
reviewers: [codex, opencode]
reviewed_at: 2026-06-15T14:20:00+05:00
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commit: cf1ec2c
note: "Cycle 6 re-reviews the CURRENT plans after commit cf1ec2c, which incorporated all 4 cycle-5 actionable MEDIUMs (sentinel→run_eval temp-file wiring D43-02-F; vec-table-name derivation D43-02-J; GRAPH.COPY stale-destination idempotency D43-02-L step 2; --verify-only query_id-keyed canonical diff D43-03-C). The Option A isolated-graph architecture (D43-02-L) is settled and was NOT re-litigated. Resolved concerns from cycles 1-5 already incorporated into PLAN.md decisions (D43-*) are NOT re-counted. The executing reviewer runs inside Claude Code, so the `claude` CLI is skipped for independence; codex and opencode are the external reviewers."
---

# Cross-AI Plan Review — Phase 43 (Cycle 6)

The plans were revised in commit `cf1ec2c` to pin all four cycle-5 actionable MEDIUMs as concrete,
source-grounded, test-named mechanisms. This cycle re-reviews the CURRENT state, confirms each of
the four pins is properly CLOSED against live source, and surfaces only genuinely new, unresolved
concerns. The settled Option A isolated-graph architecture (D43-02-L) was not re-litigated.

Both external reviewers (codex, opencode) independently re-traced the cited symbols against live
dotMD source and **independently concluded: 0 unresolved HIGH, all four cycle-5 MEDIUMs CLOSED.**

## Codex Review

**Verdict: Cycle 6 is positive — all four cycle-5 MEDIUM pins are CLOSED in the current plan text,
each linked to explicit behavior + named tests + source-grounded logic. 0 HIGH.**

**Pin-closure (all four CLOSED):**
- D43-02-F sentinel→`run_eval` temp acceptance wiring — concrete (`load_shadow_acceptance_ledger`,
  temp acceptance path, `EvalRunnerConfig.acceptance`), source-grounded (`surreal_eval_runner.py`
  line behavior), testable (named tests pinned). No real gap.
- D43-02-J vector-table-name derivation — concrete (`_model_to_table_suffix`,
  `vec_chunks_{strategy}{suffix}`), source-grounded (pipeline reference), testable via explicit
  table-name test. No real gap.
- D43-02-L stale-destination idempotency — concrete (`list_graphs()` + pre-delete +
  production-name guard + `copy`), source-grounded (falkordb client behavior),
  testable (`test_copy_baseline_graph_deletes_stale_destination_before_copy`). No real gap.
- D43-03-C `--verify-only` canonical compare — concrete (`query_id`-keyed dict compare),
  source-grounded, testable (`test_verify_only_regenerates_and_compares_shadow_diffs`). No real gap.

**Strengths.**
- Both `43-01-PLAN.md` and `43-02-PLAN.md` make the 4 medium pins first-class with direct test names
  and source-grounded logic.
- Full-corpus coverage under Option A is preserved and asymmetric-coverage regressions are explicitly
  rejected across `43-02`/`43-03`.
- `--verify-only` is now a canonical `query_id` comparison — materially stronger than byte/row-wise.

**Concerns.**
- **LOW / NEW — Stale "graph-exclusion marker (D43-02-G)" wording drift.** Despite Option A removing
  graph-category exclusion (D43-02-G is SUPERSEDED by D43-02-L), a few narrative spots still reference
  a "graph-exclusion marker": `43-02-PLAN.md:120` (D43-02-K block says the produced `source-capture.json`
  "adds ... the graph-exclusion marker (D43-02-G)") and `43-03-PLAN.md:157` ("echoing the expected
  identity plus ... the graph-exclusion marker per D43-03-E"). These contradict the dominant,
  repeated, test-pinned Option A text ("NO graph-exclusion marker"; the Task 1 verify at
  `43-03-PLAN.md:184` asserts `'graph_engines_disabled' not in cap`). Also `load_source_capture_manifest`
  remains listed as an export (`43-02:37`) and a function contract (`43-02:237`) even though D43-02-K
  split this into `load_expected_source_manifest` (input) + produced `source-capture.json`. Non-blocking
  documentation consistency, but could mislead an implementer into encoding the wrong marker semantics
  or a now-orphaned loader.
- **MEDIUM / NEW (EXCLUDED from actionable count — phase-produced artifacts).** Referenced
  implementation/test/summary files (`surreal_shadow_metrics.py`, `surreal_shadow_runner.py`, the test
  modules, `43-0x-SUMMARY.md`) are not present in the tree. These are artifacts THIS PHASE PRODUCES
  (declared under the plans' produced-artifacts lists), so per the counting rules this is the expected
  pre-execution state of a plan review, not a plan-text defect. Not counted as actionable.

**Risk Assessment — MEDIUM** (codex's rating reflects the not-yet-executed state; the plan text itself
is sound). 0 unresolved HIGH; 2 non-HIGH actionables in codex's framing, of which the "missing runtime
files" item is excluded as a phase-produced-artifact non-defect.

---

## OpenCode Review

**Verdict: All four cycle-5 MEDIUMs are properly CLOSED. Zero new HIGH. One new LOW pre-existing
documentation imprecision.** Each cited file:line (`surreal_eval_runner.py:159`, `pipeline.py:139/222`,
`graph.py:149-161`) was confirmed against live source.

**Pin-closure table (all four PASS):**

| # | Cycle-5 MEDIUM | Mechanism pinned? | Source-grounded? | Test named? | Closed? |
|---|---------------|-------------------|------------------|-------------|---------|
| 1 | Sentinel→run_eval wiring | ✅ temp file; `EvalRunnerConfig.acceptance`=stripped path; raw path never assigned | ✅ `surreal_eval_runner.py:159` | ✅ `test_run_eval_receives_stripped_acceptance_path_not_raw_sentinel_file` | CLOSED |
| 2 | Vec-table-name derivation | ✅ import `_model_to_table_suffix`; `vec_chunks_{strategy}{suffix}` | ✅ `pipeline.py:139,222` | ✅ `test_rehearsal_identity_vec_table_name_matches_pipeline_convention` | CLOSED |
| 3 | GRAPH.COPY stale-destination idempotency | ✅ guard → `list_graphs()` → conditional `GRAPH.DELETE` of isolate → `GRAPH.COPY` | ✅ `graph.py:149-161` | ✅ `test_copy_baseline_graph_deletes_stale_destination_before_copy`, `..._refuses_production_destination` | CLOSED |
| 4 | --verify-only query_id canonical diff | ✅ dicts keyed by `query_id`; reordered passes, hand-edit fails | ✅ `run_eval()` + JSONL schema | ✅ `test_verify_only_regenerates_and_compares_shadow_diffs` (dual-assertion) | CLOSED |

**Strengths.**
- All four pins are source-grounded and independently verifiable against the exact cited lines.
- The temp-file sentinel wiring is precise about who strips, where the temp goes, and which raw path
  is NEVER assigned to `EvalRunnerConfig.acceptance`.
- The GRAPH.COPY stale-destination sequence is correctly ordered, with the production-name guard
  wrapping the pre-delete so cleanup can never touch `"dotmd"`.
- The `query_id`-keyed canonical comparison handles the subtle serializer/row-order-drift edge case
  explicitly (test must prove both hand-edit-fails AND reordered-passes).
- All seven cycle-5 LOW items were correctly left deferred and not re-litigated.

**Concerns.**
- **LOW / NEW — `capture_baseline_eval_results` is described as "runs `run_eval` over the baseline
  `DotMDService`," but `run_eval` is a diff-comparison function, not a capture-from-service function.**
  `run_eval(EvalRunnerConfig)` (`surreal_eval_runner.py:151`) loads `baseline_results`/`candidate_results`
  from pre-existing JSONL FILE PATHS and `classify_difference`s them — it never runs queries through a
  live service. The plan (`43-02-PLAN.md:61,100,274,365` and the action at `:371`) conflates the
  "capture" step (run golden queries through the baseline `DotMDService` → produce one side's
  `EvalResult` JSONL) with the "diff" step (`run_eval` consuming two already-produced JSONL files). The
  intent is clear and an executor would resolve it, but the description mixes the two concepts; the
  candidate side already has an explicit field-mapping function (`capture_eval_results_from_candidates`)
  and the baseline capture deserves the same clarity. Documentation/precision item, not blocking.

**Risk Assessment — LOW.** The architecture is settled across cycles; all four actionable MEDIUMs are
concretely closed; the one new concern is a documentation imprecision, not an execution blocker. No
architecture, mechanism, or test-coverage gap rises to HIGH or MEDIUM.

---

## Consensus Summary

### Agreed Strengths
- **0 unresolved HIGH; all four cycle-5 MEDIUMs are CLOSED.** Both reviewers independently re-traced
  the cited symbols against live source (`surreal_eval_runner.py:159`, `pipeline.py:139/222`,
  `graph.py:149-161`) and confirmed each pin is concrete, source-grounded, and test-named.
- The settled Option A architecture (GRAPH.COPY isolated baseline graph, `falkordb_graph_name` clean
  knob default `"dotmd"`, symmetric full-16-query corpus with `require_complete_category_coverage=True`,
  production immutability) holds; neither reviewer re-opened it.
- The temp-file sentinel wiring (D43-02-F), the suffixed vec-table derivation (D43-02-J), the ordered
  stale-destination pre-delete with production-name guard (D43-02-L step 2), and the `query_id`-keyed
  canonical `--verify-only` comparison (D43-03-C) are each correct and testable as written.

### Agreed Concerns
- **No unresolved HIGH** — both reviewers confirm zero new HIGH and that the four pins close their
  cycle-5 targets.
- The only residual items are **LOW plan-text precision/consistency nits**, both confined to plan prose
  (not architecture, not mechanism):
  1. The `capture_baseline_eval_results` description conflates "capture (run queries through the baseline
     `DotMDService` → produce `EvalResult` JSONL)" with `run_eval`'s actual role (diff two pre-existing
     result JSONL files). Source-confirmed: `run_eval` reads result files and classifies, it does not run
     searches. **(OpenCode; also implicit in codex's "stale symbol contract" note.)**
  2. Stale "graph-exclusion marker (D43-02-G)" wording at `43-02:120` and `43-03:157`, plus the orphaned
     `load_source_capture_manifest` export/contract (`43-02:37,237`), contradict the dominant, test-pinned
     "NO graph-exclusion marker / full-corpus Option A" text. **(Codex.)**

### Divergent Views
- Codex rates overall risk MEDIUM, OpenCode rates it LOW. The divergence is emphasis, not substance:
  codex's MEDIUM is driven entirely by the not-yet-executed state (implementation/test files absent),
  which is the expected pre-execution condition of a plan review and is excluded from the actionable
  count; on the plan TEXT itself both agree the residual items are LOW. The two reviewers surfaced
  different (non-overlapping) LOW plan-text nits, which together form the actionable non-HIGH set below.

---

## Verification coverage (source-grounding pass)

Every concrete symbol the cycle-6 pins cite was independently checked against live dotMD source by the
executing reviewer. Artifacts the plans declare under their produced-artifacts lists
(`surreal_shadow_metrics.py`, `surreal_shadow_runner.py`, `source-capture.json`, the evidence bundle,
the `falkordb_graph_name` field, the new runner symbols, the `43-0x-SUMMARY.md` files) are EXCLUDED from
MISSING verdicts — they are outputs of this phase, not pre-existing dependencies.

| Symbol / claim cited by the cycle-5 pins | Location verified | Verdict |
|------------------------------------------|-------------------|---------|
| `_model_to_table_suffix(model_name)` is a MODULE-LEVEL importable function (D43-02-J pin) | `src/dotmd/ingestion/pipeline.py:139` | VERIFIED |
| Pipeline assembles `vec_chunks_{strategy}{model_suffix}` and `chunks_fts_{strategy}` | `pipeline.py:215,221,222` | VERIFIED — pin's derivation matches exactly |
| `run_eval(EvalRunnerConfig)` calls `_load_acceptances(config.acceptance)` directly on the file path (D43-02-F pin) | `devtools/surreal_eval_runner.py:151,159` | VERIFIED |
| `EvalRunnerConfig.acceptance: Path | None` (the field the runner re-points at the stripped temp file) | `surreal_eval_runner.py:35` | VERIFIED |
| `_load_acceptances` REQUIRES `accepted_by`/`accepted_reason` per row (raises on a sentinel row) | `surreal_eval_runner.py:65-66,73-76` | VERIFIED — basis for why the sentinel must be stripped before `run_eval` |
| `run_eval` loads `baseline_results`/`candidate_results` from FILE PATHS and `classify_difference`s — it is a DIFF function, not a capture-from-service function | `surreal_eval_runner.py:151-185` (`load_eval_results(config.baseline_results)`, `classify_difference`) | VERIFIED — basis of the OpenCode LOW (`capture_baseline_eval_results` vs `run_eval` conflation) |
| `Graph.copy(clone)` executes `COPY_CMD self.name clone` with NO destination pre-existence check (D43-02-L pin) | `.venv/.../falkordb/graph.py:14,149-160` | VERIFIED — basis of the stale-destination idempotency pin |
| `Graph.delete()` → `DELETE_CMD self._name` (`GRAPH.DELETE`) | `.venv/.../falkordb/graph.py:16,163-174` | VERIFIED |
| `FalkorDB.select_graph(graph_id)` and `FalkorDB.list_graphs() -> List[str]` (used by the controlled pre-copy delete) | `.venv/.../falkordb/falkordb.py:187,204` | VERIFIED |
| `_create_graph_store()` currently hardcodes `graph_name="dotmd"` (plan replaces with `settings.falkordb_graph_name`) | `ingestion/pipeline.py:161,167` | VERIFIED |
| `DEFAULT_FALKORDB_URL`@26, `RUNTIME_INDEX_DIR=Path("/dotmd-index")`@40, `falkordb_url` field@208, `validate_for_runtime` rejects non-`/dotmd-index` | `core/config.py:26,40,208,342,364-367` | VERIFIED |
| `build_surreal_native_engine_overrides(connection, settings, *, embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` accepts ONLY those two tuning params and returns `{semantic, keyword, graph_direct}` | `search/surreal_native.py:18,22,23,44`; `DEFAULT_HNSW_EF` import @11 | VERIFIED — candidate `graph_direct` engine is the symmetric counterpart under Option A |
| `require_complete_category_coverage: bool = True` enforced; golden corpus = 16 rows incl. GRAPH_ENTITY + MIXED_RU_EN | `surreal_eval_runner.py:36,155`; `surreal_eval.py:28,31`; `devtools/surreal_golden_queries.jsonl` (16 lines) | VERIFIED |

**Coverage result:** No MISSING symbols among pre-existing dependencies. No AMBIGUOUS verdicts material
to logic. No UNCHECKABLE items. All four cycle-5 MEDIUM pins are VERIFIED source-grounded and close
their targets. Two source-confirmed LOW plan-text imprecisions were surfaced (both confined to plan
prose, neither touching architecture or mechanism):
1. `capture_baseline_eval_results` is described as "runs `run_eval` over the `DotMDService`," but
   `run_eval` is a diff-over-result-files function (`surreal_eval_runner.py:151-185`); the capture step
   that produces the baseline `EvalResult` JSONL from the live service is the distinct operation.
2. Residual "graph-exclusion marker (D43-02-G)" wording (`43-02:120`, `43-03:157`) and the orphaned
   `load_source_capture_manifest` export/contract (`43-02:37,237`) contradict the dominant, test-pinned
   "NO graph-exclusion marker / full corpus" Option A text.

---

## Cycle-6 disposition (counts for the convergence loop)

- **Unresolved HIGH (current_high = 0).** Both reviewers independently confirm — against live source —
  that the plans carry no unresolved HIGH and that all four cycle-5 actionable MEDIUMs (sentinel→`run_eval`
  wiring, vec-table-name derivation, GRAPH.COPY stale-destination idempotency, `--verify-only`
  `query_id`-canonical diff) are CLOSED by commit `cf1ec2c`. No new HIGH was raised. The Option A
  architecture remains settled.

- **Unresolved actionable non-HIGH (current_actionable = 2):**
  1. **LOW — Clarify `capture_baseline_eval_results` as the CAPTURE step (run golden queries through the
     baseline `DotMDService` → produce Phase 40 `EvalResult` JSONL), distinct from `run_eval` (the DIFF
     step that consumes two already-produced result JSONL files).** Source-confirmed: `run_eval`
     (`surreal_eval_runner.py:151-185`) reads `baseline_results`/`candidate_results` from file paths and
     classifies — it does not execute searches against a service. PLAN.md (`43-02-PLAN.md:61,100,274,365,371`)
     should describe `capture_baseline_eval_results` as running the corpus through the service to emit
     `EvalResult` JSONL (mirroring the candidate side's explicit `capture_eval_results_from_candidates`),
     rather than "runs `run_eval` over the `DotMDService`." Both reviewers converge on this `run_eval`
     mental-model imprecision.
  2. **LOW — Remove the residual "graph-exclusion marker (D43-02-G)" wording and the orphaned
     `load_source_capture_manifest` symbol contract.** PLAN.md text at `43-02-PLAN.md:120` (D43-02-K block)
     and `43-03-PLAN.md:157` still says the produced `source-capture.json` records a "graph-exclusion
     marker," contradicting the SUPERSEDED status of D43-02-G and the dominant Option A text (and the
     `43-03:184` verify that asserts `'graph_engines_disabled' not in cap`). Likewise
     `load_source_capture_manifest` is still listed as an export (`43-02:37`) and function contract
     (`43-02:237`) despite D43-02-K splitting it into `load_expected_source_manifest` + the produced
     `source-capture.json`. Remove both so the plan text is internally consistent with Option A and the
     immutable-input/produced-output split.

  (EXCLUDED from the actionable count: codex's "missing runtime implementation/test/summary files"
  MEDIUM — those are artifacts THIS PHASE PRODUCES and are correctly absent before execution. The seven
  cycle-5 LOW items — production-immutability mtime/size vs trickle quiescence, `teardown_baseline_graph`
  second-connection note, GRAPH.COPY server-failure empty-graph health check, candidate-manifest
  canonical-identity-marker hardening, `getrusage` Linux-only [already documented D43-01-C], latency
  computation semantics, CLI default-name discipline, operator no-hand-edit process — remain
  non-blocking and are not re-counted.)
