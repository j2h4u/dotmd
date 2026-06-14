---
phase: 43
cycle: 2
reviewers: [codex, opencode]
reviewed_at: 2026-06-14T18:05:00Z
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commit: 1d1cb22
---

# Cross-AI Plan Review — Phase 43 (Cycle 2)

This is the **second** review cycle. The plans were revised in commit `1d1cb22` to
address the cycle-1 findings (3 HIGH + 4 actionable non-HIGH). This cycle re-reviews
the **current** state of the plans. Concerns that cycle 1 raised and the plans now
incorporate via explicit `D43-xx` decisions are recorded as RESOLVED and are **not**
re-counted as open. The previous cycle-1 review content has been superseded by this file.

## Codex Review

**Summary**

The cycle-2 revisions substantially improve the plans. The biggest cycle-1 gaps now have
explicit decisions, tests, and verification hooks: paired memory metrics, sentinel
stripping, baseline path isolation, reduced flag surface, replay descriptor typing, and
candidate-target preflight. The plans are close to executable. The main remaining issue is
new (or newly visible): `Settings.model_copy(update={"index_dir": ...})` binds
SQLite/FTS/sqlite-vec to the rehearsal copy, but it does **not** bind the FalkorDB graph
backend to the same evidence window. Since dotMD's old stack includes graph retrieval,
baseline evidence may still read a live or unrelated graph while SQLite comes from the
rehearsal snapshot.

**Cycle-1 Concern Disposition**

| Concern | Disposition | Notes |
|---|---|---|
| Sentinel rows could reach Phase 40 acceptance loader | RESOLVED | D43-02-F adds explicit stripping plus four named tests (sentinel-only, sentinel+acceptance, acceptance-only, malformed). |
| Baseline capture mechanics underspecified | PARTIALLY RESOLVED | D43-02-A makes the SQLite binding concrete with `Settings.model_copy(index_dir=...)` and a fresh `DotMDService`. Still incomplete for FalkorDB graph state. |
| Rehearsal-path isolation was aspirational | PARTIALLY RESOLVED | D43-02-B/C add production-dir overlap refusal, symlink rejection, read-only `PRAGMA integrity_check`. Still SQLite-only; does not prove graph snapshot alignment. |
| Phase 41 Surreal target prerequisite unvalidated | RESOLVED (with caveat) | D43-03-A adds an automated preflight before capture. It should also bind the target to the expected manifest/import identity (see remaining concerns). |
| Memory guardrail comparison baseline undefined | RESOLVED | D43-01-A requires paired baseline+candidate memory payloads and defines ratio plus slack evaluation. |
| Guardrail constants arbitrary | RESOLVED | D43-01-B documents the `1.25` ratios and slack rationale as first-cutover tolerances. |
| `capture_shadow_memory_metrics` placement / silent zero heap | RESOLVED | D43-01-C marks it optional and requires `tracemalloc.start()`/`stop()` with a nonzero test. |
| 43-02 scope / flag creep | RESOLVED ENOUGH | D43-02-D folds tuning knobs into `--candidate-config-json`. Runner remains large but scope is now testable. |
| `--metrics-replay-queries` ambiguous | RESOLVED | D43-02-E pins it to a `Path` JSONL descriptor with strict validation. |
| `test -s` validity checks too weak | RESOLVED | D43-03-B adds JSON parsing, `load_eval_results()`, query-id matching, and rehearsal isolation checks. |
| Critical acceptance rules buried in prose | RESOLVED | D43-03-C promotes acceptance reason and no raw diff editing to verification/success criteria. |
| Artifact privacy / redaction policy | PARTIALLY RESOLVED | 43-02 docs mention production-derived refs/snippets and intentional path/redaction choices, but no concrete export/commit policy is specified. |

**Remaining / New Concerns**

- **HIGH — Baseline graph state is not bound to the rehearsal window.** D43-02-A correctly
  redirects `Settings.index_dir`, which covers `index.db`, FTS5, and sqlite-vec. But
  `DotMDService` also constructs graph engines from the configured graph backend. In
  production that is FalkorDB, controlled by `falkordb_url` / graph config, not `index_dir`.
  The plan's claim that the "entire old stack" is pointed at the copied snapshot is therefore
  incomplete. Hybrid/graph baseline results could read live FalkorDB state while semantic/FTS
  reads the rehearsal SQLite copy.

