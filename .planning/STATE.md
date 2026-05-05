---
gsd_state_version: 1.0
milestone: v1.4
milestone_name: Search Quality & Architecture
status: executing
last_updated: "2026-05-05T20:46:29.696Z"
last_activity: 2026-05-05
progress:
  total_phases: 11
  completed_phases: 10
  total_plans: 27
  completed_plans: 25
  percent: 93
---

# GSD State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-30 after v1.3 archived)

**Core value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Current focus:** Phase 25 — document-source-abstraction-source-adapter-mvp

## Current Milestone

**v1.4 — Search Quality & Architecture**

Phase: 25
Plan: Not started
Status: Executing Phase 25
Last activity: 2026-05-05

Progress: [█████████░] 93%

## Performance Metrics

**Velocity:**

- Total plans completed: 29 (across v1.1 + v1.2 + v1.3)
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
| Phase 24 P01-config-boundary-and-validation | 8 min | 3 tasks | 7 files |
| Phase 24 P02-startup-docs-and-template | 3 min | 3 tasks | 4 files |
| 24 | 2 | - | - |
| Phase 25 P01 | 4 min | 4 tasks | 5 files |
| Phase 25 P02 | 7 min | 5 tasks | 6 files |

## Accumulated Context

### Roadmap Evolution

- Phase 15 added: Content-addressed caching (embedding cache, extraction cache, content-based chunk_id)
- Phase 19 added: Reranker adapter layer and multi-model comparison
- Phase 20 added: Reranker Latency Benchmark
- Phase 21 added: Reranker Quality Benchmark
- Phase 23 added: Fix dotMD test contract
- Phase 24 added: Config separation — user-facing settings vs internal constants
  (promoted from backlog 999.6)

- Phase 25 added: Document Source Abstraction — source adapter MVP
  (promoted from backlog 999.22)

- Phase 25 context gathered: reproduce current filesystem Markdown behavior
  through the new source-aware model first; run an architecture panel on the
  domain model and contracts before implementation planning.

- Backlog 999.22 added: Document Source Abstraction — index non-filesystem
  sources. Architecture context is captured in `docs/source-adapter-architecture.md`
  and expert-panel review in `docs/source-adapter-architecture-panel-review.md`.

- Backlog 999.23 added: Semantic enrichment — extract commitments and
  agreements. Captures the need for structured extraction of agreements,
  promises, decisions, open questions, financial terms, and next steps from
  transcript chunks so important договорённости remain discoverable without
  remembering exact words like `65 на 35`.

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

Backlog 999.22 captured on 2026-05-04. It preserves the architecture context for
moving dotMD from file-centric markdown indexing to a source/document/source-unit
model with Telegram as the first intended MVP source. See
`docs/source-adapter-architecture.md` and
`docs/source-adapter-architecture-panel-review.md`.

Backlog 999.23 captured on 2026-05-05. It preserves the commitment/agreement
extraction idea from the Николай Сенин search failure and the `gpt-5.4-mini`
PoC: chunk-level extraction with overlap, followed by wider-window validation
and document-level consolidation into a structured semantic-enrichment layer.

Phase 24 complete. It promoted backlog item `999.6` and delivered explicit
configuration separation: production/user-facing settings fail loudly when
missing, internal tuning constants no longer masquerade as operator config, and
startup/docs/templates now present the public config boundary clearly.

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
*Last updated: 2026-05-05*
