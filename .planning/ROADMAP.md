# Roadmap: dotMD

**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.

## Milestones

- [x] **v1.1 Incremental Indexing** — Phases 1-3 (shipped 2026-03-26)
- [x] **v1.2 FalkorDB Migration & Search Fix** — Phases 4-6 (shipped 2026-03-27)
- [x] **v1.3 Production Packaging & Background Indexing** — Phases 7-10 (shipped 2026-03-28)
- [x] **v1.4 Search Quality & Architecture** — Phases 15-26 (shipped 2026-05-06)
- [x] **v1.5 Telegram Source Adapter** — Phases 27-31 (shipped 2026-05-08)
- [x] **v1.6 Unified Source Architecture** — Phases 32-37 (shipped 2026-05-13)
- [x] **v1.7 Storage Simplification** — Phase 38 (shipped 2026-06-12)
- 🚧 **v1.8 SurrealDB-Native Storage Cutover** — Phases 39-46 (active)

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
<summary>Legacy phase records still present on disk (Phases 11-14)</summary>

These phase directories predate the finalized v1.4 archive but remain on disk,
so the active roadmap keeps minimal records for GSD health checks.

### Phase 11: Embedding Model Evaluation

- [x] E5-large vs Qwen3-Embedding-0.6B A/B comparison
- [x] Multi-model vector store support

### Phase 12: Indexing Integrity Rework

- [x] Unified database, split fingerprints, embedding reuse, and exclusive index lock

### Phase 13: Content-Aware Chunking & Search

- [x] Speaker-turn chunking, context prefix injection, graph-direct retrieval, and FTS5 improvements

### Phase 14: Frontmatter-Driven Indexing

- [x] Structured frontmatter handling across chunk text, graph, FTS5, and embeddings

</details>

<details>
<summary>v1.4 Search Quality & Architecture (Phases 15-26) — SHIPPED 2026-05-06</summary>

- [x] Phase 15: Content-addressed caching
- [x] Phase 16: Content-dedup schema
- [x] Phase 17: MCP OAuth 2.0 connector support
- [x] Phase 18: Multilingual reranker
- [x] Phase 19: Reranker adapter layer and multi-model comparison
- [x] Phase 20: Reranker latency benchmark
- [x] Phase 21: Reranker quality benchmark
- [x] Phase 22: Search snippet boundaries
- [x] Phase 23: Test contract cleanup
- [x] Phase 24: Config separation
- [x] Phase 25: Document source abstraction MVP
- [x] Phase 26: Source-ref-first read/search contract cleanup

See: `.planning/milestones/v1.4-ROADMAP.md`

</details>

<details>
<summary>v1.5 Telegram Source Adapter (Phases 27-31) — SHIPPED 2026-05-08</summary>

- [x] Phase 27: Resource bindings and retained artifacts foundation
- [x] Phase 28: Application source provider contract
- [x] Phase 29: Telegram adapter MVP ingestion
- [ ] Phase 30: Incremental Telegram sync and reuse — deferred to Backlog 999.30
- [x] Phase 31: Telegram search/read/drill smoke — completed 2026-05-08

See: `.planning/milestones/v1.5-ROADMAP.md`

</details>

<details>
<summary>v1.6 Unified Source Architecture (Phases 32-37) — SHIPPED 2026-05-13</summary>

- [x] Phase 32: Source capability registry
- [x] Phase 33: Source lifecycle/config/auth/cursor boundary
- [x] Phase 34: Federated SearchCandidate contract
- [x] Phase 35: Filesystem unified source adapter
- [x] Phase 36: Telegram unified sync and federated search
- [x] Phase 37: Airweave connector compatibility spike

See: `.planning/milestones/v1.6-ROADMAP.md`

</details>

<details>
<summary>v1.7 Storage Simplification (Phase 38) — SHIPPED 2026-06-12</summary>

- [x] Phase 38: Embedded SurrealDB storage spike (completed 2026-06-12)

Goal: Decide whether dotMD should replace separate SQLite/sqlite-vec/FTS5 and
FalkorDB storage with one embedded SurrealDB-backed storage layer while
migrating existing production data wherever safe instead of recomputing chunks,
embeddings, or extracted entities on CPU.

Outcome: first compatibility/parity-style prototype rejected as migrate-ready;
Phase 38 evidence becomes the input to v1.8 SurrealDB-native cutover planning.

See: `.planning/milestones/v1.7-ROADMAP.md`

</details>

## v1.8 SurrealDB-Native Storage Cutover (Phases 39-46) — ACTIVE

Goal: Replace the current SQLite/sqlite-vec/FTS5 + FalkorDB storage/retrieval
stack with one SurrealDB-native persistence and retrieval architecture,
validate search quality against real user scenarios, cut production over, and
delete the legacy stack without fallback backends or compatibility shims.

### Phase 39: SurrealDB-native retrieval contract

**Goal:** Define the new SurrealDB-native search semantics and acceptance
categories before implementation starts.
**Depends on:** Phase 38
**Plans:** 1 plan

- [x] Define the target search semantics for BM25 weighted fields, vector
  search, graph traversal, hybrid fusion, and reranker inputs.

- [x] Treat the old stack as baseline evidence only, not as a compatibility
  target.

