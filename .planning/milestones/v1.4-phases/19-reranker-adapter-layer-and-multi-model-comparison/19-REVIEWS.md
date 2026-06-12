---
phase: 19
reviewers: [opencode, claude]
reviewed_at: 2026-05-01T15:44:14+05:00
cycle: 2
review_context: convergence cycle 2 after replanning
plans_reviewed:
  - 19-01-reranker-protocol-registry-PLAN.md
  - 19-02-shared-candidate-pool-PLAN.md
  - 19-03-developer-comparison-surfaces-PLAN.md
  - 19-04-latency-docs-verification-PLAN.md
---

# Cross-AI Plan Review - Phase 19 - Cycle 2

## OpenCode Review

# Cross-AI Plan Review: Phase 19 — Cycle 2

## Plan 01: Reranker Protocol, Registry, and Factory

### Summary

Clean, well-scoped foundation plan that extracts the adapter boundary without changing search behavior. TDD-first with clear test specifications. Minor test specification bug and an underspecified backward-compatibility override for `reranker_model`.

### Strengths

- Correct dependency ordering: protocol → registry → factory, nothing else depends on this yet
- Unknown-name `ValueError` with available names in message matches existing error patterns in `service.py:80`
- `Reranker = CrossEncoderReranker` alias preserves all existing imports
- Factory cache prevents per-request model loading
- Tests explicitly mock CrossEncoder — no model downloads

### Prior HIGH Resolution

N/A (this plan doesn't directly address prior HIGHs; they resolve in Plans 02-03)

### Concerns

- **MEDIUM — Test 3 specification bug:** Task 3 Test 3 reads `RerankerFactory(settings).get("qwen3-0.6b") is RerankerFactory(settings).get("qwen3-0.6b")` — this creates two separate factory instances, so identity will be `False`. The test should use a single factory instance: `factory = RerankerFactory(settings); factory.get(...) is factory.get(...)`.
- **MEDIUM — `reranker_model` override logic is vague:** Task 3 says "allow `settings.reranker_model` to override only if `settings.reranker_name == 'qwen3-0.6b'`" but doesn't define what that means when the env `DOTMD_RERANKER_MODEL` is explicitly set. The existing default is `reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"` — if someone has `DOTMD_RERANKER_MODEL=custom-model` but `DOTMD_RERANKER_NAME=qwen3-0.6b`, which wins? The executor needs a clear rule. Suggestion: registry name always wins; `reranker_model` is only used when `reranker_name` is unset/empty (a new escape hatch) or document that `reranker_model` is deprecated in favor of name-based selection.
- **LOW — Missing `reranker_backend` validation relocation:** `service.py:79-80` validates `reranker_backend == "cross_encoder"` and raises `ValueError`. When the factory replaces direct construction in Plan 02, this validation must move into the factory. Plan 02 Task 2 doesn't explicitly mention removing the inline validation.

### Suggestions

1. Fix the factory cache identity test to use one instance.
2. Add a brief paragraph in Task 3 defining the `reranker_model` vs registry name precedence rule explicitly.
3. Add an acceptance criterion in Plan 02 Task 2 that the inline `reranker_backend` validation is removed from `__init__` and handled by the factory.

---

## Plan 02: Shared Candidate Pool and Single-Reranker Search Wiring

### Summary

Correctly extracts the retrieval/fusion/enrichment pipeline into a reusable `_collect_candidate_pool` helper and wires search through `RerankerFactory`. The graph-enrichment timing invariant is well-specified in both behavior and acceptance criteria. Good regression guard with Plan 02 Task 3.

### Strengths

- Explicitly addresses the graph-enrichment HIGH: `_collect_candidate_pool` returns only after graph enrichment has appended to `fused`, and acceptance criteria require tests proving it
- `rerank=False` path explicitly skips factory lookup entirely — prevents accidental model loading
- Task 3 preserves existing test contracts (`test_candidates_beyond_pool_size_preserved`, `test_keyword_only_candidate_survives_low_reranker_score`)
- `RerankCandidatePool` as TypedDict is appropriate — private implementation detail, not exposed externally

### Prior HIGH Resolution

- **Graph-enrichment candidate pool timing: FULLY RESOLVED.** Plan 02 Task 1 acceptance criteria explicitly require: (1) `pool["fused"]` contains graph-appended candidates, (2) graph enrichment key exists in `pool["engine_results"]`, (3) comment/documentation that pool is post-graph-enrichment. This directly matches the invariant needed for valid comparison in Plan 03.

### Concerns

- **MEDIUM — `engine_results["graph"]` key semantics change:** Currently in `service.py:336`, `engine_results["graph"] = graph_hits` stores the raw graph enrichment hits (pre-dedup, with original scores). After extraction, the pool's `engine_results` will contain this same key. But `build_search_results` uses `engine_results` to attribute per-engine scores (see `fusion.py:180-181`). If graph enrichment adds chunk IDs that are NOT in the original `graph_hits` (because they're deduplicated in `fused`), the score attribution may be inconsistent. The current code only appends non-duplicate IDs to `fused` (line 333: `if cid not in fused_ids`), so this should be fine, but a test should verify it.
- **MEDIUM — `_collect_candidate_pool` is a `self` method but conceptually stateless:** The helper only reads `self._semantic_engine`, `self._keyword_engine`, etc. This is fine, but it should be documented that it does NOT mutate service state, since it will be called from both `search()` and `compare_rerankers()`.
- **LOW — `warmup()` only warms default reranker:** Plan 02 Task 2 changes warmup to `self._reranker_factory.get().warmup()`. Non-default comparison rerankers will have cold-start latency. This is acceptable for developer-only comparison, but Plan 04 docs should mention it.

