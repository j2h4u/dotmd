---
phase: 11-embedding-model-swap
plan: 02
subsystem: search
tags: [tei, pplx-embed, embeddings, config, docker, semantic-search]

# Dependency graph
requires:
  - phase: 11-embedding-model-swap
    provides: "Research findings: TEI v1.9 requirement, two-model architecture, no-prefix for pplx-embed"
provides:
  - "TEI upgraded to cpu-1.9 with Qwen3/pplx-embed support"
  - "Prefix-aware SemanticSearchEngine (conditional E5 prefixes)"
  - "Config fields for two-model architecture (context_embedding_model, needs_embedding_prefix)"
  - "transformers and torch<2.5 dependencies declared"
affects: [11-03-PLAN, ingestion-pipeline, search-pipeline]

# Tech tracking
tech-stack:
  added: [transformers>=4.45, torch<2.5]
  patterns: [conditional-prefix-encoding, model-family-auto-detection, two-model-config]

key-files:
  created: []
  modified:
    - backend/src/dotmd/core/config.py
    - backend/src/dotmd/search/semantic.py
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/api/service.py
    - backend/pyproject.toml
    - docker-compose.yml

key-decisions:
  - "Auto-detect prefix need from model name (e5/bge -> True, others -> False)"
  - "use_prefix defaults to True for backward compatibility with E5-large"
  - "TEI --dtype float32 ensures consistent float32 vectors for sqlite-vec cosine similarity"

patterns-established:
  - "Model-family detection: needs_embedding_prefix property auto-detects from model name"
  - "Configurable prefix: use_prefix parameter propagated from Settings to SemanticSearchEngine"

requirements-completed: [EMBED-02, EMBED-03]

# Metrics
duration: 2min
completed: 2026-03-30
---

# Phase 11 Plan 02: Infrastructure + Prefix-Aware Encoding Summary

**TEI upgraded to cpu-1.9 for pplx-embed support, SemanticSearchEngine prefix logic made conditional, config and deps added for two-model architecture**

## Performance

- **Duration:** 2 min
- **Started:** 2026-03-30T19:47:08Z
- **Completed:** 2026-03-30T19:49:10Z
- **Tasks:** 2
- **Files modified:** 6

## Accomplishments
- Config supports two-model architecture: `context_embedding_model` for in-process indexing model, `needs_embedding_prefix` auto-detection property
- SemanticSearchEngine conditionally applies "query: " / "passage: " prefixes based on model family (E5/BGE get prefixes, pplx-embed does not)
- TEI Docker image upgraded from cpu-1.6 to cpu-1.9 (Qwen3 architecture support for pplx-embed)
- `--dtype float32` added to TEI command for consistent vector output
- `transformers>=4.45` and `torch<2.5` declared as dependencies for in-process context model loading

## Task Commits

Each task was committed atomically:

1. **Task 1: Config + dependencies for two-model architecture** - `8657ae9` (feat)
2. **Task 2: Prefix-aware SemanticSearchEngine + TEI upgrade** - `ba39856` (feat)

## Files Created/Modified
- `backend/src/dotmd/core/config.py` - Added context_embedding_model, embedding_uses_prefix fields, needs_embedding_prefix property
- `backend/src/dotmd/search/semantic.py` - Added use_prefix parameter, conditional prefix logic in encode_batch and search
- `backend/src/dotmd/ingestion/pipeline.py` - Passes use_prefix=settings.needs_embedding_prefix to SemanticSearchEngine
- `backend/src/dotmd/api/service.py` - Passes use_prefix=self._settings.needs_embedding_prefix to SemanticSearchEngine
- `backend/pyproject.toml` - Added transformers>=4.45 and torch<2.5 dependencies
- `docker-compose.yml` - TEI image cpu-1.6 -> cpu-1.9, added --dtype float32

## Decisions Made
- Auto-detect prefix need from model name: "e5" or "bge" in name -> True, everything else -> False. Explicit override via `embedding_uses_prefix` setting.
- `use_prefix` defaults to True so existing E5-large deployments work without config changes.
- `--dtype float32` added to TEI command because pplx-embed natively produces INT8 but sqlite-vec cosine similarity needs float32. This is a no-op for E5 (already float32).

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- Config and prefix infrastructure ready for Plan 03 (in-process context model integration)
- `context_embedding_model` field ready to receive the pplx-embed-context-v1-0.6B model name
- `needs_embedding_prefix` will return False for pplx-embed models automatically
- TEI cpu-1.9 ready to serve pplx-embed-v1-0.6B for query encoding

---
*Phase: 11-embedding-model-swap*
*Completed: 2026-03-30*