- [x] Define accepted-difference categories: improvement, harmless reorder,
  regression, and unclear.

Plans:

- [x] 39-01: Define SurrealDB-native retrieval contract and migration reuse policy

### Phase 40: Evaluation harness and golden queries

**Goal:** Build the quality evaluation surface that decides whether SurrealDB
search is good enough to cut over.
**Depends on:** Phase 39
**Plans:** 1/1 plans complete

- [ ] Build a golden query set covering title-heavy, tag-heavy, body-heavy,
  semantic, graph/entity, hybrid, source-ref, and mixed RU/EN scenarios.

- [ ] Produce machine-readable diff reports for old-vs-Surreal runs.
- [ ] Gate on user-visible quality and explainable differences, not exact rank
  parity.

Plans:

- [x] 40-01-PLAN.md - Evaluation harness, golden corpus, diff classification, and cutover-gate reporting.

### Phase 41: Production-grade Surreal schema and import

**Goal:** Convert the Phase 38 schema/import proof into production migration
tooling that preserves existing data where practical.
**Depends on:** Phase 39 and Phase 40
**Requirements:** SURR-MIG-01, SURR-MIG-02, SURR-MIG-03
**Plans:** 3/3 plans complete

- [x] Harden the Phase 38 schema/import proof into production migration code.
- [x] Preserve existing chunks, embeddings, source refs, graph relations,
  feedback, cursors, checkpoints, and retained artifacts where practical.

- [x] Avoid default rechunking, reembedding, and entity re-extraction unless a
  phase explicitly proves there is no safe transform path.

Plans:

- [x] 41-01-PLAN.md - Production schema catalog, category coverage, and storage DDL safety contract.
- [x] 41-02-PLAN.md - Production migration runner, source-capture manifests, overwrite policy, checkpoints, and partial-write semantics.
- [x] 41-03-PLAN.md - Migration evidence reports, verified restore rehearsal, devtool runner, and runbook.

### Phase 42: Surreal-native retrieval implementation

**Goal:** Implement full-text, vector, graph, and hybrid retrieval on real
SurrealDB capabilities instead of Phase 38 proxy logic.
**Depends on:** Phase 39 and Phase 41
**Plans:** 4/4 plans complete

- [ ] Implement real SurrealDB BM25/full-text indexes with weighted fields.
- [ ] Implement Surreal vector search using the chosen HNSW/DISKANN strategy.
- [ ] Implement graph relation traversal and hybrid fusion over Surreal result
  sets.

Plans:

- [x] 42-01-PLAN.md - Retrieval schema indexes, lexical field materialization, and runtime capability probes.
- [x] 42-02-PLAN.md - Surreal BM25 full-text and HNSW vector search engines.
- [x] 42-03-PLAN.md - Relation-backed Surreal graph direct retrieval.
- [x] 42-04-PLAN.md - Surreal hybrid fusion through the service candidate-pool seam.

### Phase 43: Shadow run and quality gate

**Goal:** Compare the old stack and standalone SurrealDB candidate on
production-derived data, classify every material difference, and close the
phase as a migration/shadow-run spike rather than a production cutover.
**Depends on:** Phase 40, Phase 41, and Phase 42
**Plans:** 3/3 plans executed

- [x] Run old stack and standalone SurrealDB side by side on production-derived data.
- [x] Record search quality, latency, index build time, store size, and memory
  evidence.

- [x] Resolve every regression or explicitly accept the new semantics.

Plans:

- [x] 43-01-PLAN.md - Shadow metric contract, memory evidence, and scale-gate validation.
- [x] 43-02-PLAN.md - Manifest-bound shadow-run runner, explicit Surreal override capture, and operator runbook.
- [x] 43-03-PLAN.md - Bounded production-derived evidence bundle and semantic-difference acceptance ledger.

### Phase 44: Standalone quality gate and cutover decision

**Goal:** Decide whether the standalone SurrealDB candidate is ready for
production cutover after Phase 43 evidence, with embedded SurrealKV rejected
for production because HNSW creation on the production-derived embeddings
table hits the segment-size blocker.
**Depends on:** Phase 43
**Plans:** 1/1 plan executed

- [x] Review standalone SurrealDB quality, deferred indexes, and rollout risk.
- [x] Keep the embedded SurrealKV path rejected for production until the HNSW
  segment-size blocker is removed.
- [x] Decide whether to cut over live dotMD runtime to standalone SurrealDB or
  hold the migration.
- [x] Verify MCP/API/CLI/trickle behavior against live production surfaces.
- [x] Keep rollback operationally available only until the cutover is accepted.

Plans:

- [x] 44-01-PLAN.md - Standalone SurrealDB final quality gate, smoke matrix, cutover/no-go decision, and rollback boundary.

Decision:

- [x] NO-GO: do not cut production over yet. Runtime wiring for standalone
  SurrealDB is missing for MCP/API/CLI/trickle, and reranker-on latency is not
  production-ready.
- [x] Add a follow-up runtime-wiring phase before retrying cutover.

### Phase 45: Standalone SurrealDB runtime wiring and smoke

**Goal:** Make standalone SurrealDB a real runtime search backend and prove the
MCP/API/CLI smoke surface before retrying production cutover.
**Depends on:** Phase 44
**Plans:** 1/1 plan complete

