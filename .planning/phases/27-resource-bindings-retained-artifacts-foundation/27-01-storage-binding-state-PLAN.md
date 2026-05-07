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
    - "Full-reindex answer: this plan requires no dotmd index --force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild."
---

# Phase 27 Plan 01: Storage Binding State

<objective>
Add the generic storage/domain foundation for active and inactive resource
bindings while preserving existing source documents and derived artifact rows.

This is the enabling slice for R1 and R2: activity becomes a separate state
from retained content existence. It must be source-agnostic enough for
filesystem now and Telegram later, but it must not implement Telegram ingestion.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Active state is stored only in filesystem holder rows and cannot model Telegram later | HIGH | Add namespace/ref-based binding helpers independent of `chunk_file_paths_<strategy>`. |
| Unbind deletes the metadata/provenance needed for reuse | HIGH | Storage tests assert inactive binding leaves `source_documents`, `chunk_source_provenance_<strategy>`, `chunks_*`, `chunks_fts_*`, and `vec_meta_*` rows intact. |
| Public code cannot distinguish inactive retained content from active content | HIGH | Add helpers that answer active binding/provenance queries directly. |
| Schema migration forces full reindex | HIGH | Use idempotent `CREATE TABLE IF NOT EXISTS` and no rebuild of vectors/FTS/graph/chunks. |
| Binding table becomes Telegram-specific too early | MEDIUM | Keep fields generic: `namespace`, `resource_ref`, `document_ref`, `ref`, fingerprints, active state, timestamps, metadata JSON. |
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
- Add `ResourceBinding` or an equivalently named Pydantic model in
  `backend/src/dotmd/core/models.py` with at least:
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
  - `content_fingerprint TEXT NOT NULL`
  - `metadata_fingerprint TEXT NOT NULL`
  - `source_unit_refs TEXT NOT NULL DEFAULT '[]'`
  - `metadata_json TEXT NOT NULL DEFAULT '{}'`
  - primary key `(namespace, resource_ref)`
  - index on `(namespace, document_ref, active)`
- Add `ensure_resource_bindings_table()`.
- Add `upsert_resource_binding(binding, *, conn)`.
- Add `get_resource_binding(namespace, resource_ref) -> ResourceBinding | None`.
- Add `is_resource_binding_active(namespace, resource_ref) -> bool`.
- Add `set_resource_binding_active(namespace, resource_ref, active: bool, *, conn, unbound_at: datetime | None = None)`.
- Add `count_resource_bindings() -> dict[str, int]` returning keys exactly:
  `active`, `inactive`, `total`.
- Keep helper mutations caller-transaction-owned where they can be used from
  pipeline paths.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class ResourceBinding`.
- `backend/src/dotmd/core/models.py` contains `active: bool`.
- `backend/src/dotmd/storage/metadata.py` contains `CREATE TABLE IF NOT EXISTS resource_bindings`.
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
- The helper reads `chunk_source_provenance_<strategy>` and joins/checks
  `resource_bindings` on:
  - same `namespace`
  - `resource_bindings.document_ref == chunk_source_provenance.document_ref`
  - `active = 1`
- Preserve deterministic canonical selection from Phase 26:
  `ORDER BY chunk_id, namespace, document_ref`, first row wins.
- Add `get_inactive_chunk_count_for_document(strategy, namespace, document_ref) -> int`
  or equivalent diagnostic helper if needed by pipeline/service tests.
- Do not delete, update, or rebuild `chunk_source_provenance_<strategy>`,
  `source_documents`, `chunks_*`, `chunks_fts_*`, `vec_meta_*`, or graph data
  in these helpers.
- Add storage tests with one active and one inactive filesystem binding for
  different chunks:
  - normal provenance helper returns both chunks;
  - active provenance helper returns only the active chunk;
  - inactive binding row remains present;
  - retained chunk/source/provenance rows remain present.
</action>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `def get_active_chunk_provenance_for_chunk_ids`.
- `backend/src/dotmd/storage/metadata.py` contains `active = 1` or equivalent active filter in the helper SQL.
- `backend/src/dotmd/storage/metadata.py` contains `ORDER BY chunk_id, namespace, document_ref` in the active helper or shared query path.
- `backend/tests/storage/test_metadata_m2m.py` asserts `get_chunk_provenance_for_chunk_ids` returns inactive retained provenance.
- `backend/tests/storage/test_metadata_m2m.py` asserts `get_active_chunk_provenance_for_chunk_ids` excludes inactive provenance.
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
- Resource binding state exists independently of retained artifact rows.
- Storage helpers can answer active-only provenance queries.
- Deactivation can be represented without hard deletion.
- No full reindex/rebuild command is introduced or required.
</success_criteria>
