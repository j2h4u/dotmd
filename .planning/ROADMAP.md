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
- [x] 999.3 Automatic orphan cleanup — impossible by construction after Phase 16 M2M (2026-04-25)
- [x] 999.5 Ignore patterns for data discovery — extended default excludes in config.py (2026-04-24)
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
| 15. Content-addressed caching | 2/3 | In Progress|  |
| 16. Content-dedup schema | 6/6 | Complete   | 2026-04-25 |
| 17. MCP OAuth 2.0 — Claude Desktop connector | 3/3 | Complete   | 2026-04-30 |

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

## Backlog

### Phase 999.2: Pipeline parallelism — overlap GLiNER and TEI across files (BACKLOG)

**Goal:** Eliminate idle time between GLiNER extraction and TEI embedding by running lightweight phases (purge, chunk, save, fts5, graph, fingerprints) concurrently with the heavy phases.

**Architecture decision:** Two async workers + asyncio.Queue(maxsize=1) + asyncio.Semaphore(1) as CPU gate. Expert panel unanimous. Full context in profiling notes: `.planning/notes/profiling-2026-04-02.md`.

**Expected gain:** ~1.5x over current 4.53 s/chunk.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.3: Automatic orphan cleanup — chunks/vec/FTS rows without live file_path (DONE 2026-04-25)

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

### Phase 999.7: Remove migration_v16 dead code after soak (BACKLOG)

**Goal:** Delete the migration_v16 scaffolding once Phase 16 has soaked in production without rollback need.

**Context (updated 2026-04-25):** Phase 16 shipped to production on 2026-04-25 — `dotmd migrate run` succeeded (486 collisions collapsed, 0 divergence, no override). v15-era dead code (migration_v15 stub, cleanup_v15_pre, v15 tests — 406 lines) was deleted same day in a separate commit since v15 was collision-blocked, never ran in production, and had no rollback path after `pre-phase15.bak` was removed. Only v16 cleanup remains here, gated by soak.

**Trigger condition:** Phase 16 stable in production for **2–4 weeks** without any rollback need, AND `index.db.v16-backup` is being removed in the same sweep (i.e. committing to "no rollback path" simultaneously with deleting the rollback script).

**Scope (one phase, one mental purge):**
- `backend/src/dotmd/ingestion/migration_v16.py` — full migration logic (~1500 lines); delete.
- `backend/src/dotmd/cli.py` — remove the `dotmd migrate` Click group entirely (run + status subcommands). `migrate status`'s only purpose is to report "you need to run the migration"; once migration is gone, the status command has no meaning.
- All migration tests under `backend/tests/ingestion/test_migration_v16*.py` and `backend/tests/cli/test_migrate_cli.py`.
- `index.db.v16-backup` on the dotmd-index volume (~254 MB).
- `PayloadDivergenceBlocked` exception class — only raised by migration_v16; delete alongside.
- Any `chunk_fingerprints_*`-table consumers that exist *only* to feed migration_v16's body_checksum lookup (verify with grep before deletion — fingerprints are also used by `FileTracker`, leave that path intact).

**Out of scope:**
- The M2M schema itself, `_holder_aware_chunk_cleanup`, `chunk_file_paths_*` tables — these are now the live schema, not migration code.

**Plans:**
- [ ] TBD (promote with `/gsd:review-backlog` when soak is done)

### Phase 999.8: Per-holder heading hierarchy — promote `heading_hierarchy` + `level` to M2M (BACKLOG)

**Goal:** If future feature surfaces per-holder heading context (breadcrumb per search hit, heading-filtered search), move `heading_hierarchy` and `level` from `chunks_*` into `chunk_file_paths_*` so each holder carries its own context.

