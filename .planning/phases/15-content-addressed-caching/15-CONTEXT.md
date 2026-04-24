# Phase 15: Content-Addressed Caching — Context

**Gathered:** 2026-04-24
**Status:** Ready for planning
**Source:** Session context (expert panel 2026-04-23 + architectural analysis)

<domain>
## Phase Boundary

Eliminate expensive reindexing (GLiNER + TEI) when files move, mount paths change, or the knowledgebase is reorganized. Three improvements shipped in strict order: B → C → A.

**In scope:**
- Plan 1 (B): Global embedding cache by text_hash — skip TEI on file moves
- Plan 2 (C): Extraction cache by compound key — skip GLiNER on file moves
- Plan 3 (A): Content-based chunk_id + BLAKE3 migration — make chunk_ids path-independent

**Out of scope:**
- Fingerprint-by-content (would prevent trickle from detecting file moves at all — intentionally deferred)
- Extraction cache eviction policy (at ~7500 chunks, cache is ~7MB — negligible, revisit later)

</domain>

<decisions>
## Implementation Decisions

### Deploy Order (LOCKED)
- Plan 1 (B) first, then Plan 2 (C), then Plan 3 (A)
- Plans 1+2 must be deployed and cache must be warm before Plan 3 runs
- Reason: Plan 3 migration invalidates all vec_meta chunk_ids — if B is not yet warm, the migration leaves the embedding cache cold and TEI re-runs for all files

### Plan 1 — Embedding Cache

- D-01: New table `embedding_cache(text_hash TEXT PRIMARY KEY, embedding BLOB, created_at TEXT)` in index.db
- D-02: Cache key = `text_hash` (already computed as blake2b of enriched chunk text, stored in vec_meta)
- D-03: Lookup happens BEFORE calling TEI: if text_hash in embedding_cache → skip HTTP call, reuse vector
- D-04: On TEI result: store (text_hash, embedding) in embedding_cache
- D-05: No migration needed — new table, populated lazily
- D-06: No eviction initially — at ~10k chunks, 1024-dim float32 = ~40MB max, acceptable

### Plan 2 — Extraction Cache

- D-07: New table `extraction_cache(cache_key TEXT PRIMARY KEY, entities JSON, relations JSON, created_at TEXT)`
- D-08: Cache key = `blake2b(text_hash + model_name + entity_types_hash)` — compound key, NOT just text_hash
  - Reason: GLiNER results depend on model version and entity_types list; stale cache on model upgrade = silent wrong results
- D-09: Lookup happens BEFORE running GLiNER batch inference
- D-10: On GLiNER result: store (cache_key, entities_json, relations_json)
- D-11: Invalidation: when NERExtractor loads a model, compare stored `model_name` and `entity_types_hash` against config; if changed → DELETE FROM extraction_cache (full clear, not per-chunk)
- D-12: entity_types_hash = blake2b(sorted(entity_types).join(","))
- D-13: No migration — new table, populated lazily

### Plan 3 — Content-Based chunk_id + BLAKE3

- D-14: New chunk_id formula: `blake3(body_checksum + ":" + chunk_index + ":" + chunk_strategy)`
  - `body_checksum` = the checksum already stored in `chunk_fingerprints_*` tables (blake2b of body+kind)
  - NOT the full file bytes hash (which includes frontmatter — would change chunk_id on title/tag edits)
  - This resolves the open question: use chunk_fingerprint checksum, not FileInfo.checksum
- D-15: chunk_strategy included in key to prevent collisions between heading_512_50 and contextual_512_50
- D-16: Switch hashing to BLAKE3 for chunk_id computation (add `blake3` package to pyproject.toml)
  - Rationale: migration recomputes all hashes anyway, BLAKE3 is the modern standard, marginal cost = 0
  - All other hashing (text_hash, fingerprints) stays on blake2b (stdlib, no dep change)
