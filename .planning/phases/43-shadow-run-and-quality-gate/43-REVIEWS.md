---
phase: 43
cycle: 7
reviewers: [codex, opencode]
reviewed_at: 2026-06-15T15:05:00+05:00
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commits: [cf1ec2c, 8566106]
note: "Cycle 7 is the FINAL CONFIRMING PASS. It re-reviews the CURRENT plans after commit 8566106, which scrubbed the two cycle-6 LOW plan-text consistency items (capture-vs-diff run_eval conflation; residual graph-exclusion-marker wording + orphaned load_source_capture_manifest export). Commit cf1ec2c had already pinned the four cycle-5 actionable MEDIUMs. The Option A isolated-graph architecture (D43-02-L) is settled and confirmed (cycle 5, 0 HIGH) and was NOT re-litigated. Resolved/scrubbed concerns from cycles 1-6 already incorporated into PLAN.md are NOT re-counted. Seven cycle-5 LOW runbook/wording items were explicitly deferred as non-blocking in prior cycles and are NOT re-raised. The executing reviewer runs inside Claude Code, so the `claude` CLI is skipped for independence; codex and opencode are the external reviewers."
---

# Cross-AI Plan Review — Phase 43 (Cycle 7 — Final Confirming Pass)

Commit `8566106` scrubbed the two cycle-6 LOW plan-text items (capture-vs-diff `run_eval`
conflation; residual graph-exclusion-marker wording and the orphaned `load_source_capture_manifest`
export). Commit `cf1ec2c` had already pinned the four cycle-5 actionable MEDIUMs. This cycle
re-reviews the CURRENT state and confirms the plans are execution-ready.

Both external reviewers (codex, opencode) independently re-traced the cited symbols against live
dotMD source and **independently concluded: 0 unresolved HIGH, 0 actionable non-HIGH, both cycle-6
LOWs RESOLVED.** The settled Option A isolated-graph architecture (D43-02-L) was not re-litigated.

## Codex Review

### Summary
Cycle-7 confirms the plans are coherent and execution-ready against the settled Option A
architecture: baseline and candidate are treated as separate capture artifacts with `run_eval`
explicitly as a DIFF phase, and graph isolation is now consistently documented as symmetric
full-fidelity (Graph COPY baseline + isolated Surreal target) with no graph-category exclusion
workflow. The remaining unresolved work is implementation, not plan-text integrity; at the plan
level, no new execution-blocking design gaps are evident.

### Cycle-6 LOW disposition
1. **Capture-vs-diff `run_eval` conflation — RESOLVED.** `43-02-PLAN.md` explicitly says
   baseline/candidate capture "EMIT[s] … `EvalResult` JSONL" and that `run_eval` is the separate
   DIFF step (truths in `must_haves`; key-link description "DIFF step: consumes … JSONL files").
   The behavior sections (`capture_baseline_eval_results`, `capture_eval_results_from_candidates`)
   reinforce the split and never define `capture_baseline_eval_results` as calling `run_eval` in its
   contract. `43-03-PLAN.md` (D43-03-C/B) states verify/reporting rely on regenerated diffs and that
   `run_eval` classifies the emitted capture files.
2. **Graph-exclusion marker + orphaned `load_source_capture_manifest` wording — RESOLVED.**
   `43-02-PLAN.md` marks `D43-02-G` as `SUPERSEDED by D43-02-L` and removes the graph-exclusion
   concept from the active mechanism; full-corpus behavior is required and the immutable input
   (`load_expected_source_manifest` + `source-capture-expected.json`) is explicitly separated from
   the produced output (`source-capture.json`), eliminating the old split-loader role. `43-03-PLAN.md`
   reiterates D43-03-E: full 16-query coverage, no non-graph subset, and explicitly checks
   `graph_engines_disabled` is not in the evidence output.

### Concerns
- **None.** No new execution-blocking concerns are identified in the current plan text beyond
  previously-referenced, already-resolved/non-blocking items.

