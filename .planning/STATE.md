---
gsd_state_version: 1.0
milestone: v1.8
milestone_name: SurrealDB-Native Storage Cutover
status: executing
stopped_at: Completed 42-02-PLAN.md
last_updated: "2026-06-14T07:52:16.941Z"
last_activity: 2026-06-14
progress:
  total_phases: 14
  completed_phases: 4
  total_plans: 14
  completed_plans: 12
  percent: 29
---

# GSD State

## Project Reference

See: .planning/PROJECT.md (updated 2026-05-08 after v1.6 roadmap creation)

**Core value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Current focus:** Phase 42 — surreal-native-retrieval-implementation

## Current Milestone

**v1.8 — SurrealDB-Native Storage Cutover**

Phase: 42
Status: Phase 42 executing; 42-02 complete
Last activity: 2026-06-14

Progress: [██████----] 57% (4/7 phases complete; Phase 42 executing; phases 43-45 remain to be planned)

## Deferred Items

Items acknowledged and deferred at v1.7 milestone close:

| Category | Item | Status |
|----------|------|--------|
| quick_task | 260510-0nb-adaptive-slot-quota-for-federated-search | unknown |
| todo | 2026-03-23-scout-other-dotmd-forks-for-ideas.md | pending |
| todo | 2026-03-27-background-trickle-indexer.md | pending |
| todo | 2026-03-27-smoke-tests.md | pending |
| todo | 2026-03-28-soft-delete-with-ttl-for-removed-source-files.md | pending |
| todo | 2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md | pending |
| seed | SEED-001-safe-migration-architecture | dormant |
| seed | SEED-002-promote-content-addressed-bindings-before-telegram | dormant |

## Performance Metrics

**Velocity:**

- Total plans completed: 70 (across all milestones)
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
| Phase 25 P04 | 6min | 4 tasks | 4 files |
| 25 | 4 | - | - |
| 26 | 3 | - | - |
| Phase 26 P01 | 13min | 3 tasks | 12 files |
| Phase 26 P02 | 20min | 3 tasks | 11 files |
| Phase 26 P03 | 11min | 4 tasks | 7 files |
| Phase 27 P01 | 8min | 3 tasks | 3 files |
| Phase 27 P03 | 7min | 3 tasks | 4 files |
| 27 | 4 | - | - |
| 28 | 4 | - | - |
| 29 | 4 | - | - |
| Phase 32 P01 | 6 min | 2 tasks | 3 files |
| Phase 32 P02 | 2 min | 2 tasks | 2 files |
| Phase 32 P03 | 2 min | 2 tasks | 4 files |
| Phase 32 P04 | 3 min | 2 tasks | 2 files |
| 33 | 3 | - | - |
| 35 | 2 | - | - |
| 36 | 2 | - | - |
| 37 | 4 | - | - |
| Phase 38 P01-current-data-inventory | 21 min | 3 tasks | 5 files |
| Phase 38 P05 | 10 min | 3 tasks | 6 files |
| Phase 38 P02 | 13 min | 2 tasks | 5 files |
| Phase 38 P03 | 21 min | 3 tasks | 3 files |
| 38 | 5 | - | - |
| Phase 40 P01 | 15 min | 3 tasks | 7 files |
| Phase 42 P01 | 6 min | 2 tasks | 5 files |
| 40 | 1 | - | - |
| Phase 42 P02 | 4min | 2 tasks | 4 files |

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

- Phase 26 added: Source-ref-first read/search contract cleanup
  (promoted from backlog 999.24)

- Phase 26 context gathered: remove the Phase 25 path-first compatibility layer
  before Telegram/non-filesystem source work; make `ref` / `(namespace,
  document_ref)` the primary public read/search identity; avoid full reindex
  whenever possible.

- Backlog 999.22 added: Document Source Abstraction — index non-filesystem
  sources. Architecture context is captured in `docs/source-adapter-architecture.md`
  and expert-panel review in `docs/source-adapter-architecture-panel-review.md`.

- Backlog 999.23 added: Semantic enrichment — extract commitments and
  agreements. Captures the need for structured extraction of agreements,
  promises, decisions, open questions, financial terms, and next steps from
  transcript chunks so important договорённости remain discoverable without
  remembering exact words like `65 на 35`.

