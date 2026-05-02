---
phase: "20"
plan: "01-latency-benchmark-protocol"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/devtools/reranker_latency_bench.py
  - backend/tests/devtools/test_reranker_latency_bench.py
  - .planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md
  - .planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md
autonomous: true
requirements:
  - RERANK-LATENCY-02
  - RERANK-BENCH-01
requirements_addressed: [RERANK-LATENCY-02, RERANK-BENCH-01]
must_haves:
  truths:
    - "Canonical latency rows pin shared_pool_size=20 and top_n=3"
    - "Canonical benchmark uses one cold full-query pass plus three hot full-query passes per model"
    - "Hot production latency is evaluated from rerank_ms, not elapsed_ms"
    - "Cold load_ms is recorded separately for warmup/deploy policy"
    - "Slow or stuck models produce timeout/DNF rows instead of blocking the phase indefinitely"
    - "Exploratory pre-Phase-20 runs remain marked non-canonical"
    - "Phase 20 does not evaluate relevance quality or change the production default reranker"
  artifacts:
    - path: ".planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md"
      provides: "canonical benchmark ledger"
      contains: "shared_pool_size=20"
    - path: "backend/devtools/reranker_latency_bench.py"
      provides: "repeatable latency runner"
      contains: "QUERY_SET_V1"
    - path: ".planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md"
      provides: "latency shortlist summary"
      contains: "hot rerank_ms"
  key_links:
    - from: "rerank_ms"
      to: "production latency gate"
      via: "canonical benchmark summary"
      pattern: "p50/p95/max"
---

# Phase 20 Plan 01: Latency Benchmark Protocol

<objective>
Define and run a reproducible reranker latency benchmark that separates cold
model load from hot query reranking and produces a latency shortlist for later
quality comparison.

The key business outcome is that dotMD can stop debating reranker quality for
models that are operationally unusable on the current CPU-only production host.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Benchmark rows are not apples-to-apples because pool size or top count drifts | HIGH | Pin `shared_pool_size=20` and `top_n=3` in the runner, ledger, and summary. |
| Hot measurements are accidentally cold because each repeat uses a fresh process | HIGH | Runner keeps one child process and one `DotMDService` instance alive per model for all cold/hot passes. |
| Known-slow models block the phase for hours | HIGH | Runner enforces timeout/DNF rules and records timeout rows instead of waiting forever. |
| `elapsed_ms` total time is mistaken for production latency | HIGH | Summary ranks models by hot `rerank_ms`; `load_ms` is separate warmup evidence. |
| Quality judgments creep into latency phase | MEDIUM | Summary names only latency classes/shortlist; relevance quality is explicitly deferred. |
| A heavy model leaves memory pressure that biases the next model | MEDIUM | Runner executes one model per child process and records model sequence boundaries; executor records container/runtime state in the ledger. |
</threat_model>

<constants>
Canonical Protocol v1 constants:

- `query_set`: `QUERY_SET_V1`
- `query_count`: 10
- `mode`: `hybrid`
- `expand`: enabled
- `shared_pool_size`: 20
- `top_n`: 3
- `cold_passes`: 1 full pass over all 10 queries
- `hot_passes`: 3 full passes over all 10 queries
- `hot_samples_per_model`: 30
- `model_wall_timeout_s`: 900
- `hot_query_timeout_s`: 120
- `latency_bands`:
  - `fast`: p95 hot `rerank_ms` <= 10000
  - `acceptable`: p95 hot `rerank_ms` <= 30000
  - `slow`: p95 hot `rerank_ms` <= 120000
  - `unusable`: p95 hot `rerank_ms` > 120000, timeout, DNF, or provider error
- `quality_candidate_rule`: only `fast` and `acceptable` models enter the next
  quality bake-off by default; `slow` models require explicit user override.

Initial canonical model set:

