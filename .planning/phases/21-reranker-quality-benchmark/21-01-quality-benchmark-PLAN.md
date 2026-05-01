---
phase: "21"
plan: "01-quality-benchmark"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/devtools/reranker_quality_bench.py
  - backend/tests/devtools/test_reranker_quality_bench.py
  - .planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl
  - .planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md
  - .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl
  - .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md
  - .planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md
autonomous: true
requirements:
  - RERANK-QUALITY-01
  - RERANK-QUALITY-02
  - RERANK-QUALITY-03
requirements_addressed: [RERANK-QUALITY-01, RERANK-QUALITY-02, RERANK-QUALITY-03]
must_haves:
  truths:
    - "Benchmark uses the live dotMD index and does not run dotmd index --force"
    - "Canonical model list is exactly msmarco-minilm, mmarco-minilm, mxbai-xsmall-v1"
    - "msmarco-minilm is reported as a negative historical control"
    - "Each query uses one shared retrieval/fusion candidate pool across all rerankers"
    - "Quality metrics are rank-based: Hit@1, Hit@3, Hit@5, MRR@10, nDCG@10"
    - "Raw cross-encoder scores are not used as cross-model quality metrics"
    - "Hot rerank_ms is recorded as a guardrail but does not sort the quality summary"
  artifacts:
    - path: "backend/devtools/reranker_quality_bench.py"
      provides: "repeatable quality benchmark runner"
      contains: "DEFAULT_RERANKERS"
    - path: ".planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl"
      provides: "canonical human-readable query labels"
      contains: "relevant"
    - path: ".planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md"
      provides: "quality benchmark ledger"
      contains: "Hit@1"
  key_links:
    - from: "compare_rerankers"
      to: "shared candidate pool"
      via: "DotMDService"
      pattern: "shared_pool_size"
---

# Phase 21 Plan 01: Reranker Quality Benchmark

<objective>
Build and run a repeatable reranker quality benchmark against the live dotMD
index, using human-readable labels and one shared candidate pool per query, so
the project can choose between `mmarco-minilm` and `mxbai-xsmall-v1` while
keeping `msmarco-minilm` as the negative historical control.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Benchmark compares retrieval differences instead of reranker quality | HIGH | Runner must call `DotMDService.compare_rerankers()` or equivalent single-pool path once per query and reuse the same candidate IDs for all models. |
| Labels are ambiguous and make quality scores meaningless | HIGH | Label resolver fails on unresolved or multiply matched `file_path + contains` labels and records label coverage in the summary. |
| English-only public scores override real Russian quality | HIGH | Summary must state that `msmarco-minilm` is a negative historical control and lead with local Russian-corpus metrics. |
| Runner accidentally reindexes production data | HIGH | Plan forbids `dotmd index --force`; all runtime validation uses current container/index only. |
| Raw cross-encoder score scales are compared across models | MEDIUM | Metrics use rank positions only; raw scores may be stored for diagnostics but not used for model ranking. |
| Slow reranking hides in a quality-only report | MEDIUM | Every row records hot `rerank_ms`; summary reports p50/p95 beside quality metrics. |
</threat_model>

<constants>
Canonical Protocol v1 constants:

- `model_set`: `msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1`
- `negative_control`: `msmarco-minilm`
- `mode`: `hybrid`
- `expand`: enabled
- `shared_pool_size`: 20
- `top_n`: 10
- `minimum_queries`: 30
- `metrics`: `Hit@1`, `Hit@3`, `Hit@5`, `MRR@10`, `nDCG@10`
- `grade_map`: `relevant=2`, `maybe=1`, `irrelevant=0`
- `sort_metric`: `nDCG@10`, tie-break by `MRR@10`, then `Hit@3`, then lower p95 hot `rerank_ms`
</constants>