- [x] Add config-gated service startup wiring for standalone SurrealDB retrieval.
- [x] Run controlled Surreal-backed service smoke without cutting over production.
- [x] Record MCP/API/CLI smoke evidence or concrete blockers.
- [x] Record explicit trickle write-path decision before cutover retry.

Plans:

- [x] 45-01-PLAN.md - Standalone SurrealDB runtime wiring, controlled smoke, and trickle decision.

Decision:

- [x] Runtime retrieval works through CLI/API/MCP with `search_backend=surreal`.
- [x] Trickle remains old-stack-only; Surreal-native writes are deferred and
  remain a cutover blocker.

### Phase 46: SurrealDB write path and trickle cutover

**Goal:** Decide and implement the write-path boundary needed for production
cutover: either make trickle/index writes update standalone SurrealDB directly,
or explicitly accept a bounded hybrid transition where old-stack writes remain
authoritative while SurrealDB is refreshed through a controlled sync path.
**Depends on:** Phase 45
**Plans:** 1/1 plan in progress

Success criteria:

- [ ] Trickle/index writes have an explicit SurrealDB strategy: direct write,
  controlled sync, or documented hybrid transition.
- [ ] Daily update behavior is proven without full reindex/re-embedding.
- [x] Failure/retry behavior is idempotent and instrumented with progress/ETA
  for operations expected to exceed 120 seconds.
- [ ] Production cutover criteria are updated with write-path evidence.

Plans:

- [ ] 46-01-PLAN.md - SurrealDB write-path/trickle cutover strategy, implementation, and smoke.

Progress:

- [x] Delta manifest, sync runner, row builder, and safe point-upsert writer implemented.
- [x] Fake-connection and temporary `surrealkv://` tests prove idempotent replay,
  stable bootstrap IDs, exact tombstones, unrelated-row preservation, and no
  bulk delete/insert paths.
- [ ] Real changed-file daily-update smoke remains before cutover decision.

### Phase 47: Legacy stack removal

**Goal:** Delete the old SQLite/sqlite-vec/FTS5, FalkorDB, and LadybugDB stack
after SurrealDB cutover is accepted.
**Depends on:** Accepted cutover retry after Phase 46
**Plans:** TBD

- [ ] Delete SQLite/sqlite-vec/FTS5, FalkorDB, and LadybugDB storage/retrieval
  code paths, configs, tests, docs, env vars, and deployment assumptions.

- [ ] Remove temporary evaluator/baseline code that only exists for migration.
- [ ] Verify there are no fallback backend switches, compat shims, or dead
  legacy imports left.

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
| 25. Document source abstraction MVP | 4/4 | Complete | 2026-05-06 |
| 26. Source-ref-first read/search contract cleanup | 3/3 | Complete | 2026-05-06 |
| 27. Resource bindings and retained artifacts foundation | 4/4 | Complete    | 2026-05-07 |
| 28. Application source provider contract | 4/4 | Complete    | 2026-05-07 |
| 29. Telegram adapter MVP ingestion | 4/4 | Complete    | 2026-05-08 |
| 30. Incremental Telegram sync and reuse | v1.5 | Deferred to Backlog 999.30 | — |
| 31. Telegram search/read/drill smoke | 1/1 | Complete | 2026-05-08 |
| 32. Source capability registry | 4/4 | Complete    | 2026-05-08 |
| 33. Source lifecycle/config/auth/cursor boundary | 3/3 | Complete    | 2026-05-08 |
| 34. Federated SearchCandidate contract | 3/3 | Complete | 2026-05-10 |
| 35. Filesystem unified source adapter | 2/2 | Complete    | 2026-05-10 |
| 36. Telegram unified sync and federated search | 2/2 | Complete    | 2026-05-10 |
| 37. Airweave connector compatibility spike | 4/4 | Complete    | 2026-05-13 |
| 38. Embedded SurrealDB storage spike | 5/5 | Complete    | 2026-06-12 |
| 39. SurrealDB-native retrieval contract | 1/1 | Complete | 2026-06-13 |
| 40. Evaluation harness and golden queries | 1/1 | Complete    | 2026-06-13 |
| 41. Production-grade Surreal schema and import | v1.8 | Complete | 2026-06-14 |
| 42. Surreal-native retrieval implementation | 4/4 | Complete    | 2026-06-14 |
| 43. Shadow run and quality gate | 3/3 | Complete | 2026-06-16 |
| 44. Standalone quality gate and cutover decision | 1/1 | Complete — NO-GO | 2026-06-19 |
| 45. Standalone SurrealDB runtime wiring and smoke | v1.8 | In Progress | — |
| 46. Legacy stack removal | v1.8 | Planned | — |

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

### Backlog 999.25: Content-addressed resource bindings and retained derived artifacts

**Goal:** Before adding Telegram or any other non-filesystem source, make
dotMD's indexing model reuse already-processed content and derived artifacts
whenever possible. Resource changes such as file rename, atomic write,
delete-then-readd, export refresh, or Telegram chat append should not force
TEI embedding, NER/extraction, FTS, or graph work for chunks that were already
processed.

**Context captured 2026-05-06:**

