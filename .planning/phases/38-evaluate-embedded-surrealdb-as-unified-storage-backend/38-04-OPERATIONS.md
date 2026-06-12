# Phase 38 Plan 04 Operations Evidence

- generated_at: 2026-06-12
- operations_gate: PASS for rehearsal evidence
- migration_gate: BLOCKED by Plan 38-03 retrieval parity
- requirement: STOR-04

## Inputs

| Evidence | Status | Notes |
|---|---|---|
| `38-05-EMBEDDED-SAFETY-GATE.md` | PASS | Embedded `surrealkv://` atomicity, rollback cleanup, writer guard, stale TTL recovery, and force-release passed. |
| `38-02-IMPORT-PROOF.md` | PASS | Transform-only import covered documents, chunks, vectors, graph rows, feedback, cursors, and checkpoints without rechunking, reembedding, or entity re-extraction. |
| `38-03-RETRIEVAL-PARITY.md` | FAIL | `recommendation_gate: fail`; failure categories: `defer: FTS weighting`, `reject: hybrid/RRF gap`. |

## backup / restore

The operations helper rehearses backup and restore only on copied/local Surreal store paths.

| Check | Result |
|---|---|
| surreal CLI | unavailable in this rehearsal path; fallback required |
| fallback | validated file-copy fallback |
| restore verification | reconnect/count-smoke equivalent represented by restored count comparison in tests |
| partial failure | cannot produce migrate-ready status |

Fallback restore is valid only when restored counts match every imported STOR-01 category. Missing surreal CLI plus unvalidated fallback maps to `CLI backup tooling` defer.

## rollback to current stack

Rollback rehearsal targets copied originals for the current stack:

- SQLite/sqlite-vec/FTS5: copied `index.db` original
- FalkorDB: copied graph export fixture
- smoke query: representative current-stack search/read check on the copied originals

This proves the rollback path is not merely Surreal-to-Surreal restore. Live production volumes are not mutated.

## writer / concurrency

Writer coordination remains target-specific:

- sidecar guard path: `<target>.surreal-writer-guard.json`
- second same-target writer: blocked
- stale owner: recoverable only after caller-provided TTL
- force-release: requires target-path match and records previous owner metadata

The helper does not reuse dotMD's live `indexing.lock` path for spike stores.

## partial import recovery

Partial import or failed restore cannot be marked as restored or migrate-ready. The recommendation builder requires all of these gates before `migrate`:

- transform coverage
- embedded safety
- retrieval parity
- scale gate
- backup/restore
- rollback to current SQLite/FalkorDB stack
- same-corpus full pipeline smoke
- writer coordination

## scale gate

Plan 38-03 supplied representative scale metrics, but the migration gate still fails because retrieval parity failed.

| Metric | Evidence |
|---|---|
| record count | representative copied sample in `38-03-RETRIEVAL-PARITY.md` |
| HNSW | no HNSW build required by the thin prototype; recorded as not built |
| SurrealKV file size | recorded in parity scale evidence |
| query latency | p50/p95 recorded for FTS, vector, graph-direct, and hybrid/RRF cases |

## full pipeline smoke

The same-corpus smoke path covers:

1. inventory
2. embedded safety gate
3. transform import
4. retrieval parity
5. operations
6. recommendation

The smoke can assemble the evidence chain, but it cannot pass a migration recommendation while Plan 38-03 reports `recommendation_gate: fail`.

## Operations Decision

Operations rehearsal evidence is sufficient for a spike-level fallback story, but the overall storage migration remains blocked by retrieval parity. The operations category is not the primary blocker; `hybrid/RRF gap` is.
