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
autonomous: conditional
autonomous_resolution: |
  Tasks 0 (preflight), 1, 2, 3, 4 are autonomous. Task 5 (live container
  smoke) resolves to autonomous=true ONLY IF preflight (Task 0) confirms
  mcp-telegram daemon exposes search_messages. Otherwise Task 5 runs as
  autonomous=false (operator-driven) and a coordination follow-up is
  recorded in the dotMD GSD backlog. (cycle-2 HIGH-8 fix)
requirements: ["SEARCH-01", "SEARCH-04"]
requirements_addressed: ["SEARCH-01", "SEARCH-04"]
must_haves:
  truths:
    - "D-13: Federated candidates set can_read=True only when the provider exposes read_unit_window. Plan 34-03 derives can_read from a runtime capability check on the provider, not a hard-coded literal. (cycle-2 MEDIUM fold-in)"
    - "D-14: No on-demand materialization in Phase 34. can_materialize=False for all candidates. Trickle stays the single write path."
    - "D-15: When read(ref) for a federated-only hit cannot reach the provider, the read returns a clear provider-attributed error with the same source-status attribution as search."
    - "D-16: Phase 34 proves the contract end-to-end with mcp-telegram's SearchMessages. Telegram candidates carry ref=telegram:dialog:<id>:message:<id> and round-trip through read(ref) (live read_unit_window) and drill(ref) without local indexing."
    - "D-17: dotMD never owns the Telegram client. All Telegram FTS, message fetch, and metadata access goes through the existing mcp-telegram daemon socket. The Phase 33 lifecycle bundle is the construction boundary."
    - "D-18: The contract must be generic enough that gmail/slack/notion/voicenotes federated sources land later through descriptor + provider-implementation work only, with no Phase 34 contract edits."
    - "D-LOCAL-FIRST-TG-READ: read()/drill() for Telegram refs check the local store FIRST. If a Telegram document exists locally with an ACTIVE binding, it routes through the local read path. If it exists locally but binding is INACTIVE, the call raises PermissionError — does NOT fall through to the federated provider. Only refs with NO local-store presence at all route to the federated provider. This preserves the Phase 27 active-binding gate for locally-backed Telegram refs. (cycle-2 HIGH-7 fix)"
    - "D-RANK-ZERO-BASED: source_native_rank is zero-based for all federated providers. Documented in plan and in docs/source-adapter-architecture.md. (cycle-2 MEDIUM fold-in)"
    - "D-METADATA-WHITELIST: provider_metadata for Telegram is restricted to {dialog_id, message_id, sender, sent_at, dialog_name}. Phone numbers, session paths, auth tokens are explicitly forbidden. Negative test pins this. (cycle-2 MEDIUM fold-in)"
    - "D-PREFLIGHT: Live container smoke is conditional on out-of-repo mcp-telegram search_messages endpoint. Task 0 inspects the daemon source and resolves task 5's autonomous flag. (cycle-2 HIGH-8 fix)"
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
| Phase 27 active-binding gate blocks federated-only reads | HIGH | Federated-only refs (NO local-store presence at all) bypass `_require_active_source_document`. **Locally-indexed-but-inactive** Telegram refs do NOT bypass — they raise `PermissionError`. (cycle-2 HIGH-7 fix) |
| Inactive locally-indexed Telegram ref bypasses Phase 27 binding gate via federated fallback | HIGH | Routing logic checks local store FIRST: active local doc → local path; inactive local doc → PermissionError; absent from local → federated provider. Test `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider` mocks the provider and asserts `read_unit_window` call_count == 0 for inactive locally-indexed refs. (cycle-2 HIGH-7 fix) |
| Live container smoke marked autonomous=true masks out-of-repo dependency | HIGH | Plan-level `autonomous: conditional`; Task 0 (preflight) inspects `/opt/docker/mcp-telegram/` source for `search_messages` endpoint and resolves Task 5's autonomous flag. If endpoint absent, Task 5 runs as `autonomous: false` and coordination follow-up filed in dotMD GSD backlog. (cycle-2 HIGH-8 fix) |
| `can_read=True` hard-coded; future provider without read_unit_window misrepresents capability | MEDIUM | `can_read` derived at construction time from a runtime check on the provider object: `callable(getattr(bundle.provider, "read_unit_window", None))`. Test asserts a stub provider without `read_unit_window` produces candidates with `can_read=False`. (cycle-2 MEDIUM fold-in) |
| `provider_metadata` leaks credentials, phone numbers, session paths | MEDIUM | Whitelist enforced at construction: only `{dialog_id, message_id, sender, sent_at, dialog_name}` are allowed. Negative test asserts `phone`, `auth_token`, `session_path`, `api_id`, `api_hash` keys NEVER appear in any candidate's `provider_metadata`. (cycle-2 MEDIUM fold-in) |
| `source_native_rank` indexing convention undocumented | LOW | Phase 34 fixes rank as zero-based for all federated providers. Documented in `docs/source-adapter-architecture.md` Phase 34 section. Test pins ranks `[0, 1, 2]` for a 3-hit response. |
| `dotmd` unintentionally imports Telethon, opens Telegram API directly, or queries mcp-telegram's private SQLite | HIGH | Static scan asserts no `Telethon`, no direct Telegram API import, no `sqlite.*telegram` query in Phase 34 code paths. |
| Provider-side daemon `search_messages` method missing → live smoke fails | MEDIUM | Smoke task `autonomous: false` if endpoint absent. PR description includes the coordination decision. Coordination ticket / note added to mcp-telegram docs. |
| Federated candidates accidentally written into local index as side effect of `read(ref)` | HIGH | Test asserts no chunks/embeddings/FTS rows are added during a federated `read(ref)` call (count rows before/after). |
| `can_materialize=True` slips into Telegram candidates | MEDIUM | Sweep test in Plan 02 already pins this; Plan 03 keeps construction site explicit `can_materialize=False`. |
| Drill payload for federated-only ref returns malformed local-shaped fields | MEDIUM | Drill tests pin federated `total_chunks=0`, `frontmatter={}`, `parser_name="telegram-message"`. |
| Telegram message snippet length / framing breaks UI parsing | LOW | Snippet truncated at `snippet_length` from settings; existing tests in `test_telegram_ingestion.py` keep the expected shape. |
</threat_model>

