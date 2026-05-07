---
phase: "27"
plan: "01"
type: tdd
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/storage/metadata.py
  - backend/tests/storage/test_metadata_m2m.py
autonomous: true
requirements: ["R1", "R2", "R8"]
requirements_addressed: ["R1", "R2", "R8"]
must_haves:
  truths:
    - "D-01: Active resource binding state is the normal public search/read visibility gate."
    - "D-02: Unbinding hides public output without deleting retained content."
    - "D-03: Phase 27 exposes diagnostics/counts only; no recycle-bin search."
    - "D-04: Retained artifacts include chunks, embeddings, FTS rows, graph artifacts, source/chunk provenance, and metadata needed for reuse."
    - "D-06: Historical soft-delete TTL behavior is not current product truth."
    - "D-07: Reuse identity is content/source-unit fingerprint based, not path-only."
    - "D-08: Equivalent content can rebind to retained artifacts without recomputation when fingerprints match."
    - "Review feedback: existing source_documents rows must be backfilled into active resource_bindings before public active filtering lands."
    - "Review feedback: content_fingerprint and metadata_fingerprint are produced from SourceDocument values; source_documents remains the source of truth for active document metadata."
    - "Full-reindex answer: this plan requires no dotmd index --force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild."
---

# Phase 27 Plan 01: Storage Binding State

<objective>
Add the generic storage/domain foundation for active and inactive resource
bindings while preserving existing source documents and derived artifact rows.

