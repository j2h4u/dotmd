# Source Adapter Architecture Context

This document captures the current design context for expanding dotMD beyond
filesystem markdown indexing. It is not an implementation plan yet. Its purpose
is to preserve the architectural decisions, vocabulary, trade-offs, and source
examples discussed before a future planning phase.

An expert-panel review of this context lives in
[Source Adapter Architecture Expert Panel Review](source-adapter-architecture-panel-review.md).

## Phase 26 Delivered State

Phase 25 shipped the first internal source-aware slice as a filesystem Markdown
compatibility shim. Phase 26 removed the public path-first compatibility layer:
current users still index Markdown files from the local filesystem, but public
search results now expose `ref` and MCP reads use `read(ref, start, end)` for
filesystem hits. Filesystem Markdown enters the pipeline through
`SourceDocument` identity and chunk provenance before any internal filesystem
holder path is used for local reads or content-dedup mechanics.

Canonical filesystem Markdown mapping:

```text
namespace = filesystem
document_ref = str(Path(file_path).resolve())
ref = filesystem:<document_ref>
media_type = text/markdown
parser_name = markdown
```

`SourceDocument.file_path` is an internal compatibility field for filesystem
sources. When `namespace = filesystem` and `file_path` is present, it must
resolve to `document_ref`; `file_path` is not the general source identity for
future sources and is not the public search/read contract. Frontmatter fields
that dotMD already depends on remain document metadata: `title`, `kind`,
`tags`, and `participants` live on the source document metadata layer and
continue to feed chunking, metadata embeddings, FTS metadata, and graph
extraction.

The Phase 25 storage split is intentionally additive:

- `source_documents` is one strategy-independent table keyed by
  `(namespace, document_ref)`.
- `chunk_source_provenance_<strategy>` is strategy-scoped because chunk IDs,
  chunk strategy, and source-unit refs belong to a chunking strategy.
- `chunk_file_paths_<strategy>` remains an internal filesystem/content-dedup
  holder table for filesystem discovery, local file reads, delete detection,
  and content-addressed chunk sharing. It is not the public search/read
  identity.

Filesystem Markdown chunks currently carry empty source-unit refs because Phase
25 did not add durable parser-emitted units. This keeps the shim minimal while
leaving `source_unit_refs[]` in the provenance contract for later source
slices.

Deferred scope remains explicit: Telegram read-only indexing, the
`mcp-telegram` export API, source-unit emission for non-filesystem sources,
source assets, entity catalogs, out-of-process adapter transports, TTL
retention policy, and second-source validation are not implemented by Phase 26.
PDF/DOCX/HTML parser support is also future work; it will still be
`namespace = filesystem` when it arrives, but with different `media_type`,
`parser_name`, parser output, and chunking behavior.

Current graph `File` nodes are filesystem-only legacy internals. Telegram
dialogs/messages must not be modeled as File; future Telegram work should use
`SourceDocument`/`SourceUnit` semantics rather than fitting chats into
filesystem nodes or path-shaped APIs.

No Phase 26 step requires `dotmd index --force`; full rebuild remains a
three-day cost/risk item requiring an explicit user decision.

## Phase 27 Delivered State

Phase 27 adds the retained-artifact lifecycle foundation for the existing
filesystem source. It does not ship Telegram ingestion, a Telegram export API,
attachments/media processing, a generic plugin UI, live Telegram smoke, or a
garbage-collection policy.

The current visibility rule is:

```text
active resource binding -> normal public search/read may expose the ref
inactive resource binding -> retained artifacts stay internal and hidden
```

`source_documents` remains the source of truth for active/current document
metadata, including title, source URI, parser metadata, fingerprints, and
filesystem compatibility fields. `resource_bindings` stores binding activity
plus retained fingerprint snapshots used to find equivalent content during
rebind. The retained rows are deliberately separate from public visibility:
chunks, provenance, FTS rows, vector rows, and graph artifacts may remain after
a resource becomes inactive, but normal public `search`, `read(ref)`, and
`drill(ref)` are active-binding gated.

Filesystem missing paths now deactivate the corresponding binding instead of
running the normal hard purge. This hides the ref from public output while
retaining reusable artifacts. Modified files still use replacement reindex
semantics, and successful reindex updates active binding fingerprints after the
new content is written. Restoring equivalent filesystem content can reactivate
the binding and reuse retained chunks/embeddings without TEI calls when content
and metadata fingerprints match.

Retained inactive artifacts are not a recycle bin or inactive browsing feature.
They exist to avoid recomputing expensive derived work. Garbage collection,
TTL, hard purge policy, and user-facing inactive-resource browsing remain
deferred until there is a concrete lifecycle requirement.

Telegram deletion semantics remain future work. Telegram messages that
`mcp-telegram` marks as deleted upstream are not modeled as Phase 27 resource
unbinds; that metadata should be preserved by the later Telegram adapter and
handled by future read/drill/display policy.

No Phase 27 step requires `dotmd index --force`, a full reindex, or a full
rebuild. The foundation was validated with local filesystem fixtures; live
Telegram smoke is deferred to the Telegram search/read/drill phase.

## Phase 28 Delivered State

Phase 28 adds the generic application-source provider contract and deterministic
fixtures for future non-filesystem sources. It does not ship Telegram ingestion,
an `mcp-telegram` implementation, attachments/media support, a generic plugin
marketplace, or common delete/hidden/tombstone lifecycle policy.

