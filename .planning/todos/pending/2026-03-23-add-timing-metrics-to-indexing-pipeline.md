---
created: 2026-03-23T22:48:31.307Z
title: Add timing metrics to indexing pipeline
area: api
files:
  - backend/src/dotmd/ingestion/pipeline.py
---

## Problem

No visibility into how long each indexing stage takes. Can't tell if embedding, NER, or graph population is the bottleneck without manually timing. Makes it hard to track performance improvements or spot regressions after code changes.

## Solution

Add `time.perf_counter()` instrumentation around each pipeline stage and log durations:
- File discovery
- Embedding (TEI calls)
- NER (GLiNER)
- Graph population (LadybugDB inserts)
- BM25 rebuild
- Total wall time

Log at INFO level so it appears in `docker compose logs`. Consider also returning timing in IndexStats or a separate TimingReport model for API consumers.
