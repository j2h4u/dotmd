---
phase: 43
cycle: 3
reviewers: [codex, opencode]
reviewed_at: 2026-06-14T19:10:50Z
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
prior_cycle_commit: 3122a59
---

# Cross-AI Plan Review — Phase 43 (Cycle 3, Final)

This is the **third and final** review cycle. The plans were revised in commit `3122a59`
to address the single cycle-2 consensus HIGH (baseline FalkorDB graph not bound to the
rehearsal window) plus two actionable cycle-2 MEDIUMs (candidate-config-json schema;
candidate-preflight identity binding) and the cycle-2 LOWs. This cycle re-reviews the
**current** state of the plans. Concerns that prior cycles raised and the plans now
incorporate via explicit `D43-xx` decisions are recorded as RESOLVED and are **not**
re-counted as open. The cycle-2 review file content has been superseded by this file.

The two reviewers DISAGREE on whether the cycle-2 HIGH is now resolved. The orchestrator
ran an independent source-grounding adjudication (recorded in "Orchestrator adjudication"
and "Verification coverage" below) and sides with Codex: the cycle-2 HIGH is **PARTIALLY
RESOLVED** at the comparison-policy level but **UNRESOLVED at the service-construction
boundary**, and therefore remains counted as 1 open HIGH.

## Codex Review

**Summary**

Cycle 3 is much stronger than cycle 2: the plans now explicitly acknowledge the FalkorDB
isolation problem, scope the comparison to semantic+FTS, exclude graph-category golden
queries, harden candidate config validation, bind candidate preflight to manifest identity,
and carry graph exclusion into final evidence. However, the cycle-2 HIGH is only
**partially resolved**. The query-level graph leak is addressed, but the proposed
`DotMDService(settings=cloned_settings)` baseline construction still initializes the
production graph store before any search mode is used.

**Cycle-2 HIGH Disposition — PARTIALLY RESOLVED.**

D43-02-G/D43-03-E correctly identify the root cause and choose a coherent scope:
semantic+FTS-only shadow evidence, graph-category query exclusion, and explicit exclusion
markers in `source-capture.json`, the ledger sentinel, and `shadow-summary.md`.

The remaining problem is implementation-level: `DotMDService.__init__` constructs
`IndexingPipeline`, and `IndexingPipeline` creates `FalkorDBGraphStore(url=settings.falkordb_url)`.
`FalkorDBGraphStore.__init__` establishes the FalkorDB client and creates indexes. So even
if `_collect_candidate_pool()` never runs graph search, baseline service construction still
crosses the live FalkorDB boundary. Also, the plan refers to a semantic+keyword-only
`SearchMode`, but the current enum has only `SEMANTIC`, `KEYWORD`, `GRAPH`, and `HYBRID`;
the combined modes include graph behavior.

**Strengths**

- D43-02-G is explicit about why `index_dir` cannot isolate FalkorDB.
- Graph-query exclusion is carried through 43-02 and 43-03 instead of being hidden in prose.
- D43-02-H fixes the candidate config ambiguity with a fail-closed schema and correct
  engine-vs-loop routing.
- D43-03-D materially improves candidate preflight by binding to chunk strategy, embedding
  model, import id, and counts.
- The acceptance ledger sentinel now carries guardrails, replay metadata, and
  graph-exclusion evidence.
- Privacy/artifact handling is now operational enough for execution.

**Concerns**

- **HIGH, REMAINING:** Baseline graph isolation is not fully resolved because
  `DotMDService(settings=...)` still initializes live FalkorDB through `IndexingPipeline`
  before graph-free search modes matter. This can read/write graph indexes or fail due to
  FalkorDB reachability even though graph evidence is excluded.
- **HIGH, NEW:** The planned "semantic+keyword-only `SearchMode`" does not exist. `SEMANTIC`
  and `KEYWORD` are separate; `HYBRID` and `GRAPH` invoke graph-direct. The plan needs an
  explicit graph-free fusion mechanism, not just a `SearchMode` restriction.
- **MEDIUM, REMAINING:** WAL/snapshot completeness is still only made visible, not
  fail-closed. Recording `index.db` size and mtime helps auditability, but it does not prove
  the rehearsal SQLite copy matches the same source-capture/import identity used for the
  candidate target.
- **MEDIUM, NEW:** `source-capture.json` is both an operator-supplied preflight input and a
  runner-produced/augmented output. That blurs immutable expected identity versus generated
  evidence. A bad implementation could validate against an artifact it later rewrites.
