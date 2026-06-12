# Phase 38 Plan 02 Import Proof

## Scope

- This prototype is a **thin prototype adapter** only.
- It is **not** wired into `DotMDService`, `IndexingPipeline`, CLI defaults, Docker compose, or production startup.
- Apply mode is gated by Phase 38 Plan 05 embedded safety evidence. If the gate file is missing or `go_no_go` is not `PASS`, apply mode returns a blocked report and writes nothing.

## Gate Dependency

- Source gate: [`38-05-EMBEDDED-SAFETY-GATE.md`](./38-05-EMBEDDED-SAFETY-GATE.md)
- Required signal: `go_no_go: PASS`
- Import code path: `backend/src/dotmd/ingestion/migrate_surreal.py`
- Guard used: `assert_embedded_safety_gate_passed(...)`

## Fixture Import Counts

These counts come from the deterministic fixture exercised by:

- `backend/tests/storage/test_surreal_storage_contract.py`
- `backend/tests/ingestion/test_surreal_transform_only_migration.py`

Dry-run and apply share the same counting path.

| Category | Count | Evidence |
|---|---:|---|
| documents | 2 | `source_documents` fixture rows |
| source units | 3 | `source_unit_fingerprints` fixture rows |
| chunks | 2 | `chunks_contextual_512_50` fixture rows |
| embeddings | 2 | `vec_meta_*` + `vec_chunks_*` joined by `rowid` |
| vector components | 2 | `vec_components_*` fixture rows |
| entities | 1 | fake graph exporter row |
| relations | 2 | fake graph exporter rows |
| feedback | 2 | provider-backed `list_all(limit=1000, include_closed=True)` |
| cursors | 2 | `resource_bindings` rows preserved as cursor/reference audit rows |
| checkpoints | 1 | `source_checkpoints` row |

## Special-Identifier Safety

The central **record-ID** codec covers identifiers containing:

- colon
- slash
- spaces
- brace characters
- quotes
- Unicode

Test fixture examples include:

- `chunk:/ one {"quoted"} Привет`
- `filesystem:/tmp/Doc One {"quoted"} Привет.md`
- `entity:/ two {"named"} Привет`
- `feedback:/ one {"quoted"}`

The adapter encodes caller-owned IDs before they become Surreal record identifiers and preserves the original values in explicit payload fields like `original_chunk_id`, `original_entity_name`, and `original_feedback_id`.

## Transform-Only Coverage

Imported as stored data, without rechunking, reembedding, or entity re-extraction:

- chunks
- provenance
- bindings
- fingerprints
- source state / checkpoints
- sqlite-vec embeddings
- vector components
- graph entities and relations
- feedback rows

Explicitly rejected from the import path:

- TEI calls
- GLiNER / extraction calls
- indexing pipeline startup
- direct `feedback.db` SQL access
- source-markdown derivation as a replacement for stored rows

## Graph Preservation Proof

The fake graph exporter proves that import rows preserve:

- relation labels such as `MENTIONS` and `HAS_TAG`
- numeric weights
- metadata keys
- typed edge property values

Covered edge property examples:

- `confirmed: true` stays boolean
- `rank: 7` stays integer
- `weight: 0.75` stays float
- `evidence: "quoted name"` stays string

## Copied-Snapshot Readiness From Plan 38-01

Plan 38-01 already captured production-derived copied-snapshot counts in
[`38-01-INVENTORY.md`](./38-01-INVENTORY.md). The import prototype is designed
to consume those surfaces without recomputation.

Snapshot evidence recorded in Plan 38-01:

- SQLite snapshot path: `/tmp/dotmd-phase38-snapshot/index-phase38.db`
- Feedback snapshot path: `/tmp/dotmd-phase38-snapshot/feedback-phase38.db`
- Snapshot strategy: SQLite backup API with WAL-safe copied snapshot discipline

Production-derived counts recorded in Plan 38-01:

| Category | Count |
|---|---:|
| chunks | 149739 |
| FTS rows | 150396 |
| vec meta rows | 149739 |
| vec component rows | 156842 |
| source documents | 1421 |
| resource bindings | 1523 |
| source checkpoints | 1 |
| source unit fingerprints | 143975 |
| chunk fingerprints | 1261 |
| embed fingerprints | 923 |

This plan does **not** mutate those copied snapshots or the live production volumes.

## Unsupported Production Behaviors

The current prototype intentionally does **not** claim:

- retrieval parity
- production-grade transactional rollback semantics
- production-grade migration orchestration
- live-service wiring
- production backup/restore recommendation

Current rollback-on-error behavior is limited to clearing the dedicated
prototype Surreal tables after an apply failure. That is acceptable for this
Phase 38 evidence-gathering spike, but it is not a production migration claim.

## D-01 Boundary

Imported by transform:

- current chunks and refs
- provenance and holder/file-path multiplicity
- source bindings and active/inactive state
- stored fingerprints
- source checkpoints
- stored vector values and vector row identity
- vector component rows
- graph identities, relation labels, and edge property payloads
- feedback rows through the approved provider/exporter abstraction

Still unsupported or deferred in this plan:

- FTS/vector/graph retrieval parity inside Surreal
- migrate/defer/reject recommendation
- production restore drills
- changing the default runtime backend
