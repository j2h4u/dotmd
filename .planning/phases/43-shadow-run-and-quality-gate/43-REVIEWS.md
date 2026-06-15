---
phase: 43
cycle: 4
reviewers: [codex, opencode]
reviewed_at: 2026-06-15T13:08:05+05:00
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commit: 6fcd63b
note: "Cycle 4 is an operator-authorized extension past the 3-cycle cap. Resolved concerns from cycles 1-3 are incorporated into the current PLAN.md decisions (D43-*) and are NOT re-counted here. The executing reviewer runs inside Claude Code, so the `claude` CLI is skipped for independence; codex and opencode are the external reviewers."
---

# Cross-AI Plan Review — Phase 43 (Cycle 4)

The plans were revised in commit `6fcd63b` to address all cycle-3 findings (the cycle-3 consensus
HIGH: baseline `DotMDService` construction eagerly opening + mutating live FalkorDB before any
`SearchMode` gate, plus four cycle-3 MEDIUM/LOW items). This cycle re-reviews the CURRENT state of the
plans, re-verifies the cycle-3 HIGH fix against source, and surfaces only genuinely new, unresolved
concerns.

## Codex Review

**Summary.** Cycle 4 is much stronger than earlier versions: the plans now explicitly separate
immutable expected input from produced evidence, bind rehearsal/candidate identity fail-closed, and
address the cycle-3 live-FalkorDB boundary directly. Two NEW blocking gaps remain around making the
"semantic+FTS-only" scope actually executable and fair, plus one medium read-only issue in the
proposed baseline engine construction.

**Cycle-3 HIGH fix verdict — HOLDS (for the FalkorDB boundary).**
In live source, `DotMDService.__init__` eagerly constructs `IndexingPipeline` (`service.py:260`),
which eagerly calls `_create_graph_store()` (`pipeline.py:246` → `:161`), which constructs
`FalkorDBGraphStore` whose `__init__` connects and issues `CREATE INDEX` during construction
(`falkordb_graph.py:47-63`). `SemanticSearchEngine` and `FTS5SearchEngine` can be constructed without
constructing `DotMDService`/`IndexingPipeline`/`FalkorDBGraphStore`: their constructors take a vector
store / SQLite connection directly (`semantic.py:51`, `fts5.py:93`). So the graph-free construction
fix is sound for the live-FalkorDB boundary.

**Strengths.**
- The cycle-3 HIGH is addressed by construction, not by a late `SearchMode` gate.
- `source-capture-expected.json` vs produced `source-capture.json` is cleanly separated.
- Rehearsal identity checks are fail-closed before baseline capture.
- Candidate target preflight now checks identity, not just reachability.
- `--verify-only` regenerating and comparing raw diffs is the right tamper-detection model.
- The graph exclusion is visible in artifacts instead of being silently hidden.

**Concerns.**
- **HIGH / NEW — Candidate capture is not guaranteed graph-free, so the semantic+FTS-only comparison
  can be unfair.** `build_surreal_native_engine_overrides()` returns `graph_direct` as well as semantic
  and keyword engines (`surreal_native.py:18`), and `DotMDService` hybrid collection uses `graph_direct`
  for `HYBRID` mode (`service.py:1379`). Filtering graph-category queries does not prevent the retained
  queries from receiving candidate-side graph hits. The plans claim "semantic+FTS-only" evidence but do
  not explicitly strip the candidate `graph_direct` engine or fuse only Surreal semantic+keyword pools.
- **HIGH / NEW — The non-graph golden subset conflicts with the existing Phase 40 evaluator unless the
  runner explicitly bypasses complete category coverage.** `run_eval()` defaults
  `require_complete_category_coverage=True` and validates all required categories
  (`surreal_eval_runner.py:151,155`; `surreal_eval.py:34-53`). Excluding `sq-009`/`sq-010` removes
  `graph-entity`; excluding `sq-015`/`sq-016` removes the only `mixed-ru-en` rows in the checked-in
  corpus. If the full corpus is passed, `run_eval()` will require missing graph results; if a filtered
  file is passed, category-coverage validation fails unless explicitly disabled. The 43-03 verify-only
  commands still point at the full golden file.
