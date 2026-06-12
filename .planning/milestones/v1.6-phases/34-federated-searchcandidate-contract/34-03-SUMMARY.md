---
phase: "34"
plan: "03"
subsystem: "federated-search"
tags: ["telegram", "federated-candidates", "tdd"]
status: "In Progress (Tasks 1-2 complete, Tasks 3-5 remain)"
completed_tasks: [0, 1, 2]
total_tasks: 6
duration_estimate: "3 hours remaining"
dependency_graph:
  requires: ["34-01", "34-02"]
  provides: ["Phase 35: Filesystem Unification"]
  affects: ["search contract", "read/drill contract"]
tech_stack:
  added: ["SearchCandidate.provider_metadata", "SearchCandidate.source_native_rank"]
  patterns: ["federated candidates", "provider runtime capability detection"]
key_files:
  created: []
  modified: ["backend/src/dotmd/ingestion/telegram_provider.py", "backend/src/dotmd/api/service.py"]
decisions:
  - "D-13: can_read derived from runtime provider capability check"
  - "D-14: can_materialize=False for all Phase 34 candidates"
  - "D-15: Federated read errors are provider-attributed RuntimeError"
  - "D-16: End-to-end contract proof via mcp-telegram daemon search_messages"
  - "D-17: dotMD never owns Telegram client; all access via daemon socket"
  - "D-18: Contract generic for gmail/slack/notion sources"
  - "D-LOCAL-FIRST-TG-READ: read()/drill() check local FIRST with Phase 27 binding gate"
  - "D-RANK-ZERO-BASED: source_native_rank is zero-based"
  - "D-METADATA-WHITELIST: provider_metadata safe fields only"
  - "D-PREFLIGHT: Task 5 autonomous per mcp-telegram search_messages availability"
---

# Phase 34 Plan 03: Telegram Federated Proof and Read/Drill Round-trip

## Summary

Tasks 0 (Preflight) and 1-2 (TDD RED + implementation of `search_native` on Telegram provider) have been completed. The preflight confirmed that mcp-telegram daemon exposes the `search_messages` method, making Task 5 (live smoke) fully autonomous.

Tasks 3-5 remain to complete federated read/drill routing and the final smoke test.

## Completed Work

### Task 0: Preflight ✅

- **Status:** COMPLETE
- **Finding:** mcp-telegram daemon socket at `/root/.local/state/mcp-telegram/daemon.sock` responds to `search_messages` requests with structured success responses.
- **Resolution:** Task 5 (live smoke) set to `autonomous=true` (no coordination delays needed).
- **Evidence:** Live daemon socket probe, documented in 34-PREFLIGHT.md

### Task 1: Telegram Federated Provider Tests (TDD RED) ✅

- **Status:** COMPLETE (GREEN phase passed)
- **Tests Added:** 8 tests in `backend/tests/ingestion/test_telegram_provider.py`
  - `test_telegram_source_client_protocol_includes_search_messages`
  - `test_unix_socket_search_messages_request_shape`
  - `test_search_native_returns_searchcandidate_list`
  - `test_search_native_can_read_derived_from_provider_capability` (cycle-2 MEDIUM)
  - `test_search_native_provider_metadata_whitelist` (cycle-2 MEDIUM)
  - `test_search_native_source_native_rank_is_zero_based` (D-RANK-ZERO-BASED)
  - `test_search_native_handles_empty_hits`
  - `test_search_native_propagates_daemon_failure`
- **Test Result:** All 16 telegram provider tests pass (8 new + 8 existing)
- **Commit:** `96b4c5e feat(34-03): implement Telegram federated search (Tasks 1-2)`

### Task 2: Telegram search_native Implementation (TDD GREEN) ✅

- **Status:** COMPLETE
- **Implementation Changes:**
  - Added `search_messages` method to `TelegramSourceClientProtocol`
  - Implemented `search_messages` in `UnixSocketTelegramSourceClient`
  - Implemented `search_native` in `TelegramApplicationSourceProvider`
  - Added `TELEGRAM_PROVIDER_METADATA_KEYS` whitelist (cycle-2 MEDIUM fold-in)
  - Derived `can_read` from runtime capability check (cycle-2 MEDIUM)
  - Zero-based `source_native_rank` per D-RANK-ZERO-BASED
  - Restricted `provider_metadata` to `{dialog_id, message_id, sender, sent_at, dialog_name}`
- **Test Coverage:** All 8 new tests pass
- **Type Safety:** pyright clean (0 errors, 0 warnings)
- **Integrity:** No Telethon imports, no direct mcp-telegram SQLite access, all access via daemon socket
- **Commit:** `96b4c5e feat(34-03): implement Telegram federated search (Tasks 1-2)`

## Remaining Work

### Task 3: Federated Read/Drill Round-trip Tests (TDD RED Phase)

**Tests to add in `backend/tests/ingestion/test_telegram_ingestion.py`:**

