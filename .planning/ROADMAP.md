# Roadmap: dotMD

**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Milestones

- [x] **v1.1 Incremental Indexing** — Phases 1-3 (shipped 2026-03-26)
- [x] **v1.2 FalkorDB Migration & Search Fix** — Phases 4-6 (shipped 2026-03-27)
- [x] **v1.3 Production Packaging & Background Indexing** — Phases 7-10 (shipped 2026-03-28)
- [ ] **v1.4 Search Quality & Architecture** — Phases 11-14

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

<details>
<summary>v1.4 Search Quality & Architecture (Phases 11-13) — SHIPPED 2026-04-02</summary>

### Phase 11: Embedding Model Evaluation
- [x] E5-large vs Qwen3-Embedding-0.6B A/B comparison
- [x] Multi-model vector store (per-model tables, both models coexist)
- [x] Context-aware encoding evaluated and removed (dead code, model-specific)
- **Decision:** E5-large retained (better Russian semantic quality). Qwen3 index preserved for future comparison.

### Phase 12: Indexing Integrity Rework
- [x] Unified database: metadata.db + vec.db → single index.db
- [x] Two-dimensional table naming: (chunk_strategy × embedding_model)
- [x] Split fingerprints: chunk_fingerprints + embed_fingerprints
- [x] Embedding reuse via text_hash column in vec_meta
- [x] fcntl.flock exclusive lock (prevents parallel indexing)
- [x] Orphan cleanup at trickle startup + deferred VACUUM
- [x] Watchdog on_deleted handler
- [x] CLI: dotmd reset --model/--strategy (replaces dotmd clear)
- [x] One-time migration (zero recompute)
- **Impact:** 429MB → 67MB storage, 0 orphans (was 98.8% dead data)

### Phase 13: Content-Aware Chunking & Search
- [x] Speaker-turn pre-splitting for meeting transcripts
- [x] UTF-8 token estimation (Cyrillic-aware)
- [x] Context prefix injection (document title in embeddings)
- [x] Graph-first entity-direct retrieval (RRF peer engine)
- [x] FTS5 compound decompounding (hyphenated words)
- [x] FTS5 prefix matching
- [x] TEI progress logging with ETA
- [x] MCP server: removed index tool, clean snippets, headings, graph counts
- **Impact:** 2990 → 7927 chunks (transcripts properly split). "Николай Сенин" rank 6 → rank 1. "инфоцыган" now findable.

### Phase 14: Frontmatter-Driven Indexing
- [ ] Strip frontmatter from chunk text, feed parsed dict into each engine structurally
- [ ] Graph: typed entities from tags namespace directly (bypass NER for known metadata)
- [ ] FTS5: title + tags as separate columns with bm25 column weights
- [ ] Embeddings: tags in enrichment prefix
- [ ] Convention-based per-kind metadata extraction
- **Goal:** Frontmatter is the structured contract between upstream producers and dotmd indexer

### Backlog items completed:
- [x] 999.1 Multi-model vector store — absorbed into Phase 12

</details>

## Progress

| Phase | Milestone | Status | Completed |
|-------|-----------|--------|-----------|
| 1. sqlite-vec Migration | v1.1 | Complete | 2026-03-26 |
| 2. Incremental Pipeline | v1.1 | Complete | 2026-03-26 |
| 3. CLI & API Polish | v1.1 | Complete | 2026-03-26 |
| 4. FalkorDB Adapter + Config | v1.2 | Complete | 2026-03-27 |
| 5. BM25 Hybrid Fix | v1.2 | Complete | 2026-03-27 |
| 6. Docker Integration + Migration | v1.2 | Complete | 2026-03-27 |
| 7. Production Packaging | v1.3 | Complete | 2026-03-27 |
| 8. Smoke Tests | v1.3 | Complete | 2026-03-28 |
| 9. Speed Benchmarks | v1.3 | Complete | 2026-03-28 |
| 10. Background Trickle Indexer | v1.3 | Complete | 2026-03-27 |
| 11. Embedding Model Evaluation | v1.4 | Complete | 2026-04-01 |
| 12. Indexing Integrity Rework | v1.4 | Complete | 2026-04-02 |
| 13. Content-Aware Chunking & Search | v1.4 | Complete | 2026-04-02 |
| 14. Frontmatter-Driven Indexing | v1.4 | Complete | 2026-04-02 |
| 15. Content-addressed caching | 2/3 | In Progress|  |

