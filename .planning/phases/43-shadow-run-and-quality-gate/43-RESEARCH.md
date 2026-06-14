# Phase 43: Shadow run and quality gate - Research

**Researched:** 2026-06-14
**Domain:** SurrealDB shadow evaluation, production-derived evidence capture, and retrieval quality gating
**Confidence:** MEDIUM

## User Constraints

- This is a shadow/evidence phase only, not production cutover. [VERIFIED: user prompt]
- Use production-derived data as closely as possible without risking live dotMD. [VERIFIED: user prompt]
- Preserve migrated data where possible; avoid recomputing chunks, embeddings, and entities unless proven necessary. [VERIFIED: user prompt]
- No fallback or compatibility shims as final architecture; the old stack is baseline evidence only. [VERIFIED: user prompt]
- No Phase 43 `CONTEXT.md` exists yet, so these prompt constraints are the active user constraints for planning. [VERIFIED: init.phase-op]

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SURR-CUT-01 | A shadow run compares old stack and Surreal stack on production-derived data and records quality, latency, build-time, store-size, and memory evidence. [VERIFIED: .planning/REQUIREMENTS.md] | Reuse the Phase 40 JSONL diff harness for quality, the Phase 41 source-capture/migration evidence for provenance, the Phase 42 explicit engine-override seam for candidate retrieval, and the Phase 38 scale-gate helper for build-time/store-size/latency completeness. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_migration_runner.py][VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/src/dotmd/search/surreal_parity.py] |
</phase_requirements>

## Project Constraints (from AGENTS.md)

- All public APIs must flow through `api/service.py`; Phase 43 should not add alternate public retrieval entrypoints. [VERIFIED: AGENTS.md]
- Never reload indexes per request; any shadow-run execution must reuse already-initialized engines/stores inside the comparison process. [VERIFIED: AGENTS.md]
- Never run `dotmd index --force` while the production container is running because trickle holds the `fcntl` lock. [VERIFIED: AGENTS.md]
- Never restart production on small changes; Phase 43 should collect evidence against copied data or explicit read-only capture windows, not iterative production restarts. [VERIFIED: AGENTS.md]
- Production `DOTMD_DATA_DIR` is locked to `/mnt`; corpus refs and production-derived evidence should stay anchored to that namespace. [VERIFIED: AGENTS.md]
- Feedback evidence must come through the supported CLI/exporter path, not direct `feedback.db` queries. [VERIFIED: AGENTS.md]
- Source code is bind-mounted into the container; image rebuilds are only justified if `pyproject.toml` or `start.sh` changes, which Phase 43 should avoid by default. [VERIFIED: AGENTS.md]

## Summary

Phase 43 should be planned as one bounded evidence window, not as a new long-lived parallel runtime architecture. The repo already has the right seams: Phase 40 compares captured baseline and candidate JSONL result sets instead of live dual-stack implementations, Phase 41 records source-capture manifests plus migration/restore evidence, and Phase 42 exposes explicit Surreal retrieval overrides without changing startup defaults. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md]

The planning target is therefore a reproducible shadow-run pipeline that ties together: one production-derived source-capture manifest, one baseline capture window for the old stack, one Surreal candidate target built from the preserved migration path, one metric bundle for latency/build/store/memory, and one acceptance ledger for every unresolved semantic difference. Phase 43 should end with evidence and explicit accept/fix decisions, not startup cutover wiring or legacy deletion. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: .planning/ROADMAP.md]

**Primary recommendation:** Build Phase 43 around a single repo-local shadow-run runner that reuses `surreal_eval.py`, `SurrealRetrievalParityHarness`, `evaluate_surreal_scale_gate()`, `surreal_migration_runner.py`, and `build_surreal_native_engine_overrides()` instead of inventing separate quality, scale, and migration reporting flows. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/src/dotmd/search/surreal_parity.py][VERIFIED: backend/devtools/surreal_migration_runner.py][VERIFIED: backend/src/dotmd/search/surreal_native.py]

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Source-capture window and shadow target preparation | Database / Storage | API / Backend | Phase 41 manifests, snapshot inputs, graph export, feedback export, and restore evidence define the safe production-derived boundary before any comparison runs. [VERIFIED: backend/devtools/surreal_migration_runner.py][VERIFIED: docs/surrealdb-production-migration.md] |
| Baseline old-stack result capture | API / Backend | Database / Storage | The old stack is baseline evidence only, and Phase 40 already models baseline input as captured JSONL results rather than a separate persisted backend. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: docs/surrealdb-evaluation-harness.md] |
| Surreal candidate retrieval capture | API / Backend | Database / Storage | Phase 42 exposes explicit Surreal engine overrides through the existing service candidate-pool seam without changing runtime defaults. [VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/src/dotmd/api/service.py] |
| Diff classification and acceptance gating | API / Backend | — | `surreal_eval.py` and `surreal_eval_runner.py` already own the accepted difference vocabulary and aggregate cutover pass/fail logic. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_eval_runner.py] |
| Build-time, store-size, latency, and memory evidence | Database / Storage | API / Backend | Store size and import/build timing come from the migrated Surreal target, while latency and memory measurements come from the comparison runner and retrieval calls. [VERIFIED: backend/src/dotmd/search/surreal_parity.py][VERIFIED: docs/surrealdb-production-migration.md][CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html] |
| Regression disposition ledger | API / Backend | — | Acceptance metadata is already modeled separately from raw classification and should remain a reviewer-owned artifact. [VERIFIED: backend/src/dotmd/search/surreal_eval.py] |

