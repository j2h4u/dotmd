# Session Handoff — 2026-04-02/03

## What was done this session

### Phase 14: Frontmatter-Driven Indexing (major)
- **Content-type handler system**: `kind` field in frontmatter → ContentHandler registry (pre_split + enrich)
- **Frontmatter parsing**: `parse_frontmatter()` at file-read time, `kind` on FileInfo and Chunk
- **Frontmatter strip**: YAML removed from chunk text before chunking. Metadata reaches engines through structured channels
- **Graph injection**: `_frontmatter_to_graph()` — tags with namespace (`person:X`) → typed Entity nodes directly, bypassing NER
- **FTS5 column-weighted search**: title (5x) + tags (3x) + text (1x) via bm25 column weights
- **Embedding enrichment**: title + tags in prefix (`"Title\ntags\n\nchunk_text"`)
- **Two-fingerprint architecture**: chunk_checksum (body+kind) → re-chunking, embed_checksum (body+kind+title+tags) → re-embedding+FTS5+graph. Metadata-only changes trigger lighter path
- **Convention-based per-kind extraction**: meeting_transcript participants → PERSON entities

### Code Quality Sweep (7 review agents)
- **Bug fixes**: reindex_fts5/reindex_graph now pass frontmatter metadata, OSError handling with logging, FTS5 migration logs row count
- **Decomposition**: `_ingest_and_finalize` → 6 named sub-methods
- **Enums**: DocKind, TrickleStatus, RelationType, EntityType (replaced stringly-typed values)
- **Naming**: fm → frontmatter, body → section_body, exists → table_exists, etc.
- **Types**: callable → Callable[...], Protocol fixes (VectorStoreProtocol, LadybugDB stubs)
- **All mypy errors fixed**: 0 errors across 46 files
- **All ruff errors fixed**: 0 errors

### BLAKE2b Migration
- Replaced MD5 with BLAKE2b everywhere (chunk_id, checksums, text_hash)
- Faster than MD5 on x86-64, proper collision resistance, stdlib

### Profiling Instrumentation
- `DOTMD_PROFILE_INDEXING=true` → per-phase [prof] timing in logs
- Data collected: extraction (GLiNER) = ~45%, embed (TEI) = ~52% of total time
- They run sequentially → ~50% CPU wasted on idle waits

## Current state
- **Branch**: dev (all work here)
- **Container**: running, profiling enabled, trickle re-indexing 236 files with frontmatter
- **ETA**: ~13hr for re-indexing (was ~22hr, improved by skipping 204 non-frontmatter files)

## Open items for next session

### 1. Always-on pipeline metrics (user request)
User wants per-phase timing aggregated at runtime (not just [prof] logs):
- Pipeline accumulates totals: extraction_seconds, embed_seconds, chunk_seconds, etc.
- Exposed via /status endpoint alongside existing trickle stats
- Should work even when DOTMD_PROFILE_INDEXING=false
- Goal: identify bottlenecks for optimization

### 2. Pipeline parallelism (optimization opportunity)
Profiling shows extraction (GLiNER) and embed (TEI) are ~97% of time and run sequentially.
While TEI embeds file N, GLiNER could extract file N+1. This is pipeline parallelism.
Options discussed:
- Async prefetch: while waiting for TEI HTTP response, start NER on next file
- Batch 2-3 files: send all chunks to TEI at once, NER in parallel
- Needs careful design around fcntl.flock and crash safety

### 3. .env vs config.toml consolidation
User noted .env duplicates config.toml. .env should only be for secrets (which we don't have).
Move all config to config.toml, remove .env dependency.

### 4. Disable profiling after data collection
Once enough data is collected, set DOTMD_PROFILE_INDEXING=false in .env (or remove it after .env consolidation).

## Key files
- `backend/src/dotmd/ingestion/content_handlers.py` — handler registry
- `backend/src/dotmd/ingestion/reader.py` — parse_frontmatter, chunk_checksum, embed_checksum
- `backend/src/dotmd/ingestion/pipeline.py` — decomposed _ingest_and_finalize, _frontmatter_to_graph, profiling
- `backend/src/dotmd/search/fts5.py` — title+tags columns, bm25 weights
- `backend/src/dotmd/core/models.py` — DocKind, TrickleStatus, RelationType, EntityType enums
