# Phase 34: Federated SearchCandidate contract - Research

**Researched:** 2026-05-08
**Status:** Complete

## Research Question

What does the planner need to know to ship one `SearchCandidate` contract that
covers local dotMD retrieval and source-native federated search, migrate fusion
from `chunk_id` to `ref`, fan out across federated providers with soft-skip,
and prove the contract with mcp-telegram's `SearchMessages` round-tripping
through `read(ref)` / `drill(ref)`?

## User Constraints

Copied from `34-CONTEXT.md` decisions verbatim. The planner MUST honor every
locked decision below. Areas marked Claude's Discretion are open to the
planner.

### Locked decisions (MUST honor)

- **D-01:** `SearchCandidate` is the single public search-result type at the
  service and MCP layers. The current `SearchResult` type is removed (clean
  break — no compat alias, no deprecation period).
- **D-02:** Per-engine debug scores collapse into an optional diagnostic shape
  (e.g. `engine_scores: dict[str, float] | None`). Federated candidates leave
  it `None`.
- **D-03:** Federated-only fields live in a `provider_metadata: dict[str, Any]`
  catch-all on the candidate, not as scattered top-level optional fields.
- **D-04:** `SearchCandidate` carries at least: stable `ref`, source identity
  (namespace + descriptor key), title or display name, snippet, retrieval kind
  (`semantic`, `keyword`, `graph_direct`, or a federated engine name like
  `tg:fts`), provenance for local-backed hits, source-native score and rank
  for federated hits, `can_read`, `can_materialize`, `engine_scores`,
  `provider_metadata`.
- **D-05:** Fusion key migrates from `chunk_id` to `ref`. Local engines resolve
  chunk → ref through provenance hydration **before** fusion.
- **D-06:** Federated providers participate in the same RRF as local engines.
  Engine names are namespaced (e.g. `tg:fts`). Per-engine weights remain,
  default 1.0. Fusion stays rank-only.
- **D-07:** Existing cross-encoder reranker is kept as-is for local and
  federated candidates with text snippets. Federated candidates without
  reranker-eligible text skip reranking and keep RRF score.
- **D-08:** Federated fan-out is always-on by default. Every `service.search()`
  queries all local engines plus all sources whose descriptor declares
  `FEDERATED_SEARCH` and whose lifecycle bundle is constructible.
- **D-09:** Per-source soft timeout (3-5s default, config-tunable). Failure
  detection only — not throughput shaping.
- **D-10:** MCP-level `sources` allowlist / `exclude_sources` blocklist
  parameters are deferred. Always-on fan-out.
- **D-11:** Soft-skip per source on error/timeout. `SearchResponse` envelope
  carries `candidates: list[SearchCandidate]` plus `source_status` with one
  entry per fanned-out engine (`ok` / `skipped` / `error` plus reason).
  Local engines report through the same status surface.
- **D-12:** No fail-fast.
- **D-13:** Federated candidates set `can_read: True` only when the provider
  exposes `read_unit_window` for that unit type. `read(ref)` for a
  federated-only hit routes through the lifecycle bundle's
  `read_unit_window`, not the local store.
- **D-14:** No on-demand materialization. `can_materialize: False` for all
  Phase 34 candidates. Trickle stays the single write path.
- **D-15:** When `read(ref)` for a federated-only hit cannot reach the
  provider, the read returns a clear provider-attributed error with the same
  source-status attribution shape as search.
- **D-16:** Phase 34 proves the contract with mcp-telegram's `SearchMessages`.
  Telegram candidates carry `ref = telegram:dialog:<id>:message:<id>` and
  round-trip through `read(ref)` and `drill(ref)`.
- **D-17:** dotMD never owns the Telegram client. All Telegram FTS, fetch,
  metadata go through the existing mcp-telegram daemon socket. The Phase 33
  lifecycle bundle is the construction boundary.
- **D-18:** Contract must be generic enough that gmail/slack/notion/voicenotes
  land later as descriptor + provider work only, with no Phase 34 contract
  edits.

### Claude's Discretion (planner picks)

- Exact Pydantic field names on `SearchCandidate` and `SourceStatus`; naming
  of `engine_scores` (dict vs nested model); module placement of soft-timeout
  logic.
- Whether `source_status` is top-level on `SearchResponse` or nested under a
  `meta` block — pick one and stay consistent.