<tasks>
<task id="0" type="standard">
<name>Preflight — verify mcp-telegram daemon search_messages endpoint</name>
<title>Preflight — verify mcp-telegram daemon search_messages endpoint</title>
<read_first>
- `/opt/docker/mcp-telegram/AGENTS.md` (project notes for mcp-telegram)
- `/opt/docker/mcp-telegram/` (source files — read-only inspection)
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md`
</read_first>
<files>
- `.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md` (output written here)
</files>
<action>
**Cycle-2 HIGH-8 fix.** Determine whether the mcp-telegram daemon already
exposes `search_messages` as a socket method, and resolve Task 5's
`autonomous` flag accordingly.

Steps:

1. Inspect `/opt/docker/mcp-telegram/` source files (read-only). Look for
   any of:
   - A method named `search_messages` registered with the daemon socket
     dispatcher.
   - Documentation in `/opt/docker/mcp-telegram/AGENTS.md` or
     `/opt/docker/mcp-telegram/README.md` mentioning `search_messages`.
   - A schema or routing table that lists supported daemon methods.
2. Optionally probe the live daemon socket if it's already running:
   ```bash
   docker exec mcp-telegram /bin/sh -c \
     'echo "{\"method\":\"search_messages\",\"query\":\"test\",\"limit\":1}" | \
      nc -U /var/run/mcp-telegram.sock'
   ```
   - If the daemon responds with a structured `{"ok": true, "data": {...}}`
     or even a structured error like `{"ok": false, "error": "..."}`,
     the endpoint exists.
   - If the daemon responds with `unknown method` or similar, the endpoint
     is absent.
   - If the socket path is different, locate the actual socket via
     `/opt/docker/mcp-telegram/` config and adapt.
3. Write findings to
   `.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md`
   with frontmatter:
   ```yaml
   ---
   preflight: search_messages
   resolved: <ISO-8601 timestamp>
   endpoint_present: <true|false>
   evidence: |
     <2-3 line summary of what was inspected>
   ---
   ```
   Plus a paragraph explaining what was found and where.
4. **Resolve Task 5 autonomous flag:**
   - If `endpoint_present=true`: Task 5 stays `autonomous: true`.
   - If `endpoint_present=false`: Task 5 changes to `autonomous: false`
     before execution; an entry is added to the dotMD GSD backlog (NOT
     beads — per project memory `feedback_no_beads.md`) titled "Coordinate
     mcp-telegram `search_messages` endpoint" with a brief description and
     a link back to this preflight file.
5. The dotMD-side Plan 34-03 implementation tasks (1, 2, 3, 4) proceed
   regardless — they use `FakeTelegramSourceClient` for unit/integration
   coverage, which is independent of the live daemon. Only Task 5 (live
   smoke) depends on the daemon endpoint.

This task is `autonomous: true` — it's a read-only inspection of files the
dotmd container has access to plus an optional probe of an already-running
daemon socket.
</action>
<acceptance_criteria>
- `.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md` exists with the structured frontmatter shown above.
- `endpoint_present` field is either `true` or `false` (not missing or
  ambiguous).
- If `endpoint_present=false`, a backlog entry is recorded in
  `.planning/BACKLOG.md` (or wherever GSD backlog lives in this repo)
  with the coordination follow-up. (`rg -n 'mcp-telegram.*search_messages'
  .planning/BACKLOG.md` returns at least one match.)
- Task 5's `autonomous` field in this PLAN.md is updated to match the
  preflight finding before Task 5 begins execution.
</acceptance_criteria>
<verify>
`test -f .planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md`
`grep -E '^endpoint_present:\s*(true|false)' .planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md`
</verify>
<done>
Daemon endpoint presence resolved; Task 5's autonomous flag set
accordingly; coordination follow-up filed if endpoint absent.
</done>
</task>

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
  - `c.namespace == "telegram"`, `c.descriptor_key == "telegram"`,
    `c.source_kind == "chat"`, `c.retrieval_kind == "tg:fts"`.
    (descriptor_key new per cycle-2 HIGH-1)
  - `c.title == "Project Chat"`.
  - `c.snippet` is non-empty and starts with the message text.
  - `c.can_read is True` (derived — provider has `read_unit_window`),
    `c.can_materialize is False`.
  - `c.source_native_score == 0.93` for the first hit.
  - `c.source_native_rank == 0` for the first hit, `1` for the second,
    `2` for the third (zero-based per D-RANK-ZERO-BASED).
  - `c.provider_metadata` is a dict whose keys are EXACTLY a subset of
    `{"dialog_id", "message_id", "sender", "sent_at", "dialog_name"}`
    (D-METADATA-WHITELIST).
- `test_search_native_can_read_derived_from_provider_capability` (**cycle-2
  MEDIUM fold-in for can_read derivation**) — construct a stub provider
  whose object does NOT have a `read_unit_window` attribute (delete it
  via `del fake._client.read_source_unit_window` or use a lighter stub);
  call `provider.search_native("foo", 10)`; assert every candidate has
  `c.can_read is False`. Then add `read_unit_window` back; assert
  `c.can_read is True`. Pins that `can_read` is a runtime capability
  check, not a hard-coded literal.
- `test_search_native_provider_metadata_whitelist` (**cycle-2 MEDIUM
  fold-in**) — fake client returns hits that include EXTRA fields like
  `"phone_number": "+1234..."`, `"auth_token": "abc"`,
  `"session_path": "/tmp/x"`, `"api_id": 12345`, `"api_hash": "deadbeef"`.
  Call `provider.search_native("foo", 10)`. For every candidate, assert:
  - `c.provider_metadata` keys are EXACTLY a subset of
    `{"dialog_id", "message_id", "sender", "sent_at", "dialog_name"}`.
  - None of `{"phone_number", "auth_token", "session_path", "api_id",
    "api_hash"}` appear as keys in `c.provider_metadata`.
  Defense-in-depth: even if the daemon ever leaks credentials in its
  payload, the dotMD provider strips them before constructing the
  candidate.
- `test_search_native_source_native_rank_is_zero_based` (**cycle-2 MEDIUM
  fold-in**) — fake client returns 5 hits; assert
  `[c.source_native_rank for c in result] == [0, 1, 2, 3, 4]`. Pins the
  zero-based convention.
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

- Define a module-level constant for the metadata whitelist (cycle-2
  MEDIUM fold-in):
  ```python
  TELEGRAM_PROVIDER_METADATA_KEYS: frozenset[str] = frozenset({
      "dialog_id",
      "message_id",
      "sender",
      "sent_at",
      "dialog_name",
  })
  ```
- Add method (synchronous; the Plan 02 `_run_federated_engine` wraps in
  `asyncio.to_thread`):
  ```python
  def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
      payload = self._client.search_messages(query=query, limit=limit)
      hits = payload.get("hits", [])
      # cycle-2 MEDIUM fold-in: derive can_read from provider capability,
      # not a hard-coded True literal. Future providers without
      # read_unit_window emit candidates with can_read=False.
      can_read_local = callable(
          getattr(self._client, "read_source_unit_window", None),
      )
      candidates: list[SearchCandidate] = []
      for rank, hit in enumerate(hits):
          dialog_id = _coerce_int(hit["dialog_id"])
          message_id = _coerce_int(hit["message_id"])
          ref = f"telegram:dialog:{dialog_id}:message:{message_id}"
          text = str(hit.get("text", ""))
          # cycle-2 MEDIUM fold-in: whitelist provider_metadata keys to
          # prevent credentials/auth tokens from leaking into the public
          # contract.
          metadata = {
              key: hit[key]
              for key in TELEGRAM_PROVIDER_METADATA_KEYS
              if key in hit and hit[key] is not None
          }
          candidates.append(SearchCandidate(
              ref=ref,
              namespace="telegram",
              descriptor_key="telegram",  # cycle-2 HIGH-1
              source_kind="chat",
              retrieval_kind="tg:fts",
              title=hit.get("dialog_name"),
              snippet=text,
              fused_score=0.0,
              can_read=can_read_local,  # cycle-2 MEDIUM (derived)
              can_materialize=False,
              source_native_score=hit.get("score"),
              source_native_rank=rank,  # zero-based per D-RANK-ZERO-BASED
              provider_metadata=metadata or None,
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
- `backend/src/dotmd/ingestion/telegram_provider.py` defines
  `TELEGRAM_PROVIDER_METADATA_KEYS` whitelist (cycle-2 MEDIUM fold-in
  marker — `rg -n 'TELEGRAM_PROVIDER_METADATA_KEYS' backend/src/dotmd/ingestion/telegram_provider.py` returns matches).
- `backend/src/dotmd/ingestion/telegram_provider.py` `search_native`
  derives `can_read` from a runtime capability check on the client
  (cycle-2 MEDIUM marker — `rg -n 'callable\(getattr\(.*read_source_unit_window' backend/src/dotmd/ingestion/telegram_provider.py` returns matches).
- `backend/src/dotmd/ingestion/telegram_provider.py` `search_native`
  passes `descriptor_key="telegram"` to every constructed
  `SearchCandidate` (cycle-2 HIGH-1 marker — `rg -n 'descriptor_key="telegram"' backend/src/dotmd/ingestion/telegram_provider.py` returns matches).
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
  The local store has NO Telegram document for this ref (truly federated).
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
- `test_truly_federated_telegram_ref_routes_to_provider` (**cycle-2
  HIGH-7 fix — POSITIVE case**) — `service.read(ref)` for a Telegram ref
  with NO local-store presence at all. Mock `provider.read_unit_window`.
  Assert the provider WAS called once with the right unit_ref. Assert
  `_require_active_source_document` is NOT called (federated path bypasses
  the gate when ref is truly absent from local store).
- `test_inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider`
  (**cycle-2 HIGH-7 fix — CRITICAL NEGATIVE case**) — set up `DotMDService`
  where the local store contains a Telegram document for ref
  `telegram:dialog:42:message:99` BUT its source binding is INACTIVE
  (Phase 27 visibility gate semantics). Mock the Telegram provider's
  `read_unit_window`. Call `service.read("telegram:dialog:42:message:99")`.
  Assert:
  - The call raises `PermissionError` (or whatever error type the Phase
    27 gate raises today; if it's a different type like `LookupError`,
    pin THAT type — preserve existing semantics).
  - The provider's `read_unit_window` was NOT called (call_count == 0).
    The federated path MUST NOT be a fallback for inactive local refs.
  - This is the load-bearing test for cycle-2 HIGH-7. If this test fails,
    the active-binding gate is bypassed and Phase 27 invariant is broken.
- `test_active_locally_indexed_telegram_ref_uses_local_path` (**cycle-2
  HIGH-7 fix — POSITIVE local case**) — local store has the document
  with ACTIVE binding. Call `service.read(ref)`. Assert the provider's
  `read_unit_window` was NOT called (local path used). Assert
  `_require_active_source_document` WAS called and returned the local
  document.
- `test_federated_read_helper_naming` — verify the routing helper is
  named clearly:
  - `_resolve_telegram_read_path(ref) -> TelegramReadPath` returns one
    of: `LocalActive(document)`, `LocalInactive()`,
    `FederatedOnly()`. The `read()` and `drill()` methods dispatch on
    this enum. `rg -n 'TelegramReadPath\.|class TelegramReadPath\b'
    backend/src/dotmd/api/service.py` returns matches.

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
Update `DotMDService.read` and `DotMDService.drill` to use a
**local-first three-way routing** that preserves the Phase 27 active-binding
gate for locally-indexed Telegram refs (cycle-2 HIGH-7 fix).

In `service.py`:

- Add a small enum + helper to classify the routing path:
  ```python
  from enum import Enum
  from dataclasses import dataclass

  class TelegramReadPath(Enum):
      LOCAL_ACTIVE = "local_active"
      LOCAL_INACTIVE = "local_inactive"
      FEDERATED_ONLY = "federated_only"

  @dataclass(frozen=True)
  class _TelegramRouteResult:
      path: TelegramReadPath
      document: SourceDocument | None  # only set for LOCAL_ACTIVE

  def _resolve_telegram_read_path(self, ref: str) -> _TelegramRouteResult:
      """cycle-2 HIGH-7: classify a Telegram ref before dispatching read/drill.

      LOCAL_ACTIVE: ref exists in local store with an active binding.
                    → local read path (existing).
      LOCAL_INACTIVE: ref exists in local store but binding is inactive.
                      → MUST raise PermissionError; do NOT fall back to provider.
      FEDERATED_ONLY: ref has no local-store presence at all.
                      → federated provider path.
      """
      # Local-presence check independent of binding active-ness.
      doc = self._maybe_local_source_document(ref)  # returns None if not in local store
      if doc is None:
          return _TelegramRouteResult(TelegramReadPath.FEDERATED_ONLY, None)
      if not self._is_source_binding_active(doc):
          return _TelegramRouteResult(TelegramReadPath.LOCAL_INACTIVE, None)
      return _TelegramRouteResult(TelegramReadPath.LOCAL_ACTIVE, doc)
  ```
  - `_maybe_local_source_document(ref)` is a new helper that returns
    `None` if the ref has no local document, regardless of binding status.
    It does the same lookup as `_require_active_source_document` but
    without the binding gate and without raising when missing.
  - `_is_source_binding_active(doc)` wraps the existing Phase 27 binding
    check (use the same predicate `_require_active_source_document` uses
    internally; expose it as a separate helper to keep this routing
    function pure).
- Refactor `read` (cycle-2 HIGH-7 — local-first three-way dispatch):
  ```python
  def read(self, ref: str, start: int = 0, end: int | None = None) -> ReadPayload:
      if _is_telegram_message_ref(ref):
          route = self._resolve_telegram_read_path(ref)
          if route.path is TelegramReadPath.LOCAL_ACTIVE:
              # Phase 27 invariant — local read path with active binding.
              assert route.document is not None
              return self._read_local_telegram_chunks(route.document, start, end)
          if route.path is TelegramReadPath.LOCAL_INACTIVE:
              # Phase 27 invariant — must NOT fall through to provider.
              raise PermissionError(
                  f"Source ref {ref} exists locally but is not active",
              )
          # FEDERATED_ONLY — provider path.
          return self._read_telegram_via_provider(ref, start, end)
      document = self._require_active_source_document(ref)
      ...  # existing non-Telegram local path unchanged
  ```
- Refactor `drill` with the same three-way routing:
  ```python
  def drill(self, ref: str) -> DrillPayload:
      if _is_telegram_message_ref(ref):
          route = self._resolve_telegram_read_path(ref)
          if route.path is TelegramReadPath.LOCAL_ACTIVE:
              assert route.document is not None
              return self._drill_local_telegram_message(route.document)
          if route.path is TelegramReadPath.LOCAL_INACTIVE:
              raise PermissionError(
                  f"Source ref {ref} exists locally but is not active",
              )
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
  - **Critically**, this helper is reachable ONLY through the
    `FEDERATED_ONLY` branch above. It MUST NOT be called for
    `LOCAL_INACTIVE` refs — the routing function is the gate, and the
    HIGH-7 test pins this with a `read_unit_window` call_count assertion.

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
- `backend/src/dotmd/api/service.py` defines
  `class TelegramReadPath(Enum)` with values `LOCAL_ACTIVE`,
  `LOCAL_INACTIVE`, `FEDERATED_ONLY`. (cycle-2 HIGH-7 marker — `rg -n
  'class TelegramReadPath\b' backend/src/dotmd/api/service.py` returns
  matches.)
- `backend/src/dotmd/api/service.py` defines
  `_resolve_telegram_read_path(self, ref) -> _TelegramRouteResult`.
- `backend/src/dotmd/api/service.py` `read` and `drill` use the
  three-way routing: LOCAL_ACTIVE → local path; LOCAL_INACTIVE → raise
  PermissionError; FEDERATED_ONLY → provider path. (`rg -n
  'TelegramReadPath\.' backend/src/dotmd/api/service.py` returns matches
  in both `read` and `drill`.)
- `backend/src/dotmd/api/service.py` `_read_telegram_via_provider` and
  `_drill_telegram_via_provider` exist and are reachable ONLY from the
  FEDERATED_ONLY branch (no other call sites except tests).
- `backend/src/dotmd/api/service.py` defines
  `_maybe_local_source_document(self, ref)` (does NOT raise when ref
  absent) and `_is_source_binding_active(self, doc)` helpers used by
  `_resolve_telegram_read_path`.
- `cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/api/service.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py` exits 0.
- `rg -n 'self\._telegram_provider' backend/src/dotmd/api/service.py` shows the provider attribute is initialized from `self._lifecycle_bundles` (or via Phase 33 lifecycle factory).
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py -q`
`cd backend && uv run pyright src/dotmd/api/service.py tests/ingestion/test_telegram_ingestion.py tests/api/test_service_search.py`
`rg -n 'class TelegramReadPath\b' backend/src/dotmd/api/service.py` (must return matches — cycle-2 HIGH-7 marker)
`cd backend && uv run pytest tests/ingestion/test_telegram_ingestion.py -q -k 'inactive_locally_indexed_telegram_ref_does_not_fall_through_to_provider'` exits 0 (load-bearing HIGH-7 test).
`rg -n '_require_active_source_document' backend/src/dotmd/api/service.py | grep -v 'def _require_active'` — assert call sites only happen on the non-Telegram local path; the Telegram dispatcher uses `_resolve_telegram_read_path` instead.
</verify>
<done>
`read(ref)` / `drill(ref)` for federated-only Telegram refs route through
the provider; active-binding gate is bypassed for the federated path;
errors are provider-attributed.
</done>
</task>

<task id="5" type="standard">
<name>Update docs and run live container smoke (autonomous resolved by Task 0 preflight)</name>
<title>Update docs and run live container smoke (autonomous resolved by Task 0 preflight)</title>
<autonomous_note>
This task's autonomous flag is **conditional** on Task 0 (preflight)
findings. cycle-2 HIGH-8 fix:
- If `34-PREFLIGHT.md` reports `endpoint_present: true` →
  `autonomous: true` (run live smoke end-to-end).
- If `34-PREFLIGHT.md` reports `endpoint_present: false` →
  `autonomous: false` (operator-driven; coordination follow-up filed in
  dotMD GSD backlog before Task 5 is marked done).
The dotMD-side autonomous portions (docs updates, sub-steps 1-4) run
regardless; only the live MCP smoke depends on the daemon endpoint.
</autonomous_note>
<read_first>
- `.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md` (cycle-2 HIGH-8 — reads autonomous resolution from preflight)
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
  - Public `descriptor_key` field (cycle-2 HIGH-1) — distinct from
    `source_kind`; identifies the source descriptor uniquely.
  - Always-on fan-out across `FEDERATED_SEARCH`-capable bundles.
  - Local engines run sequentially within a request (cycle-2 HIGH-4
    D-LOCAL-SEQUENTIAL) AND are serialized across concurrent requests
    via a dedicated `ThreadPoolExecutor(max_workers=1)` named
    `dotmd-local-search` (cycle-4 HIGH D-LOCAL-SERIALIZED) — only
    federated providers fan out in parallel.
  - `search_async` is the canonical async public method; sync `search()`
    is a CLI/test wrapper that fails loudly inside a running event loop
    (cycle-2 HIGH-5 D-ASYNC-CANONICAL).
  - Per-source soft timeout (4s default) applies ONLY to federated
    providers; local engines have no soft timeout.
  - Lifecycle build failures per-source are caught and surfaced as
    persistent SourceStatus(status="error") — service init never crashes
    on a single misconfigured source (cycle-2 HIGH-6 D-LIFECYCLE-GRACEFUL).
  - **Federated `read(ref)` routing — local-first three-way dispatch
    (cycle-2 HIGH-7):**
    - LOCAL_ACTIVE: ref exists in local store with active binding →
      local read path.
    - LOCAL_INACTIVE: ref exists in local store, binding inactive →
      `PermissionError`. Phase 27 visibility gate is preserved.
    - FEDERATED_ONLY: ref absent from local store entirely → provider
      `read_unit_window`.
  - Mark `can_materialize=False` as the Phase 34 invariant; materialization
    deferred.
  - Document the `tg:fts` engine name convention; future federated engines
    follow `<namespace>:<retrieval_kind>` shape.
  - **`source_native_rank` is zero-based** for all federated providers.
    A 5-hit response carries ranks `[0, 1, 2, 3, 4]`. Documented as
    convention; code enforces (`enumerate(hits)`).

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
  - **`source_native_rank` is zero-based** — first hit has rank 0.
  - **`provider_metadata` whitelist** (cycle-2 MEDIUM fold-in): only
    `{dialog_id, message_id, sender, sent_at, dialog_name}` are surfaced.
    Phone numbers, auth tokens, session paths, api_id, api_hash MUST
    NEVER appear in `provider_metadata` even if the daemon ever leaks
    them in its payload — dotMD strips them at construction.
  - **Read routing local-first** (cycle-2 HIGH-7): dotMD checks the
    local store FIRST for any Telegram ref. Locally-indexed-but-inactive
    refs raise `PermissionError`; only refs absent from the local store
    route through `read_unit_window`.
  - Note: this section reflects the **dotMD-side expectation**. If the
    mcp-telegram daemon does not yet expose `search_messages`, the
    coordination item is recorded in the dotMD GSD backlog (no beads
    ticket per project memory `feedback_no_beads.md`). Task 0 (preflight)
    resolves this state before Task 5 begins.

Live container smoke — autonomous flag resolved from
`34-PREFLIGHT.md.endpoint_present` (cycle-2 HIGH-8 fix):

**Pre-execution gate:** Read `endpoint_present` from
`.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md`.
- `endpoint_present: true` → run live smoke as `autonomous: true`.
- `endpoint_present: false` → SKIP live MCP probe; mark Task 5 sub-step 5
  as `autonomous: false` and record coordination follow-up in dotMD GSD
  backlog. Task 5 is still considered done after sub-steps 1-4 (docs)
  and the backlog entry are recorded.
- If `34-PREFLIGHT.md` is missing entirely, abort Task 5 — Task 0 must
  run first.

Sub-steps (gated by preflight):

1. **(autonomous=true)** Update the three docs above.
2. **(autonomous=true regardless of endpoint)** `docker compose restart
   dotmd` (bind-mounted source — no rebuild).
3. **(conditional on endpoint_present=true)** From a host shell:
   ```bash
   uv run python -m mcp.client.stdio_test --command "docker exec -i dotmd dotmd mcp" \
     --tool search --args '{"query": "kantine", "top_k": 5}'
   ```
   (or equivalent MCP test harness already used for Phase 33 smoke.)
4. **(conditional)** Confirm the response shape: `{"candidates": [...],
   "source_status": [{"name": "semantic", ...}, {"name": "keyword", ...},
   {"name": "graph_direct", ...}, {"name": "tg:fts", ...}]}` (cycle-2
   HIGH-2 — `candidates` not `results`).
5. **(conditional)** If at least one Telegram ref appears in
   `candidates`, run `read(ref)` on that ref and confirm the
   daemon-sourced text comes back without a local-index 404. Also run
   `drill(ref)` and confirm the metadata payload.
6. **(autonomous=false fallback)** If `endpoint_present=false` from
   preflight: append a coordination entry to `.planning/BACKLOG.md`:
   ```markdown
   ## Coordinate mcp-telegram `search_messages` endpoint

   Phase 34 Plan 03 needs the mcp-telegram daemon to expose a
   `search_messages` daemon-socket method. dotMD-side implementation
   ships unblocked via `FakeTelegramSourceClient`, but live cross-repo
   smoke is gated on this endpoint. See
   `.planning/phases/34-federated-searchcandidate-contract/34-PREFLIGHT.md`
   for the preflight finding. Owner: operator decides — coordinate with
   `/opt/docker/mcp-telegram/` maintainer or build the endpoint locally.
   ```

If the live smoke fails because of a real bug (not a missing daemon
endpoint), file a Phase 34 bug, do NOT mark this task done.
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
  `SearchCandidate`, `SearchResponse`, `fanout_federated`, or
  `FederatedSearchProviderProtocol`. Future gmail/slack/notion lands the
  same way.
- **D-LOCAL-FIRST-TG-READ** (cycle-2 HIGH-7): Phase 27 active-binding
  gate is preserved for locally-indexed Telegram refs. Inactive locally-
  indexed refs raise `PermissionError`; only refs absent from the local
  store route to the federated provider.
- **D-RANK-ZERO-BASED** (cycle-2 MEDIUM): `source_native_rank` documented
  as zero-based; tests pin `[0, 1, 2, ...]` for federated responses.
- **D-METADATA-WHITELIST** (cycle-2 MEDIUM): Telegram `provider_metadata`
  restricted to `{dialog_id, message_id, sender, sent_at, dialog_name}`;
  negative test pins absence of credential fields.
- **D-PREFLIGHT** (cycle-2 HIGH-8): mcp-telegram daemon coordination
  state recorded in `34-PREFLIGHT.md`; Task 5's autonomous flag resolved
  from preflight finding before execution; coordination follow-up filed
  in dotMD GSD backlog if endpoint absent.
</success_criteria>