**Context 2026-04-24:** Phase 16 locked these fields on the `chunks_*` row with a fail-closed divergence policy (Decision #10). Observed divergence count on current KB = 0 (all duplicates are symlinks/mirrors with identical headings), so the scope expansion was deferred. Trigger condition: any downstream feature that needs per-holder heading.

**Plans:**
- [ ] TBD (promote when a consumer emerges)

### Phase 999.9: MCP tool — graph entity inspection (BACKLOG)

**Goal:** Expose graph traversal through MCP so agents can explore entity context, not just retrieve flat snippets.

**Context 2026-04-25:** Hermes (Tiger's Claw) searched for "Даннинг-Крюгер" and found a relevant voicenote (score 0.904). When asked to explore further — linked entities, related conversations, speaker context — it couldn't. dotmd has 42k entities and 256k graph edges in FalkorDB, but they're used only internally for RRF ranking. Nothing surfaces through MCP. Hermes noted: "граф используется под капотом для reranking, но наружу выдаётся всё равно плоский список сниппетов."

**Proposed tools:**
- `get_entity(name)` → entity properties + type
- `related_entities(name, depth=1)` → neighbours with relation types and weights
- Possibly: `entity_mentions(name)` → chunks where entity appears

**Plans:**
- [ ] TBD

---

### Phase 999.10: MCP tool — document metadata / frontmatter (DONE 2026-04-26)

**Goal:** Let agents retrieve structured metadata (frontmatter, speaker, tags, date) for a specific file by path, as a follow-up to a search result.

**Context 2026-04-25:** Same Hermes session. After finding the Даннинг-Крюгер voicenote, it tried to get its frontmatter (speaker, tags, full YAML) — no way to do it. `list_resources` returns empty, `search` only returns text snippets. The file lives inside the dotmd container at `/mnt/knowledgebase/…` which Hermes cannot access directly. Hermes concluded: "dotmd не отдаёт structured metadata через MCP-интерфейс."

**Done 2026-04-26:** Implemented as `drill(file_path)` — name chosen over `get_metadata` to convey the "dig deeper after search" intent. Returns frontmatter (read from disk), chunk_count (from M2M table), and entities (from FalkorDB graph). Also covers part of 999.9 — agents get entity names from `drill` and can use them for follow-up searches.

---

### Phase 999.11: MCP list_resources — indexed file registry (BACKLOG)

**Goal:** Implement MCP `list_resources` so clients can enumerate indexed files by URI and read their metadata or content snippets.

**Context 2026-04-25:** Hermes called `list_resources` and got an empty list. MCP supports resources as a first-class primitive (URI-addressable data alongside tools and prompts). dotmd ignores this. Low immediate value at 730 files (can't paginate usefully), but the hook is needed for agents that do resource-oriented workflows. Prerequisite for proper `read_resource` support.

**Note:** Lower priority than 999.9 and 999.10. Useful only if an agent workflow specifically iterates over the file list rather than searching. A `get_metadata(file_path)` tool (999.10) is more immediately useful.

**Plans:**
- [ ] TBD

---

### Phase 999.12: Dual-encoder unified embedding — decoupled metadata vectors (BACKLOG)

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

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.13: Вернуть stateful MCP режим + notifications/tools/list_changed (BACKLOG)

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

### Phase 999.14: Migrate vector store from sqlite-vec to pgvector — shared Postgres service (BACKLOG)

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

### Phase 999.15: Автокалибровка весов фьюзинга через кросс-энкодер (BACKLOG)

**Goal:** Автоматически подбирать веса `DOTMD_EMBEDDING_WEIGHTS` без ручной разметки, используя кросс-энкодер как оракул качества.

**Mechanism:** По накопленному журналу запросов (`search_log` в index.db, введён в Phase 999.12): взять N последних запросов → для каждого прогнать топ-K результатов через cross-encoder reranker → получить "правильный" ranking → sweep весов → выбрать веса при которых e_fused ranking ближе всего к reranker ranking → записать лучшие веса в `vec_config` → пересчитать e_fused (локальная математика, секунды) → применить.

**Depends on:** Phase 999.12 (query logging + N-vector scheme)

**Trigger:** Накоплено достаточно запросов в `search_log` для статистически значимого sweep (~100+ запросов).

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.16: Автокалибровка весов через межмодульное согласие (BACKLOG)

**Goal:** Использовать согласие между semantic + FTS5 + graph как несупервизированный сигнал качества для калибровки весов фьюзинга.

**Mechanism:** Когда все три движка возвращают один результат в топе — это сильный сигнал что результат правильный. Использовать эти "consensus hits" для оценки качества разных весов без единой размеченной метки.

**Depends on:** Phase 999.12 (query logging)

**Note:** Более шумный сигнал чем кросс-энкодер (999.15). Полезен как дополнительная валидация или когда reranker недоступен.

**Plans:**
- [ ] TBD (promote with /gsd-review-backlog when ready)

### Phase 999.17: Fix shared-chunk e_fused — per-file fused vector for multi-file chunks (BACKLOG)

**Goal:** Устранить edge case: один e_fused на chunk_id при shared chunks. Текущее состояние — фьюзинг использует e_meta первого файла навсегда.
**Context:** Аудит 2026-04-29: 299/18515 (1.61%) чанков shared. Большинство — один файл в двух местах (skills cache + source repo) или voicenotes одной сессии → e_meta практически идентична, семантическое воздействие минимально. Но архитектурно некорректно.
**Fix cost when needed:** Без TEI-запросов — переиспользовать хранящиеся e_text + e_meta_правильного_файла, пересчитать e_fused математически только для ~300 чанков. Требует изменения схемы vec_meta: UNIQUE(chunk_id) → UNIQUE(chunk_id, file_path) для shared chunks.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.18: Extend devtools MCP client to support HTTP/streamable-http transport (BACKLOG)

**Goal:** Extend `backend/devtools/mcp_client/` to support HTTP transport alongside existing stdio. Accept a URL, connect via `streamablehttp_client`, run MCP initialize + tool calls — same interface as current stdio client.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.20: Заменить English-only reranker на мультиязычный (BACKLOG)

**Goal:** Текущий cross-encoder `cross-encoder/ms-marco-MiniLM-L-6-v2` обучен только на английском (MS MARCO). При русскоязычных запросах выдаёт бессмысленные скоры, что убивает качество семантического поиска — выживают только точные FTS5-совпадения. Заменить на мультиязычную модель.

**Контекст:** Blend в пайплайне — `0.4 * norm_fused + 0.6 * norm_re`. При garbage-скорах cross-encoder для русского текста 60% веса на шум = семантика теряется.

**Кандидаты (апрель 2026):**

| Модель | Параметры | Обновление | CPU-скорость | Примечание |
|--------|----------|------------|-------------|-----------|
| `cross-encoder/ms-marco-MiniLM-L-6-v2` (**текущий**) | ~66M | 2021 | Быстро | English-only, не работает на русском |
| `Alibaba-NLP/gte-multilingual-reranker-base` | 306M | Март 2024 | Быстрее всех среди мультиязычных | TEI-native (нужен отдельный TEI-инстанс), Apache 2.0 |
| `BAAI/bge-reranker-v2-m3` | 568M | Фев 2024 | ~2x медленнее gte | 9.1M скачиваний/мес, самый проверенный, работает с `CrossEncoder` |
| `nreimers/mmarco-mMiniLMv2-L12-H384-v1` | 117M | 2022 | Быстро | Trained on multilingual mMARCO (incl. Russian), не обновлялся |

**Архитектурный выбор:**
- `bge-reranker-v2-m3` — drop-in замена (работает с `sentence_transformers.CrossEncoder` без изменений архитектуры)
- `gte-multilingual-reranker-base` — TEI-native, требует отдельного TEI-инстанса для reranking

**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.19: Обновить transformers с 4.57.6 до 5.x (BACKLOG)

**Goal:** Перевести в отдельной ветке на transformers 5.x (текущая 5.7.0), проверить совместимость с GLiNER и sentence-transformers, убедиться что CPU-only wheels работают. Потенциально устраняет warning про sentencepiece fast tokenizer.
**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

### Phase 999.21: Улучшить границы сниппетов в Search — контекст вокруг матча (BACKLOG)

**Goal:** Сниппеты в результатах Search обрезаются на середине предложения. Агент видит цитату, но не может понять, что она значит — продолжение может кардинально менять смысл. Пример из реальной сессии: "они пообещали $200" — продолжается ли это "...уже три месяца" или "...если я сделаю адаптер"? Огромная разница. Сейчас агент либо делает дополнительный `read` для верификации, либо использует цитату как есть с риском ошибки.

**Контекст и источник:** Зафиксировано в feedback id=6 (апрель 2026), подтверждено в id=10 тем же автором после редизайна API. Автор понизил приоритет — "с `read` стало much less painful" — но не закрыл вопрос. Сниппеты теперь используются как "pointer на файл", а не как "что было сказано", поэтому проблема менее острая. Тем не менее: лишний `read`-вызов ради верификации одной цитаты — это waste, и в длинных сессиях накапливается.

**Варианты решения (не выбрано, требует проработки):**
- `context_window` параметр в `search` — агент запрашивает ±N чанков вокруг матча явно
- По умолчанию включать ±1 чанк в каждый результат (дешёво, решает ~80% случаев по оценке автора)
- Расширять сниппет до границы предложения (требует NLP или простой heuristic на `.`, `?`, `!`)
- Возвращать полный чанк вместо подстроки (самый простой вариант, чуть больше токенов)

**Неизвестно:**
- Насколько текущие сниппеты коррелируют с границами чанков vs внутренними подстроками
- Стоимость добавления ±1 чанка по токенам в типичной сессии

**Requirements:** TBD
**Plans:** 0 plans

Plans:
- [ ] TBD (promote with /gsd-review-backlog when ready)

---

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
**Plans:** 6/6 plans complete

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