The minimal provider method set is now:

```text
describe_source()
export_changes(cursor, limit)
read_unit_window(unit_ref, before, after)
```

`export_changes` carries documents and units in one payload. For Telegram-like
sources this means a dialog arrives as `SourceDocument` and each message arrives
as a `SourceUnit`; document-only sources can use an implicit root unit. The
provider contract deliberately does not add separate `export_documents` or
`export_units` methods in Phase 28.

Cursor semantics are explicit. `next_cursor` is the provider continuation hint,
but it is not durable progress by itself. dotMD saves `checkpoint_cursor` only
after local source-document, source-unit fingerprint, binding/provenance, and
index persistence succeeds. This prevents a crash after cursor save from losing
source units that were never locally persisted.

`SourceUnit` is the provider-owned recomputation boundary for active application
records. The durable helper `source_unit_fingerprints` keys by
`(namespace, document_ref, unit_ref)` and classifies replayed active units with
the same fingerprint as unchanged. This makes repeated active exports
idempotent without promoting lifecycle delete/tombstone state into the common
contract.

The concrete `mcp-telegram` boundary for Phase 29 planning is documented in
[mcp-telegram Source Contract for dotMD](mcp-telegram-source-contract.md). dotMD
must consume structured provider payloads and must not read private
`mcp-telegram` SQLite tables directly.

No Phase 28 step requires `dotmd index --force`; the work is additive provider
models, fixture tests, and SQLite source-state tables.

## Phase 29 Delivered State

Phase 29 delivers the first concrete Telegram application-source slice. Telegram
data is consumed through the structured `mcp-telegram` daemon API, not by
importing Telethon, instantiating a Telegram API client inside dotMD, reading
private `mcp-telegram` SQLite tables, or parsing human-rendered message output.

Telegram maps to the existing source model as:

```text
namespace = telegram
SourceDocument.document_ref = dialog:<dialog_id>
SourceDocument.ref = telegram:dialog:<dialog_id>
SourceUnit.unit_ref = dialog:<dialog_id>:message:<message_id>
public message ref = telegram:dialog:<dialog_id>:message:<message_id>
```

A Telegram dialog, group, channel, or supergroup is a `SourceDocument`. A
Telegram message is a `SourceUnit`, and message-level fingerprints are the
recomputation boundary for later incremental sync. Phase 29 persists pathless
Telegram chunks with source-unit provenance, source-unit fingerprints, active
dialog resource bindings, FTS5 rows, sqlite-vec rows, and checkpoint metadata in
one local transaction per single provider batch.

Low-signal messages such as acknowledgements and emoji-only replies are still
stored as Telegram source units with fingerprints/provenance, but they are
suppressed as standalone normal chunks. They remain available through
message-window reads around neighboring substantive messages.

Initial `read(ref)` and `drill(ref)` support now accepts concrete message refs
such as `telegram:dialog:<dialog_id>:message:<message_id>`. The resolver checks
the active resource binding at dialog scope (`dialog:<dialog_id>`) and keeps the
target message ref as the read/drill anchor. If a configured Telegram provider
is available, `read(ref)` asks the provider for a bounded message window; if not,
it can return indexed Telegram chunks for the target source unit from local
provenance.

The live validation boundary for Phase 29 is intentionally limited to:

```text
mcp-telegram export -> dotMD single-batch ingest -> Telegram metadata/index state exists
```

Phase 31 still owns full public search/read/drill live smoke, including proving
that a live `search(query)` returns Telegram refs that round-trip through
`drill(ref)` and `read(ref, start, end)` with production data.

## Phase 32 Planned Source Registry

Phase 32 adds a source registry vocabulary before broader lifecycle work. Source
descriptors are declarative: they describe source kind, display metadata,
config schema, auth schema, cursor schema, and capability flags, but they do not
construct providers, read credentials, open clients, or persist cursor
checkpoints.

The initial registry seeds include filesystem and Telegram. Filesystem remains
a first-class source while local paths stay internal holder mechanics for
discovery, local reads, delete detection, parser routing, and
content-addressed reuse. Telegram remains an application source behind
`mcp-telegram`; dotMD still consumes structured provider payloads and does not
own Telegram API authentication or direct client access.

Lifecycle construction, credential access, auth policy, provider factories,
rate-limit handling, and cursor commit mechanics are Phase 33 scope. Phase 32
only defines typed descriptor contracts and default seed metadata that later
phases can consume.

The Airweave comparison is documented in
[Source Registry Airweave Mapping](source-registry-airweave-mapping.md)
(`docs/source-registry-airweave-mapping.md`). The
short version: dotMD adapts useful source catalog concepts such as config/auth
schemas and capability flags, but has no runtime Airweave dependency and does
not adopt Airweave organizations, billing, Temporal orchestration, or connector
marketplace mechanics.

## Phase 33 Delivered Source Lifecycle

Phase 33 adds the source lifecycle boundary that Phase 32 descriptors were
designed to feed. The lifecycle/factory constructs source runtime bundles from
registry descriptors, typed local config, credential/auth provider access,
cursor store access, and small runtime helpers such as source clients. The
bundle remains inspectable so future source phases can verify which descriptor,
config, access policy, cursor store, and provider/source object were used.

