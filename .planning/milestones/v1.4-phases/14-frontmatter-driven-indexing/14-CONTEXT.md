# Phase 14: Frontmatter-Driven Indexing - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning
**Source:** Discussion + Expert Panel

## Phase Boundary

Frontmatter is parsed once at file-read time into a dict. Each search engine consumes metadata optimally from structured data — not from raw YAML accidentally left in chunk text. Content-type handlers route processing by `kind` field. Fingerprinting excludes frontmatter so metadata-only changes don't trigger expensive reindexing.

## Implementation Decisions

### Frontmatter Stripping
- **Strip frontmatter from chunk text.** Chunks contain clean content only.
- **Why:** Separation of content and metadata. Raw YAML in chunks is noise for cross-encoder reranker. Metadata should reach each engine through structured channels, not by accident.
- **Already implemented:** `parse_frontmatter()` in reader.py, `content_checksum()` excludes frontmatter from fingerprints.
- **Currently reverted** (frontmatter back in chunks as temporary hack) — this phase re-enables strip with proper downstream feeding.

### Graph: Direct Entity Injection from Frontmatter
- **Tags with namespace go directly into graph as typed entities.** `person:Сергей Плаксиенко` → Entity(name="Сергей Плаксиенко", type="PERSON"). No NER needed for structured metadata.
- **Remove `_FRONTMATTER_RE` / `_extract_frontmatter()` from structural.py** — frontmatter is no longer in chunk text, and the structured path is better anyway.
- **New method `_frontmatter_to_graph(fi: FileInfo)`** in pipeline — parses tags, creates typed entities, edges to File node.
- **Tag namespace convention:** `person:X` → PERSON, `job` / `Meeting` / `LinkedIn` → TAG. If no colon → type="TAG".

### FTS5: Column-Weighted Indexing
- **Add `title TEXT, tags TEXT` columns to FTS5 virtual table.**
- **Column weights via bm25():** title x5, tags x3, text x1.
- **Why columns instead of prepend-to-text:** Prepend pollutes chunk text visible to cross-encoder reranker. Columns give precise relevance boosting.
- **Migration:** FTS5 doesn't support ALTER TABLE — requires DROP + CREATE. `reindex_fts5()` already exists.
- **Tags stored as comma-separated string** in the tags column.

### Embeddings: Tags in Enrichment Prefix
- **Extend enrichment from title-only to title + tags.** Format: `"Title\ntag1, tag2\n\nchunk text"`
- **All chunks of a file get the same enrichment** (title + tags are file-level, not chunk-level).
- **text_hash changes → re-embedding** for files that have tags. This is correct behavior.

### Content-Type Handlers (already implemented)
- `kind` field in frontmatter routes to ContentHandler (pre_split + enrich functions).
- Registry in `content_handlers.py`: meeting_transcript, voicenote, default.
- Handler dispatch in chunker and pipeline.

### Content-Only Fingerprinting (already implemented)
- `content_checksum()` hashes body + kind, excluding frontmatter.
- Frontmatter-only changes → no reindexing. Kind changes → reindexing (correct).
- Migration script ran successfully — all 2194 fingerprints updated.

### Per-Kind Metadata Extraction
- **Convention-based, not schema-based.** Declarative mapping: `field_name → entity_type`.
- `meeting_transcript`: `participants` → PERSON entities
- `email_thread`: `from`, `to` → PERSON entities
- `telegram_chat`: `chat_name` → GROUP entity
- **No pydantic schemas per kind** — YAGNI for 3-4 kinds.

### Frontmatter NOT in Chunk Model
- Frontmatter is a file-level property, not chunk-level. Don't add `frontmatter: dict` to Chunk.
- Pipeline passes FileInfo (with frontmatter) to enrichment and graph population.
- Chunk model has `kind: str` field (already added) — sufficient for handler dispatch.

## Canonical References

### Architecture (read before planning)
- `backend/src/dotmd/ingestion/content_handlers.py` — Handler registry (new, already created)
- `backend/src/dotmd/ingestion/reader.py` — `parse_frontmatter()`, `content_checksum()` (already implemented)
- `backend/src/dotmd/ingestion/chunker.py` — `chunk_file()` with kind dispatch (already implemented)
- `backend/src/dotmd/ingestion/pipeline.py` — `_enrich_for_embedding()`, `_populate_graph()`, `_save_fingerprint()`
- `backend/src/dotmd/extraction/structural.py` — `_extract_frontmatter()` to be removed

### Search engines
- `backend/src/dotmd/search/fts5.py` — FTS5 DDL and search (column changes needed)
- `backend/src/dotmd/search/graph_direct.py` — Entity catalog (auto-picks up new entities)

### Models
- `backend/src/dotmd/core/models.py` — FileInfo (has kind, frontmatter), Chunk (has kind)

## Specific Ideas

- FTS5 column weights: experiment with `bm25(fts_table, 1.0, 5.0, 3.0)` for (text, title, tags)
- Tag parsing: `tag.split(":", 1)` — first part is type, second is name. No colon → type="TAG"
- Enrichment format for embeddings: `"{title}\n{tag1}, {tag2}\n\n{chunk_text}"`

## Deferred Ideas

- Formal pydantic schemas per kind — revisit when kind count exceeds 5-6
- Date-range filtering in search (using frontmatter `date` field)
- Telegram chat handler (format TBD, ~1 week out)

---

*Phase: 14-frontmatter-driven-indexing*
*Context gathered: 2026-04-02 via discussion + expert panel*
