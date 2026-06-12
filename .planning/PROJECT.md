# dotMD

## What This Is

Independent markdown knowledgebase search tool descended from the former `inventivepotter/dotmd` upstream. GitHub fork-network linkage has been removed; dotMD is now a standalone repository combining semantic search, BM25 keyword matching, and knowledge graph traversal. Deployed on a personal home server as search engine for voicenotes transcripts and documentation (~13,500 markdown files, bilingual RU/EN).

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
- ✓ FalkorDB runtime config (`falkordb_url`) — Validated in Phase 4 and simplified in Backlog 999.32
- ✓ Pipeline integration for the current SQLite/sqlite-vec + FalkorDB storage stack — Validated in Phase 4 and simplified in Backlog 999.32
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
- ✓ v1.7 Storage Simplification decision spike — Embedded SurrealDB is not a
  safe single replacement backend today; final recommendation is reject due to
  hybrid/RRF retrieval parity gap — Validated in Phase 38

### Active

- No active phase. Start a new milestone before the next storage architecture
  change.

### Out of Scope

- Concurrent TEI requests — benchmarked 2026-03-28, no gain (0.7→0.8 t/s within noise, TEI saturates all cores on single request)
- GLiNER batch NER — benchmarked 2026-03-28, batching slower than sequential (0.72 vs 0.53-0.61 t/s) and OOM at bs=8 on 16GB
- GPU acceleration — no GPU on current hardware, Jetson/Mac Mini is future consideration
- Reintroducing alternative storage backends for compatibility without a current
  migration or operational need
- Full QMD-style query expansion/reranking — different product philosophy
- Upstream PRs — project has diverged too far (sqlite-vec, TEI, incremental indexing, schema migrations). Former upstream is historical reference only

## Context

**Server:** senbonzakura, Xeon E3-1245 V2 (Ivy Bridge, 2012), 16GB RAM, no GPU. AVX yes, AVX2 no — constrains PyTorch (<2.5) and lancedb (Python wheels crash with SIGILL).

**Existing infrastructure reused:**
- TEI on port 8088 (intfloat/multilingual-e5-large, 1024-dim) — shared embedding server
- Docker compose deployment at /opt/docker/dotmd/
- Source at ~/repos/j2h4u/dotmd/

**Data:**
- /srv/knowledgebase/voicenotes/ — 227 voice recordings with transcripts (daily sync via voicenotes-sync)
- /home/j2h4u/ — docs, scripts, AGENTS.md, repos (mounted read-only)

**Origin history (reference only):**
- Descended from `inventivepotter/dotmd` (11 commits, Jan 29-31 2026). The GitHub fork relationship has been detached.
- Historical source is useful only as context for early graph search and reranker ideas.
- Old upstream PRs are no longer part of the active maintenance model.

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
- **Deployment**: Docker compose, build from this repository
- **TEI required**: `DOTMD_EMBEDDING_URL` is mandatory — no local model fallback

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| sqlite-vec over lancedb | lancedb Python wheels require AVX2, server is Ivy Bridge | ✓ Good |
| TEI over local embeddings | Avoid 2GB model duplication in memory, reuse existing container | ✓ Good |
| Fork-network detach → independent repository | Former upstream inactive, architectural divergence too large for PRs | ✓ Good |
| TEI mandatory (no local fallback) | Prevent accidental 50-min local model indexing | ✓ Good |
| truncate:true for TEI | Chunks exceed 512 token limit of e5-large | ✓ Good — works but loses tail context |
| NER enabled (not structural-only) | Knowledge graph quality worth the CPU cost on first index | ⚠️ Revisit — 18min NER may not be worth it for incremental |
| Reuse global DotMDService in API | LadybugDB file lock prevents concurrent connections | ✓ Good — fixes /index endpoint crash |
| Pipeline timing metrics | No visibility into stage durations without instrumentation | ✓ Good — run_id correlation in logs |
| FalkorDB over LadybugDB | LadybugDB file lock prevents concurrent CLI + API | ✓ Good — LadybugDB removed in 999.32 |
| FalkorDB adapter from scratch | LadybugDB Cypher dialect too different to port | ✓ Good — clean implementation |
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
| Application source provider contract stays source-neutral | Telegram is the first proof source, but the contract must remain viable for Slack, Notion, PDFs, and other application sources | ✓ Good — validated in Phase 28 |
| checkpoint_cursor is durable progress, next_cursor is not | Saving continuation state before local persistence can lose source units after a crash | ✓ Good — validated in Phase 28 |