- **MEDIUM — Candidate preflight can pass against the wrong or stale Surreal target.** D43-03-A
  checks reachability and nonzero imported records, which closes the original "target missing"
  blocker. It does not require the candidate target to match the source-capture manifest, chunk
  strategy, embedding model, import id, or expected record counts. A stale namespace/database
  with records could pass.

- **MEDIUM — WAL/snapshot completeness is under-validated.** D43-02-C defines a valid rehearsal
  path as a regular `index.db` that passes `PRAGMA integrity_check`. That proves the SQLite file
  is readable, not necessarily that the copy includes the intended WAL/checkpoint state or is
  recent enough for the source-capture window. The runner does not appear to record or validate
  backup method, timestamp, expected counts, or WAL handling.

- **LOW — `candidate-config.json` schema needs explicit fail-closed validation.** D43-02-D names
  the fields but the plan should require positive-integer/type validation and reject
  unknown/missing fields to prevent quietly running with malformed target-derived tuning.

- **LOW — Privacy policy is still warning-level, not operational.** Add a concrete policy: where
  artifacts may live, whether they are committed, and whether snippets are redacted or
  manifest-marked before export.

**Suggestions**

1. Add a `D43-02-G` baseline graph contract: either require a copied/isolated FalkorDB graph
   target matching the rehearsal manifest, or explicitly disable graph engines for the quality
   comparison and state that Phase 43 is semantic+FTS only. The first option is more faithful to
   the phase goal.
2. Extend source/candidate manifest validation: compare chunk strategy, embedding model,
   source-capture id, imported chunk/entity counts, and target namespace/database against expected
   metadata.
3. Add rehearsal snapshot metadata to `source-capture.json`: backup method, captured_at, expected
   `index.db` size, optional WAL/checkpoint status, record counts, and graph target identity if
   graph is included.
