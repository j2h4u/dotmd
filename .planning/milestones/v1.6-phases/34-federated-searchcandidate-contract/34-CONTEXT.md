# Phase 34: Federated SearchCandidate contract - Context

**Gathered:** 2026-05-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Define one search candidate contract that covers both local dotMD retrieval
(semantic / FTS5 / graph) and source-native federated search, then prove it
end-to-end with mcp-telegram's native FTS (`SearchMessages`) round-tripping
through `read(ref)` and `drill(ref)`.

This phase is the contract layer plus the first federated provider proof. It
is not a multi-source rollout (gmail/slack/notion remain deferred), not a
materialization-on-demand cache, not an MCP control surface for source
filtering, and not a Phase 35-37 unification of filesystem or Telegram source
adapters.

</domain>

<decisions>
## Implementation Decisions

### Public Search Contract

- **D-01:** `SearchCandidate` is the single public search-result type at the
  service and MCP layers. The current `SearchResult` type is removed (clean
  break — no compat alias, no deprecation period).
- **D-02:** Per-engine debug scores (`semantic_score`, `keyword_score`,
  `graph_score`) collapse into an optional diagnostic shape on the candidate
  (e.g. `engine_scores: dict[str, float] | None`). They are not part of the
  public contract semantics. Federated candidates leave them None.
- **D-03:** Federated-only fields live in a `provider_metadata: dict[str, Any]`
  catch-all on the candidate, not as scattered top-level optional fields. The
  catch-all is explicit, not an accidental anything-bag.
- **D-04:** `SearchCandidate` carries at least: stable `ref`, source identity
  (namespace + descriptor key), title or display name, snippet, retrieval kind
  (`semantic`, `keyword`, `graph_direct`, or a federated engine name like
  `tg:fts`), provenance for local-backed hits, source-native score and rank
  for federated hits, `can_read`, `can_materialize`, and the optional
  `engine_scores` and `provider_metadata` diagnostics.

### Fusion And Engine Topology

- **D-05:** Fusion key migrates from `chunk_id` to `ref`. Every engine emits
  ranked `(ref, score)` lists. Local engines (`semantic`, `fts5`,
  `graph_direct`) resolve chunk → ref through the existing provenance
  hydration before fusion, instead of after.
- **D-06:** Federated providers participate in the same RRF as local engines.
  Engine names are namespaced (e.g. `tg:fts`, `gmail:native`). Per-engine
  weights remain available, default 1.0. Fusion stays rank-only — no provider
  score is treated as directly comparable to another.
- **D-07:** Phase 34 keeps the existing cross-encoder reranker as-is for local
  and federated candidates with text snippets. If a federated provider returns
  a candidate without enough text to rerank, that candidate skips reranking
  and keeps its RRF score. No new reranker behavior is introduced in this
  phase.

### Federated Fan-out Policy

- **D-08:** Federated fan-out is always-on by default. Every
  `service.search()` call queries all local engines plus all sources whose
  descriptor declares `FEDERATED_SEARCH` capability and whose lifecycle
  bundle is currently constructible.
- **D-09:** Each federated provider call has a per-source soft timeout
  (default in the 3-5 second range, tunable through config). The timeout is
  for failure detection, not throughput shaping. Latency is not a primary
  concern in v1.6 — the timeout exists so that one stuck source cannot block
  the whole response indefinitely.
- **D-10:** MCP-level source filtering parameters (`sources` allowlist /
  `exclude_sources` blocklist on the MCP search tool) are deferred. Phase 34
  ships always-on fan-out without selective opt-out at the MCP surface. The
  service-layer hook may exist where the implementation needs it for tests,
  but it is not part of the public MCP contract in this phase.

### Failure Mode

- **D-11:** Soft-skip per source on error or timeout. Service returns a
  `SearchResponse` envelope: `candidates: list[SearchCandidate]` plus
  `source_status: list[SourceStatus]` with one entry per fanned-out engine
  (status: `ok` / `skipped` / `error`, plus a brief reason). Local engines
  report through the same status surface for symmetry.
- **D-12:** No fail-fast. A flapping or down federated source must not break
  a query that local plus healthy sources could otherwise answer.

### Federated Read Semantics