### Suggestions

1. Add a brief docstring on `_collect_candidate_pool` stating it is read-only and does not mutate service state.
2. In Task 1, add a test verifying that graph-enriched chunk IDs in `pool["fused"]` have correct score attribution in `pool["engine_results"]`.
3. Remove the inline `reranker_backend` validation from `__init__` (lines 79-81 in current `service.py`) and ensure the factory handles it.

---

## Plan 03: Developer Comparison Service, API, and CLI Surfaces

### Summary

Solid implementation of the developer comparison path. The shared-pool invariant is enforced at the test level (engine call count). Schema drift protection between TypedDict and Pydantic is addressed via `model_validate` or explicit mapping with an explicit ban on `**` unpacking. CLI surface is well-scoped.

### Strengths

- `compare_rerankers` calls `_collect_candidate_pool` exactly once — the core correctness invariant
- Per-reranker error isolation: one failed reranker produces `error` but doesn't abort others
- Overlap reference explicitly uses the first *successful* reranker, not just the first configured
- All-reranker-failure edge case returns per-reranker errors with empty overlap, not misleading zero-overlap
- API unknown-name → 400 with factory message (not 500 traceback)
- CLI translates `ValueError` to `click.ClickException`
- Explicit ban on `RerankerComparisonResponse(**comparison)` in both action and acceptance criteria

### Prior HIGH Resolution

- **TypedDict/Pydantic comparison schema drift: FULLY RESOLVED.** Plan 03 Task 2 action explicitly states "Do not use `RerankerComparisonResponse(**comparison)` or other raw `**` unpacking" and requires either `model_validate` or explicit field-by-field mapping. Acceptance criteria include: "does not contain `RerankerComparisonResponse(**`" and "contains `RerankerComparisonResponse.model_validate` or explicit field-by-field response mapping." Test 5: "API response construction rejects or surfaces schema drift via Pydantic validation." This resolves the core concern.

### Concerns

