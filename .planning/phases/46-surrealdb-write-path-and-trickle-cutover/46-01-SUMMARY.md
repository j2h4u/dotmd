---
phase: 46-surrealdb-write-path-and-trickle-cutover
plan: 01
status: in_progress
last_updated: 2026-06-19
---

# Phase 46 Plan 01 Summary

## What is done

Phase 46 now has the core idempotent SurrealDB delta-apply machinery:

- delta manifest contract for changed old-stack rows only;
- deterministic sync runner with resume state and progress/ETA snapshots;
- row-builder that filters transformed old-stack rows down to changed document refs;
- `SurrealDeltaStoreWriter` that uses point upserts and exact deletes only;
- writer-side table alias normalization for old-stack table names;
- stable record-id selection aligned with the bootstrap migration IDs;
- tombstone deletion by stable IDs from `previous_row`;
- fake-connection unit tests and real temporary `surrealkv://` smoke tests.
- changed-file delta smoke from an old-stack SQLite fixture through
  `load_sqlite_rows_for_surreal()` and `build_surreal_delta_manifest_from_rows()`;
- schema-derived payload pruning in the writer, so old-stack row shapes do not
  need test-side field stripping before Surreal upsert;
- `vector_components` are accepted by the writer rather than excluded.

## Evidence

Commits:

- `d706e93` `feat(46): define surreal delta manifest`
- `fb534d4` `feat(46): add surreal delta sync runner`
- `172d2ab` `feat(46): build surreal delta manifests from rows`
- `ef09f60` `feat(46): add incremental surreal delta writer`
- `15d4cd0` `fix(46): normalize surreal delta table aliases`
- `f1ca595` `fix(46): resolve surreal tombstones by stable ids`
- `da3be6e` `test(46): smoke incremental surreal delta writer`
- `779c55f` `test(46): verify fresh surreal delta reruns`
- `f775c05` `test(46): smoke changed-file surreal delta`
- `527fda0` `fix(46): sanitize surreal delta payloads by schema`

Verification run on 2026-06-19:

```bash
cd backend
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py -q
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/ingestion/surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py
```

Result:

- `21 passed`
- `All checks passed!`

The live smoke used real temporary `surrealkv://` storage, applied the dotMD
schema, seeded bootstrap-style records, applied a delta, reran with the same
state for resume-skip coverage, and reran with fresh state to prove no duplicate
record IDs or unrelated-row damage.

The changed-file smoke used the existing synthetic old-stack SQLite fixture,
loaded rows with `load_sqlite_rows_for_surreal()`, built a one-document delta,
applied it to temporary SurrealKV, and proved unrelated old-stack rows were not
applied by that delta.

## Direction Change

The product decision is direct cutover to SurrealDB, not a bounded hybrid
runtime. The delta-sync work above remains useful as migration/retry safety and
as proof that Surreal writes are idempotent, schema-aware, and stable by record
ID. It is not the target steady-state architecture.

## Not done yet

Phase 46 is not complete. Remaining work:

- implement direct SurrealDB ingest/write sink for trickle/indexing;
- make changed markdown files write to SurrealDB without using SQLite as the
  daily authoritative store;
- prove Surreal-backed search sees updated results after direct Surreal writes;
- remove or quarantine old-stack write dependencies before production cutover;
- update production cutover criteria with the write-path evidence.

## Current Decision

Proceed with direct SurrealDB write path. Do not build a long-lived hybrid
old-stack-to-Surreal sync layer.
