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
| 16. Content-dedup schema | v1.4 | Planned |  |

## Backlog

### Phase 999.2: Pipeline parallelism — overlap GLiNER and TEI across files (BACKLOG)

**Goal:** Eliminate idle time between GLiNER extraction and TEI embedding by running lightweight phases (purge, chunk, save, fts5, graph, fingerprints) concurrently with the heavy phases.

**Architecture decision:** Two async workers + asyncio.Queue(maxsize=1) + asyncio.Semaphore(1) as CPU gate. Expert panel unanimous. Full context in profiling notes: `.planning/notes/profiling-2026-04-02.md`.

**Expected gain:** ~1.5x over current 4.53 s/chunk.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.3: Automatic orphan cleanup — chunks/vec/FTS rows without live file_path (BACKLOG, partially done)

**Goal:** Detect and purge orphan rows (chunks without fingerprints, chunks without vectors, chunks for deleted files) on a periodic or startup basis. Historically `_purge_file()` only ran when re-chunking, so orphans accumulated for months across hash-algorithm migrations.

**Context found 2026-04-24 during Phase 15 pre-migration cleanup:**
- `chunks_heading_512_50`: 237 files orphan (no fingerprints — files deleted from disk)
- `chunks_contextual_512_50`: 4937 rows without FTS and without vec_meta (pure ghosts from buggy `_purge_file()` after the 2026-04-03 MD5→blake2b migration)
- Total: ~5k invisible rows consuming disk/RAM, surviving across re-chunking cycles

**Done 2026-04-24 (as a side fix while deploying Phase 15):**
- ✅ Criterion (c) — chunks with file_path not in discovered files — is now cleaned on every trickle startup
- ✅ `purge_orphaned_files` rewritten to scan ALL `chunks_<strategy>` tables, not just the active strategy (previously heading orphans were invisible to cleanup because pipeline saw only contextual)
- ✅ Cascade covers chunks, chunks_fts, vec_meta, vec0 virtual table by rowid, chunk_fingerprints, embed_fingerprints_* across every embedding model

**Still open:**
- Criterion (a) — chunks without a chunk_fingerprints row for the same file_path (should be impossible, but worth a periodic audit)
- Criterion (b) — chunks without a vec_meta row for any active embedding model (this was the 4937-row class from 2026-04-03 fallout)
- On-demand `dotmd cleanup` CLI — currently only runs on trickle startup; no way to trigger it without a restart
- Reporting mode — log a dry-run summary before destructive changes for operator confidence
- Periodic scheduling — beyond startup (e.g., weekly as systemd timer / cron), for long-lived deployments

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

### Phase 999.7: Remove migration_v15.py no-op stub (BACKLOG)

**Goal:** Delete `backend/src/dotmd/storage/migration_v15.py` and its tests.

**Context 2026-04-24:** Phase 16 supersedes v15 migration with `migration_v16` (schema change + blake3 remap + dedup collapse in one pass). v15 is left as a no-op stub with a deprecation banner for one release cycle as a safety net. Remove after Phase 16 has shipped and been stable for one cycle.

**Scope:**
- Delete `migration_v15.py`
- Remove any remaining imports / CLI wiring
- Delete v15-specific tests

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.8: Per-holder heading hierarchy — promote `heading_hierarchy` + `level` to M2M (BACKLOG)

**Goal:** If future feature surfaces per-holder heading context (breadcrumb per search hit, heading-filtered search), move `heading_hierarchy` and `level` from `chunks_*` into `chunk_file_paths_*` so each holder carries its own context.

**Context 2026-04-24:** Phase 16 locked these fields on the `chunks_*` row with a fail-closed divergence policy (Decision #10). Observed divergence count on current KB = 0 (all duplicates are symlinks/mirrors with identical headings), so the scope expansion was deferred. Trigger condition: any downstream feature that needs per-holder heading.

**Plans:**
- [ ] TBD (promote when a consumer emerges)

### Future ideas:
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

### Phase 16: Content-dedup schema — many-to-many chunks to file_paths

**Goal:** Support content-addressed chunk_ids with multiple file_paths pointing to the same chunk. Unblocks Phase 15's migration_v15 (collision-blocked) and delivers real storage + search-quality wins.

**Depends on:** Phase 15 (blake3 chunker + caches — deployed 2026-04-24)
**Requirements**: DEDUP-01..DEDUP-11 (see 16-RESEARCH.md)
**Plans:** 6 plans — generated 2026-04-24 via /gsd:plan-phase 16

**Context & design notes:** see `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md` — edge cases, schema sketch, open questions, expected plan breakdown (migrated from backlog 2026-04-24). Researcher audit in `16-RESEARCH.md`.

Plans:
- [ ] 16-P6-test-suite.md — Wave 0 RED fixtures + test skeletons (conftest, collision/empty/pre-v16 DBs, round-trip parity)
- [ ] 16-P1-schema-migration-core.md — Wave 2 M2M schema, blake3 remap, collision collapse, char_offset drop, v15 stub
- [ ] 16-P2-migration-ops-modes.md — Wave 3 `dotmd migrate {run,status}`, --dry-run, --verify-only, progress logs
- [ ] 16-P3-ingest-flow-rewrite.md — Wave 3 INSERT OR IGNORE ingest + trickle advisory-lock startup check
- [ ] 16-P4-purge-and-change-detection.md — Wave 3 decrement-cascade _purge_file + M2M orphan sweep
- [ ] 16-P5-search-api-clean-break.md — Wave 3 SearchResult.file_paths: list[Path] across models/fusion/CLI/MCP

---
*Roadmap created: 2026-03-26*
*Last updated: 2026-04-02*
