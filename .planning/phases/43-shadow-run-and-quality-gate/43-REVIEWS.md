---
phase: 43
reviewers: [codex, opencode]
reviewed_at: 2026-06-14T18:26:36Z
plans_reviewed: [43-01-PLAN.md, 43-02-PLAN.md, 43-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 43

## Codex Review

**Summary**

The plans are directionally strong: they keep Phase 43 as an evidence/shadow-run phase, reuse Phase 40/41/42 seams, separate quality from scale/memory, and avoid premature cutover. The main risk is that 43-02 is trying to define a full capture runner, validation framework, CLI, docs, sentinel-ledger semantics, metrics replay, and scope guards all at once. The architecture is sound, but the runner plan needs a tighter executable boundary around what is fixture-only, what is real capture, and what exact inputs already exist before 43-03 starts.

**Strengths**

- Clear phase boundary: no production cutover, no runtime default flip, no fallback backend, no legacy deletion.
- Good dependency order: 43-01 metric contract, 43-02 runner, 43-03 actual evidence.
- Correct reuse of Phase 40 diff semantics and explicit acceptance rows.
- Good recognition that memory evidence needs guardrails, not just passive reporting.
- Strong fail-closed posture around missing metrics, malformed JSON/JSONL, incomplete ledgers, and unsafe production access.
- Good privacy awareness for production-derived refs/snippets/non-ASCII content.

**Concerns**

- **HIGH:** `accepted-diffs.jsonl` sentinel is useful for Phase 43 metadata, but the existing Phase 40 acceptance loader requires `query_id`, `accepted_by`, and `accepted_reason`. 43-02 says to strip sentinel rows before `run_eval()`, which is correct, but this is brittle enough to deserve explicit tests for "sentinel-only ledger passes shadow validation and does not reach Phase 40 acceptance loading."
- **HIGH:** 43-02's real capture behavior is underspecified. "Baseline capture uses old-stack service path against `--baseline-rehearsal-path`" needs to say exactly how that path is bound into `DotMDService` settings without mutating live config or accidentally indexing. Same for candidate capture: the plan names `target-url`, namespace, database, and overrides, but not the concrete connection lifecycle or whether it requires an already migrated target.
- **MEDIUM:** 43-02 is probably too large for one plan (orchestration, CLI, capture adapters, eval conversion, artifact validation, sentinel handling, docs, scope-guard tests). Increases the chance of shallow tests or a partially real runner.
- **MEDIUM:** Memory guardrail semantics are not fully defined. The constants are ratios/slack, but 43-01 does not define the comparison baseline for "candidate RSS growth ratio" or "heap growth ratio." If only one memory payload exists, growth ratios cannot be evaluated meaningfully.
- **MEDIUM:** 43-01 says `ShadowMetricBundle` requires Phase 38 scale fields, but `evaluate_surreal_scale_gate()` does not return the raw `representative` flag or raw latency list. If the bundle needs replay-window metadata and representative-corpus proof, that must be added outside the scale gate rather than assumed present.
- **MEDIUM:** 43-03 is `autonomous: false` (right for semantic acceptance), but Tasks 1 and 2 are still `auto`. The plan should make required external inputs explicit before execution: baseline rehearsal path, Surreal target, source-capture manifest, metrics replay descriptor, operator identity.
- **LOW:** Scope-guard tests asserting "no package installs" / "no `dotmd index --force`" / "no legacy deletion" can become brittle if implemented as raw source substring checks; should not replace behavioral tests.
- **LOW:** The docs plan should include a redaction/export policy for artifacts, not only a warning, to avoid committing production-derived snippets into `.planning`.

**Suggestions**

- Add a small preflight contract to 43-02: validate source manifest, baseline rehearsal path, candidate Surreal target, golden corpus, replay descriptor, artifacts dir before any capture.
- Split 43-02 (43-02a verify-only+sentinel filtering; 43-02b capture adapters + runbook).
- In 43-01, define memory comparison explicitly: require both baseline and candidate memory payloads with ratios comparing candidate to baseline, OR remove ratio guardrails from validation until paired evidence exists.
- Make `accepted-diffs.jsonl` schema explicit (sentinel record_type; real rows satisfy Phase 40 loader; runner writes filtered file or calls lower-level eval APIs).
- Add an artifact manifest/checksums in the sentinel to prove the eight files share one evidence window.
- For 43-03, add a "stop condition" artifact for missing prerequisites.

**Risk Assessment:** MEDIUM. Plans achieve the goal conceptually and preserve architectural boundaries. Main risks: execution complexity in 43-02 and ambiguity around real capture inputs, memory guardrail evaluation, and sentinel handling. None require redesign, but should be tightened before implementation.

---

## OpenCode Review

## Summary

The three plans form a coherent dependency chain: 43-01 defines metric contracts, 43-02 builds the orchestration runner, 43-03 executes the evidence window. Architecture correctly reuses Phase 40/41/42 seams and avoids cutover leak, recompute creep, and ad-hoc taxonomy. Main risk: the runner plan (43-02) is under-specified on rehearsal-path isolation and service initialization mechanics despite its 27-flag surface.

### Plan 43-01 — Strengths
Correct RED→GREEN TDD; embeds Phase 38 scale-gate field names; memory kept as separate nested object; `slots=True, frozen=True` matches convention; deterministic JSON writing; fail-closed `validate_shadow_metric_bundle()`; zero production dependencies.

### Plan 43-01 — Concerns
- **MEDIUM — Arbitrary guardrail constants.** `1.25` ratios and slack bytes have no documented derivation/rationale; recommend documenting in the dataclass docstring.
- **MEDIUM — `capture_shadow_memory_metrics` conflates "capture" with "definition."** Measurement (`perf_counter`, `getrusage`, `tracemalloc`) belongs in the runner (43-02), not the contract module. Clarify it is an optional helper, or move measurement to the runner.
- **LOW — `tracemalloc` requires explicit `tracemalloc.start()`** before `get_traced_memory()` returns useful values; a silent zero-valued heap report would satisfy presence checks but fail to provide evidence.
- **LOW — parent-directory creation** in the writer is consistent with `surreal_eval_runner.py` but ideally is the runner's responsibility.

### Plan 43-01 — Risk: LOW

### Plan 43-02 — Strengths
Reuses `run_eval(EvalRunnerConfig(...))`; sentinel-row design keeps `accepted-diffs.jsonl` non-empty while preserving Phase 40 strict semantics; `--verify-only`; baseline requires `--baseline-rehearsal-path` and fails hard; candidate uses overrides without changing `DotMDService.__init__`; separates quality corpus from replay window; service init once per capture process; threat model covers tampering/disclosure.

### Plan 43-02 — Concerns
- **HIGH — Rehearsal path isolation is underspecified.** Plan asserts "read-only from an isolated copied snapshot/rehearsal path" but does not specify how the runner *verifies* isolation. Needs at minimum: (a) refuse to run if `--baseline-rehearsal-path` matches production `DOTMD_INDEX_DIR`, and (b) `PRAGMA integrity_check` on rehearsal SQLite before use. Without these the "read-only" guarantee is aspirational.
- **HIGH — `DotMDService` instantiation for baseline capture is unexplored.** Plan says "may call private `DotMDService` comparison seams" but does not specify how the baseline service is constructed (Settings, MetadataStore, engines) pointed at the rehearsal index. Compare `surreal_migration_runner.py`'s explicit config. Highest-risk gap.
- **MEDIUM — 27 CLI flags is scope creep.** `--hnsw-ef`, `--embedding-dimension`, `--top-k`, `--pool-size` may be properties of the live target rather than runner flags; consider reading from the Surreal instance or a `--candidate-config-json`.
- **MEDIUM — `capture_eval_results_from_candidates` may reimplement existing logic.** Clarify whether it is pure field mapping (rename to `search_candidates_to_eval_results`) or does read-evidence/snippet work.
- **MEDIUM — sentinel filtering in `load_shadow_acceptance_ledger` needs explicit test cases:** sentinel-only, sentinel+acceptance, acceptance-only, malformed sentinel.
- **MEDIUM — `--metrics-replay-queries` is ambiguous** (path? size? descriptor?). Scale/memory metrics depend on it being well-defined; pin to `type=Path` JSONL.
- **LOW — `ShadowArtifactPaths` omitted from frontmatter `exports`** despite being in the dataclass list.
- **LOW — negative-space scope-guard tests** are hard to assert; prefer testing that importing the module triggers no side effects.

### Plan 43-02 — Risk: MEDIUM-HIGH (rehearsal-path isolation + service init are implementation blockers).

### Plan 43-03 — Strengths
Task 1 stop-on-unsafe-input clause; Task 3 blocking checkpoint with `resume-signal`; baseline/candidate `query_id` matching check; scope boundaries restated per task; ledger sentinel keeps file non-empty.

### Plan 43-03 — Concerns
- **HIGH — Phase 41 Surreal target prerequisite is unvalidated.** "Prepare one transform-first Surreal candidate target from Phase 41 evidence" — if Phase 41 hasn't produced a valid accessible target, the plan stalls at Task 1. Add an automated pre-flight verifying the target exists and passes a basic retrieval smoke before capture.
- **MEDIUM — No explicit checklist that the rehearsal path is a proper copy** (not a symlink to production; recent enough; expected file count).
- **MEDIUM — `test -s` only checks non-empty, not validity.** Corrupted JSON passes; add JSONL schema validation as a secondary check.
- **LOW — manual JSONL acceptance editing** is error-prone; consider an `--accept query_id ... --reason ...` helper.
- **LOW — critical rules** ("no regression accepted without reason"; "do not edit raw classifications") are buried in Task 3 action; pull into verification/success criteria.

### Plan 43-03 — Risk: MEDIUM

### Cross-Cutting
- Dependency ordering 43-01→43-02→43-03 is correct; no cycles.
- **Key gap: Rehearsal Path Contract** — all three plans mention "copied snapshot/rehearsal path" but none define what constitutes a valid copy (`cp -r`? SQLite backup? FS snapshot?). Single most important missing spec; affects baseline capture correctness for 43-02 and 43-03.
- `DEFAULT_SHADOW_MEMORY_GUARDRAILS` rationale must be traceable.
- No over-engineering detected; YAGNI discipline well-applied.

### Final Risk: MEDIUM. Implementation-ready after addressing the rehearsal-path contract specification.

---

## Consensus Summary

Both reviewers agree the phase is architecturally sound, correctly scoped to evidence-only (no cutover/fallback/legacy deletion), correctly ordered (43-01→43-02→43-03), and correctly reuses Phase 40/41/42 seams. Overall risk: **MEDIUM** from both. No redesign required. The convergent blocker is the **rehearsal-path / baseline-capture contract** in 43-02.

### Agreed Strengths
- Clean phase boundary: no production cutover, runtime default switch, fallback backend, or legacy deletion (both).
- Correct dependency ordering, contract-first then runner then execution (both).
- Reuse of Phase 40 `run_eval`/acceptance semantics rather than forking quality vocabulary (both).
- Fail-closed posture on missing/malformed metrics and ledgers (both).
- Production-derived data privacy awareness (both).

### Agreed Concerns (highest priority)
- **HIGH — Baseline capture mechanics underspecified (43-02).** Both reviewers independently flag that *how* `DotMDService`/old-stack baseline is bound to `--baseline-rehearsal-path` (without mutating live config or accidentally indexing) is not specified. OpenCode additionally requires enforced isolation (refuse if path == production `DOTMD_INDEX_DIR`; `PRAGMA integrity_check`). This is the dominant shared HIGH.
- **MEDIUM — Memory guardrail comparison baseline undefined (43-01).** Both note the `1.25` ratio/slack constants lack a defined comparison baseline (candidate-vs-baseline) and lack documented rationale; ratios are currently serializable but unevaluable.
- **MEDIUM — 43-02 scope/size.** Both note the runner plan is large (Codex: too many concerns in one plan; OpenCode: 27-flag surface), suggesting flag reduction or a split.
- **MEDIUM — Sentinel-row filtering needs explicit tests (43-02).** Both call for explicit RED cases covering sentinel-only / sentinel+acceptance / acceptance-only / malformed.

### Divergent Views
- **Memory-helper placement:** OpenCode wants `capture_shadow_memory_metrics` measurement logic moved out of the 43-01 contract module into the runner; Codex does not object to its location and instead focuses on defining the comparison baseline. Worth a deliberate decision rather than silent default.
- **Phase 41 target pre-flight:** OpenCode raises Surreal-target availability as a distinct HIGH for 43-03; Codex folds the same idea into a general "stop-condition artifact for missing prerequisites" (MEDIUM). Same remedy (automate a pre-flight), different severity.
- **Splitting 43-02:** Codex proposes a concrete 43-02a/43-02b split; OpenCode prefers flag reduction within one plan.

---

## Verification coverage

Source-grounding pass: every non-produced symbol/file the plans cite was checked against project source. Artifacts the plans declare they produce (the new metric module, the runner, the runbook, and the eight `artifacts/*` files) are excluded from MISSING verdicts.

| Cited symbol / file | Plan ref | Verdict | Evidence |
|---|---|---|---|
| `evaluate_surreal_scale_gate()` | 43-01 key_links | VERIFIED | `backend/src/dotmd/search/surreal_parity.py:435` |
| Scale-gate fields `failure_category`,`recommendation_gate`,`record_counts`,`hnsw_build_seconds`,`surrealkv_file_size_bytes`,`query_latency_p50_ms`,`query_latency_p95_ms` | 43-01 behavior | VERIFIED | `surreal_parity.py:437-490` (all field names present) |
| Representative-corpus flag in scale gate | 43-01 / Codex concern | VERIFIED | `surreal_parity.py:441,461-462` — `representative: bool`; emits "representative corpus flag" when absent |
| `passed` / `missing` scale fields | 43-01 behavior | VERIFIED | present in `surreal_parity.py` ScaleGate result mapping |
| `run_eval` + `EvalRunnerConfig` + `EvalRunResult` | 43-02 key_links | VERIFIED | `backend/devtools/surreal_eval_runner.py:27,40,151` |
| `build_surreal_native_engine_overrides()` | 43-02 key_links | VERIFIED | `backend/src/dotmd/search/surreal_native.py:18` |
| `EvalResult` dataclass + `top_refs`,`matched_engines` | 43-02/43-03 | VERIFIED | `backend/src/dotmd/search/surreal_eval.py:73,80,81` |
| Acceptance fields `query_id`,`accepted_by`,`accepted_reason` | 43-02/43-03 | VERIFIED | `surreal_eval.py:91-93,112-113` |
| `load_eval_results()` | 43-03 verify cmd | VERIFIED | `surreal_eval.py:311` |
| `backend/devtools/surreal_eval_runner.py` | 43-02 context/read_first | VERIFIED | file present |
| `backend/devtools/surreal_migration_runner.py` | 43-02 read_first | VERIFIED | file present |
| `backend/devtools/surreal_golden_queries.jsonl` (16 queries) | 43-02/43-03 | VERIFIED | file present, `wc -l` = 16 (matches "16-query" claim) |
| `backend/src/dotmd/api/service.py` (`DotMDService`) | 43-02 context | VERIFIED | file present |
| `docs/surrealdb-evaluation-harness.md` | 43-02/43-03 read_first | VERIFIED | present in `docs/` |
| `docs/surrealdb-production-migration.md` | 43-02/43-03 read_first | VERIFIED | present in `docs/` |
| Test files `test_surreal_eval_runner.py`,`test_surreal_migration_runner.py`,`test_surreal_retrieval_parity.py` | 43-01/43-02 read_first | VERIFIED | present under `backend/tests/` |
| Phase summaries 40-01, 41-03, 42-04; 42-VERIFICATION | 43-0x context | VERIFIED | all present under `.planning/phases/` |
| `surreal_shadow_metrics.py` + its symbols | produced by 43-01 | EXCLUDED (produced) | declared artifact |
| `surreal_shadow_runner.py` + symbols/flags, `docs/surrealdb-shadow-run-quality-gate.md` | produced by 43-02 | EXCLUDED (produced) | declared artifact |
| `artifacts/*.json(l)/.md` (8 files) | produced by 43-03 | EXCLUDED (produced) | declared artifacts |

**Coverage result:** 17 VERIFIED, 0 MISSING, 0 AMBIGUOUS, 0 UNCHECKABLE (3 produced-artifact groups correctly excluded). No plan cites a non-existent upstream symbol; all reuse seams resolve to real source. This corroborates both reviewers' "correct reuse of existing seams" assessment.
