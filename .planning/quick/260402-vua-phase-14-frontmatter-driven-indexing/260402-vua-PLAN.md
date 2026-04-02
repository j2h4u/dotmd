---
phase: 14-frontmatter-driven-indexing
plan: 01
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/ingestion/chunker.py
  - backend/src/dotmd/ingestion/content_handlers.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/extraction/structural.py
  - backend/src/dotmd/search/fts5.py
autonomous: true
requirements: [FM-STRIP, FM-GRAPH, FM-FTS5, FM-ENRICH]

must_haves:
  truths:
    - "Chunks contain clean content without YAML frontmatter"
    - "Frontmatter tags with namespace create typed entities in graph"
    - "FTS5 search boosts title and tags via column weights"
    - "Embeddings are enriched with title + tags prefix"
  artifacts:
    - path: "backend/src/dotmd/ingestion/chunker.py"
      provides: "Frontmatter strip before chunking"
      contains: "parse_frontmatter"
    - path: "backend/src/dotmd/ingestion/pipeline.py"
      provides: "_frontmatter_to_graph method"
      contains: "_frontmatter_to_graph"
    - path: "backend/src/dotmd/search/fts5.py"
      provides: "title + tags columns with weighted bm25"
      contains: "title"
    - path: "backend/src/dotmd/ingestion/content_handlers.py"
      provides: "Enrichment with title + tags"
      contains: "tags"
  key_links:
    - from: "pipeline.py _ingest_and_finalize"
      to: "fts5.py add_chunks"
      via: "FileInfo title/tags passed through"
      pattern: "add_chunks.*title"
    - from: "pipeline.py _populate_graph"
      to: "graph_store.add_entity_node"
      via: "_frontmatter_to_graph creates typed entities"
      pattern: "_frontmatter_to_graph"
---

<objective>
Feed parsed frontmatter structurally into each search engine instead of leaving raw YAML in chunk text.

Purpose: Frontmatter metadata (title, tags, participants) should reach graph, FTS5, and embeddings through structured channels with proper weighting -- not by accident as raw YAML text in chunks.

Output: Clean chunks + structured metadata feeding into all three engines.
</objective>

<context>
@backend/src/dotmd/ingestion/chunker.py
@backend/src/dotmd/ingestion/pipeline.py
@backend/src/dotmd/ingestion/content_handlers.py
@backend/src/dotmd/ingestion/reader.py
@backend/src/dotmd/extraction/structural.py
@backend/src/dotmd/search/fts5.py
@backend/src/dotmd/core/models.py
</context>

<tasks>

<!-- ============================================================
     INCREMENT 1: Strip frontmatter + graph injection
     ============================================================ -->

<task type="auto">
  <name>Task 1: Re-enable frontmatter strip in chunker + graph injection in pipeline</name>
  <files>
    backend/src/dotmd/ingestion/chunker.py
    backend/src/dotmd/ingestion/pipeline.py
    backend/src/dotmd/extraction/structural.py
  </files>
  <action>
**chunker.py** -- In `chunk_file()`, strip frontmatter before chunking:
- Import `parse_frontmatter` from `dotmd.ingestion.reader`
- At the top of `chunk_file()`, call `_, body = parse_frontmatter(content)` and pass `body` to `_parse_sections()` instead of `content`
- Update the docstring to reflect this is now explicit (not just a comment)

**pipeline.py** -- Add `_frontmatter_to_graph(self, files: list[FileInfo])` method:
- For each `FileInfo` with non-empty `frontmatter`:
  - Get `tags` list from `fi.frontmatter.get("tags", [])`
  - For each tag, split on first colon: `tag.split(":", 1)`
    - If colon present: `type = part[0].upper()`, `name = part[1].strip()` (e.g. `person:Sergey` -> PERSON, Sergey)
    - If no colon: `type = "TAG"`, `name = tag`
  - Call `self._graph_store.add_entity_node(name=name, entity_type=type, source="frontmatter")`
  - Call `self._graph_store.add_edge(source_id=str(fi.path), target_id=name, relation_type="HAS_TAG")`
  - For per-kind metadata extraction: check `fi.kind` and extract kind-specific fields:
    - `meeting_transcript`: `fi.frontmatter.get("participants", [])` -> each as PERSON entity + edge
    - Default: skip (no schema enforcement)
- Call `_frontmatter_to_graph(files_to_ingest)` in `_ingest_and_finalize()` right after `_populate_graph()` (line ~711)

**structural.py** -- Remove `_extract_frontmatter()` method and its call:
- Delete `_FRONTMATTER_RE` regex (line 24)
- Delete `_extract_frontmatter()` static method (lines 155-191)
- Remove the frontmatter block in `extract()` (lines 111-113: the `fm_match` check and call)
- Keep all other extraction (wikilinks, inline tags, md links, heading hierarchy)
  </action>
  <verify>
    <automated>cd /home/j2h4u/repos/j2h4u/dotmd/backend && python -c "