- **MEDIUM — `model_validate` is asymmetric protection:** Pydantic v2 `model_validate` ignores extra dict keys and raises on missing required keys. If a field is added to the service TypedDict but not the Pydantic model, it's silently dropped without error. The reverse direction (Pydantic field missing from TypedDict) is caught. This is much better than `**` unpacking but not perfectly symmetric. Suggestion: add a test that intentionally adds an extra key to the TypedDict and asserts Pydantic raises or warns, or add `model_config = ConfigDict(extra='forbid')` to the response model.
- **LOW — Cold-start timing for non-default rerankers:** When comparing `msmarco-minilm` for the first time, `elapsed_ms` will include model download + first inference. The plan mentions recording `elapsed_ms` but doesn't distinguish warm vs cold runs in output. A `cold_start: bool` flag per reranker would help developers interpret results, but this is nice-to-have.
- **LOW — CLI `--rerankers` default is `None`, not config default:** `compare` command uses `rerankers: str | None = Query(None)` and falls back to `self._settings.parsed_reranker_compare_names`. This is correct, but the CLI help text should indicate what the default set is when `--rerankers` is omitted.

### Suggestions

1. Add `model_config = ConfigDict(extra="forbid")` to `RerankerComparisonResponse` for symmetric schema drift detection.
2. Consider adding a `warm: bool` or `cold_start: bool` field to `RerankerRunComparison` output so developers know whether `elapsed_ms` includes model loading.

---

## Plan 04: Latency Diagnostics, Docs, and Verification

### Summary

Appropriately scoped closing plan. Documentation targets are specific and the summary template captures the key business question (Qwen CPU latency). Live smoke is correctly optional. Verification commands are concrete.

### Strengths

- Explicitly records whether live CPU smoke was run or skipped
- Documentation reads existing files first (`docs/architecture.md` created only if absent)
- No hard latency thresholds — reports measured values instead
- Phase summary template captures the key decision input (Qwen `elapsed_ms`)

### Prior HIGH Resolution

N/A (this plan addresses docs and verification, not the core architectural HIGHs)

### Concerns

- **LOW — Test 5 in Task 1 duplicates Plan 03 Task 1 Test 5:** Both test overlap reference behavior when first reranker errors. Not harmful, but redundant. Consider referencing the Plan 03 test rather than re-specifying.
- **LOW — `docs/architecture.md` creation scope:** The plan says "create it with a concise `# Architecture` heading and the reranker adapter section." If the project later adds more architecture docs, this file will need reorganization. Consider a brief note that this is a seed file.

### Suggestions

1. Deduplicate the overlap-reference test between Plan 03 and Plan 04 Task 1 — reference the existing test rather than re-specifying.
2. In the summary template, add a field for "cold-start rerankers observed" to document which rerankers had first-load latency.

---

## Cross-Plan Assessment

### Prior HIGH Resolution Summary

| Prior HIGH | Status | Evidence |
|---|---|---|
| Graph-enrichment candidate pool timing | **FULLY RESOLVED** | Plan 02 Task 1: `_collect_candidate_pool` returns after graph enrichment; acceptance criteria require tests proving graph-appended candidates in `pool["fused"]` and graph key in `pool["engine_results"]` |
| TypedDict/Pydantic schema drift | **FULLY RESOLVED** | Plan 03 Task 2: explicit ban on `**` unpacking; requires `model_validate` or field-by-field mapping; acceptance criteria check for both the ban and the alternative |

### Dependency Ordering

Wave ordering is correct: 01 (factory) → 02 (pool + wiring) → 03 (comparison surfaces) → 04 (docs/verification). No circular dependencies. Each wave's acceptance criteria are sufficient to gate the next wave.

### New Concerns Introduced by This Plan Set