Filesystem and Telegram construction paths now route through lifecycle.
Filesystem paths remain internal holder mechanics for discovery, local reads,
delete detection, parser routing, and content-addressed reuse; they are not
promoted back into public source identity. Telegram remains delegated to
`mcp-telegram`: dotMD builds the local runtime wrapper, but does not own
Telegram API authentication, import direct Telegram clients, read private
Telegram SQLite tables, or store raw Telegram secrets.

Lifecycle cursor access preserves the Phase 28 rule for `checkpoint_cursor`.
The provider's `checkpoint_cursor` is durable progress only after local source
documents, resource bindings, source-unit fingerprints, chunks, FTS rows,
vectors, vector components, and checkpoint metadata succeed inside the same
local transaction. `next_cursor` remains only a provider continuation hint.
This construction-path migration does not require a full reindex.

## Phase 34 Delivered Federated Search Contract

Phase 34 extends the search and read contracts to support federated providers
alongside local indexing. Federated providers expose message-level search
results without requiring local full-text indexing, and return read context
for message refs that exist only in the provider's data store.

### SearchCandidate Envelope

The `SearchCandidate` model now includes:

- **`descriptor_key`** (new, cycle-2 HIGH-1): Stable identifier for the source
  descriptor. Distinct from `namespace` (which identifies the adapter tier) and
  `source_kind` (which identifies the logical content type). Enables
  future UI/filtering by specific source configuration without parsing
  `namespace` strings.
- **`provider_metadata`**: Optional dict of source-specific attributes
  (e.g., Telegram: dialog_id, message_id, sender, sent_at, dialog_name).
  Whitelist enforced at provider construction prevents leaking credentials,
  phone numbers, or auth tokens.
- **`source_native_rank`**: Zero-based rank for hits from a federated provider
  (e.g., FTS rank 0, 1, 2, ... for a 5-hit response).
- **`can_materialize`**: Phase 34 enforces `False` for all federated candidates.
  Materialization (storing search results back to local index) is deferred.

### Search Execution (Local + Federated)

`search_async()` is the canonical async method. `search()` is a synchronous
wrapper for CLI/test use only; it fails loudly if called from an active event
loop (cycle-2 HIGH-5 D-ASYNC-CANONICAL).

Local search engines (semantic, FTS, graph) run sequentially within a request,
protected by a single-worker `ThreadPoolExecutor` (max_workers=1) named
`dotmd-local-search` (cycle-2 HIGH-4, cycle-4 HIGH D-LOCAL-SERIALIZED). This
ensures SQLite metadata/graph access is single-threaded per request. Concurrent
search_async() calls across different requests queue instead of running in
parallel.

Federated providers fan out in parallel via `asyncio.gather()`. Each provider
has a soft timeout (4s default, configurable); local engines have no soft
timeout.

Lifecycle build failures are caught per-source and surfaced as persistent
`SourceStatus(status="error")` entries in every subsequent `SearchResponse`.
Service initialization never crashes due to a single misconfigured source
(cycle-2 HIGH-6 D-LIFECYCLE-GRACEFUL).

Source status envelope (cycle-2 HIGH-2):

```python
source_status = [
    {"name": "semantic", "status": "ok", "elapsed_ms": 123},
    {"name": "keyword", "status": "ok", "elapsed_ms": 45},
    {"name": "graph_direct", "status": "ok", "elapsed_ms": 78},
    {"name": "tg:fts", "status": "ok", "elapsed_ms": 234},  # federated provider
]
```

Engine naming convention: local engines use their operation name (semantic, keyword,
graph_direct); federated providers use `<namespace>:<retrieval_kind>`
(e.g., `tg:fts` for Telegram FTS search).

### Read/Drill Routing (Local-First, Three-Way Dispatch)

Federated `read(ref)` and `drill(ref)` use a **local-first three-way routing**
that preserves the Phase 27 active-binding gate for locally-indexed sources
(cycle-2 HIGH-7 D-LOCAL-FIRST-TG-READ):

1. **LOCAL_ACTIVE**: ref exists in local store with active binding → use local
   chunks path (existing).
2. **LOCAL_INACTIVE**: ref exists in local store but binding is inactive
   → raise `PermissionError`. Phase 27 visibility gate is preserved; refs
   with inactive local bindings do NOT fall back to federated providers.
3. **FEDERATED_ONLY**: ref has no local-store presence at all → call provider's
   `read_unit_window(unit_ref, before, after)` to fetch context from the
   provider. No local chunks involved.

Error handling: Provider failures are attributed via `RuntimeError("telegram: ...")`
containing the provider name and the underlying error (D-15).

### Telegram Federated Provider

The Telegram provider implements `search_native()` to expose FTS search via the
mcp-telegram daemon socket. The daemon method `search_messages` returns:

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

Telegram refs follow the shape `telegram:dialog:<id>:message:<id>`. The provider
derives `can_read` at construction time from a runtime capability check:
`callable(getattr(provider, "read_unit_window", None))` (cycle-2 MEDIUM fold-in
D-13). Future providers without `read_unit_window` emit candidates with
`can_read=False`.

`source_native_rank` is **zero-based** for all federated providers.
A 3-hit response carries ranks [0, 1, 2]. This convention is documented in
provider implementations and test suites.

### Generic Federated Contract

The Telegram federated contract is structured to be reusable for gmail/slack/
notion/voice sources without Phase 34 edits:

- `SearchCandidate`, `SearchResponse`, `SourceStatus` envelopes are source-
  agnostic.
- `FederatedSearchProviderProtocol` (base protocol) abstracts `search_native()`
  behavior.
