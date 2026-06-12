# Phase 38 Plan 01 Migration Map

This map covers every D-01 category and assigns an explicit disposition based on verified Phase 38 copied-snapshot or read-only exporter evidence.

Legend:

- `transformable` — current source artifacts are sufficient for transform-only import planning
- `unsafe` — source exists but the current evidence is insufficient to trust transform-only import
- `unsupported` — category is outside the approved D-01 migration surface

## D-01 Category Map

| Category | Disposition | Transform target | Verified source artifacts | Required source columns / properties | CPU recomputation required | Safety caveats |
|---|---|---|---|---|---|---|
| Existing chunks | `transformable` | `surreal::chunks` | copied `index-phase38.db` snapshot | `chunks_contextual_512_50.chunk_id`, `heading_hierarchy`, `level`, `text` | `no` | Preserve current `chunk_id` values and active `contextual_512_50` strategy semantics; do not regenerate chunks. |
| Provenance | `transformable` | `surreal::provenance` | copied `index-phase38.db` snapshot | `chunk_source_provenance_contextual_512_50.chunk_id`, `namespace`, `document_ref`, `source_unit_refs`, `chunk_strategy`, `parser_name`; `chunk_file_paths_contextual_512_50.chunk_id`, `file_path`, `chunk_index` | `no` | Import must preserve JSON `source_unit_refs` and M2M holder multiplicity; `149836` provenance rows exceed the `149739` chunk rows because provenance is not one-row-per-chunk. |
| Bindings | `transformable` | `surreal::bindings` | copied `index-phase38.db` snapshot | `resource_bindings.namespace`, `resource_ref`, `document_ref`, `ref`, `active`, `bound_at`, `unbound_at`, `content_fingerprint`, `metadata_fingerprint`, `source_unit_refs`, `metadata_json`; `source_documents.*` | `no` | Keep active/inactive lifecycle state (`1523` bindings, 4 inactive per prior state notes) and do not collapse `source_documents` into bindings. |
| Fingerprints | `transformable` | `surreal::fingerprints` | copied `index-phase38.db` snapshot | `chunk_fingerprints_contextual_512_50.file_path`, `mtime`, `size_bytes`, `checksum`, `indexed_at`; `embed_fingerprints_contextual_512_50_multilingual_e5_large.*`; `meta_fingerprints_contextual_512_50_multilingual_e5_large.*`; `source_unit_fingerprints.namespace`, `document_ref`, `unit_ref`, `fingerprint`, `updated_at`, `indexed_at`, `metadata_json` | `no` | Preserve chunk/embed/meta/source-unit fingerprints as separate concepts; do not recompute hashes during import. Legacy heading-strategy fingerprint surfaces can remain empty if the live snapshot count is `0`. |
| Source state | `transformable` | `surreal::source_state` | copied `index-phase38.db` snapshot | `source_checkpoints.namespace`, `checkpoint_cursor`, `last_success_at`, `last_error`, `metadata_json`; `source_documents.updated_at`; `resource_bindings.bound_at`, `unbound_at` | `no` | Snapshot shows only `1` checkpoint row, so import logic must not assume multi-namespace state is already populated. |
| sqlite-vec embeddings | `transformable` | `surreal::embeddings` | copied `index-phase38.db` snapshot | `vec_meta_contextual_512_50_multilingual_e5_large.rowid`, `chunk_id`, `text_hash`; `vec_chunks_contextual_512_50_multilingual_e5_large` row payload; `vec_config_contextual_512_50_multilingual_e5_large` | `no` | Import must decode stored sqlite-vec payloads and preserve `rowid` alignment; no TEI calls are allowed. Heading-strategy vec tables are present but currently empty. |
| Vector components | `transformable` | `surreal::vector_components` | copied `index-phase38.db` snapshot | `vec_components_contextual_512_50_multilingual_e5_large.entity_id`, `component`, `embedding` | `no` | Keep `text` and `meta` component rows distinct; do not fuse or recompute vectors during import rehearsal. |
| FalkorDB graph data | `transformable` | `surreal::graph` | live Falkor read-only exporter | Node labels `File`, `Section`, `Entity`, `Tag`; edge semantic labels from `REL.rel_type`; edge property keys `rel_type`, `weight`; sampled property types `string`, `float` | `no` | Sample evidence shows the live graph stores semantic type in `rel_type`, not in distinct physical edge labels. Plan 38-02 must preserve both `rel_type` and numeric `weight`. |
| Feedback | `transformable` | `surreal::feedback` | supported CLI exporter + copied `feedback-phase38.db` file-level snapshot | exporter fields `status`, `submitted_at`, `severity`, `message`; file-level evidence from `feedback.db` snapshot manifest | `no` | Counts must continue to come from supported exporter paths. Direct SQL against live `feedback.db` remains out of bounds. |

## Non-D-01 Surfaces Explicitly Flagged

These are not left implicit:

| Surface | Current status | Why not treated as a D-01 migration category |
|---|---|---|
| `embedding_cache`, `embedding_cache_meta` | verified present | cache implementation detail, not a required user-visible persistent domain category |
| `extraction_cache`, `extraction_cache_meta` | verified present | cache implementation detail, not a required user-visible persistent domain category |
| `migration_v16_lock`, `migration_v16_state` | verified present | legacy migration scaffolding; operational artifact, not target-domain data |
| `search_log` | verified present | diagnostic/history surface; not in the D-01 must-migrate list |
| sqlite-vec shadow tables (`*_chunks`, `*_info`, `*_rowids`, `*_vector_chunks00`) | verified present | backend storage mechanics behind `vec_chunks_*`, not independent domain records |
| `stats` | table present, no row returned | not safe to treat as canonical current state without separate producer validation |

## Recommendation Boundary for Next Plans

What this plan proves:

- Every required D-01 category currently has enough source artifacts to attempt transform-only import planning.
- No category currently requires default rechunking, TEI reembedding, or NER/entity re-extraction just to start the Surreal import rehearsal.
- Graph semantics are richer than aggregate counts and must carry through as `rel_type` + `weight`.

What this plan does **not** prove:

- Retrieval parity inside SurrealDB
- Embedded single-writer/atomicity safety
- Backup/restore and rollback acceptability
- That any cache or diagnostics table should be migrated at all

Phase 38-02 should therefore treat all nine D-01 rows above as transform-first inputs, while keeping the explicitly flagged non-D-01 surfaces out of the required success path unless later plans justify them.
