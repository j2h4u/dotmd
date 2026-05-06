# Roadmap: dotMD

**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Milestones

- [x] **v1.1 Incremental Indexing** — Phases 1-3 (shipped 2026-03-26)
- [x] **v1.2 FalkorDB Migration & Search Fix** — Phases 4-6 (shipped 2026-03-27)
- [x] **v1.3 Production Packaging & Background Indexing** — Phases 7-10 (shipped 2026-03-28)
- [x] **v1.4 Search Quality & Architecture** — Phases 11-14 (shipped 2026-04-02)

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
<summary>v1.4 Search Quality & Architecture (Phases 11-14) — SHIPPED 2026-04-02</summary>

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
- [x] Strip frontmatter from chunk text, feed parsed dict into each engine structurally
- [x] Graph: typed entities from tags namespace directly (bypass NER for known metadata)
- [x] FTS5: title + tags as separate columns with bm25 column weights
- [x] Embeddings: tags in enrichment prefix
- [x] Convention-based per-kind metadata extraction
- **Goal:** Frontmatter is the structured contract between upstream producers and dotmd indexer

### Backlog items completed:
- [x] 999.1 Multi-model vector store — absorbed into Phase 12
- [x] 999.3 Automatic orphan cleanup — impossible by construction after Phase 16 M2M (2026-04-25)
- [x] 999.5 Ignore patterns for data discovery — extended default excludes in config.py (2026-04-24)
- [x] 999.7 Remove migration_v16 dead code after soak — migration CLI/module/tests removed (2026-04-30)
- [x] 999.10 MCP document metadata — implemented as `drill(file_path)` with frontmatter + entities (2026-04-26)

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
| 15. Content-addressed caching | 3/3 | Complete | 2026-04-24 |
| 16. Content-dedup schema | 6/6 | Complete   | 2026-04-25 |
| 17. MCP OAuth 2.0 — Claude Desktop connector | 3/3 | Complete   | 2026-04-30 |
| 18. Multilingual Reranker | 1/1 | Complete    | 2026-05-01 |
| 19. Reranker Adapter Layer and Multi-Model Comparison | 4/4 | Complete | 2026-05-01 |
| 20. Reranker Latency Benchmark | 1/1 | Complete | 2026-05-01 |
| 21. Reranker Quality Benchmark | 1/1 | Complete | 2026-05-02 |
| 22. Improve Search Snippet Boundaries | 1/1 | Complete    | 2026-05-02 |
| 23. Fix dotMD test contract | 1/1 | Complete | 2026-05-03 |
| 24. Config separation | 2/2 | Complete    | 2026-05-05 |

### Phase 17: MCP OAuth 2.0 — Claude Desktop remote connector support

**Goal:** Implement OAuth 2.0 Authorization Server inside the existing FastMCP server so Claude Desktop can connect via the remote MCP connector flow (UI-based, not config-file). Auto-approve for trusted Tailnet users (no user interaction), persistent token storage on docker volume, DOTMD_BASE_URL env var.
**Requirements:** OAUTH-ENV-01, OAUTH-ENV-02, OAUTH-PROVIDER-01, OAUTH-PROVIDER-02, OAUTH-PROVIDER-03, OAUTH-WIRE-01, OAUTH-E2E-01
**Plans:** 3/3 plans complete

Plans:
**Wave 1**
- [x] 17-01-PLAN.md — Verify Tailscale path-stripping (A1), add base_url to Settings, set DOTMD_BASE_URL in .env

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 17-02-PLAN.md — Implement DotMDOAuthProvider (auth.py, all 9 methods, JSON persistence)

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 17-03-PLAN.md — Wire auth into mcp_server.py, end-to-end OAuth flow verification

---

### Phase 18: Multilingual Reranker

**Goal:** Replace or rework the English-oriented reranker so Russian and multilingual queries are not degraded by noisy cross-encoder scores.
**Backlog source:** 999.20
**Requirements:** RERANK-SELECT-01, RERANK-SELECT-02, RERANK-SELECT-03, SCORE-01
**Plans:** 1/1 plans complete

Phase boundary:
- Choose a reranker strategy from public multilingual/Russian benchmark evidence available by May 2026.
- Do not build a local dotMD quality benchmark harness or curated eval set for this phase.
- Implement `Qwen/Qwen3-Reranker-0.6B` as the first target; ContextualAI rerank-v2 and Jina v3 remain alternates if Qwen integration or latency fails.
- Fix score-floor/empty-rerank behavior so fused search results are not erased.

Plans:
- [x] 18-01-PLAN.md — Implement Qwen3 0.6B multilingual reranker

---

### Phase 19: Reranker Adapter Layer and Multi-Model Comparison

**Goal:** Refactor reranking into a provider/adapter layer so dotMD can switch rerankers by name and run developer-only comparisons across multiple candidate rerankers using one shared retrieval candidate pool.
**Depends on:** Phase 18
**Requirements:** RERANK-ADAPTER-01, RERANK-SELECT-04, RERANK-COMPARE-01, RERANK-LATENCY-01
**Plans:** 4/4 plans complete

Phase boundary:
- Keep production search behavior single-reranker by default; do not make multi-reranker production serving mandatory.
- Add a clean `RerankerProtocol`/registry/factory boundary so new rerankers can be added without changing `DotMDService` internals.
- Support runtime selection for dev/CLI/API calls, e.g. choosing Qwen vs MiniLM vs the top Phase 18 alternates by name.
- Add a comparison path that runs retrieval/fusion once, then applies multiple rerankers to the same candidate pool and reports latency, ordering, score diagnostics, and overlap.
- Treat Qwen CPU latency as a first-class concern; compare against the top 3-4 Phase 18 candidate models before settling on a production default.

