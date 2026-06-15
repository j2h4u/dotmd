---
phase: 43
cycle: 5
reviewers: [codex, opencode]
reviewed_at: 2026-06-15T13:45:20+05:00
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commit: efb3e42
note: "Cycle 5 re-reviews the CURRENT plans after the operator's Option A re-architecture (commit efb3e42): isolate the graph on BOTH sides (symmetric, full-fidelity) via a configurable falkordb_graph_name + a FalkorDB GRAPH.COPY of the production graph bound to the baseline run and torn down after capture. Resolved concerns from cycles 1-4 that are now incorporated into PLAN.md decisions (D43-*) are NOT re-counted. The executing reviewer runs inside Claude Code, so the `claude` CLI is skipped for independence; codex and opencode are the external reviewers."
---

# Cross-AI Plan Review — Phase 43 (Cycle 5)

The plans were re-architected in commit `efb3e42` per an explicit OPERATOR DECISION: **Option A —
isolate the graph on BOTH sides (symmetric, full-fidelity)**. The baseline binds to an isolated
FalkorDB graph COPY (`GRAPH.COPY` of the production `dotmd` graph into `dotmd_shadow_baseline`,
bound via the new configurable `falkordb_graph_name` Settings field, torn down via `GRAPH.DELETE`
after capture); the candidate uses its isolated Surreal target. The full 16-query corpus runs on
both sides with `require_complete_category_coverage=True`. Cycle-3 decisions D43-02-I (graph-free
factory) and D43-02-G (graph exclusion) are marked SUPERSEDED.

This cycle re-reviews the CURRENT state, confirms the Option A mechanism is sound against source
(GRAPH.COPY/GRAPH.DELETE real and used correctly; isolated baseline graph populated from the right
corpus; both sides genuinely symmetric; production graph/index untouched), and surfaces only
genuinely new, unresolved concerns. The cycle-4 unresolved HIGHs are explicitly re-evaluated for
dissolution.

## Codex Review

**Verdict: Option A is SOUND.** All five mechanism checks (a–e) pass against source facts. Two
MEDIUM and three LOW concerns remain (none blocking).

**Source fact verification (Codex independently re-traced):**
- `GRAPH.COPY` real — `falkordb/graph.py:14,149-161`: `Graph.copy(clone)` → `GRAPH.COPY <self.name> <clone>`, returns `Graph(client, clone)`. ✅
- `GRAPH.DELETE` real — `graph.py:16,163-174`: `Graph.delete()` → `GRAPH.DELETE <self._name>`. ✅
- `list_graphs()` — `falkordb.py:204`. ✅
- `_create_graph_store` hardcodes `"dotmd"` — `pipeline.py:161-167`. ✅
- `FalkorDBGraphStore.__init__` issues `CREATE INDEX` eagerly at construction — `falkordb_graph.py:37-62`. ✅
- `DotMDService.__init__` → `IndexingPipeline` → `_create_graph_store` — `service.py:260`, `pipeline.py:246`. ✅
- `build_surreal_native_engine_overrides` returns `graph_direct` — `surreal_native.py:44`. ✅ (now CORRECT under Option A: baseline has a graph too, so symmetric).
- `SurrealConnection.use(ns, db)` → isolated target — `surreal.py:125`; `SurrealGraphDirectEngine` queries `entities`/`relations` within ns/db — `surreal_graph.py:14,33-61`. ✅
- Golden corpus: 16 queries, incl. graph-entity (sq-004/009/010) + mixed-ru-en (sq-015/016). ✅
- `validate_for_runtime` requires `/dotmd-index`/`/mnt` — must NOT be called on rehearsal clone. ✅

**Strengths.**
- Option A mechanism verified sound on all 5 checks; `GRAPH.COPY` → `GRAPH.DELETE` in `try/finally`.
- `enforce_baseline_graph_isolation("dotmd")` raises `ValueError` — double-lock on production avoidance.
- Both sides run the full 16-query corpus with `require_complete_category_coverage=True` — genuinely symmetric.
- `falkordb_graph_name` default `"dotmd"` — production unchanged unless env explicitly set (clean knob, not a compat shim).
- `Settings.model_copy(update={...})` clone — no env/TOML mutation.
- Rehearsal identity fail-closed (D43-02-J) + expected-manifest immutability (D43-02-K) carried forward.

