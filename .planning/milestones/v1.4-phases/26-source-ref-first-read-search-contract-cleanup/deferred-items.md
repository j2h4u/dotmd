# Deferred Items

## Plan 26-01

- `cd backend && uv run pyright` still fails with 69 errors after the
  source-ref contract fixes. The remaining failures are outside the files and
  behaviors changed by Plan 26-01: protocol drift in `api/service.py` and
  `ingestion/pipeline.py`, GLiNER typing in `extraction/ner.py`, optional
  pipeline access typing in `ingestion/trickle.py`, FalkorDB result typing in
  `storage/graph.py`, pre-existing `_ConnProxy` typing in `storage/metadata.py`,
  and older ingestion/storage tests that still violate current constructor
  types. The directly caused CLI/MCP/SearchResult/read payload errors from this
  plan were fixed in commit `e125fdc`.
