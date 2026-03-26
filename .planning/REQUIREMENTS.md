# Requirements: dotMD

**Defined:** 2026-03-26
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## v1.2 Requirements

Requirements for FalkorDB migration and BM25 hybrid fix.

### Graph Backend

- [x] **GRAPH-01**: FalkorDB adapter implementing GraphStoreProtocol (new storage/falkordb_graph.py, written from scratch — not ported from LadybugDB)
- [x] **GRAPH-02**: Config settings for graph backend selection (`graph_backend`, `falkordb_url`, `falkordb_graph_name`)
- [ ] **GRAPH-03**: Pipeline factory selects graph backend based on config (follow existing `_create_vector_store` pattern)
- [ ] **GRAPH-04**: Docker networking connects dotmd container to `graphiti_default` network for FalkorDB access
- [ ] **GRAPH-05**: Full re-index with `--force` populates FalkorDB graph (~59 min, overnight run)

### Search Quality

- [ ] **SEARCH-01**: BM25 results appear in hybrid search mode (diagnose reranker threshold issue, fix scoring pipeline)

## Future Requirements

### Graph Backend

- **GRAPH-F1**: LadybugDB adapter removal (after FalkorDB proven stable in production)
- **GRAPH-F2**: pandas moved to optional dependency (only used by LadybugDB)

### Search Quality

- **SEARCH-F1**: Per-engine attribution logging (which engine contributed each result)
- **SEARCH-F2**: Configurable reranker threshold via env var

## Out of Scope

| Feature | Reason |
|---------|--------|
| Data export/import migration | Re-index with --force is simpler and already proven (~59 min) |
| Graph-only re-index (skip NER) | Extraction results not persisted separately; would need new infrastructure |
| LadybugDB removal in this milestone | Keep as fallback until FalkorDB proven stable |
| GPU acceleration | No GPU on current hardware |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| GRAPH-01 | Phase 4 | Complete |
| GRAPH-02 | Phase 4 | Complete |
| GRAPH-03 | Phase 4 | Pending |
| GRAPH-04 | Phase 6 | Pending |
| GRAPH-05 | Phase 6 | Pending |
| SEARCH-01 | Phase 5 | Pending |

**Coverage:**
- v1.2 requirements: 6 total
- Mapped to phases: 6
- Unmapped: 0

---
*Requirements defined: 2026-03-26*
*Last updated: 2026-03-26 after roadmap creation*