**Concerns.**
- **MEDIUM / NEW — Sentinel-to-Phase-40-loader wiring is described as behavior but not pinned against `run_eval`.** `run_eval()` calls `_load_acceptances(config.acceptance)` directly on the file path (`surreal_eval_runner.py:159` → `:48-82`), and `_load_acceptances` requires `accepted_by`/`accepted_reason` per row — a `record_type="phase43_ledger_metadata"` sentinel row would raise `ValueError`. D43-02-F states `load_shadow_acceptance_ledger()` strips the sentinel "so the Phase 40 loader never receives a sentinel row," but the concrete wiring (write a stripped temp file and point `EvalRunnerConfig.acceptance` at it, vs. passing the raw `accepted-diffs.jsonl` path to `run_eval`) is not pinned in the plan. The named test `test_ledger_sentinel_plus_acceptance_passes_only_real_rows_to_loader` asserts the loader never gets a sentinel, but the plan should make the temp-file/bypass mechanism explicit so the executor wires `run_eval`'s `acceptance` input to the stripped content, not the raw file.
- **MEDIUM / NEW — `assert_rehearsal_identity_matches_manifest` vector-table name derivation is underspecified.** Counting embeddings for `(chunk_strategy, embedding_model)` requires the vector table name `vec_chunks_{strategy}{model_suffix}`, where `model_suffix = _model_to_table_suffix(embedding_model)` (`pipeline.py:139` module-level; assembly at `pipeline.py:222` inside `IndexingPipeline.__init__`, not a standalone reusable function). The plan (D43-02-J) says to count embeddings but does not mention importing/reusing `_model_to_table_suffix` or replicating the `vec_chunks_`/`chunks_fts_` derivation. A wrong table name would silently count zero vectors and could pass-or-fail the fail-closed gate incorrectly. The plan should pin importing `_model_to_table_suffix` from `dotmd.ingestion.pipeline` and replicating the ~2-line table-name assembly.
- **LOW — Production-immutability mtime/size check vs concurrent trickle.** D43-02-L step 6 asserts the production `index.db` mtime/size is unchanged, but trickle could legitimately modify production during a shadow run, spuriously failing the assertion (test uses mocks, so this is runtime-only). The graph-side check (`dotmd` present in `list_graphs()`; baseline name never `"dotmd"`) is robust; the index.db mtime/size check should record pre-run values and tolerate trickle, or be documented as requiring trickle quiescence.
- **LOW — `teardown_baseline_graph` opens a second FalkorDB client.** The `IsolatedBaselineGraph` handle carries the name, not a live client, so teardown reconnects. Works, but worth a one-line note.
- **LOW — GRAPH.COPY server-side failure leaves an empty baseline graph.** If `GRAPH.COPY` fails (e.g. FalkorDB OOM), the baseline `DotMDService` would be built against an empty/missing graph, producing garbage baseline graph hits. The rehearsal-identity check catches chunk/embedding mismatches but not graph node/edge emptiness. Consider a minimal graph health check (node count > 0) before baseline capture, or note as accepted risk in the runbook.

**Cycle-4 HIGH dissolution — CONFIRMED.**
| Cycle-4 HIGH | Disposition | Sound? |
|--------------|-------------|--------|
| Candidate `graph_direct` asymmetry vs graph-free baseline | Baseline now queries isolated `GRAPH.COPY`; candidate queries isolated Surreal target — symmetric | ✅ DISSOLVED |
| Filtered subset vs `require_complete_category_coverage=True` | No subset; full 16-query corpus on both sides | ✅ DISSOLVED |
| (cycle-4 MEDIUM) read-only invariant / fused-pool hydration | Baseline uses normal `DotMDService`/`run_eval` over isolated throwaway copies; `EvalResult` produced directly | ✅ DISSOLVED |

