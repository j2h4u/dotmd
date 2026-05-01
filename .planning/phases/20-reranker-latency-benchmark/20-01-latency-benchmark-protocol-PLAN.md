# Phase 20 Plan 01: Latency Benchmark Protocol

## Goal

Define and run a reproducible reranker latency benchmark that separates cold
model load from hot query reranking and produces a shortlist for later quality
comparison.

## Scope

- Document the canonical benchmark methodology.
- Maintain a phase-local ledger of all exploratory and canonical runs.
- Run a first canonical latency pass over technically connected rerankers.
- Summarize which models are worth quality testing next.

## Non-Goals

- Do not evaluate relevance quality.
- Do not switch the production default reranker.
- Do not tune fusion weights.

## Tasks

1. Create `20-BENCHMARKS.md` as the benchmark ledger.
2. Define the canonical query set and fixed runtime parameters.
3. Run canonical latency measurements with split `load_ms`, `rerank_ms`, and
   `elapsed_ms`.
4. Aggregate model-level p50/p95/max hot `rerank_ms` and error counts.
5. Write `20-01-SUMMARY.md` with the latency shortlist and rejected/blocked
   candidates.

## Canonical Protocol v1

- Runtime: current `dotmd` container.
- Mode: `hybrid`.
- Expansion: enabled.
- Shared candidate pool: current configured `DOTMD_RERANK_POOL_SIZE`.
- Returned top count: fixed for all runs; the returned count is diagnostic, not
  the workload.
- Repeats: one cold run followed by at least three hot runs per model.
- Primary metric: hot `rerank_ms`.
- Secondary metrics: `load_ms`, total `elapsed_ms`, returned count, errors.

## Initial Query Set v1

Use Russian and mixed-language questions that resemble actual MCP/search usage:

1. `как подключить MCP к ChatGPT`
2. `почему не работает OAuth reconnect`
3. `где описан reranker latency benchmark`
4. `как очистить oauth_state.json`
5. `что решили по Qwen reranker`
6. `найди заметки про FalkorDB graph backend`
7. `какие есть проблемы с русским поиском`
8. `как устроен content-addressed chunk cache`
9. `TEI embedding server CPU batch size`
10. `почему BM25 результаты должны переживать reranker`

## Success Criteria

- [ ] `20-BENCHMARKS.md` contains the canonical protocol and all known
      exploratory runs.
- [ ] Canonical run rows use the same query set and fixed runtime parameters.
- [ ] Summary reports per-model p50/p95/max hot `rerank_ms`.
- [ ] Summary explicitly separates cold load concerns from hot production
      latency.
- [ ] Summary names the shortlist for later quality comparison.
