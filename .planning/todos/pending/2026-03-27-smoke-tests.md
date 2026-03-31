---
created: "2026-03-27T10:30:00Z"
title: Smoke tests for search pipeline
area: testing
files:
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/search/semantic.py
  - backend/src/dotmd/search/bm25.py
---

## Problem

No automated tests for the search pipeline. After code changes (reranker fix, FalkorDB migration, batch size tuning) validation is manual — run CLI, check output, curl API. Easy to miss regressions.

## Solution

Smoke test suite that verifies:
- All 3 engines return results (semantic, bm25, graph)
- Hybrid mode fuses results from multiple engines
- API endpoint returns HTTP 200 with valid JSON
- `dotmd status` reports correct backend and counts
- `matched_engines` field populated correctly
- BM25-only matches survive reranker (Phase 5 regression guard)

Could be pytest integration tests (require running TEI + FalkorDB) or a simple `dotmd test` CLI command that runs inside the Docker container.