1. `test_federated_only_message_round_trip` — set up DotMDService with Telegram lifecycle; search hits federated-only ref; read returns text from daemon payload; verify no chunks added to local store
2. `test_federated_drill_returns_provider_metadata` — drill on federated-only ref returns total_chunks=0, parser_name="telegram-message", target_metadata from daemon
3. `test_federated_read_provider_down_attribution` — daemon failure raises RuntimeError with "telegram" attribution
4. `test_truly_federated_telegram_ref_routes_to_provider` (cycle-2 HIGH-7) — ref with NO local-store presence calls provider.read_unit_window
5. `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider` (cycle-2 HIGH-7 CRITICAL) — local doc with INACTIVE binding raises PermissionError, provider NOT called
6. `test_active_locally_indexed_telegram_ref_uses_local_path` (cycle-2 HIGH-7) — local doc with ACTIVE binding uses local read, provider NOT called
7. `test_federated_read_helper_naming` — verify `TelegramReadPath` enum and `_resolve_telegram_read_path` helper exist

**Tests to add in `backend/tests/api/test_service_search.py`:**

1. `test_telegram_federated_engine_participates` — search with Telegram lifecycle returns source_status entry with name="tg:fts", status="ok"
2. `test_phase_34_candidates_never_materializable` — all candidates from local + federated sources have can_materialize=False
3. `test_provider_metadata_is_treated_as_opaque` — federated candidate provider_metadata round-trips through JSON serialization
4. `test_no_local_index_writes_during_federated_search` — chunk counts identical before/after federated search

### Task 4: Read/Drill Federated Routing (TDD GREEN Phase)

**Implementation in `backend/src/dotmd/api/service.py`:**

1. Add `TelegramReadPath` enum:
   ```python
   class TelegramReadPath(Enum):
       LOCAL_ACTIVE = "local_active"
       LOCAL_INACTIVE = "local_inactive"
       FEDERATED_ONLY = "federated_only"
   ```

2. Add routing helper `_resolve_telegram_read_path(ref) -> _TelegramRouteResult`:
   - Returns LOCAL_ACTIVE if doc exists with active binding
   - Returns LOCAL_INACTIVE if doc exists but binding is inactive (Phase 27 gate)
   - Returns FEDERATED_ONLY if doc does not exist in local store

3. Refactor `read(ref)` with three-way dispatch:
   - LOCAL_ACTIVE: existing local read path
   - LOCAL_INACTIVE: raise PermissionError (Phase 27 invariant preserved)
   - FEDERATED_ONLY: call provider.read_unit_window() and format response

4. Refactor `drill(ref)` with three-way dispatch:
   - LOCAL_ACTIVE: existing local drill path
   - LOCAL_INACTIVE: raise PermissionError
   - FEDERATED_ONLY: call provider.read_unit_window() and format drill response

5. Add federated search integration to `_collect_candidate_pool`:
   - Call `_run_federated_engine` from Plan 02 for each configured provider
   - Include results in RRF fusion with local candidates

### Task 5: Live Container Smoke Test (Conditional Autonomous)

**Status:** Conditional on Task 0 preflight (Task 0 confirmed autonomous=true)

1. Restart docker compose dotmd
2. Issue MCP search call for known Telegram query
3. Verify one or more Telegram candidates returned with ref shape `telegram:dialog:<id>:message:<id>`
4. Call `read(ref)` and `drill(ref)` on returned ref
5. Verify round-trip succeeds with provider payload

## Deviations from Plan

None — plan executed exactly as written for completed tasks.

## Preflight Finding

**mcp-telegram search_messages endpoint PRESENT** — daemon at `/root/.local/state/mcp-telegram/daemon.sock` responds to structured `search_messages` requests. Task 5 autonomous flag resolved to `true`.

## Test Results Summary

**Current status:**
- All 49 telegram-related tests pass (16 in test_telegram_provider.py, 15 in test_telegram_ingestion.py, 8 in test_service_search.py, etc.)
- pyright clean on telegram_provider.py and service.py
- No regressions in existing filesystem tests
- Pre-existing failure in test_filesystem_unbind_rebind_hides_and_restores_search_read_without_tei (unrelated to Plan 03, affects Plan 27 binding logic, needs separate investigation)

## Next Steps (To Complete Plan 03)

1. Add failing tests for Tasks 3-4 (RED phase)
2. Implement federated routing in service.py (GREEN phase)
3. Add federated search call to `_collect_candidate_pool` (fan-out already implemented in Plan 02)
4. Run live smoke test (Task 5)
5. Create final SUMMARY and commit

## Architecture Notes

**Load-Bearing Invariants (Cycle-2 Fixes):**

- **D-LOCAL-FIRST-TG-READ (HIGH-7):** read()/drill() for Telegram refs check local store FIRST. Only refs with NO local presence route to provider. Refs with INACTIVE local binding raise PermissionError (Phase 27 gate preserved). This is the critical test: `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider`.

- **D-METADATA-WHITELIST (MEDIUM):** provider_metadata restricted to `{dialog_id, message_id, sender, sent_at, dialog_name}`. Phone numbers, auth tokens, session paths, API credentials explicitly forbidden.

- **D-RANK-ZERO-BASED (LOW):** source_native_rank is zero-based for all federated providers (documented in docs/source-adapter-architecture.md).

**Generic Contract Design:**

The Telegram federated contract is structured to be reusable for gmail/slack/notion sources without Plan 34 edits. Provider implementations add `search_native()` method; the ServiceSourceProvider facade handles routing and error attribution.
