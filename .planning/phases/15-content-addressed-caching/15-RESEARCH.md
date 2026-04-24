# Phase 15: Content-Addressed Caching — Research

**Researched:** 2026-04-24
**Domain:** SQLite caching layer, BLAKE3, pipeline insertion points, migration safety
**Confidence:** HIGH — all findings are verified against live codebase and live DB

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Deploy Order (LOCKED)**
- Plan 1 (B) first, then Plan 2 (C), then Plan 3 (A)
- Plans 1+2 must be deployed and cache must be warm before Plan 3 runs

**Plan 1 — Embedding Cache**
- D-01: New table `embedding_cache(text_hash TEXT PRIMARY KEY, embedding BLOB, created_at TEXT)` in index.db
- D-02: Cache key = `text_hash` (blake2b of enriched chunk text, stored in vec_meta)
- D-03: Lookup BEFORE calling TEI; if found → skip HTTP call
- D-04: On TEI result: store (text_hash, embedding) in embedding_cache
- D-05: No migration needed — lazy population
- D-06: No eviction initially

**Plan 2 — Extraction Cache**
- D-07: New table `extraction_cache(cache_key TEXT PRIMARY KEY, entities JSON, relations JSON, created_at TEXT)`
- D-08: Cache key = `blake2b(text_hash + model_name + entity_types_hash)` — compound key
- D-09: Lookup BEFORE running GLiNER batch inference
- D-10: On GLiNER result: store (cache_key, entities_json, relations_json)
- D-11: Invalidation: on NERExtractor load, compare model_name + entity_types_hash; if changed → DELETE FROM extraction_cache
- D-12: entity_types_hash = blake2b(sorted(entity_types).join(","))
- D-13: No migration — lazy population

**Plan 3 — Content-Based chunk_id + BLAKE3**
- D-14: New chunk_id formula: `blake3(body_checksum + ":" + chunk_index + ":" + chunk_strategy)`
  - body_checksum = checksum stored in chunk_fingerprints_{strategy} (blake2b of body+kind)
- D-15: chunk_strategy included to prevent collisions between strategies
- D-16: Switch chunk_id hashing to BLAKE3 (add `blake3` package); all other hashing stays on blake2b
- D-17: Migration: stop container → cp index.db backup → SQL UPDATE → verify → restart
- D-18: Migration script is standalone Python, NOT run inside container
- D-19: Post-migration: every chunk_id in chunks_* must exist in vec_meta_*
- D-20: Plans 1+2 MUST be deployed and warm before Plan 3 runs
- D-21: FTS5 and sqlite_vec virtual tables require DELETE + re-INSERT (not plain UPDATE)
  - **OVERRIDDEN by research finding — see "D-21 Correction" below**

**Architectural Constraints**
- D-22: GLiNER and TEI must NEVER run concurrently (CPU constraint)
- D-23: All cache lookups are synchronous (no async complexity)
- D-24: Cache tables live in index.db (no separate DB file)
- D-25: text_hash already exists in vec_meta — reuse, don't recompute

### Claude's Discretion
- Exact SQL DDL for new tables
- Where in pipeline.py to insert cache lookups
- JSON serialization format for extraction_cache entities/relations
- Whether to add indexes on cache tables

### Deferred Ideas (OUT OF SCOPE)
- Fingerprint-by-content (would prevent trickle detecting file moves)
- Extraction cache eviction policy
- Embedding cache eviction policy
- Pipeline parallelism (Phase 999.2 backlog)
</user_constraints>

---

## Summary

Phase 15 adds two lookup caches (embedding, extraction) to skip TEI/GLiNER on file moves, then migrates chunk_ids to content-addressable BLAKE3 hashes so the caches remain valid even after vault reorganization.

The codebase is well-structured for this work. The embedding cache lookup inserts into a 6-line gap in `_embed_chunks()` that already has the text_hash → existing vector pattern. The extraction cache inserts into `NERExtractor.extract()` wrapping the `model.inference()` call. Both are synchronous, single-connection SQLite writes.

**Key discovery that changes the plan:** D-21 states FTS5 and sqlite_vec require DELETE+re-INSERT for chunk_id migration. Verified against the live DB: this is incorrect. FTS5's `chunk_id` column is `UNINDEXED`, so plain `UPDATE` works and preserves the inverted index. `vec_meta` is a regular SQLite table — plain UPDATE works. `vec_chunks` (the vec0 virtual table) has no `chunk_id` column at all; it only stores `(rowid, embedding)`. The migration can use plain `UPDATE` across all three user-facing tables. Internal vec0 shadow tables (`_rowids`, `_chunks`) must not be touched.

