# Phase 43 Shadow Run Preflight Failure

Generated: 2026-06-16T08:58:37Z

## Status

Candidate-target preparation stopped before baseline or candidate capture.

## Current Blocker

The Phase 41 migration runner is not safe to run on the production-derived
Phase 43 snapshot in its current form. Even `--mode plan` materializes the
production snapshot in memory, including all stored embeddings as Python float
lists. The run was stopped after the Python process reached roughly 9 GB RSS.

This supersedes the earlier stop note that blamed a missing
`DOTMD_SHADOW_TARGET_URL`. The target URL can be supplied explicitly, but the
target cannot be prepared safely until the migration plan/apply path avoids
full embedding materialization.

## Inputs Prepared

- Rehearsal SQLite snapshot:
  `.planning/phases/43-shadow-run-and-quality-gate/artifacts/rehearsal-index/index.db`
  (`2.4G`)
- Graph export:
  `.planning/phases/43-shadow-run-and-quality-gate/artifacts/graph-export.json`
  (`101M`, local-only artifact)
- Feedback export:
  `.planning/phases/43-shadow-run-and-quality-gate/artifacts/feedback-export.json`
  (`16K`, local-only artifact)
- `source-capture-expected.json` records:
  - `chunk_strategy=contextual_512_50`
  - `embedding_model=intfloat/multilingual-e5-large`
  - `expected_chunk_count=149800`
  - `expected_embedding_count=149800`
  - `import_id=phase43-rehearsal-sqlite-backup-2026-06-16T07-31Z`
- `candidate-config.json` and `metrics-replay-queries.jsonl` exist.

## Capture State

No baseline results, candidate results, shadow diffs, shadow summary, scale
metrics, memory metrics, production cutover, runtime default switch, fallback
backend, rechunking, reembedding, or entity re-extraction were performed.

## Required Next Fix

Fix the Phase 41 migration runner so manifest/plan and target preparation do
not decode and retain every production embedding in memory. The next attempt
must use streaming, batching, or count-only manifest construction with a memory
guard before any Phase 43 target preparation is retried.
