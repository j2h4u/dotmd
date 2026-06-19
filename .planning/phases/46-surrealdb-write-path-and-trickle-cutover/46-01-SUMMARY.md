---
phase: 46-surrealdb-write-path-and-trickle-cutover
plan: 01
status: in_progress
last_updated: 2026-06-19
---

# Phase 46 Plan 01 Summary

## What is done

Phase 46 now has the core incremental SurrealDB sync path:

- delta manifest contract for changed old-stack rows only;
- deterministic sync runner with resume state and progress/ETA snapshots;
- row-builder that filters transformed old-stack rows down to changed document refs;
- `SurrealDeltaStoreWriter` that uses point upserts and exact deletes only;
- writer-side table alias normalization for old-stack table names;
- stable record-id selection aligned with the bootstrap migration IDs;
- tombstone deletion by stable IDs from `previous_row`;
- fake-connection unit tests and real temporary `surrealkv://` smoke tests.

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

Verification run on 2026-06-19:

```bash
cd backend
UV_LINK_MODE=hardlink uv run pytest tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py -q
UV_LINK_MODE=hardlink uv run ruff check src/dotmd/ingestion/surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync.py tests/ingestion/test_surreal_delta_sync_live.py
```

Result:

- `20 passed`
- `All checks passed!`

The live smoke used real temporary `surrealkv://` storage, applied the dotMD
schema, seeded bootstrap-style records, applied a delta, reran with the same
state for resume-skip coverage, and reran with fresh state to prove no duplicate
record IDs or unrelated-row damage.

## Not done yet

Phase 46 is not complete. Remaining work:

- derive a real changed-file delta from current old-stack rows;
- run a controlled changed markdown file smoke without full reindex/re-embed;
- prove Surreal-backed search sees the updated result after sync;
- record the trickle boundary decision: bounded hybrid sync versus direct
  Surreal ingest sink;
- update production cutover criteria with the write-path evidence.

## Current Decision

Continue with the bounded hybrid path first: old-stack writes remain
authoritative while the Surreal target is refreshed through explicit incremental
sync. Direct Surreal ingest remains a later option after the changed-file smoke
proves the daily update path.
