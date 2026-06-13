# Phase 41: Production-grade Surreal schema and import - Pattern Map

**Mapped:** 2026-06-13
**Files analyzed:** 8
**Analogs found:** 8 / 8

## File Classification

| New/Modified File | Role | Data Flow | Closest Analog | Match Quality |
|---|---|---|---|---|
| `backend/src/dotmd/storage/surreal_schema.py` | config | transform | `backend/src/dotmd/storage/surreal.py` | role-match |
| `backend/src/dotmd/ingestion/migrate_surreal.py` | service | batch | `backend/src/dotmd/ingestion/migrate_surreal.py` | exact |
| `backend/src/dotmd/storage/surreal_inventory.py` | utility | file-I/O | `backend/src/dotmd/storage/surreal_inventory.py` | exact |
| `backend/src/dotmd/storage/surreal_ops.py` | utility | batch | `backend/src/dotmd/storage/surreal_ops.py` | exact |
| `backend/src/dotmd/search/surreal_parity.py` | utility | transform | `backend/src/dotmd/search/surreal_parity.py` | exact |
| `backend/tests/storage/test_surreal_storage_contract.py` | test | file-I/O | `backend/tests/storage/test_surreal_storage_contract.py` | exact |
| `backend/tests/storage/test_surreal_ops_safety.py` | test | batch | `backend/tests/storage/test_surreal_ops_safety.py` | exact |
| `backend/tests/ingestion/test_surreal_transform_only_migration.py` | test | batch | `backend/tests/ingestion/test_surreal_transform_only_migration.py` | exact |

## Read First

- `backend/src/dotmd/ingestion/migrate_surreal.py:416-492` for the current `dry-run -> gate -> apply -> rollback -> committed` runner shape.
- `backend/src/dotmd/storage/surreal_inventory.py:172-229` and `:389-449` for manifest-heavy snapshot and migration-map dataclasses/helpers.
- `backend/src/dotmd/storage/surreal_ops.py:57-158` and `:461-523` for report dataclasses plus backup/restore validation shape.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py:452-709` for the non-recompute and rollback contract the production runner should preserve while getting stricter.

## Pattern Assignments

### `backend/src/dotmd/storage/surreal_schema.py` (config, transform)

**Analog:** `backend/src/dotmd/storage/surreal.py`

**Start here:** `backend/src/dotmd/storage/surreal.py:29-47`, `:73-95`, `:170-183`

**Copy these patterns**

- Schema catalog starts as one owned mapping, not scattered literals:
```python
_SCHEMA_TABLES = {
    "documents": "document envelopes from source_documents",
    "source_units": "source-unit rows derived from source_unit_fingerprints",
    ...
    "checkpoints": "source checkpoint rows",
}
```

- Keep record-id escaping centralized and reusable:
```python
class SurrealRecordIdCodec:
    def encode(self, table_name: str, raw_identifier: str) -> RecordID:
        if not table_name:
            raise ValueError("table_name must not be empty")
        return RecordID(table_name, _urlsafe_encode(raw_identifier))
```

- Current schema definition API already returns machine-readable metadata:
```python
def define_dotmd_surreal_schema(connection: SurrealConnection | None = None) -> dict[str, Any]:
    statements = [f"DEFINE TABLE {table_name} SCHEMALESS;" for table_name in _SCHEMA_TABLES]
    ...
    return {
        "tables": list(_SCHEMA_TABLES),
        "table_notes": dict(_SCHEMA_TABLES),
        "statements": statements,
    }
```

**Planner note:** replace the prototype `SCHEMALESS` statements with a versioned DDL catalog, but preserve the single-catalog + returned-plan shape.

---

### `backend/src/dotmd/ingestion/migrate_surreal.py` (service, batch)

**Analog:** `backend/src/dotmd/ingestion/migrate_surreal.py`

**Start here:** `backend/src/dotmd/ingestion/migrate_surreal.py:38-81`, `:135-340`, `:416-492`

**Imports pattern**
```python
from dotmd.storage.surreal import (
    SurrealConnection,
    SurrealFeedbackStore,
    SurrealGraphStore,
    SurrealMetadataStore,
    SurrealStoreConfig,
    SurrealVectorStore,
    define_dotmd_surreal_schema,
)
from dotmd.storage.surreal_ops import (
    SurrealEmbeddedSafetyReport,
    assert_embedded_safety_gate_passed,
)
```

**Manifest/report dataclass pattern**
```python
@dataclass(slots=True)
class SurrealImportReport:
    mode: SurrealImportMode
    counts: SurrealImportCounts
    status: str
    target_url: str | None
    committed: bool = False
    rolled_back: bool = False
    applied_records: int = 0
    gate_status: str = "not_required"
    unsupported_categories: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
```

**Source-preserving loader pattern**
```python
def load_sqlite_rows_for_surreal(sqlite_snapshot_path: Path) -> dict[str, Any]:
    with _sqlite_connect_read_only(source_path) as conn:
        known_tables = _discover_tables(conn)
        ...
    return {
        "documents": source_document_rows,
        "source_units": source_unit_rows,
        "chunks": chunk_payloads,
        ...
        "unsupported_categories": unsupported_categories,
    }
