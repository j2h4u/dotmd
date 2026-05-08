---
phase: "34"
plan: "03"
type: tdd
wave: 3
depends_on: ["34-01", "34-02"]
files_modified:
  - backend/src/dotmd/ingestion/telegram_provider.py
  - backend/src/dotmd/api/service.py
  - backend/src/dotmd/mcp_server.py
  - backend/tests/ingestion/test_telegram_provider.py
  - backend/tests/ingestion/test_telegram_ingestion.py
  - backend/tests/api/test_service_search.py
  - docs/source-adapter-architecture.md
  - docs/source-registry-airweave-mapping.md
  - docs/mcp-telegram-source-contract.md
autonomous: true
requirements: ["SEARCH-01", "SEARCH-04"]
requirements_addressed: ["SEARCH-01", "SEARCH-04"]
must_haves:
  truths:
    - "D-13: Federated candidates set can_read=True only when the provider exposes read_unit_window. read(ref) for a federated-only hit routes through the lifecycle bundle and provider's read_unit_window, not the local store."
    - "D-14: No on-demand materialization in Phase 34. can_materialize=False for all candidates. Trickle stays the single write path."
    - "D-15: When read(ref) for a federated-only hit cannot reach the provider, the read returns a clear provider-attributed error with the same source-status attribution as search."
    - "D-16: Phase 34 proves the contract end-to-end with mcp-telegram's SearchMessages. Telegram candidates carry ref=telegram:dialog:<id>:message:<id> and round-trip through read(ref) (live read_unit_window) and drill(ref) without local indexing."
    - "D-17: dotMD never owns the Telegram client. All Telegram FTS, message fetch, and metadata access goes through the existing mcp-telegram daemon socket. The Phase 33 lifecycle bundle is the construction boundary."
    - "D-18: The contract must be generic enough that gmail/slack/notion/voicenotes federated sources land later through descriptor + provider-implementation work only, with no Phase 34 contract edits."
---

# Phase 34 Plan 03: Telegram Federated Proof And Read/Drill Round-trip

