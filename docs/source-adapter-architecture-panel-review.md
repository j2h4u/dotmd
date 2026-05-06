# Source Adapter Architecture Expert Panel Review

This review evaluates `docs/source-adapter-architecture.md` before it becomes
an implementation plan. The panel treats the document as architectural context:
good enough to preserve decisions, but not yet a phase plan.

## Scope

Goal: stress-test the source adapter direction for indexing non-filesystem
sources such as Telegram, Notion, Google Docs, Perplexity, ChatGPT/Claude
exports, and future local services.

Decision type: architecture review and risk discovery.

Blast radius: cross-system. The design affects dotMD's ingestion model, search
result identity, MCP `read` semantics, persistent state, and integrations with
other local services.

## Panel

| Expert | Mandate |
|--------|---------|
| Product Manager | User value, scope, phased adoption, acceptance criteria |
| Power User: Personal Knowledge Search | Finds past conversations, notes, and decisions across sources |
| Power User: Agent Client | Uses dotMD through MCP from Claude/Codex/OpenCode |
| Retrieval Engineer | Search quality, chunking, fusion, reranking, snippets |
| Indexing/Data Engineer | Incrementality, fingerprints, deletes, schema evolution |
| Knowledge Graph Engineer | Entity resolution, cross-source identities, graph modeling |
| Integration Architect | Cross-service contract, adapter boundaries, source ownership |
| Source API Designer | Adapter API shape, cursors, pagination, references |
| Document Processing Engineer | File formats, parsers, extraction quality, parser versioning |
| Attachment/Asset Architect | Cross-source file-like assets, provenance, parser routing |
| Metadata Architect | Source/document/unit/chunk metadata boundaries |
| Security/Privacy Engineer | Secrets, private chats, least privilege, leakage risks |
| SRE/Ops Engineer | Runtime model, observability, backpressure, retries |
| QA/Evaluation Engineer | Test strategy, fixtures, regression gates |
| Kaizen Reviewer | Scope control, minimum viable abstraction, YAGNI pressure |

## Individual Assessments

### Product Manager

**Assessment:** The direction is product-correct: users want one search surface
for personal knowledge, not one tool per source. The document should make the
first valuable slice sharper.

**Risks:** A large abstraction phase could delay visible value. Users may not
care about source architecture until Telegram or Perplexity actually works.

**Recommendation:** Define the first product milestone as "search one
non-filesystem source through the same dotMD search/read flow" while keeping
the abstraction small.

**Open question:** Which first source proves the most value with the least
integration risk: Telegram local mirror or Perplexity exporter?

### Power User: Personal Knowledge Search

**Assessment:** The model matches the user need: "where did I discuss this?"
across chats, docs, AI threads, and notes. Results need human-readable source
labels and context windows more than perfect theoretical document modeling.

**Risks:** Search results can become confusing if refs are technically correct
but not recognizable. A hit like `telegram:dialog:12345:message:987` is not
enough without title, participant, date, and surrounding messages.

**Recommendation:** Treat display metadata as first-class: title, source label,
date, participants/authors, and source URI should be part of every result.

**Open question:** What does a cross-source result card need to show so a user
can decide whether to call `read`?

### Power User: Agent Client

**Assessment:** Agents need stable tool contracts more than rich UI. Phase 26
completed the shift to `read(ref)`, and future source work should preserve that
single search-to-read key.

**Risks:** If search returns mixed filesystem-path, document, chunk, and unit
identities without a clear rule, agents will call the wrong read path.

**Recommendation:** Keep a single canonical `ref` field in search results
before adding multiple source types. Filesystem paths may remain internal
compatibility metadata for local reads and holder mechanics, not the contract
center.

**Open question:** Should MCP expose a new `read_ref` tool first, or evolve the
existing `read` schema?

### Retrieval Engineer

**Assessment:** Keeping indexing/search centralized is the right decision. The
document correctly rejects per-source search stacks and gives dotMD ownership of
chunking, embeddings, FTS, graph, fusion, snippets, and reranking.

**Risks:** "Source unit" and "chunk" can drift apart unless provenance is
stored explicitly. Short chat messages will produce weak embeddings if every
message becomes a chunk by default.

**Recommendation:** Make `source_unit_refs[]` and `chunk_strategy` mandatory
for future chunks. Telegram should start with a message-window chunker, not a
strict one-message-one-chunk strategy.

**Open question:** What are the first chunking strategies that must be versioned
and benchmarked?

### Indexing/Data Engineer

