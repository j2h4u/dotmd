# Phase 43 Shadow Run Preflight Failure

Generated: 2026-06-16T07:34:00Z

## Status

Candidate-target preflight failed before baseline or candidate capture.

## Missing Input

`DOTMD_SHADOW_TARGET_URL` is not configured in this execution environment.

The runner was invoked with an explicit empty `--target-url` value, and the
SurrealDB client rejected it before a candidate connection could be opened:

```text
ValueError: '' is not a valid UrlScheme
```

## Inputs Validated Before Failure

- Rehearsal index copy exists at
  `.planning/phases/43-shadow-run-and-quality-gate/artifacts/rehearsal-index/index.db`.
- The rehearsal copy was produced through SQLite backup from the running dotMD
  container, not by copying live WAL files directly.
- `PRAGMA integrity_check` returned `ok` on the copied database.
- `source-capture-expected.json` exists and records the copied database identity:
  `chunk_strategy=contextual_512_50`,
  `embedding_model=intfloat/multilingual-e5-large`,
  `expected_chunk_count=149800`, and
  `expected_embedding_count=149800`.
- `candidate-config.json` and `metrics-replay-queries.jsonl` exist.

## Capture State

No baseline results, candidate results, shadow diffs, shadow summary, scale
metrics, memory metrics, production cutover, runtime default switch, fallback
backend, rechunking, reembedding, or entity re-extraction were performed.

## Required Next Input

Provide a prepared Phase 41/42 Surreal candidate target and rerun preflight with:

- `DOTMD_SHADOW_TARGET_URL`
- `DOTMD_SHADOW_TARGET_NAMESPACE`
- `DOTMD_SHADOW_TARGET_DATABASE`

The target must match `source-capture-expected.json` for chunk strategy,
embedding model, import id, chunk count, and embedding count.
