---
phase: 15
reviewers: [codex, opencode]
reviewed_at: 2026-04-24T16:45:00+05:00
plans_reviewed: [15-01-PLAN.md, 15-02-PLAN.md, 15-03-PLAN.md]
---

# Cross-AI Plan Review — Phase 15

## Codex Review

Note: review based on plan text and embedded interface snippets. Repo not directly inspected.

### Plan 15-01

**Summary**
Plan 01 is directionally sound and likely delivers the embedding half of the phase goal: it is additive, keyed on content, and avoids TEI work after path changes. The main weakness is that it treats embeddings as stable across model/config changes and introduces a `commit()` inside `_embed_chunks()` without addressing the pipeline's wider transaction boundaries.

**Strengths**
- Additive rollout is good: a new table plus lazy population keeps deployment low-risk.
- `text_hash -> vector` is the right abstraction for path-independent embedding reuse.
- Batched lookups and `INSERT OR IGNORE` fit the single-user SQLite environment well.
- Graceful degradation on cache lookup failure is appropriate; worst case is re-embedding, not wrong output.
- Plugs into `_embed_chunks()` at the correct point: before `encode_batch()` and after new vectors are computed.

**Concerns**
- `HIGH` The cache key omits embedding model/version/config. If TEI model or vector dimension changes, stale vectors can be reused silently.
- `HIGH` Calling `self._conn.commit()` inside `_embed_chunks()` may break existing transaction semantics on the shared connection and persist partial state earlier than intended.
- `MEDIUM` "Global cache wins on overlap" — if vec_meta already has a live embedding, overwriting from global cache is the riskier precedence rule.
- `MEDIUM` Verification is too shallow. AST/import checks do not prove TEI is skipped on cache hit.
- `LOW` Synchronous SQLite reads in the asyncio pipeline are probably fine relative to TEI latency, but the event loop blocking cost is unacknowledged.

**Suggestions**
- Add embedding model signature to cache key or add model-change invalidation similar to Plan 02's extraction cache.
- Avoid committing inside `_embed_chunks()`; defer commit to caller or use a savepoint.
- Add an integration test that mocks `encode_batch()` and asserts zero calls on a full cache hit.
- Log hit/miss counts separately for `vec_meta` and `embedding_cache`.

**Risk: MEDIUM**

---

### Plan 15-02

**Summary**
Plan 02 has the right objective and the right compound-key direction, but as written it has major correctness problems. The invalidation flow is internally inconsistent, and the cache payload stores chunk-id-dependent data, which directly conflicts with Plan 03's migration strategy.

**Concerns**
- `HIGH` `should_invalidate()` appears broken as specified. `ensure_table()` writes the current `model_sig`, then `should_invalidate()` compares against that same value — invalidation will never trigger.
- `HIGH` The cache key omits `threshold`, even though extraction output depends on it.
- `HIGH` Cached payload includes `chunk_ids` and `MENTIONS` relation `source_id`, which are chunk-id-dependent. After Plan 03 changes chunk IDs, reusing this cache will restore stale old IDs.
- `HIGH` Cached-hit merge logic does not clearly append the current chunk ID for repeated entities across cached chunks — entity aggregation may regress.
- `MEDIUM` `store_batch()` explicitly does not commit, but the plan does not define where persistence is guaranteed.
- `MEDIUM` No graceful path for malformed JSON rows or deserialization failures.

**Suggestions**
- Split table creation from signature persistence. `should_invalidate()` must compare against the *previous* stored signature before any write.
- Include `threshold` in the signature.
- Do not cache fully materialized Entity/Relation objects with chunk IDs embedded. Cache chunk-local facts (entity name, type, spans), then rebuild `chunk_ids`, `MENTIONS`, and co-occurrence relations for the *current* chunk IDs at read time.
- Add tests for partial hit/miss, threshold change, model change, and post-migration cache reuse.

**Risk: HIGH**

---

### Plan 15-03

**Summary**
Plan 03 shows good deployment discipline around backup, stop-the-world migration, and warm-cache gating, but it is not safe enough yet. Verification is too narrow, the migration is not robust against partial completion, and FalkorDB rebuild correctness depends on assumptions that are not enforced.

