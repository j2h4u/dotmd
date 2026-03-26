---
gsd_state_version: 1.0
milestone: v1.2
milestone_name: FalkorDB Migration & Search Fix
status: defining requirements
last_updated: "2026-03-26T18:00:00.000Z"
progress:
  total_phases: 0
  completed_phases: 0
  total_plans: 0
  completed_plans: 0
---

# GSD State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-26)

**Core value:** Fast, incremental search indexing — daily sync doesn't bog down the server.
**Current focus:** Defining requirements for v1.2

## Current Milestone

**v1.2 — FalkorDB Migration & Search Fix**

Phase: Not started (defining requirements)
Plan: —
Status: Defining requirements
Last activity: 2026-03-26 — Milestone v1.2 started

## Accumulated Context

- FileTracker uses explicit `hashlib.md5()` instead of `FileInfo.checksum` computed_field to avoid unnecessary file reads
- `file_fingerprints` table shares same SQLite database as metadata.db via shared connection
- DETACH DELETE order: Sections first, then File node - ensures edge cascade is clean
- Vector delete uses rowid lookup from vec_meta, then deletes from both vec0 virtual table and vec_meta
- `overwrite_vectors` internal param routes through `_ingest_and_finalize` to `add_chunks` overwrite kwarg
- `_ExtractionBundle` dataclass bundles extraction results for cleaner method signatures
- `vector_store` property type corrected from `LanceDBVectorStore` to `VectorStoreProtocol`
- Idempotent ALTER TABLE with try/except for schema migration instead of version tracking
- Fresh diff counts on no-changes path to avoid stale stored values
- Live file diff in DotMDService.status() using stored data_dir for change detection

## Session Log

- **2026-03-26**: Milestone v1.2 started — FalkorDB migration + BM25 hybrid fix.

---
*Last updated: 2026-03-26*