- Phase 16 already separated `chunks_*` from `chunk_file_paths_<strategy>` M2M
  holder rows, so chunks can be shared by multiple filesystem paths.

- Phase 25 added `SourceDocument`, `source_documents`, and
  `chunk_source_provenance_<strategy>`, but filesystem `document_ref` is still
  derived from the resolved path.

- Phase 26 made source refs the public read/search contract, which means the
  next source work can stop treating filesystem paths as the universal identity.

- Current `_purge_file` is holder-aware, but if holder count drops to zero it
  physically deletes chunks/vectors/FTS/provenance immediately. That is correct
  for consistency but too eager for rename/move/reimport scenarios.

- The practical invariant for future source adapters is: if dotMD already spent
  CPU on a content unit or chunk, a later resource reshuffle should reuse that
  work instead of recomputing it.

**Current asset inventory:**

- Existing useful pieces:
  - `SourceDocument` with `namespace`, `document_ref`, `ref`,
    `content_fingerprint`, and `metadata_fingerprint`.

  - `chunks_*` keyed by `chunk_id`, no direct `file_path` column.
  - `chunk_file_paths_<strategy>` as a filesystem-specific holder table.
  - `chunk_source_provenance_<strategy>` as the first source provenance layer.
  - `FileTracker` split between body/chunk fingerprint and metadata fingerprint.
  - INSERT OR IGNORE chunk writes and existing text-hash embedding reuse.
- Missing or incomplete pieces:
  - universal active/inactive resource binding rows independent of filesystem
    path shape;

  - retained unreferenced content/artifacts with `unreferenced_since` /
    `retained_until` instead of immediate cascade delete;

  - source-unit identity below document level, e.g. Telegram message id,
    edited-message version, paragraph, heading section, or speaker turn;

  - search/read filtering through active bindings so retained inactive content
    stays physically available but invisible to users;

  - GC as an explicit or deferred cleanup step that deletes retained artifacts
    only after a grace period.

**Proposed scope:**

- Introduce a resource binding model that generalizes
  `chunk_file_paths_<strategy>` beyond filesystem paths. A binding should tie
  `{namespace, document_ref/resource_ref, source_unit_ref?, chunk_id,
  chunk_index}` to an active/inactive state.

- Preserve current filesystem behavior through an incremental migration or
  compatibility view; do not require a full reindex.

- Change deletion/orphan handling from immediate physical cascade to:
  1. deactivate/remove the public resource binding immediately;
  2. make search/read ignore inactive bindings immediately;
  3. retain unreferenced chunks/vectors/FTS/graph artifacts for a grace period;
  4. let GC physically delete expired unreferenced artifacts later.
- Make content/chunk reuse explicit: if a new active binding points at an
  existing chunk hash, attach the binding/provenance without recomputing
  embeddings, extraction, FTS, or graph unless the derived-artifact key changed.

- Treat watcher events (`created`, `modified`, `deleted`, `moved`) as wake-up
  signals for reconciliation, not as business logic for rename semantics.

- Keep resource identity and content identity separate:
  - source sync fingerprint: did the external resource change?
  - document metadata fingerprint: title/tags/path/source metadata;
  - content-unit fingerprint: message/paragraph/speaker-turn identity;
  - chunk fingerprint: normalized chunk text + strategy/parser version;
  - derived-artifact fingerprint: chunk/input + model/extractor/config version.

**Acceptance criteria ideas:**

- Atomic write `tmp -> file.md` indexes the destination without waiting for the
  hourly poll.

- Rename or delete-then-readd with identical content reuses existing chunks and
  derived artifacts, while the old public ref stops working immediately.

- Appending to a document reuses unchanged chunk/source-unit artifacts and
  processes only genuinely new or changed chunks.

- Metadata-only changes update only metadata-derived surfaces.
- Inactive retained content is not returned by search and cannot be read through
  stale refs.

- GC removes expired unreferenced artifacts without touching chunks that have
  active bindings.

- The phase includes a dry-run/count report before any migration that touches
  existing production index rows.

**Out of scope:**

- Telegram adapter implementation.
- Full historical reindex of the production corpus.
- Fuzzy identity resolution, contact/entity catalogs, or second-source
  validation.

- Perfect paragraph-level diffing for every markdown shape if an MVP source-unit
  model can preserve current behavior and unlock Telegram safely.

**Open design questions:**

- Should the first binding table be strategy-specific, global, or a compatibility
  layer over existing `chunk_file_paths_<strategy>`?

- What grace period is appropriate for retained unreferenced artifacts: fixed
  time, N poll cycles, explicit admin GC only, or configurable?

- Which source-unit granularity should filesystem Markdown use first: whole
  file, heading section, paragraph, speaker turn, or parser-specific units?

- Which derived artifacts can be safely retained without graph drift, and which
  graph edges need active-binding filtering?

- How should status/debug commands show active vs retained vs GC-pending rows?

**Plans:** 0 plans

Plans:

- [ ] TBD (promote before Telegram/non-filesystem source work)

---

### Backlog 999.26: Unified source capability registry — Airweave-style source catalog

**Goal:** Introduce one source catalog/registry model for all dotMD sources so
filesystem, Telegram, future federated providers, and Airweave-compatible
connectors are described through the same capability vocabulary.

**Context captured 2026-05-08:**

