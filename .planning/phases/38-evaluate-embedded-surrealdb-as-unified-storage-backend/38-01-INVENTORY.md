# Phase 38 Plan 01 Inventory Evidence

Generated on 2026-06-12 from copied/read-only production sources only.

## Mutation Discipline

- Live stores were not mutated for this evidence capture.
- SQLite evidence was taken from copied snapshots created with `copy_sqlite_snapshot()` via the SQLite backup API, not by querying or rewriting the live files in place.
- Graph evidence was taken through a read-only Falkor exporter probe inside the running `dotmd` container.
- Feedback counts were taken through the supported CLI surface `dotmd feedback list --all`; no direct SQL was used against `feedback.db`.
- Snapshot artifacts live outside git under `/tmp/dotmd-phase38-snapshot` inside the running `dotmd` container. No production-size database snapshot was added to the repository.

## Source Locations

Docker mount inspection reported:

- Host volume: `/var/lib/docker/volumes/dotmd_dotmd-index/_data`
- Container mount: `/dotmd-index`
- Source code bind mount: `/home/j2h4u/repos/j2h4u/dotmd/backend/src/dotmd -> /app/src/dotmd`

Production sources used in this plan:

| Surface | Source path | Access mode | Notes |
|---|---|---|---|
| Main SQLite index | `/dotmd-index/index.db` | copied snapshot | Host-mounted from `/var/lib/docker/volumes/dotmd_dotmd-index/_data/index.db` |
| Feedback SQLite | `/dotmd-index/feedback.db` | copied snapshot for file-level evidence + CLI exporter for counts | Host-mounted from `/var/lib/docker/volumes/dotmd_dotmd-index/_data/feedback.db` |
| Falkor graph | live `dotmd` graph via Falkor Python client inside container | read-only exporter | Used `MATCH`/`ro_query` only |

## SQLite Snapshot Evidence

### `index.db`

| Field | Value |
|---|---|
| Source path | `/dotmd-index/index.db` |
| Snapshot path | `/tmp/dotmd-phase38-snapshot/index-phase38.db` |
| Snapshot created at | `2026-06-12T14:15:22.340143+00:00` |
| Snapshot strategy | `sqlite-backup` |
| Source journal mode at snapshot time | `wal` |
| Source sidecars detected at snapshot time | `index.db-wal`, `index.db-shm` |
| Source size | `2553180160` bytes |
| Snapshot size | `2553192448` bytes |
| Snapshot SHA256 | `929908763008716a4a6588f81621f5496725ea12a3ff4dcc5765bd3d9413a876` |
| Source mtime unchanged | `true` |
| Source size unchanged | `true` |

Interpretation:

- WAL/SHM consistency was handled by the SQLite backup API. The snapshot merged the live WAL state into one standalone `.db` copy instead of relying on an incomplete filesystem copy of `index.db` alone.
- The snapshot is slightly larger than the live base file because WAL state was materialized into the backup copy.

### `feedback.db`

| Field | Value |
|---|---|
| Source path | `/dotmd-index/feedback.db` |
| Snapshot path | `/tmp/dotmd-phase38-snapshot/feedback-phase38.db` |
| Snapshot created at | `2026-06-12T14:15:52.226626+00:00` |
| Snapshot strategy | `sqlite-backup` |
| Source journal mode at snapshot time | `wal` |
| Source sidecars detected at snapshot time | `feedback.db-wal`, `feedback.db-shm` |
| Source size | `28672` bytes |
| Snapshot size | `28672` bytes |
| Snapshot SHA256 | `abd8ca70c0c2ab1de75a2710437c760ceb779cd975128fe191eb4a012c0552a5` |
| Source mtime unchanged | `true` |
| Source size unchanged | `true` |

Interpretation:

- File-level snapshot evidence exists for `feedback.db`, but row counts below come from the supported `dotmd feedback list --all` exporter surface rather than direct SQL.

## Verified Snapshot Counts

All counts in this section were read from the copied `index-phase38.db` snapshot unless noted otherwise.

### Core SQLite Surfaces