**Additional discovery:** The live `text_hash` values in vec_meta are MD5 (32 hex chars), not blake2b-128 (128 hex chars). Pipeline.py line 431 says `hashlib.blake2b(text.encode()).hexdigest()` which produces 128 hex chars, but the DB contains 32-char hashes that match MD5. This is a pre-existing inconsistency in the production DB. The embedding_cache (D-02) uses text_hash as its key — the embedding cache table must accommodate both 32-char (legacy MD5) and 128-char (current blake2b) values. The UNIQUE constraint on text_hash handles this correctly regardless of length.

**Primary recommendation:** All three plans can use plain SQLite UPDATE/INSERT — no DELETE+re-INSERT gymnastics needed. The migration script complexity is lower than assumed.

---

## Architectural Responsibility Map

| Capability | Primary Tier | Secondary Tier | Rationale |
|------------|-------------|----------------|-----------|
| Embedding cache lookup/store | Pipeline (ingestion) | SQLiteVecVectorStore | Lives in `_embed_chunks()` — the layer that already manages text_hash and calls encode_batch |
| Extraction cache lookup/store | NERExtractor | pipeline._run_extraction | Cache key needs model_name + entity_types accessible inside NERExtractor |
| cache table DDL + ensure | SQLiteVecVectorStore._ensure_tables or new CacheStore | pipeline.__init__ | Shared conn, must be ensured before first use |
| Plan 3 migration | Standalone script (migration.py pattern) | — | D-18: runs outside container against volume directly |
| chunk_id computation | chunker._make_chunk_id | — | Single function, single change point |

---

## Standard Stack

### Core (no new additions for Plans 1+2)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| hashlib (stdlib) | Python 3.12 | blake2b for all existing hashing | Already used throughout codebase |
| sqlite3 (stdlib) | Python 3.12 | Cache tables in index.db | Shared connection, zero overhead |

### New Dependency (Plan 3 only)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| blake3 | 1.0.8 | Content-based chunk_id hash | D-16 locked decision; BLAKE3 is 6x faster than blake2b for large inputs |

**Installation (Plan 3):**
```bash
# In pyproject.toml dependencies:
"blake3>=1.0",
```

**Version verification:** [VERIFIED: pip install --dry-run inside dotmd-api-1 container]
- `blake3-1.0.8-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl` — binary wheel exists for Python 3.12 x86_64 Linux
- No Rust toolchain needed (pre-built wheel)
- No AVX2 required (blake3 Python binding is pure C extension)

---

## Architecture Patterns

### System Architecture — Plan 1 (Embedding Cache)

```
_embed_chunks(chunks)
  │
  ├─ enrich texts (per-chunk)
  ├─ compute text_hashes (blake2b of enriched text)
  │
  ├─► embedding_cache.lookup(text_hashes)        ← NEW
  │     hit: reuse cached vector, skip TEI
  │     miss: add to to_encode list
  │
  ├─ [existing] vec_meta.lookup_embeddings_by_text_hash()   ← cross-strategy lookup
  │     hit: reuse from another strategy's vec_meta
  │
  ├─► encode_batch(texts_to_encode) → TEI HTTP
  │
  └─► embedding_cache.store(new text_hashes → vectors)      ← NEW
```

**Note:** Two cache levels in `_embed_chunks()`:
1. `embedding_cache` table (global, persists across index cycles, survives file moves) — NEW
2. `vec_meta.lookup_embeddings_by_text_hash()` (within-DB cross-strategy) — existing

The global `embedding_cache` handles the file-move scenario where the chunk has been purged from vec_meta but the text is unchanged. After a file move: file is detected as "new" → old vec_meta rows were deleted during purge → but embedding_cache still has the vector → TEI skipped.

### System Architecture — Plan 2 (Extraction Cache)

```
NERExtractor.extract(chunks)
  │
  ├─ ensure model loaded (lazy)
  │
  ├─► FOR EACH chunk:
  │     compute cache_key = blake2b(text_hash + model_name + entity_types_hash)
  │     extraction_cache.lookup(cache_key)
  │       hit: restore entities/relations from JSON
  │       miss: add to inference batch
  │
  ├─ model.inference(miss_texts, entity_types)  ← GLiNER batch
  │
  └─► FOR EACH miss: extraction_cache.store(cache_key, entities_json, relations_json)
```

