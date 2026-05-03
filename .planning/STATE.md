---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Search Quality & Architecture
status: complete
last_updated: "2026-05-03T12:01:32.699Z"
last_activity: 2026-05-03
progress:
  total_phases: 9
  completed_phases: 9
  total_plans: 21
  completed_plans: 21
  percent: 100
---

# GSD State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-30 after v1.3 archived)

**Core value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Current focus:** Phase 23 complete — Fix dotMD test contract

## Current Milestone

**v1.4 — Search Quality & Architecture**

Phase: 23
Plan: 1/1 complete
Status: Phase 23 complete
Last activity: 2026-05-03

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**

- Total plans completed: 27 (across v1.1 + v1.2 + v1.3)
- Average duration: ~3 min
- Total execution time: —

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 1-6 (v1.1+v1.2) | 10 | — | — |
| Phase 11 P02 | 2min | 2 tasks | 6 files |
| Phase 11-embedding-model-swap P01 | 2min | 2 tasks | 2 files |
| 999.12 | 3 | - | - |
| 18 | 1 | - | - |
| 19 | 4 | - | - |
| 22 | 1 | - | - |

## Accumulated Context

### Roadmap Evolution

- Phase 15 added: Content-addressed caching (embedding cache, extraction cache, content-based chunk_id)
- Phase 19 added: Reranker adapter layer and multi-model comparison
- Phase 20 added: Reranker Latency Benchmark
- Phase 21 added: Reranker Quality Benchmark
- Phase 23 added: Fix dotMD test contract
- Backlog `999.x` entries are documentation backlog items, not active phases;
  they should be promoted explicitly before planning/execution.

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [v1.3]: Cross-encoder auto-calibrating score floor based on cosine distance distribution
- [v1.3]: E5 query/passage prefixes applied at embedding time
- [Research]: pplx-embed-context-v1-0.6B is candidate replacement (MIT, 596M, 1024-dim, context-aware, no prefix needed)
- [v1.4]: Evaluation framework before any model/pipeline changes -- measure first
- [Phase 11]: Auto-detect E5/BGE prefix need from model name; use_prefix defaults True for backward compat
- [Phase 11-embedding-model-swap]: GET /search (not POST) for eval scripts -- matches actual API
- [Phase 18]: Reranker replacement will use public benchmark evidence instead of local eval-set preparation. Publication age is now a hard gate; license is metadata-only for this personal-use project; `Qwen/Qwen3-Reranker-0.6B` is selected as the first implementation target because the top fresh rerankers are close enough in quality that text-only operational fit wins. ContextualAI rerank-v2 and Jina v3 remain real alternates if Qwen integration or latency fails.

### Pending Todos

Phase 19 complete. Reranker adapter/factory refactor, shared retrieval pool, developer comparison surfaces, latency diagnostics, and docs are implemented and verified. Qwen CPU latency remains visible through comparison `elapsed_ms`.

Phase 20 complete. Canonical reranker latency benchmark results are recorded in
`20-BENCHMARKS.md` and `results/2026-05-01-rerank-latency-summary.md`.
Historical latency shortlist before Phase 21 quality testing: `msmarco-minilm`,
`mmarco-minilm`, `mxbai-xsmall-v1`. Relevance quality was not evaluated in
Phase 20 and `DOTMD_RERANKER_NAME` was changed to `mmarco-minilm` during
post-Phase 20 cleanup after CPU-unusable candidates were removed from the
built-in registry.

Phase 21 complete. Canonical live-index quality benchmark results are recorded
in `21-BENCHMARKS.md` and
`results/2026-05-02-rerank-quality-summary.md`. `mmarco-minilm` beat the
negative historical control on `nDCG@10` and remains the only production
reranker. `mxbai-xsmall-v1` was competitive on `Hit@3`/`MRR@10` but slower on
CPU and was removed from production candidates. The run also exposed 9
retrieval-gap pool_miss queries for future retrieval work.
Post-Phase 21 cleanup made `mmarco-minilm` the only production built-in
reranker and moved the full staged benchmark methodology to
`docs/reranker-benchmark-methodology.md`.

Phase 22 promoted from backlog item `999.21`. It targets mid-sentence search
snippet truncation and should use feedback id=6, id=10, and fresh open feedback
id=19 as source context. Planning should decide whether to improve default
snippet boundaries only, add optional context controls, or include match
marking.

2026-05-02 housekeeping: active `.planning/phases/` now contains current
milestone phase artifacts only. Shipped v1.2/v1.3 phase artifacts were moved
under `.planning/milestones/`, and completed backlog implementation `999.12`
was moved under `.planning/notes/completed-backlog/`.

### Blockers/Concerns

None for current local GSD state.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260402-vua | Phase 14: Frontmatter-Driven Indexing | 2026-04-02 | af1794a | [260402-vua-phase-14-frontmatter-driven-indexing](./quick/260402-vua-phase-14-frontmatter-driven-indexing/) |
| 260425-rel | Убрать serve из start.sh — trickle lifespan в mcp_server.py, /health на 8080 | 2026-04-25 | 98c6b99 | [260425-rel-serve-start-sh-trickle-lifespan-mcp-serv](./quick/260425-rel-serve-start-sh-trickle-lifespan-mcp-serv/) |
| 260502-scv | Normalize dotMD .planning docs: separate active roadmap from backlog/done 999.x items, fix progress/health warnings where safe, keep historical phase artifacts intact | 2026-05-02 | this commit | [260502-scv-normalize-dotmd-planning-docs-separate-a](./quick/260502-scv-normalize-dotmd-planning-docs-separate-a/) |

---
*Last updated: 2026-05-02*
