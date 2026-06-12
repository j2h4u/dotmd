---
phase: 29-telegram-adapter-mvp-ingestion
verified: 2026-05-08T08:55:53Z
status: passed
score: 10/10 must-haves verified
overrides_applied: 0
re_verification:
  previous_status: human_needed
  previous_score: 9/10
  gaps_closed:
    - "Live bounded smoke proves the Phase 29 deployed ingestion boundary."
  gaps_remaining: []
  regressions: []
deferred:
  - truth: "Full public search(query) -> Telegram ref -> drill/read live smoke"
    addressed_in: "Phase 31"
    evidence: "ROADMAP.md Phase 31 goal: Harden and verify the public dotMD MCP workflow for Telegram content: search(query) -> ref -> drill(ref) / read(ref, start, end)."
---

# Phase 29: Telegram Adapter MVP Ingestion Verification Report

**Phase Goal:** Ingest selected synced Telegram dialogs/messages from the existing mcp-telegram runtime into dotMD as first-class source units with stable provenance.
**Verified:** 2026-05-08T08:55:53Z
**Status:** passed
**Re-verification:** Yes - after deployment smoke gap closure

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | mcp-telegram exposes structured source description, export changes, update watermarks, and read windows. | VERIFIED | Daemon/client source API tests pass: `cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py tests/test_daemon_client.py -q` -> `53 passed in 5.33s`. Previous code evidence still applies for `describe_source`, `export_source_changes`, `read_source_unit_window`, `checkpoint_cursor`, `updated_after`, and `updated_after_cursor`. |
| 2 | dotMD consumes Telegram through a structured provider/client boundary, not Telegram internals or rendered message text. | VERIFIED | `TelegramSourceClientProtocol`, `UnixSocketTelegramSourceClient`, and `TelegramApplicationSourceProvider` are implemented in `backend/src/dotmd/ingestion/telegram_provider.py`. Anti-pattern scan found no forbidden provider coupling to `telethon`, `sync_db`, or rendered `list_messages` output in this provider. |
| 3 | Public refs and source units are message-shaped and stable: `telegram:dialog:<dialog_id>:message:<message_id>`. | VERIFIED | Provider maps message public refs with `public_ref_for_unit()` and docs state `public message ref = telegram:dialog:<dialog_id>:message:<message_id>` in `docs/source-adapter-architecture.md`. |
| 4 | Telegram messages are the recomputation/provenance boundary; unchanged replay skips work, edited units are reprocessed. | VERIFIED | Focused dotMD tests pass: `cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py -q` -> `65 passed, 50 warnings in 4.46s`; these include unchanged replay, edited-message reindexing, source-unit fingerprints, and provider watermark forwarding. |
| 5 | Low-signal Telegram messages are retained as source units but suppressed as standalone normal search chunks. | VERIFIED | `is_low_signal_telegram_text()` and `standalone_search` are implemented in `backend/src/dotmd/ingestion/telegram_provider.py`; ingestion tests verify low-signal fingerprints persist and standalone low-signal chunks are not produced. |
| 6 | Telegram ingestion persists source documents, bindings, fingerprints, provenance, FTS5 rows, vectors, and checkpoint state in a single local transaction. | VERIFIED | `IndexingPipeline.ingest_application_source()` is covered by transaction rollback and persistence tests in `backend/tests/ingestion/test_telegram_ingestion.py`; focused tests pass. |
| 7 | Pathless Telegram chunks are hydrated through source provenance, not filesystem file-path joins. | VERIFIED | Telegram chunks use `file_paths=[]`; `SQLiteMetadataStore.get_chunks_by_source_unit_ref(...)` and `delete_chunks_for_source_unit(...)` support provenance hydration/replacement; tests prove pathless chunks coexist with filesystem chunks. |
| 8 | Initial `read(ref)` and `drill(ref)` support accepts Telegram message refs without filesystem frontmatter. | VERIFIED | `backend/src/dotmd/api/service.py` contains Telegram-specific parsing/read/drill branches; tests verify three-message read windows, dialog-scope active binding checks, local provenance fallback, and inactive-binding rejection. |
| 9 | Operator surface supports bounded single-batch Telegram ingest over the existing UNIX socket transport only. | VERIFIED | `backend/src/dotmd/core/config.py` exposes `telegram_daemon_socket`; `backend/src/dotmd/cli.py` exposes `dotmd telegram ingest --limit N --dry-run --single-batch` and rejects loop mode in Phase 29. Negative scan found no `DOTMD_TELEGRAM_DAEMON_URL` or `telegram_daemon_url` in the checked Phase 29 code paths. |
| 10 | Live bounded smoke proves the Phase 29 deployed ingestion boundary. | VERIFIED | Runtime re-verification passed. `docker ps` showed `mcp-telegram Up ... (healthy)` and `dotmd Up ... (healthy)`. `/opt/docker/dotmd/docker-compose.override.yml` mounts external Docker volume `mcp-telegram_state` as `/mcp-telegram-state:ro`; `/opt/docker/dotmd/.env` sets `DOTMD_TELEGRAM_DAEMON_SOCKET=/mcp-telegram-state/daemon.sock`. Socket preflight succeeded in the dotMD container and `docker exec dotmd dotmd telegram ingest --limit 10 --dry-run --single-batch` returned `telegram_ingest dry_run=true single_batch=true namespace=telegram discovered=10 next_cursor=telegram:v1:dialog:-1003897013523:message:9 checkpoint_cursor=telegram:v1:dialog:-1003897013523:message:9`. |

