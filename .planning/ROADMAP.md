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

### Phase 999.4: Content-dedup schema — many-to-many chunks <-> file_paths (BACKLOG)

**Goal:** Support content-addressed chunk_ids with multiple file_paths pointing to the same chunk. Currently the schema has `file_path` as a plain column in `chunks_*` with `chunk_id` as PRIMARY KEY — this physically prevents two file_paths sharing one chunk. Phase 15's blake3 migration revealed real duplicates in the knowledgebase (128 groups in heading_512_50, 299 in contextual_512_50) which collide and block migration.

**Context found 2026-04-24 during Phase 15 migration attempt:**
- Real dup sources include pytest autogenerated `.pytest_cache/README.md`, mirrored skill copies in `~/.agents/` vs `~/repos/.../skills/`, and knowledge base symlinks
- Current schema: `chunks_*` has `file_path` column, PRIMARY KEY on `chunk_id` — one chunk, one file
- Needed: separate `chunk_file_paths_*(chunk_id, file_path, chunk_index)` M2M table
- `.pytest_cache` already excluded (Phase 999.5) — remaining duplicates are legitimate
  mirrors (skills cloned across repos, symlinked files)

**Why content-addressed chunk_ids are valuable (reminder):**
Phase 15 delivered blake3 chunk_ids = `blake3(body_checksum:chunk_index:strategy)`.
File moves (rename, mount-path change) produce the SAME chunk_id for unchanged
content. This lets `_embedding_cache` and `_extraction_cache` skip TEI + GLiNER
on re-discovery — the main win of Phase 15. But collisions across different
file_paths with identical content physically can't coexist in current schema.

**Proposed schema (detail):**
```sql
chunks_<strategy> (
    chunk_id TEXT PRIMARY KEY,
    heading_hierarchy TEXT,
    text TEXT,
    char_offset INTEGER
    -- file_path and chunk_index MOVED to M2M table
)

chunk_file_paths_<strategy> (
    chunk_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,  -- may differ across files for same chunk
    PRIMARY KEY (chunk_id, file_path, chunk_index)
)

-- plus index for fast "chunks of file" queries:
CREATE INDEX idx_chunk_file_paths_<strategy>_file_path
  ON chunk_file_paths_<strategy>(file_path);
```

**Edge cases worked out 2026-04-24:**

1. **Modify one of duplicate pair (A, B share content → same chunk_id X).**
   User edits A. New content → new blake3 → new chunk_id Y.
   - `chunk_file_paths`: `(X, A)` → REMOVE; `(Y, A)` → INSERT. `(X, B)` stays.
   - `chunks_*`: new row for Y. X untouched (still has holder B).
   - `vec_meta_*`: new vector for Y. X's vector stays (B still uses it).

2. **Delete one of duplicate pair.** Trickle notices A gone.
   - For each chunk_id where `file_path = A` in `chunk_file_paths`:
     - DELETE that association row
     - IF `SELECT COUNT(*) FROM chunk_file_paths WHERE chunk_id = X` = 0:
       cascade — DELETE from chunks_*, vec_meta_*, vec0, chunks_fts_*
     - ELSE keep chunks_* row (still has other holders)

3. **File mutates to become identical to an existing one** (A = foo, B = bar → A gets edited to be = bar).
   - Rechunk A: old `(A_chunk_id, A)` removed. If last holder → cascade delete.
   - New chunk for A with blake3 = B_chunk_id (already exists in chunks_*).
     `INSERT OR IGNORE INTO chunks_*` (no-op because chunk_id exists) +
     `INSERT INTO chunk_file_paths (B_chunk_id, A, chunk_index)`.
   - B_chunk_id now has two holders (A, B).

4. **Search result display.** Semantic/BM25 hit returns chunk_id X.
   - X has 1..N file_paths. API must pick or expose all.
   - Decision candidates: MIN path (lexicographic), shortest path (fewest /),
     closest-to-data_dir, newest mtime, expose full list with "primary" chosen.
   - Graph result: graph_direct returns entities → chunk_ids, same question.

