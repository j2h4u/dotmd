---
phase: "19"
plan: "04-latency-docs-verification"
type: execute
wave: 4
depends_on:
  - "03-developer-comparison-surfaces"
files_modified:
  - backend/src/dotmd/api/service.py
  - backend/tests/api/test_service_search.py
  - README.md
  - docs/architecture.md
  - .env.example
  - .planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md
autonomous: true
requirements:
  - RERANK-COMPARE-01
  - RERANK-LATENCY-01
must_haves:
  truths:
    - "Qwen CPU latency is visible in developer comparison output"
    - "Default production search remains single-reranker and qwen3-0.6b by name"
    - "Docs show how to run a comparison without requiring a production restart"
    - "Focused tests and ruff checks for all touched Phase 19 files pass"
    - "Phase summary records commands run and whether live CPU smoke was run or skipped"
  artifacts:
    - path: "README.md"
      provides: "developer comparison usage"
      contains: "dotmd rerank compare"
    - path: "docs/architecture.md"
      provides: "adapter/factory architecture description"
      contains: "RerankerProtocol"
    - path: ".planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md"
      provides: "execution summary and smoke status"
      contains: "Qwen CPU latency"
  key_links:
    - from: "comparison elapsed_ms"
      to: "Qwen CPU latency concern"
      via: "docs and summary"
      pattern: "elapsed_ms"
---

# Phase 19 Plan 04: Latency Diagnostics, Docs, and Verification

<objective>
Finish Phase 19 by tightening latency diagnostics, documenting the adapter/comparison workflow, and running focused verification.

The key business outcome is that dotMD can compare Qwen against alternates over the same candidate pool and see whether Qwen CPU latency is acceptable before making production decisions.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Comparison output contains elapsed time but docs do not tell developers how to use it | MEDIUM | README and architecture docs include the exact CLI and API paths. |
| Verification accidentally requires downloading all candidate models | HIGH | Unit tests mock providers; live smoke is optional and explicitly recorded as run or skipped. |
| Production restart happens during exploratory comparison | MEDIUM | Docs state comparison is developer-only and no restart is needed for local/container-side diagnostic runs. |
| Qwen latency concern is buried in logs only | HIGH | Comparison output and summary must include `elapsed_ms` and a Qwen-specific note. |
</threat_model>

<tasks>
<task id="1" type="auto" tdd="true">
<name>Task 1: Pin latency diagnostics and no-retrieval-repeat behavior</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
- `.planning/STATE.md`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
- `backend/tests/api/test_service_search.py`
</files>
<behavior>
- Test 1: each comparison row includes `elapsed_ms >= 0.0`.
- Test 2: Qwen comparison row contains `name == "qwen3-0.6b"` when configured.
- Test 3: comparing three rerankers still calls each retrieval engine at most once.
- Test 4: per-reranker output preserves ordered `top_chunk_ids` and `scores` lengths match `returned_count`.
</behavior>
<action>
Review `compare_rerankers()` and tests from Plan 03. Add missing invariants:

- `elapsed_ms` must be a float in milliseconds for every reranker.
- `returned_count == len(top_chunk_ids) == len(scores)` for successful rerankers.
- If a reranker errors, `returned_count == 0`, `top_chunk_ids == []`, `scores == []`, and `error` is non-empty.
- Engine call count tests prove the shared candidate pool is collected once for N rerankers.

Do not add model-specific benchmark thresholds. The observed Phase 18 Qwen smoke was about 20.8s with pool size 3, but this phase should report measured latency rather than fail on a hard threshold.
</action>
<verify>
<automated>cd backend && uv run pytest tests/api/test_service_search.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/tests/api/test_service_search.py` asserts `elapsed_ms`.
- `backend/tests/api/test_service_search.py` asserts `returned_count == len(top_chunk_ids)`.
- `backend/tests/api/test_service_search.py` asserts retrieval is not repeated per reranker.
- `cd backend && uv run pytest tests/api/test_service_search.py -q` exits 0.
</acceptance_criteria>
<done>
Latency and shared-pool invariants are pinned in tests.
</done>
</task>

<task id="2" type="auto">
<name>Task 2: Document adapter layer and developer comparison</name>
<read_first>
- `README.md`
- `docs/architecture.md`
- `.env.example`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-RESEARCH.md`
</read_first>
<files>
- `README.md`
- `docs/architecture.md`
- `.env.example`
</files>
<action>
Update docs with concrete Phase 19 behavior.

