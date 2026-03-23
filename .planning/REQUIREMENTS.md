# Requirements: dotMD Incremental Indexing

**Defined:** 2026-03-23
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## v1 Requirements

### File Tracking

- [ ] **FT-01**: Persist file fingerprints (path, mtime, size, checksum) in metadata.db
- [ ] **FT-02**: Classify files as new/modified/deleted/unchanged on each index run
- [ ] **FT-03**: Skip unchanged files entirely (no re-read, no re-embed, no re-extract)

### Store Cleanup

- [ ] **SC-01**: Delete chunks by file_path from metadata store
- [ ] **SC-02**: Delete vectors by file_path from sqlite-vec store
- [ ] **SC-03**: Delete Section nodes and edges by file_path from graph store (preserve Entity/Tag nodes)

### Incremental Pipeline

- [ ] **IP-01**: Modified files: purge old data from all stores, then re-ingest
- [ ] **IP-02**: New files: ingest normally (embed + NER + graph)
- [ ] **IP-03**: Deleted files: purge from all stores
- [ ] **IP-04**: BM25 index rebuilt from all chunks after diff applied (~0.1s)
- [ ] **IP-05**: `--force` flag to bypass fingerprints and do full re-index

### CLI / API

- [ ] **CA-01**: `dotmd index` uses incremental by default
- [ ] **CA-02**: `dotmd index --force` does full re-index
- [ ] **CA-03**: Progress reporting: "3 new, 1 modified, 0 deleted, 222 unchanged"

## v2 Requirements

### Graph Maintenance

- **GM-01**: Orphan entity/tag cleanup (nodes with no remaining Section edges)
- **GM-02**: NER skip for minor file changes (structural-only for small diffs)

### Multimodal

- **MM-01**: Gemini Embedding 2 integration for audio/image/PDF embedding
- **MM-02**: Multiple embedding spaces (local TEI + cloud Gemini) with fusion

### Graph Backend

- **GB-01**: FalkorDB/Graphiti adapter replacing LadybugDB (eliminates single-connection constraint)

### Formats

- **FM-01**: .txt and .org file support in reader

## Out of Scope

| Feature | Reason |
|---------|--------|
| File watcher (inotify/watchdog) | Daily batch via timer, not real-time. Adds complexity with no benefit. |
| Incremental BM25 (bm25opt) | Full rebuild is 0.1s for 500 chunks. Not worth the dependency. |
| Partial NER (re-extract only changed paragraphs) | Chunk boundaries shift on edit — simpler to re-extract per file. |
| Multi-user / concurrent writes | Personal tool, single user. |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| FT-01 | Phase 1 | Pending |
| FT-02 | Phase 1 | Pending |
| FT-03 | Phase 1 | Pending |
| SC-01 | Phase 1 | Pending |
| SC-02 | Phase 1 | Pending |
| SC-03 | Phase 1 | Pending |
| IP-01 | Phase 2 | Pending |
| IP-02 | Phase 2 | Pending |
| IP-03 | Phase 2 | Pending |
| IP-04 | Phase 2 | Pending |
| IP-05 | Phase 2 | Pending |
| CA-01 | Phase 3 | Pending |
| CA-02 | Phase 3 | Pending |
| CA-03 | Phase 3 | Pending |

**Coverage:**
- v1 requirements: 14 total
- Mapped to phases: 14
- Unmapped: 0 ✓

---
*Requirements defined: 2026-03-23*
*Last updated: 2026-03-23 after initial definition*