- Airweave's strongest reusable idea is not its search/indexing stack, but its
  source platform shape: source registry, typed config/auth/cursor metadata,
  declared capabilities, and source lifecycle wiring.

- dotMD currently has a stronger document/source-unit/chunk/provenance model,
  but source capabilities are still spread across filesystem-specific code,
  Telegram provider code, MCP tool behavior, and architecture docs.

- The registry should make source behavior explicit before we add more
  integrations, especially federated search sources where data may not be fully
  synced into the local index.

**Proposed scope:**

- Define a source descriptor/capability model with fields such as `short_name`,
  `display_name`, `source_kind`, config schema, auth schema, cursor schema, and
  capability flags:

  - `supports_sync`
  - `supports_federated_search`
  - `supports_read_unit_window`
  - `supports_materialization`
  - `supports_browse_tree`
  - `supports_acl`
  - `supports_incremental_cursor`
- Keep the registry dotMD-native: the canonical payload types remain
  `SourceDocument`, `SourceUnit`, `SourceUnitWindow`, and future `SourceAsset`,
  not Airweave `BaseEntity`.

- Seed the registry with existing filesystem and Telegram source descriptions.
- Document how Airweave source metadata maps into the dotMD registry without
  making Airweave a required dependency.

**Depends on:** Phase 31 or explicit post-v1.5 promotion.
**Recommended order:** First item in the Airweave-inspired architecture line.

**Anti-legacy gate:**

- This backlog line must not create a parallel "new source platform" beside
  legacy filesystem/Telegram paths. The registry work is only architectural
  groundwork; the source architecture line is not complete until filesystem and
  Telegram are registered, exercised, and verified through the same source
  capability model.

**Out of scope:**

- Running real Airweave connectors.
- Rewriting filesystem or Telegram ingestion.
- Adding new OAuth flows, UI, or external source credentials.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote when starting unified source architecture work)

---

### Backlog 999.27: Source lifecycle, typed config/auth/cursor boundary

**Goal:** Add a source lifecycle boundary that builds source instances from
typed config, credentials/auth providers, cursor state, logging, and optional
HTTP/rate-limit clients, instead of letting each adapter solve those concerns
separately.

**Context captured 2026-05-08:**

- Airweave has a useful lifecycle pattern: load source connection, resolve the
  source class from registry, load credentials/config, create auth provider and
  HTTP client, instantiate source, then validate it.

- dotMD should borrow that separation without inheriting Airweave's Postgres,
  Redis, organization/billing, Vespa, or Temporal assumptions.

- This boundary is the practical prerequisite for using third-party connector
  code because most real SaaS adapters expect typed config, credential access,
  retry/rate-limit behavior, and cursor state.

**Proposed scope:**

- Define typed config/auth/cursor models for filesystem and Telegram first.
- Add a source lifecycle service/factory that returns a ready source runtime
  from a registry entry and persisted local configuration.

- Keep credentials behind a provider interface; source adapters should not read
  raw secret storage directly.

- Define how cursor checkpointing is committed only after local persistence
  succeeds, preserving the Phase 28 checkpoint safety rule.

- Provide fake/test lifecycle providers so source contracts can be tested
  without live SaaS credentials.

**Depends on:** Backlog 999.26.
**Recommended order:** Second; it makes the registry executable.

**Anti-legacy gate:**

- Lifecycle/config/auth/cursor work must include migration hooks for existing
  filesystem and Telegram adapter construction. Do not leave the new lifecycle
  service used only by future SaaS integrations while current adapters continue
  to instantiate through bespoke paths.

**Out of scope:**

- Production-grade OAuth UI.
- Airweave auth-provider parity.
- Multi-tenant organization/billing model.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote after source capability registry)

---

### Backlog 999.28: Federated source search contract and unified SearchCandidate

**Goal:** Make federated search a first-class dotMD source capability so local
dotMD retrieval and source-native searches, such as MCP Telegram FTS or Slack
API search, can return one normalized result shape and round-trip through
`read(ref)` / `drill(ref)`.

**Context captured 2026-05-08:**

- Many future integrations already have native search APIs. For those sources,
  it may be wasteful or impossible to fully sync everything before search.

- MCP Telegram already has its own full-text search across its local database,
  making it a good first proof for federated search without needing a SaaS API.

- Airweave models this as `federated_search` capability on sources. dotMD should
  adopt the capability but keep its own result/ref/read model.

**Proposed scope:**

- Define a normalized `SearchCandidate` contract that can represent:
  - local semantic / FTS5 / graph results;
  - Telegram native FTS results;
  - future Slack/Notion/Google Drive native search results;
  - materialized and not-yet-materialized external hits.
- Candidate fields should include `ref`, source identity, title/snippet,
  source-native rank/score, retrieval kind, provenance, `can_read`, and
  `can_materialize`.

- Extend source connectors with optional `search(query, limit, filters)` and
  `hydrate_result(ref)`/materialization hooks.

- Define fusion/reranking rules that keep source-native rank useful without
  pretending every provider score is directly comparable.

- Use MCP Telegram native search as the first live federated provider proof.

**Depends on:** Backlog 999.26 and preferably 999.27.
**Recommended order:** Third; it should land before broad third-party adapter work.

**Anti-legacy gate:**

