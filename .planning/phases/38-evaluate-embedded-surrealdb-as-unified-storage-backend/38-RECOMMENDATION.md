Recommendation: reject
Failure category: hybrid/RRF gap

# Phase 38 Storage Recommendation

Phase 38 does not support moving dotMD to Embedded SurrealDB as the single storage backend now.

## Why

SurrealDB passed meaningful early gates:

- STOR-01 / STOR-03: current stored data can be represented and transform-imported without default rechunking, TEI reembedding, or entity re-extraction.
- STOR-04: embedded `surrealkv://` atomicity and writer-safety probes passed.
- STOR-04: backup, restore, rollback, writer guard, and concurrency helpers now have copied-store rehearsal coverage.

The blocker is STOR-02:

- `38-03-RETRIEVAL-PARITY.md` reports `recommendation_gate: fail`.
- FTS weighted-field behavior diverges: failure category `defer: FTS weighting`.
- Hybrid/RRF attribution diverges: failure category `reject: hybrid/RRF gap`.

D-01 is partly satisfied for data movement, but not for user-visible retrieval behavior. A storage migration that preserves stored rows while changing dotMD search ranking is not acceptable.

## Gate Summary

| Gate | Status | Evidence |
|---|---|---|
| STOR-01 transform coverage | PASS | `38-01-MIGRATION-MAP.md`, `38-02-IMPORT-PROOF.md` |
| STOR-02 retrieval parity | FAIL | `38-03-RETRIEVAL-PARITY.md` |
| STOR-03 no CPU-heavy recomputation | PASS | `38-02-IMPORT-PROOF.md` |
| STOR-04 embedded safety | PASS | `38-05-EMBEDDED-SAFETY-GATE.md` |
| backup / restore | PASS for copied-store rehearsal | `38-04-OPERATIONS.md` |
| rollback safety | PASS for copied SQLite/FalkorDB originals | `38-04-OPERATIONS.md` |
| concurrency / writer guard | PASS for spike boundary | `38-05-EMBEDDED-SAFETY-GATE.md`, `38-04-OPERATIONS.md` |
| scale behavior | BLOCKED by parity | record count, HNSW note, SurrealKV file size, and query latency are recorded in `38-03-RETRIEVAL-PARITY.md` |

## Rollback Path

The fallback remains the current stack:

- SQLite + FTS5 + sqlite-vec in `index.db`
- FalkorDB for graph retrieval
- existing feedback provider/exporter surface

Rollback rehearsal uses copied SQLite/sqlite-vec/FTS5 and FalkorDB originals, not a Surreal-only restore. No production data path is changed by Phase 38.

## Deployment / Config Implication

Do not wire SurrealDB into `DotMDService`, `IndexingPipeline`, CLI defaults, Docker compose, or production startup. The Surreal code added in Phase 38 is spike evidence and test harness code only.

## Remaining Work If Revisited

1. Prove weighted FTS parity or preserve the existing SQLite FTS5 path.
2. Prove hybrid/RRF ordering and engine attribution parity on the same corpus.
3. Re-run scale evidence after retrieval parity passes, including record count, HNSW build time where relevant, SurrealKV file size, and representative query latency.
4. Decide whether a partial architecture is worth planning, for example Surreal for metadata/import records while keeping current FTS/vector/graph retrieval engines.