## Likely Artifacts

| Artifact | Purpose | Notes |
|---------|---------|-------|
| `backend/devtools/surreal_shadow_runner.py` | One orchestrator for baseline capture, candidate capture, metric collection, and final report emission. [ASSUMED] | This is the narrowest missing seam; the repo has evaluators and migration helpers but no single Phase 43 runner yet. [VERIFIED: backend/devtools/surreal_eval_runner.py][VERIFIED: backend/devtools/surreal_migration_runner.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/source-capture.json` | Frozen provenance for the evidence window. [VERIFIED: docs/surrealdb-production-migration.md] | Prefer reuse of Phase 41 manifest schema over a new shape. [VERIFIED: backend/devtools/surreal_migration_runner.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/baseline-results.jsonl` | Old-stack captured results for the approved corpus. [VERIFIED: docs/surrealdb-evaluation-harness.md] | Must match Phase 40 `EvalResult` schema. [VERIFIED: backend/src/dotmd/search/surreal_eval.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/candidate-results.jsonl` | Surreal-stack captured results for the same corpus and source window. [VERIFIED: docs/surrealdb-evaluation-harness.md] | Must include `matched_engines` and any supplied snippet/read evidence. [VERIFIED: backend/src/dotmd/search/surreal_eval.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/accepted-diffs.jsonl` | Explicit semantic-change acceptance ledger plus a Phase 43 metadata sentinel row. [VERIFIED: docs/surrealdb-evaluation-harness.md] | Keep reviewer metadata separate from raw diff rows; the Phase 43 runner must strip the sentinel before delegating real acceptance rows to Phase 40 acceptance semantics. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_eval_runner.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-diffs.jsonl` | Machine-readable per-query diff output. [VERIFIED: backend/devtools/surreal_eval_runner.py] | Phase 40 already writes deterministic JSONL. [VERIFIED: backend/devtools/surreal_eval_runner.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/shadow-summary.md` | Human-readable quality gate summary. [VERIFIED: backend/devtools/surreal_eval_runner.py] | Should remain short and operator-facing. [VERIFIED: docs/surrealdb-evaluation-harness.md] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/scale-metrics.json` | Build-time, file-size, latency, and representative-corpus completeness. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] | Reuse `evaluate_surreal_scale_gate()` fields instead of inventing new names. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] |
| `.planning/phases/43-shadow-run-and-quality-gate/artifacts/memory-metrics.json` | Separate wall-clock, CPU, RSS, and Python heap peaks. [CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html] | Keep memory evidence distinct from latency and store size. [CITED: https://docs.python.org/3/library/tracemalloc.html] |

## Code Areas to Touch

| Path | Why it matters to planning |
|------|----------------------------|
| `backend/src/dotmd/search/surreal_eval.py` | Defines the Phase 40 golden-query schema, diff rows, classification rules, and acceptance semantics. [VERIFIED: backend/src/dotmd/search/surreal_eval.py] |
| `backend/devtools/surreal_eval_runner.py` | Already turns captured baseline/candidate JSONL into deterministic JSONL plus Markdown pass/fail reports. [VERIFIED: backend/devtools/surreal_eval_runner.py] |
| `backend/src/dotmd/search/surreal_parity.py` | Already has a reusable callable-based harness plus a scale gate for record counts, build time, file size, and latency completeness. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] |
| `backend/src/dotmd/search/surreal_native.py` | Builds explicit Surreal retrieval engines for shadow/evaluation use without changing runtime defaults. [VERIFIED: backend/src/dotmd/search/surreal_native.py] |
| `backend/src/dotmd/api/service.py` | `_collect_candidate_pool()` is the comparison seam for running baseline defaults versus Surreal overrides over the same service path. [VERIFIED: backend/src/dotmd/api/service.py] |
| `backend/devtools/surreal_migration_runner.py` | Supplies source-capture, target prep, verification, and restore evidence that Phase 43 should reuse rather than duplicate. [VERIFIED: backend/devtools/surreal_migration_runner.py] |
| `backend/src/dotmd/storage/surreal_ops.py` | Holds the typed restore/migration evidence report objects that already fit shadow-run provenance needs. [VERIFIED: backend/src/dotmd/storage/surreal_ops.py] |
| `backend/tests/search/test_surreal_retrieval_parity.py` | Existing contract coverage for parity and scale-gate semantics. [VERIFIED: backend/tests/search/test_surreal_retrieval_parity.py] |

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `dotmd.search.surreal_eval` + `backend/devtools/surreal_eval_runner.py` | checked-in Phase 40 artifact set [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md] | Query-level diff classification and acceptance gating. [VERIFIED: backend/src/dotmd/search/surreal_eval.py] | This is already the milestone-approved vocabulary for `improvement`, `harmless_reorder`, `regression`, and `unclear`. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md] |
| `dotmd.search.surreal_parity` | checked-in Phase 38 artifact set [VERIFIED: backend/src/dotmd/search/surreal_parity.py] | Reusable harness for old-vs-Surreal callable comparison plus scale-gate completeness fields. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] | Reusing it avoids a second ad hoc metric schema for build time, file size, and latency. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] |
| `dotmd.search.surreal_native` | checked-in Phase 42 artifact set [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md] | Explicit candidate engine overrides for Surreal FTS, vector, and graph-direct retrieval. [VERIFIED: backend/src/dotmd/search/surreal_native.py] | This is the sanctioned shadow/evaluation seam because it leaves service startup defaults unchanged. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md] |
| `dotmd.ingestion.migrate_surreal` + `backend/devtools/surreal_migration_runner.py` | checked-in Phase 41 artifact set [VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md] | Transform-first Surreal target preparation plus restore/report evidence. [VERIFIED: backend/devtools/surreal_migration_runner.py] | Phase 43 needs migrated candidate data, not a second migration workflow. [VERIFIED: docs/surrealdb-production-migration.md] |
| Python stdlib: `time`, `resource`, `tracemalloc` | Python 3.13.5 host / stdlib APIs present [VERIFIED: command] | Wall-clock, CPU, RSS, and Python-heap measurement. [CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html] | No new dependency is needed to produce benchmark-style timing and memory evidence. [CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html] |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `surrealdb` | 2.0.0 installed in the repo environment; `>=2.0.0` in `backend/pyproject.toml` [VERIFIED: command][VERIFIED: backend/pyproject.toml] | Candidate storage/retrieval target for the shadow run. [VERIFIED: backend/pyproject.toml] | Use for the candidate side only; Phase 43 should not flip the default runtime backend. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md] |
| `uv` | 0.11.21 [VERIFIED: command] | Reproducible runner/test execution. [VERIFIED: command] | Use for all repo-local devtools/test commands. [VERIFIED: justfile] |
| `just` | 1.40.0 [VERIFIED: command] | Repo-standard setup, unit, verify, and remote smoke entrypoints. [VERIFIED: command][VERIFIED: justfile] | Use `just setup`, focused `just unit`, and `just verify`; remote smoke remains Phase 44 territory. [VERIFIED: justfile][VERIFIED: .planning/ROADMAP.md] |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Reusing the Phase 40 JSONL harness [VERIFIED: backend/devtools/surreal_eval_runner.py] | A brand-new Phase 43 report format [ASSUMED] | A new format would duplicate approved diff semantics and increase acceptance-ledger drift. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md] |
| Running candidate retrieval through explicit engine overrides [VERIFIED: backend/src/dotmd/search/surreal_native.py] | Flipping `DotMDService` startup defaults to Surreal during the shadow phase [ASSUMED] | That would leak cutover work into Phase 43 and blur failure attribution. [VERIFIED: .planning/ROADMAP.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md] |
| Reusing Phase 41 source-capture and restore evidence [VERIFIED: docs/surrealdb-production-migration.md] | Rebuilding candidate data by rechunking/reembedding/reextracting [ASSUMED] | Recompute would violate the locked transform-first migration policy unless proven necessary. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md] |

**Installation:**
```bash
just setup
```

No new external packages are recommended for Phase 43. [VERIFIED: backend/pyproject.toml][VERIFIED: justfile]

## Architecture Patterns

### System Architecture Diagram

```text
read-only query set + source-capture manifest
        |
        v
baseline capture (old stack, same evidence window) ----+
        |                                               |
        v                                               v
baseline-results.jsonl                           candidate prep
                                                (Phase 41 transform-first import
                                                into isolated Surreal target)
                                                        |
                                                        v
                                          candidate capture via explicit
                                          Surreal engine overrides
                                                        |
                                                        v
                                              candidate-results.jsonl
                                                        |
                                                        v
                                   Phase 40 evaluator + acceptance ledger
                                                        |
                           +----------------------------+-------------------------+
                           |                            |                         |
                           v                            v                         v
                    shadow-diffs.jsonl          shadow-summary.md         unresolved regressions?
                                                                                  |
                                                                   +--------------+-------------+
                                                                   |                            |
                                                                   v                            v
                                                            fix in later plan          explicit acceptance ledger

parallel side-channel:
candidate import/build run -> build/store evidence
query replay -> latency evidence
runner process -> wall-clock / CPU / RSS / Python heap evidence
```

### Recommended Project Structure

```text
.planning/phases/43-shadow-run-and-quality-gate/
├── 43-RESEARCH.md                  # this file
└── artifacts/                      # planning target for evidence bundles
    ├── source-capture.json
    ├── baseline-results.jsonl
    ├── candidate-results.jsonl
    ├── accepted-diffs.jsonl
    ├── shadow-diffs.jsonl
    ├── shadow-summary.md
    ├── scale-metrics.json
    └── memory-metrics.json

backend/
├── devtools/
│   └── surreal_shadow_runner.py    # likely new runner
└── tests/
    ├── devtools/test_surreal_shadow_runner.py
    └── search/test_surreal_shadow_metrics.py
```

### Pattern 1: One Bounded Evidence Window

**What:** Capture baseline results, candidate migration inputs, candidate results, and metric outputs under one manifest-tied window instead of mixing data from unrelated timestamps. [VERIFIED: docs/surrealdb-evaluation-harness.md][VERIFIED: docs/surrealdb-production-migration.md]

**When to use:** Always for the production-derived Phase 43 run. [VERIFIED: user prompt]

**Example:**
```python
# Source: backend/devtools/surreal_eval_runner.py + backend/devtools/surreal_migration_runner.py
baseline_results = capture_old_stack_results(source_capture_manifest)
candidate_target = prepare_surreal_target(source_capture_manifest)
candidate_results = capture_surreal_results(candidate_target)
run_eval(baseline_results, candidate_results, acceptance_path)
```

### Pattern 2: Explicit Candidate Override, No Startup Flip

**What:** Run Surreal retrieval through `build_surreal_native_engine_overrides()` and pass those overrides into the existing service seam. [VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/src/dotmd/api/service.py]

**When to use:** For all shadow/candidate captures before Phase 44. [VERIFIED: .planning/ROADMAP.md]

**Example:**
```python
# Source: backend/src/dotmd/search/surreal_native.py
overrides = build_surreal_native_engine_overrides(
    connection,
    settings,
    embedding_dimension=embedding_dimension,
)
pool = service._collect_candidate_pool(
    search_query=query,
    original_query=query,
    mode=mode,
    pool_size=pool_size,
    engine_overrides=overrides,
)
```

### Pattern 3: Separate Quality Gate From Scale Gate

**What:** Keep per-query quality classification and scale/perf completeness as separate reports, then combine them at the final phase gate. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/src/dotmd/search/surreal_parity.py]

**When to use:** Always; a run can have good relevance but incomplete metric evidence, or complete metrics with blocked regressions. [VERIFIED: backend/src/dotmd/search/surreal_parity.py][VERIFIED: backend/src/dotmd/search/surreal_eval.py]

### Anti-Patterns to Avoid

- **New ad hoc diff taxonomy:** Do not create Phase 43-only labels when Phase 40 already standardized `improvement`, `harmless_reorder`, `regression`, and `unclear`. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md]
- **Candidate startup cutover:** Do not change default service startup engines in Phase 43. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md]
- **Live mutation disguised as evaluation:** Do not run indexing or write-heavy prep against the live container. [VERIFIED: AGENTS.md]
- **Metric collapse:** Do not publish a single “memory” number without distinguishing RSS, Python heap, and file size. [CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html] |

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Query-diff classification | A second custom comparator [ASSUMED] | `dotmd.search.surreal_eval` + `surreal_eval_runner.py` [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_eval_runner.py] | The accepted-difference vocabulary, acceptance semantics, and JSONL schema are already verified. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md] |
| Scale/perf completeness logic | A new “shadow score” schema [ASSUMED] | `evaluate_surreal_scale_gate()` [VERIFIED: backend/src/dotmd/search/surreal_parity.py] | It already defines required fields for record counts, build time, file size, latency, and representative-corpus completeness. [VERIFIED: backend/src/dotmd/search/surreal_parity.py] |
| Candidate retrieval wiring | A forked service/search pipeline [ASSUMED] | `build_surreal_native_engine_overrides()` + existing `_collect_candidate_pool()` seam [VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/src/dotmd/api/service.py] | Reusing the same candidate-pool seam reduces semantic drift between evaluation and eventual cutover. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md] |
| Migration provenance | New snapshot/report shapes [ASSUMED] | Phase 41 source-capture, report, and restore-manifest shapes [VERIFIED: backend/devtools/surreal_migration_runner.py][VERIFIED: backend/src/dotmd/storage/surreal_ops.py] | Reusing the same evidence schema keeps Phase 43 tied to the transform-first migration policy. [VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md] |

**Key insight:** Phase 43 is mostly orchestration and evidence normalization across already-approved seams, not a greenfield algorithm phase. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md]

## Common Pitfalls

### Pitfall 1: Baseline/Candidate Skew

**What goes wrong:** Baseline results and candidate results are compared even though they came from different source states. [VERIFIED: docs/surrealdb-evaluation-harness.md][VERIFIED: docs/surrealdb-production-migration.md]
**Why it happens:** The Phase 40 harness compares captured JSONL rows, so timestamp skew is easy to hide if the source-capture manifest is not attached. [VERIFIED: backend/devtools/surreal_eval_runner.py][VERIFIED: backend/devtools/surreal_migration_runner.py]
**How to avoid:** Require one source-capture manifest and capture timestamps for both baseline and candidate runs in the same evidence bundle. [VERIFIED: docs/surrealdb-production-migration.md]
**Warning signs:** Missing manifest, mismatched counts, or baseline refs that cannot be explained by the candidate source window. [ASSUMED]

### Pitfall 2: Recompute Creep

**What goes wrong:** The shadow candidate gets rebuilt with fresh chunking, embeddings, or entity extraction, so failures no longer measure the transform-first migration path. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md]
**Why it happens:** Recompute is a tempting shortcut when candidate imports or retrieval checks fail. [ASSUMED]
**How to avoid:** Keep the Phase 41 manifest/report fields visible in every Phase 43 artifact and fail closed when `no_recompute_verified` or `embedding_reuse_verified` is false. [VERIFIED: backend/src/dotmd/storage/surreal_ops.py]
**Warning signs:** Candidate evidence that lacks source-capture checksums, reuse verification, or checkpoint data. [VERIFIED: docs/surrealdb-production-migration.md]

### Pitfall 3: Cutover Work Leaking Into Shadow

**What goes wrong:** The phase starts changing runtime defaults, container startup, or public interfaces instead of only collecting evidence. [VERIFIED: .planning/ROADMAP.md]
**Why it happens:** The easiest way to “see Surreal live” is to wire it into startup prematurely. [ASSUMED]
**How to avoid:** Use only explicit engine overrides and repo-local devtools entrypoints in Phase 43. [VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/src/dotmd/api/service.py]
**Warning signs:** New settings flags, new startup branching, or service constructor changes that affect default search behavior. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md]

### Pitfall 4: Incomplete Metric Evidence

**What goes wrong:** The run reports latency or file size but misses build time, representative corpus declaration, or memory evidence. [VERIFIED: backend/src/dotmd/search/surreal_parity.py]
**Why it happens:** The Phase 40 harness only covers quality, not scale/perf completeness. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md]
**How to avoid:** Treat the Phase 38 scale-gate fields as mandatory Phase 43 outputs and add a separate memory report with wall-clock, CPU, RSS, and Python heap peaks. [VERIFIED: backend/src/dotmd/search/surreal_parity.py][CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html]
**Warning signs:** `hnsw_build_seconds`, `surrealkv_file_size_bytes`, or representative-corpus fields are null or absent. [VERIFIED: backend/src/dotmd/search/surreal_parity.py]

## Code Examples

### Reuse the Scale-Gate Shape
```python
# Source: backend/src/dotmd/search/surreal_parity.py
scale_gate = evaluate_surreal_scale_gate(
    record_counts=record_counts,
    hnsw_build_seconds=hnsw_build_seconds,
    surrealkv_file_size_bytes=surreal_file_size,
    query_latencies_ms=query_latencies_ms,
    representative=True,
)
```

### Use Official Single-Field Full-Text Indexing Assumption
```sql
-- Source: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes
DEFINE INDEX body_index
  ON TABLE article
  FIELDS body
  FULLTEXT ANALYZER my_analyzer BM25;
```

### Use Official HNSW Query Shape for Candidate Retrieval Checks
```sql
-- Source: https://surrealdb.com/docs/reference/query-language/language-primitives/operators
DEFINE INDEX idx_embedding
  ON TABLE test
  FIELDS embedding
  HNSW DIMENSION 3 DIST COSINE;

SELECT id FROM test WHERE embedding <|10,40|> $qvec;
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Phase 38 parity-style migration gate tried to treat the current stack as a stronger compatibility target. [VERIFIED: .planning/ROADMAP.md][VERIFIED: backend/src/dotmd/search/surreal_parity.py] | v1.8 phases explicitly treat the old stack as baseline/evaluator evidence only and gate on explainable user-visible differences. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md] | Locked by Phase 39 and Phase 40 in 2026-06. [VERIFIED: .planning/phases/39-surrealdb-native-retrieval-contract/39-VERIFICATION.md][VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-VERIFICATION.md] | Phase 43 should classify and accept semantic changes instead of chasing exact old-stack ordering. [VERIFIED: .planning/REQUIREMENTS.md] |
| Full-text index syntax in older SurrealDB docs/examples may show `SEARCH ANALYZER`. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Official docs now document `FULLTEXT ANALYZER`, with older syntax called out as pre-3.0.0-beta behavior. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Current docs page as opened on 2026-06-14. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes] | Phase 43 should evaluate the checked-in current syntax/runtime, not revive legacy syntax for comparison. [VERIFIED: backend/src/dotmd/storage/surreal_schema.py] |