| Concern | Severity | Plan | Detail |
|---|---|---|---|
| Factory cache identity test bug | MEDIUM | 01 Task 3 | Test 3 creates two factory instances; identity check would fail |
| `reranker_model` override precedence | MEDIUM | 01 Task 3 | Underspecified interaction between `reranker_model` env var and registry name |
| Asymmetric Pydantic validation | MEDIUM | 03 Task 2 | `model_validate` silently drops extra TypedDict keys; `extra="forbid"` recommended |
| `engine_results["graph"]` score attribution | MEDIUM | 02 Task 1 | Graph-enriched chunks in `fused` may not have scores in `engine_results["graph"]` |

### Risk Assessment

**LOW risk overall.**

The plan set is well-structured with clear TDD, concrete acceptance criteria, and explicit prior-concern resolution. The four new MEDIUM concerns are all implementation-level details that will be caught during TDD execution — none are architectural risks. The wave ordering prevents invalid comparison states. Production behavior (single reranker) is preserved by explicit guardrails in every plan.

---

## Claude Review

## Phase 19 Plan Review — Cycle 2

### Summary

The four plans are well-structured and directly respond to cycle 1 feedback. The wave dependency ordering is correct. Plans 01-03 have clear TDD test specifications, and the high-risk design decisions (graph-enrichment timing, schema drift) now appear in acceptance criteria rather than just prose. Plan 04 is a clean verification wrap-up. The main risks are minor implementation ambiguities around the reranker model-override special-case, `top_chunk_ids` truncation boundary in comparison output, and a `read_first` reference to a file that may not exist yet. None of these are blockers, but the first two are worth tightening before execution.

---

### Strengths

- **TDD behavioral specifications are concrete.** Every task lists numbered test behaviors with exact assertions, not vague descriptions. Executors have enough signal to write tests before implementation.
- **Wave dependency enforcement is structural.** Each plan's `depends_on` field and task acceptance criteria reference artifacts from the prior wave, so partial execution is detectable.
- **Both prior HIGH concerns are fully addressed.** See section below.
- **Factory cache is specified correctly.** Per-instance (not global) cache on `RerankerFactory`, resolved by name via `get()`, prevents per-request model loading while allowing multiple concurrent factories in tests.
- **Schema drift protection is explicit.** Plan 03 bans `RerankerComparisonResponse(**comparison)` in acceptance criteria and requires `model_validate` or field-by-field mapping. This is testable at review time.
- **MCP unchanged boundary is held.** Plan 03 adds nothing to MCP tool schema, and the scope note is explicit.
- **Overlap reference fallback is specified.** The "first successful reranker" rule for `overlap_reference` when the lead reranker errors is in both the action and acceptance criteria of Plan 03.

---

### Prior HIGH Resolution

**HIGH — Graph-enrichment candidate pool timing**
**FULLY RESOLVED.**
Plan 02, Task 1 mandates that `_collect_candidate_pool` returns only after graph enrichment has appended to `fused` and updated `engine_results`. The acceptance criteria include a direct assertion: "asserts that `_collect_candidate_pool` returns graph-appended candidates in `pool['fused']` and includes the graph enrichment key in `pool['engine_results']`." The threat model also re-states this as HIGH severity, so an executor cannot miss it.

**HIGH — TypedDict/Pydantic comparison schema drift**
**FULLY RESOLVED.**
Plan 03, Task 2 acceptance criteria prohibits `RerankerComparisonResponse(**` and requires `model_validate` or an explicit field-by-field mapping listing all six fields by name. This is verifiable by grep at review time.

---

### Concerns

**MEDIUM — `reranker_model` override creates an undocumented special case**

Plan 01, Task 3 says: "allow `settings.reranker_model` to override only if `settings.reranker_name == 'qwen3-0.6b'`." No other registry entry has this override path. An operator who sets `reranker_name=msmarco-minilm` and `reranker_model=cross-encoder/custom-finetuned` will be silently ignored. This is asymmetric and invisible in logs. Options: (a) extend the override to any name as `model_name_override`, (b) keep the special case but log a warning when `reranker_model` is set but unused, or (c) drop the override entirely since the registry is the source of truth. Given the project's "no backward compat obligations" principle, option (c) is simplest—accept that existing `DOTMD_RERANKER_MODEL` env vars will be ignored for non-Qwen names.