<objective>
Implement `search_native` on the Telegram provider, extend the daemon-socket
client and protocol with a `search_messages` method, route `read(ref)` and
`drill(ref)` for federated-only Telegram refs through the lifecycle
bundle's `read_unit_window`, and prove end-to-end round-trip with a
`FakeTelegramSourceClient` returning realistic FTS payloads. The plan also
documents the mcp-telegram daemon coordination state and ships a
container-restart smoke task at the end.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Federated `read(ref)` hits the local store and 404s | HIGH | `service.read(ref)` for any ref the provider's daemon can resolve via `read_unit_window` MUST take the provider path; integration test with non-indexed Telegram message ref pins this. |
| Daemon-down `read(ref)` returns ambiguous error | HIGH | Provider failure surfaces as `RuntimeError("telegram: ...")` with provider attribution; test pins error message shape. |
| Phase 27 active-binding gate blocks federated-only reads | HIGH | Federated-only refs never enter the binding gate; `_require_active_source_document` is bypassed when ref is federated-only. |
| `dotmd` unintentionally imports Telethon, opens Telegram API directly, or queries mcp-telegram's private SQLite | HIGH | Static scan asserts no `Telethon`, no direct Telegram API import, no `sqlite.*telegram` query in Phase 34 code paths. |
| Provider-side daemon `search_messages` method missing → live smoke fails | MEDIUM | Smoke task `autonomous: false` if endpoint absent. PR description includes the coordination decision. Coordination ticket / note added to mcp-telegram docs. |
| Federated candidates accidentally written into local index as side effect of `read(ref)` | HIGH | Test asserts no chunks/embeddings/FTS rows are added during a federated `read(ref)` call (count rows before/after). |
| `can_materialize=True` slips into Telegram candidates | MEDIUM | Sweep test in Plan 02 already pins this; Plan 03 keeps construction site explicit `can_materialize=False`. |
| Drill payload for federated-only ref returns malformed local-shaped fields | MEDIUM | Drill tests pin federated `total_chunks=0`, `frontmatter={}`, `parser_name="telegram-message"`. |
| Telegram message snippet length / framing breaks UI parsing | LOW | Snippet truncated at `snippet_length` from settings; existing tests in `test_telegram_ingestion.py` keep the expected shape. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add Telegram federated provider tests first</name>
<title>Add Telegram federated provider tests first</title>
<read_first>
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-RESEARCH.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-PATTERNS.md`
- `.planning/phases/34-federated-searchcandidate-contract/34-02-federated-fanout-and-source-status-PLAN.md`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `docs/mcp-telegram-source-contract.md`
</read_first>
<files>
- `backend/tests/ingestion/test_telegram_provider.py`
</files>
<action>
Add fixture and tests pinning the Telegram federated contract.

Reuse / extend the existing `FakeTelegramSourceClient` test fixture
(located alongside Phase 29 tests). Extend it with:

- `def search_messages(self, query: str, limit: int, dialog_id: int | None = None) -> dict`
  returning a configurable payload of shape:
  ```json
  {
    "hits": [
      {
        "dialog_id": 12345,
        "dialog_name": "Project Chat",
        "message_id": 67,
        "text": "...",
        "sender": "alice",
        "sent_at": "2026-04-12T08:11:00+00:00",
        "score": 0.93
      }
    ]
  }
  ```

Add tests in `backend/tests/ingestion/test_telegram_provider.py`:

- `test_telegram_source_client_protocol_includes_search_messages` — asserts
  `TelegramSourceClientProtocol` defines `search_messages`. Use
  `typing.get_type_hints` or `inspect.signature` to confirm the method
  exists with arguments `(query, limit, dialog_id=None)`.
- `test_unix_socket_search_messages_request_shape` — patches
  `_request` on `UnixSocketTelegramSourceClient` to capture payloads;
  calls `client.search_messages("kantine", limit=20)`; asserts captured
  payload equals
  `{"method": "search_messages", "query": "kantine", "limit": 20}`.
  Also calls with `dialog_id=42`; asserts payload includes
  `"dialog_id": 42`.
- `test_search_native_returns_searchcandidate_list` — wraps
  `FakeTelegramSourceClient` (with three seeded hits) in
  `TelegramApplicationSourceProvider`; calls `provider.search_native(
  "kantine", limit=10)`; asserts:
  - `len(result) == 3`.
  - Each candidate has
    `ref == f"telegram:dialog:{dialog_id}:message:{message_id}"`.
  - `c.namespace == "telegram"`, `c.source_kind == "chat"`,
    `c.retrieval_kind == "tg:fts"`.
  - `c.title == "Project Chat"`.
  - `c.snippet` is non-empty and starts with the message text.
  - `c.can_read is True`, `c.can_materialize is False`.
  - `c.source_native_score == 0.93` for the first hit.
  - `c.source_native_rank == 0` for the first hit, `1` for the second,
    `2` for the third.
  - `c.provider_metadata` is a dict containing
    `"dialog_id"`, `"message_id"`, `"sender"`, `"sent_at"`.
- `test_search_native_handles_empty_hits` — fake client returns
  `{"hits": []}`; assert `provider.search_native("foo", 10) == []`.
- `test_search_native_propagates_daemon_failure` — fake client raises
  `RuntimeError("Telegram daemon request failed: bad query")`; assert the
  exception bubbles unchanged out of `search_native` (the fan-out helper
  in Plan 02 catches this and reports `source_status="error"`).

Tests must fail before task 2.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_telegram_provider.py` contains the five
  tests named above.
- `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q` exits non-zero before task 2 (`search_messages` / `search_native` not implemented yet).
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q -k 'search_messages or search_native'`
</verify>
<done>
Telegram federated provider tests exist and fail only for missing
implementation.
</done>
</task>

<task id="2" type="tdd">
<name>Implement Telegram search_native + daemon socket search_messages method</name>
<title>Implement Telegram search_native + daemon socket search_messages method</title>
<read_first>
- `backend/tests/ingestion/test_telegram_provider.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/ingestion/source_provider.py`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/core/config.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/telegram_provider.py`
</files>
<action>
Extend `backend/src/dotmd/ingestion/telegram_provider.py` to implement
the federated search path.

In `TelegramSourceClientProtocol` (Protocol class):

- Add method:
  ```python
  def search_messages(
      self,
      query: str,
      limit: int,
      dialog_id: int | None = None,
  ) -> dict:
      """Search Telegram messages via daemon FTS. Returns {hits: [...]}"""
      ...
  ```

In `UnixSocketTelegramSourceClient`:

- Add method:
  ```python
  def search_messages(
      self,
      query: str,
      limit: int,
      dialog_id: int | None = None,
  ) -> dict:
      payload: dict = {
          "method": "search_messages",
          "query": query,
          "limit": limit,
      }
      if dialog_id is not None:
          payload["dialog_id"] = dialog_id
      return self._request(payload)
  ```