**Assessment:** The document correctly separates source state from the search
index. That separation is important because cursors/fingerprints are source
sync concerns, while chunks/embeddings are dotMD index concerns.

**Risks:** Deletes and edits are under-specified. A source adapter that only
emits upserts will leave stale private content in the index.

**Recommendation:** `export_changes` must support at least `document_upsert`,
`document_delete`, `unit_upsert`, and `unit_delete`. Every event should carry a
monotonic source cursor or batch cursor.

**Open question:** Should dotMD store source units durably, or can it store only
chunks plus source fingerprints?

### Knowledge Graph Engineer

**Assessment:** The source adapter model must include entity catalogs, not only
documents and units. Contacts, Telegram users, Gmail addresses, and source-owned
person IDs can provide stronger graph identity signals than text extraction.

**Risks:** If cross-source linking is only string-based, common names will be
merged incorrectly. If entity catalogs are treated as documents, dotMD will
pollute the embedding corpus with reference data that belongs in graph/alias
layers.

**Recommendation:** Add `SourceEntity`, `Mention`, and `CanonicalEntity` as
separate graph concepts. Entity resolution edges must carry confidence,
evidence, and resolver metadata.

**Open question:** What source-provided identity signals should be considered
strong enough for automatic merge versus candidate-only linking?

### Integration Architect

**Assessment:** The pull-based adapter contract is the right normalization. It
works for local mirrors, cloud APIs, and private exporters without requiring
every source to implement webhooks.

**Risks:** An in-process plugin model and local daemon model solve different
problems. If the architecture forces one runtime shape, some sources will be
awkward: filesystem wants in-process; Telegram wants a local service boundary;
Perplexity wants an external exporter with browser state.

**Recommendation:** Define the contract at the protocol/model level, not the
runtime level. Support multiple adapter runtimes behind the same source
contract.

**Open question:** What is the first transport for out-of-process adapters:
Unix socket JSONL, HTTP, MCP, or command invocation?

### Source API Designer

**Assessment:** The proposed methods are close, but `export_document` and
`export_units` need clearer pagination and consistency semantics.

**Risks:** Cursor ambiguity can cause skipped records or duplicate indexing.
Opaque cursors are good, but dotMD still needs guarantees: idempotency,
ordering, and whether a cursor means "after this batch was fully consumed."

**Recommendation:** Define `export_changes(cursor, limit)` as returning
`items[]`, `next_cursor`, and `checkpoint_cursor`. dotMD should only persist the
checkpoint cursor after the corresponding index transaction commits.

**Open question:** Does the adapter need an explicit snapshot/session ID for
large sources whose content changes during export?

### Document Processing Engineer

**Assessment:** Filesystem is not the same axis as markdown. The filesystem
adapter should discover files and track changes, while format-specific parsers
turn Markdown, PDF, HTML, DOCX, or plain text into source units.

**Risks:** If each file format becomes its own source namespace, dotMD will
duplicate filesystem watching, checksums, deletes, and access policy. If all
formats are forced through the markdown parser model, PDFs and DOCX files will
produce poor chunks and bad snippets.

**Recommendation:** Add `media_type`, `parser_name`, and parser versioning to
document metadata. Keep `namespace = filesystem` for files, and choose parser
and chunk strategy per document.

**Open question:** Which parser outputs are good enough to become stable source
units for PDFs: page text, layout blocks, headings, or inferred sections?

### Attachment/Asset Architect

**Assessment:** PDF/DOCX/HTML support is not only a filesystem concern. The
same binary asset formats can arrive as Telegram attachments, Slack uploads,
Notion file blocks, Google Drive blobs, or local files.

**Risks:** If parser routing is tied only to filesystem paths, dotMD will need a
second asset pipeline for every non-filesystem source. If source provenance is
lost, search cannot explain whether a PDF hit came from a local folder, a chat
attachment, or a workspace upload.

**Recommendation:** Add `SourceAsset` as a separate concept. Source adapters
discover assets and preserve parent provenance; content parsers process assets
by `media_type`; chunks retain both `asset_ref` and parent document/unit refs.

**Open question:** Should assets be indexed as child documents, source units, or
a separate provenance layer that can produce source units?

### Metadata Architect

**Assessment:** Metadata needs explicit levels. Current markdown frontmatter is
already document metadata: `title`, `kind`, `tags`, and `participants` influence
chunking, embeddings, FTS, and graph without becoming chunk text.

