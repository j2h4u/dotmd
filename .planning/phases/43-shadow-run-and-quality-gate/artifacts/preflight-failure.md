# Phase 43 Shadow Run Preflight Failure

Generated: 2026-06-16T08:58:37Z
Updated: 2026-06-16T10:57:54Z

## Status

Candidate-target preparation stopped before baseline or candidate capture.

## Current Blocker

The Phase 41 migration runner is not safe to run on the production-derived
Phase 43 snapshot in its current form.

The first blocker was memory: `--mode plan` materialized the production
snapshot in memory, including all stored embeddings as Python float lists. The
run was stopped after the Python process reached roughly 9 GB RSS. That memory
blocker was fixed by count-only manifest construction and streaming vector row
apply.

A second `--mode apply` run on the production-derived snapshot was allowed to
finish or fail naturally. It failed after `elapsed=2:57:54` with
`max_rss_kb=4026316` and a `5.4G` SurrealKV target. The failure occurred in the
graph phase while upserting file nodes:

```text
surrealdb.errors.InternalError: Found '/mnt/knowledgebase/voicenotes/20260419-1539-5Gs1Uhiw/transcript.md' for the `id` field, but a specific record has been specified
```

The immediate cause is that graph-export rows can contain an `id` field, and
`SurrealGraphStore.replace_file_rows()` passes that field in the payload while
also specifying the target record id in `upsert(record, payload)`.

The larger blocker is now migration design, not only that one bad field:

- destructive `explicit_replace` scans and deletes existing target rows one at
  a time, causing SurrealKV log/tombstone bloat after failed partial imports;
- most migration writes are row-by-row Surreal operations rather than bulk
  inserts;
- live progress is not persisted during long phases, so multi-hour runs are
  opaque until they finish or fail;
- `vector_components` is optional derived storage but is treated as required
  migration payload, duplicating a second large vector store;
- migration is hard-coded to `contextual_512_50_multilingual_e5_large` instead
  of discovering all `(chunk_strategy, embedding_model)` vector tables.

This supersedes the earlier stop note that blamed a missing
`DOTMD_SHADOW_TARGET_URL`. The target URL can be supplied explicitly, but the
target cannot be prepared safely until the migration plan/apply path is fixed
for memory, graph payload shape, progress telemetry, target replacement,
optional vector components, and multi-model/multi-strategy parity.

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

Fix the Phase 41 migration runner before retrying Phase 43 target preparation.
The first remediation pass has now been implemented in code:

- graph node payloads strip source `id` before explicit Surreal record upserts;
- apply catches unexpected Surreal exceptions and returns failed evidence state;
- `--progress-json` and `--resume-from-progress` support persisted phase
  checkpoints, so a retry can skip completed phases;
- default production migration no longer treats `vector_components` as required
  payload;
- primary metadata/vector/graph-node writes use batched `INSERT INTO ... $rows`
  instead of per-row Surreal calls.
- SQLite vector table discovery now walks all discovered
  `(chunk_strategy, embedding_model)` pairs instead of hard-coding
  `contextual_512_50_multilingual_e5_large`; Surreal embeddings now preserve
  `chunk_strategy` and use `(chunk_strategy, embedding_model, chunk_id)` record
  identity.
- embedded-local `explicit_replace` now physically resets the SurrealKV target
  before apply when not resuming from progress, avoiding row-by-row tombstone
  bloat in repeated rehearsals;
- migration progress now includes an `indexes` phase that rebuilds
  `embeddings_hnsw_idx` when that native retrieval index exists, so rows
  inserted after index creation become visible to HNSW queries.

Remaining before a trusted Phase 43 cutover attempt:

1. Measure the fresh-target SurrealKV size after `vector_components` removal and
   batched writes before accepting the target for shadow-run preflight.