- Backlog 999.24 added: Source-ref-first read/search contract — remove
  filesystem path compatibility layer. Captures the post-Phase 25 decision that
  dotMD has no external clients to protect, so the next source-adapter cleanup
  should make `ref` / `(namespace, document_ref)` the primary read/search
  contract before Telegram or other non-filesystem sources inherit a
  path-shaped API.

- Backlog `999.x` entries are documentation backlog items, not active phases;
  they should be promoted explicitly before planning/execution.

- Backlog 999.26-999.31 captured on 2026-05-08. They preserve the
  Airweave-inspired integration architecture thread as an ordered backlog line:
  source capability registry, source lifecycle/config/auth/cursor boundary,
  federated search candidate contract, filesystem unification, Telegram
  sync+federated unification, and an Airweave connector compatibility spike.
  These items are deliberately backlog only. After Phase 31 completion, current
  routing is milestone closeout first, then promotion of the unified source
  architecture backlog line in the next milestone when desired.

- Anti-legacy guardrail for Backlog 999.26-999.31: the architecture line must
  not create a second source plane beside existing filesystem and Telegram
  adapters. Filesystem and Telegram unification are required gates before broad
  third-party/Airweave connector work is considered architecturally complete.

- Phase 30 was deferred to Backlog 999.30 on 2026-05-08. Do not plan or execute
  Phase 30 as a Telegram-specific legacy incremental-sync phase. Its behavior
  should be reintroduced through the unified Telegram source contract after the
  registry/lifecycle/federated-search architecture line is promoted.

- Phase 31 completed on 2026-05-08. The live baseline smoke ingested 100
  Telegram messages, found real Telegram content through dotMD search, and
  verified the returned message-level ref through `drill(ref)` and `read(ref)`.
  The smoke fixed Telegram search ref hydration so search results now return
  refs like `telegram:dialog:-1003897013523:message:80` instead of the
  non-readable dialog-level ref.

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.
Recent decisions affecting current work:

