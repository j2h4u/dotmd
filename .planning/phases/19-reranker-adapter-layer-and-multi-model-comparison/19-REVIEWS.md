---
phase: 19
reviewers: [opencode, claude]
reviewed_at: 2026-05-01T15:30:20+05:00
plans_reviewed:
  - 19-01-reranker-protocol-registry-PLAN.md
  - 19-02-shared-candidate-pool-PLAN.md
  - 19-03-developer-comparison-surfaces-PLAN.md
  - 19-04-latency-docs-verification-PLAN.md
---

# Cross-AI Plan Review - Phase 19

## OpenCode Review

### Phase 19 Cross-AI Plan Review

#### Plan 01: Reranker Protocol, Registry, and Factory

##### Summary
Plan 01 establishes the adapter boundary cleanly. It introduces `RerankerProtocol`, a stable name registry, and a factory/cache over the existing CrossEncoder implementation. The three-task breakdown (settings -> protocol/registry -> factory) is logical and TDD-first. The plan aligns well with the codebase's existing Protocol patterns in `storage/base.py` and its config/validation style.

##### Strengths
- Task ordering respects dependencies: settings first, then protocol, then factory.
- `Reranker = CrossEncoderReranker` compatibility alias prevents import breakage across the codebase.
- Factory caching by name prevents per-request model instantiation and directly addresses the main model-loading risk.
- Tests explicitly forbid model downloads via mocked `CrossEncoder`.
- Unknown name raises `ValueError` with available names.
- Five registry entries cover Qwen, MiniLM legacy, multilingual MiniLM, GTE, and BGE.

##### Concerns
- **MEDIUM**: `warmup()` method on `RerankerProtocol` is declared but `CrossEncoderReranker` does not currently have one. The plan says to add it, but the task description does not explicitly cover implementing `warmup()` on the concrete class.
- **MEDIUM**: `create_reranker("qwen3-0.6b", settings)` needs to extract `reranker_length_penalty`, `reranker_min_length`, and `reranker_relevance_floor` from settings; this wiring is mentioned but has no direct test.
- **LOW**: The `reranker_compare_names` default includes `gte-multilingual` and `bge-v2-m3`, but these models have not been smoke-tested locally. The registry accepts them without validation that they actually load via CrossEncoder.

##### Suggestions
- Add an explicit `warmup()` method to `CrossEncoderReranker` that delegates to `_load_model()`, and add a test for it in Task 3.
- Add a test that `create_reranker` passes `settings.reranker_length_penalty` and `settings.reranker_min_length` through to the constructed adapter.
- Consider adding a `description` field to the registry output and testing it if it remains part of `RerankerSpec`.

##### Risk Assessment: LOW
The plan is a pure boundary extraction with no intended behavior change. It is well-scoped and follows existing patterns.

#### Plan 02: Shared Candidate Pool and Single-Reranker Search Wiring

##### Summary
Plan 02 refactors `_execute_search` to extract a reusable candidate pool and wires `DotMDService` through `RerankerFactory`. This is the highest-risk plan because it touches the core search pipeline in `service.py`. The three-task structure is sound, but the merge-back logic is complex enough that the extraction deserves more detailed specification.

##### Strengths
- `RerankCandidatePool` as a `TypedDict` matches the local service pattern.
- Task 3 explicitly preserves merge-back and keyword-survival contracts.
- `_collect_candidate_pool` is explicitly forbidden from calling `load_index()`.
- Runtime `reranker_name` parameter defaults to `None`, preserving backward compatibility.
- `warmup()` refactor from direct private method access to factory-mediated warmup is directionally correct.

##### Concerns
- **HIGH**: The candidate pool extraction must handle graph enrichment timing. Graph enrichment appends to `fused` and mutates `engine_results`; the plan says the pool should contain both, but does not explicitly document whether the pool is captured after graph enrichment. If it is captured before enrichment, comparison rerankers will not see graph-enriched candidates and the comparison is invalid.
- **MEDIUM**: The blend/merge-back logic depends on fused scores. The plan does not show how `fused_scores = dict(fused)` translates once `fused` comes from the pool.
- **MEDIUM**: `rerank=False` should skip the factory entirely but still use the collected pool. The tests cover this, but the action description should state the path clearly.
- **LOW**: Existing `reranker_backend == "cross_encoder"` validation should move into the factory or creation path after the refactor.