### Source-grounding pass (pre-existing dependencies; phase-produced artifacts excluded)
- `surreal_eval_runner.py:35,48,151` — `EvalRunnerConfig`, `_load_acceptances`, `run_eval` as DIFF path. **VERIFIED**
- `surreal_eval.py:311` — `load_eval_results` used for canonical load/validation in 43-03-B/C. **VERIFIED**
- `surreal_native.py:18,23,44` — `build_surreal_native_engine_overrides` + `DEFAULT_HNSW_EF` match the engine-override/candidate-config contract. **VERIFIED**
- `pipeline.py:139` — `_model_to_table_suffix` import source for vector-table naming. **VERIFIED**
- `pipeline.py:215,221,222` — `vec_chunks_{strategy}{suffix}` / `chunks_fts_{strategy}` derivation aligns with identity checks. **VERIFIED**
- `pipeline.py:161` — `_create_graph_store` call path exists (currently hardcoded; to be updated by plan). **VERIFIED**
- `storage/falkordb_graph.py` — `FalkorDBGraphStore` exists, is the referenced graph-store seam. **VERIFIED**
- `api/service.py:260` — `DotMDService` path for baseline capture exists. **VERIFIED**
- `core/config.py:26,40,208,342` — `DEFAULT_FALKORDB_URL`, `RUNTIME_INDEX_DIR`, `falkordb_url` grounding for config-isolation checks. **VERIFIED**
- `core/config.py:364` — `validate_for_runtime` exists (plan correctly scopes it as NOT called for the rehearsal clone). **VERIFIED**
- `surreal_parity.py` (`evaluate_surreal_scale_gate`) — scale-gate field-name reuse grounded. **VERIFIED**
- `falkordb.Graph.copy`, `Graph.delete`, `FalkorDB.list_graphs`, `FalkorDB.select_graph` — external library behavior; repo-local verification limited because the concrete client implementation is outside the source tree. **UNCHECKABLE** (codex's framing; opencode verified these directly in the installed package — see below)

### Verdict
`current_high=0`, `current_actionable=0`.

---

## OpenCode Review

### Summary
The current plan state is polished and execution-ready. All four cycle-5 MEDIUM pins remain
concretely closed in the plan text, the Option A architecture is unchanged, and the text is
internally consistent. Both cycle-6 LOW items have been fully scrubbed by commits `cf1ec2c`,
`8566106`. No genuinely new, unresolved, execution-blocking issues remain across any of the three
plans.

### Cycle-6 LOW disposition

**Item 1 — capture-vs-diff `run_eval` conflation — RESOLVED.** The plan text cleanly separates
CAPTURE from DIFF:

| Evidence | Verdict |
|----------|---------|
| `43-02-PLAN.md:29` (truths): "EMIT the Phase 40 EvalResult JSONL schema DIRECTLY from the capture steps … NOT from run_eval" | Scrub applied |
| `43-02-PLAN.md:45` (key_links): "run_eval … the DIFF step: consumes the captured baseline + candidate EvalResult JSONL files and classifies their differences (it does NOT run searches)" | Scrub applied |
| `43-02-PLAN.md:61` (key_links): "capture_baseline_eval_results runs … to EMIT Phase 40 EvalResult baseline JSONL (the CAPTURE step …); run_eval (the separate DIFF step above) then consumes …" | Scrub applied |
| `43-02-PLAN.md:273` (artifact): "It does NOT call run_eval (which is the separate DIFF step that later consumes this baseline JSONL alongside the candidate JSONL)" | Scrub applied |

**Item 2 — graph-exclusion-marker + orphaned `load_source_capture_manifest` wording — RESOLVED.**
All four cited locations are clean:

| Cited location | Current text | Verdict |
|---------------|-------------|---------|
| `43-02-PLAN.md:120` (D43-02-K) | "It does **NOT** record any graph-exclusion marker (… superseded by Option A)" | Scrub applied |
| `43-03-PLAN.md:157` (input descriptors) | "**NOT** a graph-exclusion marker, which was superseded by Option A (D43-02-K)" | Scrub applied |
| `43-02-PLAN.md:37` (exports list) | Lists `load_expected_source_manifest` — the old `load_source_capture_manifest` name is absent | Scrub applied |
| `43-02-PLAN.md:237` (function contract) | "the earlier `load_source_capture_manifest` was split into this operator-input loader … and no longer exists." | Scrub applied |

### Concerns
- **None.** Zero genuinely new, unresolved, execution-blocking issues. The plan text is internally
  consistent, all cited mechanisms are source-grounded, and no architecture, mechanism, or
  test-coverage gap rises to any severity level.

### Source-grounding pass (pre-existing dependencies; phase-produced artifacts excluded)

| Symbol / claim | Live location | Verdict |
|---|---|---|
| `_model_to_table_suffix(model_name)` — module-level importable function | `pipeline.py:139-158` | **VERIFIED** |
| `vec_table = f"vec_chunks_{strategy}{model_suffix}"` (`model_suffix` from `_model_to_table_suffix`) | `pipeline.py:215,222` | **VERIFIED** — matches plan derivation exactly |
| `_create_graph_store()` hardcodes `graph_name="dotmd"` | `pipeline.py:167` | **VERIFIED** — literal `"dotmd"` |
| `self._graph_store = _create_graph_store(settings)` | `pipeline.py:246` | **VERIFIED** |
| `DEFAULT_FALKORDB_URL = "redis://localhost:6379"` | `config.py:26` | **VERIFIED** |
| `RUNTIME_INDEX_DIR = Path("/dotmd-index")` | `config.py:40` | **VERIFIED** |
| `falkordb_url: str = DEFAULT_FALKORDB_URL` | `config.py:208` | **VERIFIED** |
| `validate_for_runtime()` rejects non-`/dotmd-index` index_dir and `DEFAULT_FALKORDB_URL` | `config.py:342-343,366-367` | **VERIFIED** |
| `build_surreal_native_engine_overrides(connection, settings, *, embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` — only those two tuning params | `surreal_native.py:18-24` | **VERIFIED** |
| Returns `"graph_direct": SurrealGraphDirectEngine(connection)` | `surreal_native.py:44` | **VERIFIED** |
| `DEFAULT_HNSW_EF` import | `surreal_native.py:11` | **VERIFIED** |
| `EvalRunnerConfig.acceptance: Path \| None` | `surreal_eval_runner.py:35` | **VERIFIED** |
| `EvalRunnerConfig.require_complete_category_coverage: bool = True` | `surreal_eval_runner.py:36` | **VERIFIED** |
| `run_eval` calls `_load_acceptances(config.acceptance)` directly on the file path | `surreal_eval_runner.py:159` | **VERIFIED** |
| `_load_acceptances` requires `accepted_by`/`accepted_reason` per row | `surreal_eval_runner.py:65-66,73-76` | **VERIFIED** — basis for sentinel-strip requirement |
| `run_eval` loads `baseline_results`/`candidate_results` from FILE PATHS — it is a DIFF function | `surreal_eval_runner.py:151-158` | **VERIFIED** |
| `DotMDService.__init__(settings)` | `service.py:247,260-283` | **VERIFIED** |
| `FalkorDBGraphStore` class | `falkordb_graph.py:20` | **VERIFIED** |
| `Graph.copy(clone)` → `COPY_CMD self.name clone`, no destination pre-existence check | `falkordb/graph.py:149-161` | **VERIFIED** — basis of stale-destination idempotency pin |
| `Graph.delete()` → `DELETE_CMD self._name` (GRAPH.DELETE) | `falkordb/graph.py:163-174` | **VERIFIED** |
| `FalkorDB.select_graph(graph_id) -> Graph` | `falkordb/falkordb.py:187` | **VERIFIED** |
| `FalkorDB.list_graphs() -> List[str]` | `falkordb/falkordb.py:204` | **VERIFIED** |
| Golden corpus = 16 rows | `devtools/surreal_golden_queries.jsonl` | **VERIFIED** (16 lines) |

**Coverage result:** 0 MISSING, 0 AMBIGUOUS, 0 UNCHECKABLE among pre-existing dependencies.
(OpenCode directly inspected the installed `falkordb` package, so the four external-library symbols
codex flagged UNCHECKABLE are VERIFIED here.)

### Verdict
`current_high=0` (all prior HIGH concerns dissolved/incorporated; no new HIGH),
`current_actionable=0` (both cycle-6 LOWs RESOLVED in the current plan text; no new actionable
non-HIGH).

---

## Consensus Summary

### Agreed Strengths
- **0 unresolved HIGH; 0 actionable non-HIGH.** Both reviewers independently confirm — against live
  source — that the plans carry no unresolved HIGH and that both cycle-6 LOW plan-text items
  (capture-vs-diff `run_eval` conflation; graph-exclusion-marker + orphaned
  `load_source_capture_manifest`) are RESOLVED by commit `8566106`.
- The four cycle-5 MEDIUM pins (sentinel→`run_eval` temp wiring, suffixed vec-table derivation,
  GRAPH.COPY stale-destination idempotency, `query_id`-canonical `--verify-only` diff) remain
  CLOSED from cycle 6 — neither reviewer re-opened them.
- The settled Option A architecture (GRAPH.COPY isolated baseline graph, `falkordb_graph_name` clean
  knob default `"dotmd"`, symmetric full-16-query corpus with `require_complete_category_coverage=True`,
  production immutability) holds; neither reviewer re-litigated it.
- The CAPTURE-vs-DIFF split is now explicit and consistent: `capture_baseline_eval_results` and
  `capture_eval_results_from_candidates` EMIT `EvalResult` JSONL; `run_eval` is the separate DIFF
  step that consumes both JSONL files.

### Agreed Concerns
- **None.** Both reviewers report zero new HIGH and zero new actionable non-HIGH. The plan text is
  internally consistent and execution-ready.

### Divergent Views
- The only divergence is the source-grounding verdict for the four external `falkordb` client symbols
  (`Graph.copy`, `Graph.delete`, `FalkorDB.list_graphs`, `FalkorDB.select_graph`): codex marked them
  **UNCHECKABLE** (concrete client implementation outside the project source tree), while opencode
  inspected the installed `falkordb` package directly and marked them **VERIFIED**. This is a
  verification-scope difference, not a substantive disagreement — both agree the cited APIs exist and
  the plan's usage matches them. The cycle-6 grounding pass already VERIFIED these against the
  `.venv` falkordb package, so the binding verdict is **VERIFIED**.

---

## Verification coverage (source-grounding pass)

Every concrete pre-existing symbol the plans cite was independently checked against live dotMD source
by both external reviewers. Artifacts the plans declare under their produced-artifacts lists
(`surreal_shadow_metrics.py`, `surreal_shadow_runner.py`, `source-capture.json`, the evidence bundle,
the `falkordb_graph_name` field, the new runner symbols, the `43-0x-SUMMARY.md` files) are EXCLUDED
from MISSING verdicts — they are outputs of this phase, not pre-existing dependencies.

| Symbol / claim | Location | Verdict |
|---|---|---|
| `_model_to_table_suffix(model_name)` module-level importable | `pipeline.py:139-158` | VERIFIED |
| `vec_chunks_{strategy}{suffix}` / `chunks_fts_{strategy}` derivation | `pipeline.py:215,221,222` | VERIFIED |
| `_create_graph_store()` hardcodes `graph_name="dotmd"` (plan replaces with `settings.falkordb_graph_name`) | `pipeline.py:161,167,246` | VERIFIED |
| `run_eval(EvalRunnerConfig)` → `_load_acceptances(config.acceptance)` on the file path | `surreal_eval_runner.py:151,159` | VERIFIED |
| `EvalRunnerConfig.acceptance: Path \| None` + `require_complete_category_coverage: bool = True` | `surreal_eval_runner.py:35,36` | VERIFIED |
| `_load_acceptances` requires `accepted_by`/`accepted_reason` per row | `surreal_eval_runner.py:65-66,73-76` | VERIFIED |
| `run_eval` loads `baseline_results`/`candidate_results` from FILE PATHS (DIFF, not capture) | `surreal_eval_runner.py:151-158` | VERIFIED — basis of cycle-6 LOW #1 resolution |
| `load_eval_results` canonical load | `surreal_eval.py:311` | VERIFIED |
| `build_surreal_native_engine_overrides(... *, embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` + `DEFAULT_HNSW_EF` | `surreal_native.py:11,18-24,44` | VERIFIED |
| `evaluate_surreal_scale_gate` scale-gate field reuse | `surreal_parity.py` | VERIFIED |
| `DotMDService.__init__(settings)` | `service.py:247,260-283` | VERIFIED |
| `FalkorDBGraphStore` class | `storage/falkordb_graph.py:20` | VERIFIED |
| `DEFAULT_FALKORDB_URL`, `RUNTIME_INDEX_DIR`, `falkordb_url`, `validate_for_runtime` | `core/config.py:26,40,208,342-343,366-367` | VERIFIED |
| `Graph.copy(clone)` / `Graph.delete()` / `FalkorDB.select_graph` / `FalkorDB.list_graphs()` | `.venv/.../falkordb/graph.py:149-174`, `falkordb.py:187,204` | VERIFIED (opencode direct; codex UNCHECKABLE — scope difference) |
| Golden corpus = 16 rows incl. graph-entity + mixed-ru-en | `devtools/surreal_golden_queries.jsonl` | VERIFIED (16 lines) |

**Coverage result:** No MISSING symbols among pre-existing dependencies. No AMBIGUOUS verdicts
material to logic. One cross-reviewer scope difference (external `falkordb` client) reconciles to
VERIFIED. Both cycle-6 LOW plan-text items are RESOLVED in the current plan text.

**Reviewer-orchestrator observation (sub-LOW, NOT counted as actionable):** A single stale parenthetical
survives in a TEST DESCRIPTION at `43-02-PLAN.md:328` —
`test_capture_baseline_eval_results_runs_full_corpus_with_coverage` is glossed as "(assert
`capture_baseline_eval_results` calls `run_eval` …)", which echoes the pre-scrub mental model and
reads against the now-dominant contract at `43-02-PLAN.md:273` ("It does NOT call `run_eval`"). This
is a residual instance of the already-dispositioned cycle-6 LOW #1 class, confined to a
phase-produced test artifact's prose. It is NOT execution-blocking: the repeated, source-grounded
contract (lines 29, 45, 61, 100, 183, 273) unambiguously specifies EMIT-not-DIFF, so a TDD executor
writes the test to match the contract. Neither external reviewer flagged it as actionable. Recorded
for transparency; does not raise `current_actionable` above 0.