- **MEDIUM / NEW — Baseline capture is described as read-only, but the planned
  `FTS5SearchEngine(conn, table_name=...)` path is not read-only in current source.** Its constructor
  calls `_ensure_fts5_schema()`, which can `DROP`/`CREATE` the FTS table and `commit()` (`fts5.py:98`).
  `SQLiteVecVectorStore` can also create/alter tables on first `_get_conn()` use (`sqlite_vec.py:67`).
  This does not touch live production if the rehearsal copy is isolated, but it mutates the evidence
  snapshot and contradicts the "read-only baseline" invariant (and is incompatible with a `mode=ro`
  connection).

**Suggestions.**
- Add a runner helper for candidate capture that mirrors baseline capture: build Surreal vector + FTS
  engines, discard/avoid `graph_direct`, and call `fuse_results({"semantic": ..., "keyword": ...})`
  directly. Add a test asserting retained candidate rows have no `graph_direct` matched engine.
- Make the evaluator path explicit: write a filtered temporary golden-query JSONL and call
  `EvalRunnerConfig(..., require_complete_category_coverage=False)`, or add a shadow-run wrapper that
  does this internally. Update verify-only commands accordingly.
- Add a baseline immutability test: record `index.db` hash/mtime before
  `build_baseline_semantic_keyword_engines()` plus a search, then assert unchanged. To pass it, use
  read-only/search-only construction that skips FTS/schema/vector-table ensure logic and fails closed
  if required tables are absent or outdated.
- Replace "16-query quality evidence" wording with "16-query source corpus, 11-query non-graph
  comparison subset, 5 graph queries explicitly excluded" wherever it appears as a must-have.

**Risk Assessment — HIGH until the two semantic+FTS execution gaps are fixed.** The FalkorDB cycle-3
fix itself is sound, but the current plan can still either fail during evaluation because of category
coverage, or produce an unfair candidate comparison if Surreal `graph_direct` participates while
baseline graph is excluded. After those are pinned with tests and the read-only SQLite construction
issue is handled, risk drops to MEDIUM/LOW for a bounded evidence phase.

---

## OpenCode Review

**Summary.** After three review cycles, the Phase 43 plans are in a mature state. The cycle-3 HIGH fix
(D43-02-I) holds against source: `SemanticSearchEngine` + `FTS5SearchEngine` can be constructed directly
over a rehearsal `index.db` without touching `DotMDService`, `IndexingPipeline`, or `FalkorDBGraphStore`,
and therefore without opening a FalkorDB connection or issuing `CREATE INDEX` writes. The filter criterion
for graph-excluded golden queries (`sq-004/009/010/015/016`) is deterministic and verifiable. The
remaining concerns are minor implementation-level gaps.

**Cycle-3 HIGH fix verdict — HOLDS.** Source-grounded trace confirmed:
`DotMDService.__init__ → IndexingPipeline → _create_graph_store() → FalkorDBGraphStore` connects +
issues `CREATE INDEX` for 5 labels; `SemanticSearchEngine` needs only `VectorStoreProtocol` + config;
`FTS5SearchEngine` needs only a `sqlite3.Connection` + table_name; `SQLiteVecVectorStore` accepts a
shared `conn`; `_model_to_table_suffix` is importable from `pipeline.py` (already done by `migration.py`);
`fuse_results` is a pure function; `Settings.model_copy(update={"index_dir": ...})` redirects
`index_db_path` while carrying `falkordb_url` through unchanged; `SearchMode` enum has no combined value.
Invariant holds by construction.

**Strengths.**
- Defense in depth on rehearsal isolation (production-dir overlap refusal, symlink rejection,
  `PRAGMA integrity_check`) plus fail-closed identity comparison (D43-02-B/C/J).