**Deprecated/outdated:**

- Exact-rank parity as the acceptance target is outdated for this milestone. The requirements and evaluation harness both reject that framing. [VERIFIED: .planning/REQUIREMENTS.md][VERIFIED: docs/surrealdb-evaluation-harness.md]
- Planning a second shadow-only hybrid fusion path is outdated because Phase 42 already chose the existing Python fusion seam plus explicit Surreal overrides. [VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md]

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | Phase 43 will likely need one new repo-local orchestrator such as `backend/devtools/surreal_shadow_runner.py` because the repo has the comparison pieces but no single end-to-end runner yet. [ASSUMED] | Likely Artifacts | Plan could over-split or under-split the implementation work. |
| A2 | Baseline capture must run read-only from an isolated copied snapshot/rehearsal path, not by mutating the live old-stack runtime. [VERIFIED: revision decision] | Summary / Resolved Planning Questions | If copied snapshot inputs are unavailable, execution must stop and report the missing input instead of falling back to live mutation or recomputation. |

## Resolved Planning Questions

1. **How should the old-stack side be executed?**
   - What we know: Phase 40 expects captured baseline JSONL, and Phase 41 already defines copied-source evidence for the candidate side. [VERIFIED: docs/surrealdb-evaluation-harness.md][VERIFIED: docs/surrealdb-production-migration.md]
   - Resolved decision: Capture the old-stack baseline read-only from an isolated copied snapshot/rehearsal path. Do not mutate the live runtime, do not narrow production `DOTMD_DATA_DIR`, do not run `dotmd index --force`, and do not use the old stack as a compatibility backend. [VERIFIED: revision decision][VERIFIED: AGENTS.md]
   - Planning impact: Plan 43-02 must document and test baseline capture as a copied-snapshot/rehearsal operation, and Plan 43-03 must stop if the copied old-stack rehearsal input is missing instead of recomputing source content or touching live storage. [VERIFIED: revision decision]

