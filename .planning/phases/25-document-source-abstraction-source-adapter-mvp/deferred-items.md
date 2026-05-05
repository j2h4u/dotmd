# Phase 25 Deferred Items

## 25-01 Plan Verification

- `cd backend && uv run pyright` fails on pre-existing project-wide type errors
  outside the files changed by Plan 25-01. Changed-file pyright passes for
  `src/dotmd/core/models.py`, `src/dotmd/ingestion/source.py`, and
  `tests/ingestion/test_source_filesystem.py`.