5. **Graph (FalkorDB) semantics.**
   - `MENTIONS(chunk_id → entity_name)` — already chunk-id-keyed, unchanged.
     Entity is associated with CONTENT, not with a specific path. Good.
   - `CO_OCCURS(entity → entity)` — entity-name-keyed, unchanged.
   - `File` nodes (after 2026-04-24 cleanup): keyed on file_path.
     Question: do we still need section-level `File → Section` edges when one
     Section has N Files? Options: duplicate edges for each path, or reshape
     the graph to have `Content` nodes instead of `Section` ones with File as
     attribute.

6. **embedding_cache.** Already keyed on `(text_hash, model_name)` — dedup
   happens naturally, no change needed.

7. **extraction_cache.** Already keyed on `blake3(raw_text + model_sig)` —
   dedup happens naturally. MENTIONS are rebuilt at read time from current
   chunk.chunk_id, which stays consistent per chunk even if multiple paths
   share it.

**Migration strategy (existing data):**
- Backup index.db
- Create `chunk_file_paths_<strategy>` for every existing strategy
- For each row in `chunks_<strategy>`:
  INSERT INTO `chunk_file_paths_<strategy>` (chunk_id, file_path, chunk_index)
- For collision groups (multiple old rows → one new blake3):
  pick canonical (MIN old chunk_id?) for chunks_*/vec_meta_*, DELETE others
  from chunks_*/vec_meta_*/chunks_fts_* (M2M already has all associations)
- UPDATE chunks_*.chunk_id = new_blake3 for every row (now unique)
- UPDATE chunk_file_paths_*.chunk_id = new_blake3 in sync
- Recreate chunks_* without file_path/chunk_index columns (SQLite CREATE+SELECT+DROP+RENAME)
- VACUUM

**Open questions (to pin down in discuss-phase):**
- **Canonical file_path for search results** — MIN lexicographic / shortest /
  closest to data_dir / newest mtime? (pillar of UX)
- **API contract** — breaking change (`file_paths: list[str]` replaces
  `file_path: str`) or additive (`file_path` stays + new `also_at: list[str]`)?
- **chunk_index placement** — leave in chunks_* as array or move to M2M?
  (M2M is cleaner but needs JOIN for every chunk render)
- **Vec collision during migration** — two old chunks → same new chunk_id,
  vectors may differ by TEI non-determinism. Keep canonical, discard others?
  Average? Recompute?
- **FalkorDB File-node semantics** — how File nodes relate to Sections when
  Section has N Files. Edge duplication vs graph reshape.
- **Transaction strategy** — one big transaction (safest, longest lock) vs
  per-strategy checkpoints with resume marker (like `migration_v15_state`)?
- **Test coverage** — at minimum: modify-one, delete-one, merge-into-existing.
  Additional: concurrent trickle + cleanup, empty knowledgebase migration.

**Rough plan breakdown (5-6 planes expected after discuss-phase):**
- P1: Schema migration (new M2M table + collapse duplicates + UPDATE chunk_ids to blake3)
- P2: Ingest flow rewrite (INSERT OR IGNORE + M2M association)
- P3: `_purge_file` + trickle change-detection decrement-style rewrite
- P4: Search API + result rendering (file_paths exposure, canonical selection)
- P5: FalkorDB semantics (File-node reshape or edge strategy)
- P6: Test suite (all edge cases from above)

**Blockers for Phase 15 completion:**
Phase 15's `migration_v15.py` is blocked by this. Once 999.4 lands,
`migration_v15` will be superseded by 999.4's schema migration (which does
chunk_id remapping + dedup collapse in one pass). Phase 15 can then be marked
fully complete.

**Side-benefits:**
- knowledgebase storage reduction (~429 dup groups × avg chunks/file = thousands of rows saved)
- search no longer returns N near-identical results for mirrored content
- cleaner graph semantics (entity ↔ content, not entity ↔ path-copy)

**Plans:**
- [ ] TBD (promote with /gsd:review-backlog when ready)

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