- `msmarco-minilm`
- `mmarco-minilm`
- `mxbai-xsmall-v1`
- `mxbai-base-v1`
- `jina-v2-multilingual`
- `gte-multilingual`
- `bge-v2-m3`
- `qwen3-0.6b`
- `gte-modernbert-base`

If the model set is too slow in practice, executor may stop after timeout rows
for known-slow models; timeout/DNF is a valid latency result.
</constants>

<tasks>
<task id="1" type="auto">
<name>Task 1: Pin the canonical protocol and ledger fields</name>
<read_first>
- `.planning/phases/20-reranker-latency-benchmark/20-CONTEXT.md`
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `.planning/phases/20-reranker-latency-benchmark/20-REVIEWS.md`
- `.planning/ROADMAP.md`
</read_first>
<files>
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
</files>
<action>
Update `20-BENCHMARKS.md` so the canonical protocol block contains these exact
strings and values:

- `shared_pool_size=20`
- `top_n=3`
- `cold_passes=1`
- `hot_passes=3`
- `hot_samples_per_model=30`
- `model_wall_timeout_s=900`
- `hot_query_timeout_s=120`
- `fast: p95 rerank_ms <= 10000`
- `acceptable: p95 rerank_ms <= 30000`
- `slow: p95 rerank_ms <= 120000`
- `unusable: p95 rerank_ms > 120000, timeout, DNF, or provider error`

Add a pre-run checklist with these required fields:

- commit hash
- container name or runtime identifier
- benchmark runner command
- query set version
- model list
- `shared_pool_size`
- `top_n`
- `mode`
- expansion setting
- timeout settings
- raw output path

Keep all existing exploratory run sections and keep them marked non-canonical.
</action>
<verify>
<automated>rg --no-heading "shared_pool_size=20|top_n=3|hot_samples_per_model=30|model_wall_timeout_s=900|Exploratory Runs" .planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md</automated>
</verify>
<acceptance_criteria>
- `20-BENCHMARKS.md` contains `shared_pool_size=20`.
- `20-BENCHMARKS.md` contains `top_n=3`.
- `20-BENCHMARKS.md` contains `hot_samples_per_model=30`.
- `20-BENCHMARKS.md` contains `model_wall_timeout_s=900`.
- `20-BENCHMARKS.md` contains `hot_query_timeout_s=120`.
- `20-BENCHMARKS.md` still contains `Exploratory Runs Before Phase 20`.
</acceptance_criteria>
<done>
Benchmark ledger has a pinned canonical protocol and preserves exploratory evidence separately.
</done>
</task>