```

**Safe source access pattern**
```python
def _validate_table_name(table_name: str, known_tables: set[str]) -> str:
    if not _SAFE_TABLE_NAME.match(table_name):
        raise ValueError(f"unsafe table name: {table_name!r}")
    if table_name not in known_tables:
        raise ValueError(f"unknown table name: {table_name!r}")
    return table_name
```

**Runner pattern**
```python
if mode is SurrealImportMode.DRY_RUN:
    report.status = "dry-run"
    return report

...
with SurrealConnection(config) as connection:
    define_dotmd_surreal_schema(connection)
    connection.clear_phase38_tables()
    ...
    try:
        metadata_store.replace_documents(sqlite_rows["documents"])
        ...
        feedback_store.replace_feedback_rows(feedback_rows)
    except (KeyError, RuntimeError, TypeError, ValueError) as exc:
        connection.clear_phase38_tables()
        report.status = "rolled_back"
        report.rolled_back = True
        report.errors.append(str(exc))
        return report
```

**Planner note:** keep the staged report-first runner shape, but remove `clear_phase38_tables()` as the default production contract and replace it with explicit phase plans/checkpoints.

---

### `backend/src/dotmd/storage/surreal_inventory.py` (utility, file-I/O)

**Analog:** `backend/src/dotmd/storage/surreal_inventory.py`

**Start here:** `backend/src/dotmd/storage/surreal_inventory.py:46-98`, `:172-229`, `:232-319`, `:389-449`

**Snapshot manifest pattern**
```python
@dataclass(frozen=True)
class SQLiteSnapshotInventory:
    source_path: Path
    snapshot_path: Path
    snapshot_created_at: str
    wal_mode: str
    manifest: dict[str, Any]
    table_counts: dict[str, int] = field(default_factory=dict)
    unmapped_tables: list[str] = field(default_factory=list)
    sha256: str | None = None
```

**Copy-safe snapshot pattern**
```python
with (
    _sqlite_connect_read_only(source_path) as source_conn,
    sqlite3.connect(snapshot_path) as snapshot_conn,
):
    source_conn.backup(snapshot_conn)
    snapshot_conn.commit()
```

**Inventory counting pattern**
```python
table_counts = {
    "chunks": _sum_matching_tables(...),
    "fts_rows": sum(...),
    "vectors": _sum_matching_tables(...),
    ...
}
```

**Disposition map pattern**
```python
if expected_fields is None:
    dispositions[category_name] = MigrationCategoryDisposition(
        disposition="unsupported",
        ...
        cpu_recomputation_required=True,
    )
elif missing_fields:
    dispositions[category_name] = MigrationCategoryDisposition(
        disposition="unsafe",
        ...
    )
else:
    dispositions[category_name] = MigrationCategoryDisposition(
        disposition="transformable",
        ...
    )
```

**Planner note:** production manifests/reports should extend this typed-inventory style rather than inventing free-form JSON blobs.

---

### `backend/src/dotmd/storage/surreal_ops.py` (utility, batch)

**Analog:** `backend/src/dotmd/storage/surreal_ops.py`

**Start here:** `backend/src/dotmd/storage/surreal_ops.py:57-158`, `:160-214`, `:393-449`, `:461-523`, `:526-680`, `:683-760`

**Report dataclass pattern**
```python
@dataclass(slots=True)
class SurrealBackupReport:
    source_path: str
    backup_path: str
    method: str
    cli_available: bool
    cli_version: str | None
    restore: SurrealRestoreReport
    verified: bool
    notes: list[str] = field(default_factory=list)
```

**Safety helper pattern**
```python
class SurrealWriterGuard:
    def acquire(self) -> dict[str, str]:
        ...
        with self.guard_path.open("x", encoding="utf-8") as handle:
            json.dump(metadata, handle, sort_keys=True)
```

**Rollback helper pattern**
```python
def force_release_surreal_writer_guard(...):
    if current.get("target_path") != expected:
        raise ValueError("target path mismatch for force-release")
    guard_path.unlink(missing_ok=True)
```

**Backup/restore verification pattern**
```python
shutil.copy2(source, backup_path)
shutil.copy2(backup_path, restored_path)
restored_counts = _read_surreal_counts_manifest(source)
restore_verified = restored_path.read_bytes() == source.read_bytes()
counts_verified = verify_surreal_restore_counts(expected_counts, restored_counts)
```

**Decision runner pattern**
```python
gate_checks: list[tuple[bool, SurrealDecisionCategory, str, bool]] = [
    (inputs.transform_coverage_passed, SurrealDecisionCategory.TRANSFORM_COVERAGE, ..., False),
    (inputs.embedded_safety_passed, SurrealDecisionCategory.EMBEDDED_ATOMICITY, ..., True),
    ...
]
```

**Planner note:** Phase 41 backup/rollback semantics should extend this explicit typed-report + verified fallback pattern, not a best-effort cleanup step.

---

### `backend/src/dotmd/search/surreal_parity.py` (utility, transform)

**Analog:** `backend/src/dotmd/search/surreal_parity.py`

**Start here:** `backend/src/dotmd/search/surreal_parity.py:24-92`, `:158-225`, `:302-356`, `:374-417`, `:435-546`

**Why this matters for Phase 41:** not because Phase 41 owns retrieval, but because this file shows the repo’s preferred pattern for machine-readable comparison results, failure categories, and pass/fail aggregation. Reuse that style for import verify/report outputs.

**Comparator/report pattern**
```python
@dataclass(slots=True, frozen=True)
class RetrievalParityResult:
    case: RetrievalParityCase
    passed: bool
    top_result_match: bool
    top_k_overlap: float
    ...
    failure_category: RetrievalFailureCategory | None = None
    stop_condition: str | None = None