2. **Is the checked-in 16-query golden corpus the only quality set, or is there also a larger production-derived replay set?**
   - What we know: The approved corpus has 16 rows and covers the required categories. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md]
   - Resolved decision: Use both sets. The 16-query golden corpus is the semantic quality gate; a larger production-derived replay/metrics window supplies performance, latency, memory, build-time, and store-size evidence. [VERIFIED: revision decision]
   - Planning impact: Plan 43-02 must expose an explicit metrics replay input or window descriptor, and Plan 43-03 must record replay-window metadata in `scale-metrics.json`, `memory-metrics.json`, and the acceptance-ledger sentinel without changing raw quality classifications. [VERIFIED: revision decision]

3. **What acceptance rule should apply to memory evidence?**
   - What we know: Python and OS metrics can be split into wall-clock, CPU time, traced heap, and RSS. [CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html]
   - Resolved decision: Memory is not evidence-only. Phase 43 must emit memory evidence plus explicit guardrail thresholds in the acceptance ledger sentinel. The exact thresholds are planned as code constants/config in the Phase 43 evidence contract, not informal notes. [VERIFIED: revision decision]
   - Planning impact: Plan 43-01 must define the guardrail constants in `surreal_shadow_metrics.py`; Plan 43-02 must write/read those constants through the ledger metadata row; Plan 43-03 must fail verification when the memory report or ledger omits the configured thresholds. [VERIFIED: revision decision]

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | devtools runners, tests, metrics collection | ✓ [VERIFIED: command] | 3.13.5 [VERIFIED: command] | — |
| `uv` | repo-standard execution and env sync | ✓ [VERIFIED: command] | 0.11.21 [VERIFIED: command] | direct `python` is weaker and lacks repo-standard env management. [ASSUMED] |
| `just` | setup, focused unit runs, full verify | ✓ [VERIFIED: command] | 1.40.0 [VERIFIED: command] | run the underlying `uv` commands manually. [VERIFIED: justfile] |
| Docker | live container state checks and any container-tied capture path | ✓ [VERIFIED: command] | 29.5.3 [VERIFIED: command] | none for production-like shadow capture. [ASSUMED] |
| `dotmd` container | read-only baseline or smoke-oriented checks if chosen | ✓ [VERIFIED: command] | running, healthy [VERIFIED: command] | baseline capture could be repo-local only if live reads are rejected. [ASSUMED] |
| `falkordb` container | current-stack graph baseline | ✓ [VERIFIED: command] | running [VERIFIED: command] | none if old-stack capture must include graph retrieval. [ASSUMED] |
| `embeddings` container | candidate vector retrieval and any semantic capture path | ✓ [VERIFIED: command] | running [VERIFIED: command] | none for semantic/shadow capture. [ASSUMED] |
| `/mnt` | production ref namespace and production-derived corpus access | ✓ [VERIFIED: command] | — | none; AGENTS locks production data dir to `/mnt`. [VERIFIED: AGENTS.md] |
| `surreal` CLI | optional extra export/import restore evidence | ✗ [VERIFIED: command] | — | use the Phase 41 copied-target restore rehearsal path and record CLI absence explicitly. [VERIFIED: docs/surrealdb-production-migration.md] |
| `pip index` via system `python3` | raw registry version checks | ✗ [VERIFIED: command] | — | rely on checked-in constraints, installed metadata via `uv run`, and official docs. [VERIFIED: backend/pyproject.toml][VERIFIED: command] |

