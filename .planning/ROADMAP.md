# Roadmap: dotMD

**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Milestones

- [x] **v1.1 Incremental Indexing** — Phases 1-3 (shipped 2026-03-26)
- [x] **v1.2 FalkorDB Migration & Search Fix** — Phases 4-6 (shipped 2026-03-27)
- [x] **v1.3 Production Packaging & Background Indexing** — Phases 7-10 (shipped 2026-03-28)
- [ ] **v1.4 Search Quality Evaluations** — Phases 11-12 (in progress)

<details>
<summary>v1.1 Incremental Indexing (Phases 1-3) — SHIPPED 2026-03-26</summary>

- [x] Phase 1: sqlite-vec Migration (2/2 plans) — completed 2026-03-26
- [x] Phase 2: Incremental Pipeline (2/2 plans) — completed 2026-03-26
- [x] Phase 3: CLI & API Polish (2/2 plans) — completed 2026-03-26

See: `.planning/milestones/v1.1-ROADMAP.md`

</details>

<details>
<summary>v1.2 FalkorDB Migration & Search Fix (Phases 4-6) — SHIPPED 2026-03-27</summary>

- [x] Phase 4: FalkorDB Adapter + Config (2/2 plans) — completed 2026-03-27
- [x] Phase 5: BM25 Hybrid Fix (1/1 plan) — completed 2026-03-27
- [x] Phase 6: Docker Integration + Migration (1/1 plan) — completed 2026-03-27

See: `.planning/milestones/v1.2-ROADMAP.md`

</details>

<details>
<summary>v1.3 Production Packaging & Background Indexing (Phases 7-10) — SHIPPED 2026-03-28</summary>

- [x] Phase 7: Production Packaging (2/2 plans) — completed 2026-03-27
- [x] Phase 8: Smoke Tests (1/1 plan) — completed 2026-03-28
- [x] Phase 9: Speed Benchmarks (1/1 plan) — completed 2026-03-28
- [x] Phase 10: Background Trickle Indexer (4/4 plans) — completed 2026-03-27

See: `.planning/milestones/v1.3-ROADMAP.md`

</details>

## v1.4 Search Quality Evaluations

**Milestone Goal:** Measurably improve retrieval quality on Russian voicenotes corpus through empirical evaluation of embedding models, chunking strategies, and scoring pipeline.

## Phases

- [ ] **Phase 11: Embedding Model Swap** - pplx-embed integration on feature branch, A/B comparison with saved E5-large baseline
- [ ] **Phase 12: Chunking & Scoring Calibration** - Semantic chunking for topic-switching transcripts and score pipeline recalibration

## Phase Details

### Phase 11: Embedding Model Swap
**Goal**: pplx-embed models replace E5-large on a feature branch; A/B comparison against saved baseline decides whether to merge
**Depends on**: Phase 10 (working indexed corpus). Baseline saved in `.planning/research/SEARCH-BASELINE.md`
**Requirements**: EVAL-01, EVAL-02, EMBED-01, EMBED-02, EMBED-03
**Success Criteria** (what must be TRUE):
  1. Documents indexed using pplx-embed-context-v1-0.6B with grouped chunks per document (context-aware embeddings)
  2. Search queries encoded using pplx-embed-v1-0.6B (standard single-text, no prefix needed)
  3. pplx-embed runs self-hosted in Docker — no external API dependency
  4. Same test queries from baseline run on feature branch; results compared manually
  5. Decision made: merge (significantly better) or discard branch (marginal/worse)
**Plans**: TBD

### Phase 12: Chunking & Scoring Calibration
**Goal**: Chunk boundaries follow topic shifts in transcripts; scoring pipeline calibrated for new model
**Depends on**: Phase 11 (embedding model integrated, A/B shows improvement worth keeping)
**Requirements**: CHUNK-01, CHUNK-02, SCORE-01, SCORE-02
**Success Criteria** (what must be TRUE):
  1. Semantic chunker splits at topic boundaries using embedding similarity — voicenote transcripts produce chunks aligned to topic shifts
  2. Chunk strategy configurable per content type (voicenotes vs markdown)
  3. Cross-encoder threshold calibrated from real corpus score distributions
  4. Semantic score floor recalibrated for new model's characteristics
  5. Search quality on test queries improved or not degraded vs Phase 11
**Plans**: TBD

## Progress

**Execution Order:** Phase 11 -> 12 -> 13

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. sqlite-vec Migration | v1.1 | 2/2 | Complete | 2026-03-26 |
| 2. Incremental Pipeline | v1.1 | 2/2 | Complete | 2026-03-26 |
| 3. CLI & API Polish | v1.1 | 2/2 | Complete | 2026-03-26 |
| 4. FalkorDB Adapter + Config | v1.2 | 2/2 | Complete | 2026-03-27 |
| 5. BM25 Hybrid Fix | v1.2 | 1/1 | Complete | 2026-03-27 |
| 6. Docker Integration + Migration | v1.2 | 1/1 | Complete | 2026-03-27 |
| 7. Production Packaging | v1.3 | 2/2 | Complete | 2026-03-27 |
| 8. Smoke Tests | v1.3 | 1/1 | Complete | 2026-03-28 |
| 9. Speed Benchmarks | v1.3 | 1/1 | Complete | 2026-03-28 |
| 10. Background Trickle Indexer | v1.3 | 4/4 | Complete | 2026-03-27 |
| 11. Embedding Model Swap | v1.4 | 2/3 | In Progress|  |
| 12. Chunking & Scoring Calibration | v1.4 | 0/? | Not started | - |

## Backlog

### Phase 999.1: Multi-model vector store (BACKLOG)

**Goal:** Store embeddings from multiple models side by side (per chunk, per model column) to enable instant model switching without re-indexing. Currently A/B requires separate index dirs and full re-index per model swap (~1hr). With multi-model storage, switching is just a query parameter.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd:review-backlog when ready)

---
*Roadmap created: 2026-03-26*
*Last updated: 2026-03-31*