**Risk Assessment — LOW-MEDIUM.** Option A is architecturally sound. The two MEDIUM concerns are
implementation-clarity gaps the author resolves during development; neither threatens the
architecture. LOW concerns are operational edge cases.

---

## OpenCode Review

**Option A validation against checks (a–e):**
- (a) GRAPH.COPY / GRAPH.DELETE availability and use — **PASS**. Plan uses `select_graph(...).copy(...)` and `Graph.delete()`, matching client source.
- (b) Isolated baseline graph source of truth — **PASS (with caution)**. Baseline is copied from `--production-graph-name` (default `dotmd`) into `--baseline-graph-name` and bound to the baseline `DotMDService` via `falkordb_graph_name`.
- (c) Symmetric full corpus on both sides — **PASS**. Non-graph filtering removed; `require_complete_category_coverage=True` on both captures.
- (d) Production index/graph untouched — **PASS in intent**. Rehearsal copies + isolated graph copy + final immutability assertions specified.
- (e) Graph-name config knob is clean parameterization — **PASS**. `falkordb_graph_name` defaults to `"dotmd"`, threaded into `_create_graph_store`, no default runtime behavior change.

**Strengths.**
- The clean config change (`DEFAULT_FALKORDB_GRAPH_NAME` + `Settings.falkordb_graph_name`) is the right production-safe baseline-binding mechanism.
- `copy_baseline_graph`/`teardown_baseline_graph` with `try/finally` addresses isolation lifecycle and cleanup.
- Full-corpus capture preserves mixed-RU/EN and graph-entity categories (critical real-regression signal).
- Manifest split (`source-capture-expected.json` immutable input vs produced `source-capture.json`) avoids validation-loop contamination.
- Candidate-config schema separation (`embedding_dimension`/`hnsw_ef` for overrides, `top_k`/`pool_size` for the loop) is deterministic and fail-closed.

**Concerns.**
- **MEDIUM / NEW — Baseline destination-graph lifecycle is not idempotent on a stale isolate.** If `dotmd_shadow_baseline` already exists from a prior interrupted run, `GRAPH.COPY` behavior with a pre-existing destination is unspecified by the client (`Graph.copy` simply executes `GRAPH.COPY self.name clone` with no pre-check). The plan should preemptively `GRAPH.DELETE` any pre-existing baseline graph in a controlled path before the copy, or refuse early with a clear message, to keep the run idempotent.
- **MEDIUM / NEW — `--verify-only` diff regeneration should compare by `query_id`, not raw byte/row-order.** The plan (Task 3 / D43-03-C) says `--verify-only` regenerates `shadow-diffs.jsonl` and compares it "byte/row-wise" against the on-disk file. Serializer or row-order drift between capture and verify could cause false tamper failures. Canonicalize the comparison by `query_id` mapping so it still catches hand-edited classifications without being brittle to ordering.
- **MEDIUM — Candidate-side isolation is only as strong as the operator-supplied manifest identity.** Identity/preflight checks bound the candidate target (D43-03-D), but if `expected_manifest` does not carry a canonical namespace/database identity, a wrong namespace with matching shape (chunk strategy / embedding model / counts) could pass shape-based checks. Consider a deterministic target-identity marker (e.g. import/source manifest hash) beyond row counts.
- **LOW — `SurrealConnection.use(namespace, database)` coupling.** If client API drift exists in this checkout, this is a method-shape coupling; use the explicit existing connection constructor path consistently.

**43-01 / 43-03 concerns.** 43-01: two LOW (Linux-only `getrusage` already documented; latency computation semantics pushed to caller/tests — acceptable for scope). 43-03: one MEDIUM (same canonical-`query_id` diff-comparison point as 43-02) and two LOW (CLI default-name discipline; operator process discipline for not hand-editing raw diffs).

