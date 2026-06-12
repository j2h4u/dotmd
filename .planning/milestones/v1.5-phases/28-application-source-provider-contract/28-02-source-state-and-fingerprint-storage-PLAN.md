---
phase: "28"
plan: "02"
type: tdd
wave: 2
depends_on:
  - "28-01"
files_modified:
  - backend/src/dotmd/storage/metadata.py
  - backend/tests/storage/test_metadata_m2m.py
autonomous: true
requirements: ["R3", "R8"]
requirements_addressed: ["R3", "R8"]
must_haves:
  truths:
    - "D-07: dotMD saves checkpoint_cursor only after corresponding local persistence/indexing succeeds."
    - "D-08: next_cursor alone is not durable progress because saving it early can lose data after a crash."
    - "D-09: Reprocessing the same active unit fingerprint is idempotent and skips redundant work."
    - "D-14: Source-unit storage keys include namespace, document_ref, unit_ref, fingerprint, updated_at, and metadata_json linkage through models."
    - "D-15: deleted/hidden/tombstone state is not promoted to common storage in Phase 28."
    - "D-22/D-23: graphify is advisory only; storage helper plans are verified against live metadata.py."
    - "Full-reindex answer: this plan adds additive SQLite tables only; no dotmd index --force, TEI re-embedding, FTS rebuild, vector rebuild, or graph rebuild."
---

# Phase 28 Plan 02: Source State and Fingerprint Storage

<objective>
Add the thin durable source-state layer needed by provider-fed application
sources: checkpoint cursor storage and source-unit fingerprint tracking.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| A crash after cursor save but before persistence loses source units | HIGH | Helper names and tests require committing `checkpoint_cursor`, not `next_cursor`, after persistence. |
| Duplicate active records cause recomputation | HIGH | Store source-unit fingerprints and test unchanged units are recognized. |
| Storage helpers leak an API shape that conflicts with `metadata.py` conventions | HIGH | Verify existing transaction conventions before adding helpers: transactional writes require caller-owned `conn`, reads use `self._conn` or optional `conn`, and standalone diagnostics may auto-commit when no transaction is supplied. |
| Lifecycle/delete semantics leak into Phase 28 | MEDIUM | Storage state tracks active fingerprints/checkpoints only; tombstone lifecycle remains metadata_json/deferred. |
| Schema addition forces rebuild | HIGH | Use additive `CREATE TABLE IF NOT EXISTS`; no chunk/vector/FTS/graph rewrite. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Add source checkpoint table and helpers</title>
<name>Add source checkpoint table and helpers</name>
<read_first>
- `.planning/phases/28-application-source-provider-contract/28-CONTEXT.md`
- `.planning/phases/28-application-source-provider-contract/28-RESEARCH.md`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<behavior>
- New stores create source checkpoint tables idempotently.
- Saving a checkpoint writes a `checkpoint_cursor` value, not a speculative `next_cursor`.
- `commit_source_checkpoint` runs inside a caller-owned SQLite transaction and does not call `commit()`, matching `upsert_source_document`, `upsert_resource_binding`, and `set_resource_binding_active`.
- `record_source_checkpoint_error` can be called from an exception handler without forcing the caller to open a new transaction solely for diagnostics.
</behavior>
<action>
Add source checkpoint persistence to `SQLiteMetadataStore`.

Concrete target state:
- First verify the live `metadata.py` transaction convention by reading:
  - `upsert_source_document(document, *, conn: _SQLiteConn) -> None`
  - `upsert_resource_binding(binding, *, conn: _SQLiteConn) -> None`
  - `set_resource_binding_active(..., *, conn: _SQLiteConn, ...) -> None`
  - `delete_m2m_for_file(..., *, conn: _SQLiteConn) -> list[str]`
  - `backfill_resource_bindings_from_source_documents(*, conn: _SQLiteConn | None = None) -> int`
- Apply the same convention explicitly:
  - helpers that must be atomic with source-document, fingerprint, binding/provenance, and indexing persistence require `conn: _SQLiteConn` and never call `commit()`;
  - read helpers use `self._conn` by default and may accept optional `conn` only when a read must see uncommitted writes;
  - diagnostic helpers that are useful after a failed transaction may accept optional `conn` and commit only when `conn is None`.
- Add `source_checkpoints` table:
  - `namespace TEXT PRIMARY KEY`
  - `checkpoint_cursor TEXT`
  - `last_success_at TEXT`
  - `last_error TEXT`
  - `metadata_json TEXT NOT NULL DEFAULT '{}'`
- Add `ensure_source_checkpoint_tables()` or `ensure_source_state_tables()` and call it from `SQLiteMetadataStore.__init__`.
- Add `commit_source_checkpoint(namespace: str, checkpoint_cursor: str | None, *, conn: _SQLiteConn, metadata_json: dict | None = None) -> None`.
- Add `get_source_checkpoint(namespace: str) -> dict[str, object] | None`.
- Add `record_source_checkpoint_error(namespace: str, error: str, *, conn: _SQLiteConn | None = None) -> None`.
  - When `conn` is supplied, use it and do not commit.
  - When `conn` is omitted, use `self._conn` and commit so an exception handler can persist the error after rolling back the failed processing transaction.