- **LOW, NEW:** The 43-03 preflight verification command shows `--target-url` but omits
  `--target-namespace` and `--target-database`, despite the plan requiring explicit target
  binding. If defaults exist, they should be stated; otherwise include the flags.

**Suggestions**

1. Change D43-02-G implementation to avoid constructing live FalkorDB at all. Options: inject
   a no-op graph store before `DotMDService`/`IndexingPipeline` construction, add a
   baseline-only service factory that builds only SQLite/FTS/vector engines, or bypass
   `DotMDService` and call semantic + FTS engines directly for this runner.
2. Define a real graph-free fusion path: e.g. `collect_semantic_keyword_pool()` that calls
   semantic and keyword engines and fuses with existing `fuse_results()`. Do not rely on a
   non-existent combined `SearchMode`.
3. Split immutable input from produced evidence: `source-capture-expected.json` or
   `candidate-source-manifest.json` for preflight identity, then generated `source-capture.json`
   can echo it with a hash plus graph-exclusion fields.
4. Make rehearsal snapshot identity fail-closed where possible: record and compare chunk
   counts, embedding row counts, chunk strategy, embedding model, and source manifest hash
   against the expected manifest before baseline capture.
5. If semantic+FTS-only is the chosen Phase 43 scope, update the phase goal/risk language to
   say graph retrieval is explicitly deferred from shadow quality gating, not merely excluded
   from a few queries.

**Risk Assessment — MEDIUM-HIGH** until the baseline construction path is corrected. The
plans are otherwise close to executable, and most cycle-2 issues are incorporated with good
tests and artifact checks. The remaining risk is concentrated: graph isolation is solved at
the comparison-policy level, but not yet at the actual service-construction boundary. Once
the runner can build/capture semantic+FTS evidence without initializing FalkorDB, risk drops
to MEDIUM or LOW-MEDIUM.

---

## OpenCode Review

**Reviewed:** 43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md — review commit 3122a59
(post-cycle-2 revision)

### 1. Summary

The cycle-3 revisions address the cycle-2 consensus HIGH (graph isolation) and all
actionable MEDIUM/LOW items with concrete, source-grounded decisions. The plans are now
executable. The graph isolation fix (D43-02-G/D43-03-E) is honest — it acknowledges the
hardcoded `graph_name="dotmd"` constraint in `_create_graph_store()` (pipeline.py:161) and
scopes Phase 43 to semantic+FTS-only evidence, excluding graph-category queries with explicit
documentation of the exclusion. The candidate-config schema (D43-02-H) resolves the
engine-vs-loop parameter confusion, preflight identity binding (D43-03-D) closes the
stale-target gap, and the zero-division guard (D43-01-A) is explicit. Remaining concerns are
all LOW — implementation-level precision issues resolvable during coding.

### 2. Cycle-2 HIGH Disposition: RESOLVED

The cycle-2 consensus HIGH was: *Baseline graph state is not bound to the rehearsal window —
`Settings.model_copy(update={"index_dir": ...})` covers SQLite/FTS/sqlite-vec but not
FalkorDB, which is bound by `falkordb_url` (config.py:208), independent of `index_dir`.*

**Disposition: RESOLVED via D43-02-G + D43-03-E.**

Source-verified the root cause: `_create_graph_store()` at pipeline.py:161 hardcodes
`graph_name="dotmd"` and uses `settings.falkordb_url` — independent of `index_dir`. The
resolution (option b: disable graph engines, exclude graph-category queries) is the correct
pragmatic choice. The chosen mechanism is sound: `_collect_candidate_pool` gates graph
engines behind `SearchMode.GRAPH`/`SearchMode.HYBRID`; running baseline capture with
`SEMANTIC`/`KEYWORD` only ensures graph engines are never invoked, and `DotMDService.search()`
accepts `mode: SearchMode | str`, the exact seam the runner needs.

**One precision note** (Concern #2): D43-02-G states "no FalkorDB connection is opened during
baseline capture." The `DotMDService` constructor creates `IndexingPipeline` which calls
`_create_graph_store()` → `FalkorDBGraphStore(url=...)` — this connection is established at
construction time, before any search call. OpenCode rated the connection "harmless (no graph
data is read for results)" and classified the wording as a documentation precision issue, not
a functional gap.

### 3. Strengths

- All three cycle-1 HIGHs resolved in prior cycles and held stable (sentinel stripping;
  baseline binding via `Settings.model_copy` clone; Phase 41 preflight).