In `TelegramApplicationSourceProvider`:

- Add method (synchronous; the Plan 02 fan-out helper wraps in
  `asyncio.to_thread`):
  ```python
  def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
      payload = self._client.search_messages(query=query, limit=limit)
      hits = payload.get("hits", [])
      candidates: list[SearchCandidate] = []
      for rank, hit in enumerate(hits):
          dialog_id = _coerce_int(hit["dialog_id"])
          message_id = _coerce_int(hit["message_id"])
          ref = f"telegram:dialog:{dialog_id}:message:{message_id}"
          text = str(hit.get("text", ""))
          candidates.append(SearchCandidate(
              ref=ref,
              namespace="telegram",
              source_kind="chat",
              retrieval_kind="tg:fts",
              title=hit.get("dialog_name"),
              snippet=text,
              fused_score=0.0,
              can_read=True,
              can_materialize=False,
              source_native_score=hit.get("score"),
              source_native_rank=rank,
              provider_metadata={
                  "dialog_id": dialog_id,
                  "message_id": message_id,
                  "sender": hit.get("sender"),
                  "sent_at": hit.get("sent_at"),
                  "dialog_name": hit.get("dialog_name"),
              },
          ))
      return candidates
  ```

Implementation rules:
- Do NOT import `Telethon`, `telethon`, or any direct Telegram API
  client.
- Do NOT read SQLite from mcp-telegram.
- Do NOT add any helper that bypasses the daemon socket — every call goes
  through `self._client`.

mcp-telegram daemon coordination note (record outcome here in PR
description):
- If the mcp-telegram daemon already exposes `search_messages` as a
  socket method, mark Plan 03 task 5 (live smoke) `autonomous: true`.
- If it does not, the live smoke task is `autonomous: false` and a
  follow-up coordination item is filed in dotMD GSD backlog (NOT in beads,
  per project memory). dotMD-side Plan 03 still ships unblocked because
  unit/integration tests use `FakeTelegramSourceClient`.
- Investigate `/opt/docker/mcp-telegram/` source as part of this task to
  determine state. Record finding in the commit message.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/telegram_provider.py` `TelegramSourceClientProtocol` declares `def search_messages`.
- `backend/src/dotmd/ingestion/telegram_provider.py` `UnixSocketTelegramSourceClient.search_messages` issues a `{"method": "search_messages"}` daemon request.
- `backend/src/dotmd/ingestion/telegram_provider.py` `TelegramApplicationSourceProvider.search_native` returns `list[SearchCandidate]`.
- `backend/src/dotmd/ingestion/telegram_provider.py` does NOT contain `Telethon` or `telethon`.
- `backend/src/dotmd/ingestion/telegram_provider.py` does NOT contain direct sqlite cursors over mcp-telegram tables.
- `cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_telegram_provider.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_telegram_provider.py -q`
`cd backend && uv run pyright src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_telegram_provider.py`
`rg -n 'Telethon|from telethon' backend/src/dotmd/ingestion/telegram_provider.py` returns no matches.
`rg -n 'sqlite.*telegram' backend/src/dotmd/ingestion/telegram_provider.py` returns no matches.
</verify>
<done>
Telegram provider exposes `search_native` end-to-end, routed through the
daemon socket; no direct Telegram API import or private SQLite access.
</done>
</task>

<task id="3" type="tdd">
<name>Add federated read/drill round-trip tests first</name>
<title>Add federated read/drill round-trip tests first</title>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/api/test_service_search.py`
</read_first>
<files>
- `backend/tests/ingestion/test_telegram_ingestion.py`
- `backend/tests/api/test_service_search.py`
</files>
<action>
Add tests pinning federated read/drill semantics.

In `backend/tests/ingestion/test_telegram_ingestion.py`:

- `test_federated_only_message_round_trip` — set up `DotMDService` with a
  Telegram lifecycle bundle backed by `FakeTelegramSourceClient`. The
  fake client's `search_messages` returns one hit at
  `telegram:dialog:42:message:99`. The fake client's
  `read_source_unit_window` returns a window with the corresponding unit.
  Run `service.search("kantine")` → assert one Telegram candidate.
  Then `service.read("telegram:dialog:42:message:99")` → assert the
  returned text matches the daemon payload (the federated read path).
  Assert NO row was inserted into `chunks_*` during the round trip
  (count rows before/after).
