# Phase 31 Plan 01: Live Telegram Search/Read/Drill Smoke

## Goal

Verify the current v1.5 Telegram baseline on live containers by ingesting a
bounded Telegram batch and proving the public workflow:

`search(query) -> ref -> drill(ref) / read(ref, start, end)`

## Scope

- Run existing live MCP smoke against the deployed `dotmd` container.
- Ingest about 100 Telegram messages through the bounded Telegram source ingest.
- Search for real ingested Telegram content through `DotMDService`.
- Verify the returned Telegram `ref` is directly usable by `drill` and `read`.
- Fix only blocking contract bugs discovered by the smoke.

## Verification

- `just test-e2e`
- `docker exec dotmd dotmd telegram ingest --single-batch --limit 100`
- Live service search for `кругляш видео люди ботом`
- Targeted regression tests for search-result ref hydration and Telegram read/drill