## Shipped Milestones

- **v1.1** — Incremental Indexing (Phases 1-3, shipped 2026-03-26)
- **v1.2** — FalkorDB Migration & Search Fix (Phases 4-6, shipped 2026-03-27)
- **v1.3** — Production Packaging & Background Indexing (Phases 7-10, shipped 2026-03-28)
- **v1.4** — Search Quality & Architecture (Phases 15-26, shipped 2026-05-06)
- **v1.5** — Telegram Source Adapter (Phases 27-31, shipped 2026-05-08)
- **v1.6** — Unified Source Architecture (Phases 32-37, shipped 2026-05-13)
- **v1.7** — Storage Simplification (Phase 38, shipped 2026-06-12)

## Last Shipped Milestone: v1.7 Storage Simplification

**Goal:** Decide whether embedded SurrealDB can replace the current
SQLite/sqlite-vec/FTS5 + FalkorDB split with one embedded storage layer while
preserving as much existing data as practical.

**Shipped:**
- Read-only inventory and migration-map evidence for current
  SQLite/sqlite-vec/FalkorDB/feedback storage.
- Thin SurrealDB schema, transform-only import proof, and embedded safety gate.
- Retrieval comparison harness covering full-text, vector, graph-direct, and
  hybrid/RRF behavior.
- Operations rehearsal for copied-store backup/restore, rollback, writer guard,
  and conservative recommendation assembly.

**Decision:** The first compatibility/parity-style SurrealDB replacement
prototype is not migrate-ready. The next milestone deliberately switches to a
SurrealDB-native retrieval contract and quality evaluation rather than trying to
imitate the old stack.

## Current State

v1.7 Storage Simplification is complete. The current SQLite/sqlite-vec/FTS5 +
FalkorDB stack remains the production storage architecture until v1.8 cutover.
Phase 38 added a SurrealDB spike/prototype and evidence reports, but no
production wiring.

## Current Milestone: v1.8 SurrealDB-Native Storage Cutover

**Goal:** Replace the current SQLite/sqlite-vec/FTS5 + FalkorDB
storage/retrieval stack with one SurrealDB-native architecture, validate search
quality against real user scenarios, cut production over, and delete the legacy
stack.

**Target features:**
- Define a SurrealDB-native retrieval contract instead of productizing old-stack
  compatibility.
- Build a golden-query evaluation harness and classify differences as
  improvement, harmless reorder, regression, or unclear.
- Harden SurrealDB schema/import so existing chunks, embeddings, source refs,
  graph relations, feedback, cursors, and checkpoints migrate where practical.
- Implement real SurrealDB weighted full-text, vector search, graph traversal,
  hybrid fusion, and reranker inputs.
- Shadow-run against production-derived data, then cut over production.
- Delete SQLite/sqlite-vec/FTS5, FalkorDB, LadybugDB, temporary baseline code,
  fallback switches, and compatibility shims after cutover acceptance.

Phase 33 complete (2026-05-08): Source runtimes now build through an
inspectable lifecycle factory that combines registry descriptors, typed local
config, credential-provider access, cursor state, and runtime objects.
Filesystem discovery/source-document construction routes through
`build("filesystem")`; Telegram service/CLI construction routes through
`build_if_configured("telegram")` / `build("telegram")` and remains delegated to
`mcp-telegram`. Application-source checkpoint reads, commits, and errors now go
through `SourceCursorStoreProtocol`, with checkpoint commits kept inside the
caller-owned SQLite transaction.

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

Phase 28 complete (2026-05-07): dotMD now has a minimal application-source
provider contract for future non-filesystem sources. The contract exposes
`describe_source`, `export_changes`, and `read_unit_window`; provider payloads
carry `SourceDocument`, `SourceUnit`, source-unit windows, and checkpoint
cursors. SQLite source-state helpers persist checkpoint cursors only after local
persistence succeeds and classify replayed source-unit fingerprints as
unchanged. Deterministic fixtures prove Telegram-like message units, document
implicit-root units, read windows, and replay idempotency without live Telegram.
The `mcp-telegram` Phase 29 boundary is documented in
`docs/mcp-telegram-source-contract.md`; Phase 28 did not require
`dotmd index --force` or a full rebuild.

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
*Last updated: 2026-06-12 after v1.8 milestone creation*
