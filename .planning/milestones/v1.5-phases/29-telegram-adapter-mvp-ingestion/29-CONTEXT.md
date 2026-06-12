# Phase 29: telegram-adapter-mvp-ingestion - Context

**Gathered:** 2026-05-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Implement the Telegram adapter MVP ingestion path.

Phase 29 should ingest all currently available synced Telegram dialogs/messages
from the existing `mcp-telegram` runtime into dotMD as first-class Telegram
source documents and message source units with stable provenance. This phase
turns the Phase 28 provider contract into a real Telegram ingestion slice.

This phase is not full incremental sync hardening, not full public
`search -> read/drill` smoke, not lifecycle delete/edit policy, not media or
attachment indexing, not bidirectional Telegram actions, and not a direct
Telegram API client inside dotMD.

</domain>

<decisions>
## Implementation Decisions

### Dialog Scope

- **D-01:** Phase 29 should ingest all Telegram dialogs that are already
  available/synced through `mcp-telegram`. Do not add a separate dotMD
  allowlist in this phase.
- **D-02:** `mcp-telegram` remains the source of Telegram coverage and sync
  state. dotMD should consume the structured source export and focus on
  ingestion, provenance, indexing, and later search/read integration.

### Public Telegram Refs And Read Shape

- **D-03:** Public Telegram refs should point to concrete messages, using the
  established shape `telegram:dialog:<dialog_id>:message:<message_id>` or the
  equivalent source-ref form already supported by the code.
- **D-04:** `read(ref)` for Telegram should return a window around the target
  message, not only the target message and not the whole dialog. The target
  message remains the anchor.
- **D-05:** `drill(ref)` should expose Telegram source metadata for the dialog
  and target message without assuming filesystem frontmatter.

### Message Units, Search Chunks, And Short Messages

- **D-06:** A Telegram message remains the durable `SourceUnit` and
  recomputation/provenance boundary. Do not make word-count blocks, sessions,
  or whole dialogs the source-unit identity.
- **D-07:** Do not use artificial word-count merge blocks as the primary index
  identity. They improve semantic density but create ref ambiguity and make
  later incremental sync/reuse harder.
- **D-08:** Normal/substantive messages may be indexed as message-anchored
  chunks with compact Telegram metadata context such as dialog, sender, topic,
  timestamp, and reply metadata where available.
- **D-09:** Low-signal messages such as `ok`, `yes`, `+1`, emoji-only replies,
  and very short acknowledgements must still be stored as full Telegram
  `SourceUnit` records with provenance, but they should not be promoted as
  standalone normal search hits.
- **D-10:** Low-signal messages should surface through `read(ref)` windows and
  provenance around more substantive neighboring messages. If planning needs
  retrieval context for them, use a conservative anchored-context approach:
  the public ref still anchors to one concrete message and provenance records
  every included source unit.

### mcp-telegram Boundary

- **D-11:** dotMD must not read private `mcp-telegram` SQLite tables and must
  not parse human-rendered `list_messages` output as the durable ingest
  format.
- **D-12:** If the current `mcp-telegram` runtime lacks the structured source
  export needed by dotMD, Phase 29 should include the minimal cross-repo
  `mcp-telegram` change required to expose a machine-oriented export/source
  API for dotMD.
- **D-13:** The required API should stay aligned with the Phase 28 contract:
  source description, `export_changes(cursor, limit)`, checkpoint cursor
  semantics, and `read_unit_window(unit_ref, before, after)`.

### Validation And Smoke

- **D-14:** Phase 29 live smoke only needs to prove the ingestion boundary:
  `mcp-telegram export -> dotMD ingest -> Telegram records exist in dotMD
  metadata/index state`.
- **D-15:** Full public `search -> ref -> read/drill` live smoke remains Phase
  31 scope. Phase 29 should add enough initial resolver support and tests that
  Phase 31 can harden the public workflow without reopening ingestion scope.
- **D-16:** Fixture coverage should include short acknowledgements, duplicate
  short messages with different ids/senders/timestamps, rapid multi-person
  chats, topic/reply metadata, edited-message fingerprint changes, and
  unchanged replay/idempotency.

### Planning Aids

- **D-17:** Downstream research/planning agents may use the existing Graphify
  codebase graph to navigate relevant code relationships faster.
- **D-18:** Graphify output is advisory only. Any graph-derived finding must
  be verified against live source files before planning or implementing.

### the agent's Discretion

- Decide exact Python class/module names for the Telegram adapter and any small
  `mcp-telegram` client wrapper, as long as the provider contract stays
  structured and minimal.
- Decide the precise low-signal-message heuristic, but keep it conservative,
  deterministic, fixture-tested, and overrideable later if Phase 31 search
  smoke proves it too strict.
- Decide whether Phase 29 implements anchored-context indexing immediately or
  stores the necessary provenance first and leaves richer ranking behavior to
  Phase 31, as long as standalone low-signal hits do not dominate normal
  search.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone And Phase Definition

- `.planning/ROADMAP.md` - Phase 29 goal, requirements mapping, phase boundary,
  and relationship to Phases 28, 30, and 31.
- `.planning/STATE.md` - Current v1.5 workflow state and next-step routing.
- `.planning/REQUIREMENTS.md` - v1.5 requirements, especially R4 Telegram
  Provider Via mcp-telegram, R5 Telegram Source Units, R7 Telegram
  Search/Read/Drill Round-Trip, and R8 Validation And Smoke.
- `.planning/PROJECT.md` - Current milestone state and key decisions from
  Phase 28.

### Prior Source-Adapter Decisions

- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
  - Active/inactive resource bindings, retained artifacts, and public
  active-binding filtering.
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md`
  - Minimal provider contract, message-as-source-unit boundary,
  checkpoint-cursor semantics, and `mcp-telegram` boundary note.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
  - Minimal source/document/source-unit model and filesystem-first shim.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  - Source-ref-first public contract, `ref` as public identity, and no-full
  reindex guardrail.

### Architecture Notes

- `docs/mcp-telegram-source-contract.md` - Concrete Phase 29 boundary for
  Telegram `SourceDocument`, message `SourceUnit`, `export_changes`, cursors,
  and `read_unit_window`.
- `docs/source-adapter-architecture.md` - Source adapter architecture,
  provider methods, metadata layers, Telegram local mirror notes, and future
  source examples.
- `docs/source-adapter-architecture-panel-review.md` - Prior expert-panel
  concerns around refs, cursor commit semantics, events, deletes, and source
  adapter API shape.
- `docs/architecture.md` - High-level architecture and current source-adapter
  state.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py` - `SourceDocument`, `SourceUnit`,
  `SourceUnitWindow`, `ApplicationSourceChange`, `ApplicationSourceChangeBatch`,
  `ResourceBinding`, `ChunkProvenance`, and `SearchResult.ref`.
- `backend/src/dotmd/ingestion/source_provider.py` - Phase 28
  `ApplicationSourceProviderProtocol` with `describe_source`,
  `export_changes`, and `read_unit_window`.
- `backend/src/dotmd/ingestion/pipeline.py` - Indexing orchestration,
  source-document persistence, source-unit fingerprinting/reuse integration
  points, and chunk provenance persistence.
- `backend/src/dotmd/storage/metadata.py` - Resource bindings, source
  checkpoints, source-unit fingerprint storage, source-document storage, and
  chunk source provenance tables.
- `backend/src/dotmd/api/service.py` - Public search/read/drill facade and
  likely Telegram read/drill resolver integration point.
- `backend/src/dotmd/mcp_server.py` - Public MCP tools that Phase 31 will
  harden for Telegram-backed refs.
- `backend/tests/ingestion/test_application_source_provider.py` and
  `backend/tests/ingestion/application_source_fixtures.py` - Existing fixture
  provider coverage to extend for Telegram ingestion and edge cases.

### Codebase Navigation

- `.planning/graphs/` - Graphify-generated codebase graph output, if present.
  Use as a navigation aid only; verify all findings against source files.
- `graphify-out/` - Graphify generated reports, if present. Advisory only.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `ApplicationSourceProviderProtocol` already defines the right provider shape
  for Phase 29.
- `SourceDocument`, `SourceUnit`, `SourceUnitWindow`, and
  `ApplicationSourceChangeBatch` already model the Telegram dialog/message
  contract.
- `SQLiteMetadataStore` already has source checkpoint and source-unit
  fingerprint helpers from Phase 28.
- `ChunkProvenance.source_unit_refs` can represent chunks that include one
  anchor message plus supporting neighboring message refs.
- Existing application source fixture tests provide the starting point for
  Telegram-like batches, windows, cursors, and replay idempotency.

### Established Patterns

- Public behavior flows through `DotMDService`, MCP, CLI, and FastAPI; storage
  internals should not become public integration APIs.
- dotMD prefers small Protocol/Pydantic boundaries over broad plugin
  frameworks.
- Migrations/backfills should be idempotent, countable, and avoid full reindex.
- `mcp-telegram` owns Telegram auth, daemon behavior, local mirror/sync, and
  Telegram API details.
- Local fixtures are the right default for tests; targeted live smoke validates
  the runtime boundary.

### Integration Points

- A Telegram provider/client boundary should connect to the structured
  `mcp-telegram` export API, not private storage.
- The ingestion pipeline needs a path that persists Telegram source documents,
  source-unit fingerprints, resource bindings/provenance, and chunks without
  pretending Telegram messages are filesystem files.
- Read/drill resolver support should resolve Telegram message refs to provider
  windows/metadata while keeping full public search/read/drill smoke for Phase
  31.
- Planning may use Graphify graph output to identify affected modules, but
  must verify against the live files listed above.

</code_context>

<specifics>
## Specific Ideas

- Use all available synced Telegram dialogs from `mcp-telegram` for the MVP,
  rather than a separate dotMD allowlist.
- Anchor public results to concrete messages. Search can use richer retrieval
  context, but public identity remains message-shaped.
- Store short messages, but keep normal search results from being dominated by
  standalone acknowledgements.
- If a low-signal message needs retrieval context, prefer a deterministic
  anchored context chunk over word-count/session blocks.
- Live smoke should prove real export/import/metadata state only; Phase 31 owns
  full public search/read/drill smoke.

</specifics>

<deferred>
## Deferred Ideas

- Full incremental Telegram sync and changed-unit reuse hardening.
- Full public `search -> read/drill` live smoke.
- Full edit/delete/tombstone lifecycle policy.
- Attachments/media indexing.
- Bidirectional Telegram actions.
- Shared contact/entity catalog.
- Generic plugin marketplace or arbitrary source-app UI.
- Sliding-window ranking experiments or richer chat search quality tuning if
  Phase 31 smoke proves the conservative MVP too weak.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` - historical
  graph migration work, not Telegram ingestion scope.
- `2026-03-27-background-trickle-indexer.md` - may matter for Phase 30
  recurring/incremental sync scheduling, not Phase 29 MVP ingestion.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` - Phase 27
  already folded the retention intent; TTL remains lifecycle work.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` -
  embedding-model work, not Telegram ingestion scope.
- `2026-03-27-smoke-tests.md` - broader live smoke belongs later, especially
  Phase 31.
- `2026-03-23-scout-other-dotmd-forks-for-ideas.md` - broad research, not
  needed for this phase.

</deferred>

---

*Phase: 29-telegram-adapter-mvp-ingestion*
*Context gathered: 2026-05-07*