- [Phase 38]: [Plan 38-01]: SQLite backup API is the required copied-snapshot strategy for WAL-mode source evidence. — Prevents silent loss of uncheckpointed WAL state while keeping live files read-only.
- [Phase 38]: [Plan 38-01]: Feedback counts remain on the supported CLI exporter path; `feedback.db` snapshots are file-level evidence only. — Preserves the feedback surface constraint from AGENTS.md.
- [Phase 38]: [Plan 38-01]: Falkor graph import planning must preserve semantic relation type in `rel_type` plus numeric `weight`. — Aggregate node/edge totals are insufficient for later transform-only import work.
- [v1.3]: Cross-encoder auto-calibrating score floor based on cosine distance distribution
- [v1.3]: E5 query/passage prefixes applied at embedding time
- [Research]: pplx-embed-context-v1-0.6B is candidate replacement (MIT, 596M, 1024-dim, context-aware, no prefix needed)
- [v1.4]: Evaluation framework before any model/pipeline changes -- measure first
- [Phase 11]: Auto-detect E5/BGE prefix need from model name; use_prefix defaults True for backward compat
- [Phase 11-embedding-model-swap]: GET /search (not POST) for eval scripts -- matches actual API
- [Phase 18]: Reranker replacement will use public benchmark evidence instead of local eval-set preparation. Publication age is now a hard gate; license is metadata-only for this personal-use project; `Qwen/Qwen3-Reranker-0.6B` is selected as the first implementation target because the top fresh rerankers are close enough in quality that text-only operational fit wins. ContextualAI rerank-v2 and Jina v3 remain real alternates if Qwen integration or latency fails.
- [Phase 25]: Canonical filesystem ref is document_ref = str(Path(file_path).resolve()) and ref = filesystem:<document_ref>. — Plans 25-01 through 25-04 use this invariant for SourceDocument identity and documentation.
- [Phase 25]: Phase 25 keeps MCP read(file_path, start, end) as the public filesystem read contract. — Plan 25-04 regression coverage and docs preserve user-visible filesystem compatibility.
- [Phase 26]: [Phase 26 Plan 01]: SearchResult exposes ref as the only public search-to-read key; Chunk.file_paths remains internal. — Core source-ref public contract for Phase 26.
- [Phase 26]: [Phase 26 Plan 01]: Missing search provenance is a hard ValueError after the count/dry-run/write safety gate. — Prevents silent fallback to internal holder paths.
- [Phase 26]: [Phase 26 Plan 01]: Service read(ref) is active-strategy-only for Phase 26. — Avoids scanning all chunk_file_paths strategy tables per request.
- [Phase 26]: [Phase 26 Plan 02]: MCP read/drill convert service ValueError into tool-level errors containing Action: pass a ref returned by search. — Keeps service errors domain-level while giving agents actionable MCP tool errors.
- [Phase 26]: [Phase 26 Plan 02]: FastAPI Plan 02 scope is /search only; no read route exists and no new drill route was invented. — Route enumeration found no FastAPI read route and the plan forbade inventing a new drill route without an existing facade pattern.
- [Phase 26]: [Phase 26 Plan 02]: Filesystem refs from live backfilled provenance may resolve from an existing file path when source_documents lacks the row. — Needed for search -> ref -> read to remain round-trippable on live backfilled provenance without a full reindex.
- [Phase 26]: [Phase 26 Plan 03]: Public MCP/docs contract is source-ref-first: search hits are { ref, heading?, snippet, score } and agents use drill(ref) plus read(ref, start, end). — Regression docs and live smoke closure.
- [Phase 26]: [Phase 26 Plan 03]: Optional graph/entity enrichment remains deferred from drill(ref) until a stable non-filesystem shape exists. — Avoids making filesystem graph internals part of the new public source contract.
- [Phase 26]: [Phase 26 Plan 03]: The first post-restart smoke failure was a startup/pre-flight reachability race, not a contract regression. — The same restart completed pre-flight and the final explicit live smoke passed without a second restart.
- [Phase 27]: Active public provenance is resolved by joining chunk_source_provenance tables to resource_bindings where active = 1. — Retained inactive provenance stays available for reuse while normal public output can filter it.
- [Phase 27]: Existing source_documents rows are backfilled into active resource_bindings during SQLiteMetadataStore readiness using non-overwrite conflict handling. — This prevents later active filtering from hiding existing Phase 26 refs on production databases.
- [Phase 27]: source_documents remains authoritative for active/current document metadata; resource_bindings stores activity state and fingerprint snapshots for retained lookup. — Plan 27-01 keeps metadata source-of-truth separate from binding lifecycle state.
- [Phase 27]: [Phase 27 Plan 03]: Public search filters inactive retained chunks before reranking and SearchResult hydration. — Internal engines may still return retained candidates, but public output is active-binding gated.
- [Phase 27]: [Phase 27 Plan 03]: read(ref) and drill(ref) require active resource bindings before source-document resolution, filesystem fallback, frontmatter reads, or chunk range reads. — Prevents retained filesystem artifacts from bypassing the public visibility gate.
- [Phase 27]: [Phase 27 Plan 03]: Binding diagnostics are count-only with active, inactive, retained, and reused keys. — No include_inactive, recycle-bin search, inactive read, or inactive list surface was added.
- [Phase 38]: [Plan 38-05]: Embedded Surreal probes use raw SurrealQL transactions via query_raw because the embedded SDK rejects client-side begin()/commit(). — The installed embedded SDK raises UnsupportedFeatureError for begin()/commit(), so the gate proves commit and rollback semantics through raw SurrealQL on a local surrealkv target instead.
- [Phase 38]: [Plan 38-05]: Same-target embedded writer safety is guarded with a sidecar JSON lock plus TTL stale recovery and explicit force-release. — Phase 38 needs explicit single-writer evidence before schema/import work, and the local guard preserves owner metadata for stale recovery and force-release reporting without touching live production volumes.
- [Phase 38]: Use a centralized Surreal record-ID codec so chunk IDs, refs, file paths, entity names, relation IDs, and feedback IDs remain data-only and cannot shape SurrealQL structure.
- [Phase 38]: Block Surreal apply writes on the 38-05 embedded safety gate and refuse migrate-ready evidence when the gate is missing or failed.
- [Phase 38]: Keep feedback import behind the supported provider/exporter abstraction instead of querying feedback.db directly.
- [Phase 38]: [Plan 38-03]: Weighted-field FTS mismatch is a blocking defer signal and cannot be treated as migrate-ready parity. — Representative copied-snapshot FTS evidence showed top-k visibility drift caused by title/tags weighting versus text-only proxy behavior.
- [Phase 38]: [Plan 38-03]: Retrieval parity must reuse copied snapshot rows and stored embeddings; no TEI calls or source indexing are allowed in the evidence path. — The parity harness used copied snapshot rows and fixed stored embeddings so the evidence measures storage behavior instead of recomputation.
- [Phase 38]: [Plan 38-03]: Hybrid/RRF parity comparisons normalize ties by score then chunk_id for deterministic evidence. — Stable tie ordering removes flaky rank drift so hybrid parity failures reflect real attribution gaps instead of incidental sort order.
- [Phase 40]: GoldenQueryCategory.GRAPH_ENTITY.value is the single serialized graph/entity category label.
- [Phase 40]: contains anchors are checked only against supplied snippets/read evidence and never by dereferencing corpus refs.
- [Phase 40]: Accepted regressions and unclear rows keep raw classification/gate while dropping out of unresolved aggregate counts once accepted.
- [Phase 42]: [Plan 42-02]: Surreal full-text scores are negated in-query so dotMD keeps descending higher-is-better tuple ordering.
- [Phase 42]: [Plan 42-02]: The embedded Surreal runtime requires validated literal HNSW top-k/ef values inside <|k,ef|>, while query vectors and embedding models stay bound as variables.

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