**Score:** 10/10 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|---|---|---|
| 1 | Full public `search(query) -> Telegram ref -> drill/read` live smoke | Phase 31 | `.planning/ROADMAP.md` Phase 31 goal is to harden and verify the public dotMD MCP workflow for Telegram content: `search(query) -> ref -> drill(ref) / read(ref, start, end)`. `docs/source-adapter-architecture.md` also states Phase 31 owns this live smoke. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_api.py` | Structured daemon source API | VERIFIED | Daemon/client tests passed; source export/read-window API is available to the rebuilt runtime used by smoke. |
| `/home/j2h4u/repos/j2h4u/mcp-telegram/src/mcp_telegram/daemon_client.py` | Client wrappers with timeout | VERIFIED | Covered by `tests/test_daemon_client.py`; focused suite passed. |
| `backend/src/dotmd/ingestion/telegram_provider.py` | dotMD Telegram provider/client mapping | VERIFIED | Structured client protocol, UNIX socket client, provider mapping, low-signal classification, public ref helper. |
| `backend/src/dotmd/ingestion/pipeline.py` | Telegram application-source ingestion | VERIFIED | Single-batch ingest, checkpoint/watermark forwarding, low-signal retention, pathless chunks, metadata/FTS/vector/checkpoint transaction are covered by tests. |
| `backend/src/dotmd/storage/metadata.py` | Provenance hydration/deletion helpers | VERIFIED | `get_chunks_by_source_unit_ref` and `delete_chunks_for_source_unit` support pathless Telegram chunks. |
| `backend/src/dotmd/search/fts5.py` | Source-meta FTS wrapper | VERIFIED | Telegram chunks get explicit source metadata through the source-meta wrapper; focused ingestion tests pass. |
| `backend/src/dotmd/api/service.py` | Telegram read/drill resolver | VERIFIED | Telegram refs resolve before filesystem fallback; read/drill resolver tests pass. |
| `backend/src/dotmd/cli.py` | Bounded smoke command | VERIFIED | `dotmd telegram ingest --limit 10 --dry-run --single-batch` passed in the running container. |
| `backend/src/dotmd/core/config.py` | Runtime socket config | VERIFIED | `telegram_daemon_socket` maps to `DOTMD_TELEGRAM_DAEMON_SOCKET`; deployed container has the env var set. |
| `/opt/docker/dotmd/docker-compose.override.yml` and `/opt/docker/dotmd/.env` | Runtime socket mount/env | VERIFIED | Override mounts `mcp-telegram_state` at `/mcp-telegram-state:ro`; `.env` sets `/mcp-telegram-state/daemon.sock`; socket preflight passed. |
| `docs/mcp-telegram-source-contract.md` and `docs/source-adapter-architecture.md` | Delivered-state documentation | VERIFIED | Docs state structured API, no private DB reads, UNIX socket boundary, Phase 29 scope, and Phase 31 search/read/drill smoke deferral. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| mcp-telegram daemon | dotMD provider | `describe_source`, `export_source_changes`, `read_source_unit_window` JSON methods over UNIX socket | WIRED | Live dry-run smoke exercised the deployed dotMD -> socket -> mcp-telegram source export path. |
| dotMD provider | ingestion pipeline | `ApplicationSourceProviderProtocol.export_changes(...)` | WIRED | Pipeline calls provider export with checkpoint cursor and update watermarks; tests pass. |
| ingestion pipeline | metadata/FTS/vector stores | shared SQLite transaction | WIRED | Rollback and persistence tests pass. |
| service `read/drill` | Telegram source provenance/provider | parser plus provider/fallback branches | WIRED | Resolver tests pass for provider window and local indexed-chunk fallback. |
| CLI | runtime socket | `DOTMD_TELEGRAM_DAEMON_SOCKET` | WIRED | Container env points to a mounted socket and bounded dry-run ingest returned structured counts/cursors. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `daemon_api.py` export | `changes` | mcp-telegram stored synced/syncing/access_lost messages | Yes | FLOWING - live smoke discovered 10 records. |
| `telegram_provider.py` batch | `ApplicationSourceChangeBatch.changes` | `client.export_source_changes(...)` payload | Yes | FLOWING - live dry-run provider export returned 10 changes and cursors. |
| `pipeline.py` ingest | `batch.changes` | Provider export plus stored checkpoint metadata | Yes | FLOWING - fixture tests cover persistence; live dry-run proves runtime source export boundary. |
| `service.py` Telegram read | `window.units` or provenance chunks | Provider `read_unit_window` or `get_chunks_by_source_unit_ref` | Yes | FLOWING - resolver tests pass. |
| `cli.py` live smoke | dry-run batch | UNIX socket configured from `DOTMD_TELEGRAM_DAEMON_SOCKET` | Yes | FLOWING - socket preflight and `dotmd telegram ingest --limit 10 --dry-run --single-batch` passed. |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| dotMD Telegram provider/ingest/read tests | `cd backend && uv run pytest tests/api/test_service_search.py tests/ingestion/test_telegram_ingestion.py tests/ingestion/test_telegram_provider.py -q` | `65 passed, 50 warnings in 4.46s` | PASS |
| mcp-telegram daemon/client source API tests | `cd /home/j2h4u/repos/j2h4u/mcp-telegram && uv run pytest tests/test_daemon.py tests/test_daemon_client.py -q` | `53 passed in 5.33s` | PASS |
| dotMD typecheck ratchet | `cd backend && just typecheck` | `pyright ratchet: 66 errors (baseline 69); improvements: -3 across 2 files` | PASS WITH RATCHET |
| dotMD lint | `cd backend && just lint` | `All checks passed!` | PASS |
| Container health | `docker ps --format '{{.Names}} {{.Status}}' | rg '^(dotmd|mcp-telegram) '` | `mcp-telegram Up ... (healthy)` and `dotmd Up ... (healthy)` | PASS |
| Socket preflight | `docker exec dotmd sh -lc 'printf "DOTMD_TELEGRAM_DAEMON_SOCKET=%s\n" "${DOTMD_TELEGRAM_DAEMON_SOCKET-}"; test -S "$DOTMD_TELEGRAM_DAEMON_SOCKET"; ls -l "$DOTMD_TELEGRAM_DAEMON_SOCKET"'` | `DOTMD_TELEGRAM_DAEMON_SOCKET=/mcp-telegram-state/daemon.sock`; socket exists at that path | PASS |
| Live bounded ingest smoke | `docker exec dotmd dotmd telegram ingest --limit 10 --dry-run --single-batch` | `telegram_ingest dry_run=true single_batch=true namespace=telegram discovered=10 next_cursor=telegram:v1:dialog:-1003897013523:message:9 checkpoint_cursor=telegram:v1:dialog:-1003897013523:message:9` | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| R4 | Plans 01, 02, 03, 04 | Telegram provider via mcp-telegram | SATISFIED | dotMD consumes structured mcp-telegram daemon/client payloads over the configured UNIX socket; live dry-run source export passed; dotMD does not instantiate Telegram API client or parse private sync DB/rendered output. |
| R5 | Plans 01, 02, 03, 04 | Telegram source units are recomputation boundary | SATISFIED | Message-level refs, source-unit fingerprints, unchanged skip, changed unit replacement, provenance, and update watermark/tie-break cursor are implemented and tested. |
| R7 | Plan 04 | Telegram search/read/drill round-trip | SATISFIED FOR PHASE 29 BOUNDARY | Initial `read(ref)` and `drill(ref)` for Telegram message refs are implemented and tested. Full public `search(query) -> Telegram ref -> read/drill` live smoke is explicitly deferred to Phase 31. |
| R8 | Plans 01, 02, 03, 04 | Validation and smoke | SATISFIED | Fixture tests, mcp-telegram source API tests, typecheck ratchet, lint, container health, socket preflight, and bounded live ingest smoke all passed or have documented ratchet status. |

No orphaned Phase 29 requirement IDs found: requested IDs R4, R5, R7, and R8 appear in Phase 29 plan frontmatter and are traced above.

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `docs/source-adapter-architecture.md` | 763 | Mentions `list_messages` as agent-facing, not indexing-facing | INFO | Documentation-only boundary explanation; not a provider implementation dependency. |

### Human Verification Required

None. The previous human-needed deployment smoke item is now verified by live container/socket/dry-run evidence.

### Gaps Summary

No blocking gaps remain for Phase 29. The deployed Phase 29 ingestion boundary is verified: dotMD has the mcp-telegram daemon socket mounted/configured, both containers are healthy, and a bounded dry-run source ingest returns structured Telegram counts and cursors.

Full public Telegram `search(query) -> ref -> drill/read` live smoke remains deferred to Phase 31 by roadmap and docs, not a Phase 29 gap.

---

_Verified: 2026-05-08T08:55:53Z_
_Verifier: the agent (gsd-verifier)_