**Concerns**
- `HIGH` D-14's formula can collide across distinct files with identical full body content, same chunk index, and same strategy. If duplicate files exist, chunk IDs will collide by design.
- `HIGH` `needs_migration_v15()` is not safe for partially migrated databases. Sampling one table can misclassify a mixed state and skip unfinished work.
- `HIGH` Verification only checks `chunks_* -> vec_meta_*` orphan absence. Does not check duplicate new IDs, row-count drift, FTS consistency, cache payloads, or stale graph references.
- `HIGH` The warm-up gate is necessary but not sufficient. Proves caches have some data, not that `reindex_graph()` can run entirely from safe, chunk-id-independent cache payloads.
- `HIGH` FalkorDB handling underspecified: assumes `reindex_graph()` both rewrites chunk-id references AND removes stale old nodes/edges, but not verified.
- `MEDIUM` Per-strategy transactions mean a crash can leave the DB partially migrated across strategies.
- `MEDIUM` The JOIN on `fp.file_path = c.file_path` is only safe if `chunk_fingerprints_*` has exactly one row per file path.
- `MEDIUM` Migration runs outside the container but depends on host Python having `blake3` and compatible SQLite behavior.

**Suggestions**
- Add a migration version/state marker; make resume logic strategy-aware, not sample-based.
- Before applying updates, assert `COUNT(*) == COUNT(DISTINCT new_id)` per strategy and abort on collision.
- Expand verification: row counts, uniqueness checks, FTS row parity, scan for remaining 128-char IDs.
- Either redesign Plan 02's extraction cache to be chunk-id-independent or explicitly invalidate it during migration.
- Make graph rebuild destructive + verify no nodes/edges remain keyed by old IDs.

**Risk: HIGH**

---

## OpenCode Review

Note: OpenCode explored the live codebase during review.

### Plan 15-01

**Summary**
Plan 01 adds a standalone `EmbeddingCache` backed by an `embedding_cache` SQLite table, wired into `_embed_chunks()` as a secondary lookup after the existing `vec_meta` cross-strategy lookup. The design is straightforward and additive — no existing data or behavior is modified.

**Strengths**
- Correct layering: global cache checked *after* vec_meta lookup — avoids redundant deserialization.
- `INSERT OR IGNORE`: idempotent store semantics.
- Graceful degradation: `lookup()` returns `{}` on exception.
- No commit in `store()`: batch commit after encode loop is the right pattern.
- Batch size of 500 consistent with existing SQLite variable limits.

**Concerns**
- `HIGH` embedding_cache is a shadow vec_meta that never gets purged. Plan doesn't address when rows become stale after a model change. The existing `vec_config` stores model+dim for this reason.
- `MEDIUM` No `model` or `dim` column in schema. If embedding model changes (384-dim → 1024-dim), stale rows will deserialize to wrong dimensionality and produce silently incorrect vectors.
- `LOW` `ensure_table()` called in `__init__` — minor risk since dotmd is single-user.

**Suggestions**
- Add `model_name` column or make cache key `blake2b(text_hash + model_name)` to handle model upgrades.
- Add model-change invalidation similar to Plan 02's extraction cache.

**Risk: LOW** (model-change gap real but rare in practice)

---

### Plan 15-02

**Summary**
Plan 02 adds `ExtractionCache` with a compound key and sentinel-based invalidation. The compound key design is correct. Two significant concerns: `settings.ner_model_name` doesn't exist and needs its own task, and the full rewrite of `extract()` is high-risk.

**Strengths**
- Compound cache key (model_name + entity_types_hash) correctly prevents stale results on model/config changes.
- Sentinel-based invalidation is elegant and simpler than scanning all rows.
- Partial hit handling (`lookup_batch()` returns hits + miss_chunks) — GLiNER only runs on misses.
- Cache keyed on `chunk.text` (not enriched text) — correct, NER runs on raw text.

**Concerns**
- `HIGH` `settings.ner_model_name` does not exist in Settings. The plan's pipeline.py wiring code uses it unconditionally. Adding it to config.py is buried as a footnote in Task 2, not a dedicated task.
- `HIGH` Cache key uses raw `chunk.text` via internal blake2b — but naming relative to D-08 is confusing (D-08 says "text_hash" which in the codebase means enriched-text hash). Plan should explicitly state the extraction cache key uses raw chunk.text, not the pipeline's text_hash.
- `MEDIUM` Full rewrite of `extract()` (80 lines with non-trivial dedup logic). Any subtle change in `seen_entities` or relation generation could silently corrupt the graph. Wrapper pattern would be safer.
- `MEDIUM` `store_batch()` stores per-chunk results, but Entity.chunk_ids from cached results may reference old chunk IDs if reused after Plan 03. Plan 03 migration updates vec_meta chunk_ids but NOT extraction_cache rows.