- Service fan-out is implemented once in `_run_federated_engine()` for all
  providers.
- New federated sources add a descriptor in the registry + provider implementation,
  then register through `SourceRuntimeFactory.build_if_configured()`.
  Zero changes to search envelope or fan-out glue required.

## Problem

dotMD currently indexes markdown files from the local filesystem. That is too
narrow for the data we want to search:

- local service mirrors, such as a Telegram account mirror in SQLite;
- cloud knowledge tools, such as Notion and Google Docs;
- AI chat products, such as Perplexity, ChatGPT, and Claude;
- future local services that store useful text in SQLite, DuckDB, or APIs.

The existing search stack is valuable and should be reused:

- source-aware chunking;
- semantic vector retrieval;
- SQLite FTS5 keyword retrieval;
- graph-direct entity retrieval;
- RRF/fusion;
- cross-encoder reranking;
- snippets and read context.

The goal is to make source ingestion more general without duplicating this
search-quality stack per source.

## Core Direction

dotMD should become an indexer of documents from sources, not an indexer of
files.

The future conceptual shape is:

```text
namespace/source -> document -> source unit -> chunk
```

Filesystem markdown remains one source adapter, not the central abstraction.

Source, asset location, and content format are separate axes. A filesystem
source can discover many file formats, and each format may need a different
parser and chunking strategy:

```text
filesystem source -> markdown parser -> markdown source units -> chunks
filesystem source -> PDF parser -> page/section source units -> chunks
filesystem source -> HTML parser -> DOM/article source units -> chunks
filesystem source -> DOCX parser -> paragraph/table source units -> chunks
```

The same format axis also applies to files or attachments that arrive from
non-filesystem sources:

```text
telegram source -> attached PDF asset -> PDF parser -> source units -> chunks
slack source -> attached PDF asset -> PDF parser -> source units -> chunks
notion source -> uploaded PDF asset -> PDF parser -> source units -> chunks
```

The filesystem adapter owns file discovery, file identity, and change
detection. Other sources own their native document/message identity and attached
asset discovery. Format parsers own content extraction and native structure.
dotMD chunk strategies own final retrieval chunks.

## Key Concepts

### Namespace

A stable source namespace. Examples:

```text
filesystem
telegram
notion
google_docs
perplexity
chatgpt_export
claude_export
```

The namespace scopes document IDs, unit IDs, cursors, fingerprints, and adapter
state.

### Document

A logical object recognizable to a user.

Examples:

| Source | Document |
|--------|----------|
| Filesystem | One file |
| Telegram | One dialog/chat/channel |
| Notion | One page |
| Google Docs | One document |
| Perplexity | One thread |
| ChatGPT/Claude export | One conversation |

Example fields:

```text
namespace
document_ref
title
source_uri
media_type
parser_name
parser_version
document_type
updated_at
fingerprint
metadata_json
```

Document metadata should use a hybrid shape:

- normalized fields used by dotMD directly (`title`, `document_type`, `tags`,
  `source_uri`, `updated_at`, `media_type`, `parser_name`);
- source/parser-specific `metadata_json` for everything else.

Markdown frontmatter is the current example of document metadata. In the future,
PDF metadata, Google Docs metadata, Notion page properties, Telegram dialog
metadata, and imported export metadata should flow into the same conceptual
layer, even though their raw fields differ.

### Source Asset

A binary or file-like object discovered inside a source document or source
unit. Assets can come from any source, not only the filesystem.

Examples:

| Source | Asset |
|--------|-------|
| Filesystem | `report.pdf`, `contract.docx`, `page.html` |
| Telegram | PDF/document attachment, image with OCR text, voice transcript |
| Slack | Uploaded PDF/document, thread attachment |
| Notion | Uploaded file block, embedded PDF |
| Google Drive | Blob file or exported Workspace document |

Example fields:

```text
namespace
asset_ref
parent_document_ref
parent_unit_ref
source_uri
media_type
filename
size_bytes
content_fingerprint
metadata_json
```

Assets should be routed through content parsers by `media_type` and parser
policy. This prevents "PDF from Telegram" and "PDF from filesystem" from
becoming unrelated ingestion designs.

### Source Unit

A natural structural unit from the source before dotMD chunking.

Examples:

| Source | Source unit |
|--------|-------------|
| Filesystem | Heading section, paragraph, speaker turn |
| Telegram | Message |
| Notion | Block |
| Google Docs | Paragraph, list item, table element |
| Perplexity | Conversation entry / turn |
| ChatGPT/Claude export | Message or turn |

Example fields:

```text
namespace
document_ref
unit_ref
unit_type
text
order_key
updated_at
fingerprint
metadata_json
chunking_hints
```

### Source Entity

A source can also provide entities that are not themselves corpus documents.
Examples:

| Source | Entity catalog |
|--------|----------------|
| Telegram | Users, bots, channels, groups, usernames, contact-like dialog metadata |
| Google Contacts | People, names, email addresses, phone numbers |
| Gmail | Email addresses and display names observed in mail headers |
| Notion | Users and page/database authors if available |
| Filesystem | Frontmatter authors, explicit people metadata |

These entities are not necessarily embedded as searchable documents. They are
reference data for graph linking, entity resolution, aliases, and possibly
keyword lookup.

Example fields:

```text
namespace
entity_ref
entity_type
canonical_label
aliases[]
external_ids[]
metadata_json
updated_at
confidence
```