- Cycle-2 HIGH resolved with honest scope documentation — `graph_engines_disabled: true` +
  excluded query ids/count recorded; nothing silently missed.
- Candidate-config schema fully fail-closed (D43-02-H), pinned by five named tests.
- Preflight identity binding closes the stale-target gap (D43-03-D).
- Zero-division guard explicit (D43-01-A), pinned by `test_guardrails_reject_zero_baseline_field`.
- Source-grounding thorough; correct dependency order 43-01 → 43-02 → 43-03, no cycles.
- Artifact privacy policy now operational.

### 4. Concerns

**MEDIUM**

1. **NEW — "Graph-category" query definition for `filter_non_graph_golden_queries()` is
   underspecified.** The golden query JSONL has a `category` field
   (`title-heavy`, `tag-heavy`, `body-heavy`, `semantic`, `graph-entity`, `hybrid`,
   `source-ref`, `mixed-ru-en`) but no boolean `is_graph` marker. The plan says D43-02-G
   "excludes graph-category golden queries" without specifying the criterion. The natural
   implementation filters on `expected_engines` containing `"graph_direct"`. Without a clear
   criterion, the filter could include/exclude the wrong queries, breaking the D43-02-G test
   invariant.

**LOW**

2. **NEW — D43-02-G wording overstates graph connection isolation.** `DotMDService.__init__`
   constructs `IndexingPipeline` → `_create_graph_store()` → `FalkorDBGraphStore(url=...)` at
   construction time, before any SearchMode-gated call. Wording should distinguish "no graph
   engine is invoked" from "no connection is opened." The cloned settings' `falkordb_url` is
   not overridden in `model_copy`, so the constructor will attempt the connection.
3. **NEW — `--verify-only` tamper-detection for `shadow-diffs.jsonl` is implicit.** D43-03-C
   says raw classifications must "match runner-generated output (never hand-edited)," but the
   plan doesn't explicitly state `--verify-only` regenerates `shadow-diffs.jsonl` and compares
   it against the on-disk file. Without this, verification can't detect hand edits.
4. **NEW — `--metrics-replay-queries` JSONL row schema is not specified.** D43-02-E pins the
   flag to `type=Path` JSONL but doesn't define required per-row fields. The runner loads it
   with "strict line-numbered validation" but the schema is undefined.

### 5. Suggestions

1. Define the "graph-category" criterion in D43-02-G (e.g., exclude any golden query whose
   `expected_engines` contains `'graph_direct'` OR whose `primary_surface` is `'graph_entity'`).
2. Refine D43-02-G wording: "no graph engine is invoked during baseline capture; the FalkorDB
   connection established at service construction is not used for baseline results." Clarify in
   D43-02-A whether `falkordb_url` should be nullified in the `model_copy` clone or left as-is.
3. Make `--verify-only` tamper-detection explicit (regenerate `shadow-diffs.jsonl` and compare
   against disk; mismatch is a hard failure).
4. Document `--metrics-replay-queries` row schema in the runbook (min `query_id` + `query`).

### 6. Risk Assessment — LOW

The plans are ready for execution. The cycle-2 consensus HIGH is resolved with a documented,
honest scope reduction. All cycle-1 HIGHs remain resolved. Remaining concerns are
implementation-level precision issues resolvable during coding without architectural impact.

---

## Orchestrator adjudication (source-grounded)

The two reviewers disagree on the cycle-2 HIGH disposition. Both agree the **comparison
policy** (disable graph, exclude graph-category queries) is sound. They split on whether the
**construction-time FalkorDB connection** matters. I verified the live source to adjudicate:

1. **`DotMDService.__init__` (`backend/src/dotmd/api/service.py:260`) eagerly builds the graph
   store at construction.** Line 264 constructs `IndexingPipeline(self._settings)`;
   `IndexingPipeline.__init__` (`backend/src/dotmd/ingestion/pipeline.py:246`) calls
   `_create_graph_store(settings)` (`pipeline.py:161`), returning
   `FalkorDBGraphStore(url=settings.falkordb_url, graph_name="dotmd")`. There is no lazy seam.

