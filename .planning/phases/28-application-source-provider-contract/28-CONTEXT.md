# Phase 28: application-source-provider-contract - Context

**Gathered:** 2026-05-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Define and implement the smallest generic provider contract for
application-backed sources.

Telegram via the existing `mcp-telegram` runtime is the first validation
source, but the contract must be reusable for later sources such as Slack,
Notion, PDFs from different origins, and other application exports.

This phase should produce the dotMD provider protocol, a fixture provider,
source/cursor model support needed for planning the Telegram adapter, and a
small `mcp-telegram` contract note with example payloads.

This phase is not Telegram ingestion, not full incremental Telegram sync, not
direct Telegram API ownership inside dotMD, and not a broad plugin marketplace
or enterprise integration framework.

</domain>

<decisions>
## Implementation Decisions

### Provider Contract Shape

- **D-01:** Phase 28 should define a minimal generic provider contract, not a
  Telegram-only import path and not a broad plugin framework.
- **D-02:** The contract must work for future sources such as Slack, Notion,
  PDFs, and other services. Telegram is the first proof source, not the only
  design target.
- **D-03:** dotMD must not read `mcp-telegram` private SQLite tables directly.
  Any Telegram data consumed by dotMD must come through a structured,
  machine-oriented export/source contract.
- **D-04:** The minimum provider methods for Phase 28 are:
  `describe_source`, `export_changes(cursor, limit)`, and
  `read_unit_window(unit_ref, before, after)`.
- **D-05:** `export_changes` is the core pull primitive. For this phase it
  returns active records only, not mandatory delete/hidden/tombstone events.
  Full delete/hidden lifecycle semantics remain deferred.
- **D-06:** Do not add separate `export_documents` or `export_units` methods in
  Phase 28 unless research proves they are necessary for the smallest working
  contract. Documents and units can be included in `export_changes` payloads.

### Cursor And Sync Progress

- **D-07:** The provider contract should include `checkpoint_cursor`
  semantics. dotMD saves the checkpoint only after the corresponding local
  persistence/indexing transaction succeeds.
- **D-08:** A single simple `next_cursor` is not sufficient as the only durable
  progress marker because saving it too early can lose data after a crash.
- **D-09:** Provider processing must be idempotent: seeing the same active
  record and fingerprint again should be safe and should not force redundant
  indexing work.

### Documents And Units

- **D-10:** Every provider must expose a stable `SourceDocument` envelope.
  Examples: Telegram dialog, Slack channel/thread, Notion page, PDF document.
- **D-11:** dotMD should process content through a unified `SourceUnit` shape.
  Providers emit real units when the source naturally has them, and dotMD can
  normalize simple document-only sources into one implicit root unit.
- **D-12:** Telegram should use real message units from the start. Slack should
  later use message/thread units. Notion and PDFs may begin with an implicit
  root unit and later move to block/page/section units when stable parsing
  makes that useful.
- **D-13:** A `SourceUnit` is the smallest provider-owned sync/indexing item
  that dotMD can fingerprint and reuse. It should not be over-modeled with
  source-specific Telegram/Slack/Notion concepts in the generic contract.
- **D-14:** Required minimum fields for a `SourceUnit` are `namespace`,
  `document_ref`, `unit_ref`, `text`, `fingerprint`, `updated_at`,
  `order_key`, and `metadata_json`.
- **D-15:** Lifecycle status such as `deleted`, `hidden`, or `tombstone` is not
  mandatory in Phase 28. Providers may carry such source-specific state in
  `metadata_json`, and a later lifecycle phase can promote it into the common
  contract if needed.

### Read Window

- **D-16:** `read_unit_window(unit_ref, before, after)` should be required by
  the provider contract.
- **D-17:** Providers that do not have meaningful neighboring units may return
  a fallback window containing only the requested unit.
- **D-18:** This keeps `search -> ref -> read/drill` behavior consistent while
  avoiding artificial complexity for simple sources.

### mcp-telegram Boundary

- **D-19:** Phase 28 should include a short `mcp-telegram` contract note with
  example payloads, not a full `mcp-telegram` implementation plan.
- **D-20:** The note should show Telegram dialog as `SourceDocument`, Telegram
  message as `SourceUnit`, `export_changes(cursor, limit)` with
  `checkpoint_cursor`, and `read_unit_window(unit_ref, before, after)` with
  neighboring message context.
- **D-21:** The note should be concrete enough that Phase 29 can plan Telegram
  ingestion without re-opening the integration boundary.

### Codebase Research And Planning

- **D-22:** Research and planning may use graphify/codebase graph outputs to
  navigate relationships and find relevant code clusters faster.
- **D-23:** graphify is advisory only. Downstream agents must verify graphify
  findings against live source files before making a plan or code change.

### the agent's Discretion

- Decide exact Python names for provider protocol classes and payload models as
  long as they follow existing Protocol/Pydantic style and remain minimal.
- Decide whether the fixture provider lives under ingestion, tests, or a small
  provider module, as long as it exercises the provider contract without live
  Telegram.
- Decide the exact shape of `metadata_json` examples, but keep common fields
  minimal and avoid encoding Telegram-specific semantics into generic models.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone And Phase Definition

- `.planning/ROADMAP.md` - Phase 28 goal, requirements mapping, phase boundary,
  and relationship to Phases 27 and 29.
- `.planning/STATE.md` - Current v1.5 workflow state and next-step routing.
- `.planning/REQUIREMENTS.md` - v1.5 requirements, especially R3 Application
  Source Provider Contract, R4 Telegram Provider Via mcp-telegram, and R8
  Validation And Smoke.