- `test_federated_drill_returns_provider_metadata` — same setup;
  `service.drill("telegram:dialog:42:message:99")` returns `DrillPayload`
  with `title=dialog_name`, `total_chunks=0`,
  `parser_name="telegram-message"`, `frontmatter={}`,
  `target_metadata={...}` populated from the unit window.
- `test_federated_read_provider_down_attribution` — fake client
  `read_source_unit_window` raises `RuntimeError("Telegram daemon request
  failed: socket disconnected")`. Assert
  `service.read("telegram:dialog:42:message:99")` raises `RuntimeError`
  whose message contains `"telegram"` (provider-attributed) and the
  underlying daemon failure text.
- `test_federated_read_does_not_invoke_active_binding_gate` — assert
  reading a federated-only Telegram ref does NOT call
  `_require_active_source_document` (mock that helper; assert call_count
  zero for the federated path). Local-ref read continues to call it
  (regression).

In `backend/tests/api/test_service_search.py`:

- `test_telegram_federated_engine_participates` — `DotMDService` with a
  configured Telegram lifecycle bundle; `service.search("kantine")`
  returns a `SearchResponse` whose `source_status` includes an entry with
  `name="tg:fts"` and `status="ok"`.
- `test_phase_34_candidates_never_materializable` — for any synthetic
  search result mix (local + federated), every
  `candidate.can_materialize is False`.
- `test_provider_metadata_is_treated_as_opaque` — federated candidate's
  `provider_metadata` is a dict; the response envelope serialization
  preserves it round-trip; type stays `dict[str, Any] | None`.
- `test_no_local_index_writes_during_federated_search` — count rows in
  `chunks_*` and the FTS5 table before and after a federated search; the
  counts MUST be identical.

Tests must fail before task 4.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_telegram_ingestion.py` contains the four
  federated round-trip tests above.
- `backend/tests/api/test_service_search.py` contains
  `test_telegram_federated_engine_participates`,
  `test_phase_34_candidates_never_materializable`,
  `test_provider_metadata_is_treated_as_opaque`,
  `test_no_local_index_writes_during_federated_search`.
- `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q -k 'federated'` exits non-zero before task 4 (read/drill federated routing not implemented yet).
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q -k 'federated or phase_34_candidates'`
</verify>
<done>
Federated read/drill and round-trip tests exist and fail only for missing
implementation.
</done>
</task>