- Do not add a durable helper named `save_next_cursor`; if a pending cursor appears in code, it must be non-durable or test-only.
- Tests must prove rollback behavior: call `commit_source_checkpoint()` inside a transaction, roll back, and assert the checkpoint row is absent or unchanged.
- Tests must prove `record_source_checkpoint_error(namespace, "boom")` without `conn` persists `last_error` without requiring callers to manually open a transaction.
</action>
<verify>
<automated>rg -n "def (upsert_source_document|upsert_resource_binding|set_resource_binding_active|delete_m2m_for_file|backfill_resource_bindings_from_source_documents|commit_source_checkpoint|record_source_checkpoint_error)" backend/src/dotmd/storage/metadata.py</automated>
<automated>cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `CREATE TABLE IF NOT EXISTS source_checkpoints`.
- `backend/src/dotmd/storage/metadata.py` contains `def commit_source_checkpoint`.
- `backend/src/dotmd/storage/metadata.py` contains `def get_source_checkpoint`.
- `backend/src/dotmd/storage/metadata.py` contains `def record_source_checkpoint_error`.
- `backend/src/dotmd/storage/metadata.py` contains `conn: _SQLiteConn | None = None` in `record_source_checkpoint_error`.
- `backend/tests/storage/test_metadata_m2m.py` contains `checkpoint_cursor`.
- `backend/tests/storage/test_metadata_m2m.py` contains a rollback assertion for checkpoint persistence.
- `backend/tests/storage/test_metadata_m2m.py` proves `record_source_checkpoint_error` works without passing `conn`.
- `backend/src/dotmd/storage/metadata.py` does not contain `def save_next_cursor`.
- `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Add source-unit fingerprint helpers</title>
<name>Add source-unit fingerprint helpers</name>
<read_first>
- `backend/src/dotmd/core/models.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</read_first>
<files>
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/storage/test_metadata_m2m.py`
</files>
<behavior>
- A source unit fingerprint can be upserted by `(namespace, document_ref, unit_ref)`.
- Seeing the same fingerprint again is classified as unchanged.
- A changed fingerprint is classified as changed and updates indexed metadata.
- The fingerprint write helper follows the same caller-owned transaction convention as existing metadata write helpers.
</behavior>
<action>
Add source-unit fingerprint persistence.

Concrete target state:
- Add `source_unit_fingerprints` table:
  - `namespace TEXT NOT NULL`
  - `document_ref TEXT NOT NULL`
  - `unit_ref TEXT NOT NULL`
  - `fingerprint TEXT NOT NULL`
  - `updated_at TEXT NOT NULL`
  - `indexed_at TEXT NOT NULL`
  - `metadata_json TEXT NOT NULL DEFAULT '{}'`
  - primary key `(namespace, document_ref, unit_ref)`
  - index `idx_source_unit_fingerprints_document` on `(namespace, document_ref)`
- Add `upsert_source_unit_fingerprint(unit: SourceUnit, *, conn: _SQLiteConn, indexed_at: datetime | None = None) -> bool`.
  - Return `True` when the unit is new or the fingerprint changed.
  - Return `False` when the existing fingerprint is identical.
  - Use `conn.execute(...)` and do not call `commit()` inside this helper.
- Add `get_source_unit_fingerprint(namespace, document_ref, unit_ref) -> dict[str, object] | None`.
  - Read from `self._conn` by default; accept optional `conn: _SQLiteConn | None = None` only if needed for tests to read uncommitted writes.
  - Parse `metadata_json` with `json.loads` and serialize with `json.dumps(..., sort_keys=True)`.
- Tests must cover:
  - first insert returns `True`;
  - identical repeat returns `False`;
  - changed fingerprint returns `True`;
  - metadata JSON round-trips as a dict;
  - `updated_at` and `indexed_at` are stored as ISO 8601 text and hydrated back as parseable timestamp strings or datetimes, matching existing metadata-store timestamp style;
  - no lifecycle status columns such as `deleted_at` are added in Phase 28.
</action>
<verify>
<automated>cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q</automated>
</verify>
<acceptance_criteria>
- `backend/src/dotmd/storage/metadata.py` contains `CREATE TABLE IF NOT EXISTS source_unit_fingerprints`.
- `backend/src/dotmd/storage/metadata.py` contains `idx_source_unit_fingerprints_document`.
- `backend/src/dotmd/storage/metadata.py` contains `def upsert_source_unit_fingerprint`.
- `backend/src/dotmd/storage/metadata.py` contains `def get_source_unit_fingerprint`.
- `backend/tests/storage/test_metadata_m2m.py` asserts identical fingerprint repeat returns `False`.
- `backend/tests/storage/test_metadata_m2m.py` asserts changed fingerprint returns `True`.
- `backend/src/dotmd/storage/metadata.py` does not contain `deleted_at` in the `source_unit_fingerprints` table definition.
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
- Provider checkpoint state is durable only at the safe checkpoint boundary.
- Source-unit fingerprints make repeat active records idempotent.
- Storage additions are additive and do not require a full reindex or rebuild.
</success_criteria>

## PLANNING COMPLETE
