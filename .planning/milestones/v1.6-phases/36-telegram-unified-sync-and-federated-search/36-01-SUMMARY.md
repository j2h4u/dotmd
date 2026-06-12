---
phase: 36-telegram-unified-sync-and-federated-search
plan: "01"
subsystem: ingestion
tags: [tdd, tg-03, tg-04, rebound-units, ref-consistency]
dependency_graph:
  requires: []
  provides: [rebound_units_counter, tg04_regression_anchor]
  affects: [pipeline.py, cli.py, test_telegram_provider.py]
tech_stack:
  added: []
  patterns: [TDD RED/GREEN/REFACTOR, dataclass field addition, binding rebound detection]
key_files:
  created: []
  modified:
    - backend/src/dotmd/ingestion/pipeline.py
    - backend/src/dotmd/cli.py
    - backend/tests/ingestion/test_telegram_provider.py
decisions:
  - "rebound detection uses dialog-level resource_ref (change.document.document_ref) matching upsert_resource_binding key"
  - "TG-04 invariant confirmed by construction — test anchored as regression guard"
metrics:
  duration: "4 minutes"
  completed_date: "2026-05-10"
  tasks_completed: 4
  files_modified: 3
---

# Phase 36 Plan 01: TG-03 rebound_units counter + TG-04 ref consistency regression test Summary

TDD plan locking the rebound_units reporting counter (TG-03) and the message-level ref consistency invariant (TG-04) via RED/GREEN/REFACTOR cycle and a regression anchor commit.

## What Was Built

**TG-03 — rebound_units counter:**
- `ApplicationSourceIngestResult` gains `rebound_units: int = 0` field
- Second loop in `_ingest_application_source` checks `get_resource_binding` before `upsert_resource_binding`; if the existing binding has `active=False`, increments `result.rebound_units`
- CLI `telegram ingest` output now includes `rebound_units=N` and `reused_units=N`

**TG-04 — ref consistency regression anchor:**
- `test_tg04_public_ref_matches_search_native_ref` confirms that `public_ref_for_unit`, the `ChunkProvenance.ref` formula (`{namespace}:{unit_ref}`), and `search_native` result refs all produce `telegram:dialog:<id>:message:<id>` — the invariant holds by construction and is now pinned as a regression guard

## TDD Gate Compliance

| Gate | Commit | Status |
|------|--------|--------|
| RED | 429500b | `test_application_source_ingest_result_has_rebound_units` FAILED (field absent) |
| GREEN | eb84e92 | `test_application_source_ingest_result_has_rebound_units` PASSED (field added) |
| REFACTOR | 6eab8d0 | CLI output updated, all 173 tests pass |
| TG-04 ANCHOR | 1d03929 | TG-04 invariant confirmed, full suite green |

## Commits

| Task | Commit | Description |
|------|--------|-------------|
| RED | 429500b | test(36): RED — rebound_units missing from ApplicationSourceIngestResult (TG-03) |
| GREEN | eb84e92 | feat(36): add rebound_units to ApplicationSourceIngestResult + rebound detection (TG-03) |
| REFACTOR | 6eab8d0 | refactor(36): add rebound_units and reused_units to telegram ingest CLI output (TG-03) |
| TG-04-ANCHOR | 1d03929 | test(36): anchor TG-04 ref consistency as regression test |

## Verification Results

```
cd backend && uv run pytest tests/ingestion/ -x -q
173 passed, 88 warnings in 8.44s

grep "rebound_units" backend/src/dotmd/ingestion/pipeline.py
    rebound_units: int = 0
                    result.rebound_units += 1

grep "rebound_units\|reused_units" backend/src/dotmd/cli.py
        f"rebound_units={result.rebound_units} "
        f"reused_units={result.reused_units}"
```

## Deviations from Plan

None — plan executed exactly as written.

The plan specified `change.document.document_ref` as the lookup key for `get_resource_binding` (dialog-level, matching `upsert_resource_binding`). This was confirmed correct by reading the `upsert_resource_binding` call at line ~588 which uses `resource_ref=change.document.document_ref`.

## Known Stubs

None.

## Threat Flags

None — no new network endpoints, auth paths, file access patterns, or schema changes introduced.

## Self-Check: PASSED

- `backend/src/dotmd/ingestion/pipeline.py` — modified, contains both `rebound_units: int = 0` and `result.rebound_units += 1`
- `backend/src/dotmd/cli.py` — modified, contains `rebound_units` and `reused_units` in output
- `backend/tests/ingestion/test_telegram_provider.py` — modified, contains both new tests
- Commits 429500b, eb84e92, 6eab8d0, 1d03929 — all present in git log
