# dotMD

## What This Is

Independent fork of [inventivepotter/dotmd](https://github.com/inventivepotter/dotmd) — a markdown knowledgebase search tool combining semantic search, BM25 keyword matching, and knowledge graph traversal. Deployed on a personal home server as search engine for voicenotes transcripts and documentation (~227 markdown files, bilingual RU/EN). Developed independently; upstream is a reference for ideas, not a merge target.

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

### Active
- [ ] FalkorDB graph store adapter (replace LadybugDB)
- [ ] Graph backend config (`graph_backend`, `falkordb_url`)
- [ ] Pipeline integration for backend selection
- [ ] Docker networking for FalkorDB connectivity

### Out of Scope

- GPU acceleration — no GPU on current hardware, Jetson/Mac Mini is future consideration
- LadybugDB replacement — Now active in v1.2 (FalkorDB migration) due to lock conflicts with concurrent access
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

**Current index (after v1.1):**
- 227 files, 520 chunks, 3,456 entities, 19,667 edges
- Full re-index: ~59 min via TEI
- Incremental (no changes): <1s
- Per-stage timing metrics in pipeline logs (run_id correlation)

**Performance baseline (full index):**
- Embedding via TEI: ~25 min (520 chunks)
- NER (GLiNER): ~18 min on CPU
- Graph population: ~10 min (19k edges)
- Total: ~59 min

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

## Current Milestone: v1.2 FalkorDB Migration & Search Fix

**Goal:** Replace LadybugDB graph store with FalkorDB to eliminate single-connection file lock issues, and fix BM25 results missing in hybrid search mode.

**Target features:**
- FalkorDB graph store adapter implementing existing protocol
- Config settings for graph backend selection and FalkorDB URL
- Pipeline integration to select backend based on config
- Docker networking (connect dotmd to `graphiti_default` network)
- BM25 hybrid mode fix (reranker/fusion investigation)

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
*Last updated: 2026-03-27 after Phase 5 complete — BM25 hybrid fix verified, reranker threshold removed, merge-back logic added*