2. **`FalkorDBGraphStore.__init__` (`backend/src/dotmd/storage/falkordb_graph.py:37-63`)
   connects AND writes.** It calls `FalkorDB(host, port)` + `select_graph(graph_name)` (raising
   `ConnectionError` if FalkorDB is unreachable, `falkordb_graph.py:47-53`), then issues
   `CREATE INDEX FOR (n:{label}) ON (n.id)` for five labels (`File`, `Section`, `Entity`,
   `Tag`, `Node`) against the live `dotmd` graph (`falkordb_graph.py:60-63`). These are
   idempotent but they are **writes against live FalkorDB**, executed at baseline-service
   construction time, before any `SearchMode` is chosen.

3. **The cloned settings do not override `falkordb_url`.** D43-02-A clones only `index_dir`
   via `Settings.model_copy(update={"index_dir": ...})`; `falkordb_url` (`config.py:208`)
   carries through unchanged, so the connection targets the live container.

**Consequence:** D43-02-G's truth claim "no FalkorDB connection is opened during baseline
capture," the threat-model row T-43-04c ("no live FalkorDB read occurs"), and the cycle-2
LOW disposition test premise `test_build_baseline_service_has_no_side_effects` ("opens no
network connection ... graph URL excluded since graph engines are disabled") are all **false
against the real constructor**. Building the baseline service connects to live FalkorDB and
mutates it (CREATE INDEX), which also violates the phase's read-only / no-live-mutation scope
(T-43-09, "Use read-only capture paths"). This is not merely a wording issue; an executor
following the plan literally would (a) write the false-premise side-effects test, which cannot
pass against the real constructor, and (b) perform a live-graph mutation the plan forbids. So
the cycle-2 HIGH is **PARTIALLY RESOLVED** and is counted as **1 open HIGH**.

**On Codex's "NEW HIGH — semantic+keyword-only SearchMode does not exist":** downgraded, not
counted as a separate HIGH. The plan text says "semantic+keyword(FTS) modes only" (plural
separate modes), not one combined enum value. `_collect_candidate_pool` (`service.py:1373,
1376, 1380`) fires graph-direct only for `SearchMode.GRAPH`/`SearchMode.HYBRID`; issuing
`SEMANTIC` and `KEYWORD` separately and fusing their pools is a real graph-free path using
existing enum members. The plan should still pin the explicit two-mode-fuse mechanism (it
currently leans on imprecise "semantic+keyword-only SearchMode" phrasing), but this is an
actionable precision fix folded into the HIGH remediation, not an independent blocker.

The remaining items both reviewers raise (graph-category filter criterion; immutable-input vs
produced-output split for `source-capture.json`; `--verify-only` tamper-detection;
`--metrics-replay-queries` row schema; preflight namespace/database flags; WAL/snapshot
identity fail-closed) are genuine actionable non-HIGH gaps not yet incorporated into the
PLAN.md task/acceptance text.

---

## Consensus Summary

Both reviewers agree the cycle-3 revisions **fully resolve** every prior-cycle concern at the
policy/decision level: all three cycle-1 HIGHs remain closed; the cycle-2 candidate-config
schema gap is closed by D43-02-H (five named tests); the cycle-2 preflight identity-binding
gap is closed by D43-03-D; the cycle-2 LOWs (zero-division guard D43-01-A, preflight-failure
stop path D43-03-A, artifact-handling policy) are incorporated. Dependency order
(43-01 → 43-02 → 43-03) is correct with no cycles, and the reuse seams resolve to real source.

Both reviewers **independently flag the same residual issue**: the `DotMDService` constructor
establishes the FalkorDB graph store before any `SearchMode` gate. They differ only on
severity — Codex calls it a remaining HIGH (baseline construction crosses the live FalkorDB
boundary); OpenCode calls it a LOW wording imprecision (the connection is "harmless"). The
orchestrator's source-grounding (above) shows the constructor not only connects but issues
`CREATE INDEX` **writes** to live FalkorDB, contradicting the plan's explicit isolation
invariant and the phase's read-only scope, and falsifies the `*_has_no_side_effects` test
premise. The issue is therefore counted as **1 open HIGH**.

### Agreed Strengths
- All cycle-1 HIGHs closed and stable; cycle-2 schema/preflight/LOW gaps incorporated with
  named tests (both).
- Honest, documented scope reduction to semantic+FTS with recorded graph exclusion (both).
- Candidate-config fail-closed schema with correct engine-vs-loop routing (both).
- Correct dependency ordering, no cycles; reuse seams source-confirmed (both).

### Agreed Concerns (highest priority)
- **HIGH — Baseline service construction crosses the live FalkorDB boundary.** Both reviewers,
  independently, ground this in `service.py:260` → `pipeline.py:161` →
  `FalkorDBGraphStore.__init__`. The construction-time connect + `CREATE INDEX` write breaks
  the D43-02-G "no connection opened" / T-43-04c "no live FalkorDB read" invariant and the
  read-only scope. Remedy: build the baseline pool without constructing the FalkorDB-backed
  graph store (no-op/null graph store injection, a semantic+FTS-only baseline factory, or
  calling the semantic and keyword engines directly and fusing), and correct the false-premise
  side-effects test and the threat-model row. Also pin the explicit two-mode
  (`SEMANTIC`+`KEYWORD`) fuse path rather than a non-existent combined "semantic+keyword
  SearchMode."

### Divergent / Single-Reviewer Concerns
- **MEDIUM — "graph-category" filter criterion underspecified (OpenCode, source-confirmed):**
  golden queries carry `category`, `expected_engines`, and `primary_surface`; the plan does
  not state which field defines "graph-category," so `filter_non_graph_golden_queries()` is
  ambiguous (notably `category: "hybrid"` rows that include `graph_direct` in
  `expected_engines`).
- **MEDIUM — `source-capture.json` is both immutable preflight input and produced output
  (Codex):** the plan should split expected-identity input from generated evidence so
  validation cannot pass against an artifact the runner later rewrites.
- **MEDIUM — WAL/snapshot identity only visible, not fail-closed (Codex, remaining):** size +
  mtime are recorded but not compared against the expected import identity before baseline
  capture.
- **LOW — `--verify-only` does not explicitly regenerate-and-compare `shadow-diffs.jsonl`
  (OpenCode):** tamper-detection for D43-03-C is implicit.
- **LOW — `--metrics-replay-queries` per-row JSONL schema undefined (OpenCode).**
- **LOW — 43-03 preflight verify command omits `--target-namespace`/`--target-database`
  (Codex).**

---

## Verification coverage

Source-grounding pass over every non-produced symbol/file the revised (cycle-3) plans cite.
Artifacts the plans declare under "Artifacts This Phase Produces" (the metric module, the
runner, the runbook, and the eight `artifacts/*` files plus the operator-supplied input
descriptors) are EXCLUDED from MISSING verdicts. The new cycle-3 citations introduced by the
revised decisions (`SearchMode` enum members, `_collect_candidate_pool` graph gating,
`FalkorDBGraphStore.__init__` connect/index behavior, `DEFAULT_HNSW_EF`,
`build_surreal_native_engine_overrides` signature, `DotMDService.search` mode seam) were
checked in addition to the verified cycle-2 set.

| Cited symbol / file | Plan ref | Verdict | Evidence |
|---|---|---|---|
| `evaluate_surreal_scale_gate()` + scale-gate field names | 43-01 | VERIFIED | `backend/src/dotmd/search/surreal_parity.py:435` (cycle-2 confirmed) |
| `SearchMode` enum (`SEMANTIC`,`KEYWORD`,`GRAPH`,`HYBRID`) | 43-02 D43-02-G | VERIFIED | `backend/src/dotmd/core/models.py:20-26` — only these four members; no combined "semantic+keyword" member (basis for the precision fix folded into the HIGH) |
| `_collect_candidate_pool` graph gating by mode | 43-02 D43-02-G | VERIFIED | `backend/src/dotmd/api/service.py:1373,1376,1380` — graph_direct fires only for `GRAPH`/`HYBRID`; `SEMANTIC`/`KEYWORD` issued separately are graph-free |
| `DotMDService.search(mode=...)` seam | 43-02 D43-02-G | VERIFIED | `api/service.py:472-476` (`mode: SearchMode | str = SearchMode.HYBRID`) |
| `DotMDService.__init__` builds graph store at construction | 43-02 D43-02-A/G | VERIFIED (CONTRADICTS plan claim) | `api/service.py:260,264` → `IndexingPipeline(settings)`; `_create_graph_store` at `ingestion/pipeline.py:161,246`; graph store built eagerly — falsifies "no FalkorDB connection opened" |
| `FalkorDBGraphStore.__init__` connects + writes indexes | concern source | VERIFIED | `storage/falkordb_graph.py:47-53` connects (raises `ConnectionError` if down), `:60-63` issues `CREATE INDEX` for `File/Section/Entity/Tag/Node` — confirms the open HIGH |
| `_create_graph_store` hardcodes `graph_name="dotmd"`, uses `settings.falkordb_url` | 43-02 D43-02-G | VERIFIED | `ingestion/pipeline.py:161-168`; `falkordb_url` at `core/config.py:208` |
| `build_surreal_native_engine_overrides(embedding_dimension, hnsw_ef=DEFAULT_HNSW_EF)` | 43-02 D43-02-H | VERIFIED | `search/surreal_native.py:18` — accepts only `embedding_dimension`,`hnsw_ef` (confirms engine-vs-loop routing) |
| `DEFAULT_HNSW_EF` | 43-02 D43-02-H | VERIFIED | `storage/surreal_schema.py` (`DEFAULT_HNSW_EF = 40`), imported by `surreal_native.py` |
| `run_eval` + `EvalRunnerConfig` + `EvalRunResult` | 43-02 key_links | VERIFIED | `devtools/surreal_eval_runner.py:27,40,151` |
| `EvalResult` + `query_id`,`top_refs`,`matched_engines` | 43-02/43-03 | VERIFIED | `search/surreal_eval.py:73,76,80,81` |
| Acceptance fields `query_id`,`accepted_by`,`accepted_reason` | 43-02/43-03 | VERIFIED | `surreal_eval.py:91-93` |
| `load_eval_results()` | 43-02/43-03 verify | VERIFIED | `surreal_eval.py` (`def load_eval_results` present) |
| `Settings` + `index_dir` + `index_db_path` (= `index_dir/"index.db"`) | 43-02 D43-02-A | VERIFIED | `core/config.py:406` |
| `Settings.model_copy(update=...)` | 43-02 D43-02-A | VERIFIED | Pydantic v2 BaseModel method on `Settings(BaseSettings)` |
| `RUNTIME_INDEX_DIR` (`/dotmd-index`) | 43-02 D43-02-B | VERIFIED | `core/config.py:40` |
| `Settings.validate_for_runtime()` (NOT called on clone) | 43-02 D43-02-A | VERIFIED | `core/config.py:333` |
| `load_settings()` | 43-02 D43-02-A | VERIFIED | `core/config.py:415` |
| Golden-query schema fields (`category`,`expected_engines`,`primary_surface`) | 43-02 D43-02-G filter | VERIFIED | `devtools/surreal_golden_queries.jsonl` — 16 rows; categories include `graph-entity`,`hybrid`; some `expected_engines` include `graph_direct`; criterion not pinned by the plan (basis for the MEDIUM) |
| `surreal_eval_runner.py` / `surreal_migration_runner.py` | 43-02 read_first | VERIFIED | both present |
| `docs/surrealdb-evaluation-harness.md`, `docs/surrealdb-production-migration.md` | 43-02/43-03 | VERIFIED | present in `docs/` |
| Test files `test_surreal_eval_runner.py`,`test_surreal_migration_runner.py`,`test_surreal_retrieval_parity.py` | read_first | VERIFIED | present under `backend/tests/` |
| Phase summaries 40-01, 41-03, 42-04; 42-VERIFICATION | 43-0x context | VERIFIED | present under `.planning/phases/` |
| `surreal_shadow_metrics.py` + symbols | produced by 43-01 | EXCLUDED (produced) | declared artifact |
| `surreal_shadow_runner.py` + symbols/flags, `docs/surrealdb-shadow-run-quality-gate.md` | produced by 43-02 | EXCLUDED (produced) | declared artifact |
| `artifacts/*` (8 outputs + `candidate-config.json`, `metrics-replay-queries.jsonl`, `preflight-failure.md`) | produced by 43-03 | EXCLUDED (produced) | declared artifacts |

**Coverage result:** 24 VERIFIED, 0 MISSING, 0 AMBIGUOUS, 0 UNCHECKABLE (3 produced-artifact
groups correctly excluded). No plan cites a non-existent upstream symbol; every reuse seam
resolves to real source. Crucially, the source-grounding pass **contradicts one plan truth
claim**: `DotMDService.__init__` (`service.py:260`) eagerly builds `FalkorDBGraphStore`
(`pipeline.py:161` → `falkordb_graph.py:47-63`), which connects to AND writes `CREATE INDEX`
into the live `dotmd` graph at baseline-service construction — so D43-02-G's "no FalkorDB
connection is opened during baseline capture" and T-43-04c's "no live FalkorDB read occurs"
are false, confirming the open HIGH. It also confirms OpenCode's MEDIUM: the golden-query
"graph-category" exclusion criterion is not pinned by the plan despite the schema offering
three plausible fields.
