# Requirements: dotMD

**Defined:** 2026-03-30
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## v1.4 Requirements

### Evaluation Framework

- [ ] **EVAL-01**: Reproducible test query set (5+ queries) with expected result annotations covering keyword, semantic, negative, and entity+topic scenarios
- [ ] **EVAL-02**: A/B comparison script that runs same queries on two branches and reports score/rank differences

### Embedding Model

- [ ] **EMBED-01**: pplx-embed-context-v1-0.6B integration for document indexing (grouped chunks per document, context-aware embeddings)
- [x] **EMBED-02**: pplx-embed-v1-0.6B integration for query encoding (standard single-text embedding)
- [x] **EMBED-03**: Self-hosted deployment in Docker (no external API dependency)

### Chunking Strategy

- [ ] **CHUNK-01**: Semantic chunking with adaptive boundaries based on embedding similarity between consecutive segments
- [ ] **CHUNK-02**: Configurable chunk strategy per content type (voicenotes vs markdown documentation)

### Scoring Pipeline

- [ ] **SCORE-01**: Cross-encoder relevance threshold calibrated on real corpus queries
- [ ] **SCORE-02**: Semantic score floor recalibrated after embedding model swap

## Future Requirements

### Chunking Advanced

- **CHUNK-03**: Multi-resolution indexing (multiple chunk sizes, RRF between resolutions)
- **CHUNK-04**: Late chunking with long-context model (embed full document, pool per chunk)

### Search Intelligence

- **SRCH-01**: Query decomposition — extract entity mentions, filter results by entity
- **SRCH-02**: Named entity boost — graph-aware filtering when query contains known entities

## Out of Scope

| Feature | Reason |
|---------|--------|
| Anthropic Contextual Retrieval | $1/M tokens LLM cost per chunk, not justified for personal use |
| Propositionizer (atomic fact extraction) | $400/100M tokens, overkill for voicenotes |
| GPU acceleration | No GPU on current hardware |
| pplx-embed-v1-4B | 2560-dim, too large for 16GB RAM server with other services |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| EVAL-01 | Phase 11 | Pending |
| EVAL-02 | Phase 11 | Pending |
| EMBED-01 | Phase 11 | Pending |
| EMBED-02 | Phase 11 | Complete |
| EMBED-03 | Phase 11 | Complete |
| CHUNK-01 | Phase 12 | Pending |
| CHUNK-02 | Phase 12 | Pending |
| SCORE-01 | Phase 12 | Pending |
| SCORE-02 | Phase 12 | Pending |

**Coverage:**
- v1.4 requirements: 9 total
- Mapped to phases: 9
- Unmapped: 0

---
*Requirements defined: 2026-03-30*
*Last updated: 2026-03-30 after roadmap creation*