**Suggestions**
- Give `ner_model_name` config addition its own task in Plan 02.
- Extract cache logic into a wrapper around existing `extract()`, not an interleaved rewrite.
- Add note clarifying that extraction cache key hashes `chunk.text` (raw), not pipeline's text_hash (enriched).
- Consider storing extraction_cache rows without materialized chunk_ids; rebuild them at read time.

**Risk: MEDIUM**

---

### Plan 15-03

**Summary**
Plan 03 shows good operational discipline (backup-first, warm-gate, verify). Several implementation details are actually safe (FTS5 UPDATE on UNINDEXED column, JOIN on file_path PK, both caches survive migration). Main risks: FalkorDB rebuild when reindex_graph() creates a new pipeline instance, and migration resume logic.

**Strengths**
- Staged rollout (additive caches first, migration last) is correct.
- Mandatory backup before mutation.
- `chunks_*`, `chunks_fts_*`, `vec_meta_*` UPDATE targets the critical surfaces.
- Explicit post-migration graph rebuild in checkpoint.
- `needs_migration_v15()` uses hash length as signal (128 = blake2b, 64 = blake3).

**Concerns**
- `HIGH` FalkorDB migration is underspecified: `reindex_graph()` creates a *new* `IndexingPipeline` instance. The extraction cache must be warm and `should_invalidate()` must return False on the new instance. Correct IF caches warm, but the checkpoint should explicitly verify this.
- `HIGH` FTS5 UPDATE safety confirmed (UNINDEXED column): actually fine. But should be explicitly noted in plan.
- `MEDIUM` `blake3` hexdigest is 64 chars (256-bit). `needs_migration_v15()` checks for 128-char (blake2b). This is correct.
- `MEDIUM` Migration runs outside container. Needs host to have `blake3` + compatible SQLite extension. Checkpoint step 1 (`pip install blake3`) handles this.
- `LOW` Plan's `kind` defaulting to `DocKind.DOCUMENT` in `get_all_chunks()` — not stored in chunks table. Migration uses `chunk_fingerprints.checksum` (which was computed with real kind). After migration, new chunks compute body_checksum with real kind. So fingerprint-based migration is correct.

**Suggestions**
- Checkpoint step 8 (reindex_graph) should explicitly verify that a *new* IndexingPipeline instance sees the warm extraction cache.
- Add `COUNT(*) == COUNT(DISTINCT chunk_id)` uniqueness assertion to migration verification.
- Note in migration script that FTS5 chunk_id UPDATE is safe because UNINDEXED.

**Risk: MEDIUM** (migration is correct as designed, FalkorDB concern is manageable with explicit verification)

---

## Consensus Summary

### Agreed Strengths
- Additive rollout (Plans 1+2 first, migration last) is the correct approach
- Compound cache key for extraction (model + entity_types) correctly handles model upgrades
- Backup-first migration pattern is correct operational default
- Lazy cache population (no up-front migration for Plans 1+2) is good

### Agreed Concerns (HIGH priority — address before executing)

1. **Plans 1+2 missing model/config in cache invalidation**: Embedding cache has no model version; stale vectors after model change. Both reviewers flagged this.

2. **Plan 02 should_invalidate() logic**: Codex found that writing model_sig in `ensure_table()` before checking in `should_invalidate()` means invalidation never triggers. OpenCode confirmed the sentinel design is correct in principle but flagged the same initialization ordering risk.

3. **Plan 02 extraction cache stores chunk-id-dependent data**: Cached `MENTIONS` relations have `source_id = chunk_id`. After Plan 03 migration, reusing cached extraction results restores old chunk IDs. Design should cache chunk-local facts (name, type, spans) and rebuild chunk_id-dependent relations at read time.

4. **Plan 03 FalkorDB rebuild underspecified**: Both reviewers flagged that `reindex_graph()` on a new pipeline instance must see warm caches to avoid GLiNER re-run. Checkpoint needs explicit verification.

### Divergent Views

- **Transaction semantics (Plan 01)**: Codex flagged commit inside `_embed_chunks()` as HIGH risk; OpenCode did not flag it. Investigate whether existing pipeline already commits at this point.
- **Plan 03 risk level**: Codex rated HIGH; OpenCode rated MEDIUM. OpenCode confirmed several concerns (FTS5 UPDATE safety, JOIN safety, cache survival) by reading the actual code. Codex worked from plan text only. OpenCode's MEDIUM is probably more accurate.
- **Plan 02 rewrite risk**: OpenCode strongly recommends wrapper pattern; Codex notes the rewrite can work if correct. Consensus: wrapper is safer.