### Prior Source-Adapter Decisions

- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
  - Minimal source/document/source-unit model and filesystem-first shim.
- `.planning/phases/26-source-ref-first-read-search-contract-cleanup/26-CONTEXT.md`
  - Source-ref-first public contract, `ref` as public identity, and no-full
  reindex guardrail.
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
  - Active/inactive resource bindings, retained artifact reuse, and public
  active-binding filtering.

### Architecture Notes

- `docs/source-adapter-architecture.md` - Source adapter contract concepts,
  provider methods, source state/cursors, Telegram local mirror notes, and
  future source examples.
- `docs/source-adapter-architecture-panel-review.md` - Prior expert-panel
  concerns about cursor commit semantics, idempotency, events, and source
  adapter API shape.
- `docs/architecture.md` - Current high-level architecture and Phase 27
  retained-artifact boundary.

### Current Code Surfaces

- `backend/src/dotmd/core/models.py` - `SourceDocument`, `SourceUnit`,
  `ResourceBinding`, `ChunkProvenance`, and source-ref validation patterns.
- `backend/src/dotmd/ingestion/source.py` - Current filesystem
  `SourceAdapterProtocol` and `FilesystemMarkdownSourceAdapter` shim.
- `backend/src/dotmd/ingestion/pipeline.py` - Indexing orchestration,
  source-document persistence, retained rebind logic, and integration point for
  provider-fed units.
- `backend/src/dotmd/storage/metadata.py` - Resource bindings, source
  documents, provenance tables, active filtering helpers, and likely location
  for source checkpoint/fingerprint persistence.
- `backend/src/dotmd/api/service.py` - Public search/read/drill facade and
  active-binding gate.
- `backend/src/dotmd/mcp_server.py` - Public MCP contract that future
  Telegram-backed refs must round-trip through.

### Codebase Navigation

- `.planning/graphs/` - graphify-generated codebase graph output, if present.
  Use as navigation aid only; verify all findings against source files.
- `graphify-out/` - graphify generated reports, if present. Advisory only.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceDocument` already provides `(namespace, document_ref, ref)` identity
  and source metadata.
- `SourceUnit` already exists as a Pydantic model and is the natural place to
  express provider-owned content units.
- `ResourceBinding` already stores active/inactive resource visibility and
  fingerprint snapshots from Phase 27.
- `FilesystemMarkdownSourceAdapter` demonstrates the existing Protocol-style
  source boundary and can guide naming/style, but Phase 28 should not force
  application sources through filesystem path semantics.
- `chunk_source_provenance_<strategy>` and `resource_bindings` already provide
  the active public visibility substrate that provider-fed units must connect
  to later.

### Established Patterns

- dotMD prefers small Protocol boundaries and Pydantic models over broad
  framework abstractions.
- Public behavior goes through `DotMDService`, MCP, CLI, and FastAPI surfaces;
  storage internals should not become public source-provider APIs.
- Migrations and backfills should be idempotent, countable, and avoid full
  reindex.
- Local tests should use fixtures and not require live Telegram; live runtime
  smoke belongs later in the milestone.

### Integration Points

- `backend/src/dotmd/ingestion/source.py` is the current source discovery
  boundary and likely needs the next provider protocol or adjacent module.
- `backend/src/dotmd/core/models.py` likely needs small provider payload models
  or tightened `SourceUnit` semantics.
- `backend/src/dotmd/storage/metadata.py` likely needs thin source checkpoint
  and source-unit fingerprint persistence.
- `backend/src/dotmd/ingestion/pipeline.py` will later consume provider
  changes and normalize document-only sources into implicit root units.
- A fixture provider should exercise `describe_source`, `export_changes`, and
  `read_unit_window` without touching `mcp-telegram`.

</code_context>

<specifics>
## Specific Ideas

- Minimal contract nucleus:
  `describe_source`, `export_changes(cursor, limit)`,
  `read_unit_window(unit_ref, before, after)`.
- `export_changes` should return active records and `checkpoint_cursor`.
- Telegram example:
  `SourceDocument(namespace="telegram", document_ref="dialog:<id>")` and
  `SourceUnit(unit_ref="dialog:<id>:message:<message_id>")`.
- PDF example:
  start as one implicit root unit; later move to page or section units only if
  parser output is stable enough to make that useful.
- Keep future Slack/Notion viability explicit in docs and tests, but do not
  build those providers in Phase 28.

</specifics>

<deferred>
## Deferred Ideas

- Telegram ingestion implementation.
- Full incremental Telegram sync.
- Full delete/hidden/tombstone lifecycle in the common provider contract.
- Separate `export_documents` and `export_units` methods.
- Direct Telegram API client inside dotMD.
- Generic plugin marketplace or UI for arbitrary source apps.
- Slack, Notion, Google Docs, and PDF parser implementation beyond contract
  examples/fixtures.

### Reviewed Todos (not folded)

- `2026-03-24-migrate-graph-store-from-ladybugdb-to-falkordb.md` - historical
  graph migration work, not provider contract scope.
- `2026-03-27-background-trickle-indexer.md` - may matter later for Phase 30
  sync scheduling, not Phase 28 contract capture.
- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` - Phase 27
  already folded the retention intent; TTL remains deferred lifecycle work.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` -
  embedding-model work, not source-provider contract scope.
- `2026-03-27-smoke-tests.md` - broader live smoke belongs later, especially
  Phase 31.
- `2026-03-23-scout-other-dotmd-forks-for-ideas.md` - broad research, not
  needed for this phase.

</deferred>

---

*Phase: 28-application-source-provider-contract*
*Context gathered: 2026-05-07*
