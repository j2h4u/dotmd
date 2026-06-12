# Deferred Items

## Plan 24-01

- Direct `uv run pyright` over `backend/src/dotmd/api/service.py` and
  `backend/src/dotmd/ingestion/trickle.py` reports pre-existing protocol and
  optional-member errors that are outside this config-boundary change. The
  repository ratchet gate remains unchanged and passes via `just typecheck`
  (`pyright ratchet: 76 errors (baseline 76)`).