**Scope decision (Claude's discretion):** Cache lookup happens at individual chunk granularity inside `NERExtractor.extract()`. The loop already iterates per chunk over `batch_predictions`. Partial cache hits (some chunks cached, some not) are the common case for incremental indexing — the uncached subset is passed to GLiNER as a smaller batch.

### Plan 3 Migration Flow

```
stop container
  │
  ├─ cp index.db → index.db.bak (atomic backup)
  │
  ├─ BEGIN TRANSACTION
  │   for each strategy in [heading_512_50, contextual_512_50]:
  │     for each file in chunk_fingerprints_{strategy}:
  │       for each chunk in chunks_{strategy} for that file:
  │         new_id = blake3(checksum + ":" + chunk_index + ":" + strategy)
  │         UPDATE chunks_{strategy}
  │         UPDATE chunks_fts_{strategy}    (UNINDEXED col — safe plain UPDATE)
  │         UPDATE vec_meta_{strategy}_*   (regular table — plain UPDATE)
  │     UPDATE chunk_fingerprints_{strategy} — no chunk_id column, skip
  │ COMMIT
  │
  ├─ verify: SELECT chunk_ids from chunks_* NOT IN vec_meta_* → must be 0
  │
  └─ restart container
```

### Recommended Project Structure (additions only)
```
backend/src/dotmd/
├── storage/
│   ├── cache.py          # NEW: EmbeddingCache + ExtractionCache classes
│   └── sqlite_vec.py     # existing — unchanged
├── ingestion/
│   ├── pipeline.py       # modified: Plan 1 cache integration
│   ├── chunker.py        # modified: Plan 3 new _make_chunk_id
│   └── migration_v15.py  # NEW: Plan 3 standalone migration script
└── extraction/
    └── ner.py            # modified: Plan 2 cache integration
```

### Anti-Patterns to Avoid

- **Loading cache from disk on every request:** D-23 mandates synchronous lookups. The cache tables are in the shared SQLite connection — no file I/O beyond what SQLite does internally.
- **Recomputing text_hash in cache lookup:** text_hash is already computed in `_embed_chunks()` (line 430-432) and passed to `add_chunks()`. Cache lookup reuses this value — do not recompute.
- **Putting cache in a separate DB file:** D-24 locked — everything in index.db on the shared connection.
- **Touching vec0 shadow tables directly:** `vec_chunks_*_rowids` and `vec_chunks_*_chunks` are vec0 internal tables. Never UPDATE/DELETE these manually.
- **Running Plan 3 migration while container is up:** The migration does a full UPDATE of chunk_ids. If the container is running and serving requests mid-migration, half the rows will have new IDs and half old. Always stop first.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| BLAKE3 hashing | Custom C extension or ctypes wrapper | `blake3` PyPI package | Pre-built manylinux wheel, pure Python API, maintained by algorithm authors |
| Binary embedding storage | Custom float packing | `struct.pack(f"{n}f", *vec)` | Already used in sqlite_vec.py — reuse `_serialize_f32` |
| JSON serialization for entities/relations | Custom format | `json.dumps([e.__dict__ for e in entities])` | Pydantic models already JSON-serializable via `.model_dump()` |
| Cache invalidation logic | Complex eviction | Full table DELETE (D-11) | At ~7500 chunks the extraction cache is ~7MB — nuclear option is fine |

---

## Critical Findings (Planner Must Read)

### Finding 1: D-21 is Wrong — Plain UPDATE Works for All Tables [VERIFIED: live DB test]

CONTEXT.md D-21: "FTS5 and sqlite_vec virtual tables require DELETE + re-INSERT (not plain UPDATE)"

Live DB test results:
- `chunks_fts_{strategy}`: `chunk_id` is declared `UNINDEXED` in the FTS5 DDL. Plain `UPDATE SET chunk_id=?` works and does **not** corrupt the FTS inverted index (only the `text` column is indexed).
- `vec_meta_{strategy}_{model}`: this is a **regular SQLite table** (not virtual). Plain `UPDATE` works.
- `vec_chunks_{strategy}_{model}`: this is a vec0 virtual table but has **no `chunk_id` column** — only `(rowid, embedding)`. The chunk_id↔rowid mapping lives in `vec_meta`. No update needed in vec_chunks at all.

**Impact on Plan 3 migration:** The migration script can use plain `UPDATE ... SET chunk_id = new_id WHERE chunk_id = old_id` across all three tables. No DELETE+re-INSERT loop needed. This makes the migration simpler and faster (single pass, transactional).

**FTS5 DDL (verified):**
```sql
-- heading strategy:
CREATE VIRTUAL TABLE chunks_fts_heading_512_50 USING fts5(
    chunk_id UNINDEXED, text, tokenize = 'unicode61')
-- contextual strategy:
CREATE VIRTUAL TABLE chunks_fts_contextual_512_50 USING fts5(
    chunk_id UNINDEXED, text, title, tags, tokenize = 'unicode61')
```

### Finding 2: text_hash in Production DB is MD5, Not blake2b [VERIFIED: live DB comparison]

pipeline.py line 431 computes: `hashlib.blake2b(text.encode()).hexdigest()` → 128 hex chars
Live DB values in `vec_meta_heading_512_50_multilingual_e5_large`: 32 hex chars → MD5

Confirmed by testing: `hashlib.md5(enriched_text.encode()).hexdigest()` matches stored values.

Likely cause: the heading strategy's vec_meta rows were populated by an older version of the code that used MD5. The contextual strategy shows a mix of 32-char (MD5, older rows) and 128-char (blake2b, newer rows).

**Impact on Plan 1 (embedding cache):** The cache key `text_hash` will have mixed lengths across rows. This is not a correctness problem — the `TEXT PRIMARY KEY` on `embedding_cache` handles both lengths correctly. However, the heading strategy's old rows will cache-miss on the embedding_cache lookup (because the current pipeline would compute a 128-char blake2b hash, but the stored text_hash in vec_meta is 32-char MD5 — they won't match). The cache population is lazy so this self-heals on next re-index.