<tasks>
<task id="1" type="auto">
<name>Task 1: Create quality label file and benchmark ledger</name>
<read_first>
- `.planning/phases/21-reranker-quality-benchmark/21-CONTEXT.md`
- `.planning/phases/21-reranker-quality-benchmark/21-RESEARCH.md`
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `.planning/ROADMAP.md`
- `.planning/REQUIREMENTS.md`
</read_first>
<files>
- `.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
</files>
<action>
Create `21-LABELS.jsonl` with at least 30 JSONL rows. Each row must contain:

- `id`: stable string like `rq-001`
- `query`: Russian or mixed real-use query
- `category`: one of `setup`, `architecture`, `decision-history`, `weak-baseline`, `ambiguous`
- `relevant`: non-empty list of label objects
- `maybe`: optional list of label objects

Each label object must use one of these forms:

- `{"chunk_id": "..."}`
- `{"file_path": "...", "contains": "..."}`

Use query categories from `21-CONTEXT.md`. Favor Russian phrasing. Include
queries about MCP, ChatGPT, Claude/OAuth, Tailscale, sqlite-vec, FTS5, graph,
chunk cache, reranker selection, model latency, and Russian reranker quality.

Create `21-BENCHMARKS.md` with:

- canonical protocol constants from this plan
- model table with `msmarco-minilm`, `mmarco-minilm`, `mxbai-xsmall-v1`
- metric definitions for `Hit@1`, `Hit@3`, `Hit@5`, `MRR@10`, `nDCG@10`
- pre-run checklist requiring commit hash, container/runtime, query count,
  label coverage, shared_pool_size, top_n, model list, command, raw output path
- a section stating exactly: `msmarco-minilm is a negative historical control`
</action>
<verify>
<automated>test -s .planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl</automated>
<automated>python -c "import json, pathlib; rows=pathlib.Path('.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl').read_text(encoding='utf-8').splitlines(); [json.loads(row) for row in rows if row.strip()]"</automated>
<automated>rg --no-heading "Hit@1|MRR@10|nDCG@10|msmarco-minilm is a negative historical control|shared_pool_size=20|top_n=10" .planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md</automated>
</verify>
<acceptance_criteria>
- `21-LABELS.jsonl` contains at least 30 lines.
- Every label row contains `"query"` and `"relevant"`.
- `21-BENCHMARKS.md` contains `shared_pool_size=20`.
- `21-BENCHMARKS.md` contains `top_n=10`.
- `21-BENCHMARKS.md` contains `Hit@1`.
- `21-BENCHMARKS.md` contains `MRR@10`.
- `21-BENCHMARKS.md` contains `nDCG@10`.
- `21-BENCHMARKS.md` contains `msmarco-minilm is a negative historical control`.
</acceptance_criteria>
<done>
Phase 21 has a reviewable label set and benchmark ledger before code execution.
</done>
</task>

<task id="2" type="auto" tdd="true">
<name>Task 2: Implement the quality benchmark runner</name>
<read_first>
- `backend/devtools/reranker_latency_bench.py`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/core/config.py`
- `backend/tests/devtools/test_reranker_latency_bench.py`
</read_first>
<files>
- `backend/devtools/reranker_quality_bench.py`
- `backend/tests/devtools/test_reranker_quality_bench.py`
</files>
<behavior>
The runner must execute quality scoring without manual spreadsheet work. It
must fail loudly when labels cannot be resolved against the live index.
</behavior>
<action>
Create `backend/devtools/reranker_quality_bench.py` with:

- `DEFAULT_RERANKERS = ["msmarco-minilm", "mmarco-minilm", "mxbai-xsmall-v1"]`
- CLI arguments:
  - `--labels` path, required
  - `--output` path for JSONL rows, required
  - `--summary` path for Markdown summary, required
  - `--rerankers` comma-separated names, defaulting to `DEFAULT_RERANKERS`
  - `--mode` default `hybrid`
  - `--top-n` default `10`
  - `--pool-size` default `20`
  - `--commit` optional commit override
- JSONL label parser that accepts `chunk_id` labels and `file_path + contains`
  labels.
- Label resolver that uses `service._pipeline.metadata_store` and
  `get_chunks_for_file_range()` for `file_path + contains` labels.
- A clear error if a label resolves to zero chunks or more than one chunk.
- Metric functions:
  - `hit_at(ranked_ids, relevant_ids, maybe_ids, k)`
  - `mrr_at(ranked_ids, relevant_ids, maybe_ids, k=10)`
  - `ndcg_at(ranked_ids, relevant_ids, maybe_ids, k=10)`
- Per-query execution that calls
  `service.compare_rerankers(query, rerankers, top_k=top_n, mode=mode, expand=True)`.
- Output JSONL rows with `query_id`, `query`, `category`, `model`,
  `top_chunk_ids`, `top_file_paths`, `labels_by_rank`, `hit_at_1`,
  `hit_at_3`, `hit_at_5`, `mrr_at_10`, `ndcg_at_10`, `rerank_ms`, `error`,
  and `pool_miss`.
- Markdown summary sorted by `nDCG@10` descending, then `MRR@10`, then `Hit@3`,
  then lower p95 hot `rerank_ms`.

Do not compare raw model scores across rerankers. Raw scores may be stored for
diagnostics only.
</action>
<verify>
<automated>cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py -q</automated>
<automated>cd backend && uv run ruff check devtools/reranker_quality_bench.py tests/devtools/test_reranker_quality_bench.py</automated>
</verify>
<acceptance_criteria>
- `backend/devtools/reranker_quality_bench.py` contains `DEFAULT_RERANKERS`.
- `backend/devtools/reranker_quality_bench.py` contains `hit_at`.
- `backend/devtools/reranker_quality_bench.py` contains `mrr_at`.
- `backend/devtools/reranker_quality_bench.py` contains `ndcg_at`.
- `backend/devtools/reranker_quality_bench.py` contains `pool_miss`.
- `cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py -q` exits 0.
- `cd backend && uv run ruff check devtools/reranker_quality_bench.py tests/devtools/test_reranker_quality_bench.py` exits 0.
</acceptance_criteria>
<done>
Quality benchmark runner exists, is tested, and can produce raw rows plus a summary.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Run canonical quality benchmark on live index</name>
<read_first>
- `backend/devtools/reranker_quality_bench.py`
- `.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
- `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`
</read_first>
<files>
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl`
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
</files>
<action>
Run the canonical benchmark against the current live `dotmd` container and
current `/dotmd-index/index.db`. Do not run `dotmd index --force`.