---

## Cycle-7 disposition (counts for the convergence loop)

- **Unresolved HIGH (current_high = 0).** Both reviewers independently confirm — against live source —
  that the plans carry no unresolved HIGH. The four cycle-5 MEDIUM pins remain CLOSED (commit
  `cf1ec2c`) and both cycle-6 LOW plan-text items are RESOLVED (commit `8566106`). No new HIGH was
  raised. The Option A architecture remains settled and confirmed.

- **Unresolved actionable non-HIGH (current_actionable = 0).** Both cycle-6 LOWs are RESOLVED in the
  current plan text with line-level evidence. No genuinely new, execution-blocking, non-HIGH concern
  was raised by either reviewer. The single residual stale parenthetical at `43-02-PLAN.md:328` is a
  sub-LOW instance of the already-dispositioned cycle-6 LOW #1 class, confined to a phase-produced
  test artifact, and is resolved for the executor by the dominant contract — not counted.

  (EXCLUDED from the actionable count: artifacts THIS PHASE PRODUCES — `surreal_shadow_runner.py`,
  `surreal_shadow_metrics.py`, the test modules, `source-capture.json`, the evidence bundle, the
  `43-0x-SUMMARY.md` files — correctly absent before execution. The seven cycle-5 LOW runbook/wording
  items remain explicitly deferred as non-blocking and are not re-counted.)

**Convergence:** Cycle 7 reaches 0 HIGH + 0 actionable across both independent reviewers. The plans
are confirmed execution-ready.
