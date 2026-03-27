# Milestones

## v1.2 FalkorDB Migration & Search Fix (Shipped: 2026-03-27)

**Phases completed:** 3 phases, 4 plans, 6 tasks

**Key accomplishments:**

- FalkorDB graph store adapter with 12 protocol methods, config-driven backend selection, and updated GraphStoreProtocol
- Config-driven graph store factory in pipeline with CLI status reporting of active backend
- Removed cross-encoder score threshold and added merge-back logic so all BM25 fusion candidates survive through reranking

---

## v1.1 Incremental Indexing (Shipped: 2026-03-26)

**Phases completed:** 3 phases, 5 plans, 9 tasks

**Key accomplishments:**

- FileTracker with two-stage mtime+size/MD5 change detection, per-file chunk deletion methods, and extended storage protocols for incremental indexing
- Per-file vector and graph delete methods with LadybugDB DETACH DELETE cascade validation across all 7 REL tables
- Diff-based incremental indexing via FileTracker integration -- modified/deleted files purged from all 3 stores, new files appended, unchanged files skipped entirely
- --force CLI flag threaded through DotMDService to IndexingPipeline, enabling user-triggered full re-index bypass of incremental change detection
- Diff counts threaded from FileDiff through IndexStats to CLI/API output with live change detection in status command

---