- Default per-source soft timeout within the 3-5s range. Tunable through
  config.
- Concrete shape of `provider_metadata` for Telegram (dialog title, sender,
  topic, etc.) — provider-specific and inspectable, not part of the public
  contract.
- Whether the FastAPI `/search` route also returns the new `SearchResponse`
  envelope or stays on the previous shape for Phase 34.

### Deferred (out of scope)

- MCP source-filter parameters; on-demand materialization; gmail/slack/notion
  federated sources; per-source latency observability; federated reranker
  behavior changes; FastAPI envelope migration (optional).

## Project Constraints (from CLAUDE.md)

- **Containers first:** Never run `dotmd` on host — always Docker exec or API.
- **No prod restarts on small changes:** Batch changes, deploy once.
- **No manual reindex / parallel indexing:** Trickle owns the write path; tests
  must not assume `dotmd index --force` is safe to run while the container is
  up. Phase 34 has zero indexing impact (read-side contract only).
- **No backward compat obligations:** Clean breaks preferred over aliases.
  Decision D-01 is consistent with this — `SearchResult` is removed outright.
- **No legacy compat shims:** No `SearchResult = SearchCandidate` aliases.
- **No new beads tickets:** dotMD uses GSD exclusively.
- **DOTMD_DATA_DIR=/mnt is locked:** No narrowing the indexing scope; not
  affected by this phase but tests should not assume otherwise.
- **Never reload indexes per-request:** Same applies to lifecycle bundles —
  build once, reuse on every search.
- **Tests before refactor:** All contract migrations get behavior-pinning
  tests first (TDD).
- **`docker compose restart` does NOT recreate the container:** After image
  changes, use `docker compose up -d`. Phase 34 is bind-mounted source —
  `docker compose restart dotmd` is sufficient for code changes; only the
  one production restart needed at Wave-2 sign-off.

## Standard Stack

| Concern | Library / Pattern |
|---------|-------------------|
| Public domain models | Pydantic v2, `model_config = ConfigDict(extra="forbid")` |
| Protocols | `typing.Protocol` (small, behavior-only) |
| Async fan-out | `asyncio.gather(..., return_exceptions=True)` with `asyncio.wait_for(..., timeout=...)` per task |
| Soft timeout | `asyncio.wait_for` per source coroutine; on `TimeoutError` produce `SourceStatus(status="skipped", reason="timeout")` |
| MCP server | FastMCP (`mcp.server.fastmcp.FastMCP`); tool returns Pydantic model directly |
| Reranker | Existing `CrossEncoderReranker` from `dotmd.search.reranker`, unchanged |
| Tests | pytest, `uv run pytest`, fixtures over mocks where possible |

[VERIFIED: codebase grep] All bullets above match how dotMD already builds
boundaries (e.g., `ApplicationSourceProviderProtocol`, `SourceRuntimeBundle`).

## Architecture Patterns

### Pattern 1: Single Pydantic envelope, append-only field shape (D-04, D-18)

`SearchCandidate` is one Pydantic model that covers both local and federated
hits. To stay generic for future providers, every "this only matters for
local" or "this only matters for federated" field is `Optional` with `None`
default. Future providers do not edit this model — they fill what fits and
leave the rest `None`.

```python
class SearchCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    ref: str                           # public identity (D-04, D-05)
    namespace: str                     # source namespace (D-04)
    source_kind: str                   # descriptor.source_kind
    retrieval_kind: str                # "semantic"|"keyword"|"graph_direct"|"tg:fts"|...
    title: str | None = None
    snippet: str
    fused_score: float                 # rank-only RRF (D-06)
    can_read: bool                     # D-13
    can_materialize: bool = False      # D-14 (always False in Phase 34)

    # Local-backed fields (None for federated-only hits)
    chunk_id: str | None = None
    heading_path: str | None = None
    matched_engines: list[str] = Field(default_factory=list)
    provenance: ChunkProvenance | None = None

    # Federated-only fields (None for local-only hits)
    source_native_score: float | None = None
    source_native_rank: int | None = None

    # Diagnostic / generic catch-all (D-02, D-03)
    engine_scores: dict[str, float] | None = None
    provider_metadata: dict[str, Any] | None = None
```

### Pattern 2: Per-engine ranked `(ref, score)` lists (D-05)