- Input/output artifact split (D43-02-K) closes the "validate against an artifact you later rewrite" gap.
- Sentinel-stripping with four named test cases (D43-02-F).
- Candidate-config schema is fail-closed with engine-vs-loop field routing (D43-02-H).
- Memory guardrails with slack fallback and zero-baseline rejection (D43-01-A/B).
- `--verify-only` regeneration catches hand-edited classifications (D43-03-C).

**Concerns.**
- **MEDIUM / NEW — Fused-pool-to-EvalResult conversion pathway for baseline capture is implied but not
  specified.** `collect_semantic_keyword_pool` returns `fuse_results` output (ref, score tuples), and
  `capture_eval_results_from_candidates` converts `SearchCandidate` objects. The intermediate step —
  converting fused chunk IDs into `SearchCandidate` objects (requiring metadata lookup via
  `SQLiteMetadataStore` or direct SQL on the rehearsal `index.db`) — is not an exported function or
  explicit step. `SQLiteMetadataStore(conn=.., table_name=.., fts_table_name=..)` (`pipeline.py:227-231`)
  is importable and constructable independently, but the plan's exports list doesn't include it. An
  implementer would need to figure it out.
- **LOW / NEW — `--verify-only` regeneration sensitivity to eval-code changes.** Re-running `run_eval()`
  to regenerate `shadow-diffs.jsonl` and comparing against disk will also flag legitimate re-evaluation
  differences if the eval/rrf/reranker code changed between capture and verify. A code change is
  indistinguishable from tampering. Worth documenting in the runbook.
- **LOW / NEW — TEI availability for baseline capture is not explicitly pre-flighted.** Baseline capture
  runs `SemanticSearchEngine.search()` which triggers lazy TEI initialization. If TEI is down, the runner
  fails at search time rather than failing fast. The runbook could note this as a requirement.

**RESIDUAL — none.** All prior-cycle concerns are incorporated into explicit decisions/tasks/criteria
(cycle-3 HIGH FalkorDB boundary → D43-02-I; cycle-2 HIGH graph binding → D43-02-G/D43-03-E; candidate-
config schema → D43-02-H; preflight identity → D43-03-D; source-capture in/out split → D43-02-K;
rehearsal identity fail-closed → D43-02-J; verify-only regeneration → D43-03-C; privacy policy → runbook
"Artifact Handling"; division by zero → D43-01-A; getrusage platform note → D43-01-C docstring).

**Suggestions.**
1. Add metadata-store construction to 43-02 exports, or document the fused-pool→candidate pathway
   (`SQLiteMetadataStore(conn=conn, table_name=chunks_table, fts_table_name=fts_table)`).
2. Document `--verify-only` eval-code sensitivity in the runbook (capture and verify should use the same
   commit).
3. Add "TEI must be running" to the rehearsal-path contract in the runbook.
4. (Optional) Store a SHA-256 of `shadow-diffs.jsonl` at capture time in `source-capture.json` and have
   verify-only compare the hash, avoiding eval-code-change sensitivity.

**Risk Assessment — LOW.** The cycle-3 HIGH fix is source-confirmed sound. All prior-cycle concerns are
genuinely resolved with test coverage. The new concerns are implementation-level gaps that do not
threaten the phase goal or introduce cutover risk. "The plans are ready for execution."

---

## Consensus Summary

### Agreed Strengths
- The cycle-3 HIGH (baseline `DotMDService` construction crossing the live FalkorDB boundary) is
  resolved **by construction** via D43-02-I, not by a late `SearchMode` gate. Both reviewers
  independently traced the source and confirmed `SemanticSearchEngine` + `FTS5SearchEngine` can be
  built and run without ever constructing `DotMDService`/`IndexingPipeline`/`FalkorDBGraphStore`.
- Input/output manifest split (D43-02-K), fail-closed rehearsal identity (D43-02-J), preflight
  identity binding (D43-03-D), sentinel-stripping (D43-02-F), and `--verify-only` regenerate-and-compare
  tamper detection (D43-03-C) are all sound.