- Federated search must reuse the same public `ref` / `read(ref)` /
  `drill(ref)` surface as local search. Do not add a separate Telegram-native
  or Airweave-native result plane that callers have to handle differently.

**Out of scope:**

- Replacing dotMD's local search stack.
- Full cross-source ACL enforcement.
- New UI for search source selection.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote after registry/lifecycle, or earlier if Telegram native search becomes urgent)

---

### Backlog 999.29: Filesystem adapter on the unified source contract

**Goal:** Refactor the existing filesystem indexer so it becomes a first-class
implementation of the same source connector contract as Telegram and future
Airweave-compatible integrations.

**Context captured 2026-05-08:**

- Airweave does not appear to have a local filesystem indexer, so dotMD's
  filesystem source is not a trivial adapter port. It must preserve discovery,
  watch/trickle behavior, local file reads, retained artifacts, parser routing,
  and content-addressed reuse.

- The filesystem source is the hardest compatibility test for the unified
  contract. If the contract cannot model filesystem well, it is too narrow for
  dotMD.

**Proposed scope:**

- Implement filesystem as a registered source with typed config and cursor-ish
  local state.

- Map filesystem discovery into the same source lifecycle vocabulary used by
  app sources: resource discovery, document identity, source units, parser
  routing, active bindings, and retained artifacts.

- Preserve existing public refs and existing trickle behavior.
- Keep internal filesystem paths where they are actually needed for discovery,
  local reads, display, delete detection, and content-dedup holder semantics.

- Add regression coverage proving filesystem behavior remains stable after the
  unified source refactor.

**Depends on:** Backlog 999.26 and 999.27. Coordinate with deferred Phase 30
scope in Backlog 999.30 and with Phase 31 if this touches Telegram source state
in the same milestone.
**Recommended order:** Fourth; do this before declaring the source contract
stable for third-party connectors.

**Anti-legacy gate:**

- This item is mandatory before broad external connector work. The filesystem
  indexer must not remain a special legacy pipeline after the unified source
  architecture exists.

- Completion must include a code-path inventory showing which filesystem
  internals remain intentionally source-specific and which older adapter paths
  were removed or redirected through the unified lifecycle.

**Out of scope:**

- Removing all path-shaped internals.
- Full parser rewrite for PDF/DOCX/HTML.
- Full reindex unless an explicit later plan proves no incremental path exists.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote after source lifecycle boundary)

---

### Backlog 999.30: Telegram adapter unified with sync and federated search capabilities

**Goal:** Bring the MCP Telegram integration into the same unified source
contract as filesystem and future app connectors, including both local
sync/export and source-native federated search.

**Context captured 2026-05-08:**

- Phase 29 made Telegram a first concrete source-unit ingestion path.
- Phase 30 was deferred into this backlog item instead of being implemented as
  a Telegram-specific legacy branch. Its incremental sync/reuse requirements
  should be implemented only through the unified source contract path.

- Phase 31 may still run as a v1.5 baseline smoke, but it does not prove
  incremental Telegram sync/reuse after this deferral.

- MCP Telegram also has native full-text search over its database. That search
  should be usable as a federated source capability rather than treated as a
  separate one-off integration path.

**Proposed scope:**

- Register Telegram source capabilities: sync/export, read unit window,
  incremental cursor, and federated FTS search where available.

- Carry forward the deferred Phase 30 behavior:
  - repeated Telegram sync processes only new or changed source units;
  - unchanged history is not rechunked/reembedded;
  - sync state is per source or per dialog/source-unit stream, not one
    whole-dialog fingerprint;

  - reporting exposes discovered, new, changed, rebound, skipped, hidden,
    failed, and reused counts where practical;

  - failure isolation and regression coverage preserve filesystem behavior.
- Normalize MCP Telegram native search hits into `SearchCandidate` with stable
  message-shaped refs.

- Decide when a federated Telegram hit should remain search-only versus be
  materialized into local `SourceDocument`/`SourceUnit` state.

- Preserve Phase 29 identity decisions:
  `telegram:dialog:<dialog_id>:message:<message_id>` remains the public
  message ref shape.

- Ensure `read(ref)` and `drill(ref)` do not require callers to know whether a
  result came from local dotMD search or native Telegram search.

**Depends on:** Phase 31 for current v1.5 closure, plus Backlog 999.28 for the
generic federated contract.
**Recommended order:** Fifth; after filesystem validates the unified source
contract, Telegram proves hybrid sync + federated behavior.

**Anti-legacy gate:**

- Telegram must not remain as a one-off application provider after the unified
  source contract exists. Both the existing export/sync path and the native FTS
  search path must present the same source descriptor, stable refs, read/drill
  behavior, and lifecycle/cursor model as other sources.

- Completion must prove callers cannot tell, from API shape alone, whether a
  Telegram result came from local dotMD indexing or MCP Telegram native search.

**Out of scope:**

- Bidirectional Telegram actions.
- Attachment/media ingestion.
- Long-term TTL/GC scheduler, complete edit/delete lifecycle policy, or full
  media ingestion.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote after Phase 31 or as part of the next source-search milestone)

---

### Backlog 999.31: Airweave connector compatibility spike