**Risks:** A single `metadata_json` everywhere will be flexible but too vague.
Over-normalizing every possible field will be brittle across PDF, Notion,
Telegram, Google Docs, and exports.

**Recommendation:** Use normalized common fields plus raw `metadata_json` at
each level: source, document, asset, source unit, and chunk. Preserve the
current metadata-only fast-path idea for future sources where metadata changes
do not require body re-chunking.

**Open question:** Which fields must be normalized in the first source model
shim, and which can stay in raw metadata until a real source needs them?

### Security/Privacy Engineer

**Assessment:** This design indexes highly private data: personal Telegram DMs,
AI chats, internal docs, and possibly exported account data. The document needs
a stronger privacy section before implementation.

**Risks:** Source credentials, session cookies, raw mirrored content, deleted
messages, and generated snippets can leak. The most dangerous failure is
retaining content after the source deleted it.

**Recommendation:** Add source-level allowlists, explicit opt-in per source,
secret isolation, deletion propagation, and audit logs for source ingestion.
Never let adapters receive broader filesystem or database access than needed.

**Open question:** Should the default policy index only explicitly enabled
sources/documents, even for local services?

### SRE/Ops Engineer

**Assessment:** Pull-based sync is operationally easier than webhooks, but it
still needs backpressure, retries, and observability. Source adapters will fail
in different ways: rate limits, expired cookies, API outages, locked SQLite,
slow exports.

**Risks:** A bad adapter can block global indexing or overload an upstream
service. Perplexity-style browser exporters are especially fragile and should
not run inside the main dotMD process.

**Recommendation:** Source sync should be per-source isolated with status,
last success, last error, item counts, and duration metrics. Adapter failures
must be non-fatal to search and to other sources.

**Open question:** Should source sync run inside trickle, beside trickle, or as
a separate scheduler?

### QA/Evaluation Engineer

**Assessment:** The doc identifies the right architecture, but the test plan is
not yet present. This needs fixtures that simulate filesystem, Telegram, and
export-style sources before real integrations land.

**Risks:** Regressions will hide in edge cases: duplicate units, reordered
messages, deletes, edited messages, failed checkpoint commits, tiny chat
messages, large messages, source outages.

**Recommendation:** Build fake source adapters first. Tests should verify
contract behavior, idempotency, delete propagation, chunk provenance, and
read-window behavior before adding Telegram or Perplexity.

**Open question:** What is the minimum fake-source fixture set that proves the
abstraction without overbuilding?

### Kaizen Reviewer

**Assessment:** The architecture is directionally sound but large. The biggest
danger is trying to solve Notion, Google Docs, Telegram, Perplexity, ChatGPT,
Claude, and all runtime models in one phase.

**Risks:** The abstraction can become speculative. Every optional capability
added now creates schema, tests, docs, and migration burden.

**Recommendation:** First phase should only introduce the vocabulary and a
filesystem adapter shim while preserving behavior. Second phase should add one
real source. Do not build full mirror support until a source proves it needs it.

**Open question:** What can be postponed without blocking Telegram/Perplexity as
the first validation source?

## Panel Conflicts

| Topic | Position A | Position B | Resolution |
|-------|------------|------------|------------|
| First real adapter | Product: Telegram has strongest personal-search value | Kaizen/Ops: Perplexity exporter may be less invasive to dotMD data model | Keep phase 1 source-agnostic. Choose first adapter only after the model shim exists. |
| Adapter runtime | Integration: support in-process, daemon, and exporter runtimes | Kaizen: do not design all runtime types upfront | Define the data contract now; implement one runtime path first. |
| Filesystem formats | Document Processing: one filesystem source with per-format parsers | Kaizen: do not add PDF/DOCX before Telegram MVP | Model the axis now, implement only markdown in the first shim. |
| Cross-source assets | Asset Architect: PDFs/docs can come from any source and need one asset model | Kaizen: asset extraction is not MVP for Telegram text search | Add `SourceAsset` to the model now; implement asset parsing later. |
| Metadata shape | Metadata Architect: explicit source/document/asset/unit/chunk levels | Kaizen: do not design columns for every future source | Normalize only common fields now; keep source-specific data in `metadata_json`. |
| Source unit storage | Data: store source units for reproducible chunking | Security: storing raw units increases privacy risk | Start with fingerprints and chunk provenance; add durable raw source units only if read/rechunk requirements demand it. |
| Entity catalogs | Graph: contacts/users should be first-class source output | Retrieval/Kaizen: do not turn every contact into searchable corpus text | Model entity catalogs separately from documents; use them for graph, aliases, and display metadata, not default embeddings. |
| `read` migration | Agent user: add clear ref-first guidance | Product: one tool is simpler for users | Phase 26 settled on one canonical `read(ref=...)` tool. |
| Native source search | Integration: native search can help candidate generation | Retrieval: global ranking should stay centralized | Native search may be optional candidate provider, never the primary architecture. |
| Full mirror support | Data/Ops: mirrors improve reliability | Kaizen/Security: mirrors increase scope and data exposure | Treat mirrors as adapter capability, not baseline requirement. |