<task id="2" type="auto" tdd="true">
<name>Task 2: Add a repeatable latency benchmark runner</name>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/search/reranker.py`
- `backend/src/dotmd/core/config.py`
- `backend/devtools/mcp_client/cli.py`
- `backend/pyproject.toml`
</read_first>
<files>
- `backend/devtools/reranker_latency_bench.py`
- `backend/tests/devtools/test_reranker_latency_bench.py`
</files>
<behavior>
The runner must produce canonical JSON/JSONL rows without requiring manual log
parsing. It must keep one model warm across repeated queries so hot `rerank_ms`
is real.
</behavior>
<action>
Create `backend/devtools/reranker_latency_bench.py` with:

- `QUERY_SET_V1`: the exact 10 query strings from `20-CONTEXT.md`.
- `DEFAULT_RERANKERS`: the nine model names from the `<constants>` block.
- CLI arguments:
  - `--rerankers` comma-separated names, defaulting to `DEFAULT_RERANKERS`
  - `--output` path for JSONL rows
  - `--summary` path for Markdown summary
  - `--mode` default `hybrid`
  - `--top-n` default `3`
  - `--pool-size` default `20`
  - `--cold-passes` default `1`
  - `--hot-passes` default `3`
  - `--model-wall-timeout-s` default `900`
  - `--hot-query-timeout-s` default `120`
- One child process per model. Each child process must instantiate exactly one
  `DotMDService(Settings(rerank_pool_size=20))` for that model sequence.
- For each model child process:
  - run one cold full pass over all queries;
  - run three hot full passes over all queries;
  - call `service.compare_rerankers(query, [model], top_k=top_n, mode=mode, expand=True)`;
  - write one JSONL row per query/model/pass with `phase`, `query_set`,
    `query_index`, `query`, `model`, `model_name`, `pass_kind`, `pass_index`,
    `shared_pool_size`, `top_n`, `load_ms`, `rerank_ms`, `elapsed_ms`,
    `returned_count`, `error`, `timeout`, and `commit`.
- Parent process must enforce `model_wall_timeout_s`. If a child model process is
  still alive after 900 seconds, terminate it and write a DNF row with
  `timeout=true`, `error="model_wall_timeout_s exceeded"`, and the model name.
- Hot query rows with `rerank_ms > 120000` must be marked `timeout=true` and
  classified as `unusable` in the summary.
- Markdown summary must group by model and report p50, p95, max, error count,
  timeout count, and latency band using hot rows only.

Do not judge relevance quality. Do not change the production default reranker.
</action>
<verify>
<automated>cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/devtools/reranker_latency_bench.py` contains `QUERY_SET_V1`.
- `backend/devtools/reranker_latency_bench.py` contains `DEFAULT_RERANKERS`.
- `backend/devtools/reranker_latency_bench.py` contains `model_wall_timeout_s`.
- `backend/devtools/reranker_latency_bench.py` contains `hot_query_timeout_s`.
- `backend/tests/devtools/test_reranker_latency_bench.py` exists.
- `cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py -q` exits 0.
</acceptance_criteria>
<done>
Benchmark runner can produce canonical hot/cold latency rows and summary files.
</done>
</task>

<task id="3" type="auto">
<name>Task 3: Run canonical latency pass and append raw results to ledger</name>
<read_first>
- `backend/devtools/reranker_latency_bench.py`
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `backend/src/dotmd/search/reranker.py`
- `backend/src/dotmd/core/config.py`
</read_first>
<files>
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `.planning/phases/20-reranker-latency-benchmark/results/`
</files>
<action>
Run the canonical benchmark inside the current repository against the running
`dotmd` container/runtime. Before the run, ensure the container has code that
prints split `load_ms` and `rerank_ms`; because source is bind-mounted, restart
or force-recreate only when needed to load changed Python code.

Use this output layout:

- `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl`
- `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`

Run command:

```bash
cd backend && uv run python devtools/reranker_latency_bench.py \
  --output ../.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl \
  --summary ../.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md \
  --pool-size 20 \
  --top-n 3 \
  --cold-passes 1 \
  --hot-passes 3 \
  --model-wall-timeout-s 900 \
  --hot-query-timeout-s 120
```

Append a `## Canonical Run: 2026-05-01` section to `20-BENCHMARKS.md` with:

- commit hash from `git rev-parse --short HEAD`;
- command used;
- output JSONL path;
- output summary path;
- runtime/container notes;
- exact constants `shared_pool_size=20`, `top_n=3`, `cold_passes=1`,
  `hot_passes=3`, `model_wall_timeout_s=900`, `hot_query_timeout_s=120`;
- a short table copied from the generated summary.

If the full model list is too slow, the runner timeout rows are sufficient. Do
not manually omit slow models without recording that omission in the ledger.
</action>
<verify>
<automated>test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl</automated>
<automated>test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md</automated>
<automated>rg --no-heading "Canonical Run: 2026-05-01|shared_pool_size=20|hot_query_timeout_s=120" .planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md</automated>
</verify>
<acceptance_criteria>
- JSONL results file exists and is non-empty.
- Markdown summary file exists and is non-empty.
- `20-BENCHMARKS.md` contains `Canonical Run: 2026-05-01`.
- `20-BENCHMARKS.md` contains the JSONL results path.
- `20-BENCHMARKS.md` contains `shared_pool_size=20`.
- `20-BENCHMARKS.md` contains `hot_query_timeout_s=120`.
</acceptance_criteria>
<done>
Canonical latency run is captured in raw results and phase ledger.
</done>
</task>

