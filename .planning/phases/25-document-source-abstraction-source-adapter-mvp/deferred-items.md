# Phase 25 Deferred Items

## 25-01 Plan Verification

- `cd backend && uv run pyright` fails on pre-existing project-wide type errors
  outside the files changed by Plan 25-01. Changed-file pyright passes for
  `src/dotmd/core/models.py`, `src/dotmd/ingestion/source.py`, and
  `tests/ingestion/test_source_filesystem.py`.

## 25-02 Plan Verification

- `cd backend && uv run pyright` still fails on the same pre-existing
  project-wide type errors reported in Plan 25-01, plus older test typing
  issues outside Plan 25-02. The new Plan 25-02 test typing issue found during
  verification was fixed before completion; `tests/ingestion/test_source_filesystem.py`
  now passes targeted pyright.