Every engine — local and federated — emits `list[tuple[ref, score]]` where
`ref` is the public source-ref identity. Local engines resolve `chunk_id ->
ref` before fusion through the existing provenance hydration. The fusion
function changes its key type from `chunk_id: str` to `ref: str`. The
function body stays algorithmically identical (RRF formula unchanged).

```python
# Old: ranked_lists: dict[str, list[tuple[chunk_id, score]]]
# New: ranked_lists: dict[str, list[tuple[ref, score]]]
def fuse_results(
    ranked_lists: dict[str, list[tuple[str, float]]],
    k: int = 60,
    engine_weights: dict[str, float] | None = None,
) -> list[tuple[str, float]]: ...
```

[CITED: airweave executor] Airweave's `_merge_with_rrf` operates on
`entity_id` strings — same shape, just keyed on their public ID. dotMD adapts
the pattern but keys on source-ref instead of `entity_id+sync_id`.

### Pattern 3: Parallel fan-out with per-source soft timeout (D-08, D-09, D-11, D-12)

```python
async def _run_one(name: str, coro: Awaitable, timeout: float) -> EngineOutcome:
    try:
        result = await asyncio.wait_for(coro, timeout=timeout)
        return EngineOutcome.ok(name, result)
    except asyncio.TimeoutError:
        return EngineOutcome.skipped(name, reason="timeout")
    except Exception as exc:
        logger.warning("federated %s failed", name, exc_info=True)
        return EngineOutcome.error(name, reason=str(exc))

outcomes = await asyncio.gather(*[
    _run_one(name, coro, timeout=settings.federated_timeout_seconds)
    for name, coro in engine_calls.items()
])
```

[CITED: airweave executor `_search_federated_sources`] dotMD adapts the
parallel-fan-out pattern; it explicitly **rejects** Airweave's fail-fast
behavior (`FederatedSearchError` raise on any source failure) per D-12.

### Pattern 4: Lifecycle bundle exposes federated capability (D-08, D-17)

`SourceRuntimeBundle` (Phase 33) gains an optional `search_native` callable
when the descriptor declares `FEDERATED_SEARCH` and the provider implements
the new method. The factory's `build()` for `telegram` already returns
`provider=TelegramApplicationSourceProvider(...)`; that provider gets a new
`search_native(query, limit) -> list[SearchCandidate]` method. The bundle
exposes:

```python
class SourceRuntimeBundle(BaseModel):
    descriptor: SourceDescriptor
    config: ...
    access: ...
    cursor_store: ...
    source: FilesystemMarkdownSourceAdapter | None = None
    provider: ApplicationSourceProviderProtocol | None = None
    metadata_json: dict[str, object] = Field(default_factory=dict)

    @property
    def supports_federated_search(self) -> bool:
        return (
            SourceCapability.FEDERATED_SEARCH in self.descriptor.capabilities
            and self.provider is not None
            and hasattr(self.provider, "search_native")
        )
```

This avoids hard-coding namespaces in the search executor — the executor
discovers federated bundles by capability flag, not by name.

### Pattern 5: SearchResponse envelope (D-11)

```python
class SourceStatus(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    name: str                          # "semantic" | "keyword" | "graph_direct" | "tg:fts"
    status: Literal["ok", "skipped", "error"]
    reason: str | None = None
    candidate_count: int = 0
    elapsed_ms: float | None = None

class SearchResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    candidates: list[SearchCandidate]
    source_status: list[SourceStatus]
```

`source_status` lives at the top level (Decision: top-level chosen over a
`meta` block — flatter envelope, fewer nested attribute accesses for the MCP
tool layer; both were on the table per discretion).

### Pattern 6: Telegram daemon socket extension

The dotMD-side `TelegramSourceClientProtocol` already has `describe_source`,
`export_source_changes`, `read_source_unit_window`. Phase 34 adds:

```python
def search_messages(
    self,
    query: str,
    limit: int,
    dialog_id: int | None = None,
) -> dict: ...
```

The wire payload mirrors the existing pattern:
```json
{"method": "search_messages", "query": "kantine", "limit": 20}
```