**Risk Assessment — MEDIUM (43-02), LOW (43-01), LOW-MEDIUM (43-03).** "Option A is materially
sound and the major remaining gap is operational determinism/safety around isolate-graph lifecycle
and candidate-target identity enforcement. No newly discovered critical/high-severity blocker
remains; residual risk is mostly medium and around edge-case hardening rather than architecture
mismatch."

---

## Consensus Summary

### Agreed Strengths
- **Option A is sound and dissolves both cycle-4 HIGHs.** Both reviewers independently re-traced the
  source and confirmed `GRAPH.COPY`/`GRAPH.DELETE` are real in the installed FalkorDB client
  (`graph.py:14,16,149-174`), correctly invoked via `select_graph(source).copy(dst)` and
  `Graph.delete()`, that the baseline `DotMDService` binds to the isolated copy via the new
  `falkordb_graph_name` knob (default `"dotmd"`, production unaffected), and that both sides run the
  full 16-query corpus with `require_complete_category_coverage=True` — genuinely symmetric.
- The `try/finally` teardown, `enforce_baseline_graph_isolation` refusing `"dotmd"`, the
  input/output manifest split (D43-02-K), fail-closed rehearsal identity (D43-02-J), preflight
  identity binding (D43-03-D), and `--verify-only` tamper detection (D43-03-C) are all sound.

### Agreed Concerns
- **No unresolved HIGH.** Both reviewers explicitly confirm zero new HIGH and that both cycle-4
  HIGHs are dissolved by Option A.
- Both surface the same underlying theme — **operational determinism / hardening around the
  isolate-graph lifecycle and the diff-comparison mechanism**, not architecture: (1) the
  sentinel→`run_eval` wiring and the embedding-count table-name derivation need to be pinned
  (Codex), (2) the stale-destination idempotency of `GRAPH.COPY` and the `query_id`-canonical
  diff comparison need hardening (OpenCode).

### Divergent Views
- Codex rates 43-02 LOW-MEDIUM; OpenCode rates it MEDIUM. The difference is emphasis, not
  substance — both agree the architecture is sound and the residual items are implementation/
  operational hardening, none HIGH. The two reviewers each surfaced a different (non-overlapping)
  MEDIUM about the runner internals (Codex: sentinel-wiring + vec-table suffix; OpenCode:
  GRAPH.COPY idempotency + query_id-canonical diff compare), which together form the actionable
  non-HIGH set below.

---

## Verification coverage (source-grounding pass)

Every concrete symbol the plans cite was checked against live dotMD source. Artifacts the plans
declare under "Artifacts This Phase Produces" (`surreal_shadow_metrics.py`, `surreal_shadow_runner.py`,
`source-capture-expected.json`, `source-capture.json`, the eight evidence artifacts, the new
`falkordb_graph_name` field, and all new runner symbols) are excluded from MISSING verdicts — they
are outputs of this phase, not pre-existing dependencies.