Backlog 999.24 captured on 2026-05-06. It preserves the legacy cleanup follow-up
from Phase 25: replace path-first public contracts like `SearchResult.file_paths`
and MCP `read(file_path)` with a source-ref-first read/search contract before
implementing Telegram read-only. Compatibility should be kept only where it
serves internal filesystem discovery, local file reads, display, delete
detection, or content-dedup holder semantics. Every dotMD refactor, new feature,
and bugfix should first be evaluated through the operational question: will
this require a full reindex or not? Planning should avoid full reindex whenever
possible: no `dotmd index --force`, full TEI re-embedding, metadata-vector
recomputation, or graph rebuild unless the plan proves there is no practical
incremental path and asks for an explicit user decision. Existing Phase 25
`source_documents` and `chunk_source_provenance_<strategy>` rows should be used
for source-ref migration wherever possible.

Phase 24 complete. It promoted backlog item `999.6` and delivered explicit
configuration separation: production/user-facing settings fail loudly when
missing, internal tuning constants no longer masquerade as operator config, and
startup/docs/templates now present the public config boundary clearly.

2026-05-02 housekeeping: active `.planning/phases/` now contains current
milestone phase artifacts only. Shipped v1.2/v1.3 phase artifacts were moved
under `.planning/milestones/`, and completed backlog implementation `999.12`
was moved under `.planning/notes/completed-backlog/`.

### Blockers/Concerns

No active phase blocker. Phase 38 completed the v1.7 storage simplification
spike and rejected Embedded SurrealDB as a single replacement backend because
retrieval parity failed on hybrid/RRF behavior.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260402-vua | Phase 14: Frontmatter-Driven Indexing | 2026-04-02 | af1794a | [260402-vua-phase-14-frontmatter-driven-indexing](./quick/260402-vua-phase-14-frontmatter-driven-indexing/) |
| 260425-rel | Убрать serve из start.sh — trickle lifespan в mcp_server.py, /health на 8080 | 2026-04-25 | 98c6b99 | [260425-rel-serve-start-sh-trickle-lifespan-mcp-serv](./quick/260425-rel-serve-start-sh-trickle-lifespan-mcp-serv/) |
| 260502-scv | Normalize dotMD .planning docs: separate active roadmap from backlog/done 999.x items, fix progress/health warnings where safe, keep historical phase artifacts intact | 2026-05-02 | this commit | [260502-scv-normalize-dotmd-planning-docs-separate-a](./quick/260502-scv-normalize-dotmd-planning-docs-separate-a/) |
| 260510-0nb | Adaptive slot quota for federated search merge — ensures tg:fts candidates appear in results despite heterogeneous score spaces | 2026-05-10 | 654cdf1 | [260510-0nb-adaptive-slot-quota-for-federated-search](./quick/260510-0nb-adaptive-slot-quota-for-federated-search/) |

---
*Last updated: 2026-06-12*

## Current Position

Phase: 42 (surreal-native-retrieval-implementation) — EXECUTING
Plan: 3 of 4
Status: Ready to execute 42-03-PLAN.md
Last activity: 2026-06-14 -- Completed 42-02-PLAN.md

## Operator Next Steps

- Execute `42-03-PLAN.md` for Phase 42.

## Session

**Last session:** 2026-06-14T07:52:16.916Z
**Stopped at:** Completed 42-02-PLAN.md
**Resume file:** None