- **D-13:** Federated candidates set `can_read: True` when the provider
  exposes `read_unit_window` for that unit type. `read(ref)` for a
  federated-only hit routes through the lifecycle bundle and the provider's
  `read_unit_window`, not the local store.
- **D-14:** No on-demand materialization in Phase 34. `can_materialize: False`
  for all MVP candidates. Trickle remains the single write path into the
  local index. The materialization path is deliberately deferred and may be
  reconsidered if live-read latency for repeated federated hits becomes a
  real operational pain.
- **D-15:** When `read(ref)` for a federated-only hit cannot reach the
  provider (down, timeout), the read returns a clear provider-attributed
  error. The agent sees the same `source_status`-style attribution as in
  search, so it understands why the read failed.

### Telegram Proof

- **D-16:** Phase 34 proves the contract end-to-end with mcp-telegram's
  `SearchMessages` as the first federated provider. Telegram candidates carry
  `ref = telegram:dialog:<id>:message:<id>` and round-trip through
  `read(ref)` (live `read_unit_window`) and `drill(ref)`
  (provider-sourced metadata) without requiring local indexing of the matched
  message.
- **D-17:** dotMD never owns the Telegram client. All Telegram FTS, message
  fetch, and metadata access goes through the existing mcp-telegram daemon
  socket. The Phase 33 lifecycle bundle is the single construction boundary
  for the Telegram runtime.

### Multi-Source Future

- **D-18:** The contract must be generic enough that gmail / slack / notion /
  voice-notes federated sources land later through descriptor +
  provider-implementation work only, with no Phase 34 contract edits. The
  test for "generic enough" is: adding a second federated provider in a
  later phase should not require renaming or restructuring `SearchCandidate`,
  `SearchResponse`, or fusion APIs.

### Claude's Discretion

- Exact Pydantic field names on `SearchCandidate` and `SourceStatus`, naming
  of the `engine_scores` diagnostic shape (dict vs nested model), and module
  placement of the soft-timeout logic — within the existing Pydantic /
  Protocol style.
- Whether `source_status` is a top-level field on `SearchResponse` or nested
  under a `meta` block — both are reasonable; pick one and stay consistent.
- Default per-source soft timeout value within the 3-5 second range. Tunable
  through config.
- Concrete shape of how `provider_metadata` is populated for Telegram
  (dialog title, sender, topic, etc.) — keep it provider-specific and
  inspectable, not part of the public contract.
- Whether the FastAPI `/search` route also returns the new
  `SearchResponse` envelope or stays on the previous shape for Phase 34. The
  MCP tool surface is the canonical proof; FastAPI may follow as a thin
  consequence.

### Folded Todos

No pending todos were folded into Phase 34. The keyword-only matches surfaced
by `gsd-sdk query todo.match-phase 34` were reviewed and routed elsewhere
(see Reviewed Todos in `<deferred>`).

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone And Phase Definition

- `.planning/ROADMAP.md` — Phase 34 goal, dependency on Phase 33, requirement
  mapping (SEARCH-01..SEARCH-04), and success criteria.
- `.planning/REQUIREMENTS.md` — SEARCH-01..SEARCH-04 v1.6 federated search
  requirements.
- `.planning/PROJECT.md` — Source architecture decisions, source-ref public
  identity, and active-binding visibility gate.
- `.planning/STATE.md` — Current workflow state and milestone progress.

### Prior Source Architecture Decisions

- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
  — Lifecycle bundle: descriptor + typed config + credential provider +
  cursor store + provider/source object. Phase 34 search routes through this
  boundary, not through bespoke per-source construction.
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md` — Descriptor
  stays declarative; `FEDERATED_SEARCH` is a capability flag on the
  descriptor; lifecycle owns runtime construction.
- `.planning/phases/29-telegram-adapter-mvp-ingestion/29-CONTEXT.md` —
  Telegram message refs (`telegram:dialog:<id>:message:<id>`), `mcp-telegram`
  daemon boundary, low-signal-message handling.
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md` —
  Minimal provider contract, `read_unit_window` semantics, source-unit
  boundary.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
  — Active binding as the public visibility gate. Federated read must not
  bypass this gate for locally-backed candidates.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  — Public source-ref-first read/search contract; no-full-reindex guardrail.

### Architecture Notes