Plans:
**Wave 1**
- [x] 19-01-reranker-protocol-registry-PLAN.md — Add RerankerProtocol, registry, factory, and name-based config

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 19-02-shared-candidate-pool-PLAN.md — Extract shared candidate pool and preserve single-reranker search

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 19-03-developer-comparison-surfaces-PLAN.md — Add service, API, and CLI comparison over one shared pool

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 19-04-latency-docs-verification-PLAN.md — Pin latency diagnostics, docs, and focused verification

---

## Backlog

### Backlog 999.2: Pipeline parallelism — overlap GLiNER and TEI across files

**Goal:** Eliminate idle time between GLiNER extraction and TEI embedding by running lightweight phases (purge, chunk, save, fts5, graph, fingerprints) concurrently with the heavy phases.

**Architecture decision:** Two async workers + asyncio.Queue(maxsize=1) + asyncio.Semaphore(1) as CPU gate. Expert panel unanimous. Full context in profiling notes: `.planning/notes/profiling-2026-04-02.md`.

**Expected gain:** ~1.5x over current 4.53 s/chunk.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Backlog 999.3: Automatic orphan cleanup — chunks/vec/FTS rows without live file_path (DONE 2026-04-25)

**Goal:** Detect and purge orphan rows (chunks without fingerprints, chunks without vectors, chunks for deleted files) on a periodic or startup basis. Historically `_purge_file()` only ran when re-chunking, so orphans accumulated for months across hash-algorithm migrations.

**Context found 2026-04-24 during Phase 15 pre-migration cleanup:**
- `chunks_heading_512_50`: 237 files orphan (no fingerprints — files deleted from disk)
- `chunks_contextual_512_50`: 4937 rows without FTS and without vec_meta (pure ghosts from buggy `_purge_file()` after the 2026-04-03 MD5→blake2b migration)
- Total: ~5k invisible rows consuming disk/RAM, surviving across re-chunking cycles

**Done:**
- ✅ Criterion (c) — chunks with file_path not in discovered files — cleaned on every trickle startup (2026-04-24)
- ✅ `purge_orphaned_files` rewritten to scan ALL `chunks_<strategy>` tables, not just the active strategy (2026-04-24)
- ✅ Cascade covers chunks, chunks_fts, vec_meta, vec0 virtual table by rowid, chunk_fingerprints, embed_fingerprints_* across every embedding model (2026-04-24)
- ✅ Phase 16 M2M rewrite (2026-04-25): `purge_orphaned_files` now scans `chunk_file_paths_*` M2M tables; `_purge_file` cascade is authoritative — criteria (a) and (b) impossible by construction after Phase 16
- ✅ 4937-row ghost class from MD5→blake2b migration: eliminated by Phase 16 migration (486 collisions collapsed, schema rebuilt clean)

### Backlog 999.5: Ignore patterns for data discovery (DONE 2026-04-24)

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

### Backlog 999.7: Remove migration_v16 dead code after soak (DONE 2026-04-30)

**Goal:** Delete the migration_v16 scaffolding once Phase 16 has soaked in production without rollback need.

**Context (updated 2026-04-30):** Phase 16 shipped to production on 2026-04-25 — `dotmd migrate run` succeeded (486 collisions collapsed, 0 divergence, no override). v15-era dead code (migration_v15 stub, cleanup_v15_pre, v15 tests — 406 lines) was deleted same day in a separate commit since v15 was collision-blocked, never ran in production, and had no rollback path after `pre-phase15.bak` was removed. The v16 migration path also soaked successfully and was removed on 2026-04-30.

**Trigger condition:** Phase 16 stable in production without rollback need, AND `index.db.v16-backup` removed or verified absent in the same sweep (i.e. committing to "no rollback path" simultaneously with deleting the rollback script).

**Scope (one phase, one mental purge):**
- [x] `backend/src/dotmd/ingestion/migration_v16.py` — full migration logic deleted.
- [x] `backend/src/dotmd/cli.py` — `dotmd migrate` Click group removed entirely.
- [x] Migration tests and pre-v16 schema fixtures removed.
- [x] `index.db.v16-backup` on the dotmd-index volume verified absent.
- [x] `PayloadDivergenceBlocked` removed with `migration_v16.py`.
- [x] `chunk_fingerprints_*` runtime consumers preserved only where still used by `FileTracker`.
- [x] `migration_v16_lock` startup guard and `lock_constants.py` removed because no process creates that lock anymore.

**Out of scope:**
- The M2M schema itself, `_holder_aware_chunk_cleanup`, `chunk_file_paths_*` tables — these are now the live schema, not migration code.

**Plans:** Complete.

### Backlog 999.8: Per-holder heading hierarchy — promote `heading_hierarchy` + `level` to M2M

**Goal:** If future feature surfaces per-holder heading context (breadcrumb per search hit, heading-filtered search), move `heading_hierarchy` and `level` from `chunks_*` into `chunk_file_paths_*` so each holder carries its own context.

