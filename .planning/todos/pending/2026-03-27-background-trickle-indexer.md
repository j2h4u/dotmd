---
created: "2026-03-27T09:29:49.313Z"
title: Background trickle indexer
area: api
files:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/search/semantic.py
  - backend/src/dotmd/ingestion/file_tracker.py
---

## Problem

Full re-index of the entire dataset (13,515 files, 188k chunks) takes 40-70 hours on current hardware (Xeon E3 V2, TEI on CPU). This makes `dotmd index --force /mnt` impractical as a one-shot operation when the data directory includes both voicenotes (229 files) and home directory markdown (13k+ files).

Currently indexing is either "everything now" (--force) or "only changed files" (incremental). There's no middle ground for gradually building up the index from scratch in the background.

## Solution

Add a background indexing mode that continuously processes pending files at low priority:

- **Trickle mode**: process one file at a time with configurable pauses between files
- **Priority**: run with low cpu_shares so search/serve stays responsive
- **FileTracker integration**: already has content hashes — use to discover unindexed files
- **Auto-tune TEI batch size**: measure throughput (texts/sec) across different batch sizes, pick the one with best integral performance (not just per-batch speed)
- **Graceful coexistence**: background indexer and API server share the same stores without conflicts (FalkorDB is network-based, sqlite-vec supports concurrent reads)
- **Progress visibility**: `dotmd status` should show background indexing progress ("indexing 1,234/13,515 files")

Could be implemented as a separate CLI command (`dotmd index --background`) or as an always-on feature of `dotmd serve`.