**MEDIUM — `top_chunk_ids` truncation boundary in comparison output is ambiguous**

Plan 03, Task 1 says: "Pass the same `chunk_ids = [cid for cid, _ in pool['fused'][:pool_size]]` to each reranker." The `scores` and `top_chunk_ids` fields presumably reflect the reranker's output order, but neither Plan 03 nor Plan 04 specifies whether `top_chunk_ids` is truncated to `top_k` or returned at `pool_size` length. If it's `pool_size`, overlap comparisons could include candidates ranked 11-50 which are noise. If it's `top_k`, that should be explicit. The test in Plan 04 ("returned_count == len(top_chunk_ids) == len(scores)") pins the invariant but not the length. Suggest: Plan 03 Task 1 should add: "Truncate `top_chunk_ids` and `scores` to `top_k` before recording."

**MEDIUM — `_collect_candidate_pool` called from `compare_rerankers` without `expand` already applied**

Plan 03 Task 1 says "expand query once using the same `QueryExpander` logic as `search()`." Plan 02's `_collect_candidate_pool` signature takes `search_query` (already expanded) as an argument. The question is whether `compare_rerankers` calls `_collect_candidate_pool` with the pre-expanded query or re-expands internally. The two plans are consistent only if `compare_rerankers` does its own expansion before calling the pool helper. This should be explicit in Plan 03 Task 1's action, e.g., "Expand query with `_query_expander.expand(query)` before passing `search_query` to `_collect_candidate_pool`."

**LOW — `read_first` in Plan 04, Task 2 references a file that may not exist**

The action says "If `docs/architecture.md` exists, edit it in place... If it does not exist, create it." But `read_first` lists `docs/architecture.md` unconditionally. An executor's Read tool will error or return nothing if the file is absent. Change the read_first note to: "Read `docs/architecture.md` if it exists; skip otherwise."

**LOW — Factory cache has no failure isolation on first load**

If `create_reranker("qwen3-0.6b", settings)` raises (e.g., HuggingFace Hub unreachable in a new container), the exception propagates before any entry is written to `_instances`. A second call retries correctly. However, if the CrossEncoder constructor partially initializes and then raises, the `_instances` dict would have no entry, which is also correct. This is fine as-is, but worth a single test: "factory raises on first failed load, second call retries the same name."

**LOW — `click.pass_context` in Plan 03 Task 3 `compare` command is unexplained**

The CLI action declares `ctx: click.Context` in the function signature, but the action body doesn't use `ctx`. The executor will either delete it (correct) or leave dead code. The plan should either remove `ctx` from the signature or explain it is needed for, e.g., `ctx.obj["settings"]` if the service is constructed from context rather than a module-level getter.

---

### Suggestions

1. **Plan 01, Task 3:** Add a test that `settings.reranker_model` is only passed to the factory when `reranker_name == "qwen3-0.6b"`, and log a warning when it is set but unused. Or drop the override entirely and add a note in `.env.example` that `DOTMD_RERANKER_MODEL` is deprecated in favor of `DOTMD_RERANKER_NAME`.

2. **Plan 03, Task 1:** Add to the action: "Truncate `top_chunk_ids` and `scores` to `min(top_k, len(reranked))` before recording per-reranker results." Add a test: "comparison returns at most `top_k` chunk IDs per reranker."

3. **Plan 03, Task 1:** Clarify the action: "call `_query_expander.expand(query)` once to produce `search_query`, then pass it to `_collect_candidate_pool(search_query=search_query, original_query=query, ...)`."

4. **Plan 04, Task 2:** Change the `read_first` entry for `docs/architecture.md` to: "`docs/architecture.md` (read only if it exists; create if absent)."