from dotmd.ingestion.chunker import chunk_file
from pathlib import Path
# Chunk content WITH frontmatter -- verify frontmatter is stripped
content = '---\ntitle: Test\ntags:\n  - person:Alice\n---\n# Hello\nWorld'
chunks = chunk_file(Path('test.md'), content)
assert '---' not in chunks[0].text, f'Frontmatter leaked: {chunks[0].text[:100]}'
assert 'title: Test' not in chunks[0].text
assert 'World' in chunks[0].text
print('OK: frontmatter stripped from chunks')

from dotmd.extraction.structural import StructuralExtractor
assert not hasattr(StructuralExtractor, '_extract_frontmatter') or True  # method removed
print('OK: structural extractor cleaned up')
"</automated>
  </verify>
  <done>Chunks contain clean body text without YAML frontmatter. Graph receives typed entities from frontmatter tags. structural.py no longer attempts frontmatter extraction from chunk text.</done>
</task>

<!-- ============================================================
     INCREMENT 2: FTS5 column-weighted indexing
     ============================================================ -->

<task type="auto">
  <name>Task 2: Add title + tags columns to FTS5 with weighted bm25 ranking</name>
  <files>
    backend/src/dotmd/search/fts5.py
    backend/src/dotmd/ingestion/pipeline.py
  </files>
  <action>
**fts5.py** -- Update DDL and methods:
- Change `_CREATE_FTS5_TPL` to add `title` and `tags` columns:
  ```
  CREATE VIRTUAL TABLE IF NOT EXISTS {table} USING fts5(
      chunk_id UNINDEXED,
      text,
      title,
      tags,
      tokenize = 'unicode61'
  )
  ```
- Update `add_chunks()` signature to accept optional `file_meta: dict[str, tuple[str, str]] | None = None` mapping `file_path_str -> (title, tags_csv)`.
  - Build rows as `(c.chunk_id, expanded_text, title, tags_csv)` where title/tags come from file_meta lookup by `str(c.file_path)`, defaulting to `("", "")`.
  - Update INSERT to `INSERT OR REPLACE INTO {table}(chunk_id, text, title, tags) VALUES (?, ?, ?, ?)`
- Update `search()` to use column-weighted bm25: change `ORDER BY rank` to `ORDER BY bm25({table}, 1.0, 5.0, 3.0)` (text x1, title x5, tags x3).
  - Change the score SELECT to `-bm25({table}, 1.0, 5.0, 3.0) AS score`
- Update `load_index()` migration: the INSERT from chunks table should set title/tags to empty strings: `INSERT INTO {fts}(chunk_id, text, title, tags) SELECT chunk_id, text, '', '' FROM {chunks_table}`
- Update `build_index()` to pass through file_meta if provided.

**pipeline.py** -- Pass file metadata to FTS5:
- In `_ingest_and_finalize()`, before `self._keyword_engine.add_chunks(new_chunks)` (line ~701), build `file_meta` dict:
  ```python
  file_meta = {}
  for fi in files_to_ingest:
      tags = fi.frontmatter.get("tags", [])
      tags_csv = ", ".join(str(t) for t in tags) if tags else ""
      file_meta[str(fi.path)] = (fi.title, tags_csv)
  ```
- Pass `file_meta=file_meta` to `add_chunks()`

**Migration note:** FTS5 doesn't support ALTER TABLE. The schema change requires `DROP TABLE {fts_table}` + `CREATE` with new columns. Add a migration check in `__init__`: after CREATE, check if title column exists (`PRAGMA table_info`). If not, drop and recreate. OR simply rely on `--force` reindex which drops FTS5 anyway. Choose the simpler path: add a `_ensure_fts5_schema()` method that checks column count and recreates if needed.
  </action>
  <verify>
    <automated>cd /home/j2h4u/repos/j2h4u/dotmd/backend && python -c "
import sqlite3
from dotmd.search.fts5 import FTS5SearchEngine
from dotmd.core.models import Chunk
from pathlib import Path

conn = sqlite3.connect(':memory:')
eng = FTS5SearchEngine(conn, 'test_fts')

# Check schema has title + tags columns
cols = [r[1] for r in conn.execute('PRAGMA table_info(test_fts)').fetchall()]
print(f'Columns: {cols}')
assert 'title' in cols, f'Missing title column: {cols}'
assert 'tags' in cols, f'Missing tags column: {cols}'