[ASSUMED] mcp-telegram daemon already has the underlying capability — its MCP
tool `SearchMessages` proves the data path exists; the daemon socket likely
needs a corresponding `search_messages` method. **Confirm with the
mcp-telegram maintainer or read the daemon source before Plan 03.** If the
method does not yet exist on the socket, Plan 03 must coordinate with
`/opt/docker/mcp-telegram/` to add it (out-of-repo work item) — but Phase 34
unit-tests use a fake `TelegramSourceClientProtocol` implementation so dotMD
work is unblocked.

## Don't Hand-Roll

- **RRF fusion math** — reuse `dotmd.search.fusion.fuse_results`; only its
  key semantics (`chunk_id` -> `ref`) and dict-value type change.
- **Cross-encoder reranking** — use existing `CrossEncoderReranker.rerank`.
  Federated candidates without snippet text simply skip the reranker call
  for those refs (D-07).
- **Telegram message ref shape / parsing** — reuse
  `_parse_telegram_message_ref` and `_is_telegram_message_ref` already in
  `api/service.py`.
- **`read_unit_window` glue** — reuse
  `TelegramApplicationSourceProvider.read_unit_window` and the existing
  `service._read_telegram_message` / `_drill_telegram_message` paths.
- **MCP output Pydantic models** — define new `SearchCandidate`-shaped MCP
  tool model in `mcp_server.py` mirroring the new Pydantic; reuse
  `_collapse_null` for optional fields.
- **Active-binding visibility gate** — local-backed candidates flow through
  the existing `_filter_active_fused_candidates`. Federated-only candidates
  are not filtered by it (no local provenance to filter against), per
  Phase 27 semantics that only constrain locally-indexed content.
- **Telegram client** — reuse `UnixSocketTelegramSourceClient`; only add a
  new method.

## Common Pitfalls

| Pitfall | Detection / Mitigation |
|---------|------------------------|
| Treating provider-native scores as comparable across providers | Test: federated candidate with extreme `source_native_score` cannot leapfrog a local hit purely on raw score. Only RRF rank counts. |
| Federated candidates leak into active-binding filter and disappear | Test: federated-only candidate (no `chunk_id`) survives `_filter_active_fused_candidates`. The filter only inspects rows that have local provenance. |
| Reranker called on candidates without snippet → CrossEncoder error | Code: skip reranker for candidates whose snippet is empty/missing; assertion test asserts they retain RRF score. |
| Fan-out blocks on slowest provider | Test: stub federated provider that sleeps > timeout returns `SourceStatus(status="skipped", reason="timeout")`; total response time stays within timeout + slack. |
| `read(ref)` for federated-only hit hits the local store and 404s | Test: `read("telegram:dialog:1:message:99")` for a never-indexed message returns the live `read_unit_window` response, not a "no chunks" error. |
| `SearchResult` references survive elsewhere → import errors | `rg -n "SearchResult\b" backend/` must return zero matches outside test fixtures explicitly testing the removal. |
| Fusion-key change breaks per-engine score attribution | `engine_scores: dict[str, float]` keyed by engine name — populate from the same per-engine ref-keyed lists used as fusion inputs. |
| Lifecycle bundle reload cost on every search | Build bundles once at `DotMDService.__init__` and cache; never re-`build()` per request (CLAUDE.md rule "never reload per request"). |
| `engine_scores` becomes a misleading "all engines tried" map | Convention: only populate keys for engines that **scored** the ref. Absent key = engine didn't return this ref. Tests assert this. |
| `provider_metadata` accidentally turns into a contract | Tests assert `SearchCandidate.model_fields["provider_metadata"]` is `dict[str, Any] | None` — schema deliberately wide; downstream consumers must treat as opaque. |
| Telegram message snippet reranker friction | Telegram message text is short; pass it through reranker (it handles short strings) but document in code: short messages may rerank low. |

## Code Examples

### Service-layer fan-out skeleton

```python
async def search(
    self,
    query: str,
    top_k: int = 10,
    rerank: bool = True,
    expand: bool = True,
) -> SearchResponse:
    # 1. Expand query (existing).
    # 2. Build engine call coroutines:
    #    - local: semantic, fts5, graph_direct (sync → run_in_executor)
    #    - federated: every bundle.supports_federated_search
    # 3. Fan out with asyncio.gather + per-source wait_for(timeout).
    # 4. Collect EngineOutcome list — populate engine_results + source_status.
    # 5. Hydrate local lists chunk_id → ref via provenance batch query.
    # 6. fuse_results(ranked_lists_by_ref) → fused: list[(ref, score)].
    # 7. Build SearchCandidate list:
    #    - local refs: pull chunk metadata, snippet, heading.
    #    - federated refs: keep provider-supplied snippet, title, metadata.
    # 8. Optional cross-encoder rerank on candidates with snippet text.
    # 9. Return SearchResponse(candidates=top_k, source_status=...).
```