## Focused Panel Review: Source-Provided Entity Catalogs

User proposal:

> Each source may provide lists of entities, such as Telegram contacts, Google
> Contacts, Gmail addresses, and other identity catalogs. These are not
> necessarily documents to embed, but they may participate in FTS and graph
> linking.

### Knowledge Graph Engineer

**Assessment:** This is a strong proposal. Entity catalogs are the right way to
avoid relying only on text extraction for people and organizations. Telegram
user IDs, Google contact IDs, emails, and usernames are much stronger graph
signals than names found in prose.

**Concern:** Do not collapse `SourceEntity` and `CanonicalEntity`. A Telegram
user and a Google contact may refer to the same person, but the graph needs an
evidenced edge between them, not destructive merging.

**Recommendation:** Accept the proposal, but model it explicitly:
`SourceEntity -> candidate/confirmed CanonicalEntity`.

### Retrieval Engineer

**Assessment:** Entity catalogs can improve recall through query expansion:
searching for a person can expand to aliases, usernames, emails, and source
IDs. This is especially useful when documents mention a short name but contacts
contain the full identity.

**Concern:** Entity catalogs should not dominate ranking. A contact match alone
is not the same as a content hit. Otherwise searches for common names will
return irrelevant documents just because a contact exists.

**Recommendation:** Use entity catalogs as graph/alias signals and optional FTS
terms, but keep content hits and source evidence visible in scoring metadata.

### Indexing/Data Engineer

**Assessment:** This creates a second ingestion lane: document/unit changes and
entity catalog changes. That is manageable if entity cursors are separate from
content cursors.

**Concern:** Contacts change independently from messages or docs. A renamed
contact should not force content re-embedding, but it may require graph and
metadata refresh.

**Recommendation:** Add separate entity checkpoints/fingerprints and make
entity updates graph-only by default.

### Security/Privacy Engineer

**Assessment:** Contacts are highly sensitive. Importing a contact book can
expose private relationships, phone numbers, emails, and names that never
appeared in indexed documents.

**Concern:** Indexing all contacts by default may create searchable private
data the user did not expect to expose to agents.

**Recommendation:** Entity catalogs must be opt-in per source and per entity
type. Sensitive fields like phone numbers and emails need explicit policy:
stored for identity resolution does not necessarily mean exposed in search
snippets or MCP output.

### Source API Designer

**Assessment:** The adapter contract should include entity export, but not
force every adapter to implement it. Some sources have no useful entity catalog.

**Concern:** If entity export is bolted onto `export_changes`, content and
identity semantics will get mixed.

**Recommendation:** Add optional `export_entities(cursor, limit)` and declare
capability `entity_catalog`. Entity records should have stable `entity_ref`,
aliases, external IDs, and field-level metadata.

### Product Manager

**Assessment:** This directly supports a high-value user story: "find
everything related to this person across my systems." The Sergey Khabarov
example is exactly the kind of cross-source search users will understand.

**Concern:** Users need control. A wrong merge between two people with the same
name is worse than no merge because it creates false confidence.

**Recommendation:** Start with suggested links and explainable evidence. Add
manual confirmation later if automatic confidence is not enough.

### QA/Evaluation Engineer

**Assessment:** This is testable and should be tested early. The fake-source
fixtures should include contact catalogs and ambiguous names.

**Concern:** Happy-path tests with unique names will miss the hard part. The
system must handle "two Sergeys", renamed contacts, deleted contacts, and
messages that mention only first names.

**Recommendation:** Add entity-resolution fixtures:
same person across two sources, same name different people, alias-only match,
deleted/renamed contact, and email-only identity.

### Kaizen Reviewer

**Assessment:** The proposal is valid, but implementation should be staged.
Entity catalogs can easily become a large identity-management subsystem.

**Concern:** Building manual merge UI, rich contact import, and confidence
workflows before the first source adapter would stall the main architecture.