This plan must be safe on the existing production database: when the table is
created, existing `source_documents` rows receive active filesystem bindings
idempotently before any public active-filtering code can reject them.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Existing Phase 26 refs disappear after active filtering because bindings are empty | HIGH | Backfill active bindings from every existing `source_documents` row in the same storage readiness path that creates the table. |
| `resource_bindings` becomes a second source of truth for document metadata | HIGH | Document and test that `source_documents` is the source of truth for active/current content and metadata fingerprints; binding rows hold activity state plus a fingerprint snapshot for retained lookup. |
| Fingerprint fields are required but no writer owns them | HIGH | Produce `content_fingerprint` and `metadata_fingerprint` from the already persisted `SourceDocument` values in backfill/upsert helpers. |
| Unbind deletes metadata/provenance needed for reuse | HIGH | Storage tests assert inactive binding leaves `source_documents`, provenance, chunks, FTS, vector metadata, and graph-owned rows untouched. |
| Schema migration forces full reindex | HIGH | Use idempotent `CREATE TABLE IF NOT EXISTS`, `INSERT ... ON CONFLICT`, and no rebuild of vectors/FTS/graph/chunks. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add resource binding domain model and SQLite table helpers</title>
<name>Add resource binding domain model and SQLite table helpers</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-RESEARCH.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-PATTERNS.md`
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Introduce a generic resource binding model and storage helpers.

Concrete target state:
- Add `ResourceBinding` in `backend/src/dotmd/core/models.py` with:
  - `namespace: str`
  - `resource_ref: str`
  - `document_ref: str`
  - `ref: str`
  - `active: bool = True`
  - `bound_at: datetime`
  - `unbound_at: datetime | None = None`
  - `content_fingerprint: str`
  - `metadata_fingerprint: str`
  - `source_unit_refs: list[str] = Field(default_factory=list)`
  - `metadata_json: dict = Field(default_factory=dict)`
- Validate that `ref == f"{namespace}:{document_ref}"`.
- For filesystem bindings, use `resource_ref == document_ref == str(Path(file_path).resolve())`.
- Add a `resource_bindings` table in `backend/src/dotmd/storage/metadata.py`:
  - `namespace TEXT NOT NULL`
  - `resource_ref TEXT NOT NULL`
  - `document_ref TEXT NOT NULL`
  - `ref TEXT NOT NULL`
  - `active INTEGER NOT NULL DEFAULT 1`
  - `bound_at TEXT NOT NULL`
  - `unbound_at TEXT`
  - `content_fingerprint TEXT NOT NULL DEFAULT ''`
  - `metadata_fingerprint TEXT NOT NULL DEFAULT ''`
  - `source_unit_refs TEXT NOT NULL DEFAULT '[]'`
  - `metadata_json TEXT NOT NULL DEFAULT '{}'`
  - primary key `(namespace, resource_ref)`
  - index `idx_resource_bindings_document_active` on `(namespace, document_ref, active)`
  - index `idx_resource_bindings_fingerprints` on `(namespace, content_fingerprint, metadata_fingerprint, active)`
- Source-of-truth rule:
  - `source_documents.content_fingerprint`, `source_documents.metadata_fingerprint`, and `source_documents.metadata_json` are authoritative for active/current document metadata.
  - `resource_bindings.content_fingerprint` and `resource_bindings.metadata_fingerprint` are copied snapshots used to find retained inactive bindings for rebind.
  - `resource_bindings.metadata_json` is binding lifecycle metadata only, for example `{"deactivation_reason": "file_missing"}`, not a duplicate of source document metadata.
- Add `ensure_resource_bindings_table()`.
- Add `upsert_resource_binding(binding, *, conn)`.
- Add `get_resource_binding(namespace, resource_ref) -> ResourceBinding | None`.
- Add `is_resource_binding_active(namespace, resource_ref) -> bool`.
- Add `set_resource_binding_active(namespace, resource_ref, active: bool, *, conn, unbound_at: datetime | None = None)`.
- Add `count_resource_bindings() -> dict[str, int]` returning keys exactly `active`, `inactive`, `total`.
- Keep helper mutations caller-transaction-owned where they can be used from pipeline paths.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class ResourceBinding`.
- `backend/src/dotmd/core/models.py` contains `active: bool`.
- `backend/src/dotmd/storage/metadata.py` contains `CREATE TABLE IF NOT EXISTS resource_bindings`.
- `backend/src/dotmd/storage/metadata.py` contains `DEFAULT ''` for both fingerprint columns or an equivalent non-null placeholder strategy.
- `backend/src/dotmd/storage/metadata.py` contains `idx_resource_bindings_document_active`.
- `backend/src/dotmd/storage/metadata.py` contains `idx_resource_bindings_fingerprints`.
- `backend/src/dotmd/storage/metadata.py` contains `def ensure_resource_bindings_table`.
- `backend/src/dotmd/storage/metadata.py` contains `def upsert_resource_binding`.
- `backend/src/dotmd/storage/metadata.py` contains `def set_resource_binding_active`.
- `backend/src/dotmd/storage/metadata.py` contains `def count_resource_bindings`.
- `backend/tests/storage/test_metadata_m2m.py` contains `resource_bindings`.
- `backend/tests/storage/test_metadata_m2m.py` asserts active/inactive/total counts.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Backfill existing source documents into active bindings</title>
<name>Backfill existing source documents into active bindings</name>
<read_first>
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/core/models.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Add an idempotent backfill from existing `source_documents` rows into active
`resource_bindings`.

Concrete target state:
- Add `backfill_resource_bindings_from_source_documents(*, conn: sqlite3.Connection | None = None) -> int`.
- It must read every row from `source_documents`.
- For each row, insert one active binding with:
  - `namespace = source_documents.namespace`
  - `resource_ref = source_documents.document_ref`
  - `document_ref = source_documents.document_ref`
  - `ref = source_documents.ref`
  - `active = 1`
  - `bound_at = source_documents.updated_at` if present, otherwise current UTC timestamp
  - `unbound_at = NULL`
  - `content_fingerprint = source_documents.content_fingerprint`
  - `metadata_fingerprint = source_documents.metadata_fingerprint`
  - `source_unit_refs = '[]'`
  - `metadata_json = '{}'`
