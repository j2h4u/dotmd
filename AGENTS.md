# AGENTS.md — dotMD

## Project Status

dotMD is a **heavily modified fork** of an upstream markdown knowledgebase search tool.
The upstream project appears inactive — last commit January 2026 ("docs update").
We treat this as our own project with independent development direction.

## Branches

- **`dev`** — our working branch. All development happens here. Significantly diverged from upstream.
- **`main`** — tracks upstream (`remotes/upstream/main`). Synced automatically by `git-sync.timer`. Do not commit directly. Exists only as a reference for upstream changes if they ever resume.

**Always work in `dev`.** Feature branches off `dev` when needed, merge back to `dev`.

## What Changed From Upstream

The fork has been substantially reworked:

- **Unified database**: single `index.db` (was separate `metadata.db` + `vec.db`)
- **Two-dimensional storage**: tables keyed by `(chunk_strategy, embedding_model)` — supports multiple chunking strategies and embedding models simultaneously
- **Content-aware chunking**: speaker-turn splitting for meeting transcripts, paragraph splitting for voicenotes, heading-based for docs
- **Context prefix injection**: document title prepended to embeddings at encode time
- **Graph-first entity retrieval**: entity-direct graph search as RRF peer alongside semantic and BM25
- **Embedding reuse**: text_hash column enables cross-strategy embedding cache
- **Split fingerprints**: chunk tracking and embed tracking separated (change model → skip re-chunking)
- **Exclusive lock**: `fcntl.flock` prevents parallel indexing
- **Orphan cleanup**: automatic at trickle startup
- **sqlite-vec**: replaced LanceDB with sqlite-vec (no AVX2 requirement)
- **FalkorDB**: replaced LadybugDB with FalkorDB for knowledge graph
- **TEI**: external embedding server (Text Embeddings Inference), CPU-only

## Architecture Overview

See `CLAUDE.md` for full details. Key paths:

```
backend/src/dotmd/
  ingestion/pipeline.py   — IndexingPipeline (orchestrates everything)
  ingestion/trickle.py    — background file watcher + indexer
  ingestion/chunker.py    — content-aware chunking
  search/semantic.py      — TEI embedding + vector search
  search/graph_direct.py  — entity-direct graph retrieval
  search/fts5.py          — FTS5 keyword search
  api/service.py          — DotMDService facade
  api/server.py           — FastAPI REST API
  cli.py                  — Click CLI
```

## Deployment

Docker container on senbonzakura server. See `/opt/docker/dotmd/` for compose config.
TEI runs as separate container (`embeddings` service on port 8088).
FalkorDB runs as separate container (`graphiti-falkordb-1`).
