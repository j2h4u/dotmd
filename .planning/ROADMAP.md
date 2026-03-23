# Roadmap: dotMD v1.1 — Incremental Indexing

**Created:** 2026-03-23
**Milestone:** v1.1 — Incremental Indexing
**Core Value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Granularity:** Coarse (3 phases)

## Phase 1: Storage Layer — File Tracking + Delete Methods

**Goal:** All stores can track file fingerprints and delete data by file path.

**Requirements:** FT-01, FT-02, FT-03, SC-01, SC-02, SC-03

**Plans:** 2 plans

Plans:
- [ ] 01-01-PLAN.md — FileTracker class, protocol extensions, metadata delete methods + pytest bootstrap
- [ ] 01-02-PLAN.md — Vector store delete, graph store delete with DETACH DELETE spike

**Scope:**
- `file_fingerprints` table in metadata.db (path, mtime, size, checksum)
- `FileTracker` class: save/load fingerprints, classify files (new/modified/deleted/unchanged)
- `delete_chunks_by_file()` in SQLiteMetadataStore
- `delete_vectors_by_file()` in SQLiteVecVectorStore (via vec_meta JOIN)
- `delete_file_subgraph()` in LadybugDBGraphStore (DETACH DELETE Section nodes, preserve Entity/Tag)
- Smoke test: LadybugDB `DETACH DELETE` with file_path scoped query

**Risk:** LadybugDB DETACH DELETE cascade behavior across explicit REL tables untested. Spike first.

**Done when:** Each store can independently delete all data associated with a single file, and file fingerprints persist across runs.

---

## Phase 2: Incremental Pipeline — Diff-Based Indexing

**Goal:** `index()` only processes changed files. Full re-index available via `--force`.

**Requirements:** IP-01, IP-02, IP-03, IP-04, IP-05

**Scope:**
- Refactor `IndexingPipeline.index()` into diff-based flow:
  1. Discover files → compare fingerprints → classify changes
  2. Delete stale data for modified/deleted files
  3. Ingest only new/modified files (read → chunk → embed → NER → graph)
  4. BM25 rebuild from `metadata_store.get_all_chunks()` (always full, ~0.1s)
  5. Update fingerprints
- `--force` flag bypasses fingerprint comparison
- Existing `index()` preserved as `full_index()` for backward compat

**Risk:** Chunk ID instability — IDs are positional (`md5(path:index)`). Modified file must purge ALL old chunks before re-ingesting. Not an upsert.

**Done when:** Adding 1 new file to 226 existing takes seconds (embed + NER for 1 file), not 50 minutes.

---

## Phase 3: CLI & API Polish

**Goal:** Clean user-facing interface with progress reporting.

**Requirements:** CA-01, CA-02, CA-03

**Scope:**
- Default `dotmd index` uses incremental
- `dotmd index --force` does full re-index
- Progress output: "3 new, 1 modified, 0 deleted, 222 unchanged"
- API `POST /index` returns diff summary in response
- `dotmd status` shows last index time, file count, change detection

**Risk:** Low — thin wrapper over Phase 2 pipeline.

**Done when:** Daily cron `dotmd index /mnt/voicenotes` completes in <1 minute for typical changes (0-3 new files).

---

## Phase Summary

| Phase | Name | Requirements | Status |
|-------|------|-------------|--------|
| 1 | Storage Layer | FT-01..03, SC-01..03 | ○ Pending |
| 2 | Incremental Pipeline | IP-01..05 | ○ Pending |
| 3 | CLI & API Polish | CA-01..03 | ○ Pending |

**Total requirements:** 14
**Estimated phases:** 3

---
*Roadmap created: 2026-03-23*
*Last updated: 2026-03-23 after Phase 1 planning*
