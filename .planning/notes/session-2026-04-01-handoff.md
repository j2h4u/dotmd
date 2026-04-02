# Session Handoff — 2026-04-01/02

## What was done this session

### Phase 12: Indexing Integrity Rework (major)
- **Unified database**: merged metadata.db + vec.db → single index.db
- **Two-dimensional table naming**: `chunks_{strategy}`, `vec_{strategy}_{model}`
- **Split fingerprints**: `chunk_fingerprints_{strategy}` + `embed_fingerprints_{strategy}_{model}` — change model → skip re-chunking
- **Embedding reuse**: text_hash column in vec_meta — cross-strategy cache
- **fcntl.flock** exclusive lock — prevents parallel indexing (was the original trigger: 8h wasted CPU from accidental parallel run)
- **Orphan cleanup** at trickle startup + deferred VACUUM
- **Watchdog on_deleted** handler
- **CLI**: `dotmd reset --model/--strategy` replaces `dotmd clear`. No `reset_all` — only granular drops
- **REST**: removed `/clear` endpoint
- **Removed dead code**: context-aware encoding (pplx-embed, never used)
- **Removed `_LEGACY_MODELS`** from suffix function
- **Migration**: one-time rename of tables, zero recompute. Production data migrated successfully.
- **Result**: 429MB → 67MB storage, 0 orphans (was 98.8% / 238K dead chunks)

### Phase 13: Content-Aware Chunking & Search
- **Speaker-turn pre-splitting**: `[HH:MM:SS] **Speaker:**` as chunk boundaries for meetings. 73K-char transcripts went from 1 chunk → 54 chunks
- **UTF-8 token estimation**: `len(text.encode('utf-8')) // 4` instead of `len(text) // 4` (Cyrillic fix)
- **Context prefix injection**: document title prepended to embedding text at encode time (not stored). "Николай Сенин" rank 6 → rank 1
- **Graph-first entity-direct retrieval**: new `GraphDirectEngine` as RRF peer. Entity catalog loaded at startup (4713 entities), query-time string matching → 1-hop Cypher → chunk_ids
- **FTS5 compound decompounding**: `_expand_compounds()` — "инфо-цыганам" also indexed as "инфоцыганам"
- **FTS5 prefix matching**: query `word*` instead of `"word"` — matches inflected forms
- **TEI progress logging**: ETA + throughput every ~5%
- **MCP server**: removed `index` tool (security — agent called index("/mnt"), caused 210K garbage chunks), clean snippets (strip frontmatter + timestamps), heading fallback to title, start_time field, graph counts in status
- **Result**: 2990 → 7927 chunks. "инфоцыган" now findable (was invisible). All eval queries improved or stable.

### Housekeeping
- Merged feature/qwen3-embedding → dev, deleted all stale branches
- Created AGENTS.md in repo root
- Closed v1.4 milestone, updated ROADMAP.md
- All commits pushed to dev

## Current state
- **Branch**: dev (all work here, main = upstream sync)
- **Container**: dotmd-api-1 running, healthy, watch mode
- **Strategy**: `contextual_512_50` (in /opt/docker/dotmd/config.toml)
- **Model**: intfloat/multilingual-e5-large (TEI on CPU)
- **Data**: 442 files, 7927 chunks, 18500 entities in FalkorDB
- **index.db**: unified, ~53MB after VACUUM

## Open request: Telegram chat log processing

User wants to add a new content source: Telegram chat logs exported as Markdown files. Key points:

1. **Format**: Markdown with frontmatter (user-controlled). Turn-based conversation — similar to meeting transcripts but text-based (no timestamps like `[HH:MM:SS]`, but has message boundaries)

2. **Detection**: Need to distinguish from existing content types. User will provide frontmatter with a field that identifies the type (e.g., `source: telegram` or `type: chat_log`)

3. **Processing needs**: Similar to meeting transcripts — turn-based splitting, speaker names in embeddings, entity extraction. But different from voice transcripts: no timestamps, different turn markers, possibly different metadata (chat name, date range, etc.)

4. **Architecture request**: Formalize the content-type handler pattern. Currently the detection is ad-hoc regex in `_pre_split_segments()` and `_enrich_for_embedding()`. User wants a proper handler factory pattern so adding new content types is clean and extensible.

5. **Current content types in code**:
   - **Meeting transcripts**: detected by `[HH:MM:SS] **Speaker:**` pattern. Pre-split by speaker turns. Timestamps stripped from embeddings, speaker names kept.
   - **Personal voicenotes**: no speakers, no headings. Split by `\n\n` paragraphs.
   - **Docs/markdown**: ATX headings. Existing heading-based chunking.
   - **NEW: Telegram chats**: TBD format, turn-based, frontmatter-identified.

6. **Key files to read**:
   - `backend/src/dotmd/ingestion/chunker.py` — `_pre_split_segments()`, `chunk_file()`
   - `backend/src/dotmd/ingestion/pipeline.py` — `_enrich_for_embedding()`, `_embed_chunks()`
   - `backend/src/dotmd/search/fts5.py` — `_expand_compounds()`
   - `.planning/phases/12-indexing-integrity/PLAN.md` — architecture overview
   - `.planning/phases/13-hierarchical-chunking/PLAN.md` — chunking strategy design
   - `AGENTS.md` — project overview