| Symbol / claim cited by plan | Location verified | Verdict |
|------------------------------|-------------------|---------|
| `GRAPH.COPY` command + `Graph.copy(clone)` → `GRAPH.COPY <self.name> <clone>`, returns `Graph(client, clone)` | `.venv/.../falkordb/graph.py:14,149-161` | VERIFIED |
| `GRAPH.DELETE` command + `Graph.delete()` → `GRAPH.DELETE <self._name>` | `.venv/.../falkordb/graph.py:16,163-174` | VERIFIED |
| `FalkorDB.select_graph(graph_id)` and `FalkorDB.list_graphs() -> List[str]` | `.venv/.../falkordb/falkordb.py:187,204` | VERIFIED |
| `_create_graph_store()` currently hardcodes `graph_name="dotmd"` (plan replaces with `settings.falkordb_graph_name`) | `ingestion/pipeline.py:161-167` | VERIFIED |
| `FalkorDBGraphStore.__init__(url, graph_name="dotmd")` connects (`select_graph`) and issues `CREATE INDEX` for 5 labels eagerly at construction | `storage/falkordb_graph.py:37-62` | VERIFIED |
| `DotMDService.__init__` → `IndexingPipeline(settings)` → `_create_graph_store(settings)` (eager graph build) | `api/service.py:260`, `ingestion/pipeline.py:246` | VERIFIED |
| `DEFAULT_FALKORDB_URL`@26, `RUNTIME_INDEX_DIR=Path("/dotmd-index")`@40, `falkordb_url` field@208 | `core/config.py:26,40,208` | VERIFIED |
| `Settings(BaseSettings)` with `model_copy(update=...)` available; `index_db_path == index_dir / "index.db"` | `core/config.py:55,406` | VERIFIED |
| `chunk_strategy`@102, `embedding_model`@76 settings fields | `core/config.py:76,102` | VERIFIED |
| `validate_for_runtime()` rejects non-`/dotmd-index` index_dir (runner must NOT call on clone) | `core/config.py:333-370` | VERIFIED |
| `build_surreal_native_engine_overrides(connection, settings, *, embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` accepts ONLY those two tuning params and RETURNS `{semantic, keyword, graph_direct}` | `search/surreal_native.py:18-44` | VERIFIED (candidate has a `graph_direct` engine — now CORRECT/symmetric under Option A, no longer a defect) |
| `DEFAULT_HNSW_EF` import source | `search/surreal_native.py:11` (`storage/surreal_schema`) | VERIFIED |
| `SurrealConnection.use(namespace, database)` binds the isolated target ns/db | `storage/surreal.py:125` | VERIFIED |
| `SurrealGraphDirectEngine` queries `entities`/`relations` within the bound ns/db | `search/surreal_graph.py:14,33-61` | VERIFIED |
| `run_eval(EvalRunnerConfig)` exists; `require_complete_category_coverage: bool = True`@36 enforced@155 | `devtools/surreal_eval_runner.py:36,151,155` | VERIFIED |
| `run_eval` calls `_load_acceptances(config.acceptance)` directly on the file path; `_load_acceptances` requires `accepted_by`/`accepted_reason` per row | `devtools/surreal_eval_runner.py:159,48-82` | VERIFIED — basis of the sentinel-wiring actionable MEDIUM (D43-02-F states the strip behavior but not the `run_eval` wiring) |
| `load_eval_results(path)` exists (validity check, not just non-empty) | `search/surreal_eval.py:311` | VERIFIED |
| `GoldenQueryCategory` includes GRAPH_ENTITY and MIXED_RU_EN; golden corpus = 16 rows incl. 2 graph-entity + 2 mixed-ru-en | `search/surreal_eval.py:21-31`, `devtools/surreal_golden_queries.jsonl` | VERIFIED |
| `_model_to_table_suffix(model_name)` is module-level importable; `vec_chunks_{strategy}{model_suffix}` / `chunks_fts_{strategy}` assembly lives in `IndexingPipeline.__init__` (not standalone) | `ingestion/pipeline.py:139,221,222` | VERIFIED — basis of the embedding-count table-name actionable MEDIUM (identity check needs this derivation; plan does not pin it) |
| `Graph.copy` executes `GRAPH.COPY self.name clone` with no pre-existence check on `clone` | `.venv/.../falkordb/graph.py:149-161` | VERIFIED — basis of the GRAPH.COPY stale-destination idempotency actionable MEDIUM |
| `evaluate_surreal_scale_gate` field names (`passed`, `failure_category`, `recommendation_gate`, ...) | `search/surreal_parity.py:41,50,68,91` | VERIFIED |
| `EvalResult`/`DiffAcceptance` use `query_id`/`accepted_by`/`accepted_reason` | `search/surreal_eval.py:73-103` | VERIFIED |
| read_first devtool fixtures exist (`test_surreal_eval_runner.py`, `surreal_migration_runner.py`) | `backend/tests/devtools/`, `backend/devtools/` | VERIFIED |