**Goal:** Prove that dotMD can use third-party Airweave connector code as a
source reader/search provider without adopting Airweave's indexing, chunking,
Vespa, Temporal, billing, or organization model.

**Context captured 2026-05-08:**

- The business goal is to connect to integrations such as Notion, Google Drive,
  Slack, GitHub, and similar products using existing third-party connector work
  where practical.

- Airweave's connector ecosystem is valuable, but its `BaseEntity` /
  textual-representation / chunk-as-document / destination pipeline should not
  become dotMD's internal ontology.

- dotMD should adapt Airweave connector outputs into `SourceDocument`,
  `SourceUnit`, `SourceAsset`, and `SearchCandidate` contracts.

**Proposed scope:**

- Choose one pilot connector with low ambiguity. Recommended order:
  1. Notion or GitHub for sync/export proof;
  2. Google Drive for file/asset proof;
  3. Slack for federated-search proof.
- Build a thin adapter runner:
  - Airweave source `generate_entities(...)` -> dotMD source changes;
  - Airweave source `search(query, limit)` -> dotMD `SearchCandidate`;
  - Airweave entity fields -> dotMD document/unit/source metadata.
- Provide minimal compatibility shims for auth provider, typed config, logger,
  HTTP client, cursor, and optional file service.

- Produce an integration report: which Airweave pieces are reusable directly,
  which require shims, and which should be avoided.

**Depends on:** Backlog 999.26, 999.27, and ideally 999.28.
**Recommended order:** Sixth; run after dotMD's own filesystem/Telegram sources
fit the unified contract.

**Anti-legacy gate:**

- Do not start the compatibility spike as a shortcut around unfinished
  filesystem/Telegram unification. The spike should validate that the unified
  contract is good enough for third-party connectors, not introduce a separate
  Airweave-only integration lane.

**Out of scope:**

- Importing the whole Airweave backend.
- Replacing dotMD local retrieval, chunking, embeddings, FTS5, graph, or rerank.
- Supporting every Airweave connector in the first pass.

**Plans:** 0 plans

Plans:

- [ ] TBD (promote after unified source contract is validated on local sources)

---

### Backlog 999.32: Remove LanceDB and LadybugDB completely (DONE 2026-06-12)

**Goal:** Delete unused legacy storage backends and all references to them.

**Context captured 2026-06-12:**

- Production uses SQLite/FTS5/sqlite-vec plus FalkorDB.
- LanceDB existed only as a legacy optional code path and dependency extra.
- LadybugDB existed only as a local-dev graph fallback.
- We do not want to preserve either compatibility layer.

**Proposed scope:**

- Remove LanceDB and LadybugDB code, config, dependency extras, tests, docs,
  examples, comments, and lockfile references where no longer needed.

- Make supported storage choices explicit in code and documentation.
- Keep migration behavior focused on the current production storage model.

**Plans:** 0 plans

Plans:

- [x] Removed legacy backends directly from backlog cleanup.

---

### Future ideas:

- Semantic chunking (split by topic similarity, not just structure)
- Doc-level chunks (whole-document embeddings for broad queries)
- Query-time NER via GLiNER (complement entity catalog string matching)
- Telegram/chat history as additional data source

---

### Phase 32: Source capability registry

**Goal:** Introduce a dotMD-native source registry/capability model and seed it
with filesystem and Telegram so current and future sources are described
through one vocabulary.
**Requirements:** SRC-01, SRC-02, SRC-03, SRC-04
**Depends on:** Phase 31
**Backlog source:** 999.26
**Plans:** 4/4 plans complete

Reference:

- Upstream: `https://github.com/airweave-ai/airweave`
- Local checkout: `/home/j2h4u/repos/airweave-ai/airweave`

Success criteria:

1. Source descriptors include source kind, display metadata, config schema,
   auth schema, cursor schema, and capability flags.

2. Filesystem and Telegram are present in the registry.
3. Capability flags distinguish sync, federated search, read-unit windows,
   materialization, browse trees, ACLs, and incremental cursors.

4. Docs map Airweave source metadata to dotMD descriptors without a runtime
   Airweave dependency.

Plans:
**Wave 1**

- [x] 32-01-source-descriptor-contract-PLAN.md — Source descriptor contract

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 32-02-filesystem-telegram-registry-seeds-PLAN.md — Filesystem and Telegram registry seeds
- [x] 32-03-provider-description-compatibility-PLAN.md — Provider description compatibility

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 32-04-airweave-mapping-docs-PLAN.md — Airweave mapping documentation

---

### Phase 33: Source lifecycle/config/auth/cursor boundary

**Goal:** Build the lifecycle service that constructs source runtimes from
registry entries, typed config, credentials, cursor state, and runtime helpers.
**Requirements:** LIFE-01, LIFE-02, LIFE-03, LIFE-04
**Depends on:** Phase 32
**Backlog source:** 999.27
**Plans:** 3/3 plans complete

Success criteria:

1. Source runtimes are built through one lifecycle/factory boundary.
2. Credentials are accessed through a provider interface, not direct secret
   reads inside adapters.

3. Cursor commits happen only after local persistence succeeds.
4. Filesystem and Telegram construction paths use the lifecycle boundary.

Plans:
**Wave 1**