**Recommendation:** Phase 1 should only preserve the model and graph shape.
Real entity resolution can start with conservative exact external-ID and exact
email matches. Fuzzy/person-name merging can come later.

### Entity Catalog Verdict

The panel accepts the proposal with constraints:

1. Source-provided entity catalogs are a first-class optional adapter output.
2. Entity catalogs are not corpus documents by default.
3. Entity updates should not force content re-embedding unless chunk text
   actually changes.
4. `SourceEntity`, `Mention`, and `CanonicalEntity` must remain separate.
5. Identity links need confidence, evidence, and resolver metadata.
6. Contact import must be opt-in and privacy-aware.
7. Automatic merging should start conservative: stable external IDs and exact
   email/phone matches before fuzzy name matching.
8. FTS/alias expansion can use entity catalogs, but ranking must expose why a
   result matched.

## Recommended Plan

### Approach

Keep the architecture direction, but make the first implementation phase smaller
and more testable. Introduce source/document/unit identity inside dotMD without
changing external behavior for filesystem markdown. Then validate the contract
with one non-filesystem adapter.

### Key Decisions

1. **Centralized search remains mandatory.**  
   Sources own extraction/sync; dotMD owns chunking, embeddings, FTS, graph,
   fusion, reranking, snippets, and global ranking.

2. **The adapter contract is pull-based.**  
   `export_changes(cursor, limit)` is the core primitive. Webhooks and callbacks
   are optional source-internal mechanisms, not dotMD's integration contract.

3. **Runtime model is not the contract.**  
   Filesystem can be in-process, Telegram can be a local daemon, Perplexity can
   remain an exporter. They should all emit the same normalized documents,
   units, and changes.

4. **Filesystem source and file format are separate axes.**  
   Filesystem should own discovery/change detection. Markdown, PDF, HTML, DOCX,
   and other formats should be handled by parsers and chunk strategies under the
   same filesystem namespace.

5. **File-like assets can come from any source.**  
   A PDF from Telegram, Slack, Notion, Google Drive, or the filesystem should
   share parser/chunking infrastructure while preserving source provenance.

6. **Metadata has multiple levels.**  
   Source metadata, document metadata, asset metadata, source-unit metadata, and
   chunk metadata should stay distinct. Markdown frontmatter is today's document
   metadata example.

7. **Chunking is dotMD-owned, source-aware, and format-aware.**  
   Adapters provide source units and hints. dotMD creates final chunks using
   versioned chunk strategies.

8. **Deletes must be first-class.**  
   The future source contract must represent deleted documents and units before
   indexing private sources.

9. **Entity catalogs must be separate from corpus documents.**  
   Sources may provide contacts, users, email addresses, aliases, and stable
   external IDs. These should feed graph identity resolution, alias expansion,
   keyword lookup, and result display metadata, not default embedding corpus.

10. **Cross-source identity resolution needs evidence.**  
   Linking a person mentioned in Telegram to the same person in a transcript
   should use source entities, mentions, canonical entities, confidence, and
   evidence. String equality alone is not enough for permanent merges.

11. **Privacy must be part of the architecture, not a later hardening pass.**  
   Explicit opt-in, credential isolation, deletion propagation, and ingestion
   auditability are required for personal chats and AI conversations.

## Required Improvements To The Architecture Document

- Add an explicit "Privacy and Security Requirements" section.
- Add event types for `export_changes`: document/unit upsert/delete.
- Clarify cursor commit semantics: persist checkpoint only after index commit.
- State that display metadata is first-class for cross-source search results.
- Make `source_unit_refs[]`, `namespace`, `document_ref`, and `chunk_strategy`
  required future chunk provenance.
- Add `SourceEntity`, `Mention`, and `CanonicalEntity` concepts for
  cross-source identity resolution.
- Clarify that contact lists and source-owned entity catalogs are not corpus
  documents by default.
- Clarify the filesystem source versus file format/parser axis, including
  `media_type`, `parser_name`, and future parser versioning.
- Add a cross-source `SourceAsset` concept for PDFs, DOCX files, HTML, images,
  and other file-like attachments that can come from any source.
- Add a metadata model that separates source, document, asset, source-unit, and
  chunk metadata, with markdown frontmatter documented as the current document
  metadata example.
- Clarify that adapter runtime is flexible: in-process, local daemon, external
  exporter, or cloud API client.
- Add a "Testing Strategy" section with fake source adapters and delete/edit
  cases.
- Keep historical migration notes explicit: the old path-shaped read contract
  is superseded by `read(ref)`.