### Agreed Concerns
- Both reviewers agree there is no unresolved residual from cycles 1-3 — every prior-cycle concern is
  incorporated into an explicit PLAN.md decision/task/criteria.
- Both reviewers note the same underlying theme from different angles: the "semantic+FTS-only"
  comparison is asserted but the **mechanics of making it executable and symmetric are under-specified**
  (OpenCode flags the missing fused-pool→EvalResult hydration step; Codex flags that the candidate side
  still includes `graph_direct` and that the Phase 40 evaluator's category-coverage gate rejects the
  filtered corpus).

### Divergent Views
- **Severity of the candidate-side `graph_direct` / category-coverage issues.** Codex rates these
  HIGH and rates overall risk HIGH until fixed; OpenCode does not surface them at all (its candidate-
  side analysis stopped at the baseline boundary) and rates overall risk LOW. The source check in this
  review (see Verification coverage) confirms **Codex is correct on both points**:
  `build_surreal_native_engine_overrides()` returns a `graph_direct` engine
  (`surreal_native.py:44-45`), and `run_eval()` defaults to `require_complete_category_coverage=True`
  with `required_golden_query_categories() == frozenset(GoldenQueryCategory)` (all 8 categories,
  `surreal_eval.py:34-53`), so the 11-query filtered subset — which drops the entire `graph-entity` AND
  `mixed-ru-en` categories — would fail coverage validation unless the runner explicitly disables it.
  These two are therefore counted as the cycle-4 unresolved HIGHs.

---

## Verification coverage (source-grounding pass)

Every concrete symbol the plans cite was checked against the live dotMD source. Artifacts the plans
declare under "Artifacts This Phase Produces" (e.g. `surreal_shadow_metrics.py`, `surreal_shadow_runner.py`,
`source-capture-expected.json`, `source-capture.json`) are excluded from MISSING verdicts — they are
outputs of this phase, not pre-existing dependencies.