- `docs/source-registry-airweave-mapping.md` — Airweave-to-dotMD capability
  mapping; `federated_search` capability lineage.
- `docs/source-adapter-architecture.md` — Source / document / unit model
  context.
- `docs/source-adapter-architecture-panel-review.md` — Prior expert-panel
  recommendations on source APIs and adapter boundaries.
- `docs/mcp-telegram-source-contract.md` — Telegram provider payloads and
  `read_unit_window` semantics; useful as the read path for federated-only
  Telegram hits in this phase.
- `docs/architecture.md` — Current architecture summary.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py:405` — Existing `SearchResult` (chunk-shaped,
  to be removed in favor of `SearchCandidate`).
- `backend/src/dotmd/core/models.py:75` — `SourceCapability.FEDERATED_SEARCH`
  enum value.
- `backend/src/dotmd/search/fusion.py` — Existing rank-only RRF (`fuse_results`
  and `build_search_results`). Fusion key changes from `chunk_id` to `ref` in
  this phase.
- `backend/src/dotmd/search/semantic.py`,
  `backend/src/dotmd/search/fts5.py`,
  `backend/src/dotmd/search/graph_direct.py` — Local engines that must emit
  ref-keyed ranked lists after the fusion-key change.
- `backend/src/dotmd/search/reranker.py` — Cross-encoder reranker; behavior is
  unchanged in this phase but the input shape moves to `SearchCandidate`.
- `backend/src/dotmd/api/service.py` — `DotMDService.search()` becomes the
  fan-out orchestrator returning `SearchResponse`.
- `backend/src/dotmd/mcp_server.py:75` — `SearchHit` MCP-tool model; replaced
  by the new `SearchCandidate` envelope.
- `backend/src/dotmd/ingestion/source_registry.py:100` — Telegram descriptor
  with `FEDERATED_SEARCH` capability already declared.
- `backend/src/dotmd/ingestion/telegram_provider.py` — Telegram provider /
  Unix-socket client; receives the new `search_native(query, limit)` method
  (or equivalent) that wraps mcp-telegram's `SearchMessages`.

### Airweave Reference

- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/search/executor.py`
  — Federated executor: parallel `asyncio.gather`, RRF merge of vector and
  federated results, per-source retries, fail-fast handling. dotMD adapts the
  parallel-fan-out and rank-only-RRF patterns and rejects the fail-fast
  failure mode.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/platform/sources/_base.py`
  — `federated_search: ClassVar[bool]` flag and `async def search(query, limit)`
  contract on BaseSource. dotMD adapts the capability-flag-plus-method shape
  but routes the construction through the Phase 33 lifecycle bundle.
- `/home/j2h4u/repos/airweave-ai/airweave/backend/airweave/domains/search/types/results.py`
  — Single `SearchResult` for both vector and federated, distinguished by
  `sync_id is None`. dotMD adapts the single-result-type idea but uses the
  source-ref public identity instead of an `entity_id` plus `sync_id`
  signaling.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceDescriptor` and `SourceCapability.FEDERATED_SEARCH` already exist
  from Phase 32. Telegram descriptor declares the capability; no descriptor
  changes are needed for the contract layer.
- The Phase 33 lifecycle bundle already builds Telegram and filesystem
  runtimes through one construction boundary. Federated search slots in as a
  method on the runtime bundle without inventing a second construction path.
- `IndexingPipeline` and `SQLiteMetadataStore` already enforce the active
  resource-binding visibility gate; federated read for local-backed
  candidates reuses the same gate.
- mcp-telegram already exposes `SearchMessages` as a daemon tool; no
  mcp-telegram changes are required to demo the proof.
- `_public_ref_for_provenance` in `search/fusion.py` already encodes
  Telegram's public message-level ref shape; the same logic applies to
  federated Telegram hits.

### Established Patterns

- dotMD prefers small Protocol / Pydantic boundaries over broad plugin
  frameworks.
- Public behavior flows through `DotMDService`, CLI, MCP, and FastAPI;
  storage internals do not become public integration APIs.
- Source refs are the public identity; chunk IDs and file paths are internal
  holder mechanics.
- Rank-only RRF — provider scores are never assumed to be directly
  comparable.
- Migrations and refactors are idempotent and avoid full reindex.

### Integration Points