### Telegram provider federated method

```python
class TelegramApplicationSourceProvider(ApplicationSourceProviderProtocol):
    def search_native(self, query: str, limit: int) -> list[SearchCandidate]:
        payload = self._client.search_messages(query=query, limit=limit)
        candidates: list[SearchCandidate] = []
        for rank, hit in enumerate(payload["hits"]):
            ref = f"telegram:dialog:{hit['dialog_id']}:message:{hit['message_id']}"
            candidates.append(SearchCandidate(
                ref=ref,
                namespace="telegram",
                source_kind="chat",
                retrieval_kind="tg:fts",
                title=hit.get("dialog_name"),
                snippet=hit["text"][:300],
                fused_score=0.0,                         # RRF replaces this
                can_read=True,                            # has read_unit_window
                can_materialize=False,                    # D-14
                source_native_score=hit.get("score"),
                source_native_rank=rank,
                provider_metadata={
                    "dialog_id": hit["dialog_id"],
                    "message_id": hit["message_id"],
                    "sender": hit.get("sender"),
                    "sent_at": hit.get("sent_at"),
                },
            ))
        return candidates
```

### MCP search tool returning SearchResponse

```python
class SearchHit(BaseModel):
    ref: str
    namespace: str
    retrieval_kind: str
    title: str | None = None
    snippet: str
    score: float
    can_read: bool
    provider_metadata: dict[str, Any] | None = None

class SearchEnvelope(BaseModel):
    results: list[SearchHit]
    source_status: list[dict]   # serialized SourceStatus

@mcp.tool(name="search", ...)
async def search(query: str, top_k: int = 10) -> SearchEnvelope:
    response = await asyncio.to_thread(service.search, query, top_k=top_k)
    return SearchEnvelope(
        results=[_to_hit(c) for c in response.candidates],
        source_status=[s.model_dump() for s in response.source_status],
    )
```

## Validation Architecture

### Test infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest (sync), `pytest-asyncio` for async fan-out tests (already in deps if needed) |
| Quick command | `cd backend && uv run pytest tests/api/test_service_search.py tests/search/test_fusion.py tests/core/test_search_candidate.py -q` |
| Full suite command | `cd backend && uv run pytest tests/ -q -k "search or fusion or candidate or telegram_provider"` |
| Static checks | `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/search/fusion.py src/dotmd/api/service.py src/dotmd/mcp_server.py src/dotmd/ingestion/telegram_provider.py` |
| Estimated runtime | ~20s targeted, ~90s full search test set |

### Sampling rate

- Per-task commit: targeted file-scoped pytest (~5s).
- Per-plan completion: full search test set + pyright on modified files.
- Phase verification (gsd-verify-work): full suite + container restart smoke
  test against live MCP search tool with stub federated provider.

### Required behaviors to test (Nyquist)

1. **Contract removal:** `SearchResult` symbol no longer exists in
   `dotmd.core.models`; all callers import `SearchCandidate`.
2. **Ref-keyed fusion:** `fuse_results({"semantic": [("ns:a", 0.9)], "keyword":
   [("ns:a", 0.5)]})` returns `[("ns:a", combined)]` — same arithmetic, just
   keyed on ref.
3. **Local-engine ref hydration:** semantic engine returning chunk_id `c1`
   becomes ranked entry `("filesystem:/foo.md#0", score)` after pre-fusion
   provenance hydration.
4. **Per-engine score map:** candidate matched by semantic+keyword shows
   `engine_scores={"semantic": 0.9, "keyword": 0.5}`; absent for engines that
   didn't score it.
5. **Federated parallel + soft timeout:** stub provider that sleeps 10s with
   timeout=2s returns `SourceStatus(status="skipped", reason="timeout")`;
   total `service.search()` wall time < 3s.
6. **Federated error soft-skip:** stub provider raising
   `RuntimeError("daemon down")` returns
   `SourceStatus(status="error", reason="daemon down")`; local results are
   unaffected.