| Symbol / claim cited by plan | Location verified | Verdict |
|------------------------------|-------------------|---------|
| `DotMDService.__init__` constructs `IndexingPipeline` first | `api/service.py:261-264` | VERIFIED |
| `IndexingPipeline.__init__` calls `_create_graph_store(settings)` | `ingestion/pipeline.py:246` | VERIFIED |
| `_create_graph_store` constructs `FalkorDBGraphStore(url=falkordb_url, graph_name="dotmd")` | `ingestion/pipeline.py:161` | VERIFIED |
| `FalkorDBGraphStore.__init__` connects + issues `CREATE INDEX` for File/Section/Entity/Tag/Node at construction | `storage/falkordb_graph.py:47-63` | VERIFIED |
| `SemanticSearchEngine.__init__(vector_store, model_name, score_floor, embedding_url, tei_batch_size, use_prefix, query_instruction)`, no graph dep | `search/semantic.py:51-70` | VERIFIED |
| `FTS5SearchEngine.__init__(conn, table_name)`, no graph dep | `search/fts5.py:93-96` | VERIFIED |
| `SQLiteVecVectorStore.__init__` accepts shared `conn=` and `table_name=` | `storage/sqlite_vec.py:45` | VERIFIED |
| `fuse_results(ranked_lists, k=60, engine_weights=None)` pure function | `search/fusion.py:189` | VERIFIED |
| `_collect_candidate_pool` fuses `{"semantic","keyword","graph_direct"}` via `fuse_results(engine_results, k=fusion_k)` | `api/service.py:~1373-1407` | VERIFIED |
| `SearchMode` enum = SEMANTIC/KEYWORD/GRAPH/HYBRID (no combined value) | `core/models.py:20-26` | VERIFIED |
| `_model_to_table_suffix`, `chunks_fts_{strategy}`, `vec_chunks_{strategy}{suffix}` derivation | `ingestion/pipeline.py:139,221,222` | VERIFIED (suffix fn is module-level importable; the `chunks_fts_`/`vec_chunks_` string assembly lives inside `IndexingPipeline.__init__`, not a standalone reusable function — executor must replicate ~2 lines) |
| `build_surreal_native_engine_overrides(connection, settings, *, embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` accepts ONLY those two tuning params | `search/surreal_native.py:18-23` | VERIFIED (supports D43-02-H field routing) |
| ...but it RETURNS `{"semantic","keyword","graph_direct"}` — candidate side includes a graph engine | `search/surreal_native.py:27-45` | VERIFIED — contradicts the plan's "semantic+FTS-only" symmetry claim for the candidate side (basis of Codex HIGH #1) |
| `DEFAULT_HNSW_EF` import source | `search/surreal_native.py:11` (`storage/surreal_schema`) | VERIFIED |
| `evaluate_surreal_scale_gate` field names (`passed`, `failure_category`, `recommendation_gate`, ...) | `search/surreal_parity.py:41,50,68,91` | VERIFIED |
| `run_eval(EvalRunnerConfig)` exists | `devtools/surreal_eval_runner.py:151` + `:27` | VERIFIED |
| `EvalRunnerConfig.require_complete_category_coverage: bool = True`, enforced in run_eval | `devtools/surreal_eval_runner.py:36,155` | VERIFIED — basis of Codex HIGH #2 |
| `required_golden_query_categories() == frozenset(GoldenQueryCategory)` (all 8 categories); coverage validator raises on missing | `search/surreal_eval.py:34-53` | VERIFIED |
| `GoldenQueryCategory` includes GRAPH_ENTITY and MIXED_RU_EN | `search/surreal_eval.py:21-31` | VERIFIED |
| Excluding `sq-004/009/010/015/016` by (`expected_engines` has `graph_direct` OR `primary_surface==graph_entity`) yields exactly those 5, retains 11 incl. `sq-011/012` | `devtools/surreal_golden_queries.jsonl` (empirical) | VERIFIED — but ALSO drops the entire `graph-entity` AND `mixed-ru-en` categories (both `mixed-ru-en` rows are `sq-015/016`); the plan does not acknowledge the `mixed-ru-en` collateral loss |
| Golden-query rows are keyed by field `id` (`sq-001`..`sq-016`), NOT `query_id` | `devtools/surreal_golden_queries.jsonl` | AMBIGUOUS — deciding fields the filter uses (`expected_engines`, `primary_surface`) are correct & present; the plan repeatedly says "golden query `query_id`" but the golden file's identifier field is `id` (the `query_id` name is the `EvalResult`/ledger field; the existing runner maps golden→EvalResult). Cosmetic naming nuance, not a logic error |
| `load_eval_results(path)` exists (used for validity check, not just non-empty) | `search/surreal_eval.py:311` | VERIFIED |
| `EvalResult`/`DiffAcceptance` use `query_id`/`accepted_by`/`accepted_reason` | `search/surreal_eval.py:73-103` | VERIFIED |
| `FTS5SearchEngine.__init__ → _ensure_fts5_schema()` runs `DROP TABLE`/`CREATE`+`commit()` at construction | `search/fts5.py:98-...` | VERIFIED — basis of Codex MEDIUM (read-only invariant broken; incompatible with `mode=ro` connection) |
| `SQLiteVecVectorStore._get_conn → _ensure_tables()` runs `CREATE TABLE IF NOT EXISTS` on first use | `storage/sqlite_vec.py:67-...` | VERIFIED — reinforces the read-only-invariant concern |
| `SQLiteMetadataStore(conn, table_name, fts_table_name)` constructable independently (fused-id→candidate hydration) | `storage/metadata.py:317`, `ingestion/pipeline.py:227-231` | VERIFIED — but NOT in the 43-02 exports list / not an explicit step (basis of OpenCode MEDIUM) |
| `RUNTIME_INDEX_DIR = Path("/dotmd-index")` | `core/config.py:40` | VERIFIED |
| `falkordb_url` setting | `core/config.py:208` | VERIFIED |
| `validate_for_runtime()` rejects non-`/dotmd-index` index_dir (so runner must NOT call it on clone) | `core/config.py:333-343` | VERIFIED |
| `Settings.index_db_path == index_dir / "index.db"` | `core/config.py:406-408` | VERIFIED |
| `Settings(BaseSettings)` → `model_copy(update=...)` available (pydantic-settings) | `core/config.py:7,55` | VERIFIED |
| `needs_embedding_prefix`, `query_instruction`, `semantic_score_floor`, `fusion_k`, `chunk_strategy`, `embedding_model` settings | `core/config.py:381,390,190,188,102` | VERIFIED |
| `sqlite_vec.load(conn)` encapsulated in `SQLiteVecVectorStore` | `storage/sqlite_vec.py:75-77` | VERIFIED |
| read_first test/devtool fixtures exist (`test_surreal_eval_runner.py`, `test_surreal_migration_runner.py`, `surreal_migration_runner.py`) | `backend/tests/devtools/`, `backend/devtools/` | VERIFIED |