Entity catalogs should be optional adapter output. A source may provide
documents only, entities only, or both.

### Chunk

An indexable dotMD retrieval unit. Chunks are produced by dotMD from source
units.

A chunk may map to:

- one source unit;
- a range of source units;
- part of a large source unit.

Chunks should store provenance:

```text
namespace
document_ref
chunk_id
chunk_strategy
source_unit_refs[]
text
metadata_json
```

## Responsibility Split

### Source Service / Adapter Owns

- authentication to the upstream system;
- native API or local database access;
- source-specific sync mechanics;
- stable native identity;
- change discovery;
- source metadata;
- read windows around native units, when the source can provide them.

### dotMD Owns

- chunking strategy selection;
- embeddings;
- FTS5 indexing;
- graph extraction;
- vector/keyword/graph fusion;
- reranking;
- snippets;
- global search;
- index schema and search-quality evaluation.

Adapters should not write directly into search tables. They provide normalized
documents and source units; dotMD decides what to index.

## Source Adapter Contract

A future adapter should expose a pull-based export contract. dotMD asks what
changed; the source adapter returns normalized records.

Minimal conceptual methods:

```text
describe_source()
export_changes(cursor, limit)
read_unit_window(unit_ref, before, after)
```

The cursor should be opaque to dotMD. Each adapter owns its cursor semantics.
`export_changes` returns active document/unit changes together in Phase 28.
`checkpoint_cursor` is durable only after dotMD's local persistence succeeds;
`next_cursor` alone is not durable progress.

Example refs:

```text
filesystem:/mnt/home/docs/example.md
telegram:dialog:12345
telegram:dialog:12345:message:987654
notion:page:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee
google_docs:document:1abc...
perplexity:thread:uuid
```

## Persistence Model

Source adapters need persistent state, but not every source needs a full local
mirror.

### Source State

Almost every adapter needs thin persistent state:

```text
source_checkpoints:
  namespace
  checkpoint_cursor
  last_success_at
  last_error

source_unit_fingerprints:
  namespace
  document_ref
  unit_ref
  fingerprint
  updated_at
  indexed_at
```

This should be shared infrastructure, not custom SQLite code invented by every
adapter.

Phase 27's `resource_bindings` table is the first concrete binding-state slice,
not the full source-state platform. It tracks active/inactive resource
visibility and retained fingerprint snapshots for rebind lookup. Future source
state still needs adapter-specific sync state before Telegram or other
application sources are complete. Phase 28 adds checkpoint cursor and
source-unit fingerprint helpers, but delete/hidden/tombstone lifecycle remains
deferred from the common contract.

### Source Mirror

A full mirror is optional. It is useful when:

- the upstream API is expensive or rate-limited;
- offline indexing matters;
- the source is already a local mirror;
- debugging source extraction requires durable raw data.

Telegram already has a mirror in `mcp-telegram`. Notion and Google Docs can
start with thin state. A future adapter can add mirror tables only when needed.

## Metadata Model

Metadata exists at several levels. These levels should not be collapsed into
one generic dictionary.

### Source Metadata

Describes the source adapter and sync state:

```text
namespace
source_kind
capabilities
enabled
cursor
last_success_at
last_error
sync_policy
```

Examples: filesystem path specs, Telegram daemon connection, Notion workspace,
Google Drive account, Perplexity exporter state.

### Document Metadata

Describes a user-recognizable document:

```text
document_ref
title
document_type
source_uri
media_type
parser_name
parser_version
created_at
updated_at
tags
metadata_json
```

Markdown frontmatter currently fills this role. Existing frontmatter fields
such as `title`, `kind`, `tags`, and `participants` are document metadata, not
chunk text.

Current behavior:

- dotMD discovers only `.md` files;
- YAML frontmatter is parsed by the markdown reader;
- frontmatter is stripped before chunk text is produced;
- `kind` selects content handling such as default document, meeting transcript,
  or voicenote;
- `title + tags` are embedded as a separate metadata vector component;
- `title/tags` feed FTS metadata;
- `tags` and transcript `participants` feed graph nodes/edges.

Future behavior should preserve the same idea for other formats and sources:

- PDF metadata stays document/parser metadata;
- Google Docs file metadata and document properties stay document metadata;
- Notion page properties stay document metadata;
- Telegram dialog metadata stays document metadata for the dialog document;
- raw source-specific fields live in `metadata_json`.

### Asset Metadata

Describes file-like objects inside sources:

```text
asset_ref
parent_document_ref
parent_unit_ref
filename
media_type
size_bytes
content_fingerprint
metadata_json
```

This is where Telegram PDF attachments, Slack uploads, Notion file blocks, and
filesystem PDFs differ by provenance but can share parser routing.

### Source Unit Metadata

Describes native source units before chunking:

```text
unit_ref
unit_type
order_key
author/sender
timestamp
reply/thread/topic metadata
metadata_json
```

Examples: Telegram message fields, Notion block type, Google Docs paragraph
position, Perplexity conversation entry metadata.

### Chunk Metadata

Describes the retrieval unit produced by dotMD:

```text
chunk_id
chunk_strategy
source_unit_refs[]
asset_ref
heading_path
message_range
metadata_json
```

Chunk metadata should preserve provenance. It should not become the only place
where source/document metadata is stored.

## Source Patterns

### Attachments and Binary Assets Across Sources