- Use `INSERT ... ON CONFLICT(namespace, resource_ref) DO NOTHING` so inactive or already-updated binding rows are not overwritten.
- Call the backfill from the same metadata readiness path that ensures source provenance tables for service/pipeline startup. If there is no single readiness method, call it immediately after `ensure_resource_bindings_table()` in `SQLiteMetadataStore.__init__`.
- The backfill must run without reading source files, embedding text, rebuilding FTS, rebuilding vectors, or touching graph storage.
</action>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `def backfill_resource_bindings_from_source_documents`.
- `backend/src/dotmd/storage/metadata.py` contains `FROM source_documents`.
- `backend/src/dotmd/storage/metadata.py` contains `ON CONFLICT(namespace, resource_ref) DO NOTHING` or equivalent non-overwrite upsert.
- `backend/tests/storage/test_metadata_m2m.py` inserts a `SourceDocument` before any explicit binding upsert and asserts the backfill creates an active binding.
- `backend/tests/storage/test_metadata_m2m.py` asserts backfill returns `0` on a second run or otherwise proves idempotence.
- `backend/tests/storage/test_metadata_m2m.py` asserts an inactive binding is not overwritten active by the backfill.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="tdd">
<title>Add active provenance query helpers without deleting retained rows</title>
<name>Add active provenance query helpers without deleting retained rows</name>
<read_first>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
- `backend/src/dotmd/search/fusion.py`
</read_first>
<files>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<action>
Add storage helpers that let service/search distinguish active provenance from
retained inactive provenance.

Concrete target state:
- Add `get_active_chunk_provenance_for_chunk_ids(strategy: str, chunk_ids: Sequence[str]) -> dict[str, ChunkProvenance]`.
- The helper reads `chunk_source_provenance_<strategy>` and joins/checks `resource_bindings` on:
  - same `namespace`
  - `resource_bindings.document_ref == chunk_source_provenance.document_ref`
  - `active = 1`
- Preserve deterministic canonical selection from Phase 26:
  `ORDER BY chunk_id, namespace, document_ref`, first row wins.
- Add `get_inactive_chunk_count_for_document(strategy, namespace, document_ref) -> int` or equivalent diagnostic helper if needed by pipeline/service tests.
- Add an EXPLAIN-oriented test or assertion that the active helper uses the `(namespace, document_ref, active)` index path. The assertion can be a focused SQLite `EXPLAIN QUERY PLAN` substring check for `idx_resource_bindings_document_active`.
- Do not delete, update, or rebuild `chunk_source_provenance_<strategy>`, `source_documents`, `chunks_*`, `chunks_fts_*`, `vec_meta_*`, or graph data in these helpers.
- Add storage tests with:
  - one active and one inactive filesystem binding for different chunks;
  - one shared chunk with an active binding and an inactive binding, where the active provenance wins;
  - normal provenance helper returns inactive retained provenance;
  - active provenance helper returns only active public provenance;
  - retained chunk/source/provenance rows remain present.
</action>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `def get_active_chunk_provenance_for_chunk_ids`.
- `backend/src/dotmd/storage/metadata.py` contains `active = 1` or equivalent active filter in the helper SQL.
- `backend/src/dotmd/storage/metadata.py` contains `ORDER BY chunk_id, namespace, document_ref` in the active helper or shared query path.
- `backend/tests/storage/test_metadata_m2m.py` asserts `get_chunk_provenance_for_chunk_ids` returns inactive retained provenance.
- `backend/tests/storage/test_metadata_m2m.py` asserts `get_active_chunk_provenance_for_chunk_ids` excludes inactive provenance.
- `backend/tests/storage/test_metadata_m2m.py` asserts shared active/inactive M2M provenance resolves to the active ref.
- `backend/tests/storage/test_metadata_m2m.py` contains `EXPLAIN QUERY PLAN` and `idx_resource_bindings_document_active`.
- `backend/tests/storage/test_metadata_m2m.py` asserts retained rows still exist after deactivation.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q
```
</verification>

<success_criteria>
- Existing `source_documents` are backfilled into active `resource_bindings` without full reindex.
- Resource binding state exists independently of retained artifact rows.
- Fingerprint producer and source-of-truth rules are explicit and tested.
- Storage helpers can answer active-only provenance queries.
- Deactivation can be represented without hard deletion.
</success_criteria>
