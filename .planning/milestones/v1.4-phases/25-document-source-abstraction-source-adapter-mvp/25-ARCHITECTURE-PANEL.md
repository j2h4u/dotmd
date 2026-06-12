# Phase 25 Architecture Panel: Filesystem Source Shim

**Date:** 2026-05-05
**Input context:**
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`

## Scope

Phase 25 should reproduce current filesystem Markdown indexing through a new
source-aware internal model. The phase should not implement Telegram, Notion,
Perplexity, PDF/DOCX parsing, entity catalogs, or cross-source identity
resolution.

Decision type: domain model and contract narrowing before implementation
planning.

Blast radius: cross-system. The contract touches ingestion identity, chunk
provenance, incremental indexing, metadata persistence, search result shape,
and MCP `read` compatibility.

## Panel Verdict

The panel agrees Phase 25 should be a compatibility-preserving shim:

```text
filesystem source -> markdown parser -> markdown source units -> dotMD chunks
```

The implementation should introduce source-aware identity internally while
keeping current user-visible behavior stable. The phase is successful when the
same Markdown corpus can be indexed and searched as before, but the indexing
path no longer treats raw `file_path` as the only durable identity concept.

## Expert Assessments

### Product Manager

**Assessment:** The first valuable step is risk reduction, not a new source.
Users should see no regression while the system becomes ready for future
sources.
**Risk:** If Telegram is pulled in now, the phase becomes too large to validate
cleanly.
**Recommendation:** Define acceptance as "current Markdown corpus works through
the new model with the same search/read behavior."

### System Architect

**Assessment:** The source model should enter at the domain boundary, not as
random columns sprinkled across storage.
**Risk:** A half-migration can produce two competing identities: file paths in
some layers, refs in others.
**Recommendation:** Introduce explicit model objects for source document,
source unit, and chunk provenance, then map filesystem Markdown into them.

### Indexing/Data Engineer

**Assessment:** Incrementality is the hard requirement. The current
`chunk_checksum()` and `meta_checksum()` split is valuable and must survive.
**Risk:** A generic adapter event model could accidentally force full
re-chunking or re-embedding on metadata-only changes.
**Recommendation:** Preserve separate body/kind fingerprint and metadata
fingerprint semantics in the new filesystem adapter contract.

### Retrieval Engineer

**Assessment:** Search quality should not change in this phase. The retrieval
stack already works and should receive the same chunk text and metadata signals.
**Risk:** Changing source-unit boundaries can change embeddings, FTS contents,
and graph extraction in ways that look like adapter work but are actually
search behavior changes.
**Recommendation:** Keep Markdown chunk text and frontmatter-driven kind
behavior equivalent. Version any new chunk provenance fields without changing
chunking strategy unless required.

### Agent Client

**Assessment:** Agents already know `search` returns file paths and `read`
accepts a file path. Breaking that in the shim phase would damage daily use.
**Risk:** Introducing `ref` without compatibility rules can confuse clients:
should they call `read(file_path)` or `read(ref)`?
**Recommendation:** Add canonical `ref` internally and, if exposed, as additive
metadata. Do not remove `file_paths` or break existing `read(file_path, start,
end)` during Phase 25.

### Metadata Architect

**Assessment:** Markdown frontmatter is already document metadata. The new model
should make that explicit instead of flattening everything into chunk metadata.
**Risk:** A single generic `metadata_json` can hide fields that dotMD actively
uses for chunking, embeddings, FTS, and graph.
**Recommendation:** Normalize the fields dotMD depends on now: title, kind,
tags, participants, source URI/path, media type, parser name, updated time, and
fingerprints. Keep source-specific leftovers in `metadata_json`.

### Security/Privacy Engineer

**Assessment:** Phase 25 does not add new data exposure if it stays filesystem
only, but it must not weaken delete handling or access boundaries.
**Risk:** Future-source concepts like raw source-unit mirrors can increase
private data retention if added speculatively.
**Recommendation:** Do not durably store raw source units beyond what current
chunk/search/read behavior requires. Preserve current delete behavior and defer
TTL/retention policy changes.

### QA Engineer

**Assessment:** The shim needs regression tests more than broad new-source
tests.
**Risk:** Tests that only check object construction will miss behavior drift in
search/read results.
**Recommendation:** Use a fake/minimal filesystem adapter fixture plus
behavioral checks for discovery, frontmatter metadata, chunk provenance,
metadata-only fast path, deletes, search hydration, and MCP read compatibility.

### SRE/Ops Engineer

**Assessment:** Runtime behavior should not become more complex in this phase.
The existing container and startup checks should keep working.
**Risk:** Adding schedulers, source daemons, or source health dashboards now
creates operational surface before a real non-filesystem source exists.
**Recommendation:** Keep the adapter in-process for filesystem. Defer
out-of-process adapter runtime, per-source sync status, and retry/backpressure
machinery.

### Kaizen Reviewer

**Assessment:** The minimum useful abstraction is enough. Phase 25 should make
the next phase easier, not solve every future source.
**Risk:** Modeling `SourceAsset`, `SourceEntity`, contacts, identity resolution,
and adapter transports now will create unused abstractions.
**Recommendation:** Define future-reserved terms in docs, but implement only
what the filesystem Markdown shim needs.

## Panel Conflicts

| Topic | Position A | Position B | Resolution |
|-------|------------|------------|------------|
| Expose `ref` now | Agent Client: additive `ref` helps clients migrate early | QA: any new public field needs tests and docs | Add `ref` only if planner can keep it additive and covered; do not make clients depend on it yet. |
| Store source units durably | Data: useful for reproducible re-chunking | Security/Kaizen: stores more raw private data and expands scope | Do not add durable raw source-unit storage in Phase 25 unless the current behavior cannot be reproduced without it. Store provenance and fingerprints first. |
| Add asset/entity tables now | Architecture docs reserve these concepts | Kaizen: unused tables become speculative schema | Do not implement assets or entity catalogs. Keep docs aware, not runtime schema. |
| Change MCP `read` | Agent Client: future `read(ref)` is needed | Product/QA: current users rely on `read(file_path)` | Keep current `read` stable. Any ref-aware read path must be additive and explicitly tested, or deferred. |
| Delete semantics | Security: deletes must be first-class for future private sources | Phase scope: current filesystem delete behavior already exists | Preserve current delete behavior. Do not add TTL or retention policy in this phase. |

## Locked Contract For Planning

### Minimum Domain Objects

Planning should define the smallest implementation shape for:

- `SourceDocument` or equivalent: `namespace`, `document_ref`, `ref`, `title`,
  `source_uri`, `media_type`, `parser_name`, `document_type`, `updated_at`,
  body/content fingerprint, metadata fingerprint, and `metadata_json`.
- `SourceUnit` or equivalent: `namespace`, `document_ref`, `unit_ref`,
  `unit_type`, `text`, `order_key`, `fingerprint`, `metadata_json`, and optional
  chunking hints.
- Chunk provenance: `namespace`, `document_ref`, `source_unit_refs[]`,
  `chunk_strategy`, optional `parser_name`, and existing chunk text/heading
  metadata.

Names may change during implementation, but these concepts must remain visible.

### Filesystem Markdown Mapping

The filesystem adapter should map today's Markdown path as:

```text
namespace = filesystem
document_ref = stable normalized path/ref for one Markdown file
ref = filesystem:<document_ref>
media_type = text/markdown
parser_name = markdown
document_type = current frontmatter kind
source unit = parser-emitted Markdown section / paragraph / speaker-turn unit
chunk = current dotMD retrieval chunk
```

Current frontmatter remains document metadata. It must keep affecting:

- title extraction;
- `kind` and content handling;
- metadata embeddings;
- FTS metadata;
- graph tags and participants.

### Compatibility Requirements

- Existing `file_paths` in `SearchResult` remain available for filesystem hits.
- Existing MCP `read(file_path, start, end)` remains valid.
- Existing Markdown chunk text should not drift except where the planner
  explicitly documents an unavoidable adapter-boundary change.
- Existing metadata-only fast path must remain possible.
- Existing delete behavior for removed Markdown files must remain at least as
  correct as before.

## Deferred From Phase 25

- Telegram read-only adapter.
- `mcp-telegram` export API.
- Out-of-process adapter transports such as Unix socket, HTTP, MCP, or command
  invocation.
- Source assets and binary parsing.
- Entity catalogs, source entities, canonical identity resolution, and fuzzy
  person matching.
- TTL/soft-delete retention policy changes.
- Per-source scheduler, status dashboard, retries, and backpressure.
- Second-source validation with Perplexity, Notion, Google Docs, or another
  exporter.

## Planning Instructions

The planner should produce a small number of plans that keep the work
reversible:

1. Define source-aware domain models and filesystem Markdown adapter contract.
2. Route current Markdown discovery/parsing through that contract while
   preserving current chunk/search/read behavior.
3. Persist only the provenance and metadata required for compatibility and
   future source identity.
4. Add focused tests for filesystem compatibility, metadata fingerprints,
   delete behavior, search hydration, and MCP read/search compatibility.

The planner should not create implementation tasks for Telegram, source assets,
entity catalogs, or adapter runtime transports.

## Acceptance Gate

Phase 25 is ready to execute only if the plan can answer these questions:

- What is the canonical internal ref for a filesystem Markdown document?
- Where is `file_path` still intentionally preserved for compatibility?
- What object owns frontmatter metadata after the shim?
- How are source-unit refs attached to chunks?
- What schema or storage changes are required, if any?
- How does metadata-only change detection still avoid full re-chunking?
- Which tests prove user-visible behavior did not change?