**Coverage result:** No MISSING symbols. No AMBIGUOUS verdicts material to logic (the cycle-4
`id` vs `query_id` golden-row naming nuance is cosmetic and unchanged). No UNCHECKABLE items. The
Option A mechanism (GRAPH.COPY/GRAPH.DELETE isolated baseline graph, `falkordb_graph_name` clean
knob, symmetric full-corpus capture, production immutability) is VERIFIED sound against source. The
candidate-side `graph_direct` engine — the cycle-4 HIGH #1 — is confirmed present and now CORRECT
under Option A (it is the symmetric counterpart to the isolated baseline graph, not an asymmetry).
The cycle-4 HIGH #2 (category-coverage collision) is dissolved because there is no filtered subset:
the full 16-query corpus runs on both sides with `require_complete_category_coverage=True`.

Four source-confirmed actionable non-HIGH gaps were surfaced (all MEDIUM, all implementation/
operational hardening, none threatening the architecture):
1. Sentinel→`run_eval`/`_load_acceptances` wiring not pinned (`surreal_eval_runner.py:159` loads on file path).
2. `assert_rehearsal_identity_matches_manifest` embedding-count vector-table-name derivation not pinned (`_model_to_table_suffix` / `vec_chunks_{strategy}{suffix}`).
3. `GRAPH.COPY` stale-destination idempotency (pre-existing `dotmd_shadow_baseline` from an interrupted run).
4. `--verify-only` diff comparison should canonicalize by `query_id` rather than raw byte/row-order.

---

## Cycle-5 disposition (counts for the convergence loop)

- **Unresolved HIGH (current_high = 0).** Both reviewers independently confirm Option A is sound
  against source and that both cycle-4 HIGHs (candidate `graph_direct` asymmetry; filtered-subset
  vs category-coverage collision) are DISSOLVED by the re-architecture. No new HIGH was raised.

- **Unresolved actionable non-HIGH (current_actionable = 4):**
  1. **MEDIUM — Pin the sentinel→`run_eval` acceptance wiring.** D43-02-F states
     `load_shadow_acceptance_ledger()` strips the `phase43_ledger_metadata` sentinel so the Phase 40
     loader never receives it, but `run_eval()` calls `_load_acceptances(config.acceptance)` directly
     on the file path (`surreal_eval_runner.py:159`), which raises on a sentinel row. PLAN.md (D43-02-F /
     Task 3 action) should pin the concrete mechanism (write a stripped temp file and point
     `EvalRunnerConfig.acceptance` at it, or otherwise bypass passing the raw `accepted-diffs.jsonl`
     path into `run_eval`).
  2. **MEDIUM — Pin the embedding-count vector-table-name derivation for the rehearsal-identity check.**
     D43-02-J must specify that `assert_rehearsal_identity_matches_manifest` imports
     `_model_to_table_suffix` from `dotmd.ingestion.pipeline` and derives `vec_chunks_{strategy}{suffix}`
     (and `chunks_fts_{strategy}`) to count embeddings; otherwise a wrong table name could silently
     count zero and mis-fire the fail-closed gate.
  3. **MEDIUM — Make the isolated baseline graph copy idempotent on a stale destination.** Add a
     controlled pre-copy `GRAPH.DELETE` (or early refusal) for a pre-existing `--baseline-graph-name`
     so an interrupted prior run cannot corrupt the copy; `Graph.copy` performs no destination
     pre-check (`graph.py:149-161`). PLAN.md (D43-02-L step 2) should state this.
  4. **MEDIUM — Canonicalize the `--verify-only` diff comparison by `query_id`.** D43-03-C / 43-02
     Task 3 says `--verify-only` compares regenerated `shadow-diffs.jsonl` "byte/row-wise"; change the
     comparison to a `query_id`-keyed canonical comparison so serializer/row-order drift does not
     produce false tamper failures while still catching hand edits.

  (LOW items — production-immutability mtime/size vs trickle quiescence, `teardown_baseline_graph`
  second-connection note, GRAPH.COPY server-failure empty-graph health check, candidate-manifest
  canonical-identity-marker hardening, `getrusage` Linux-only [already documented D43-01-C], latency
  computation semantics, CLI default-name discipline, operator no-hand-edit process — are non-blocking
  runbook/wording/hardening suggestions and are not counted as actionable blockers.)