## Risk Register

| Risk | Severity | Mitigation |
|------|----------|------------|
| Stale deleted private content remains searchable | High | First-class delete events, delete tests, source audit log |
| Adapter leaks credentials or cookies | High | Per-source secret isolation, no broad filesystem access |
| Abstraction phase becomes too broad | High | Phase 1 filesystem shim only, no real cloud adapter |
| Mixed refs confuse MCP agents | Medium | Canonical `ref` field and compatibility plan |
| Different people with the same name get merged | High | Confidence-scored identity edges, strong/weak signal policy, candidate links |
| Contact catalogs pollute embedding corpus | Medium | Separate source entity catalogs from document/unit indexing |
| Short chat messages degrade vector quality | Medium | Message-window chunking strategy |
| Perplexity private API breaks | Medium | Keep exporter isolated; failure non-fatal to dotMD |
| Source scores become incomparable | Medium | Keep global ranking in dotMD |
| Cursor bugs skip records | Medium | Idempotent event handling and checkpoint-after-commit rule |

## Suggested MVP Phase Shape

The user wants a working minimum quickly, especially for Telegram, instead of
spending a long time building an ideal generic architecture first. The panel
agrees with this constraint. The architecture should be discovered through a
small real integration, not finalized in isolation.

### Phase 1: Minimal Source Model Shim

Deliver:

- `namespace`, `document_ref`, and canonical `ref` for filesystem results;
- filesystem adapter shim preserving current behavior;
- `media_type` and `parser_name` metadata for current markdown files, even if
  only the markdown parser exists initially;
- normalized markdown/frontmatter document metadata: `title`, `kind`, `tags`,
  and raw `metadata_json`;
- compatibility with current filesystem reads through `read(ref)`;
- only the tests needed to prove old filesystem behavior still works.

Do not deliver:

- Telegram integration;
- Perplexity integration;
- cloud credentials;
- full source mirrors;
- native source search.

### Phase 2: Telegram Read-Only MVP

Deliver:

- minimal export surface in `mcp-telegram` for synced dialogs/messages;
- Telegram adapter in dotMD;
- document = Telegram dialog/chat/channel;
- unit = Telegram message;
- simple message-window chunking with message ID provenance;
- search results with dialog title, sender/date, source label, and message
  range;
- a way to read context around a Telegram result.

Do not deliver:

- fuzzy cross-source identity resolution;
- Google Contacts/Gmail;
- Notion/Google Docs/Perplexity;
- native Telegram search integration;
- full mirror inside dotMD.

### Phase 3: Telegram Hardening From Real Usage

Deliver improvements only after using the MVP:

- chunking window tuning;
- snippet/read improvements;
- delete/edit propagation fixes;
- sync observability;
- fake-source and Telegram fixtures for edge cases seen in practice.

### Phase 4: Minimal Entity Catalog Layer

Deliver:

- Telegram users/entities as `SourceEntity`;
- graph links between messages/dialogs and source entities;
- conservative exact-ID matching only;
- no fuzzy name merging by default.

### Phase 5: Second Source Validation

Candidate choices:

| Candidate | Why choose it | Risk |
|-----------|---------------|------|
| Telegram | Highest personal-search value; stable `(dialog_id, message_id)` identity; local mirror exists | Requires changes in another service |
| Perplexity | Existing exporter already produces JSON/markdown; good external-exporter validation | Private API and browser automation fragility |

The panel now favors Telegram as the first real source because the user wants
hands-on validation quickly. Perplexity remains a good second-source validation
for the external-exporter runtime.

## Acceptance Criteria For The Future Plan

Before implementing a real source adapter, the plan should answer:

- How does a source emit deletes?
- Does the source emit entity catalogs separately from documents/units?
- Which source identity signals can auto-resolve entities, and which only
  create candidates?
- When exactly is a cursor checkpoint committed?
- What fields are required in every search result?
- How does `read` work for non-filesystem refs?
- What fake-source tests prove idempotency, edits, deletes, and read windows?
- What source data is stored permanently in dotMD, and what remains in the
  source service?
- How are source credentials isolated?
- What is the first real source and why?

## Final Panel Verdict

The architecture document is directionally strong and should be kept. The most
important refinements are privacy/deletes, cursor semantics, result display
metadata, test strategy, and a smaller first implementation phase.

The panel recommends proceeding with a dedicated `Document Source Abstraction`
phase, but only after tightening the architecture document with the required
improvements above.
