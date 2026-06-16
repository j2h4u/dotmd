# v1.8 Requirements: SurrealDB-Native Storage Cutover

**Defined:** 2026-06-12
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Goal

Move dotMD from the current SQLite/sqlite-vec/FTS5 + FalkorDB storage and
retrieval stack to one SurrealDB-native persistence and retrieval architecture.

This milestone does not aim to reproduce the old search ordering exactly. The
old stack is a baseline/evaluator only. The target is a SurrealDB-native search
contract with demonstrably good user-facing retrieval quality, safe migration of
existing data, production cutover, and complete removal of legacy storage code.

## Scope Summary

### Must Have

- A SurrealDB-native retrieval contract covering weighted BM25/full-text,
  vector search, graph traversal, hybrid fusion, and reranker inputs.

- A golden-query evaluation harness that classifies differences as improvement,
  harmless reorder, regression, or unclear.

- Production-grade Surreal schema/import code that migrates existing stored
  chunks, embeddings, source refs, graph relations, feedback, cursors, and
  checkpoints where practical.

- SurrealDB-native retrieval implementation using real full-text/vector/graph
  capabilities instead of Phase 38 proxy logic.

- Shadow-run evidence on production-derived data before cutover.
- Production cutover to SurrealDB as the single dotMD storage/retrieval backend.
- Removal of SQLite/sqlite-vec/FTS5, FalkorDB, and LadybugDB code paths after
  cutover acceptance.

### Should Have

- Explainable search diff reports that make changed ranking semantics debuggable
  without requiring exact compatibility.

- Index build time, store size, latency, and memory evidence for production-like
  data volume.

- Migration tooling that avoids default rechunking, reembedding, and entity
  re-extraction unless a phase explicitly proves there is no safe transform
  path.

### Explicit Non-Goals

- Runtime fallback backend after cutover.
- Productized compatibility mode for the old SQLite/Falkor retrieval semantics.
- Compatibility shims kept for hypothetical external clients.
- Preserving legacy code after the SurrealDB cutover is accepted.
- Reintroducing LadybugDB, LanceDB, or any alternate local backend.

## Requirements

### Retrieval Contract

- [x] **SURR-RET-01**: dotMD has a documented SurrealDB-native retrieval
  contract for weighted full-text, vector, graph/entity, hybrid fusion, and
  reranker candidate inputs.

- [x] **SURR-RET-02**: The retrieval contract defines quality gates in terms of
  expected user-visible results and explainable differences, not exact rank
  parity with the old stack.

- [x] **SURR-RET-03**: The old stack is explicitly treated as a temporary
  baseline/evaluator only and not as a product compatibility target.

### Evaluation

- [x] **SURR-EVAL-01**: A golden query set covers title-heavy, tag-heavy,
  body-heavy, semantic, graph/entity, hybrid, source-ref, and mixed RU/EN
  queries.

- [x] **SURR-EVAL-02**: Old-vs-Surreal diff reports classify changed results as
  improvement, harmless reorder, regression, or unclear.

- [x] **SURR-EVAL-03**: Regressions block cutover unless fixed or explicitly
  accepted as a deliberate search semantics change.

### Migration

- [ ] **SURR-MIG-01**: The production Surreal schema represents documents,
  source units, chunks, embeddings, source refs, file/resource bindings,
  fingerprints, graph entities/relations, feedback, cursors, and checkpoints.

- [x] **SURR-MIG-02**: Migration imports existing stored data transform-first
  wherever practical, avoiding default TEI reembedding, rechunking, and entity
  re-extraction.

- [ ] **SURR-MIG-03**: Migration has explicit backup, restore, rollback, and
  partial-failure semantics before production cutover.

### Surreal Retrieval

- [x] **SURR-SEARCH-01**: SurrealDB full-text search uses real BM25/full-text
  indexes with weighted title, tags, and body/text contributions.

- [x] **SURR-SEARCH-02**: SurrealDB vector search uses the selected HNSW or
  DISKANN strategy with production-like build-time and latency evidence.

- [x] **SURR-SEARCH-03**: Graph/entity retrieval runs through Surreal relation
  records and preserves relation labels, weights, and metadata needed by dotMD
  search.

- [x] **SURR-SEARCH-04**: Hybrid fusion runs over Surreal result sets and
  produces explainable engine attribution for returned candidates.

### Cutover

- [x] **SURR-CUT-01**: A shadow run compares old stack and Surreal stack on
  production-derived data and records quality, latency, build-time, store-size,
  and memory evidence.

- [ ] **SURR-CUT-02**: dotMD production runtime can start and serve MCP/API/CLI
  search/read/drill/trickle flows using SurrealDB as the single
  storage/retrieval backend.

- [ ] **SURR-CUT-03**: Cutover acceptance is verified against live production
  surfaces before legacy code removal begins.

### Legacy Removal

- [ ] **SURR-DEL-01**: SQLite/sqlite-vec/FTS5 storage and retrieval code paths
  are deleted after cutover acceptance.

- [ ] **SURR-DEL-02**: FalkorDB and LadybugDB graph/storage code paths,
  configs, docs, tests, env vars, and deployment assumptions are deleted after
  cutover acceptance.

- [ ] **SURR-DEL-03**: Temporary evaluator/baseline code used only for migration
  is deleted once the milestone no longer needs old-stack comparisons.

- [ ] **SURR-DEL-04**: Final verification proves no fallback backend switches,
  compat shims, dead legacy imports, or obsolete docs remain.

## Out Of Scope

| Feature | Reason |
|---------|--------|
| Exact old-stack search parity | The milestone targets improved SurrealDB-native semantics, not imitation of the old architecture. |
| Runtime fallback backend | The project has no backward-compatibility obligation and should not keep old systems alive after cutover. |
| Broad connector marketplace work | Storage cutover is already a full milestone. |
| New embedding/reranker model selection | The milestone may preserve and migrate existing embeddings; model changes require a separate quality effort. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| SURR-RET-01 | Phase 39 | Complete |
| SURR-RET-02 | Phase 39 | Complete |
| SURR-RET-03 | Phase 39 | Complete |
| SURR-EVAL-01 | Phase 40 | Complete |
| SURR-EVAL-02 | Phase 40 | Complete |
| SURR-EVAL-03 | Phase 40 / Phase 43 | Complete |
| SURR-MIG-01 | Phase 41 | Pending |
| SURR-MIG-02 | Phase 39 / Phase 41 | Complete |
| SURR-MIG-03 | Phase 41 / Phase 44 | Pending |
| SURR-SEARCH-01 | Phase 42 | Complete |
| SURR-SEARCH-02 | Phase 42 / Phase 43 | Complete |
| SURR-SEARCH-03 | Phase 42 | Complete |
| SURR-SEARCH-04 | Phase 42 | Complete |
| SURR-CUT-01 | Phase 43 | Complete |
| SURR-CUT-02 | Phase 44 | Pending |
| SURR-CUT-03 | Phase 44 | Pending |
| SURR-DEL-01 | Phase 45 | Pending |
| SURR-DEL-02 | Phase 45 | Pending |
| SURR-DEL-03 | Phase 45 | Pending |
| SURR-DEL-04 | Phase 45 | Pending |

**Coverage:**

- v1.8 requirements: 20 total
- Mapped to phases: 20
- Unmapped: 0

---
*Requirements defined: 2026-06-12*
*Last updated: 2026-06-13 after Phase 39 execution*