- `DotMDService.search()` becomes the fan-out orchestrator: it spawns local
  engine queries plus per-federated-source `search_native` calls in parallel
  and aggregates results into a `SearchResponse` envelope with
  `source_status`.
- The Phase 33 lifecycle bundle is the source of `search_native` callables.
  Each bundle that has `FEDERATED_SEARCH` capability exposes a coroutine
  with shape `search_native(query: str, limit: int) -> list[SearchCandidate]`
  (exact name at the agent's discretion).
- Cross-encoder reranker keeps its current adapter contract; input switches
  to `SearchCandidate` with text snippets present.
- MCP `search` tool returns `SearchResponse` instead of a bare candidate
  list. `read(ref)` and `drill(ref)` MCP tools route federated-only refs
  through the lifecycle bundle's `read_unit_window`.

### Anti-Patterns To Avoid

- Treating provider-native scores as directly comparable across sources or
  with local cosine / BM25 / graph scores.
- Adding chunk-shaped fields (`semantic_score`, `keyword_score`,
  `graph_score`) to the public `SearchCandidate` contract — they belong in
  the optional diagnostic shape, not the public surface.
- Implementing on-demand materialization in this phase — explicitly deferred.
- Adding MCP-level source-filter parameters in this phase — explicitly
  deferred.
- Reintroducing fail-fast on federated provider errors — explicitly rejected.
- Reintroducing `chunk_id`-keyed fusion or any compat-shim aliasing
  `SearchResult` to `SearchCandidate`.
- Indexing federated message text into the local store as a side effect of
  search or read in this phase. Trickle remains the single write path.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly framed Phase 34 as "полный путь сразу" — so the
  unified-RRF path is in scope from day one, not as a follow-up.
- The user expects the public `search()` to be always-on across federated
  sources; per-call MCP-level source filters are explicitly deferred to a
  later phase, after a second federated provider exists and selective opt-out
  becomes meaningful.
- The user explicitly chose read-via-provider over on-demand materialization
  to keep the write path single (trickle) and avoid a second indexing
  pathway.
- The user explicitly chose soft-skip with notice over fail-fast; the
  `source_status` envelope is the agent-visible signal.
- The Airweave reference repo at `/home/j2h4u/repos/airweave-ai/airweave` is
  treated as architecture material only — patterns adapted (capability flag,
  parallel fan-out, rank-only RRF, single result type) and patterns rejected
  (fail-fast, runtime dependency, marketplace plumbing).

</specifics>

<deferred>
## Deferred Ideas

- **MCP source filters** (`sources` allowlist / `exclude_sources` blocklist)
  — defer to the phase that introduces a second federated source, where the
  filter becomes operationally meaningful.
- **On-demand materialization** of federated hits into the local index —
  defer until live-read latency for repeated federated hits is shown to be a
  real operational problem.
- **gmail / slack / notion / voice-notes federated sources** — out of scope
  for Phase 34. They land through descriptor + provider implementation work
  in later phases, on top of the contract this phase ships.
- **Per-source latency observability** (Grafana panels, structured timing
  events) — defer unless real ops pain emerges. Soft-timeout reasons in
  `source_status` give the first level of visibility for free.
- **Federated reranker behavior changes** — Phase 34 leaves the reranker
  alone; revisit only if federated text quality degrades reranking output.
- **FastAPI `/search` envelope migration** — at the agent's discretion in
  Phase 34; the canonical proof is the MCP tool. FastAPI alignment may
  follow as a thin consequence either inside Phase 34 or as a small
  follow-up.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` — Not
  folded; matched only on the generic `graph` keyword and is unrelated to
  the federated search contract.
- `2026-03-27-background-trickle-indexer.md` — Not folded; trickle work is
  unchanged by Phase 34 (read-via-provider explicitly chosen so trickle
  stays the single write path).
- `2026-03-27-smoke-tests.md` — Not folded; broader test-contract item, not
  Phase-34-specific.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` — Not folded;
  removed-source TTL is a separate lifecycle topic.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` — Not
  folded; embedding-model evaluation is unrelated to the federated contract.
- `2026-03-23-scout-other-dotmd-forks-for-ideas.md` — Not folded; out of
  scope for this phase.

</deferred>

---

*Phase: 34-Federated SearchCandidate contract*
*Context gathered: 2026-05-08*