File-like content can originate from many sources. A PDF may be a local file, a
Telegram attachment, a Slack upload, a Notion file block, or a Google Drive
blob. The parser and chunk strategy should depend on the asset format, while
provenance should preserve the source where the asset came from.

Example:

```text
namespace = telegram
document_ref = telegram:dialog:12345
unit_ref = telegram:dialog:12345:message:987654
asset_ref = telegram:dialog:12345:message:987654:asset:1
media_type = application/pdf
parser_name = pdf
```

The resulting chunks should still point back to both the asset and its parent
source unit/message. This lets search explain that a PDF hit came from a
Telegram message attachment rather than from a local filesystem file.

### Filesystem Source With Multiple Formats

The filesystem is a source adapter, but markdown is only one content format
handled by that source. Future support for PDF, HTML, DOCX, plain text, or other
file types should not require a separate "filesystem-like source" for each
format.

The split should be:

```text
FilesystemSource:
  discovers paths
  tracks mtime/checksum/fingerprint
  emits document records with media_type/parser_name

ContentParser:
  markdown -> headings/paragraphs/speaker turns
  pdf -> pages/blocks/sections
  html -> headings/article/dom blocks
  docx -> paragraphs/tables/headings

ChunkStrategy:
  turns parser source units into dotMD chunks
```

Current markdown files map as:

```text
namespace = filesystem
document = file
source_unit = section / paragraph / speaker turn
media_type = text/markdown
parser_name = markdown
```

This adapter should preserve current behavior while the internal model stops
treating `file_path` as the universal identity.

Current implementation note:

- dotMD currently discovers `.md` files only;
- `.txt` is not a separate supported parser today;
- `voicenote` is a markdown/frontmatter `kind`, not a `.txt` format;
- YAML frontmatter is the current metadata extraction mechanism for filesystem
  markdown.

PDF or DOCX files would still be `namespace = filesystem`, because discovery
and change detection are filesystem concerns. They would differ by `media_type`,
`parser_name`, source-unit shape, and chunk strategy.

This distinction matters for incremental indexing:

- file creation/change/delete is detected once by the filesystem source;
- parser selection happens per changed document;
- only parser/chunk outputs for that document need to be refreshed;
- switching a PDF parser or chunk strategy should not require rethinking the
  filesystem source contract.

### Telegram Local Mirror

`mcp-telegram` already has the main primitives needed for a source adapter:

- `sync.db`;
- `dialogs`;
- `messages`;
- stable `(dialog_id, message_id)` identity;
- sync statuses such as `synced`, `own_only`, `fragment`, and `access_lost`;
- a daemon API over Unix socket.

The missing piece is an export-oriented API. Existing MCP tools like
`list_messages` and `search_messages` are agent-facing, not indexing-facing.

Suggested additions to `mcp-telegram`:

```text
export_documents(cursor, limit)
export_changes(cursor, limit)
export_units(document_ref, cursor, limit)
read_unit_window(unit_ref, before, after)
```

Telegram mapping:

```text
namespace = telegram
document_ref = dialog:<dialog_id>
unit_ref = dialog:<dialog_id>:message:<message_id>
public_ref = telegram:dialog:<dialog_id>:message:<message_id>
document = dialog/chat/channel
unit = message
```

dotMD should not read `mcp-telegram` SQLite tables directly. That would couple
dotMD to another service's private schema. `mcp-telegram` should export
normalized documents and units.

### Notion

Notion is naturally document/unit based:

```text
document = page
unit = block
```

The adapter can use Notion page/block IDs and `last_edited_time`. It probably
does not need a full mirror at first. Thin state with page/block fingerprints
should be enough for an MVP.

Important property: Notion block IDs can be stable source-unit refs.

### Google Docs

Google Docs is document-oriented:

```text
document = Google Doc
unit = paragraph/list/table element
```

Drive metadata and change tracking can identify changed files. Inside a changed
document, stable paragraph IDs are less obvious than Telegram message IDs or
Notion block IDs, so the adapter may need to rebuild source units and let dotMD
compare fingerprints.

Google Docs is a good example where document-level change detection may be
stronger than unit-level native identity.

### Perplexity

The local `perplexport` project already acts as a private web API exporter:

- authenticates through Puppeteer and email OTP;
- stores session cookies;
- calls Perplexity private REST endpoints from the browser context;
- exports library threads and Spaces;
- writes raw JSON and markdown;
- tracks progress in `done.json`.

Perplexity mapping:

```text
namespace = perplexity
document = thread
unit = conversation entry / turn
group = space
```

This should not be imported into dotMD as "markdown files from a folder" if we
want a clean architecture. `perplexport` can evolve into an exporter adapter
that emits normalized source documents and units. The markdown output can stay
as a human backup artifact.

### ChatGPT and Claude

For ChatGPT and Claude web products, there may be data exports but not a stable
public incremental API for personal chat history.

These should be treated as export/capture sources:

```text
source_kind = batch_export
document = conversation
unit = message / turn
```

For new conversations created through our own tooling, a better pattern is
capture-at-creation:

```text
ai_chat_journal:
  provider
  conversation_id
  message_id
  role
  text
  artifact/file/citation metadata
  created_at
  model
```

dotMD then indexes the local journal through the same source adapter contract.

## Chunking Direction

Chunking should be source-aware but remain dotMD-owned.

Source adapters provide natural structure and hints. dotMD turns source units
into chunks using configured strategies.

