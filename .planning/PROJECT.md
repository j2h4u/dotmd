# dotMD

## What This Is

Fork of [inventivepotter/dotmd](https://github.com/inventivepotter/dotmd) — a markdown knowledgebase search tool combining semantic search, BM25 keyword matching, and knowledge graph traversal. Deployed on a personal home server as search engine for voicenotes transcripts and documentation (~226 markdown files, bilingual RU/EN).

## Core Value

Fast, incremental search indexing — so the daily sync of new voicenotes doesn't bog down the server for 25 minutes.

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

### Active
- [ ] Fix BM25 results missing in hybrid mode (reranker/fusion issue?)
- [ ] Upstream PR strategy — start small, build trust with maintainer

### Out of Scope

- GPU acceleration — no GPU on current hardware, Jetson/Mac Mini is future consideration
- LadybugDB replacement — works fine for reads, single-connection is manageable
- Full QMD-style query expansion/reranking — different product philosophy

## Context

**Server:** senbonzakura, Xeon E3-1245 V2 (Ivy Bridge, 2012), 16GB RAM, no GPU. AVX yes, AVX2 no — constrains PyTorch (<2.5) and lancedb (Python wheels crash with SIGILL).

**Existing infrastructure reused:**
- TEI on port 8088 (intfloat/multilingual-e5-large, 1024-dim) — shared embedding server
- Docker compose deployment at /opt/docker/dotmd/
- Source at ~/repos/j2h4u/dotmd/

**Data:**
- /srv/knowledgebase/voicenotes/ — 226 voice recordings with transcripts (daily sync via voicenotes-sync)
- /home/j2h4u/ — docs, scripts, AGENTS.md, repos (mounted read-only)

**Upstream:**
- inventivepotter/dotmd: 11 commits, 1 author, 26 stars, 0 PRs/issues
- No CONTRIBUTING.md, no license
- Solo-dev commit style (short messages, no conventional commits)
- PR strategy: small fixes first (MCP fix → TEI support → sqlite-vec → incremental indexing)

**Performance baseline (full index):**
- Embedding via TEI: ~25 min (495 chunks × 4 per batch × 12s/batch on CPU)
- NER (GLiNER): ~18 min on CPU
- Graph population: ~10 min (21k edges)
- Total: ~50 min — unacceptable for daily runs

## Constraints

- **CPU**: Xeon E3 V2 (Ivy Bridge) — no AVX2, limits ML library versions
- **RAM**: 16GB shared across all Docker services — TEI already uses ~2.6GB
- **Deployment**: Docker compose, build from fork, deploy branch merges main + our features
- **Upstream compatibility**: Changes must be backward-compatible, opt-in via config

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| sqlite-vec over lancedb | lancedb Python wheels require AVX2, server is Ivy Bridge | ✓ Good |
| TEI over local embeddings | Avoid 2GB model duplication in memory, reuse existing container | ✓ Good |
| Fork over patches | Want to contribute upstream, need clean PR branches | ✓ Good |
| deploy branch for deployment | Separate from PR branches, merges main + all our features | — Pending |
| truncate:true for TEI | Chunks exceed 512 token limit of e5-large | ✓ Good — works but loses tail context |
| NER enabled (not structural-only) | Knowledge graph quality worth the CPU cost on first index | ⚠️ Revisit — 18min NER may not be worth it for incremental |

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
*Last updated: 2026-03-23 after Phase 3 completion — CLI & API polish (diff reporting, status change detection, API force param). Milestone v1.1 complete.*
