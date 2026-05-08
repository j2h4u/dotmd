# Phase 34: Federated SearchCandidate contract - Pattern Map

**Generated:** 2026-05-08
**Status:** Complete

## Purpose

Map Phase 34 planned files to existing dotMD patterns so execution agents
keep one search plane (no parallel federated lane) and reuse already-tested
boundaries.

## Planned File Roles

| Planned file | Role | Closest existing analog |
|--------------|------|-------------------------|
| `backend/src/dotmd/core/models.py` | Add `SearchCandidate`, `SearchResponse`, `SourceStatus`; remove `SearchResult` | Existing `SearchResult` (lines 405-427); `ApplicationSourceChange*`, `SourceDocument`, `SourceUnit` Pydantic patterns |
| `backend/src/dotmd/search/fusion.py` | Migrate `fuse_results` and `build_search_results` from `chunk_id` keys to `ref` keys; produce `SearchCandidate` instead of `SearchResult` | Existing `fuse_results` (RRF math unchanged), `build_search_results`, `_public_ref_for_provenance` |
| `backend/src/dotmd/search/federated.py` (new) | Federated fan-out helper: parallel `asyncio.gather`, per-source soft timeout, `EngineOutcome` dataclass, `SourceStatus` collection | None — new module, but mirrors Airweave `_search_federated_sources` shape (rejecting fail-fast) |
| `backend/src/dotmd/api/service.py` | `DotMDService.search` returns `SearchResponse`; orchestrates async fan-out across local + federated engines; pre-fusion provenance hydration | Existing `_execute_search`, `_collect_candidate_pool`, `_filter_active_fused_candidates` |
| `backend/src/dotmd/ingestion/source_provider.py` | Add optional `search_native(query, limit) -> list[SearchCandidate]` to a federated-search protocol (separate optional Protocol, not on `ApplicationSourceProviderProtocol` to keep Phase 28 surface untouched) | Existing `ApplicationSourceProviderProtocol` |
| `backend/src/dotmd/ingestion/telegram_provider.py` | Implement `search_native` on `TelegramApplicationSourceProvider`; extend `TelegramSourceClientProtocol` and `UnixSocketTelegramSourceClient` with `search_messages` | Existing `read_source_unit_window` socket method pattern (lines 102-116, 177-190); existing `_request` helper |
| `backend/src/dotmd/ingestion/source_lifecycle.py` | Add `SourceRuntimeBundle.supports_federated_search` property; no constructor changes | Existing `SourceRuntimeBundle` model (lines 228-239) |
| `backend/src/dotmd/mcp_server.py` | Update `SearchHit` to mirror `SearchCandidate` essentials; add `SearchEnvelope` wrapping `results` + `source_status`; `search` tool returns envelope | Existing `SearchHit`, `_format_result`, `read`, `drill` tool definitions |
| `backend/src/dotmd/api/server.py` | FastAPI `/search` route — at planner discretion (CONTEXT.md): keep current shape OR migrate to envelope. Default plan choice: keep current shape, document follow-up | Existing FastAPI route patterns |
| `backend/tests/core/test_search_candidate.py` (new) | Pydantic shape tests, field semantics, `extra="forbid"`, frozen invariants | `tests/core/test_models_*` test patterns |
| `backend/tests/search/test_fusion.py` | Update fusion tests for ref keys; add federated-rank-parity tests | Existing fusion tests |
| `backend/tests/search/test_federated.py` (new) | Stub federated provider, soft-timeout, soft-skip, source_status assertions | None — new; shape mirrors `tests/ingestion/test_source_lifecycle.py` |
| `backend/tests/api/test_service_search.py` | Service-level fan-out, envelope shape, federated round-trip with `FakeTelegramSourceClient` | Existing `test_service_search.py` test patterns |
| `backend/tests/ingestion/test_telegram_provider.py` | `search_native` returns expected `SearchCandidate` list given fake client payload | Existing `test_telegram_provider.py` round-trip patterns |
| `backend/tests/ingestion/test_telegram_ingestion.py` | Round-trip: federated `search_native` ref → `read(ref)` → `drill(ref)` | Existing Telegram ingest fixture & assertion patterns |
| `docs/source-adapter-architecture.md` | Add Phase 34 federated section: SearchCandidate, fan-out, soft-skip | Existing Phase 26-33 sections |
| `docs/source-registry-airweave-mapping.md` | Update to mark `federated_search` capability as Phase 34 implemented | Existing capability mapping table |