For filesystem documents, chunking is also format-aware. Markdown, PDF, HTML,
DOCX, and plain text can share filesystem discovery but still use different
parsers and chunking strategies.

Examples:

| Source | Chunking strategy |
|--------|-------------------|
| Filesystem docs | Heading/paragraph/speaker-turn aware |
| Filesystem PDFs | Page/section/layout-aware, depending on parser output |
| Filesystem HTML | Heading/article/DOM-block aware |
| Filesystem DOCX | Paragraph/table/heading aware |
| Telegram | Message/window aware |
| Notion | Block/tree aware |
| Google Docs | Paragraph/list/table aware |
| Perplexity | Query/answer/citation-turn aware |

Telegram example:

- base source unit: message;
- normal chunk: one message or a small window of adjacent messages;
- very short messages may be merged;
- very long messages may be split;
- chunk metadata preserves message ID range.

The source adapter may provide hints:

```json
{
  "hard_boundary": false,
  "soft_boundary_after": true,
  "group_key": "dialog:123:topic:general",
  "order_key": "0000000987"
}
```

But it should not precompute final embedding chunks by default.

## Search Direction

Each source should not own its own full search stack. That would duplicate:

- embeddings;
- FTS;
- graph extraction;
- fusion;
- reranking;
- snippets;
- evaluation;
- migrations.

It also makes global search hard because source-local scores are not naturally
comparable.

Preferred split:

```text
Sources own extraction and sync.
dotMD owns indexing and search.
```

Native source search can be used as an optional additional candidate provider,
but the canonical global ranking should remain in dotMD.

## Cross-Source Entity Resolution

General source adapters create another requirement: graph identities must span
sources.

Example user-facing goal:

> A search for a person's full name should be able to connect a Telegram dialog
> participant, a transcript mention, a meeting note, and a contact record when
> evidence supports that they refer to the same person.

This requires separating three concepts:

```text
SourceEntity:
  entity as provided by a source, such as telegram:user:123 or google_contact:abc

Mention:
  a textual or structured occurrence inside a document/chunk, such as
  a full-name mention in a transcript chunk

CanonicalEntity:
  dotMD's resolved cross-source identity, such as person:sergey-khabarov
```

The graph should not treat every matching string as the same person. It should
record resolution edges with evidence:

```text
(:Chunk)-[:MENTIONS]->(:Mention)
(:Mention)-[:RESOLVES_TO {confidence, evidence, resolver}]->(:CanonicalEntity)
(:SourceEntity)-[:SAME_AS {confidence, evidence, resolver}]->(:CanonicalEntity)
(:Document)-[:HAS_PARTICIPANT]->(:SourceEntity)
```

### Strong and Weak Signals

Strong signals:

- Telegram user ID;
- Google contact ID;
- email address;
- phone number;
- explicit frontmatter/person metadata;
- source-owned stable person ID.

Medium signals:

- exact full name match plus relevant context;
- username/display-name match;
- transcript title or meeting metadata matching a known contact.

Weak signals:

- first name only;
- fuzzy name match;
- role/title similarity without a stable identifier.

Weak signals should not silently create permanent canonical merges. They can
produce candidate links or low-confidence graph edges, but users and future
tools need a way to inspect or override them.

### Entity Catalogs Are Not Documents

Contacts and identity catalogs are a different kind of source output. A Google
Contacts adapter, for example, may provide almost no corpus text worth
embedding, but it can still provide high-value graph data:

```text
google_contact:abc
  name = Person Example
  aliases = ["Sergey Khabarov"]
  emails = [...]
  phones = [...]
```

This data should participate in:

- graph identity resolution;
- alias expansion;
- keyword/FTS lookup for names and emails where useful;
- result display metadata.

It should not automatically become embedding corpus text unless a source has
meaningful document-like content.

### Search Implications

Cross-source identity resolution can improve search by expanding from one
signal to related signals:

```text
query: Person Example
  -> exact text matches
  -> canonical person entity
  -> Telegram user/source entity
  -> documents/chunks where this entity participates or is mentioned
```

This should be an augmentation of retrieval, not a replacement for text/vector
search. All identity expansion should preserve explainability in result
metadata so the user can see why a Telegram chat, transcript, or note matched.

## Read Semantics

The current MCP API is source-ref-first. Agents should follow:

```text
search(query) -> ref
drill(ref) -> source metadata
read(ref, start, end) -> chunk text
```

Search results should return:

```text
ref
heading?
snippet
score
```

For filesystem hits, `ref` is `filesystem:<document_ref>`, with
`document_ref = str(Path(file_path).resolve())`. This lets clients read context
from a Telegram message, Notion block, Google Doc paragraph, Perplexity turn,
or filesystem document through one surface once those sources exist.

`drill(ref)` is the metadata follow-up. It returns source metadata such as
frontmatter, title, source URI, document type, parser name, and chunk count.
Optional graph/entity enrichment is intentionally deferred until that shape is
stable for non-filesystem sources.

`read(ref)` uses the active configured chunk strategy only. Phase 26 does not
scan alternate `chunk_file_paths_<strategy>` holder tables per request.

## Non-Goals and Rejected Directions

### FUSE as the Main Integration Layer

FUSE would let other sources pretend to be markdown files, but it adds fragile
operational complexity:

- mount lifecycle;
- permissions;
- caching;
- modification times;
- deletes and renames;
- Docker/host boundary issues;
- hard-to-debug failures.

It may be useful as an emergency bridge, but it should not be the architecture.

