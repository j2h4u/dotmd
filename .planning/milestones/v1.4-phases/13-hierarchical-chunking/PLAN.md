# Phase 13: Content-Aware Hierarchical Chunking

## Goal

Improve search quality by adapting chunking strategy to content type,
injecting document context into embeddings, and stripping noise (frontmatter,
timestamps) from embedding content.

## Current Problems

1. Frontmatter (title, tags, date) wastes 50-100 tokens of 512 in embedding
2. Voicenotes 512 tokens ≈ 2 min speech — misses "what's the meeting about?"
3. Heading path empty for voicenotes — no context in results
4. "Николай Сенин" → name in frontmatter title, not in chunk text → semantic miss
5. Timestamps `[00:15:30]` embedded as text — no semantic value, wastes tokens
6. Meeting transcripts chunked by sentence boundaries, ignoring speaker turns

## Content Types in Corpus

| Type | Files | Boundaries | Has Frontmatter | Has Speakers |
|------|-------|-----------|-----------------|-------------|
| Meetings (diarized) | ~99 | `[HH:MM:SS] **Speaker:**` turns | Yes | Yes |
| Personal voicenotes | ~139 | None (continuous text) | Yes | No |
| Docs/markdown | ~202 | ATX headings (`#`) | Some | No |

## Architecture: Content-Aware Chunker

One strategy, three content-type handlers, one universal overflow logic.

```
chunk_file(file_path, content, strategy, max_tokens, overlap):

    # 1. Detect content type
    content_type = detect_type(content)  # meeting / personal / doc

    # 2. Extract + strip frontmatter
    frontmatter, body = extract_frontmatter(content)
    title = frontmatter.get("title", "")
    tags = frontmatter.get("tags", [])
    participants = frontmatter.get("participants", [])

    # 3. Content-type-specific boundary detection
    match content_type:
        "meeting":
            segments = split_by_speaker_turns(body)
        "doc":
            segments = split_by_headings(body)
        "personal":
            segments = [Section(text=body)]  # one block

    # 4. Universal overflow: segment > max_tokens → sentence-split
    chunks = []
    for segment in segments:
        if estimate_tokens(segment.text) <= max_tokens:
            chunks.append(segment)
        else:
            chunks.extend(sentence_split(segment, max_tokens, overlap))

    # 5. Context prefix injection (before embedding, after chunking)
    context_prefix = build_prefix(title, tags, participants, heading_path)
    for chunk in chunks:
        chunk.embedding_text = f"{context_prefix}\n\n{chunk.text}"
        chunk.text_for_storage = chunk.text  # without prefix (for display)

    return chunks
```

### Key Design Decisions

1. **Frontmatter stripped from chunk text.** Extracted to metadata, injected
   as prefix. Saves 50-100 tokens per chunk.

2. **Timestamps stripped from embedding text.** `[00:15:30]` → stored as
   `start_time` metadata, removed from text before embedding. Keep in
   display text for user navigation.

3. **Speaker names kept in embedding text.** `**Сергей Хабаров:**` is
   semantic signal — helps match "Хабаров" queries.

4. **Context prefix format:**
   ```
   {title} | {relevant_tags}
   ```
   Max 50 tokens. Truncate if longer. Prepended to embedding text only,
   NOT stored in chunk text (display stays clean).

5. **text_hash computed on chunk.text (without prefix).** Prefix may change
   (title update), but content stays same → embedding reuse works.

6. **Single strategy name** (e.g., `contextual_384_50`). Content-type detection
   is internal to the chunker, not a separate strategy per type.

---

## Step 1: Frontmatter Extraction + Context Prefix

Minimum viable change. No new chunk levels, no speaker-turn splitting yet.

### Changes to `chunker.py`:

**New function: `extract_frontmatter(content)`**
```python
def extract_frontmatter(content: str) -> tuple[dict, str]:
    """Extract YAML frontmatter and return (metadata_dict, body_without_frontmatter)."""
    if not content.startswith("---"):
        return {}, content
    end = content.find("---", 3)
    if end == -1:
        return {}, content
    import yaml
    fm = yaml.safe_load(content[3:end])
    body = content[end + 3:].strip()
    return fm or {}, body
```

**New function: `build_context_prefix(frontmatter, heading_path)`**
```python
def build_context_prefix(
    frontmatter: dict,
    heading_path: list[str] | None = None,
    max_tokens: int = 50,
) -> str:
    """Build context prefix from document metadata."""
    parts = []
    if title := frontmatter.get("title", ""):
        parts.append(title)
    if tags := frontmatter.get("tags", []):
        # Filter: keep names and meaningful tags, skip generic ones
        meaningful = [t for t in tags if t not in ("Meeting", "dear diary")]
        if meaningful:
            parts.append(", ".join(meaningful[:5]))
    if heading_path:
        parts.append(" > ".join(heading_path))

    prefix = " | ".join(parts)
    # Truncate if too long
    while estimate_tokens(prefix) > max_tokens and parts:
        parts.pop()
        prefix = " | ".join(parts)
    return prefix
```

**New function: `strip_timestamps(text)`**
```python
def strip_timestamps(text: str) -> tuple[str, str | None]:
    """Remove [HH:MM:SS] timestamps from text. Returns (clean_text, first_timestamp)."""
    import re
    first = re.search(r'\[(\d{2}:\d{2}:\d{2})\]', text)
    start_time = first.group(1) if first else None
    clean = re.sub(r'\[\d{2}:\d{2}:\d{2}\]\s*', '', text)
    return clean, start_time
```