##### Suggestions
- State explicitly that `_collect_candidate_pool` returns the pool after graph enrichment, with `pool["fused"]` including graph-appended candidates and `pool["engine_results"]` including the `"graph"` key.
- Add a test that `search(rerank=False)` returns results from `pool["fused"]` without touching the factory.
- Move `reranker_backend` validation into `create_reranker()` or `RerankerFactory.__init__`.
- Add a comment in the pool type noting that `fused` includes graph-enrichment appended candidates.

##### Risk Assessment: MEDIUM
The extraction touches complex normalization and merge-back logic. One error in how graph enrichment is captured would invalidate comparison results.

#### Plan 03: Developer Comparison Service, API, and CLI Surfaces

##### Summary
Plan 03 adds the developer-only comparison path: one retrieval/fusion pass, multiple rerankers applied to the same candidate pool, and latency/score/overlap diagnostics exposed through service, API, and CLI. The plan is well-structured and correctly identifies repeated retrieval as the core correctness risk.

##### Strengths
- Engine call count test directly mitigates the risk of repeated retrieval.
- Per-reranker error isolation ensures one failed model does not abort comparison.
- Overlap is computed from top chunk IDs rather than scores.
- Pydantic response models prevent untyped API JSON.
- CLI `rerank compare` follows existing nested command patterns.
- MCP schema remains unchanged, which is the right scope boundary.

##### Concerns
- **HIGH**: `RerankerComparison` `TypedDict` in the service and `RerankerComparisonResponse` Pydantic model in the API are defined separately. The API route does `RerankerComparisonResponse(**_get_service().compare_rerankers(...))`, which requires keys to match exactly. This is fragile and can fail or drop fields when the two definitions diverge.
- **MEDIUM**: The overlap key semantics are not specified. It should be clear whether keys mean overlap with the first reranker or pairwise overlaps.
- **MEDIUM**: The CLI comparison path creates a fresh service, while the API path reuses the warmed service. This is acceptable for a developer tool but should be documented because it affects latency.
- **LOW**: Unknown reranker names may propagate as a 500 from the API route unless `ValueError` is translated to a 400 response.

##### Suggestions
- Use `RerankerComparisonResponse.model_validate(comparison_dict)` or explicit field mapping instead of `**` unpacking.
- Add a 400 Bad Request handler for unknown reranker names in the API route.
- Clarify overlap key format in both service and response model docs.
- Consider adding `total_engine_calls` or similar diagnostics so developers can verify retrieval ran once.

##### Risk Assessment: MEDIUM
The service-level comparison is straightforward. The API/CLI wiring is mechanical, but schema drift and input validation should be tightened before execution.

#### Plan 04: Latency Diagnostics, Docs, and Verification

##### Summary
Plan 04 tightens latency test invariants, documents the adapter/comparison workflow, and runs final verification. This is the lightest plan, mostly documentation and verification with one test-hardening task.

##### Strengths
- Invariant `returned_count == len(top_chunk_ids) == len(scores)` is valuable.
- Phase summary records whether live CPU smoke was run or skipped.
- `.env.example` updates make new settings discoverable.
- Live smoke is optional and operator-gated.

##### Concerns
- **MEDIUM**: `README.md`, `docs/architecture.md`, and `.env.example` may not all exist in the expected structure. The plan does not require reading them first; `docs/architecture.md` may need to be created.
- **LOW**: Task 1 invariants overlap with Plan 03 tests, so the additional coverage may be small.
- **LOW**: `grep -R` is a weak acceptance check and can pass or fail for tool-specific regex reasons rather than doc correctness.

##### Suggestions
- Add `README.md`, `docs/architecture.md`, and `.env.example` to `read_first` in Task 2.
- If `docs/architecture.md` does not exist, create it with the reranker adapter section instead of failing.
- Prefer `uv run pytest --tb=short` when debugging failures.

##### Risk Assessment: LOW
Documentation and verification work with minimal code risk.

#### Overall Phase Assessment

##### Strengths
- Wave dependency ordering is correct: protocol -> pool -> comparison -> docs.
- Each plan has a threat model and focused tests.
- Factory cache prevents per-request model loading.
- Compatibility alias reduces import-breakage risk.
- The plans reference the current codebase with good specificity.