### Per-Source Search Stacks

Building vectors, FTS, graph retrieval, fusion, snippets, and reranking inside
each source service would multiply complexity and make global search quality
harder to reason about.

### Direct Reads From Other Services' Private Tables

Reading another service's SQLite/DuckDB schema directly is tempting, but creates
tight coupling. Prefer a stable export contract owned by the source service.

## Open Questions

- What is the exact storage schema for `documents`, `source_units`, and source
  state in dotMD?
- Should source adapters run in-process, as local daemon clients, or both?
- What is the first non-filesystem adapter to implement: Telegram or
  Perplexity?
- Which migration note, if any, should be kept for historical clients that used
  the old Phase 25 path-shaped read contract?
- How should deletes be represented in `export_changes`?
- Should dotMD store source-unit raw text permanently, or only the produced
  chunks plus fingerprints?
- Which chunking strategies should be versioned first?
- Which metadata fields should be normalized into columns versus preserved only
  in `metadata_json`?
- How should metadata-only changes be detected per source and parser, analogous
  to current markdown frontmatter `title/tags` handling?
- How should parser versions and chunk strategy versions interact for
  filesystem formats such as Markdown, PDF, HTML, and DOCX?
- How should binary assets and attachments be represented when the same format
  can arrive from filesystem, Telegram, Slack, Notion, or Google Drive?
- How should adapter capabilities be declared?

Possible capabilities:

```text
stateful_cursor
unit_fingerprints
entity_catalog
identity_resolution_hints
local_mirror
native_search
read_windows
batch_export
capture_at_creation
```

## Suggested Future Phase

A future milestone should not try to implement the ideal architecture in one
step. The goal is to get a working minimum with Telegram, use it, observe real
edge cases, and then harden the architecture with evidence.

The overall workstream can still be framed as:

```text
Document Source Abstraction
```

But it should be split into small phases.

### Phase 1: Minimal Source Model Shim

Goal: introduce only the minimum internal model needed to stop treating
`file_path` as the universal identity.

Deliver:

- `namespace`, `document_ref`, and canonical result `ref` for filesystem
  documents;
- document metadata fields for the current markdown/frontmatter case:
  `media_type=text/markdown`, `parser_name=markdown`, `document_type/kind`,
  `title`, `tags`, and raw `metadata_json`;
- compatibility with current filesystem indexing through `search(query) ->
  ref`, `drill(ref)`, and `read(ref, start, end)`;
- a filesystem adapter shim that preserves current behavior;
- no Telegram integration yet;
- no entity resolution implementation;
- no full source-state platform beyond what the shim actually needs.

This phase should avoid changing search quality. It is plumbing and contract
prep, not a feature launch.

### Phase 2: Telegram Read-Only MVP

Goal: make Telegram searchable through dotMD as soon as possible with a thin
vertical slice.

Deliver:

- minimal export endpoint or CLI in `mcp-telegram` for synced dialogs/messages;
- dotMD Telegram source adapter that consumes the export;
- document model: one Telegram dialog/chat/channel is one document;
- source unit model: one Telegram message is one unit;
- conservative chunking: message-window chunks with message ID provenance;
- search results that show source label, dialog title, date, sender, and
  message range;
- `read(ref)` for Telegram context windows;
- preserve deleted-upstream metadata from `mcp-telegram` if available in
  `sync.db`, without treating that metadata as a Phase 27 unbind rule.

Do not deliver:

- Google Docs, Notion, Perplexity;
- contact imports;
- fuzzy cross-source entity merging;
- native Telegram search as a candidate provider;
- Telegram recycle-bin behavior;
- full mirror inside dotMD.

This phase is successful when real Telegram chats can be searched from the same
MCP surface as filesystem notes.

### Phase 3: Telegram Hardening From Usage

Goal: improve the MVP based on real searches and observed failures.

Likely work:

- tune Telegram chunking windows;
- handle very short and very long messages better;
- improve snippets and read context;
- add sync status/error visibility;
- improve delete/edit propagation;
- add fake-source and Telegram fixture tests for observed edge cases;
- decide whether source-unit raw text must be stored in dotMD or can stay in
  `mcp-telegram`.

This phase should be driven by actual search sessions, not speculation.

### Phase 4: Minimal Entity Catalog Support

Goal: add the smallest useful graph identity layer after Telegram search is
already usable.

Deliver:

- source-provided Telegram entities/users as `SourceEntity`;
- graph links from Telegram messages/dialogs to Telegram source entities;
- exact identity matching only for strong signals;
- no fuzzy person-name merge by default;
- no Google Contacts/Gmail import yet unless Telegram proves the graph path.

This phase should make searches for a person explainably connect to
Telegram participants when the evidence is strong, but avoid speculative
automatic merges.

### Phase 5: Second Source Validation

Goal: validate that the abstraction is not Telegram-specific.

Good candidates:

- Perplexity exporter, because `perplexport` already exports structured JSON;
- Notion, because page/block structure maps well to document/unit;
- Google Docs, because it tests document-level change detection and weaker
  unit identity.

Only start this after the Telegram MVP has produced enough lessons to update
the source contract.

### MVP Bias

For the first working version, choose the simplest thing that gives real search
value:

- pull-based export, not webhooks;
- one real source, not a generic plugin marketplace;
- conservative refs and provenance, not full identity management;
- source-aware chunking for Telegram, not a universal perfect chunker;
- explicit known limitations documented in the phase summary.