**Planner note:** No special handling needed. Document the mixed state in a comment. The cache populates lazily from current-run text_hashes (always blake2b-128) and will not see hits for legacy MD5-hashed rows until those files are re-indexed.

### Finding 3: chunk_fingerprints Checksums Are Also Mixed [VERIFIED: live DB]

`chunk_fingerprints_heading_512_50`: 2 rows have MD5 (len=32), 201 rows have blake2b (len=128).
`chunk_fingerprints_contextual_512_50`: all rows have blake2b (len=128).

D-14 says: `new_chunk_id = blake3(body_checksum + ":" + chunk_index + ":" + strategy)`
where `body_checksum` = the checksum stored in `chunk_fingerprints_{strategy}`.

**Impact on Plan 3 migration:** The 2 legacy MD5 rows in `chunk_fingerprints_heading_512_50` will produce shorter inputs to blake3 — but the output is still a valid unique blake3 hash. This is fine. The migration reads whatever checksum is stored and hashes it. The only edge case: if the same file gets re-indexed after migration, its new chunk_fingerprint checksum will be blake2b-128, generating different blake3 chunk_ids. This means one more full re-index for the 2 legacy files. Acceptable — document in migration script comment.

### Finding 4: Exact Insertion Points in pipeline.py [VERIFIED: code reading]

**Plan 1 — embedding_cache lookup insertion point:**

`_embed_chunks()`, lines 437–461. The existing code already has the structure:
```python
# EXISTING (line 437-449):
existing: dict[str, list[float]] = {}
if hasattr(self._vector_store, "lookup_embeddings_by_text_hash"):
    existing = self._vector_store.lookup_embeddings_by_text_hash(...)
...
for i, chunk in enumerate(chunks):
    th = text_hashes[chunk.chunk_id]
    if th in existing:
        embeddings[i] = existing[th]  # cache hit
    else:
        to_encode_indices.append(i)   # miss
```

The embedding_cache lookup merges into `existing` dict BEFORE the `if th in existing` check. Pattern:
```python
# After line 439 (after vec_meta lookup), add:
if hasattr(self, '_embedding_cache'):
    global_hits = self._embedding_cache.lookup(list(text_hashes.values()))
    existing.update(global_hits)  # global cache wins over cross-strategy
```

After encoding misses (line 460), store new embeddings in embedding_cache:
```python
# After new_embeddings are computed (line 460):
if hasattr(self, '_embedding_cache'):
    for j, idx in enumerate(to_encode_indices):
        th = text_hashes[chunks[idx].chunk_id]
        self._embedding_cache.store(th, new_embeddings[j])
```

**Plan 2 — extraction_cache lookup insertion point:**

`NERExtractor.extract()`, immediately after model load (line 91-95). Wrap the per-chunk loop.

Currently:
```python
# Line 92-99:
model = self._get_model()
texts = [chunk.text for chunk in chunks]
batch_predictions = model.inference(texts, self._entity_types, threshold=...)
```

