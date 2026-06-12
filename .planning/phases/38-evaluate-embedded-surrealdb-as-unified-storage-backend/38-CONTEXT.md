# Phase 38 Context — Embedded SurrealDB storage spike

## Goal

Decide whether embedded SurrealDB can replace the current SQLite/sqlite-vec/FTS5
plus FalkorDB storage split with one embedded database.

## Key Constraint

Prefer migration over recomputation wherever technically safe. The spike must
measure how much existing production state can be moved into SurrealDB without
CPU-heavy rechunking, reembedding, or NER/entity re-extraction.

Current data to evaluate:
- SQLite `index.db`: chunks, metadata, FTS/source state, fingerprints, source
  documents, bindings, cursors/checkpoints, sqlite-vec vector rows.
- FalkorDB graph: File, Section, Entity, Tag nodes and relations.
- SQLite `feedback.db`: agent feedback.

## Decision Output

The phase should end with one explicit recommendation: migrate, defer, or reject
SurrealDB. If migration is recommended, include a migration path and fallback
plan.