## Backlog

### Phase 999.2: Pipeline parallelism — overlap GLiNER and TEI across files (BACKLOG)

**Goal:** Eliminate idle time between GLiNER extraction and TEI embedding by running lightweight phases (purge, chunk, save, fts5, graph, fingerprints) concurrently with the heavy phases.

**Architecture decision:** Two async workers + asyncio.Queue(maxsize=1) + asyncio.Semaphore(1) as CPU gate. Expert panel unanimous. Full context in profiling notes: `.planning/notes/profiling-2026-04-02.md`.

**Expected gain:** ~1.5x over current 4.53 s/chunk.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.3: Automatic orphan cleanup — chunks/vec/FTS rows without live file_path (BACKLOG)

**Goal:** Detect and purge orphan rows (chunks without fingerprints, chunks without vectors, chunks for deleted files) on a periodic or startup basis. Currently `_purge_file()` runs only when re-chunking, so orphans accumulate silently for months.

**Context found 2026-04-24 during Phase 15 pre-migration cleanup:**
- `chunks_heading_512_50`: 237 files orphan (no fingerprints — files deleted from disk)
- `chunks_contextual_512_50`: 4937 rows without FTS and without vec_meta (pure ghosts from buggy `_purge_file()` after the 2026-04-03 MD5→blake2b migration)
- Total: ~5k invisible rows consuming disk/RAM, surviving across re-chunking cycles

**Rough scope:**
- Startup-time scan mode (report only, opt-in log) + on-demand `dotmd cleanup` CLI
- Criteria: (a) chunks without chunk_fingerprints row, (b) chunks without vec_meta row for any active model, (c) chunks with file_path not in discovered files
- Atomic cascade: chunks → chunks_fts → vec_meta → vec0 virtual table rowid

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.4: Content-dedup schema — many-to-many chunks <-> file_paths (BACKLOG)

**Goal:** Support content-addressed chunk_ids with multiple file_paths pointing to the same chunk. Currently the schema has `file_path` as a plain column in `chunks_*` with `chunk_id` as PRIMARY KEY — this physically prevents two file_paths sharing one chunk. Phase 15's blake3 migration revealed real duplicates in the knowledgebase (128 groups in heading_512_50, 299 in contextual_512_50) which collide and block migration.

**Context found 2026-04-24 during Phase 15 migration attempt:**
- Real dup sources include pytest autogenerated `.pytest_cache/README.md`, mirrored skill copies in `~/.agents/` vs `~/repos/.../skills/`, and knowledge base symlinks
- Current schema: `chunks_*` has `file_path` column, PRIMARY KEY on `chunk_id` — one chunk, one file
- Needed: separate `chunk_file_paths_*(chunk_id, file_path, chunk_index)` M2M table

**Scope:**
- New table `chunk_file_paths_*` with `(chunk_id, file_path, chunk_index)` PK
- Remove `file_path`/`chunk_index` from `chunks_*`
- Update ingest: when inserting chunk, check if chunk_id exists, only add file_path association if not
- Update `_purge_file()`: decrement-style — remove associations, cascade-delete chunks/vec/fts only when last association gone
- Update search result rendering: expose `file_paths: list[str]` instead of single path
- Full migration: collapse dup groups, move file_paths out of chunks_*, migrate chunk_id to blake3
- Tests for: modify-one-of-duplicates (new chunk_id branches off), delete-one-of-duplicates (survivor retained), file becomes identical to existing one (merge into existing chunk_id)

**Blockers for Phase 15 completion:**
Phase 15's migration_v15.py is blocked by this. Once Phase 999.4 lands, migration_v15 can be replaced by a dedup-aware variant that collapses `(body_checksum, chunk_index)` groups before UPDATEing chunk_ids.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.5: Ignore patterns for data discovery (DONE 2026-04-24)

