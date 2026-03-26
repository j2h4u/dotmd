# Research Summary: dotMD v1.2 -- FalkorDB Migration & BM25 Hybrid Fix

**Domain:** Graph store backend swap + hybrid search scoring fix
**Researched:** 2026-03-26
**Overall confidence:** HIGH

## Executive Summary

The v1.2 milestone addresses two independent issues: (1) replacing the embedded LadybugDB graph store with FalkorDB to eliminate single-connection file lock conflicts, and (2) fixing BM25 results disappearing in hybrid search mode.

The FalkorDB migration is architecturally clean. The codebase already has Protocol-based abstractions (`GraphStoreProtocol`) and a proven backend-swap pattern (`vector_backend` with factory function). FalkorDB is already running on the server as `graphiti-falkordb-1`, sharing an instance via separate named graphs. The Cypher dialect is compatible with minor differences (`labels()` vs `label()`, schemaless vs explicit schema). The adapter is simpler than the current LadybugDB implementation -- no schema DDL, no relationship table map, no 4-query-per-node label lookups for edge creation.

The BM25 hybrid fix requires diagnosis before implementation. Code analysis reveals a clear "kill chain" where the cross-encoder reranker's score threshold (-8.0) filters out BM25-unique results that score poorly on semantic relevance. The reranker was designed for clean English QA pairs, not bilingual voicenote transcripts. The fix is likely a threshold adjustment combined with preserving dropped results as fallback. All entry points (FastAPI, MCP, CLI) call `warmup()` which loads the BM25 index, so the engine itself is functioning -- the issue is downstream in the scoring pipeline.

Both work items are independent and can be parallelized.

## Key Findings

**Stack:** Add `falkordb>=1.5` Python client. Remove `real_ladybug` from core deps (move to optional). No new infrastructure -- FalkorDB server already running.

**Architecture:** Follow existing `_create_vector_store()` factory pattern. New `_create_graph_store()` factory in pipeline.py. Config adds `graph_backend`, `falkordb_url`, `falkordb_graph_name`. Docker networking adds `graphiti_default` external network.

**Critical pitfall:** FalkorDB is schemaless (no `CREATE NODE TABLE`) and uses `labels()` (plural, returns list) instead of `label()`. Do NOT port LadybugDB adapter code -- write FalkorDB adapter from scratch against the Protocol. Porting would carry unnecessary complexity (schema init, rel table map, label lookup pattern) and break on dialect differences.

## Implications for Roadmap

Based on research, suggested phase structure:

1. **Phase 1: FalkorDB Adapter + Config** -- Build the new graph store backend
   - Addresses: FalkorDB adapter, config settings, pipeline factory, Protocol extension (`get_graph_data`)
   - Avoids: Pitfall 1 (Cypher dialect), Pitfall 8 (porting `_find_node_label`), Pitfall 9 (hardcoded pipeline)
   - Scope: `storage/falkordb_graph.py` (new), `core/config.py`, `storage/base.py`, `ingestion/pipeline.py`, `pyproject.toml`
   - Test gate: Unit tests against local FalkorDB; all Protocol methods verified

2. **Phase 2: BM25 Hybrid Fix** -- Diagnose and fix scoring pipeline (INDEPENDENT, can run in parallel)
   - Addresses: BM25 results missing in hybrid mode
   - Avoids: Pitfall 2 (reranker kills keyword matches), Pitfall 5 (score attribution lost)
   - Scope: `api/service.py` (search method), possibly `search/reranker.py` or config thresholds
   - Test gate: `dotmd search --mode hybrid` returns results with `bm25` in `matched_engines`

3. **Phase 3: Docker Integration + Migration** -- Deploy and re-index
   - Addresses: Docker networking, production deployment, full re-index
   - Avoids: Pitfall 3 (graph name collision), Pitfall 4 (network isolation)
   - Scope: `/opt/docker/dotmd/docker-compose.yml`, `docker-compose.yml` (repo)
   - Test gate: `dotmd search` from Docker returns graph results; concurrent CLI + serve works

**Phase ordering rationale:**
- Phase 1 before Phase 3: adapter must exist before deploying it
- Phase 2 is independent: BM25 fix doesn't touch graph code at all
- Phase 3 is last: requires adapter (Phase 1) and benefits from BM25 fix (Phase 2) being in place before the full re-index validates both changes together
- Phase 1 and Phase 2 can be worked in parallel if desired

**Research flags for phases:**
- Phase 1: Standard patterns, well-researched. All Cypher queries verified against FalkorDB docs. No deeper research needed.
- Phase 2: Needs empirical diagnosis. The root cause analysis is strong but not confirmed -- add diagnostic logging first, then fix based on evidence.
- Phase 3: Standard Docker networking. No research needed, just ops work.

## Confidence Assessment

| Area | Confidence | Notes |
|------|------------|-------|
| Stack | HIGH | FalkorDB client API verified against docs + GitHub. Already deployed on server. |
| Features | HIGH | Protocol mapping is 1:1. Feature list derived directly from codebase gaps. |
| Architecture | HIGH | Factory pattern already proven with `vector_backend`. Same approach applies. |
| Pitfalls | HIGH for FalkorDB adapter, MEDIUM for BM25 fix | FalkorDB pitfalls are well-understood from docs. BM25 root cause is analyzed but needs empirical confirmation. |

## Gaps to Address

- **BM25 root cause confirmation:** The kill chain analysis (reranker threshold) is the most likely cause but not empirically verified. Phase 2 should start with diagnostic logging before implementing a fix.
- **FalkorDB `params` kwarg name:** The falkordb-py client uses `params={}` but the exact parameter passing API should be verified with a quick REPL test against the running instance before writing all adapter methods.
- **pandas dependency scope:** Currently a core dependency. Only used by `LadybugDBGraphStore.get_graph_data()` for `.get_as_df()`. Verify no other code imports pandas before moving to optional.
- **Connection pool sizing:** Default `falkordb` connection settings should work, but optimal pool size for concurrent serve + CLI + index operations is unknown. Monitor during Phase 3 testing.

### Files Created

| File | Purpose |
|------|---------|
| `.planning/research/SUMMARY.md` | This file -- executive summary with roadmap implications |
| `.planning/research/ARCHITECTURE.md` | Integration points, component design, build order |
| `.planning/research/STACK.md` | Technology decisions (FalkorDB client, Cypher mapping) |
| `.planning/research/FEATURES.md` | Feature landscape for v1.2 (table stakes, differentiators, anti-features) |
| `.planning/research/PITFALLS.md` | 12 identified pitfalls with prevention strategies |

---
*Research summary for: dotMD v1.2 FalkorDB Migration & BM25 Hybrid Fix*
*Researched: 2026-03-26*