| Category | Verified count | Source |
|---|---|---|
| Chunks (`chunks_*`, non-FTS) | `149739` | copied snapshot |
| FTS rows (`chunks_fts_*`) | `150396` | copied snapshot |
| Vector metadata rows (`vec_meta_*`) | `149739` | copied snapshot |
| Raw vector component rows (`vec_components_*`) | `156842` | copied snapshot |
| Source documents | `1421` | copied snapshot |
| Resource bindings | `1523` | copied snapshot |
| Source checkpoints | `1` | copied snapshot |
| Source unit fingerprints | `143975` | copied snapshot |
| Chunk fingerprints | `1261` | copied snapshot |
| Embed fingerprints | `923` | copied snapshot |
| Cache rows (aggregate of cache tables) | `156012` | copied snapshot |

### Transform-Relevant Tables Exposed as Drift/Unmapped Evidence

These tables were intentionally surfaced in `unmapped_tables` rather than silently folded into aggregates:

| Table | Verified count | Why it matters |
|---|---:|---|
| `chunk_file_paths_contextual_512_50` | `24221` | M2M holder bindings for the active strategy |
| `chunk_file_paths_heading_512_50` | `0` | Legacy heading strategy holder table; no live rows |
| `chunk_source_provenance_contextual_512_50` | `149836` | Direct provenance rows needed for transform-only migration |
| `meta_fingerprints_contextual_512_50_multilingual_e5_large` | `1080` | Metadata-only fingerprint fast path |
| `embedding_cache` | `149548` | Current embedding reuse cache surface |
| `embedding_cache_meta` | `1` | Embedding cache metadata |
| `extraction_cache` | `6462` | Extraction reuse cache surface |
| `extraction_cache_meta` | `1` | Extraction cache metadata |
| `vec_chunks_contextual_512_50_multilingual_e5_large` | `149739` | Actual sqlite-vec payload rows aligned by `rowid` |
| `vec_chunks_heading_512_50_multilingual_e5_large` | `0` | Legacy heading-strategy vec table; no live rows |

Additional unmapped tables exposed by the helper:

- `migration_v16_lock`
- `migration_v16_state`
- `search_log`
- `sqlite_sequence`
- `stats` (present, but `SELECT ... FROM stats LIMIT 1` returned no row)
- `vec_chunks_contextual_512_50_multilingual_e5_large_chunks`
- `vec_chunks_contextual_512_50_multilingual_e5_large_info`
- `vec_chunks_contextual_512_50_multilingual_e5_large_rowids`
- `vec_chunks_contextual_512_50_multilingual_e5_large_vector_chunks00`
- `vec_chunks_heading_512_50_multilingual_e5_large_chunks`
- `vec_chunks_heading_512_50_multilingual_e5_large_info`
- `vec_chunks_heading_512_50_multilingual_e5_large_rowids`
- `vec_chunks_heading_512_50_multilingual_e5_large_vector_chunks00`
- `vec_config_contextual_512_50_multilingual_e5_large`
- `vec_config_heading_512_50_multilingual_e5_large`

Interpretation:

- Snapshot drift is visible and explicit. Plan 38-02 should consume these extra tables deliberately instead of pretending the storage surface is only the high-level aggregates.
- The active live strategy is clearly `contextual_512_50`; heading-strategy vec/M2M tables are present but empty.

## Verified Column Shapes

Copied snapshot `PRAGMA table_info(...)` results for D-01 migration inputs:

| Table | Columns |
|---|---|
| `chunks_contextual_512_50` | `chunk_id`, `heading_hierarchy`, `level`, `text` |
| `chunk_source_provenance_contextual_512_50` | `chunk_id`, `namespace`, `document_ref`, `source_unit_refs`, `chunk_strategy`, `parser_name` |
| `chunk_file_paths_contextual_512_50` | `chunk_id`, `file_path`, `chunk_index` |
| `resource_bindings` | `namespace`, `resource_ref`, `document_ref`, `ref`, `active`, `bound_at`, `unbound_at`, `content_fingerprint`, `metadata_fingerprint`, `source_unit_refs`, `metadata_json` |
| `source_documents` | `namespace`, `document_ref`, `ref`, `source_uri`, `file_path`, `media_type`, `parser_name`, `document_type`, `title`, `updated_at`, `content_fingerprint`, `metadata_fingerprint`, `metadata_json` |
| `source_checkpoints` | `namespace`, `checkpoint_cursor`, `last_success_at`, `last_error`, `metadata_json` |
| `source_unit_fingerprints` | `namespace`, `document_ref`, `unit_ref`, `fingerprint`, `updated_at`, `indexed_at`, `metadata_json` |
| `chunk_fingerprints_contextual_512_50` | `file_path`, `mtime`, `size_bytes`, `checksum`, `indexed_at` |
| `embed_fingerprints_contextual_512_50_multilingual_e5_large` | `file_path`, `mtime`, `size_bytes`, `checksum`, `indexed_at` |
| `meta_fingerprints_contextual_512_50_multilingual_e5_large` | `file_path`, `mtime`, `size_bytes`, `checksum`, `indexed_at` |
| `vec_meta_contextual_512_50_multilingual_e5_large` | `rowid`, `chunk_id`, `text_hash` |
| `vec_components_contextual_512_50_multilingual_e5_large` | `entity_id`, `component`, `embedding` |

