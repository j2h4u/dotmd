---
phase: "29"
plan: "03"
subsystem: "telegram ingestion"
tags: ["telegram", "application-source", "tdd", "sqlite", "fts5", "sqlite-vec", "provenance"]
dependency_graph:
  requires: ["29-01 structured mcp-telegram source export", "29-02 TelegramApplicationSourceProvider"]
  provides: ["single-batch Telegram source ingestion", "Telegram provenance hydration helpers", "transaction-covered Telegram chunk/FTS/vector/checkpoint writes"]
  affects: ["29-04-telegram-read-drill-and-smoke", "Phase 31 search/read/drill smoke"]
tech-stack:
  added: []
  patterns: ["message-level source-unit fingerprints", "file_paths=[] application chunks", "source-meta FTS wrapper", "direct sqlite-vec transaction writes"]
key-files:
  created:
    - "backend/tests/ingestion/test_telegram_ingestion.py"
  modified:
    - "backend/src/dotmd/ingestion/pipeline.py"
    - "backend/src/dotmd/search/fts5.py"
    - "backend/src/dotmd/storage/metadata.py"
key-decisions:
  - "Phase 29 Telegram ingestion is single-batch per call; callers must explicitly loop for bootstrap pagination."
  - "Telegram chunks stay pathless with file_paths=[] and are hydrated through chunk_source_provenance by source_unit_ref."
  - "Telegram metadata uses a real source-meta embedding text and FTS title/tags wrapper instead of filesystem FileInfo/frontmatter fallbacks."
requirements-completed: ["R4", "R5", "R8"]
metrics:
  duration: "~10 min"
  completed_at: "2026-05-08T08:03:40Z"
  tasks: 2
  files_changed: 4
---

# Phase 29 Plan 03: dotMD Telegram Ingestion Summary

Single-batch Telegram message ingestion now persists source documents, active bindings, source-unit fingerprints, pathless chunks, provenance, FTS5 rows, sqlite-vec rows, and checkpoint metadata.

## Performance

- **Duration:** ~10 min
- **Completed:** 2026-05-08T08:03:40Z
- **Tasks:** 2
- **Files modified:** 4

## Completed Tasks

| Task | Name | Commit | Files |
|---|---|---|---|
| 1 | Add Telegram ingestion persistence tests | `ed6bc2a` | `backend/tests/ingestion/test_telegram_ingestion.py` |
| 2 | Implement incremental Telegram ingestion path | `20fcd42` | `backend/src/dotmd/ingestion/pipeline.py`, `backend/src/dotmd/search/fts5.py`, `backend/src/dotmd/storage/metadata.py`, `backend/tests/ingestion/test_telegram_ingestion.py` |

## What Changed

- Added `ApplicationSourceIngestResult` and `IndexingPipeline.ingest_application_source(provider, limit=...)`.
- The ingestion path reads stored Telegram checkpoint metadata, forwards `updated_after` and `updated_after_cursor`, processes exactly one provider batch, and commits `"single_batch": true`.
- Source documents, resource bindings, source-unit fingerprints, chunk rows, provenance rows, FTS rows, vector rows, and checkpoint state are written under one SQLite transaction for the Telegram path.
- Low-signal units such as `"ok"` persist as fingerprints/bindings but do not become standalone chunks.
- Changed message units delete and replace old Telegram chunks for that source unit before writing replacement chunks.
- Added `SQLiteMetadataStore.get_chunks_by_source_unit_ref(...)` and `delete_chunks_for_source_unit(...)` for provenance-based Telegram hydration and replacement.
- Added `FTS5SearchEngine.add_chunks_with_source_meta(...)` so Telegram chunks receive explicit title/tags metadata without empty-key file metadata conventions.

## Verification

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_source_filesystem.py tests/storage/test_metadata_m2m.py -q
# 54 passed, 22 warnings in 3.43s
```

```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend && uv run ruff check src/dotmd/ingestion/pipeline.py src/dotmd/search/fts5.py src/dotmd/storage/metadata.py tests/ingestion/test_telegram_ingestion.py
# All checks passed.
```

```bash
rg -n "ingest_application_source|ApplicationSourceIngestResult|standalone_search|telegram-message|get_chunks_by_source_unit_ref|updated_after|updated_after_cursor|add_chunks_with_source_meta|single_batch" backend/src/dotmd/ingestion/pipeline.py backend/src/dotmd/ingestion/telegram_provider.py backend/src/dotmd/storage/metadata.py backend/tests/ingestion/test_telegram_ingestion.py
# Found expected implementation and test references.
```

```bash
! rg -n "e_meta\\s*=\\s*e_text|file_meta=\\{\\\"\\\"" backend/src/dotmd/ingestion/pipeline.py backend/src/dotmd/storage/metadata.py
# No forbidden dual-embedding or empty-key metadata convention found.
```

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 2 - Missing Critical] Added transaction-owned FTS5 and sqlite-vec writes for Telegram ingestion**
- **Found during:** Task 2
- **Issue:** Existing FTS5 and vector helpers commit internally, which would break the plan requirement that Telegram metadata, FTS5, vector, provenance, and checkpoint writes roll back together.
- **Fix:** Added source-meta FTS insertion with caller-owned transaction and direct sqlite-vec row insertion for the Telegram path after ensuring vector tables before `BEGIN`.
- **Files modified:** `backend/src/dotmd/ingestion/pipeline.py`, `backend/src/dotmd/search/fts5.py`
- **Verification:** Rollback test injects vector failure and asserts no source document, fingerprint, chunk, provenance, FTS, vector, or successful checkpoint cursor remains.
- **Commit:** `20fcd42`

**2. [Rule 1 - Bug] Preserved existing checkpoint cursor on empty provider batches**
- **Found during:** Task 2
- **Issue:** An empty provider batch with no explicit checkpoint cursor could otherwise overwrite a stored checkpoint with `NULL`.
- **Fix:** Empty-batch checkpoint commits preserve the existing cursor and watermark metadata when the provider returns no replacements.
- **Files modified:** `backend/src/dotmd/ingestion/pipeline.py`
- **Verification:** Focused pytest suite passed after the fix.
- **Commit:** `20fcd42`

## Known Stubs

None. The `file_paths=[]` and empty `source_unit_refs=[]` occurrences are intentional application-source/pathless-chunk and bounded-binding semantics covered by tests.

## Auth Gates

None.

## Threat Flags

None. The new Telegram ingestion and provenance helpers are the planned Phase 29 threat mitigations and are covered by transaction, low-signal, checkpoint, and pathless-chunk tests.

## Self-Check: PASSED

- Summary file exists at `.planning/phases/29-telegram-adapter-mvp-ingestion/29-03-dotmd-telegram-ingestion-SUMMARY.md`.
- Task commits exist: `ed6bc2a`, `20fcd42`.
- Focused pytest, targeted ruff, required positive `rg`, and forbidden-pattern negative `rg` checks passed.
- `.planning/STATE.md` and `.planning/ROADMAP.md` were not updated by this executor, per orchestrator instructions.