4. Make `load_candidate_config()` strict: required keys, positive integer ranges, no unknown keys.
5. Add a short artifact-handling section ("local only unless redacted", or "do not commit raw
   snippets").

**Risk Assessment:** MEDIUM-HIGH until the baseline graph contract is fixed; MEDIUM after that.
The revised plans resolve the original review's main control-flow and validation issues, and the
dependency order is sound. The remaining graph-state issue is material because the phase goal is
old-stack vs Surreal-stack quality on production-derived data, and the old stack is not just
SQLite/FTS/sqlite-vec.

---

## OpenCode Review

## 1. Summary

The revised plans are substantially improved. The cycle-1 consensus HIGHs (rehearsal-path binding
and isolation) are now addressed with concrete mechanisms: `Settings.model_copy` clone + fresh
`DotMDService` (D43-02-A), production-dir refusal + symlink rejection + `PRAGMA integrity_check`
(D43-02-B/C). Sentinel stripping is pinned by four named tests (D43-02-F). Memory guardrails now
require paired baseline+candidate payloads with ratio-and-slack semantics (D43-01-A). The Phase 41
target pre-flight automates what was a manual gate (D43-03-A). Flag surface is reduced by folding
four tuning knobs into `--candidate-config-json` (D43-02-D). One significant gap remains
unaddressed: the graph-store isolation problem.

## 2. Cycle-1 Concern Disposition

| # | Concern | Severity | Disposition | Plan Decision |
|---|---------|----------|-------------|---------------|
| 1 | Sentinel stripping needs explicit tests | HIGH | RESOLVED | D43-02-F: four named tests, sentinel never reaches Phase 40 loader |
| 2 | Baseline capture mechanics underspecified | HIGH | RESOLVED (SQLite) | D43-02-A: `Settings.model_copy(update={"index_dir": ...})` → fresh `DotMDService` |
| 3 | Rehearsal path isolation underspecified | HIGH | RESOLVED (SQLite) | D43-02-B/C: production-dir overlap refusal, symlink rejection, `PRAGMA integrity_check` |
| 4 | `DotMDService` instantiation for baseline unexplored | HIGH | RESOLVED | D43-02-A + `test_build_baseline_service_uses_model_copy_index_dir_clone` |
| 5 | 43-02 too large | MEDIUM | RESOLVED as designed | D43-02-D: flag reduction over plan split |
| 6 | Memory guardrail comparison baseline undefined | MEDIUM | RESOLVED | D43-01-A: paired payloads; ratio-and-slack rule |
| 7 | `ShadowMetricBundle` & scale-gate raw fields mismatch | MEDIUM | RESOLVED | 43-01 task lists exact return fields from `evaluate_surreal_scale_gate()` |
| 8 | 43-03 Tasks 1-2 `auto` but `autonomous: false` | MEDIUM | PARTIALLY RESOLVED | Input descriptors + pre-flight listed; tasks remain `auto` (arguably correct for automated capture) |
| 9 | Arbitrary guardrail constants undocumented | MEDIUM | RESOLVED | D43-01-B: rationale in `ShadowMemoryGuardrails` docstring |
| 10 | `capture_shadow_memory_metrics` conflates capture/definition | MEDIUM | RESOLVED | D43-01-C: helper optional; runner authoritative |
| 11 | `tracemalloc` needs `tracemalloc.start()` | LOW | RESOLVED | D43-01-C + `test_capture_starts_tracemalloc_so_heap_is_nonzero` |
| 12 | Parent-directory creation in writer | LOW | RESOLVED | 43-01 Task 2: `write_shadow_metric_json` creates parent dirs |
| 13 | 27 CLI flags scope creep | MEDIUM | RESOLVED | D43-02-D: four flags folded into `--candidate-config-json` |
| 14 | `capture_eval_results_from_candidates` may reimplement logic | MEDIUM | RESOLVED | Task 2: pure field mapping, no new searches |
| 15 | Sentinel filtering test cases needed | MEDIUM | RESOLVED | D43-02-F (same as #1) |
| 16 | `--metrics-replay-queries` ambiguous type | MEDIUM | RESOLVED | D43-02-E: `type=Path` JSONL |
| 17 | `ShadowArtifactPaths` omitted from exports | LOW | RESOLVED | Now present in 43-02 exports list |
| 18 | Negative-space scope-guard tests brittle | LOW | RESOLVED | Task 1: behavioral side-effect assertions preferred |
| 19 | Phase 41 Surreal target prerequisite unvalidated | HIGH | RESOLVED | D43-03-A: automated `--preflight-candidate-target` smoke |

## 3. Remaining / New Concerns

**NEW — HIGH: Graph store not covered by rehearsal path contract.**
`_create_graph_store()` in `pipeline.py:161` creates a `FalkorDBGraphStore` pointed at
`settings.falkordb_url` — a live Redis container. The rehearsal-path contract (D43-02-C) requires
only an `index.db` copy, but graph data lives externally in FalkorDB. When `build_baseline_service`
constructs a `DotMDService` from cloned settings, the graph engines still connect to the **live**
FalkorDB container (or crash if rehearsal settings lack a FalkorDB URL). This breaks the "isolated
snapshot" guarantee for graph-category golden queries (graph/entity, hybrid). Either (a) the
rehearsal contract must include a FalkorDB dump/restore, (b) baseline capture must explicitly
disable graph engines, or (c) a plan decision must acknowledge that graph data is assumed read-only
for the bounded window and the isolation gap is accepted.

**NEW — MEDIUM: `--candidate-config-json` shape underspecified.**
D43-02-D folds four fields into one JSON descriptor, but the exact field names, types, and
required-vs-optional status are not specified. `build_surreal_native_engine_overrides()` at
`surreal_native.py:18` accepts only `embedding_dimension` (int) and `hnsw_ef` (int) — it does
**not** accept `top_k` or `pool_size`. Those two go to the capture loop, not engine construction.
The plan conflates them. Need an explicit field list distinguishing which fields feed
`build_surreal_native_engine_overrides()` and which feed the capture search loop.

**NEW — MEDIUM: `DotMDService` constructor side effect (`TrickleIndexer` created, not started).**
`DotMDService.__init__` at `service.py:295` unconditionally creates `TrickleIndexer(...)`. The
constructor is lightweight (no lock, no writes), but the plan should explicitly verify the cloned
service does not trigger side effects (opening connections, migration checks, directory creation).
A behavioral test or explicit comment in the runner would close this.

**NEW — LOW: Division by zero in memory guardrail ratios.**
D43-01-A computes `candidate.max_rss_bytes / baseline.max_rss_bytes`. If `baseline.max_rss_bytes`
is 0 (malformed, empty run, or test fixture), this raises `ZeroDivisionError` and bypasses the
ratio-and-slack rule. The plan should specify a guard (treat zero baseline as slack-pass or raise a
descriptive `ValueError` naming the zero field).

**NEW — LOW: No explicit stop-condition artifact path for D43-03-A failures.**
D43-03-A says "STOP and record the exact missing input in a stop-condition note" but does not
specify a file path. A concrete path (e.g., `artifacts/preflight-failure.md`) would make the stop
condition discoverable and verifiable in 43-03's `verify` step.

**REMAINING — LOW: `resource.getrusage` platform note.**
`resource.getrusage` raises `ValueError` on some platforms for unsupported `who`. Linux-only in
practice, but worth a docstring note.

## 4. Suggestions

- **Graph isolation:** Add `D43-02-G` acknowledging the rehearsal `index.db` does not snapshot
  graph data in FalkorDB; either require a `--baseline-graph-dump` flag for FalkorDB
  export/restore, or explicitly disable `graph_direct`/`graph` engines during baseline capture and
  exclude graph-category golden queries with a documented warning.
- **candidate-config-json:** Specify the schema, e.g.
  `{"embedding_dimension": int, "hnsw_ef": int, "top_k": int, "pool_size": int}` with
  `embedding_dimension` required and `hnsw_ef` defaulting to `DEFAULT_HNSW_EF`. Document that
  `top_k`/`pool_size` go to the search capture loop, not `build_surreal_native_engine_overrides()`.
- **Zero-division:** Add a guard in D43-01-A for a zero baseline field.
- **Stop-condition path:** Pin pre-flight failure output to `artifacts/preflight-failure.md` and
  add it to 43-03's verification commands.
- **Runner construction side effects:** State in Task 2 that `DotMDService(settings=cloned)` must
  not acquire locks, open network connections (besides the graph URL), or trigger migrations,
  verified by a `test_build_baseline_service_has_no_side_effects`.

## 5. Risk Assessment

**MEDIUM.** The cycle-1 consensus HIGHs are well-addressed. The dominant remaining gap is the
graph-store isolation problem — the rehearsal-path contract treats `index.db` as the full baseline
snapshot, but graph data lives in FalkorDB and is not snapshot-captured. For a production
deployment running FalkorDB (the stated default), baseline capture will either read live graph
results (breaking isolation) or fail to access graph data (breaking query completeness). All other
concerns are MEDIUM or LOW and resolvable in-plan.

---

## Consensus Summary

Both reviewers agree the cycle-2 revisions **resolve all three cycle-1 HIGHs** (sentinel stripping
→ D43-02-F; baseline-capture mechanics / rehearsal isolation → D43-02-A/B/C; Phase 41 target
preflight → D43-03-A) and all four actionable cycle-1 non-HIGH items (memory guardrail baseline →
D43-01-A/B; flag creep → D43-02-D; replay-descriptor typing → D43-02-E; validity-vs-non-emptiness →
D43-03-B; buried acceptance rules → D43-03-C; tracemalloc start → D43-01-C). No redesign required.

Both reviewers then **independently raise the same single new HIGH**: the baseline rehearsal
contract isolates only the SQLite side (`index.db` via `index_dir`) and leaves the FalkorDB graph
backend bound to the live container, because graph configuration flows through `falkordb_url`, not
`index_dir`. This is source-confirmed: `pipeline.py:161 _create_graph_store()` →
`FalkorDBGraphStore(url=settings.falkordb_url)`. Baseline graph/hybrid golden queries would either
read live graph state (breaking the "isolated snapshot" guarantee) or fail if the clone lacks a
graph URL.

### Agreed Strengths
- Cycle-1 HIGHs fully closed with concrete, testable decisions (both).
- Correct dependency ordering 43-01 → 43-02 → 43-03; no cycles (both).
- Reuse of real Phase 40/42 seams confirmed against source (both).
- Fail-closed validation, paired memory guardrails, sentinel stripping all pinned by named tests (both).

### Agreed Concerns (highest priority)
- **HIGH — Baseline graph state not bound to the rehearsal window (43-02).** Both reviewers,
  independently, source-grounded in `pipeline.py:161` + `config.py:208 falkordb_url`. The dominant
  shared new HIGH. Remedy: add a `D43-02-G` decision that either (a) snapshots/isolates the FalkorDB
  graph for the same window, or (b) explicitly disables graph engines for baseline capture and
  documents Phase 43 as semantic+FTS-only with graph-category queries excluded.

### Divergent / Single-Reviewer Concerns
- **MEDIUM — Candidate preflight identity binding (Codex only):** preflight checks reachability +
  nonzero records but not manifest/chunk-strategy/embedding-model/import-id match. A stale target
  could pass.
- **MEDIUM — `--candidate-config-json` schema underspecified (OpenCode only, source-confirmed):**
  `build_surreal_native_engine_overrides()` accepts only `embedding_dimension`/`hnsw_ef`;
  `top_k`/`pool_size` are capture-loop inputs. D43-02-D conflates the two routes and gives no field
  schema or fail-closed validation.
- **MEDIUM — WAL/snapshot completeness under-validated (Codex only):** integrity_check proves
  readability, not that the copy captured the intended WAL/checkpoint state or is recent enough.
- **LOW — Zero-division guard in memory ratios (OpenCode only).**
- **LOW — Stop-condition artifact path for preflight failures unspecified (OpenCode only).**
- **LOW — Operational (not warning-level) artifact privacy/redaction policy (Codex only).**

---

## Verification coverage

Source-grounding pass over every non-produced symbol/file the revised plans cite. Artifacts the
plans declare under "Artifacts This Phase Produces" (the new metric module, the runner, the runbook,
and the eight `artifacts/*` files plus the two operator-supplied input descriptors) are excluded
from MISSING verdicts. New cycle-2 citations introduced by the revised decisions
(`Settings.model_copy`, `index_dir`, `index_db_path`, `RUNTIME_INDEX_DIR`, `validate_for_runtime`,
`load_settings`, `chunk_strategy`, `DotMDService(settings=...)`, `falkordb_url`) were checked in
addition to the cycle-1 set.

| Cited symbol / file | Plan ref | Verdict | Evidence |
|---|---|---|---|
| `evaluate_surreal_scale_gate()` | 43-01 key_links | VERIFIED | `backend/src/dotmd/search/surreal_parity.py:435` |
| Scale-gate fields `failure_category`,`recommendation_gate`,`record_counts`,`hnsw_build_seconds`,`surrealkv_file_size_bytes`,`query_latency_p50_ms`,`query_latency_p95_ms`,`representative`,`passed`,`missing` | 43-01 behavior | VERIFIED | `surreal_parity.py:437-490` (all present; `representative` at 441/461-462) |
| `run_eval` + `EvalRunnerConfig` + `EvalRunResult` | 43-02 key_links | VERIFIED | `backend/devtools/surreal_eval_runner.py:27,40,151` |
| `build_surreal_native_engine_overrides()` | 43-02/43-03 key_links | VERIFIED | `backend/src/dotmd/search/surreal_native.py:18` (signature accepts only `embedding_dimension`,`hnsw_ef` — basis for the MEDIUM concern that D43-02-D over-claims four engine params) |
| `EvalResult` + `top_refs`,`matched_engines`,`query_id` | 43-02/43-03 | VERIFIED | `backend/src/dotmd/search/surreal_eval.py:73,80,81,76` |
| Acceptance fields `query_id`,`accepted_by`,`accepted_reason` + `DiffAcceptance` handling | 43-02/43-03 | VERIFIED | `surreal_eval.py:91-93,112-113,516-530` |
| `load_eval_results()` | 43-02/43-03 verify | VERIFIED | `surreal_eval.py:311` |
| `Settings` class + `index_dir` + `index_db_path` | 43-02 D43-02-A | VERIFIED | `core/config.py:55,72,406-408` (`index_db_path = index_dir / "index.db"`) |
| `Settings.model_copy(update=...)` | 43-02 D43-02-A | VERIFIED | `Settings(BaseSettings)` (Pydantic v2) — `model_copy` is a BaseModel method |
| `RUNTIME_INDEX_DIR` (`/dotmd-index`) | 43-02 D43-02-B | VERIFIED | `core/config.py:40` |
| `Settings.validate_for_runtime()` (not called on clone) | 43-02 D43-02-A | VERIFIED | `core/config.py:333` (rejects non-`/dotmd-index` index_dir at 342-343) |
| `load_settings()` | 43-02 D43-02-A | VERIFIED | `core/config.py:415` |
| `chunk_strategy` (preflight smoke target) | 43-02/43-03 D43-03-A | VERIFIED | `core/config.py:102` |
| `DotMDService(settings=...)` constructor | 43-02 D43-02-A | VERIFIED | `api/service.py:247,260` (`__init__(self, settings: Settings | None = None)`) |
| `_collect_candidate_pool` (baseline search path) | 43-02 D43-02-A | VERIFIED | `api/service.py:1339` |
| `SearchCandidate` (capture conversion input) | 43-02 Task 2 | VERIFIED | `core/models.py:399` |
| `falkordb_url` graph config (basis of the HIGH concern) | not cited; concern source | VERIFIED | `core/config.py:208`; `_create_graph_store()` at `ingestion/pipeline.py:161` builds `FalkorDBGraphStore(url=settings.falkordb_url)` — graph backend is independent of `index_dir`, confirming the consensus HIGH |
| `backend/devtools/surreal_eval_runner.py` / `surreal_migration_runner.py` | 43-02 read_first | VERIFIED | both present |
| `backend/devtools/surreal_golden_queries.jsonl` (16 queries) | 43-02/43-03 | VERIFIED | present, 16 lines |
| `docs/surrealdb-evaluation-harness.md`, `docs/surrealdb-production-migration.md` | 43-02/43-03 read_first | VERIFIED | present in `docs/` |
| Test files `test_surreal_eval_runner.py`,`test_surreal_migration_runner.py`,`test_surreal_retrieval_parity.py` | 43-01/43-02 read_first | VERIFIED | present under `backend/tests/` |
| Phase summaries 40-01, 41-03, 42-04; 42-VERIFICATION | 43-0x context | VERIFIED | present under `.planning/phases/` |
| "builds config exactly like `surreal_migration_runner.py`" analogy | 43-02 D43-02-A prose | AMBIGUOUS | The migration runner operates on manifests/exports and does NOT construct a `DotMDService` via `load_settings()`/`model_copy`; the analogy is loose, but the concrete mechanism the decision specifies is independently grounded in real symbols (above), so this is a wording imprecision, not a missing symbol. |
| `surreal_shadow_metrics.py` + its symbols | produced by 43-01 | EXCLUDED (produced) | declared artifact |
| `surreal_shadow_runner.py` + symbols/flags, `docs/surrealdb-shadow-run-quality-gate.md` | produced by 43-02 | EXCLUDED (produced) | declared artifact |
| `artifacts/*.json(l)/.md` (8 outputs + `candidate-config.json`, `metrics-replay-queries.jsonl`) | produced by 43-03 | EXCLUDED (produced) | declared artifacts |

**Coverage result:** 24 VERIFIED, 0 MISSING, 1 AMBIGUOUS (a loose analogy in D43-02-A prose, not a
missing symbol), 0 UNCHECKABLE (3 produced-artifact groups correctly excluded). No plan cites a
non-existent upstream symbol; all reuse seams resolve to real source. The source-grounding pass also
**corroborates the consensus HIGH**: `index_dir` does not bind the FalkorDB graph backend
(`pipeline.py:161` + `config.py:208`), so D43-02-A's "entire old stack" claim is incomplete for the
graph dimension.