## Code Excerpts And Patterns

### Pattern 1: Pydantic envelope with `extra="forbid"` and `frozen=True`

Existing patterns in `core/models.py`:

```python
class SourceUnit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    namespace: str
    document_ref: str
    unit_ref: str
    ...
```

Phase 34 mirrors this exactly. `SearchCandidate` and `SearchResponse` use
`model_config = ConfigDict(extra="forbid", frozen=True)` for read-side
immutability.

### Pattern 2: Public ref construction for Telegram

Existing helper in `search/fusion.py`:

```python
def _public_ref_for_provenance(provenance: ChunkProvenance) -> str:
    if provenance.namespace == "telegram" and len(provenance.source_unit_refs) == 1:
        return f"telegram:{provenance.source_unit_refs[0]}"
    return provenance.ref
```

This already produces the same ref shape that federated Telegram hits will
carry: `telegram:dialog:<id>:message:<id>`. Phase 34 reuses it for local
hydration; federated path constructs the ref directly from daemon payload
(see Telegram provider snippet in RESEARCH.md).

### Pattern 3: Pre-fusion provenance hydration

Currently `build_search_results` (`fusion.py` line 281+) calls
`get_chunk_provenance_for_chunk_ids` AFTER fusion to hydrate refs. Phase 34
moves that batch call to BEFORE fusion. Each local engine output
`list[(chunk_id, score)]` becomes `list[(ref, score)]` via the same batch
provenance call, then fusion runs on ref keys directly.

```python
# Currently (post-fusion):
fused = fuse_results({"semantic": chunk_id_results, ...})  # keyed by chunk_id
results = build_search_results(fused, ..., provenance_map=...)  # hydrates ref

# Phase 34 (pre-fusion):
provenance_map = store.get_chunk_provenance_for_chunk_ids(strategy, all_chunk_ids)
ref_keyed = {
    engine: [(provenance_map[cid].ref, score) for cid, score in hits]
    for engine, hits in chunk_id_results.items()
}
fused = fuse_results(ref_keyed)  # keyed by ref
candidates = build_candidates(fused, ref_to_chunk_metadata, ..., federated_extras)
```

[VERIFIED: `search/fusion.py:281-296`]

### Pattern 4: Lifecycle bundle and capability dispatch

Existing capability check (Phase 32-33):

```python
if SourceCapability.FEDERATED_SEARCH in descriptor.capabilities:
    ...
```

Phase 34 adds at lifecycle boundary:

```python
class SourceRuntimeBundle(BaseModel):
    ...
    @property
    def supports_federated_search(self) -> bool:
        if SourceCapability.FEDERATED_SEARCH not in self.descriptor.capabilities:
            return False
        return getattr(self.provider, "search_native", None) is not None
```

Service-layer iteration:

```python
federated_bundles = [
    bundle for bundle in self._lifecycle_bundles.values()
    if bundle.supports_federated_search
]
```

### Pattern 5: Async fan-out with `asyncio.wait_for`

Pattern adopted from Airweave (`_search_federated_sources` lines 301-337) but
reshaped for soft-skip:

```python
@dataclass(frozen=True)
class EngineOutcome:
    name: str
    status: Literal["ok", "skipped", "error"]
    candidates: list[SearchCandidate]
    reason: str | None
    elapsed_ms: float

async def _run_one(name: str, coro: Awaitable[list[SearchCandidate]], timeout: float) -> EngineOutcome:
    t0 = time.perf_counter()
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return EngineOutcome(name, "ok", result, None, _ms_since(t0))
    except asyncio.TimeoutError:
        return EngineOutcome(name, "skipped", [], "timeout", _ms_since(t0))
    except Exception as exc:
        logger.warning("federated %s failed", name, exc_info=True)
        return EngineOutcome(name, "error", [], str(exc), _ms_since(t0))
```

### Pattern 6: MCP tool returning Pydantic envelope

Existing pattern in `mcp_server.py`:

```python
@mcp.tool(name="read", ...)
async def read_document(...) -> ReadResult:
    result = await asyncio.to_thread(service.read, ref, start, end)
    return ReadResult(...)
```