##### Cross-Cutting Concerns
1. **Graph enrichment timing (HIGH)**: Plans 02 and 03 must agree that the candidate pool captures fused results after graph enrichment. Otherwise comparison misses graph candidates.
2. **Error propagation from factory to API (MEDIUM)**: Factory `ValueError` should become API 400 and CLI-friendly output.
3. **TypedDict to Pydantic synchronization (MEDIUM/HIGH)**: Comparison output is defined twice, once as service `TypedDict` and once as API Pydantic model.
4. **Warmup for comparison rerankers (LOW)**: First comparison for non-default rerankers may include lazy model load time in `elapsed_ms`.

##### Overall Risk Assessment: MEDIUM
Plans 01, 03, and 04 are low-to-medium risk. Plan 02 is medium-risk due to the complexity of extracting the candidate pool from retrieval/fusion/graph-enrichment/rerank/merge-back behavior.

---

## Claude Review

### Summary

Four well-structured plans with correct wave ordering, consistent TDD framing, and a sound architectural goal. The factory/protocol boundary is the right abstraction, and the shared candidate pool correctly prevents the most common comparison invalidation mistake. The main risks are concentrated in the service/API translation layer, lazy model loading behavior for non-default rerankers, and one silent edge case in overlap computation. Nothing is blocking; these are implementation-level details a careful executor will hit.

### Strengths

- **Wave ordering is correct.** Protocol -> pool extraction -> surfaces -> verification is the valid dependency chain.
- **Shared candidate pool prevents false comparisons.** The `_collect_candidate_pool` constraint is the most important correctness invariant and is enforced via engine-call-count tests.
- **Factory cache prevents per-request model loading.** The `_instances: dict[str, RerankerProtocol]` pattern isolates model loading from request handling.
- **MCP left unchanged.** Not touching MCP schema for a developer-only feature is correct.
- **Error isolation in comparison.** Per-reranker `error` field with partial results is the right diagnostic shape.
- **Unknown name fails loudly with available names.** Silent fallback would hide operator mistakes.
- **TDD throughout.** Tasks specify behavior before action and use focused pytest invocations.

### Concerns

#### Plan 01

- **MEDIUM - `Reranker = CrossEncoderReranker` alias with no enforcement.** The alias means callers can still bypass the factory and construct models directly. The plan should mandate that all internal construction uses the factory by the end of Plan 01 Task 3, while keeping the alias only for compatibility.
- **MEDIUM - `reranker_model` override interaction is underspecified.** The factory spec says `settings.reranker_model` can override only when `reranker_name == "qwen3-0.6b"`, but behavior for custom model paths with other names is unclear.
- **LOW - `MetadataStoreProtocol` guard under `TYPE_CHECKING`.** This is fine for type annotations, but runtime use still needs the actual object available through the method argument.

#### Plan 02

- **MEDIUM - Empty pool handling is underspecified.** The current code has a `return []` path; the refactored flow should explicitly preserve it.
- **MEDIUM - Test names are referenced as acceptance criteria.** If the named tests are renamed during refactor, verification could pass a weaker suite. Prefer behavior descriptions or verify names exist before execution.
- **LOW - Warmup pre-loads only the default reranker.** Non-default comparison rerankers will load on demand during the first comparison, polluting latency. This is acceptable if documented.

#### Plan 03

- **HIGH - TypedDict service return unpacked into Pydantic response model.** `RerankerComparisonResponse(**_get_service().compare_rerankers(...))` is fragile if service `TypedDict` and API Pydantic model diverge. Make `compare_rerankers()` return a Pydantic model directly, use `model_validate`, or map fields explicitly.
- **MEDIUM - Overlap computation fails silently when the first reranker errors.** If the first reranker fails and returns no top IDs, all later overlap values become `0`, which looks like no overlap rather than no valid reference. Use the first successful reranker as the baseline or add an `overlap_reference` field.
- **LOW - `--top` vs `top_k` confusion in CLI.** Use consistent naming between CLI and service.
- **LOW - Chunk ID output readability.** Compact CLI tables should truncate or limit top chunk IDs.

#### Plan 04

