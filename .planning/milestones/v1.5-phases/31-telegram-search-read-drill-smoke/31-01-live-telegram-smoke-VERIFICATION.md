# Phase 31 Verification: Live Telegram Search/Read/Drill Smoke

Date: 2026-05-08

## Result

PASS.

## Commands

- `curl -fsS http://127.0.0.1:18082/health`
  - Result: `{"status":"ok"}`
- `just test-e2e`
  - Result: `36 passed in 163.08s`
- `docker exec dotmd dotmd telegram ingest --dry-run --single-batch --limit 5`
  - Result: source reachable; 5 discovered
- `docker exec dotmd dotmd telegram ingest --single-batch --limit 100`
  - Result: `discovered=100 new_units=100 changed_units=0 skipped_units=0 hidden_units=4 failed_units=0`
- `cd backend && uv run pytest tests/test_fusion.py::test_build_search_results_uses_telegram_message_ref_from_unit_provenance -q`
  - Result: `1 passed`
- `cd backend && uv run pytest tests/test_fusion.py tests/api/test_service_search.py -k telegram -q`
  - Result: `8 passed, 61 deselected`

## Live Search Evidence

Query: `кругляш видео люди ботом`

Search returned a Telegram hit:

- `telegram:dialog:-1003897013523:message:80`
- Snippet contains: `Может быть, добавить еще и кругляш-видео, чтобы было видно людей за этим ботом`

`drill(ref)` returned:

- title: `KS x Женские сезоны`
- document_ref: `dialog:-1003897013523`
- target_unit_ref: `dialog:-1003897013523:message:80`

`read(ref, start=2, end=2)` returned a 5-message Telegram window with
`target=true` on message `80`.

## Fix Applied During Smoke

The first live run exposed that Telegram search results returned the dialog ref
`telegram:dialog:-1003897013523`, while Telegram `read` and `drill` require a
message ref such as `telegram:dialog:-1003897013523:message:80`.

Fixed in `backend/src/dotmd/search/fusion.py`: when chunk provenance belongs to
Telegram and contains exactly one source unit, `SearchResult.ref` now uses the
message-level unit ref. Regression coverage was added in `backend/tests/test_fusion.py`.

## Residual Scope

Phase 31 verifies the v1.5 baseline only. It does not prove deferred Phase 30
incremental sync/reuse behavior; that scope remains in Backlog 999.30.