Resolved: `indexing_exclude` already existed; extended default list in `config.py` with
`.pytest_cache`, `.ruff_cache`, `.mypy_cache`, `.tox`, `.nox`, `.venv`, `venv`, `dist`,
`build`, `.cache`. Orphan cleaner in trickle removes stale entries on next startup.

_Below is the original backlog description, kept for history:_


**Goal:** Stop indexing auto-generated or duplicate content that pollutes the knowledgebase.

**Context found 2026-04-24 during Phase 15 migration attempt:**
- `.pytest_cache/README.md` is pytest boilerplate, identical in every repo — currently indexed as many separate "documents"
- Skill directories are cloned into multiple locations (`~/.agents/`, `~/.hermes/`, `~/repos/.../skills/`) — same content indexed N times
- No exclusion mechanism in `discover_files()`

**Scope:**
- Config field `DOTMD_IGNORE_PATTERNS` (list of glob patterns, default includes `.pytest_cache/`, `node_modules/`, `.venv/`, `.git/`, `__pycache__/`)
- Apply in `discover_files()` before yielding FileInfo
- Purge existing chunks for files matching new ignore patterns on next startup
- Document in CLAUDE.md/AGENTS.md that copy-reflection patterns should not be under `data_dir`

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.6: Config separation — user-facing settings vs internal constants (BACKLOG)

**Goal:** Split `core/config.py` into two layers: user-facing configuration (paths,
models, URLs, strategy — must be explicit in config.toml, no defaults, fails on
missing) vs internal tuning constants (fusion_k, snippet_length, poll intervals —
reasonable defaults, rarely changed, can live in a module constant).

**Context 2026-04-24:** Current `Settings` has ~20 fields with Python defaults. When
TOML overrides them, defaults are silently ignored — which hid for 5 minutes why
our just-added `indexing_exclude` changes had no effect (config.toml had its own
list). Defaults on environment-specific settings (URLs, paths, model names) are an
anti-pattern for a production service — they let misconfiguration ship.

**Scope:**
- Audit every field in `Settings`: user config vs internal constant
- User config (no default, pydantic `Field(...)` required):
  `indexing_paths`, `indexing_exclude`, `data_dir`, `index_dir`,
  `embedding_url`, `falkordb_url`, `embedding_model`, `ner_model_name`,
  `reranker_model`, `chunk_strategy`
- Internal constants (move to module-level or a separate `Constants` class):
  `max_chunk_tokens`, `chunk_overlap_tokens`, `fusion_k`, `rerank_pool_size`,
  `snippet_length`, `default_top_k`, `poll_interval_seconds`, `tei_batch_size`,
  tuning thresholds etc.
- Feature flags stay as Settings booleans: `profile_indexing`, `read_only`
- Update config.toml template & docs with the full user-facing surface
- Adopt "fail loud at startup" — missing required field = service exits

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Future ideas:
- Replace MD5 with a better hash (blake2b?) for chunk_id and content_checksum — MD5 collision resistance is broken, defense-in-depth
- Semantic chunking (split by topic similarity, not just structure)
- Doc-level chunks (whole-document embeddings for broad queries)
- Query-time NER via GLiNER (complement entity catalog string matching)
- Telegram/chat history as additional data source

### Phase 15: Content-addressed caching: embedding cache, extraction cache, content-based chunk_id

**Goal:** Prevent expensive reindexing (GLiNER + TEI) when files move or mount paths change. Three improvements in order: embedding cache (B) → extraction cache (C) → content-based chunk_id migration (A).
**Requirements**: TBD
**Plans:** 2/3 plans executed

Plans:
- [ ] Plan 1: Global embedding cache by text_hash (skip TEI on file moves)
- [ ] Plan 2: Extraction cache by (text_hash + model + entity_types_hash) (skip GLiNER on file moves)
- [ ] Plan 3: Content-based chunk_id + switch to BLAKE3. chunk_id = blake3(file_content_checksum + ":" + chunk_index + ":" + chunk_strategy). Migration: stop → backup → SQL UPDATE all tables → verify → restart. Depends on Plan 1+2 deployed and warm.

---
*Roadmap created: 2026-03-26*
*Last updated: 2026-04-02*