<task id="4" type="auto">
<name>Task 4: Write latency shortlist summary and verify phase artifacts</name>
<read_first>
- `.planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md`
- `.planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md`
- `.planning/phases/20-reranker-latency-benchmark/20-CONTEXT.md`
- `.planning/phases/20-reranker-latency-benchmark/20-REVIEWS.md`
</read_first>
<files>
- `.planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md`
</files>
<action>
Write `20-01-latency-benchmark-protocol-SUMMARY.md` with:

- phase and plan frontmatter;
- commands run and pass/fail status;
- canonical constants used;
- per-model p50/p95/max hot `rerank_ms`;
- per-model max/cold `load_ms`;
- error and timeout counts;
- latency band per model;
- shortlist for later quality testing, using `fast` and `acceptable` bands by
  default;
- rejected or deferred models with exact reason (`slow`, `unusable`, `timeout`,
  `provider error`, or `not measured`);
- explicit note that Phase 20 made no relevance-quality judgment and did not
  change `DOTMD_RERANKER_NAME`.

Mention that p95 is an operational percentile from 30 hot samples per measured
model, not a statistically strong long-term SLO.
</action>
<verify>
<automated>test -f .planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md</automated>
<automated>rg --no-heading "hot rerank_ms|load_ms|p50|p95|quality testing|DOTMD_RERANKER_NAME" .planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md</automated>
<automated>cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py tests/test_reranker.py tests/api/test_service_search.py tests/test_cli.py -q</automated>
<automated>cd backend && uv run ruff check src devtools tests</automated>
</verify>
<acceptance_criteria>
- `20-01-latency-benchmark-protocol-SUMMARY.md` contains `hot rerank_ms`.
- `20-01-latency-benchmark-protocol-SUMMARY.md` contains `load_ms`.
- `20-01-latency-benchmark-protocol-SUMMARY.md` contains `p50`.
- `20-01-latency-benchmark-protocol-SUMMARY.md` contains `p95`.
- `20-01-latency-benchmark-protocol-SUMMARY.md` contains `DOTMD_RERANKER_NAME`.
- `20-01-latency-benchmark-protocol-SUMMARY.md` states that relevance quality was not evaluated.
- Focused pytest command exits 0 or exact failures are documented in the summary.
- Ruff command exits 0 or exact failures are documented in the summary.
</acceptance_criteria>
<done>
Phase 20 has a canonical latency summary and clear shortlist for the next quality phase.
</done>
</task>
</tasks>

<verification>
```bash
rg --no-heading "shared_pool_size=20|top_n=3|hot_samples_per_model=30|model_wall_timeout_s=900" .planning/phases/20-reranker-latency-benchmark/20-BENCHMARKS.md
cd backend && uv run pytest tests/devtools/test_reranker_latency_bench.py tests/test_reranker.py tests/api/test_service_search.py tests/test_cli.py -q
cd backend && uv run ruff check src devtools tests
test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency.jsonl
test -s .planning/phases/20-reranker-latency-benchmark/results/2026-05-01-rerank-latency-summary.md
rg --no-heading "hot rerank_ms|load_ms|p50|p95|quality testing|DOTMD_RERANKER_NAME" .planning/phases/20-reranker-latency-benchmark/20-01-latency-benchmark-protocol-SUMMARY.md
```
</verification>

<success_criteria>
- Canonical benchmark protocol is pinned and no longer depends on drifting config values.
- Runner records one cold full-query pass and three hot full-query passes per model.
- Slow models produce timeout/DNF rows instead of blocking execution indefinitely.
- Summary ranks models by hot `rerank_ms`, not total `elapsed_ms`.
- Quality comparison is deferred to a later phase and only receives the latency shortlist.
</success_criteria>
