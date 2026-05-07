# dotMD

## What This Is

Independent fork of [inventivepotter/dotmd](https://github.com/inventivepotter/dotmd) — a markdown knowledgebase search tool combining semantic search, BM25 keyword matching, and knowledge graph traversal. Deployed on a personal home server as search engine for voicenotes transcripts and documentation (~13,500 markdown files, bilingual RU/EN). Developed independently; upstream is a reference for ideas, not a merge target.

## Core Value

Fast, incremental search indexing — so the daily sync of new voicenotes doesn't bog down the server for 25 minutes. (Validated in v1.1 — incremental runs in <1s for typical daily changes.)

## Requirements

### Validated

- ✓ sqlite-vec vector store backend (replaces lancedb, no AVX2 needed) — feat/sqlite-vec-backend
- ✓ TEI-compatible external embedding server support — feat/sqlite-vec-backend
- ✓ MCP stdout fix (startup message to stderr) — fix/mcp-stdout, PR #1
- ✓ CPU-only Dockerfile (torch<2.5 for Ivy Bridge) — feat/sqlite-vec-backend
- ✓ Hybrid search working (semantic + BM25 + graph) — deployed
- ✓ First full index completed (226 files, 495 chunks, 3143 entities, 21020 edges)
- ✓ Incremental indexing — diff-based pipeline with `--force` override — Validated in Phase 2: Incremental Pipeline
- ✓ CLI progress reporting ("3 new, 1 modified, 0 deleted, 222 unchanged") — Validated in Phase 3: CLI & API Polish
- ✓ Status command with live change detection — Validated in Phase 3: CLI & API Polish
- ✓ API force parameter on POST /index — Validated in Phase 3: CLI & API Polish
- ✓ Fix BM25 results missing in hybrid mode — Validated in Phase 5: BM25 Hybrid Fix
- ✓ FalkorDB graph store adapter — Validated in Phase 4: FalkorDB Adapter + Config
- ✓ Graph backend config (`graph_backend`, `falkordb_url`) — Validated in Phase 4
- ✓ Pipeline integration for backend selection — Validated in Phase 4
- ✓ Docker networking for FalkorDB connectivity — Validated in Phase 6: Docker Integration + Migration
- ✓ Full re-index with FalkorDB (229 files, 3520 entities, 20269 edges) — Validated in Phase 6
- ✓ Production packaging — parameterized compose with bundled profiles, env-driven config, production include: pattern — Validated in Phase 7: Production Packaging
- ✓ Smoke tests — 5 external HTTP tests covering semantic/BM25/graph/hybrid/API — Validated in Phase 8: Smoke Tests
- ✓ Background trickle indexer — FTS5 incremental BM25, TOML config, watchdog + polling, progress reporting — Validated in Phase 10: Background Trickle Indexer
- ✓ Production packaging — parameterized compose with bundled profiles, .env.example, production include pattern — Validated in Phase 7
- ✓ SQLite WAL mode on all databases — Validated in Phase 7
- ✓ Smoke tests — 5 external HTTP tests (semantic/BM25/graph/hybrid/API) — Validated in Phase 8
- ✓ TEI concurrency benchmark — no gain, closed optimization path — Validated in Phase 9
- ✓ GLiNER batching benchmark — slower + OOM, closed optimization path — Validated in Phase 9
- ✓ FTS5 BM25 replacement — incremental keyword search, removed rank-bm25 dep — Validated in Phase 10
- ✓ Trickle indexer progress reporting — rate, ETA, CLI + API — Validated in Phase 10

### Active

- v1.5 Telegram Source Adapter — requirements and roadmap created. Next step:
  Phase 27 discussion for resource bindings and retained artifacts foundation.

### Out of Scope

- Concurrent TEI requests — benchmarked 2026-03-28, no gain (0.7→0.8 t/s within noise, TEI saturates all cores on single request)
- GLiNER batch NER — benchmarked 2026-03-28, batching slower than sequential (0.72 vs 0.53-0.61 t/s) and OOM at bs=8 on 16GB
- GPU acceleration — no GPU on current hardware, Jetson/Mac Mini is future consideration
- LadybugDB removal — keep as alternative embedded backend and for upstream compatibility
- Full QMD-style query expansion/reranking — different product philosophy
- Upstream PRs — fork has diverged too far (sqlite-vec, TEI, incremental indexing, schema migrations). Upstream is reference-only now

## Context

**Server:** senbonzakura, Xeon E3-1245 V2 (Ivy Bridge, 2012), 16GB RAM, no GPU. AVX yes, AVX2 no — constrains PyTorch (<2.5) and lancedb (Python wheels crash with SIGILL).

**Existing infrastructure reused:**
- TEI on port 8088 (intfloat/multilingual-e5-large, 1024-dim) — shared embedding server
- Docker compose deployment at /opt/docker/dotmd/
- Source at ~/repos/j2h4u/dotmd/

**Data:**
- /srv/knowledgebase/voicenotes/ — 227 voice recordings with transcripts (daily sync via voicenotes-sync)
- /home/j2h4u/ — docs, scripts, AGENTS.md, repos (mounted read-only)

**Upstream (reference only):**
- inventivepotter/dotmd: 11 commits (Jan 29-31 2026), inactive since. 26 stars, 5 forks, no license
- Useful as reference for graph search patterns and reranker tuning ideas
- PR #1 (MCP stderr fix) approved, PR #2 (LadybugDB lock fix) submitted

**Current index (after v1.2):**
- 229 files (voicenotes), 532 chunks, 3,520 entities, 20,269 edges
- Graph backend: FalkorDB @ redis://falkordb:6379/dotmd
- Full corpus: ~13,500 files (voicenotes + home) — only voicenotes indexed so far
- Full re-index (voicenotes): ~50 min via TEI
- Incremental (no changes): <1s
- Per-stage timing metrics in pipeline logs (run_id correlation)

**Performance baseline (voicenotes full index, v1.2):**
- Embedding via TEI: ~30 min (532 chunks, bs=4)
- NER (GLiNER): ~15 min on CPU
- Graph population (FalkorDB): ~5 min (20k edges)
- Total: ~50 min

## Constraints

- **CPU**: Xeon E3 V2 (Ivy Bridge) — no AVX2, limits ML library versions
- **RAM**: 16GB shared across all Docker services — TEI already uses ~2.6GB
- **Deployment**: Docker compose, build from fork
- **TEI required**: `DOTMD_EMBEDDING_URL` is mandatory — no local model fallback

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| sqlite-vec over lancedb | lancedb Python wheels require AVX2, server is Ivy Bridge | ✓ Good |
| TEI over local embeddings | Avoid 2GB model duplication in memory, reuse existing container | ✓ Good |
| Fork → independent project | Upstream inactive, architectural divergence too large for PRs | ✓ Good |
| TEI mandatory (no local fallback) | Prevent accidental 50-min local model indexing | ✓ Good |
| truncate:true for TEI | Chunks exceed 512 token limit of e5-large | ✓ Good — works but loses tail context |
| NER enabled (not structural-only) | Knowledge graph quality worth the CPU cost on first index | ⚠️ Revisit — 18min NER may not be worth it for incremental |
| Reuse global DotMDService in API | LadybugDB file lock prevents concurrent connections | ✓ Good — fixes /index endpoint crash |
| Pipeline timing metrics | No visibility into stage durations without instrumentation | ✓ Good — run_id correlation in logs |
| FalkorDB over LadybugDB (production) | LadybugDB file lock prevents concurrent CLI + API | ✓ Good — concurrent access works |
| FalkorDB adapter from scratch | LadybugDB Cypher dialect too different to port | ✓ Good — clean implementation |
| Keep LadybugDB as alternative | Embedded use case + upstream compatibility | — Ongoing |
| Remove reranker score threshold | Cross-encoder threshold silently dropped BM25 results | ✓ Good — all fusion candidates survive |
| TEI batch size auto-tuning | Avoid 413 errors, adapt to server capacity | ✓ Good — probe on first call |
| Compose profiles for bundled services | Optional TEI+FalkorDB via --profile bundled | ✓ Good |
| Production include directive | /opt/docker/dotmd/ references repo compose as source of truth | ✓ Good |
| FTS5 replaces rank_bm25+pickle | Incremental add/remove per chunk, no full-corpus rebuild | ✓ Good — removed numpy transitive dep |
| Concurrent TEI — no gain | Benchmarked 1/2/3 workers, TEI saturates all cores on single request | ✓ Good — closed optimization path |
| GLiNER batch — slower + OOM | Sequential 0.72 t/s vs batch 0.53-0.61 t/s, bs=8 OOM | ✓ Good — closed optimization path |
| Watchdog + polling for trickle indexer | inotify for immediate, hourly poll as fallback | ✓ Good |
| Source refs as public read/search identity | Non-filesystem sources should not inherit a path-shaped public API | ✓ Good — shipped in Phase 26 |
| Filesystem paths remain internal holder mechanics | Local discovery, reads, delete detection, and content-dedup still need paths | ✓ Good |
| Avoid full reindex for source-ref migration | Existing Phase 25 provenance was enough for lightweight backfill | ✓ Good |

## Shipped Milestones

- **v1.1** — Incremental Indexing (Phases 1-3, shipped 2026-03-26)
- **v1.2** — FalkorDB Migration & Search Fix (Phases 4-6, shipped 2026-03-27)
- **v1.3** — Production Packaging & Background Indexing (Phases 7-10, shipped 2026-03-28)
- **v1.4** — Search Quality & Architecture (Phases 15-26, shipped 2026-05-06)

## Current Milestone: v1.5 Telegram Source Adapter

**Goal:** Add Telegram as a first-class dotMD source with incremental search +
sync through the existing `mcp-telegram` runtime, while avoiding recomputation
of already-processed content and derived artifacts.

**Target features:**
- Content-addressed resource bindings and retained derived artifacts as the
  first infrastructure phase before Telegram.
- Telegram source discovery through existing `mcp-telegram`, not a new direct
  Telegram API client inside dotMD.
- Telegram search results return source refs that round-trip through
  `drill(ref)` / `read(ref, start, end)`.
- Repeated Telegram sync/refresh is incremental and reuses unchanged
  messages/chunks/derived artifacts.
- Telegram adapter hardening is scoped to what is needed for reliable read-only
  search + sync; full lifecycle edits/deletes/TTL can follow after real usage.

## Current State

v1.5 is active around Telegram source integration. v1.4 shipped and archived
the source-ref-first read/search contract, which is now the public identity
surface for this work. Backlog `999.25` and `SEED-002` are selected as
milestone context so Telegram does not inherit path-shaped holder semantics or
force wasted TEI/NER/FTS/graph recomputation for already-processed content.

The v1.5 roadmap has five phases:
1. Resource bindings and retained artifacts foundation.
2. Application source provider contract.
3. Telegram adapter MVP ingestion.
4. Incremental Telegram sync and reuse.
5. Telegram search/read/drill smoke.

Phase 999.12 complete (2026-04-27): Dual-encoder unified embedding shipped. Metadata-only changes (tag updates, title renames) now require 1 TEI call per document instead of N calls per chunk. VecComponentStore stores raw e_text/e_meta BLOBs; meta_tracker (title+tags checksum) triggers fast path when only metadata changes. search_log table added. 189 tests pass.

Phase 19 complete (2026-05-01): Reranking now has a provider protocol, stable-name registry, and cached factory. Production search remains single-reranker by default (`qwen3-0.6b`) while service, FastAPI, and CLI can select rerankers by name. Developer comparison runs multiple rerankers over one shared retrieval/fusion candidate pool and reports latency, errors, ordered IDs, scores, and overlap for Qwen-vs-alternate decisions.

Post-Phase 20 cleanup (2026-05-02): CPU-unusable latency candidates were removed
from the built-in reranker registry. The active comparison set is
`msmarco-minilm`, `mmarco-minilm`, and `mxbai-xsmall-v1`; default search now
uses `mmarco-minilm` pending the Phase 21 quality benchmark.

Phase 24 complete (2026-05-05): Configuration is now split conceptually between
deployment-bound operator config and internal tuning defaults. Runtime service
entry points validate required deployment values before serving, preserving the
single live container contract (`/mnt`, `/dotmd-index`, explicit indexing paths,
TEI URL, and FalkorDB URL when selected). Built-in indexing excludes are
preserved through `effective_indexing_exclude`, with additive
`indexing_extra_exclude` for operator-specific ignores. The restart safety gate
is now named `DOTMD_RUN_STARTUP_CHECKS`, while `ENVIRONMENT=dev` remains a
temporary compatibility alias.

Phase 26 complete (2026-05-06): The public search/read contract is now
source-ref-first. Search hits expose `ref` instead of public `file_paths`, MCP
agents use `search(query) -> ref -> drill(ref) / read(ref, start, end)`, and
CLI/API search surfaces no longer treat filesystem holder paths as public
identity. Filesystem paths remain only as internal discovery/read/delete/dedup
holder mechanics (`Chunk.file_paths` and `chunk_file_paths_<strategy>`).
The active strategy provenance gate backfilled missing lightweight
`chunk_source_provenance_contextual_512_50` rows without a full reindex and now
blocks incomplete provenance before search hydration.

## Evolution

This document evolves at phase transitions and milestone boundaries.

**After each phase transition** (via `/gsd:transition`):
1. Requirements invalidated? → Move to Out of Scope with reason
2. Requirements validated? → Move to Validated with phase reference
3. New requirements emerged? → Add to Active
4. Decisions to log? → Add to Key Decisions
5. "What This Is" still accurate? → Update if drifted

**After each milestone** (via `/gsd:complete-milestone`):
1. Full review of all sections
2. Core Value check — still the right priority?
3. Audit Out of Scope — reasons still valid?
4. Update Context with current state

---
*Last updated: 2026-05-07 after v1.5 roadmap creation*