## FalkorDB Graph Evidence

Graph evidence was collected read-only inside the running `dotmd` container through the Falkor Python client using `ro_query()` only.

### Verified Live Counts

| Label / relation | Verified count | Source |
|---|---:|---|
| `File` nodes | `1080` | live Falkor read-only exporter |
| `Section` nodes | `23857` | live Falkor read-only exporter |
| `Entity` nodes | `28838` | live Falkor read-only exporter |
| `Tag` nodes | `274` | live Falkor read-only exporter |
| `REL` edges total | `353700` | live Falkor read-only exporter |
| `CONTAINS` | `24302` | live Falkor read-only exporter |
| `CO_OCCURS` | `166477` | live Falkor read-only exporter |
| `HAS_PARTICIPANT` | `93` | live Falkor read-only exporter |
| `HAS_TAG` | `1095` | live Falkor read-only exporter |
| `LINKS_TO` | `13927` | live Falkor read-only exporter |
| `MENTIONS` | `133114` | live Falkor read-only exporter |
| `PARENT_OF` | `14692` | live Falkor read-only exporter |

### Relation Property Shape Summary

The exporter sampled up to 200 edges per `rel_type` and preserved the observed property keys and Python-level value types. This is verified sample evidence, not an exhaustive scan of every edge payload.

| Relation label | Sample size | Metadata keys observed | Property value types observed | Weight sample |
|---|---:|---|---|---|
| `CONTAINS` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |
| `CO_OCCURS` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |
| `HAS_PARTICIPANT` | `93` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |
| `HAS_TAG` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |
| `LINKS_TO` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |
| `MENTIONS` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `0.0`, `1.0`, `2.0`, `3.0`, `4.0` |
| `PARENT_OF` | `200` | `rel_type`, `weight` | `rel_type=string`, `weight=float` | `1.0` |

Interpretation:

- The live graph currently uses one physical edge label `REL` plus semantic edge typing in `r.rel_type`.
- Phase 38 import work must preserve both the semantic relation label and the numeric `weight`; flattening graph evidence to node/edge totals would lose live retrieval semantics.

## Feedback Evidence

Feedback row counts were exported through the supported CLI surface:

- Command: `docker exec dotmd dotmd feedback list --all`
- Parsed summary: `total=5`, `statuses={'done': 5}`

Interpretation:

- Feedback is live and non-empty, but currently all entries are historical/closed (`done`).
- The plan requirement to avoid direct SQL against `feedback.db` was preserved.

## Verified vs Inferred

- Verified live or copied-snapshot counts:
  - all SQLite counts in the tables above
  - both SQLite snapshot manifests and checksums
  - all graph node/edge counts
  - feedback total/status counts from CLI output
- Verified sample-only evidence:
  - graph edge property key/type summaries (sampled up to 200 edges per relation label)
- Not inferred or fabricated:
  - no unavailable category was silently filled with guessed counts
  - no TEI/NER recomputation was triggered to “discover” missing data

## Outcome for Plan 38-02

Phase 38 now has copied-snapshot evidence for:

- current chunk, binding, provenance, fingerprint, source-state, sqlite-vec, and cache surfaces
- current graph node/edge/relation property shapes
- current feedback volume via supported exporter surface

This is sufficient to design a transform-only import rehearsal in Plan 38-02 without defaulting to rechunking, TEI reembedding, or NER/entity re-extraction.