<task id="4" type="tdd">
<name>Route read(ref) and drill(ref) for federated-only Telegram refs through provider</name>
<title>Route read(ref) and drill(ref) for federated-only Telegram refs through provider</title>
<read_first>
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/ingestion/telegram_provider.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/tests/ingestion/test_telegram_ingestion.py`
</read_first>
<files>
- `backend/src/dotmd/api/service.py`
</files>
<action>
Update `DotMDService.read` and `DotMDService.drill` to dispatch
federated-only Telegram refs through the lifecycle bundle's provider
without calling the active-binding gate.

In `service.py`:

- Refactor `read`:
  ```python
  def read(self, ref: str, start: int = 0, end: int | None = None) -> ReadPayload:
      if _is_telegram_message_ref(ref):
          return self._read_telegram_via_provider(ref, start, end)
      document = self._require_active_source_document(ref)
      ...  # existing local path unchanged
  ```
  - `_is_telegram_message_ref(ref)` already exists (lines 129-131).
- Refactor `drill`:
  ```python
  def drill(self, ref: str) -> DrillPayload:
      if _is_telegram_message_ref(ref):
          return self._drill_telegram_via_provider(ref)
      document = self._require_active_source_document(ref)
      ...
  ```

- New helper `_read_telegram_via_provider(ref, start, end) -> ReadPayload`:
  - Resolve the lifecycle bundle for namespace `telegram`. If absent,
    raise `RuntimeError("telegram: no lifecycle bundle configured")`.
  - Resolve the provider — if `bundle.provider is None` or it lacks
    `read_unit_window`, raise
    `RuntimeError("telegram: provider does not support read_unit_window")`.
  - Parse `document_ref, unit_ref = _parse_telegram_message_ref(ref)`.
  - Call `provider.read_unit_window(unit_ref, before=0, after=0)` wrapped
    in try/except. On `RuntimeError` propagate as
    `RuntimeError(f"telegram: {original_msg}")` to give consistent
    provider-attributed error shape (D-15).
  - Build the `ReadPayload` from the returned window. The payload mirrors
    the existing `_read_telegram_message` shape (which already routes to
    the provider for indexed Telegram refs); the federated path may reuse
    that helper directly if it does not depend on local provenance.
  - **Critically**, do NOT call `self._require_active_source_document` on
    the federated path. Active-binding gate is local-store-only.

- New helper `_drill_telegram_via_provider(ref) -> DrillPayload`:
  - Same resolution as above, then build a `DrillPayload` using the
    Telegram document/unit metadata. Reuse the existing
    `_drill_telegram_message` logic where possible (it already routes
    through `self._telegram_provider.read_unit_window`).
  - Set `total_chunks=0`, `frontmatter={}`,
    `parser_name="telegram-message"`,
    `document_type="dialog"` (matching mcp-telegram-source-contract.md).
  - On daemon failure: `RuntimeError(f"telegram: {original_msg}")`.

Critical: the `_telegram_provider` attribute that
`_read_telegram_message` / `_drill_telegram_message` currently use must
be sourced from the lifecycle bundle (Plan 02 caches bundles at
`self._lifecycle_bundles["telegram"]`). The existing
`_build_telegram_provider()` helper (which Plan 33 already migrated to
lifecycle) returns the same provider — Plan 03 must verify that
`self._telegram_provider` is set from `self._lifecycle_bundles["telegram"]`
during `__init__`, not constructed independently.

If duplication exists, consolidate so the federated-only and ingested
paths share one provider object — both go through the same socket.
</action>
<acceptance_criteria>
- `backend/src/dotmd/api/service.py` `read` dispatches Telegram refs
  through the new federated helper without calling
  `_require_active_source_document`.
- `backend/src/dotmd/api/service.py` `drill` does the same.
- `backend/src/dotmd/api/service.py` `_read_telegram_via_provider` and
  `_drill_telegram_via_provider` exist (or `_read_telegram_message` and
  `_drill_telegram_message` are refactored to be the federated path).
- `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/api/service.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py` exits 0.
- `rg -n 'self\._telegram_provider' backend/src/dotmd/api/service.py` shows the provider attribute is initialized from `self._lifecycle_bundles` (or via Phase 33 lifecycle factory).
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q`
`cd backend && uv run pyright src/dotmd/api/service.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py`
`rg -n '_require_active_source_document' backend/src/dotmd/api/service.py | grep -v 'def _require_active'` — assert call sites only happen on the local path; no call on the Telegram federated branch.
</verify>
<done>
`read(ref)` / `drill(ref)` for federated-only Telegram refs route through
the provider; active-binding gate is bypassed for the federated path;
errors are provider-attributed.
</done>
</task>

<task id="5" type="standard">
<name>Update docs and run live container smoke</name>
<title>Update docs and run live container smoke</title>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-registry-airweave-mapping.md`
- `docs/mcp-telegram-source-contract.md`
- `backend/src/dotmd/api/service.py`
- `backend/src/dotmd/mcp_server.py`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/source-registry-airweave-mapping.md`
- `docs/mcp-telegram-source-contract.md`
</files>
<action>
Update three docs and run the live container smoke.

`docs/source-adapter-architecture.md`:
- Add a "Phase 34 Federated Search" section describing:
  - `SearchCandidate` / `SearchResponse` / `SourceStatus` envelope.
  - Always-on fan-out across `FEDERATED_SEARCH`-capable bundles.
  - Per-source soft timeout (4s default) and soft-skip semantics.
  - Federated `read(ref)` routing through `read_unit_window` without local
    indexing.
  - Mark `can_materialize=False` as the Phase 34 invariant; materialization
    deferred.
  - Document the `tg:fts` engine name convention; future federated engines
    follow `<namespace>:<retrieval_kind>` shape.

`docs/source-registry-airweave-mapping.md`:
- Mark `federated_search` capability as Phase 34 implemented for
  `telegram`. Note the lifecycle bundle's `supports_federated_search`
  helper as the discovery mechanism.

`docs/mcp-telegram-source-contract.md`:
- Add a "Federated FTS Search (Phase 34)" section describing:
  - The `search_messages` daemon socket method shape:
    request: `{"method": "search_messages", "query": "...", "limit": 20,
    "dialog_id": null}`; response:
    `{"ok": true, "data": {"hits": [{"dialog_id": ..., "message_id": ...,
    "text": ..., "score": ..., "sender": ..., "sent_at": ...,
    "dialog_name": ...}]}}`.
  - Note: this section reflects the **dotMD-side expectation**. If the
    mcp-telegram daemon does not yet expose `search_messages`, the
    coordination item is recorded in the dotMD backlog (no beads ticket
    per project memory).

