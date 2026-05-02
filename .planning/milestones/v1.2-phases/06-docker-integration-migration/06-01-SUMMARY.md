---
plan: 06-01
phase: 06-docker-integration-migration
status: complete
started: 2026-03-27T23:00:00Z
completed: 2026-03-27T10:10:00Z
duration: ~55min (Tasks 1-2: 5min, Task 3: 50min re-index)
tasks_completed: 3
tasks_total: 3
---

# Plan 06-01: Docker Integration + Migration — Summary

## What Was Built

Connected dotmd production Docker container to FalkorDB on `graphiti_default` network, rebuilt image with falkordb dependency, and populated the FalkorDB knowledge graph via full re-index.

## Task Results

| Task | Status | What |
|------|--------|------|
| Task 1: Compose file edit | Complete | Added 3 FalkorDB env vars + graphiti_default external network |
| Task 2: Image rebuild + verify | Complete | Rebuilt image (falkordb 1.6.0), DNS resolves, status shows falkordb backend |
| Task 3: Re-index + validation | Complete | 229 files, 532 chunks, 3520 entities, 20269 edges in FalkorDB |

## Key Outcomes

- `/opt/docker/dotmd/docker-compose.yml` has `DOTMD_GRAPH_BACKEND=falkordb`, `DOTMD_FALKORDB_URL=redis://falkordb:6379`, `DOTMD_FALKORDB_GRAPH_NAME=dotmd`
- `graphiti_default` external network added (same pattern as `embeddings_default`)
- Docker image rebuilt — `falkordb` Python package v1.6.0 installed
- FalkorDB hostname resolves: `172.25.0.2 falkordb`
- Full re-index: 229 files → 532 chunks → 3520 entities → 20269 edges
- Hybrid search returns graph results (`graph` in matched_engines)
- API concurrent access works (curl http://localhost:8321/search returns HTTP 200)
- FalkorDB direct query: 2800 nodes in `dotmd` graph

## Deviations

- **TEI batch size**: Added auto-tuning probe (start at configured size, halve on 413). Default kept at 4 — empirically fastest on this CPU.
- **Index scope**: Only voicenotes indexed (/mnt/voicenotes, 229 files). Full /mnt (13,515 files) deferred to background trickle indexer (todo created).

## Key Files

### Modified
- `/opt/docker/dotmd/docker-compose.yml` — Added FalkorDB networking and env vars
- `backend/src/dotmd/search/semantic.py` — TEI batch size auto-tuning probe
- `backend/src/dotmd/core/config.py` — `tei_batch_size` setting
- `backend/src/dotmd/api/service.py` — Pass tei_batch_size to SemanticSearchEngine
- `backend/src/dotmd/ingestion/pipeline.py` — Pass tei_batch_size to SemanticSearchEngine

## Self-Check

- [x] Compose file has all 3 FalkorDB env vars
- [x] Compose file has graphiti_default external network
- [x] Existing env vars unchanged (no regression)
- [x] Docker image rebuilt with falkordb package
- [x] FalkorDB hostname resolves from container
- [x] dotmd status shows falkordb backend
- [x] Full re-index populates FalkorDB graph (3520 entities, 20269 edges)
- [x] Hybrid search returns graph results (graph in matched_engines)
- [x] API concurrent access works (HTTP 200)