- [x] 33-01-lifecycle-runtime-bundle-PLAN.md — Lifecycle runtime bundle contract

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 33-02-filesystem-lifecycle-migration-PLAN.md — Filesystem lifecycle migration

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 33-03-telegram-lifecycle-and-cursor-boundary-PLAN.md — Telegram lifecycle and cursor boundary

---

### Phase 34: Federated SearchCandidate contract

**Goal:** Define one search candidate contract for local dotMD retrieval and
source-native federated search, then prove it with MCP Telegram native FTS.
**Requirements:** SEARCH-01, SEARCH-02, SEARCH-03, SEARCH-04
**Depends on:** Phase 33
**Backlog source:** 999.28
**Plans:** 0/0 plans complete

Success criteria:

1. Local semantic/FTS5/graph hits and source-native hits share one
   `SearchCandidate` shape.

2. Candidates include stable ref, source identity, title/snippet, retrieval
   kind, provenance, source score/rank, `can_read`, and `can_materialize`.

3. Fusion/ranking handles provider-native scores without treating them as
   directly comparable.

4. MCP Telegram native FTS can return candidates that round-trip through
   `read(ref)` and `drill(ref)`.

---

### Phase 35: Filesystem unified source adapter

**Goal:** Refactor filesystem into a first-class unified source implementation
without breaking trickle, search, read, parser routing, delete detection, or
content-addressed reuse.
**Requirements:** FS-01, FS-02, FS-03
**Depends on:** Phase 33
**Backlog source:** 999.29
**Plans:** 2/2 plans complete

Success criteria:

1. Filesystem indexing/search/read flows through the source registry and
   lifecycle where appropriate.

2. Path-shaped internals remain only where needed for discovery, holder
   semantics, local reads, display, and delete detection.

3. Regression coverage proves current filesystem behavior is preserved.

---

### Phase 36: Telegram unified sync and federated search

**Goal:** Bring Telegram fully onto the unified source contract, including the
deferred incremental sync/reuse behavior and native federated FTS search.
**Requirements:** TG-01, TG-02, TG-03, TG-04
**Depends on:** Phase 34 and Phase 35
**Backlog source:** 999.30 and deferred Phase 30
**Plans:** 2/2 plans complete

Success criteria:

1. Telegram declares sync/export, read-unit-window, incremental-cursor, and
   federated-search capabilities where available.

2. Repeated sync skips/reuses unchanged source units without rechunking or
   reembedding unchanged history.

3. Sync reporting includes discovered, new, changed, rebound, skipped, hidden,
   failed, and reused counts where practical.

4. Telegram local-index and native-search results expose the same public
   `search -> ref -> drill/read` shape.

---

### Phase 37: Airweave connector compatibility spike

**Goal:** Prove dotMD can adapt one Airweave connector-style source into
dotMD's source contracts without adopting Airweave's indexing/runtime stack.
**Requirements:** AIR-01, AIR-02, AIR-03
**Depends on:** Phase 36
**Backlog source:** 999.31
**Plans:** 4/4 plans complete

Success criteria:

1. One pilot connector or connector-like source maps into `SourceDocument`,
   `SourceUnit`, optional `SourceAsset`, and `SearchCandidate`.

2. The spike reports reusable Airweave pieces, required shims, and avoided
   assumptions.

3. The spike uses the same source registry/lifecycle/search contracts as
   filesystem and Telegram.

---

### Phase 38: Embedded SurrealDB storage spike

**Goal:** Decide whether dotMD should replace separate SQLite/sqlite-vec/FTS5
and FalkorDB storage with one embedded SurrealDB-backed storage layer.
**Requirements:** STOR-01, STOR-02, STOR-03, STOR-04
**Depends on:** Phase 37
**Backlog source:** 999.33
**Plans:** 5/5 plans complete
Plans:
**Wave 1**

- [x] 38-01-PLAN.md - Current data inventory, copied snapshot evidence, and migration map

**Wave 2** *(blocked on Wave 1 completion)*

- [x] 38-05-PLAN.md - Early embedded atomicity, writer-safety, and package gate before schema/import

**Wave 3** *(blocked on Wave 2 completion)*

- [x] 38-02-PLAN.md - Surreal storage schema/adapters and transform-only import proof

**Wave 4** *(blocked on Wave 3 completion)*

- [x] 38-03-PLAN.md - Retrieval parity proof for FTS, vector, graph-direct, and hybrid/RRF

**Wave 5** *(blocked on Wave 4 completion)*

- [x] 38-04-PLAN.md - Operations proof and final migrate/defer/reject recommendation

Success criteria:

1. A minimal SurrealDB prototype models documents, source units, chunks,
   embeddings, entities, relations, feedback, and cursor/checkpoint state.

2. The prototype proves or rejects dotMD's required retrieval paths:
   full-text, vector, graph-direct entity retrieval, and hybrid/RRF fusion.

3. The spike measures migration feasibility from current production data:
   SQLite metadata/FTS/source state, sqlite-vec embeddings, and FalkorDB graph
   data should be migrated where possible instead of recomputed on CPU.

4. The result is an explicit recommendation: migrate, defer, or reject, with
   operational notes for backup/restore, locking/concurrency, and rollback.

---

*Roadmap created: 2026-03-26*
*Last updated: 2026-06-14*