README requirements:
- Mention production default is a single reranker selected by `DOTMD_RERANKER_NAME=qwen3-0.6b`.
- Include CLI example:

```bash
dotmd search "пример запроса" --reranker msmarco-minilm
dotmd rerank compare "пример запроса" --rerankers qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual
```

- Explain comparison runs retrieval/fusion once and reports `elapsed_ms`, ordering, scores, and overlap.
- Say this is developer-only and does not make production serve multiple rerankers.

Architecture doc requirements:
- Add a short reranker adapter section naming `RerankerProtocol`, registry, factory/cache, and shared candidate pool.
- State that `DotMDService` owns selection and comparison through public service methods.
- State no indexes are reloaded per request.

`.env.example` requirements:
- Include `DOTMD_RERANKER_NAME=qwen3-0.6b`.
- Include `DOTMD_RERANKER_COMPARE_NAMES=qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual`.
</action>
<verify>
<automated>grep -R "dotmd rerank compare\\|RerankerProtocol\\|DOTMD_RERANKER_NAME" README.md docs/architecture.md .env.example</automated>
</verify>
<acceptance_criteria>
- `README.md` contains `dotmd rerank compare`.
- `README.md` contains `elapsed_ms`.
- `docs/architecture.md` contains `RerankerProtocol`.
- `docs/architecture.md` contains `shared candidate pool`.
- `.env.example` contains `DOTMD_RERANKER_NAME=qwen3-0.6b`.
- `.env.example` contains `DOTMD_RERANKER_COMPARE_NAMES=qwen3-0.6b,msmarco-minilm,mmarco-minilm,gte-multilingual`.
</acceptance_criteria>
<done>
Docs explain the adapter layer, runtime selection, and developer comparison commands.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Run focused checks and write Phase 19 summary</name>
<read_first>
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-01-reranker-protocol-registry-PLAN.md`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-02-shared-candidate-pool-PLAN.md`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-03-developer-comparison-surfaces-PLAN.md`
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-latency-docs-verification-PLAN.md`
</read_first>
<files>
- `.planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md`
</files>
<action>
Run focused verification:

```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py
```

Optional live CPU smoke only if the operator explicitly wants a real model run and the environment is ready:

```bash
dotmd rerank compare "русский тестовый запрос" --rerankers qwen3-0.6b,msmarco-minilm --top 3
```

Write `19-04-SUMMARY.md` with:
- what adapter/factory/comparison features shipped;
- commands run and pass/fail status;
- whether live Qwen CPU smoke was run or skipped;
- observed Qwen `elapsed_ms` if smoke was run;
- explicit note that production remains single-reranker by default.
</action>
<verify>
<automated>test -f .planning/phases/19-reranker-adapter-layer-and-multi-model-comparison/19-04-SUMMARY.md</automated>
</verify>
<acceptance_criteria>
- `19-04-SUMMARY.md` contains `Qwen CPU latency`.
- `19-04-SUMMARY.md` contains `production remains single-reranker`.
- `19-04-SUMMARY.md` contains `Commands run`.
- `19-04-SUMMARY.md` states `live CPU smoke was run` or `live CPU smoke was skipped`.
- Focused pytest command exits 0 or any failure is documented with exact failing test.
- Focused ruff command exits 0 or any failure is documented with exact failing file.
</acceptance_criteria>
<done>
Verification results and Qwen CPU smoke status are recorded for the phase.
</done>
</task>
</tasks>

<verification>
```bash
cd backend && uv run pytest tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py -q
cd backend && uv run ruff check src/dotmd/core/config.py src/dotmd/search/reranker.py src/dotmd/api/service.py src/dotmd/api/server.py src/dotmd/cli.py tests/test_reranker.py tests/test_hybrid_bm25.py tests/api/test_service_search.py tests/test_cli.py
grep -R "dotmd rerank compare\\|RerankerProtocol\\|DOTMD_RERANKER_NAME" README.md docs/architecture.md .env.example
```
</verification>

<success_criteria>
- Qwen latency is visible in comparison output and recorded in summary when smoke is run.
- Documentation shows runtime selection and developer comparison.
- Production remains single-reranker by default.
- Focused tests and lint checks pass or exact residual failures are recorded.
</success_criteria>