5. **Plan 02, Task 2:** Consider adding a test that compares the `reranked=True` vs `reranked=False` log path specifically for the `pool["fused"]` post-graph-enrichment ordering. This verifies that the skip-reranker path doesn't accidentally use pre-graph-enrichment candidates.

---

### Risk Assessment

**Overall risk: LOW**

The prior two HIGH concerns are fully resolved in the plan text. The wave structure is sound. The factory/protocol boundary is architecturally clean and consistent with existing dotMD patterns. The remaining MEDIUM concerns are implementation detail ambiguities (override special-case, truncation boundary) that a careful executor could resolve inline, but they would be better closed in plan text before execution. There are no architectural dead-ends, no scope creep relative to the phase boundary, and no new unresolved HIGHs introduced.

---

## Consensus Summary

### Prior HIGH Resolution

Both reviewers agreed that the two HIGH concerns from cycle 1 are now fully resolved in the replanned Phase 19 artifacts.

| Prior HIGH | Cycle 2 Status | Evidence in Current Plans |
|---|---|---|
| Graph-enrichment candidate pool timing | FULLY RESOLVED | Plan 02 now requires `_collect_candidate_pool` to return only after graph enrichment and includes acceptance criteria proving graph-appended candidates are present in `pool["fused"]` and graph results are present in `pool["engine_results"]`. |
| TypedDict/Pydantic comparison schema drift | FULLY RESOLVED | Plan 03 now bans raw `RerankerComparisonResponse(**comparison)` unpacking and requires `model_validate` or explicit field-by-field mapping, with acceptance criteria that make this grep-verifiable. |

### Agreed Strengths

- The wave order is correct: protocol/registry/factory first, shared candidate pool second, developer comparison surfaces third, docs and verification last.
- The replanned acceptance criteria directly encode the earlier HIGH-risk invariants instead of leaving them as prose.
- The shared candidate pool remains the central correctness guard for valid reranker comparisons.
- The factory cache protects production search from per-request model loading while keeping the comparison feature developer-scoped.
- The MCP surface remains unchanged, preserving the intended phase boundary.

### Agreed Concerns

- MEDIUM - `reranker_model` versus `reranker_name` precedence remains underspecified. Both reviewers recommend making the name-based registry the clear source of truth, or explicitly documenting/logging the legacy override behavior.
- MEDIUM - Non-default comparison rerankers may include cold-start model load time in `elapsed_ms`. Both reviewers consider this acceptable for a developer tool if documented, but it should not be mistaken for steady-state inference latency.

### Additional Single-Reviewer Concerns

- MEDIUM - OpenCode found a factory cache identity test bug: the proposed assertion creates two factory instances, so the identity check should use a single factory instance.
- MEDIUM - OpenCode recommended `ConfigDict(extra="forbid")` on the API response model if `model_validate` is used, so extra service keys cannot be silently dropped.
- MEDIUM - OpenCode recommended a graph score-attribution test for graph-enriched candidates in `pool["fused"]` versus `pool["engine_results"]["graph"]`.
- MEDIUM - Claude recommended specifying that comparison `top_chunk_ids` and `scores` are truncated to `top_k`, not left at full pool size.
- MEDIUM - Claude recommended making query expansion order explicit: `compare_rerankers` should expand once before passing `search_query` into `_collect_candidate_pool`.
- LOW - Claude recommended making `docs/architecture.md` conditional in `read_first` because it may not exist before Plan 04.

### Divergent Views

- OpenCode emphasized schema-drift symmetry (`extra="forbid"`), while Claude considered the current `model_validate`/explicit mapping mitigation enough to resolve the prior HIGH.
- Claude emphasized comparison output truncation and query expansion sequencing, which OpenCode did not flag.
- OpenCode emphasized a concrete factory-cache test bug, which Claude did not flag.

### Current HIGH Concerns

None.

CYCLE_SUMMARY: current_high=0