With cache:
```python
model = self._get_model()
# --- CACHE CHECK ---
if self._extraction_cache:
    cached_results, miss_chunks = self._extraction_cache.lookup_batch(
        chunks, self._model_name, self._entity_types_hash)
else:
    cached_results, miss_chunks = {}, chunks

# Only run GLiNER on misses
if miss_chunks:
    texts = [c.text for c in miss_chunks]
    batch_predictions = model.inference(texts, self._entity_types, threshold=...)
    # ... build entities/relations ...
    if self._extraction_cache:
        self._extraction_cache.store_batch(miss_chunks, results_per_chunk)
```

**Plan 3 — _make_chunk_id change:**

`chunker.py` lines 22-25, replace entirely:
```python
# BEFORE:
def _make_chunk_id(file_path: Path, chunk_index: int) -> str:
    payload = f"{file_path}:{chunk_index}"
    return hashlib.blake2b(payload.encode()).hexdigest()

# AFTER:
def _make_chunk_id(body_checksum: str, chunk_index: int, chunk_strategy: str) -> str:
    import blake3
    payload = f"{body_checksum}:{chunk_index}:{chunk_strategy}"
    return blake3.blake3(payload.encode()).hexdigest()
```

The call sites in `chunk_file()` must pass `body_checksum` instead of `file_path`. The `body_checksum` is `chunk_checksum(path)` which is already computed by `FileTracker` — but at chunking time this checksum is not yet available as a parameter. The chunker currently receives `file_path` and `content`. The simplest approach: compute `chunk_checksum` inside `chunk_file()` using the already-parsed `body` + `kind`:

```python
# In chunk_file(), after parsing frontmatter:
_, body = parse_frontmatter(content)
kind = frontmatter.get("kind", DocKind.DOCUMENT)
body_checksum = hashlib.blake2b(f"{kind}\n{body}".encode()).hexdigest()
```

This is the same formula as `chunk_checksum()` in reader.py. chunk_file() already has `body` from `parse_frontmatter()`.

### Finding 5: entity_types_hash — Cache Key Component [VERIFIED: code reading]

`NERExtractor._entity_types` is `list[str]` (line 62). The D-12 formula: `blake2b(sorted(entity_types).join(","))`.

Implementation:
```python
# In NERExtractor.__init__():
self._entity_types_hash = hashlib.blake2b(
    ",".join(sorted(self._entity_types)).encode()
).hexdigest()
```

The `model_name` is `self._model_name` (line 63). Both are available inside `NERExtractor` without any API changes.

### Finding 6: cache_key Formula for D-08 [VERIFIED: code reading]

D-08: `blake2b(text_hash + model_name + entity_types_hash)` — this is a concatenation.

```python
cache_key = hashlib.blake2b(
    (text_hash + self._model_name + self._entity_types_hash).encode()
).hexdigest()
```

`text_hash` here refers to each chunk's text_hash. But NERExtractor receives `chunks` and their text is not yet hashed. Two options:
1. Compute `hashlib.blake2b(chunk.text.encode()).hexdigest()` inside NERExtractor — but text_hash is computed on ENRICHED text in pipeline, not raw chunk.text
2. Pass text_hashes mapping to NERExtractor.extract()

The simpler approach: compute hash of raw chunk.text inside NERExtractor for the cache key. This is consistent since GLiNER also runs on raw chunk.text (not enriched). The cache key does not need to match the embedding text_hash — it just needs to be stable and content-dependent.

```python
# In NERExtractor.extract(), per chunk:
chunk_text_hash = hashlib.blake2b(chunk.text.encode()).hexdigest()
cache_key = hashlib.blake2b(
    (chunk_text_hash + self._model_name + self._entity_types_hash).encode()
).hexdigest()
```

### Finding 7: extraction_cache Invalidation (D-11) [VERIFIED: code reading]

D-11: when NERExtractor loads a model, compare stored model_name and entity_types_hash; if changed → DELETE FROM extraction_cache.

The `_get_model()` method (line 166-183) does lazy loading. Invalidation logic should run at `NERExtractor.__init__()` time, not at model-load time — because at init time we have access to the cache connection.

However, NERExtractor currently receives no DB connection. Two approaches:
1. Pass `conn` to NERExtractor (adds a parameter)
2. Have pipeline check the invalidation condition and clear the cache before constructing NERExtractor

Approach 2 is cleaner and keeps NERExtractor free of storage concerns. In `IndexingPipeline.__init__()`:
```python
if settings.extract_depth == ExtractDepth.NER:
    # Check if model config changed → invalidate extraction_cache
    if self._extraction_cache.should_invalidate(
        settings.ner_model_name, entity_types_hash
    ):
        self._extraction_cache.clear()
    self._ner_extractor = NERExtractor(settings.ner_entity_types)
```