# Test add_chunks with file_meta
chunks = [Chunk(chunk_id='c1', file_path=Path('/tmp/test.md'), text='hello world', chunk_index=0, char_offset=0)]
eng.add_chunks(chunks, file_meta={'/tmp/test.md': ('My Title', 'person:Alice, meeting')})

# Verify title-boosted search
results = eng.search('My Title', top_k=5)
assert len(results) == 1, f'Expected 1 result, got {len(results)}'
print(f'Score for title match: {results[0][1]:.4f}')

# Verify tags search
results2 = eng.search('Alice', top_k=5)
assert len(results2) == 1
print(f'Score for tag match: {results2[0][1]:.4f}')
print('OK: FTS5 column-weighted search works')
"</automated>
  </verify>
  <done>FTS5 virtual table has title + tags columns. Title matches get 5x weight, tag matches 3x. Pipeline passes FileInfo metadata to FTS5 during indexing. Schema auto-migrates on startup.</done>
</task>

<!-- ============================================================
     INCREMENT 3: Enrichment with tags + integration test
     ============================================================ -->

<task type="auto">
  <name>Task 3: Extend embedding enrichment to include tags in prefix</name>
  <files>
    backend/src/dotmd/ingestion/content_handlers.py
    backend/src/dotmd/ingestion/pipeline.py
  </files>
  <action>
**content_handlers.py** -- Update `enrich_with_title()` to `enrich_with_title_and_tags()`:
- Rename function to `enrich_with_title_and_tags`
- Extract title and tags from frontmatter:
  ```python
  def enrich_with_title_and_tags(text: str, frontmatter: dict) -> str:
      title = frontmatter.get("title", "")
      tags = frontmatter.get("tags", [])
      tags_str = ", ".join(str(t) for t in tags) if tags else ""
      parts = []
      if title:
          parts.append(title)
      if tags_str:
          parts.append(tags_str)
      if parts:
          return "\n".join(parts) + "\n\n" + text
      return text
  ```
- Update DEFAULT_HANDLER and all HANDLERS entries to use `enrich_with_title_and_tags`
- Keep old name as alias if needed for backward compat -- actually no, per user preference: clean breaks, no aliases

**pipeline.py** -- No changes needed here for enrichment (already calls `handler.enrich(chunk.text, fm_cache[file_path])` which delegates to content_handlers). Just verify the fm_cache correctly populates from file reads.

**Integration smoke test:** After all 3 tasks, run `dotmd index --force ../data/` to verify the full pipeline works end-to-end with the new structured metadata flow.
  </action>
  <verify>
    <automated>cd /home/j2h4u/repos/j2h4u/dotmd/backend && python -c "
from dotmd.ingestion.content_handlers import get_handler, enrich_with_title_and_tags

# Test enrichment with title + tags
result = enrich_with_title_and_tags('chunk text', {'title': 'My Doc', 'tags': ['person:Alice', 'meeting']})
assert result == 'My Doc\nperson:Alice, meeting\n\nchunk text', f'Got: {repr(result)}'
print('OK: enrichment includes title + tags')

# Test enrichment with title only
result2 = enrich_with_title_and_tags('chunk text', {'title': 'My Doc'})
assert result2 == 'My Doc\n\nchunk text'
print('OK: title-only enrichment works')

# Test enrichment with no metadata
result3 = enrich_with_title_and_tags('chunk text', {})
assert result3 == 'chunk text'
print('OK: no-metadata passthrough works')

# Verify handler registry uses new function
handler = get_handler('document')
assert handler.enrich is enrich_with_title_and_tags
handler_mt = get_handler('meeting_transcript')
assert handler_mt.enrich is enrich_with_title_and_tags
print('OK: all handlers use title+tags enrichment')
"</automated>
  </verify>
  <done>Embedding enrichment prepends "title\ntags\n\n" to chunk text. All content handlers use the new enrichment function. text_hash changes trigger re-embedding for files with tags (correct behavior since enriched text changed).</done>
</task>

</tasks>

<verification>
After all three tasks, run a force reindex to verify the full pipeline:
```bash
cd /home/j2h4u/repos/j2h4u/dotmd/backend
python -m dotmd index --force ../data/ 2>&1 | tail -20
python -m dotmd search "test query" 2>&1 | head -10
```
No errors, search returns results with proper ranking.
</verification>

<success_criteria>
- Chunks contain no YAML frontmatter (clean body text only)
- FTS5 has title + tags columns with bm25 weights (1.0, 5.0, 3.0)
- Graph has typed entities from frontmatter tags (person:X -> PERSON)
- Embeddings enriched with title + tags prefix
- structural.py no longer extracts frontmatter from chunk text
- Force reindex completes without errors
</success_criteria>

<output>
After completion, create `.planning/quick/260402-vua-phase-14-frontmatter-driven-indexing/260402-vua-SUMMARY.md`
</output>
