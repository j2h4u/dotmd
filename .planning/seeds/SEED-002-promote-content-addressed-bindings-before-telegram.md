---
id: SEED-002
status: dormant
planted: 2026-05-06
planted_during: after v1.4 milestone close
trigger_when: next milestone scope includes Telegram, non-filesystem sources, source adapters, resource bindings, or avoiding wasted reindex/TEI/NER work
scope: Medium
---

# SEED-002: Promote content-addressed bindings before Telegram

## Why This Matters

Backlog `999.25` captures the infrastructure needed to keep dotMD from
recomputing expensive derived artifacts when resources move, disappear, return,
or append new content. This should surface before Telegram because Telegram will
introduce source records that are not path-shaped and will naturally produce
append, edit, repeated export, and duplicate-message scenarios.

If Telegram is implemented first, the adapter is likely to inherit the current
filesystem-holder semantics and will have to be reworked after active bindings,
retained content, and source-unit reuse are introduced.

## When to Surface

**Trigger:** next milestone scope includes Telegram, non-filesystem sources,
source adapters, resource bindings, retained content, GC, or explicit avoidance
of wasted full reindex / TEI / NER / graph work.

This seed should be presented during `$gsd-new-milestone` when the milestone
scope matches any of these conditions:

- The user says the next milestone is Telegram, chat history, or source adapter
  integration.
- The milestone includes non-filesystem documents or source-unit modeling.
- The milestone discusses rename, atomic write, delete-then-readd, import
  refresh, or append-only source updates.
- The milestone tries to reduce full reindex, re-embedding, NER/extraction, FTS,
  or graph recomputation.

## Scope Estimate

**Medium** — likely one infrastructure phase before Telegram:

- Promote backlog `999.25` into the active milestone.
- Discuss and plan active/inactive resource bindings, retained unreferenced
  content, active-binding search/read filtering, and GC.
- Keep Telegram adapter implementation out of this phase.

## Breadcrumbs

- `.planning/ROADMAP.md` — `Backlog 999.25: Content-addressed resource bindings and retained derived artifacts`
- `.planning/ROADMAP.md` — `Backlog 999.22: Document Source Abstraction — index non-filesystem sources`
- `.planning/ROADMAP.md` — `Backlog 999.24: Source-ref-first read/search contract — remove filesystem path compatibility layer`
- `backend/src/dotmd/storage/metadata.py` — `chunks_*`, `chunk_file_paths_<strategy>`, `source_documents`, `chunk_source_provenance_<strategy>`
- `backend/src/dotmd/ingestion/pipeline.py` — `_holder_aware_chunk_cleanup`, `_purge_file`, `index_file`
- `backend/src/dotmd/ingestion/source.py` — `SourceDocument` filesystem adapter and path-derived `document_ref`
- `backend/src/dotmd/ingestion/file_tracker.py` — split body/chunk and metadata fingerprint tracking

## Notes

Recommended next milestone ordering:

1. Content-addressed resource bindings and retained derived artifacts.
2. Telegram read-only source adapter.
3. Telegram hardening after real usage.

Do not treat this as a request to execute backlog `999.25` automatically.
The seed should only surface it during `$gsd-new-milestone` so the user can
promote it deliberately into the active roadmap.