This follows the existing pattern where pipeline owns all storage concerns and extractors are pure computation.

---

## Common Pitfalls

### Pitfall 1: embedding_cache double-lookup inefficiency
**What goes wrong:** The existing `lookup_embeddings_by_text_hash()` already queries vec_meta across all strategy tables. If embedding_cache is checked AFTER this, we make two DB round-trips for every encode batch.
**How to avoid:** Check embedding_cache FIRST (it's a single indexed PK lookup), then fall through to vec_meta cross-strategy lookup for misses. The `existing` dict merge handles this: `existing.update(global_hits)` before the per-strategy lookup, or replace the per-strategy lookup with the global cache entirely.
**Note:** Plan 1 embedding_cache subsumes the cross-strategy vec_meta lookup for file-move scenarios. Both can coexist: embedding_cache = fast PK lookup; vec_meta = slower join (handles strategy switch without cache warmup).

### Pitfall 2: embedding_cache stores BLOB — need correct serialization
**What goes wrong:** `embedding_cache.embedding BLOB` — if stored as Python list, SQLite will serialize it as text representation, not binary, and retrieval will return a string.
**How to avoid:** Reuse `_serialize_f32()` from sqlite_vec.py for storage. For retrieval, use `struct.unpack()` same as `lookup_embeddings_by_text_hash()` lines 346-349. Both functions are already in sqlite_vec.py.

### Pitfall 3: extraction_cache JSON round-trip loses Pydantic types
**What goes wrong:** `entities` are `Entity` objects with Pydantic fields. `json.dumps(entities)` won't work directly.
**How to avoid:** Use `[e.model_dump() for e in entities]` for serialization, `[Entity(**d) for d in data]` for deserialization. Both `Entity` and `Relation` are Pydantic v2 models — `.model_dump()` / constructor round-trip is safe.

### Pitfall 4: Plan 3 migration — chunk_index in body_checksum vs chunk_index in chunk row
**What goes wrong:** D-14 says `blake3(body_checksum + ":" + chunk_index + ":" + chunk_strategy)`. The `body_checksum` from `chunk_fingerprints` is per-FILE (one row per file). The `chunk_index` is per-CHUNK. The migration must JOIN these correctly.
**How to avoid:** The migration iterates `chunks_{strategy}` rows (which have `chunk_index`), looks up `chunk_fingerprints_{strategy}` by `file_path` to get the per-file `checksum`, then computes the new ID. One file → many chunks, each with its own `chunk_index`.

SQL sketch:
```sql
UPDATE chunks_heading_512_50
SET chunk_id = blake3_udf(
    (SELECT checksum FROM chunk_fingerprints_heading_512_50 fp
     WHERE fp.file_path = chunks_heading_512_50.file_path)
    || ':' || chunk_index || ':heading_512_50'
)
```
Since SQLite has no built-in blake3, the migration script uses a Python UDF registered via `conn.create_function('blake3_udf', 1, ...)`.

### Pitfall 5: vec_meta rowid gap after drop_vectors
**What goes wrong:** `vec_meta` uses `AUTOINCREMENT`. After `drop_vectors()`, the `sqlite_sequence` counter is NOT reset. New insertions get rowids continuing from the last value. The `vec_chunks` (vec0) virtual table also uses rowids. If there's a mismatch between `vec_meta.rowid` and `vec_chunks.rowid`, the JOIN in `search()` returns wrong results.
**Why this matters for Plan 1:** The embedding_cache stores embeddings as BLOBs indexed by text_hash. This bypasses the rowid JOIN entirely. No rowid gap problem for the cache.
**For Plan 3:** The migration does NOT drop_vectors. It only updates chunk_id strings. rowids are preserved. No gap issue.

### Pitfall 6: FTS5 contextual vs heading have different column schemas
**What goes wrong:** `chunks_fts_heading_512_50` has `(chunk_id UNINDEXED, text)`. `chunks_fts_contextual_512_50` has `(chunk_id UNINDEXED, text, title, tags)`. A migration script that hardcodes INSERT columns will break on the wrong table.
**How to avoid:** The Plan 3 migration only UPDATEs `chunk_id` — it does not INSERT. Since `chunk_id` is `UNINDEXED` in both, a plain `UPDATE chunks_fts_{strategy} SET chunk_id=? WHERE chunk_id=?` works for both without knowing the other columns.

---

## Code Examples

### embedding_cache table DDL
```sql
-- Source: D-01 (CONTEXT.md, locked decision)
CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash TEXT PRIMARY KEY,
    embedding BLOB NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```

### extraction_cache table DDL
```sql
-- Source: D-07 (CONTEXT.md, locked decision)
CREATE TABLE IF NOT EXISTS extraction_cache (
    cache_key TEXT PRIMARY KEY,
    entities JSON NOT NULL,
    relations JSON NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
)
```

### blake3 usage (Plan 3)
```python
# Source: D-16 (CONTEXT.md) + verified via pip dry-run in container
import blake3

def _make_chunk_id(body_checksum: str, chunk_index: int, chunk_strategy: str) -> str:
    payload = f"{body_checksum}:{chunk_index}:{chunk_strategy}"
    return blake3.blake3(payload.encode()).hexdigest()
```

### extraction_cache key computation
```python
# Source: D-08 (CONTEXT.md) + Finding 6 (research)
import hashlib

def _make_extraction_cache_key(
    chunk_text: str, model_name: str, entity_types_hash: str
) -> str:
    chunk_text_hash = hashlib.blake2b(chunk_text.encode()).hexdigest()
    return hashlib.blake2b(
        (chunk_text_hash + model_name + entity_types_hash).encode()
    ).hexdigest()
```

### Migration script UDF registration pattern
```python
# Source: migration.py (existing pattern, line 80-83)
import blake3 as _blake3

conn.create_function(
    "blake3_udf", 1,
    lambda payload: _blake3.blake3(payload.encode() if isinstance(payload, str)
                                   else payload).hexdigest()
)
```

### Plan 3 migration UPDATE sketch (single strategy)
```python
# Source: live DB schema verification
# All three user-facing tables support plain UPDATE (verified)
with conn:
    # 1. Compute new IDs and build old→new mapping
    rows = conn.execute(
        f"SELECT c.chunk_id, fp.checksum, c.chunk_index "
        f"FROM chunks_{strategy} c "
        f"JOIN chunk_fingerprints_{strategy} fp ON fp.file_path = c.file_path"
    ).fetchall()

    id_map = {}
    for old_id, checksum, chunk_index in rows:
        new_id = blake3.blake3(
            f"{checksum}:{chunk_index}:{strategy}".encode()
        ).hexdigest()
        id_map[old_id] = new_id

    # 2. UPDATE all tables
    for old_id, new_id in id_map.items():
        conn.execute(
            f"UPDATE chunks_{strategy} SET chunk_id=? WHERE chunk_id=?",
            (new_id, old_id)
        )
        conn.execute(
            f"UPDATE chunks_fts_{strategy} SET chunk_id=? WHERE chunk_id=?",
            (new_id, old_id)
        )
        for meta_table in meta_tables:  # all vec_meta_{strategy}_* tables
            conn.execute(
                f"UPDATE {meta_table} SET chunk_id=? WHERE chunk_id=?",
                (new_id, old_id)
            )
```

---

## Runtime State Inventory

> Plan 3 is a rename/refactor phase for chunk_ids — runtime state audit required.

| Category | Items Found | Action Required |
|----------|-------------|-----------------|
| Stored data | `index.db`: chunk_id in `chunks_*`, `chunks_fts_*`, `vec_meta_*` — all tables verified | SQL UPDATE all tables in single transaction |
| Live service config | dotmd-api-1 container — must be stopped before migration | `docker compose stop` + restart after |
| OS-registered state | No OS-level chunk_id registrations | None |
| Secrets/env vars | No env vars reference chunk_ids | None |
| Build artifacts | No compiled artifacts reference chunk_ids | None |

**Nothing found in these categories:** OS-registered state, secrets/env vars, build artifacts — confirmed by inspection.

**Graph store (FalkorDB):** Section nodes in the graph store are keyed by `chunk_id` (see `add_section_node` in pipeline.py line 531). FalkorDB is a Redis-backed graph — it stores chunk_ids as node identifiers. **Plan 3 migration must also update FalkorDB section nodes**, or the graph search will return stale chunk_ids that no longer exist in `chunks_*`.

Options:
1. Run `pipeline.drop_chunks()` before migration → wipes graph. After migration, run `pipeline.reindex_graph()`. This is the safe option — graph is fully rebuilt.
2. Patch FalkorDB nodes individually via graph API. Complex, fragile.

**Recommended:** Option 1 — drop graph + reindex_graph() after migration. Since Plans 1+2 are already deployed and the embedding cache is warm, `reindex_graph()` calls `_run_extraction()` which hits the extraction cache. GLiNER does not re-run. Fast.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| blake3 | Plan 3 chunk_id | Not installed | — | Add to pyproject.toml; wheel available |
| sqlite3 | Plans 1, 2, 3 | ✓ | Python 3.12 stdlib | — |
| hashlib blake2b | Plans 1, 2 | ✓ | Python 3.12 stdlib | — |
| dotmd-api-1 container (Python 3.12, x86_64) | All | ✓ | Python 3.12.13 | — |
| index.db at /dotmd-index/index.db | All | ✓ | — | — |

**blake3 installation:** not blocking — wheel is confirmed available for the container's exact platform (`blake3-1.0.8-cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl`). Add to `pyproject.toml` dependencies. Container rebuild picks it up.

---

## Open Questions

1. **Where does CacheStore live in the module hierarchy?**
   - What we know: D-24 says cache tables are in index.db on the shared connection. The pipeline owns the connection.
   - What's unclear: Should cache be a new `storage/cache.py` class, or methods on `SQLiteMetadataStore`, or inline in `IndexingPipeline`?
   - Recommendation: New `storage/cache.py` with two thin classes (`EmbeddingCache`, `ExtractionCache`) following the existing storage pattern. Both take a `conn` parameter. Pipeline instantiates them in `__init__()`. This keeps extractors clean.

2. **Extraction cache: per-chunk or per-batch lookup?**
   - What we know: GLiNER uses `model.inference()` which processes ALL chunks as a batch. A partial hit (some chunks cached, some not) means calling inference with only the miss subset.
   - What's unclear: Is the per-chunk cache lookup loop fast enough, or should we batch the DB query?
   - Recommendation: One `SELECT cache_key FROM extraction_cache WHERE cache_key IN (?,?,...)` for the whole chunk list, then iterate. Single DB round-trip, fully batched.

3. **Plan 3 migration: FalkorDB section nodes need chunk_id update**
   - What we know: FalkorDB stores section nodes by chunk_id. After Plan 3, all chunk_ids change.
   - What's unclear: CONTEXT.md does not mention FalkorDB as a migration target.
   - Recommendation: Include `reindex_graph()` as a mandatory post-migration step. This is fast with warm extraction cache (D-20 prerequisite ensures this).

---

## Assumptions Log

| # | Claim | Section | Risk if Wrong |
|---|-------|---------|---------------|
| A1 | `reindex_graph()` after Plan 3 migration will be fast due to warm extraction cache | Open Questions #3 | If extraction cache is not warm, GLiNER reruns for all chunks — slow but correct |
| A2 | blake3 package API: `blake3.blake3(data).hexdigest()` | Code Examples | If API changed in 1.0.x, import or call will fail at runtime |

---

## Sources

### Primary (HIGH confidence — verified against live codebase/DB)
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/pipeline.py` — `_embed_chunks()` (lines 408-472), `_run_extraction()` (lines 1105-1135), `index_file()` (lines 853-1000)
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/chunker.py` — `_make_chunk_id()` (lines 22-25), `chunk_file()` (lines 121-239)
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/extraction/ner.py` — `NERExtractor.extract()` (lines 71-160), `_get_model()` (lines 166-183)
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/search/semantic.py` — `encode_batch()` (lines 203-217), `_encode_via_tei()` (lines 126-179)
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/storage/sqlite_vec.py` — `_ensure_tables()`, `add_chunks()`, `lookup_embeddings_by_text_hash()`, `delete_vectors_by_chunk_ids()`
- `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd/ingestion/migration.py` — migration pattern
- Live DB queries against `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` via `docker exec dotmd-api-1`

### Secondary (HIGH confidence — official package registry)
- `pip install --dry-run blake3` inside container: blake3-1.0.8 cp312 manylinux wheel confirmed [VERIFIED: docker exec]

---

## Metadata

**Confidence breakdown:**
- Insertion points (pipeline.py): HIGH — exact line numbers read, no guessing
- Table schema / UPDATE semantics: HIGH — live DB tested with SAVEPOINT/ROLLBACK
- text_hash format discrepancy: HIGH — confirmed by MD5 match on enriched text
- blake3 availability: HIGH — dry-run install confirmed in container
- FalkorDB graph impact: MEDIUM — code path clear but not explicitly tested

**Research date:** 2026-04-24
**Valid until:** 2026-05-24 (stable dependencies, 30-day horizon)