Use this command shape, adjusting only the commit hash if needed:

`docker exec dotmd python /app/devtools/reranker_quality_bench.py --labels /app/.planning/phases/21-reranker-quality-benchmark/21-LABELS.jsonl --output /app/.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl --summary /app/.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md --rerankers msmarco-minilm,mmarco-minilm,mxbai-xsmall-v1 --mode hybrid --top-n 10 --pool-size 20 --commit $(git rev-parse --short HEAD)`

If `backend/devtools` is not mounted into the container, copy the committed
runner to `/app/devtools/reranker_quality_bench.py` before running, matching the
Phase 20 operational pattern.

Append the canonical result section to `21-BENCHMARKS.md` with:

- command
- commit hash
- runtime/container
- query count
- label resolution count
- model summary table
- per-query failure examples
- recommendation: promote one model, keep current default temporarily, or
  continue model search if neither survivor beats the negative control
</action>
<verify>
<automated>test -s .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl</automated>
<automated>test -s .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md</automated>
<automated>rg --no-heading "Canonical Run|Hit@1|MRR@10|nDCG@10|negative historical control|Recommendation" .planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md</automated>
</verify>
<acceptance_criteria>
- Raw JSONL result file exists and is non-empty.
- Markdown summary exists and is non-empty.
- `21-BENCHMARKS.md` contains `Canonical Run`.
- `21-BENCHMARKS.md` contains `Hit@1`.
- `21-BENCHMARKS.md` contains `MRR@10`.
- `21-BENCHMARKS.md` contains `nDCG@10`.
- `21-BENCHMARKS.md` contains `Recommendation`.
</acceptance_criteria>
<done>
Canonical Phase 21 quality benchmark is recorded against the live dotMD index.
</done>
</task>

<task id="4" type="auto">
<name>Task 4: Summarize decision and update phase state</name>
<read_first>
- `.planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`
- `.planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md`
- `backend/src/dotmd/core/config.py`
- `README.md`
- `docs/architecture.md`
</read_first>
<files>
- `.planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md`
- `.planning/STATE.md`
</files>
<action>
Create `21-01-SUMMARY.md` with:

- final quality table for all three models
- clear statement that `msmarco-minilm` was a negative historical control
- whether `mmarco-minilm` or `mxbai-xsmall-v1` beat the negative control
- whether default config should remain `mmarco-minilm`, switch to
  `mxbai-xsmall-v1`, or remain undecided pending more model search
- commands run and their pass/fail status

Update `.planning/STATE.md` pending todo section so Phase 21 is marked complete
only if the canonical benchmark ran and the summary exists.

Do not change `DOTMD_RERANKER_NAME` in this task unless the canonical quality
summary gives an explicit recommendation and tests are updated in the same
commit. If changing the default, also update `.env.example`, `README.md`,
`docs/architecture.md`, and `backend/tests/test_reranker.py`.
</action>
<verify>
<automated>test -s .planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md</automated>
<automated>rg --no-heading "negative historical control|Recommendation|Commands Run|Phase 21" .planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md .planning/STATE.md</automated>
<automated>cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py tests/test_reranker.py tests/api/test_service_search.py tests/test_cli.py -q</automated>
<automated>cd backend && uv run ruff check src devtools tests</automated>
</verify>
<acceptance_criteria>
- `21-01-SUMMARY.md` contains `negative historical control`.
- `21-01-SUMMARY.md` contains `Recommendation`.
- `.planning/STATE.md` contains `Phase 21`.
- Focused pytest command exits 0.
- Ruff command exits 0.
</acceptance_criteria>
<done>
Phase 21 records a quality-based reranker recommendation and leaves default config consistent with that recommendation.
</done>
</task>
</tasks>

<verification>
Run:

1. `cd backend && uv run pytest tests/devtools/test_reranker_quality_bench.py tests/test_reranker.py tests/api/test_service_search.py tests/test_cli.py -q`
2. `cd backend && uv run ruff check src devtools tests`
3. `test -s .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality.jsonl`
4. `test -s .planning/phases/21-reranker-quality-benchmark/results/2026-05-02-rerank-quality-summary.md`
5. `rg --no-heading "Hit@1|MRR@10|nDCG@10|Recommendation" .planning/phases/21-reranker-quality-benchmark/21-BENCHMARKS.md .planning/phases/21-reranker-quality-benchmark/21-01-SUMMARY.md`
</verification>

<success_criteria>
- The quality benchmark uses the live dotMD index, not a synthetic corpus.
- All three models are compared against the same per-query candidate pool.
- At least 30 labeled Russian/mixed queries are scored.
- Summary reports Hit@1, Hit@3, Hit@5, MRR@10, nDCG@10, and hot rerank latency.
- `msmarco-minilm` is documented as a negative historical control.
- The phase ends with a concrete recommendation for default reranker policy.
</success_criteria>
