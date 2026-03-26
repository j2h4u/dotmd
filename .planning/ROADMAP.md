# Roadmap: dotMD v1.2 — FalkorDB Migration & Search Fix

**Created:** 2026-03-26
**Milestone:** v1.2 — FalkorDB Migration & Search Fix
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Granularity:** Coarse (3 phases)

## Milestones

- [x] **v1.1 Incremental Indexing** - Phases 1-3 (shipped 2026-03-26)
- [ ] **v1.2 FalkorDB Migration & Search Fix** - Phases 4-6 (in progress)

## Phases

- [ ] **Phase 4: FalkorDB Adapter + Config** - New graph store backend with config-driven backend selection
- [ ] **Phase 5: BM25 Hybrid Fix** - Diagnose and fix BM25 results missing from hybrid search
- [ ] **Phase 6: Docker Integration + Migration** - Connect dotmd container to FalkorDB and run full re-index

## Phase Details

### Phase 4: FalkorDB Adapter + Config
**Goal**: Users can select FalkorDB as graph backend and the pipeline uses it for indexing and search
**Depends on**: Nothing (first phase of v1.2; builds on v1.1 Protocol abstractions)
**Requirements**: GRAPH-01, GRAPH-02, GRAPH-03
**Success Criteria** (what must be TRUE):
  1. `dotmd index` with `DOTMD_GRAPH_BACKEND=falkordb` indexes files into a FalkorDB graph (entities and edges created)
  2. `dotmd search --mode hybrid` with FalkorDB backend returns graph-sourced results alongside semantic and BM25
  3. Setting `DOTMD_GRAPH_BACKEND=ladybugdb` (or omitting the setting) still works as before -- no regression
  4. `dotmd status` reports graph store type and connection status
**Plans:** 2 plans
Plans:
- [ ] 04-01-PLAN.md — FalkorDB dependency, config settings, protocol update, adapter implementation
- [ ] 04-02-PLAN.md — Pipeline factory for graph backend selection, CLI status enhancement

### Phase 5: BM25 Hybrid Fix
**Goal**: BM25 keyword matches survive the scoring pipeline and appear in hybrid search results
**Depends on**: Nothing (independent of Phase 4)
**Requirements**: SEARCH-01
**Success Criteria** (what must be TRUE):
  1. `dotmd search --mode hybrid "some keyword"` returns results with `bm25` in `matched_engines` field
  2. Results that match only via BM25 (no semantic similarity) still appear in final output, not filtered by reranker
**Plans**: TBD

### Phase 6: Docker Integration + Migration
**Goal**: dotmd production container connects to FalkorDB and the knowledge graph is fully populated
**Depends on**: Phase 4 (adapter must exist), Phase 5 (BM25 fix should be in place before full re-index validates everything)
**Requirements**: GRAPH-04, GRAPH-05
**Success Criteria** (what must be TRUE):
  1. dotmd Docker container can reach FalkorDB on `graphiti_default` network without manual network commands
  2. `dotmd index --force` from Docker populates the FalkorDB "dotmd" graph (separate from Graphiti's "knowledgebase" graph)
  3. After full re-index, `dotmd search` and `dotmd serve` both return graph results from FalkorDB
  4. Concurrent CLI search + API serve works without connection conflicts (the whole reason for leaving LadybugDB)
**Plans**: TBD

## Progress

**Execution Order:** Phase 4 and Phase 5 are independent. Phase 6 depends on both.

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 4. FalkorDB Adapter + Config | v1.2 | 0/2 | Planned | - |
| 5. BM25 Hybrid Fix | v1.2 | 0/? | Not started | - |
| 6. Docker Integration + Migration | v1.2 | 0/? | Not started | - |

---
*Roadmap created: 2026-03-26*
*Last updated: 2026-03-26*