Live container smoke (operator step — `autonomous: false` if mcp-telegram
daemon `search_messages` endpoint is not available):

1. `docker compose restart dotmd` (bind-mounted source — no rebuild).
2. From a host shell:
   ```bash
   uv run python -m mcp.client.stdio_test --command "docker exec -i dotmd dotmd mcp" \
     --tool search --args '{"query": "kantine", "top_k": 5}'
   ```
   (or equivalent MCP test harness already used for Phase 33 smoke.)
3. Confirm the response shape: `{"results": [...], "source_status":
   [{"name": "semantic", ...}, {"name": "keyword", ...},
   {"name": "graph_direct", ...}, {"name": "tg:fts", ...}]}`.
4. If at least one Telegram ref appears in `results`, run
   `read(ref)` on that ref and confirm the daemon-sourced text comes
   back without a local-index 404.
5. If `tg:fts` reports `status="error"` because the daemon endpoint is
   absent, mark the smoke task complete with `autonomous: false` and
   record the coordination follow-up in the PR description.

If the smoke fails because of a real bug (not a missing daemon endpoint),
file a Phase 34 bug, do NOT mark this task done.
</action>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains a "Phase 34" or
  "Federated Search" heading describing the SearchCandidate envelope and
  fan-out.
- `docs/source-registry-airweave-mapping.md` marks `federated_search` as
  implemented for `telegram`.
- `docs/mcp-telegram-source-contract.md` documents the `search_messages`
  daemon-socket contract.
- Live container smoke: either passes end-to-end (daemon endpoint
  present), or completes with `autonomous: false` and a coordination
  follow-up recorded in the PR description (daemon endpoint absent).
- Full Phase 34 verification suite passes:
  `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/mcp/test_mcp_search_envelope.py -q` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/mcp/test_mcp_search_envelope.py -q`
`cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/config.py src/dotmd/search/fusion.py src/dotmd/search/federated.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/telegram_provider.py tests/`
`grep -E 'Phase 34|Federated Search' docs/source-adapter-architecture.md`
Live MCP smoke (operator-driven) — see action steps.
</verify>
<done>
Docs reflect Phase 34 federated contract; the live container smoke either
passed end-to-end or recorded the daemon-coordination follow-up.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/core/test_search_candidate.py tests/search/test_fusion.py tests/search/test_federated.py tests/api/test_service_search.py tests/ingestion/test_telegram_provider.py tests/ingestion/test_telegram_ingestion.py tests/mcp/test_mcp_search_envelope.py -q`
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/config.py src/dotmd/search/fusion.py src/dotmd/search/federated.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/telegram_provider.py tests/`
- `rg -n 'Telethon|from telethon|sqlite.*telegram' backend/src/dotmd/ingestion/telegram_provider.py` returns no matches.
- `rg -n 'class SearchResult\b|from dotmd\.core\.models import.*SearchResult' backend/src` returns no matches.
- `rg -n 'FederatedSearchError' backend/src/dotmd/search backend/src/dotmd/api` returns no matches.
- `rg -n 'can_materialize\s*=\s*True' backend/src/dotmd` returns no matches.
- Live MCP smoke (operator) — passes or records coordination follow-up.
</verification>

<success_criteria>
- SEARCH-04 has end-to-end proof: mcp-telegram FTS produces
  `SearchCandidate` records with `ref=telegram:dialog:<id>:message:<id>`
  that round-trip through `read(ref)` and `drill(ref)`.
- D-13, D-14, D-15 behaviors are pinned: federated `read(ref)` uses
  `read_unit_window`, never materializes, and provider failures attribute
  via `RuntimeError("telegram: ...")`.
- D-17 invariant preserved: dotMD owns no Telegram client; all access
  goes through the existing daemon socket.
- D-18 generic-enough invariant validated: adding Telegram as the second
  federated provider (after the Plan 02 stub) required ZERO edits to
  `SearchCandidate`, `SearchResponse`, `fanout_search`, or
  `FederatedSearchProviderProtocol`. Future gmail/slack/notion lands the
  same way.
- mcp-telegram daemon coordination state recorded in PR description.
</success_criteria>