**Context 2026-04-24:** Phase 16 locked these fields on the `chunks_*` row with a fail-closed divergence policy (Decision #10). Observed divergence count on current KB = 0 (all duplicates are symlinks/mirrors with identical headings), so the scope expansion was deferred. Trigger condition: any downstream feature that needs per-holder heading.

**Plans:**
- [ ] TBD (promote when a consumer emerges)

### Backlog 999.9: MCP tool — graph entity inspection

**Goal:** Expose graph traversal through MCP so agents can explore entity context, not just retrieve flat snippets.

**Context 2026-04-25:** Hermes (Tiger's Claw) searched for "Даннинг-Крюгер" and found a relevant voicenote (score 0.904). When asked to explore further — linked entities, related conversations, speaker context — it couldn't. dotmd has 42k entities and 256k graph edges in FalkorDB, but they're used only internally for RRF ranking. Nothing surfaces through MCP. Hermes noted: "граф используется под капотом для reranking, но наружу выдаётся всё равно плоский список сниппетов."

**Proposed tools:**
- `get_entity(name)` → entity properties + type
- `related_entities(name, depth=1)` → neighbours with relation types and weights
- Possibly: `entity_mentions(name)` → chunks where entity appears

**Plans:**
- [ ] TBD

---

### Backlog 999.10: MCP tool — document metadata / frontmatter (DONE 2026-04-26)

**Goal:** Let agents retrieve structured metadata (frontmatter, speaker, tags, date) for a specific file by path, as a follow-up to a search result.

**Context 2026-04-25:** Same Hermes session. After finding the Даннинг-Крюгер voicenote, it tried to get its frontmatter (speaker, tags, full YAML) — no way to do it. `list_resources` returns empty, `search` only returns text snippets. The file lives inside the dotmd container at `/mnt/knowledgebase/…` which Hermes cannot access directly. Hermes concluded: "dotmd не отдаёт structured metadata через MCP-интерфейс."

**Done 2026-04-26:** Implemented as `drill(file_path)` — name chosen over `get_metadata` to convey the "dig deeper after search" intent. Returns frontmatter (read from disk), chunk_count (from M2M table), and entities (from FalkorDB graph). Also covers part of 999.9 — agents get entity names from `drill` and can use them for follow-up searches.

---

### Backlog 999.11: MCP list_resources — indexed file registry

**Goal:** Implement MCP `list_resources` so clients can enumerate indexed files by URI and read their metadata or content snippets.

**Context 2026-04-25:** Hermes called `list_resources` and got an empty list. MCP supports resources as a first-class primitive (URI-addressable data alongside tools and prompts). dotmd ignores this. Low immediate value at 730 files (can't paginate usefully), but the hook is needed for agents that do resource-oriented workflows. Prerequisite for proper `read_resource` support.

**Note:** Lower priority than 999.9 and 999.10. Useful only if an agent workflow specifically iterates over the file list rather than searching. A `get_metadata(file_path)` tool (999.10) is more immediately useful.

**Plans:**
- [ ] TBD

---

### Backlog 999.12: Dual-encoder unified embedding — decoupled metadata vectors (DONE 2026-04-27)

**Goal:** Decouple metadata (title, tags) from chunk embeddings so that metadata-only changes (tag updates, title renames) require 1 TEI call per document instead of N TEI calls per chunk.

**Context 2026-04-26:** Sync agent updated tags on 50 voicenote transcripts → trickle triggered full re-embed of all chunks in each file (~107 chunks × 393s TEI = hours of work). Root cause: `enrich_with_title_and_tags` bakes title+tags into the embedding text, so any tag change changes `text_hash` for every chunk → 0 cache hits.

**Technique:** Dual-encoder unified embedding (arxiv 2601.11863, ECIR 2026).

Instead of `embed(title + tags + chunk_text)` → store two vectors separately:
```
e_text  = embed(chunk_text)           # computed once per chunk, frozen
e_meta  = embed(title + tags)         # one vector per document (not per chunk)
e_fused = norm(α·norm(e_text) + (1-α)·norm(e_meta))   # local math, no TEI
```

On tag/title update: 1 TEI call to recompute `e_meta` + N local vector additions (no TEI).
On body change: recompute `e_text` per chunk (same as today).

Paper reports unified embeddings match or beat prefix approach in retrieval quality. `α` is a tunable weight (needs per-corpus calibration).

**Schema impact:**
- `e_text` — store alongside existing vec in `vec_meta_*`
- `e_meta` — new per-file table (one vector per file_path per model)
- `e_fused` — replaces current vec0 content; recomputed locally on metadata change
- `text_hash` — computed on `chunk_text` only (no prefix), enabling true cross-strategy reuse

**Reference:** [Utilizing Metadata for Better RAG (ECIR 2026)](https://arxiv.org/abs/2601.11863)

**Artifact status:** completed artifacts are archived under
`.planning/notes/completed-backlog/999.12-dual-encoder-unified-embedding-decoupled-metadata-vectors-ba/`
so `.planning/phases/` only contains active milestone phase directories.

**Plans:**
- [x] Completed as a backlog implementation run (3/3 plans)

---

### Backlog 999.13: Вернуть stateful MCP режим + notifications/tools/list_changed

**Goal:** Перейти обратно с `stateless_http=True` на stateful режим, чтобы сервер мог слать `notifications/tools/list_changed` агентам при изменении инструментов.

**Context 2026-04-26:** Текущий workaround `stateless_http=True + json_response=True` был введён из-за бага в mcp 1.27.0 где SSE-доставка ответов на `tools/call` не работала. Root cause: в `streamable_http.py` `message_router` использует zero-buffer `anyio.create_memory_object_stream(0)` для доставки ответов в SSE writer — при определённых условиях response дропался без ошибки.

**Почему notification важна:**
- Hermes поддерживает `notifications/tools/list_changed` — реализовано в `tools/mcp_tool.py::_make_message_handler()` + `_refresh_tools()`
- При получении уведомления Hermes немедленно перечитывает `tools/list` и обновляет реестр инструментов
- В stateless режиме нет персистентного SSE-канала — уведомление некуда слать
- Hermes не детектирует рестарт dotmd в stateless режиме: каждый POST независим, ошибок нет, инструменты остаются устаревшими

**Как отправить notification:**
FastMCP поддерживает `Context.session.send_tool_list_changed()`. В нашем случае — отправлять при старте lifespan (после warmup), чтобы уже подключённые клиенты обновили кэш.

**Блокер:** mcp 1.27.0 SSE bug. Варианты разблокировки:
- Дождаться фикса в mcp SDK (открыть issue upstream)
- Зафиксировать версию SDK на 1.26.x где SSE работало
- Самостоятельно патчить `message_router` (хрупко)

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.14: Migrate vector store from sqlite-vec to pgvector — shared Postgres service

**Goal:** Replace sqlite-vec with pgvector for native UPDATE semantics on vector components (e_text, e_meta, e_fused). Enables clean N-vector component updates without DELETE+INSERT choreography.

**Context 2026-04-27:** Evaluated during Phase 999.12 design. Decision: stay on sqlite-vec for now (all vectors rebuilt anyway on 999.12 deploy; DELETE+INSERT for ~8 rows/file is not meaningful overhead; atomic transactions with FTS5/metadata in single index.db is a real advantage). Revisit if performance issues arise at scale.

**Prerequisite:** voiceprint-postgres (`pgvector/pgvector:pg18`) is already running on senbonzakura but belongs to voiceprint service. Before dotmd can adopt pgvector, Postgres must be extracted into a shared service (`shared-postgres`) independent of voiceprint. Both voiceprint and dotmd then connect to the shared instance.

**Migration scope:**
- Extract `voiceprint-postgres` → `shared-postgres` standalone Docker service
- Implement `PgVectorVectorStore` adapter (existing `VectorStoreProtocol` abstraction makes this clean)
- Full index rebuild required (no vector portability from sqlite-vec)
- FTS5 and metadata stay in SQLite (pgvector handles vectors only)
- Transactions across vector updates and metadata/FTS5 updates become eventually-consistent (currently atomic)

**Trigger:** Performance issues with sqlite-vec at scale, or when N-vector component updates become a meaningful operational pain.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.15: Автокалибровка весов фьюзинга через кросс-энкодер

**Goal:** Автоматически подбирать веса `DOTMD_EMBEDDING_WEIGHTS` без ручной разметки, используя кросс-энкодер как оракул качества.

**Mechanism:** По накопленному журналу запросов (`search_log` в index.db, введён в Phase 999.12): взять N последних запросов → для каждого прогнать топ-K результатов через cross-encoder reranker → получить "правильный" ranking → sweep весов → выбрать веса при которых e_fused ranking ближе всего к reranker ranking → записать лучшие веса в `vec_config` → пересчитать e_fused (локальная математика, секунды) → применить.

**Depends on:** Phase 999.12 (query logging + N-vector scheme)

**Trigger:** Накоплено достаточно запросов в `search_log` для статистически значимого sweep (~100+ запросов).

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.16: Автокалибровка весов через межмодульное согласие

**Goal:** Использовать согласие между semantic + FTS5 + graph как несупервизированный сигнал качества для калибровки весов фьюзинга.

**Mechanism:** Когда все три движка возвращают один результат в топе — это сильный сигнал что результат правильный. Использовать эти "consensus hits" для оценки качества разных весов без единой размеченной метки.

**Depends on:** Phase 999.12 (query logging)

**Note:** Более шумный сигнал чем кросс-энкодер (999.15). Полезен как дополнительная валидация или когда reranker недоступен.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Backlog 999.17: Fix shared-chunk e_fused — per-file fused vector for multi-file chunks

**Goal:** Устранить edge case: один e_fused на chunk_id при shared chunks. Текущее состояние — фьюзинг использует e_meta первого файла навсегда.
**Context:** Аудит 2026-04-29: 299/18515 (1.61%) чанков shared. Большинство — один файл в двух местах (skills cache + source repo) или voicenotes одной сессии → e_meta практически идентична, семантическое воздействие минимально. Но архитектурно некорректно.
**Fix cost when needed:** Без TEI-запросов — переиспользовать хранящиеся e_text + e_meta_правильного_файла, пересчитать e_fused математически только для ~300 чанков. Требует изменения схемы vec_meta: UNIQUE(chunk_id) → UNIQUE(chunk_id, file_path) для shared chunks.
**Requirements:** TBD
**Plans:** 4 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.18: Extend devtools MCP client to support HTTP/streamable-http transport

**Goal:** Extend `backend/devtools/mcp_client/` to support HTTP transport alongside existing stdio. Accept a URL, connect via `streamablehttp_client`, run MCP initialize + tool calls — same interface as current stdio client.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.19: Обновить transformers с 4.57.6 до 5.x

**Goal:** Перевести в отдельной ветке на transformers 5.x (текущая 5.7.0), проверить совместимость с GLiNER и sentence-transformers, убедиться что CPU-only wheels работают. Потенциально устраняет warning про sentencepiece fast tokenizer.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.22: Document Source Abstraction — index non-filesystem sources

**Goal:** Rework dotMD ingestion from file-centric markdown indexing into a
source/document/source-unit/chunk model so non-filesystem sources can be
indexed through the same search stack. The near-term MVP should stay small:
introduce the minimal source model, then integrate Telegram read-only as the
first real non-filesystem source and harden from real usage.

**Architecture context:**
- [`docs/source-adapter-architecture.md`](../docs/source-adapter-architecture.md)
  — source/document/unit/chunk vocabulary, source assets, metadata layers,
  source entity catalogs, cross-source identity resolution, parser/content
  format axis, and phased MVP proposal.
- [`docs/source-adapter-architecture-panel-review.md`](../docs/source-adapter-architecture-panel-review.md)
  — expert-panel review covering product scope, retrieval/indexing, integration
  contracts, metadata, file-like assets, entity catalogs, security/privacy,
  QA, and MVP phase shape.
- [`docs/architecture.md`](../docs/architecture.md)
  — top-level architecture index linking to the source-adapter context.

**Context captured 2026-05-04:**
- Current dotMD discovery is `.md`-only; `.txt` is not a supported parser today.
- Markdown frontmatter is already document metadata: `title`, `kind`, `tags`,
  and `participants` influence chunking, metadata embeddings, FTS, and graph.
- Source and content format are separate axes: filesystem can discover Markdown,
  PDF, HTML, DOCX, etc.; the parser/chunking strategy should depend on
  `media_type`/`parser_name`, not on the source alone.
- File-like assets can come from any source: PDF from filesystem, Telegram,
  Slack, Notion, or Google Drive should share parser infrastructure while
  preserving provenance.
- Sources may emit entity catalogs such as Telegram users, Google contacts, or
  Gmail addresses. These are not corpus documents by default; they should feed
  graph identity resolution, alias expansion, keyword lookup, and display
  metadata.
- Cross-source identity resolution must keep `SourceEntity`, `Mention`, and
  `CanonicalEntity` separate and record confidence/evidence; string equality is
  not enough for automatic person merges.

**MVP phase shape proposed by the docs:**
1. Minimal Source Model Shim — canonical `namespace`, `document_ref`, `ref`,
   `media_type`, `parser_name`, current markdown/frontmatter metadata, and
   filesystem compatibility.
2. Telegram Read-Only MVP — minimal export surface in `mcp-telegram`, Telegram
   adapter in dotMD, dialog-as-document, message-as-source-unit, message-window
   chunks, and read context around Telegram hits.
3. Telegram Hardening From Real Usage — improve chunking, snippets/read,
   delete/edit propagation, observability, and tests based on real searches.
4. Minimal Entity Catalog Layer — Telegram users/entities as `SourceEntity`,
   conservative exact-ID graph links, no fuzzy name merging by default.
5. Second Source Validation — Perplexity exporter, Notion, or Google Docs after
   Telegram lessons refine the contract.

**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.23: Semantic enrichment — extract commitments and agreements

**Goal:** Add a structured semantic-enrichment layer for meeting transcripts
and other conversational documents so dotMD can recall important commitments
even when the user does not remember the exact words.

**Context captured 2026-05-05:**
- A search for prior profit-sharing agreements found useful nearby results but
  missed the Николай Сенин agreement until the exact phrase `65 на 35` was
  supplied.
- The missed transcript used `выручку делить`, `доли`, and `65/35`, while the
  user asked with broader wording such as `распределение прибыли`. This showed
  that embeddings + top-K search are not enough for high-recall retrieval of
  agreements, commitments, and financial terms.
- A quick PoC with `gpt-5.4-mini` over
  `/mnt/knowledgebase/voicenotes/20260319-1358-Aqny3Jxn/transcript.md`
  produced useful structured arrays for agreements, promises, decisions, open
  questions, financial terms, and next steps. It caught the `65/35` financial
  term and several action items, but also showed production needs quote/timecode
  validation and normalization.

**Proposed approach:**
- During indexing, run a cheap candidate extractor over chunks, with overlap or
  neighbouring context, to produce arrays:
  `agreements`, `promises`, `decisions`, `open_questions`,
  `financial_terms`, and `next_steps`.
- Mark low-context items with a flag such as `requires_context` when a chunk
  says "договорились" or "давай так" but the actual subject is in a neighbouring
  chunk.
- For candidates, re-read a wider window (`previous + current + next`) and run
  a verifier/consolidator that confirms the item, normalizes participants,
  extracts short evidence quotes, and pins source timecodes.
- Store the final structured items as a separate searchable layer linked to
  source file, chunk/window ids, participants, date, and project/topic hints.

**Example target record:**
```json
{
  "type": "financial_term",
  "participants": ["Максим Бращенко", "Николай Сенин"],
  "topic": "Nolium revenue split",
  "summary": "Revenue split proposed as 65/35; Maxim's share is fixed.",
  "numbers": ["65", "35"],
  "source_file": "/mnt/knowledgebase/voicenotes/20260319-1358-Aqny3Jxn/transcript.md",
  "timecodes": ["00:01:08", "00:05:57"],
  "evidence_quotes": [
    "выручку делить 35 на, соответственно, 65%",
    "65. 65, 35",
    "твоя доля, она, кстати, фиксирована"
  ],
  "confidence": 0.9
}
```

**Open design questions:**
- Whether this belongs in the existing graph layer, a new SQLite table family,
  or both.
- Whether extraction should run for every chunk by default, only for
  transcript-like `kind`s, or behind an opt-in indexing mode.
- How much overlap is needed for reliable commitment extraction without making
  indexing too expensive.
- Which model tier is acceptable for first-pass extraction, and whether a
  stronger verifier is needed for low-confidence or financially sensitive items.

**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Backlog 999.24: Source-ref-first read/search contract — remove filesystem path compatibility layer

**Goal:** Before adding Telegram or any other non-filesystem source, make
dotMD's read/search contract source-ref-first instead of filesystem-path-first.
Phase 25 intentionally preserved `file_paths` and `read(file_path)` while the
source model was introduced. In hindsight this compatibility was mostly useful
as a migration safety rail, not as a real external-client requirement: dotMD is
currently a single-user/single-runtime service and can tolerate a breaking
contract change if it simplifies the next source-adapter phases.

**Context captured 2026-05-06:**
- Phase 25 shipped `SourceDocument`, `ChunkProvenance`, `source_documents`, and
  `chunk_source_provenance_<strategy>`, but kept `SearchResult.file_paths`, MCP
  `SearchHit.file_paths`, MCP `read(file_path, start, end)`, and
  `chunk_file_paths_<strategy>` as the compatibility-authoritative path.
- That shape is still filesystem-centric. If Telegram read-only is implemented
  next without cleanup, the Telegram adapter will likely inherit path-shaped
  APIs and require another compatibility bridge.
- There are no external dotMD users or third-party MCP clients to protect. The
  only current consumers are our own agents and service workflows, so an
  intentional breaking change is acceptable if it is planned and tested.

**Proposed scope:**
- Make `ref` / `(namespace, document_ref)` the primary identity returned from
  search results and used by read/drill-style APIs.
- Replace or supersede MCP `read(file_path, start, end)` with source-aware
  `read(ref, start, end)` or an equivalent `SourceRef` input contract.
- Keep filesystem path as source metadata (`source_uri` / display path) for
  filesystem documents, not as the universal public identity.
- Decide whether `SearchResult.file_paths` becomes optional display metadata,
  `source_refs`, or is removed from the public MCP/API shape.
- Reassess `chunk_file_paths_<strategy>`: keep it only if it remains needed as
  an internal holder table for content-addressed dedup, not as the public read
  contract.
- Update `drill(file_path)` and any docs/tests that assume path-first lookup.
- Run a live MCP smoke against the local container after the breaking contract
  change, because our own agents are the real consumer.

**Migration constraint: avoid full reindex whenever possible**
- Every refactor, new feature, and bugfix in dotMD should first be evaluated
  through one operational question: will this require a full reindex or not?
- The phase should be planned as an API/schema-contract migration over the
  existing index wherever possible, not as a rebuild of all chunks, vectors,
  metadata embeddings, FTS rows, or graph state.
- Avoid requiring `dotmd index --force`, full TEI re-embedding, full metadata
  vector recomputation, or full graph rebuild unless the plan proves there is
  no practical incremental path.
- Prefer deriving source refs from already persisted Phase 25 data:
  `source_documents`, `chunk_source_provenance_<strategy>`, and existing
  filesystem document refs. Backfill only missing lightweight rows if needed.
- Any unavoidable data migration must be idempotent, resumable, and scoped to
  metadata/reference rows, with a dry-run/count report before writes.
- A plan that proposes full reindex must treat it as a major cost/risk item
  requiring an explicit user decision, because current full rebuild cost is
  about three days.

**Out of scope:**
- Telegram adapter implementation.
- Source-unit emission for non-filesystem sources.
- Entity catalogs, canonical identity resolution, TTL, and second-source
  validation.
- Removing every internal filesystem path. Filesystem sources still need paths
  for discovery, local file reads, display, and delete detection.

**Open design questions:**
- Should the new public input be a plain `ref` string like
  `filesystem:/abs/path.md`, or a structured `{namespace, document_ref}` object?
- Should filesystem search still expose display paths for convenience while
  making `ref` the only stable read key?
- Should `drill` merge into `read(ref)` or remain a separate source-aware
  metadata tool?
- How much of `chunk_file_paths_<strategy>` is still required for
  content-dedup holder semantics after the public path contract is removed?

**Plans:** 0 plans

Plans:
- [ ] TBD (promote before Telegram/non-filesystem source work)

---

### Future ideas:
- Semantic chunking (split by topic similarity, not just structure)
- Doc-level chunks (whole-document embeddings for broad queries)
- Query-time NER via GLiNER (complement entity catalog string matching)
- Telegram/chat history as additional data source

### Phase 15: Content-addressed caching: embedding cache, extraction cache, content-based chunk_id

**Goal:** Prevent expensive reindexing (GLiNER + TEI) when files move or mount paths change. Three improvements in order: embedding cache (B) → extraction cache (C) → content-based chunk_id migration (A).
**Requirements**: TBD
**Plans:** 3/3 plans complete

Plans:
- [x] Plan 1: Global embedding cache by text_hash (skip TEI on file moves)
- [x] Plan 2: Extraction cache by (text_hash + model + entity_types_hash) (skip GLiNER on file moves)
- [x] Plan 3: Content-based chunk_id + switch to BLAKE3. chunk_id = blake3(file_content_checksum + ":" + chunk_index + ":" + chunk_strategy). Migration: stop → backup → SQL UPDATE all tables → verify → restart. Superseded by Phase 16 M2M migration where needed.

### Phase 16: Content-dedup schema — many-to-many chunks to file_paths

**Goal:** Support content-addressed chunk_ids with multiple file_paths pointing to the same chunk. Unblocks Phase 15's migration_v15 (collision-blocked) and delivers real storage + search-quality wins.

**Depends on:** Phase 15 (blake3 chunker + caches — deployed 2026-04-24)
**Requirements**: DEDUP-01..DEDUP-11 (see 16-RESEARCH.md)
**Plans:** 6/6 plans complete

**Context & design notes:** see `.planning/phases/16-content-dedup-schema-many-to-many-chunks-to-file-paths/16-CONTEXT.md` — edge cases, schema sketch, open questions, expected plan breakdown (migrated from backlog 2026-04-24). Researcher audit in `16-RESEARCH.md`.

Plans:
- [x] 16-06-test-suite-PLAN.md — Wave 0 RED fixtures + test skeletons (conftest, collision/empty/pre-v16 DBs, round-trip parity)
- [x] 16-01-schema-migration-core-PLAN.md — Wave 2 M2M schema, blake3 remap, collision collapse, char_offset drop, v15 stub
- [x] 16-02-migration-ops-modes-PLAN.md — Wave 3 `dotmd migrate {run,status}`, --dry-run, --verify-only, progress logs
- [x] 16-03-ingest-flow-rewrite-PLAN.md — Wave 3 INSERT OR IGNORE ingest + trickle advisory-lock startup check
- [x] 16-04-purge-and-change-detection-PLAN.md — Wave 3 decrement-cascade _purge_file + M2M orphan sweep
- [x] 16-05-search-api-clean-break-PLAN.md — Wave 3 SearchResult.file_paths: list[Path] across models/fusion/CLI/MCP

### Phase 20: Reranker Latency Benchmark

**Goal:** Establish a reproducible latency benchmark protocol for rerankers and select the models worth comparing for quality.
**Requirements**: RERANK-LATENCY-02, RERANK-BENCH-01
**Depends on:** Phase 19
**Plans:** 1 plan

Plans:
- [x] 20-01-latency-benchmark-protocol-PLAN.md — Define protocol, capture benchmark ledger, and run canonical latency shortlist

---

### Phase 21: Reranker Quality Benchmark

**Goal:** Compare the three latency-surviving rerankers on relevance quality against the live dotMD document index and decide which model is worth using as the production default.
**Requirements**: RERANK-QUALITY-01, RERANK-QUALITY-02, RERANK-QUALITY-03
**Depends on:** Phase 20
**Plans:** 1/1 plans complete

Phase boundary:
- Use the current production `dotmd` container and live `/dotmd-index/index.db`; do not reindex or build a synthetic corpus.
- Compare only `msmarco-minilm`, `mmarco-minilm`, and `mxbai-xsmall-v1`.
- Treat `msmarco-minilm` as a negative historical control, not as a serious Russian-language candidate.
- Use one shared retrieval/fusion candidate pool per query before reranking so model comparisons are apples-to-apples.
- Measure ranking quality first; keep hot `rerank_ms` as an operational guardrail.

Plans:
- [x] 21-01-quality-benchmark-PLAN.md — Build and run live-index reranker quality benchmark

### Phase 22: Improve Search Snippet Boundaries

**Goal:** Improve `search` snippets so agents can judge whether a hit is worth opening with `read` without guessing around mid-sentence truncation.
**Backlog source:** 999.21
**Feedback source:** feedback id=6, id=10, and fresh open feedback id=19
**Requirements:** SNIPPET-BOUNDARY-01, SNIPPET-CONTEXT-01, SNIPPET-VERIFY-01
**Depends on:** Phase 21
**Plans:** 1/1 plans complete

Phase boundary:
- Expand snippets only inside the current chunk.
- Use deterministic sentence, paragraph, and chunk boundaries.
- Do not add neighboring chunks, `context_window`, speaker-turn anchors, ML,
  summarization, or semantic expansion.
- Enforce a hard cap for long sentences, recommended as `2 * snippet_length`.

Plans:
- [x] 22-01-snippet-boundary-extraction-PLAN.md — Implement and verify bounded sentence-boundary snippets

### Phase 23: Fix dotMD test contract

**Goal:** Make dotMD's test commands and tests honest by separating local and live test tiers, removing stale smoke coverage, making explicit live commands fail on missing runtime, and replacing misleading low-signal tests with behavior checks.
**Requirements:** TEST-CONTRACT-01, TEST-CONTRACT-02, TEST-CONTRACT-03, TEST-CONTRACT-04
**Depends on:** Phase 22
**Plans:** 1/1 plans complete

Phase boundary:
- Local test gates must not require live containers or external ports.
- Live MCP e2e must run inside the `dotmd` container and fail if the runtime is unavailable.
- Legacy smoke tests must be removed or replaced by the current e2e contract.
- Runtime product behavior should not change except for real regressions exposed by tests.

Plans:
- [x] 23-01-test-contract-cleanup-PLAN.md — Clean up test tiers, stale smoke, e2e fixtures, low-signal tests, and docs

### Phase 24: Config separation — user-facing settings vs internal constants

**Goal:** Split `core/config.py` into explicit user-facing configuration versus
internal tuning constants so production misconfiguration fails loudly instead
of being hidden by Python defaults.
**Requirements**: TBD
**Depends on:** Phase 23
**Backlog source:** 999.6
**Plans:** 2/2 plans complete

Phase context:
- Current `Settings` has many Python defaults. When TOML overrides exist,
  defaults are silently ignored, which previously hid why new
  `indexing_exclude` defaults had no effect.
- Defaults on environment-specific settings such as URLs, paths, model names,
  and index locations are unsafe for production because they let missing config
  ship.
- Internal tuning values such as fusion sizes, snippet lengths, polling
  intervals, and thresholds should remain defaults/constants, not required
  operator config.

Initial scope from backlog 999.6:
- Audit every field in `Settings`: user config vs internal constant.
- User config should be explicit and fail loudly when missing where appropriate:
  `indexing_paths`, `indexing_exclude`, `data_dir`, `index_dir`,
  `embedding_url`, `falkordb_url`, `embedding_model`, `ner_model_name`,
  `reranker_model`, `chunk_strategy`.
- Internal constants should move to module-level constants or a dedicated
  constants structure where that improves clarity: `max_chunk_tokens`,
  `chunk_overlap_tokens`, `fusion_k`, `rerank_pool_size`, `snippet_length`,
  `default_top_k`, `poll_interval_seconds`, `tei_batch_size`, and tuning
  thresholds.
- Feature flags can remain settings booleans, for example `profile_indexing`
  and `read_only`.
- Update config templates and docs with the full user-facing surface.

Plans:
- [x] 24-01-config-boundary-and-validation-PLAN.md — Separate `Settings` from internal defaults, add runtime validation, and migrate effective exclude usage
- [x] 24-02-startup-docs-and-template-PLAN.md — Preserve/rename startup checks and align `.env.example` plus README with the new config surface

### Phase 25: Document Source Abstraction — source adapter MVP

**Goal:** Start the move from file-centric Markdown indexing toward a
source/document/source-unit/chunk model by defining the minimal source adapter
contract and reproducing current filesystem Markdown behavior through that
model.
**Requirements:** TBD
**Backlog source:** 999.22
**Depends on:** Phase 24
**Plans:** 4/4 plans complete

Phase context:
- Use the architecture docs linked from backlog `999.22` as the source of
  truth: `docs/source-adapter-architecture.md` and
  `docs/source-adapter-architecture-panel-review.md`.
- Keep the first implementation path MVP-first: minimal source model shim and
  filesystem Markdown compatibility. Telegram read-only is the intended first
  non-filesystem validation source after this phase, not part of Phase 25.
- Preserve the source-vs-parser distinction: source adapters discover assets
  and units; parser/chunking behavior follows media type and parser metadata.
- Keep entity catalogs, fuzzy identity resolution, delete/edit propagation, and
  second-source validation as follow-up scope unless planning explicitly pulls
  a minimal slice into this phase.

Plans:
**Wave 1**
- [x] 25-01-domain-models-and-filesystem-adapter-PLAN.md — Define source-aware domain models and the in-process filesystem Markdown adapter contract

**Wave 2** *(blocked on Wave 1 completion)*
- [x] 25-02-ingestion-routing-and-chunk-provenance-PLAN.md — Route current Markdown ingestion through source documents and preserve chunk/fingerprint behavior

**Wave 3** *(blocked on Wave 2 completion)*
- [x] 25-03-provenance-persistence-and-read-search-compatibility-PLAN.md — Persist minimal source provenance while preserving `file_paths` and MCP read/search compatibility

**Wave 4** *(blocked on Wave 3 completion)*
- [x] 25-04-regression-docs-and-phase-verification-PLAN.md — Add cross-surface regression coverage, docs, and final phase verification

### Phase 26: Source-ref-first read/search contract cleanup

**Goal:** Remove the Phase 25 filesystem-path-first compatibility layer from
dotMD's public read/search contract before adding Telegram or other
non-filesystem sources. Make `ref` / `(namespace, document_ref)` the primary
identity for search hits and read/drill-style APIs, while keeping filesystem
paths only where they are still needed for discovery, local file reads, display,
delete detection, or content-dedup holder semantics.
**Requirements**: TBD
**Depends on:** Phase 25
**Backlog source:** 999.24
**Plans:** 3 plans

Phase context:
- Phase 25 shipped `SourceDocument`, `ChunkProvenance`, `source_documents`, and
  `chunk_source_provenance_<strategy>`, but deliberately preserved
  `SearchResult.file_paths`, MCP `SearchHit.file_paths`, MCP
  `read(file_path, start, end)`, and `chunk_file_paths_<strategy>` as
  compatibility-authoritative.
- dotMD has no external users or third-party MCP clients to protect. The only
  current consumers are our own agents and service workflows, so a deliberate
  breaking change is acceptable if it simplifies the next source-adapter phases.
- Telegram read-only must not inherit a filesystem-shaped API. This phase should
  clean the contract before Telegram/non-filesystem source implementation.
- Every refactor, feature, and bugfix must first be evaluated through the
  operational question: will this require a full reindex or not?
- Avoid full reindex whenever possible. Do not require `dotmd index --force`,
  full TEI re-embedding, full metadata-vector recomputation, or full graph
  rebuild unless planning proves there is no practical incremental path and asks
  for an explicit user decision. Current full rebuild cost is about three days.
- Prefer deriving source refs from existing Phase 25 data:
  `source_documents`, `chunk_source_provenance_<strategy>`, and filesystem
  document refs. Backfill only missing lightweight metadata/reference rows if
  needed.

Phase boundary:
- In scope: source-ref-first search/read/drill contract, MCP/API/test/docs
  updates, and a live MCP smoke against the local container after implementation.
- In scope: reassess whether `chunk_file_paths_<strategy>` remains an internal
  holder table for dedup, but stop treating it as the public read contract.
- Out of scope: Telegram adapter implementation, source-unit emission for
  non-filesystem sources, entity catalogs, canonical identity resolution, TTL,
  second-source validation, and removing filesystem paths needed internally for
  filesystem source operation.

Plans:
**Wave 1**
- [ ] 26-01-core-ref-model-and-service-resolution-PLAN.md — Core ref model and service resolution

**Wave 2** *(blocked on Wave 1 completion)*
- [ ] 26-02-mcp-api-cli-ref-contract-PLAN.md — MCP/API/CLI ref contract

**Wave 3** *(blocked on Wave 2 completion)*
- [ ] 26-03-regression-docs-and-live-smoke-PLAN.md — Regression, documentation, and live smoke

---

*Roadmap created: 2026-03-26*
*Last updated: 2026-05-06*