```

**Harness pattern**
```python
def run(
    self,
    cases: Sequence[RetrievalParityCase],
    *,
    scale_gate: dict[str, Any] | None = None,
) -> RetrievalParityReport:
    return RetrievalParityReport(
        results=tuple(self.run_case(case) for case in cases),
        scale_gate=scale_gate,
    )
```

---

### Tests to Copy First

**Transform-first import tests**

- `backend/tests/ingestion/test_surreal_transform_only_migration.py:452-495`
  Dry-run must count transformable rows without writing.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py:495-570`
  Apply must preserve weird ids, vectors, feedback, and graph properties.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py:571-607`
  Apply requires the embedded safety gate.
- `backend/tests/ingestion/test_surreal_transform_only_migration.py:679-709`
  Import must never call embedding/extraction recomputation and must roll back on apply error.

**Storage contract tests**

- `backend/tests/storage/test_surreal_storage_contract.py:223-274`
  Snapshot helpers must use backup/copy semantics without mutating the source.
- `backend/tests/storage/test_surreal_storage_contract.py:296-315`
  Graph inventory must preserve labels, weights, keys, and value types.
- `backend/tests/storage/test_surreal_storage_contract.py:349-467`
  Migration-map, record-id codec, schema-plan, and store-surface contract tests are the best template for new schema/report tests.

**Ops/safety tests**

- `backend/tests/storage/test_surreal_ops_safety.py:34-126`
  Atomicity probe and writer guard semantics.
- `backend/tests/storage/test_surreal_ops_safety.py:173-230`
  Backup/restore validation plus recommendation gating.
- `backend/tests/storage/test_surreal_ops_safety.py:230-256`
  Rollback rehearsal against copied SQLite/Falkor originals.

**Runner/report tests**

- `backend/tests/devtools/test_surreal_eval_runner.py:61-179`
  Good analog for JSONL + markdown dual-output reporting with acceptance metadata preserved.

## Shared Patterns

### Source-preserving transforms
**Source:** `backend/src/dotmd/ingestion/migrate_surreal.py:135-376`

```python
def load_graph_rows_for_surreal(exporter: Any) -> dict[str, Any]:
    inventory = exporter.export_inventory()
    rows = exporter.export_rows()
    return {
        "inventory": inventory,
        "entities": [dict(row) for row in rows.get("entities", [])],
        "relations": [dict(row) for row in rows.get("relations", [])],
    }
```

Apply to all import phases. Read through provider/exporter abstractions, not direct live-store SQL except the copied SQLite snapshot.

### Safe table/input validation
**Source:** `backend/src/dotmd/ingestion/migrate_surreal.py:97-110`, `backend/src/dotmd/storage/surreal_inventory.py:117-147`

```python
if not _SAFE_TABLE_NAME.match(table_name):
    raise ValueError(f"unsafe table name: {table_name!r}")
if table_name not in known_tables:
    raise ValueError(f"unknown table name: {table_name!r}")
```

Apply anywhere Phase 41 accepts source table/category names.

### Typed reports over booleans
**Source:** `backend/src/dotmd/storage/surreal_ops.py:57-158`, `backend/src/dotmd/search/surreal_parity.py:24-92`

Use dataclasses carrying counts, statuses, reasons, notes, and failure categories. The repo prefers machine-readable gate outputs over naked booleans.

### Verified fallback, not silent fallback
**Source:** `backend/src/dotmd/storage/surreal_ops.py:461-523`

```python
if backup_report.cli_available and backup_report.verified:
    return restore
if not backup_report.cli_available and restore.verified and restore.smoke_passed:
    return restore
raise RuntimeError("surreal CLI unavailable and fallback restore was not validated")
```

Apply to backup/restore and any apply-time safety fallback.

## No Analog Found

| File | Role | Data Flow | Reason |
|---|---|---|---|
| `backend/src/dotmd/storage/surreal_schema.py` | config | transform | No existing dedicated schema-catalog module; split it out from `storage/surreal.py` and keep the same returned-plan shape. |

## Metadata

**Analog search scope:** `backend/src/dotmd/storage`, `backend/src/dotmd/ingestion`, `backend/src/dotmd/search`, `backend/tests`
**Files scanned:** 12
**Pattern extraction date:** 2026-06-13