**Update `chunk_file()`:**
```python
def chunk_file(file_path, content, max_tokens=384, overlap_tokens=50):
    frontmatter, body = extract_frontmatter(content)

    # Existing heading-based chunking on body (without frontmatter)
    sections = _parse_sections(body)
    chunks = []
    # ... existing logic but on body, not content ...

    # Post-process: add context prefix and strip timestamps
    prefix = build_context_prefix(frontmatter)
    for chunk in chunks:
        clean_text, start_time = strip_timestamps(chunk.text)
        chunk.embedding_text = f"{prefix}\n\n{clean_text}" if prefix else clean_text
        chunk.start_time = start_time  # new field on Chunk model
    return chunks
```

### Changes to Chunk model (`core/models.py`):

Add fields:
```python
embedding_text: str = ""    # text with context prefix (for embedding)
start_time: str | None = None  # first timestamp in chunk
```

### Changes to pipeline:

`_embed_chunks()` uses `chunk.embedding_text` instead of `chunk.text`:
```python
texts = [c.embedding_text or c.text for c in chunks]
return self._semantic_engine.encode_batch(texts)
```

`text_hash` computed on `chunk.text` (not embedding_text).

### Strategy name: `contextual_384_50`

Config: `chunk_strategy = "contextual_384_50"`

---

## Step 2: Speaker-Turn Chunking (meetings)

After Step 1 eval confirms improvement.

### New function: `detect_content_type(body)`
```python
def detect_content_type(body: str) -> str:
    """Detect content type from body text."""
    # Meeting: has [HH:MM:SS] **Speaker:** pattern
    if re.search(r'\[\d{2}:\d{2}:\d{2}\]\s*\*\*\w', body):
        return "meeting"
    # Doc: has ATX headings
    if re.search(r'^#{1,6}\s+', body, re.MULTILINE):
        return "doc"
    return "personal"
```

### New function: `split_by_speaker_turns(body)`
```python
def split_by_speaker_turns(body: str) -> list[Section]:
    """Split meeting transcript by speaker turns.

    Groups consecutive lines by speaker. Each turn becomes a segment.
    """
    # Pattern: [HH:MM:SS] **Speaker Name:**
    turn_pattern = re.compile(r'(\[\d{2}:\d{2}:\d{2}\])\s*\*\*([^*]+)\*\*:?\s*(.*)')
    ...
```

A speaker turn that exceeds max_tokens → universal sentence-split (same
as oversized heading sections in current code).

### Updated `chunk_file()`:
```python
content_type = detect_content_type(body)
if content_type == "meeting":
    segments = split_by_speaker_turns(body)
elif content_type == "doc":
    segments = _parse_sections(body)
else:
    segments = [Section(level=0, heading="", body=body, char_offset=0)]

# Universal overflow handling (existing _split_with_overlap)
for segment in segments:
    if too_large: sentence_split(segment)
```

---

## Step 3: Doc-Level Chunks (if Steps 1-2 insufficient)

Add one doc-level chunk per file: first 2048 tokens (or full content if shorter).

Chunk model: `level: str = "detail"` — doc-level chunks get `level="doc"`.

Both levels in same vec store. Search result dedup: group by file_path,
if both doc and detail hit, keep detail (more specific).

---

## Eval Plan

Run after each step on the 5 eval queries from eval_baseline.json:

| Query | Current Issue | Expected Improvement |
|-------|--------------|---------------------|
| q1 "распределение прибыли" | Top-1 correct but title empty | Title in prefix → heading_path shows in results |
| q4 "Николай Сенин как делить деньги" | Rank 6 for correct doc | Title "Рабочая встреча. Николай Сенин" in prefix → rank 1-3 |
| q2 "hiveon" | Works (keyword+semantic) | Should still work (regression check) |
| q3 "trickle indexer" | 0 results (correct) | Should still be 0 (regression check) |
| q5 "docker compose" | Works well | Should still work, heading_path preserved |

Success criteria: q4 rank ≤ 3 for correct document.

---

## Dependency Graph

```
Step 1: Context prefix + frontmatter strip + timestamp strip
  │     (changes: chunker.py, models.py, pipeline.py)
  │     eval → measure improvement
  │
Step 2: Speaker-turn chunking (meetings only)
  │     (changes: chunker.py only)
  │     eval → measure improvement
  │
Step 3: Doc-level chunks (only if needed)
        (changes: chunker.py, pipeline.py, search fusion)
```

## Files Changed

| File | Step | Changes |
|------|------|---------|
| `ingestion/chunker.py` | 1,2 | extract_frontmatter, build_context_prefix, strip_timestamps, detect_content_type, split_by_speaker_turns |
| `core/models.py` | 1 | Chunk: add embedding_text, start_time fields |
| `ingestion/pipeline.py` | 1 | _embed_chunks uses embedding_text; text_hash on .text not .embedding_text |
| `core/config.py` | 1 | Default chunk_strategy → "contextual_384_50" |

## Verification

### V1: Context Prefix
- [ ] Frontmatter stripped from chunk text
- [ ] Title/tags appear in embedding_text as prefix
- [ ] Timestamps stripped from embedding text, stored in start_time
- [ ] Speaker names preserved in embedding text
- [ ] text_hash computed without prefix
- [ ] q4 "Николай Сенин" → correct doc rank ≤ 3

### V2: Speaker Turns
- [ ] Meeting transcripts chunked by speaker turns
- [ ] Long turns sentence-split (same overflow logic)
- [ ] Personal voicenotes chunked as before (no speaker detection)
- [ ] Docs chunked by headings (no change)

### V3: Eval Regression
- [ ] All 5 eval queries: results equal or better than baseline
- [ ] No new empty results for queries that worked before