**Missing dependencies with no fallback:**

- None identified for Phase 43 planning. [VERIFIED: command]

**Missing dependencies with fallback:**

- `surreal` CLI is absent, but Phase 41 already defines a non-CLI restore rehearsal fallback. [VERIFIED: docs/surrealdb-production-migration.md]
- `python3 -m pip index` is unavailable, but Phase 43 does not need new package installs; installed versions can still be inspected through `uv run`. [VERIFIED: command][VERIFIED: backend/pyproject.toml]

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | `pytest` 9.0.3 in the repo environment. [VERIFIED: command] |
| Config file | `backend/pyproject.toml` for the main suite; `backend/tests/e2e/pytest.ini` for container E2E. [VERIFIED: backend/pyproject.toml][VERIFIED: backend/tests/e2e/pytest.ini] |
| Quick run command | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/search/test_surreal_retrieval_parity.py tests/devtools/test_surreal_eval_runner.py -q` [VERIFIED: backend/tests/search/test_surreal_eval.py][VERIFIED: backend/tests/search/test_surreal_retrieval_parity.py][VERIFIED: backend/tests/devtools/test_surreal_eval_runner.py] |
| Full suite command | `just verify` [VERIFIED: justfile] |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SURR-CUT-01 | Captured baseline/candidate results are diffed with accepted-difference semantics and aggregate pass/fail gating. [VERIFIED: .planning/REQUIREMENTS.md] | unit/integration | `cd backend && uv run pytest tests/search/test_surreal_eval.py tests/devtools/test_surreal_eval_runner.py -q` | ✅ [VERIFIED: backend/tests/search/test_surreal_eval.py][VERIFIED: backend/tests/devtools/test_surreal_eval_runner.py] |
| SURR-CUT-01 | Scale/build/store/latency completeness is enforced before the phase can pass. [VERIFIED: .planning/REQUIREMENTS.md] | unit | `cd backend && uv run pytest tests/search/test_surreal_retrieval_parity.py -q -k scale_gate` | ✅ [VERIFIED: backend/tests/search/test_surreal_retrieval_parity.py] |
| SURR-CUT-01 | End-to-end shadow orchestration emits the required artifact bundle. [ASSUMED] | integration | `cd backend && uv run pytest tests/devtools/test_surreal_shadow_runner.py -q` | ❌ Wave 0 |
| SURR-CUT-01 | Memory/latency reporting uses distinct metric fields and stable output schema. [ASSUMED] | unit | `cd backend && uv run pytest tests/search/test_surreal_shadow_metrics.py -q` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** focused `uv run pytest ... -q` on the touched shadow/eval/parity/devtool tests. [VERIFIED: backend/pyproject.toml]
- **Per wave merge:** `just verify`. [VERIFIED: justfile]
- **Phase gate:** `just verify` plus one artifact-producing dry run of the new shadow runner on non-live inputs before `$gsd-verify-work`. [ASSUMED]

### Wave 0 Gaps

- [ ] `backend/tests/devtools/test_surreal_shadow_runner.py` — covers end-to-end artifact emission and failure modes. [ASSUMED]
- [ ] `backend/tests/search/test_surreal_shadow_metrics.py` — covers metric field definitions, missing-metric failures, and memory/timing capture helpers. [ASSUMED]
- [ ] A fixture or helper for producing Phase 43-style captured `EvalResult` JSONL from real `DotMDService` search output without changing runtime defaults. [ASSUMED]

## Security Domain

### Applicable ASVS Categories

| ASVS Category | Applies | Standard Control |
|---------------|---------|-----------------|
| V2 Authentication | no [ASSUMED] | Phase 43 is repo-local/devtool oriented and should not add new auth flows. [ASSUMED] |
| V3 Session Management | no [ASSUMED] | No new session surface is required for this phase. [ASSUMED] |
| V4 Access Control | yes [VERIFIED: AGENTS.md] | Respect active resource bindings and public ref visibility by using existing service/search seams rather than bypassing them. [VERIFIED: backend/src/dotmd/api/service.py] |
| V5 Input Validation | yes [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_migration_runner.py] | Reuse existing line-numbered JSON/JSONL validation and fail-closed field checks. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_migration_runner.py] |
| V6 Cryptography | no [ASSUMED] | Phase 43 does not introduce new cryptographic primitives; it should reuse existing file/checksum evidence only. [ASSUMED] |

### Known Threat Patterns for this stack

| Pattern | STRIDE | Standard Mitigation |
|---------|--------|---------------------|
| Accidental live-store mutation during candidate prep | Tampering | Use copied snapshots/exports and isolated Surreal targets only; never run force indexing against the live container. [VERIFIED: AGENTS.md][VERIFIED: docs/surrealdb-production-migration.md] |
| Production-derived artifact leakage in reports | Information Disclosure | Keep report paths intentional, support sample redaction, and separate readable snippets from raw metrics when needed. [VERIFIED: docs/surrealdb-production-migration.md][VERIFIED: docs/surrealdb-evaluation-harness.md] |
| Malformed JSON/JSONL evidence silently producing false gates | Tampering | Reuse existing strict loaders that fail fast with path and line information. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/devtools/surreal_migration_runner.py] |
| Path or ref dereference from `contains` anchors | Information Disclosure | Preserve the Phase 40 rule that `contains` is checked only against supplied evidence, never arbitrary filesystem reads during report generation. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: docs/surrealdb-evaluation-harness.md] |

## Sources

### Primary (HIGH confidence)

- Repo artifact set for Phases 40-42 and current dotMD code seams. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md][VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/src/dotmd/search/surreal_parity.py][VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: backend/devtools/surreal_migration_runner.py]
- Project constraints and runtime facts from `AGENTS.md`, `justfile`, `backend/pyproject.toml`, and live command probes. [VERIFIED: AGENTS.md][VERIFIED: justfile][VERIFIED: backend/pyproject.toml][VERIFIED: command]

### Secondary (MEDIUM confidence)

- SurrealDB official docs on `DEFINE INDEX`, search indexes, vector operators, and backups/recovery. [CITED: https://surrealdb.com/docs/reference/query-language/statements/define/indexes][CITED: https://surrealdb.com/docs/learn/data-models/full-text-search/search-indexes][CITED: https://surrealdb.com/docs/reference/query-language/language-primitives/operators][CITED: https://surrealdb.com/docs/manage/self-hosted/backups-and-recovery]
- Python official docs on `time`, `resource`, and `tracemalloc`. [CITED: https://docs.python.org/3/library/time.html][CITED: https://docs.python.org/3/library/resource.html][CITED: https://docs.python.org/3/library/tracemalloc.html]

### Tertiary (LOW confidence)

- None. All low-confidence planning recommendations are called out as `[ASSUMED]` in place. [VERIFIED: this document]

## Metadata

**Confidence breakdown:**

- Standard stack: HIGH - the recommended stack is almost entirely checked-in code and verified local tooling, with only narrow official-doc support for Surreal and Python measurement APIs. [VERIFIED: backend/src/dotmd/search/surreal_eval.py][VERIFIED: backend/src/dotmd/search/surreal_parity.py][VERIFIED: backend/src/dotmd/search/surreal_native.py][VERIFIED: command]
- Architecture: MEDIUM - the bounded evidence-window recommendation is a strong synthesis of Phases 40-42, but the end-to-end orchestrator does not exist yet. [VERIFIED: .planning/phases/40-evaluation-harness-and-golden-queries/40-01-SUMMARY.md][VERIFIED: .planning/phases/41-production-grade-surreal-schema-and-import/41-VERIFICATION.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-04-SUMMARY.md][ASSUMED]
- Pitfalls: HIGH - the major risks are directly exposed by AGENTS, Phase 40 acceptance semantics, Phase 41 transform-first rules, and Phase 42 non-cutover seams. [VERIFIED: AGENTS.md][VERIFIED: docs/surrealdb-evaluation-harness.md][VERIFIED: docs/surrealdb-production-migration.md][VERIFIED: .planning/phases/42-surreal-native-retrieval-implementation/42-VERIFICATION.md]

**Research date:** 2026-06-14
**Valid until:** 2026-06-21