Phase 34 search tool follows the same shape, returning `SearchEnvelope`.
Existing `_collapse_null` helper handles `T | None` schema cleanup for
optional fields like `provider_metadata`.

### Pattern 7: Telegram daemon socket method addition

Existing `_request` pattern in `telegram_provider.py:118-141`:

```python
def _request(self, payload: dict) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
        sock.settimeout(self._timeout_seconds)
        sock.connect(str(self._socket_path))
        sock.sendall(json.dumps(payload).encode("utf-8") + b"\n")
        ...
        return data_payload
```

Phase 34 adds:

```python
def search_messages(
    self,
    query: str,
    limit: int,
    dialog_id: int | None = None,
) -> dict:
    payload = {"method": "search_messages", "query": query, "limit": limit}
    if dialog_id is not None:
        payload["dialog_id"] = dialog_id
    return self._request(payload)
```

Same response envelope shape as other daemon methods (`{"ok": true, "data":
{...}}`). [VERIFIED: existing `_request` enforces `ok==true`.]

### Pattern 8: Active-binding gate scope (Phase 27 invariant)

Existing `_filter_active_fused_candidates` (lines 587-612 of `service.py`)
strips fused entries whose chunk has no active binding. Phase 34 must keep
this filter ONLY for refs that have local provenance. Federated-only refs
(no chunk_id, no provenance) bypass this filter entirely.

```python
def _filter_active_fused_candidates_by_ref(
    self,
    fused: list[tuple[str, float]],
    local_provenance: dict[str, ChunkProvenance],   # ref → provenance
) -> tuple[list[tuple[str, float]], int]:
    """Drop inactive local refs; pass federated-only refs through unchanged."""
    filtered: list[tuple[str, float]] = []
    inactive_count = 0
    for ref, score in fused:
        provenance = local_provenance.get(ref)
        if provenance is None:
            filtered.append((ref, score))   # federated-only, no local check
            continue
        if self._is_active(provenance):
            filtered.append((ref, score))
        else:
            inactive_count += 1
    return filtered, inactive_count
```

Test `test_federated_only_ref_bypasses_active_filter` pins this behavior.

## Anti-Patterns To Avoid

- Re-implementing RRF math — only the key type changes; math stays in
  `fuse_results`.
- Adding `SearchResult = SearchCandidate` aliases — D-01 is a clean break.
- Treating `ApplicationSourceProviderProtocol` as the federated boundary —
  add a separate optional `FederatedSearchProviderProtocol` (or duck-typed
  `search_native`) so Phase 28 surface stays minimal.
- Hard-coding "telegram" namespace in the executor — discover via
  `bundle.supports_federated_search`.
- Calling `lifecycle_factory.build()` per request — build once at service
  init, cache.
- Bypassing the active-binding gate for local hits — keep Phase 27 semantics
  intact.
- Adding asyncio anywhere local engines are called synchronously — use
  `asyncio.to_thread` for sync engines, native await for federated
  coroutines.
- Putting fan-out in `mcp_server.py` — service layer owns orchestration; MCP
  is a thin transport.
- Adding new Telegram capabilities to `mcp-telegram` repo from inside
  Phase 34 PLAN — Plan 03 marks the daemon-side coordination as a separate
  step (see RESEARCH.md "Open Question").

## Test Fixture Hand-offs

| Fixture | Role | Source |
|---------|------|--------|
| `FakeTelegramSourceClient` | In-memory client implementing `TelegramSourceClientProtocol` with seeded `search_messages` payloads | New in `tests/ingestion/conftest.py` next to existing fakes |
| `StubFederatedProvider` | Trivial provider with `search_native` returning fixed candidates; used for fan-out / timeout tests without Telegram coupling | New in `tests/search/conftest.py` |
| `make_lifecycle_bundle` | Helper to assemble a `SourceRuntimeBundle` from a fake registry, fake config store, fake credential provider, and either real or stub provider | Already exists for Phase 33 — extend for federated-search test cases |
| `slow_provider_factory` | Returns a stub provider whose `search_native` `await asyncio.sleep(N)` to exercise timeout path | New in `tests/search/conftest.py` |

---

*Phase: 34-Federated SearchCandidate contract*
*Patterns mapped: 2026-05-08*