7. **Federated RRF parity:** federated candidate at rank 1 of `tg:fts`
   contributes `1/(60+1)` to its ref's RRF score, identical to a local
   engine's rank-1 contribution.
8. **Federated read round-trip:** `service.read("telegram:dialog:1:message:99")`
   for a non-indexed Telegram message routes through provider
   `read_unit_window` — never queries local metadata store.
9. **Federated read provider-down attribution:** `read(ref)` when the
   Telegram daemon socket is down raises
   `RuntimeError` with provider-attributed message ("telegram: ...").
10. **MCP tool envelope:** `mcp.search(...)` returns
    `{"results": [...], "source_status": [...]}` with at least one entry per
    fanned-out engine.
11. **`can_materialize=False` invariant:** every candidate's
    `can_materialize` is `False` in Phase 34. Single assertion sweep.
12. **Active-binding gate scope:** federated-only candidate (no chunk_id)
    survives `_filter_active_fused_candidates`; local candidate with inactive
    binding is dropped (existing Phase 27 behavior preserved).
13. **Lifecycle bundle reuse:** lifecycle factory `build_if_configured` is
    called once at service init; mock asserts no per-request rebuild.

### Stubs and fixtures

- `FakeTelegramSourceClient` implementing the protocol with hardcoded
  `search_messages` payloads — already established pattern from Phase 29
  test suite.
- `StubFederatedProvider` registered with synthesized descriptor for
  contract-only tests (no Telegram coupling), exercising soft-timeout and
  fan-out behavior.

### Manual smoke (Phase verification only)

- One container restart of `dotmd` after Plan 03 lands; one MCP `search`
  call from Claude Code returning a Telegram message ref; one `read(ref)`
  call confirming the message body comes back via daemon socket.

## Open Question (single)

**Does mcp-telegram's daemon socket already expose a `search_messages`
method, or does Phase 34 need to coordinate with the `/opt/docker/mcp-
telegram` repo to add it?** [ASSUMED — needs verification by reading
`/opt/docker/mcp-telegram/` source before Plan 03 starts.]

If absent: Plan 03 splits in two — (a) dotMD-side wrapper + tests using
fake client; (b) coordinate-out ticket to add `search_messages` to the
mcp-telegram daemon. Plan 03 marks the live-smoke task `autonomous: false`
in that case.

If present: Plan 03 stays end-to-end with a real daemon-socket round-trip
in Wave 3.

## Recommended Phase Shape

Three plans, three waves:

- **34-01: SearchCandidate + SearchResponse + ref-keyed local fusion** —
  Foundation. No federated work. Removes `SearchResult`, builds
  `SearchCandidate`, migrates fusion to ref keys, hydrates chunk→ref
  pre-fusion. Ships behind the existing API surface (no MCP tool changes
  yet — internal-only model swap with shim assemble at the MCP boundary
  preserved temporarily). After this plan, all current tests should still
  pass with the new internal shape.

- **34-02: Federated fan-out infrastructure** — Adds `SourceStatus`,
  `SearchResponse`, async fan-out, soft-timeout, `search_native` provider
  protocol method, lifecycle bundle `supports_federated_search` discovery.
  Uses an in-tree `StubFederatedProvider` to exercise contract; Telegram
  is not yet wired. Updates the MCP `search` tool to return the envelope.

- **34-03: Telegram federated proof + read/drill round-trip** —
  Implements `TelegramApplicationSourceProvider.search_native`, extends
  `UnixSocketTelegramSourceClient` and the protocol with `search_messages`,
  routes `read(ref)` and `drill(ref)` for federated-only refs through
  `read_unit_window`. End-to-end test using `FakeTelegramSourceClient`
  with realistic payloads. One container-restart smoke task at the end.

This shape lets Plan 01 land cleanly without touching async or fan-out
plumbing, isolates async/fan-out risk in Plan 02, and isolates the
mcp-telegram coordination question to Plan 03.

## Provenance Tags Summary

- All `[VERIFIED]` claims confirmed by reading current dotMD source files
  listed in CONTEXT.md canonical refs (2026-05-08).
- `[CITED: airweave executor]` claims reference
  `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/search/executor.py`.
- `[ASSUMED]` claims are flagged inline and require Plan 03 verification.

---

*Phase: 34-Federated SearchCandidate contract*
*Research completed: 2026-05-08*