**Coverage result:** No MISSING symbols. One AMBIGUOUS naming nuance (`id` vs `query_id` on golden rows;
cosmetic). The cycle-3 HIGH fix (graph-free baseline construction) is VERIFIED sound. Three new
source-confirmed gaps were surfaced: two HIGH (candidate-side `graph_direct` asymmetry; Phase 40
category-coverage gate vs filtered subset) and supporting MEDIUMs (read-only invariant broken by FTS5/vec
construction; missing fused-pool→candidate hydration step).

---

## Cycle-4 disposition (counts for the convergence loop)

- **Unresolved HIGH (current_high = 2):**
  1. Candidate capture is not graph-free — `build_surreal_native_engine_overrides()` returns a
     `graph_direct` engine, so retained queries get candidate-side graph hits while the baseline is
     graph-free, making the "semantic+FTS-only" comparison asymmetric/unfair. No PLAN.md decision strips
     the candidate `graph_direct` engine. (Source-confirmed: `surreal_native.py:27-45`.)
  2. The non-graph filtered golden subset (11 queries) collides with the Phase 40 evaluator's
     `require_complete_category_coverage=True` default, which requires all 8 categories; the filtered
     subset is missing `graph-entity` AND `mixed-ru-en`, so `run_eval()` raises unless the runner sets
     `require_complete_category_coverage=False` (or writes a filtered temp corpus + disables coverage).
     No PLAN.md decision reconciles this; 43-03 verify-only commands still point at the full corpus.
     (Source-confirmed: `surreal_eval_runner.py:36,155`; `surreal_eval.py:34-53`.)

- **Unresolved actionable non-HIGH (current_actionable = 2):**
  1. MEDIUM — Read-only baseline invariant is broken by the chosen construction path:
     `FTS5SearchEngine.__init__ → _ensure_fts5_schema()` writes (`DROP`/`CREATE`+`commit`) and
     `SQLiteVecVectorStore` ensures tables on first use, so the rehearsal snapshot is mutated and a
     `mode=ro` connection is impossible. PLAN.md (D43-02-I and `test_build_baseline_engines_has_no_falkordb_side_effects`)
     must add a read-only/search-only construction path (or drop the "writes no file"/read-only wording)
     and pin a baseline-immutability test.
  2. MEDIUM — The fused-pool→`EvalResult` hydration step is unspecified: `collect_semantic_keyword_pool`
     returns ref/score tuples but `capture_eval_results_from_candidates` consumes `SearchCandidate`
     objects. PLAN.md 43-02 should export/document the hydration step
     (`SQLiteMetadataStore(conn, table_name, fts_table_name)`) so the executor does not have to infer it.

  (LOW items — verify-only eval-code sensitivity, TEI pre-flight, `mixed-ru-en` collateral-loss wording,
  golden `id` vs `query_id` naming — are non-blocking suggestions for the runbook/wording; not counted
  as actionable blockers.)