- D-17: Migration procedure: stop container → cp index.db to /tmp backup → SQL UPDATE all tables → verify → restart
- D-18: Migration script is standalone Python, NOT run inside the container — runs against the volume directly
- D-19: Post-migration consistency check: every chunk_id in chunks_* must exist in vec_meta_*
- D-20: Plans 1+2 MUST be deployed and warm (at least one full index cycle) before Plan 3 runs
- D-21: FTS5 and sqlite_vec are virtual tables — chunk_id update requires DELETE + re-INSERT (not plain UPDATE)

### Architectural Constraints (from expert panel)

- D-22: GLiNER and TEI must NEVER run concurrently (CPU constraint on Xeon E3 V2, 8 threads, no AVX2)
- D-23: All cache lookups are synchronous (no async complexity added)
- D-24: Cache tables live in index.db alongside existing tables (no separate DB file)
- D-25: `text_hash` already exists in vec_meta — reuse, don't recompute

### Claude's Discretion
- Exact SQL DDL for new tables
- Where in pipeline.py to insert cache lookups (before GLiNER call in _run_extraction, before TEI call in _embed_chunks)
- JSON serialization format for extraction_cache entities/relations
- Whether to add indexes on cache tables (text_hash is PK, so already indexed)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Pipeline implementation
- `backend/src/dotmd/ingestion/pipeline.py` — index_file(), _run_extraction(), _embed_chunks()
- `backend/src/dotmd/ingestion/chunker.py` — _make_chunk_id() (line 22-25, the function to change)
- `backend/src/dotmd/extraction/ner.py` — NERExtractor.extract() (cache lookup goes here)
- `backend/src/dotmd/search/semantic.py` — SemanticSearchEngine.encode_batch(), _encode_via_tei() (cache lookup goes here)

### Storage
- `backend/src/dotmd/storage/sqlite_vec.py` — vec_meta table, text_hash column
- `backend/src/dotmd/ingestion/migration.py` — existing migration framework (Plan 3 migration follows same pattern)

### Schema reference (live DB)
- `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` — current schema, ~10317 chunks

### Planning context
- `.planning/notes/profiling-2026-04-02.md` — profiling data, CPU breakdown, benchmark files

</canonical_refs>

<specifics>
## Specific Implementation Notes

**Embedding cache lookup (Plan 1):**
```python
# In _embed_chunks(), before encode_batch():
cached = embedding_cache.lookup(text_hashes)  # {text_hash: vector}
texts_to_encode = [t for h, t in zip(hashes, texts) if h not in cached]
# ... encode missing ones, store results in embedding_cache
```

**Extraction cache lookup (Plan 2):**
```python
# In NERExtractor.extract() or _run_extraction():
cache_key = blake2b(text_hash + model_name + entity_types_hash)
if cache_key in extraction_cache:
    return cached_result
# ... run GLiNER, store result
```

**New chunk_id (Plan 3):**
```python
# In chunker.py _make_chunk_id():
import blake3
payload = f"{body_checksum}:{chunk_index}:{chunk_strategy}"
return blake3.blake3(payload.encode()).hexdigest()
```

**Migration SQL pattern (Plan 3):**
```sql
-- Per table, in a single transaction:
UPDATE chunks_{strategy} SET chunk_id = blake3_hash(
    chunk_fingerprints_{strategy}.checksum || ':' || chunk_index || ':' || '{strategy}'
) FROM chunk_fingerprints_{strategy}
WHERE chunks_{strategy}.file_path = chunk_fingerprints_{strategy}.file_path
-- FTS5 and vec tables require DELETE + INSERT
```

</specifics>

<deferred>
## Deferred

- Extraction cache eviction on model upgrade requires clearing the whole table — acceptable for now
- Embedding cache eviction policy — deferred (cache is small, ~40MB max)
- Fingerprint-by-content-hash (would need trickle redesign) — out of scope for this phase
- Pipeline parallelism (GLiNER/TEI queue) — Phase 999.2 backlog

</deferred>

---

*Phase: 15-content-addressed-caching*
*Context gathered: 2026-04-24 from session (expert panel 2026-04-23)*