- **MEDIUM - `docs/architecture.md` existence is assumed.** Add "create if not exists" or verify file existence before planning doc edits.
- **LOW - `grep -R` with `\|` alternation is tool-sensitive.** Use `grep -E` or `rg`.
- **LOW - Live smoke precondition is unstated.** The smoke command may trigger model downloads; the summary should say what was cached versus downloaded.

#### Cross-Plan

- **MEDIUM - `rerank_pool_size` setting is referenced without confirmation.** Confirm the exact setting exists in `Settings` before using it in `compare_rerankers`.
- **LOW - `tests/api/test_service_search.py` may not exist.** If it is only a role-match, plans should say "create if not present."

### Suggestions

1. **Plan 01, Task 3:** Mandate that `DotMDService.__init__` no longer imports `Reranker` directly by the end of the plan. Keep the alias only for compatibility and remove or de-emphasize it after factory wiring.
2. **Plan 01, Task 1:** Make `parsed_reranker_compare_names` validated at settings construction time, or clearly document why a property is enough.
3. **Plan 03, Task 1:** Change `compare_rerankers` return type from a service-only `TypedDict` to a Pydantic model or use explicit field mapping in the FastAPI route.
4. **Plan 03, Task 1:** If all rerankers error, return a valid comparison with `shared_pool_size` and per-reranker errors. If only the first reranker errors, use the next successful reranker as overlap reference.
5. **Plan 02, Task 2:** Consider `RerankerFactory.warmup_all(names)` and call it from `DotMDService.warmup()` with comparison names if clean latency diagnostics matter.
6. **Plan 04, Task 2:** Specify where README content belongs to avoid putting developer diagnostics into quickstart sections.
7. **Plan 04, Task 3:** Replace `grep -R` with `rg --no-heading`.

### Risk Assessment

**Overall: LOW-MEDIUM**

The architecture is sound. Wave ordering is correct. The shared candidate pool invariant is properly enforced. The risks are concentrated in two areas: the TypedDict-to-Pydantic translation in Plan 03, and the overlap edge case when the reference reranker fails. Neither is a blocker, but both are worth fixing in the plan before executor pickup. The remaining concerns are low-level implementation details that a careful executor would catch during TDD cycles.

---

## Consensus Summary

### Agreed Strengths

- Both reviewers found the four-wave dependency order correct: adapter/factory first, shared pool second, developer comparison surfaces third, and docs/verification last.
- Both reviewers agreed the shared candidate pool is the central correctness invariant for valid multi-reranker comparison.
- Both reviewers agreed the factory cache is the right protection against per-request model loading.
- Both reviewers agreed leaving the MCP tool schema unchanged is the right scope boundary for a developer-only comparison feature.
- Both reviewers found the plan set generally sound and executable with focused tests.

### Agreed Concerns

- **HIGH - TypedDict/Pydantic comparison schema drift:** Both reviewers raised that the service `TypedDict` and API Pydantic response model are defined separately. The plan should avoid fragile `**` unpacking by returning a shared Pydantic model, using `model_validate`, or explicitly mapping fields.
- **MEDIUM - Unknown-name and API error handling:** Both reviewers noted that factory `ValueError` should become a clean API 400 and CLI-friendly error rather than a traceback or 500.
- **MEDIUM - Cold-start latency for non-default comparison rerankers:** Both reviewers noted that comparison `elapsed_ms` can include first-load model latency unless non-default rerankers are warmed or the behavior is documented.
- **MEDIUM - Documentation/file existence assumptions:** Both reviewers noted that docs targets such as `docs/architecture.md` should be read first or created if absent.

### Divergent Views

- OpenCode classified graph enrichment timing in the candidate pool as **HIGH**, while Claude did not raise it as a high-severity concern. This should still be treated as a current unresolved HIGH because an incorrectly captured pool would invalidate the comparison feature.
- Claude emphasized overlap-reference behavior when the first reranker fails; OpenCode did not flag this. It is a useful Plan 03 refinement but not a shared HIGH.

### Current HIGH Concerns

- **Graph-enrichment candidate pool timing:** `_collect_candidate_pool` must explicitly return fused candidates after graph enrichment; otherwise comparison rerankers may receive an incomplete pool.
- **TypedDict/Pydantic comparison schema drift:** Service comparison output and API response schema should not rely on fragile `**` unpacking between separately maintained shapes.

CYCLE_SUMMARY: current_high=2
