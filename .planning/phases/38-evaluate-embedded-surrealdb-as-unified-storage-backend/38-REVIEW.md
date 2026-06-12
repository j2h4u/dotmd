---
phase: 38-evaluate-embedded-surrealdb-as-unified-storage-backend
reviewed: 2026-06-12T16:44:59Z
depth: deep
files_reviewed: 9
files_reviewed_list:
  - backend/src/dotmd/storage/surreal_inventory.py
  - backend/src/dotmd/storage/surreal_ops.py
  - backend/src/dotmd/storage/surreal.py
  - backend/src/dotmd/ingestion/migrate_surreal.py
  - backend/src/dotmd/search/surreal_parity.py
  - backend/tests/storage/test_surreal_storage_contract.py
  - backend/tests/storage/test_surreal_ops_safety.py
  - backend/tests/ingestion/test_surreal_transform_only_migration.py
  - backend/tests/search/test_surreal_retrieval_parity.py
findings:
  critical: 0
  warning: 0
  info: 0
  total: 0
status: clean
previous_status: issues_found
resolved_findings:
  critical: 4
  warning: 3
---
# Phase 38: Code Review Report

**Reviewed:** 2026-06-12T16:44:59Z
**Depth:** deep
**Files Reviewed:** 9
**Status:** issues_found

**Resolution:** clean after follow-up fixes. The original findings are retained
below for auditability; each is closed in the resolution section.

## Resolution

| Finding | Status | Fix |
|---|---|---|
| CR-01 composite source keys collapse | resolved | Surreal import/storage now uses composite record IDs for source units, provenance, bindings, and cursors. |
| CR-02 Phase 16 chunk/file ordering dropped | resolved | Import now persists `chunk_file_bindings` with `(chunk_id, file_path, chunk_index)` and file lookup reads that table. |
| CR-03 backup/rollback gates tautological | resolved | Fallback restore now requires restored count manifest evidence and current-stack rollback smoke opens restored SQLite plus parses Falkor JSON. |
| CR-04 feedback truncation at 1000 rows | resolved | Feedback inventory/import now requests `1001` rows and fails closed if the provider reaches the limit. |
| WR-01 graph entity typing overwritten | resolved | Relation import no longer overwrites existing imported entity records with generic placeholders. |
| WR-02 graph parity ignores top_k | resolved | Graph-direct parity trims normalized baseline/candidate rows to `case.top_k`; regression test added. |
| WR-03 hardcoded strategy/model evidence | mitigated | This remains a documented Phase 38 spike limit and does not affect the final `reject` recommendation; future migrate work must discover strategy/model families dynamically. |

## Summary

Reviewed the Phase 38 Surreal prototype source/test files plus the minimum protocol/model cross-references needed to verify behavior. The prototype-only boundary appears intact, but the spike evidence is not trustworthy yet: the import path silently collapses composite source keys, the Phase 16 chunk/file M2M surface is flattened away, and the backup/rollback gates can report success without validating a restored store.

## Narrative Findings (AI reviewer)

## Critical Issues

### CR-01 BLOCKER: Transform import collapses composite source keys and will overwrite rows

**File:** `backend/src/dotmd/ingestion/migrate_surreal.py:208-217`, `backend/src/dotmd/ingestion/migrate_surreal.py:300-309`, `backend/src/dotmd/storage/surreal.py:303-356`
**Issue:** Several imported record ids drop parts of the real source primary key. `source_unit_fingerprints` is keyed by `(namespace, document_ref, unit_ref)` in SQLite, but `replace_source_units()` stores only `unit_ref`. `resource_bindings` is keyed by `(namespace, resource_ref)`, but `replace_binding_rows()` stores only `resource_ref`. Cursor audit rows are described as resource-ref keyed, but `replace_cursor_rows()` keys them by `original_ref`, so multiple resources bound to the same document collapse into one row. `provenance_id` is built as `chunk_id::document_ref`, which also drops `namespace`. In any multi-namespace or multi-resource corpus, later upserts overwrite earlier rows while `counts.total_records()` still claims full coverage.
**Fix:**
```python
def _composite_id(*parts: str) -> str:
    return "::".join(parts)

self._connection.upsert(
    self._codec.encode(
        "source_units",
        _composite_id(row["namespace"], row["document_ref"], row["unit_ref"]),
    ),
    dict(row),
)
```
Apply the same pattern to bindings, cursors, and provenance using the full source key, then add regression tests with duplicate `resource_ref`/`unit_ref` values across namespaces.

### CR-02 BLOCKER: The importer drops Phase 16 chunk/file ordering data

**File:** `backend/src/dotmd/ingestion/migrate_surreal.py:148-150`, `backend/src/dotmd/ingestion/migrate_surreal.py:201-237`, `backend/src/dotmd/storage/surreal.py:188-207`, `backend/src/dotmd/storage/surreal.py:226-231`, `backend/src/dotmd/storage/surreal.py:277-282`
**Issue:** The loader reads `chunk_file_paths_contextual_512_50`, but only keeps `file_path` strings per chunk; `chunk_index` is discarded before import. The Surreal metadata adapter then stores one `chunk_index` field on the chunk row and reconstructs file membership by scanning the flattened `file_paths` list. That cannot represent the real `(chunk_id, file_path, chunk_index)` M2M surface, and it loses per-file order whenever a content-addressed chunk is shared by multiple files.
**Fix:**
```python
binding_rows.append(
    {
        "chunk_id": chunk_id,
        "file_path": str(row["file_path"]),
        "chunk_index": int(row["chunk_index"]),
    }
)
```
Persist file bindings in a dedicated Surreal table keyed by `(chunk_id, file_path, chunk_index)`, and drive `get_chunk_ids_by_file()` from that binding surface instead of the flattened chunk row.

### CR-03 BLOCKER: Backup/restore and rollback gates can pass without checking restored data

**File:** `backend/src/dotmd/storage/surreal_ops.py:478-500`, `backend/src/dotmd/storage/surreal_ops.py:541-552`
**Issue:** `rehearse_surreal_backup_restore()` never inspects the restored Surreal store; it sets `restored_counts = expected_counts`, so `verify_surreal_restore_counts()` is a tautology. `rehearse_current_stack_rollback()` marks the smoke step as passed whenever `smoke_queries` is non-empty and the copied bytes match. Both gates can therefore report success for an unreadable or logically incomplete restore, which makes the operations evidence unusable for a migration decision.
**Fix:**
```python
with SurrealConnection(SurrealStoreConfig(url=f"surrealkv://{restored_path}")) as conn:
    restored_counts = collect_surreal_counts(conn)

smoke_passed = run_restore_smoke_queries(restored_sqlite, restored_falkor, smoke_queries)
```
Derive counts from the restored store, and run real read queries against the restored SQLite/Falkor artifacts before setting `verified` or `current_stack_smoke_passed`.

### CR-04 BLOCKER: Feedback coverage is silently truncated at 1000 rows

**File:** `backend/src/dotmd/storage/surreal_inventory.py:357-376`, `backend/src/dotmd/ingestion/migrate_surreal.py:341-356`
**Issue:** Both inventory collection and import call `provider.list_all(limit=1000, include_closed=True)` exactly once. If `feedback.db` contains more than 1000 rows, the spike undercounts inventory and drops older feedback on import with no error or warning. Because direct `feedback.db` SQL is explicitly forbidden, the provider surface must support exhaustive iteration before this can be treated as a transform-only proof.
**Fix:**
```python
rows: list[dict[str, Any]] = []
cursor: int | None = None
while True:
    page, cursor = provider.list_page(limit=500, include_closed=True, cursor=cursor)
    rows.extend(page)
    if cursor is None:
        break
```
Add a paginated or iterator-style provider API and fail the spike if exhaustive export is unavailable.

## Warnings

### WR-01 WARNING: Graph import overwrites entity typing and loses file context

**File:** `backend/src/dotmd/storage/surreal.py:681-726`
**Issue:** `replace_entity_rows()` imports the exporter’s real `entity_type`, but `replace_relation_rows()` rewrites every non-tag target through `add_entity_node(target_id, "Entity", ...)`, which overwrites the imported type/source on upsert. The same path also synthesizes section nodes with `file_path=""`, so file-scoped helpers such as `get_entities_by_file()` cannot behave correctly on imported data.
**Fix:** Only create placeholder entities when the target record does not already exist, preserve the imported `entity_type`/`source`, and import section/file context explicitly instead of synthesizing empty `file_path` values.

### WR-02 WARNING: Graph-direct parity ignores the requested top-K

**File:** `backend/src/dotmd/search/surreal_parity.py:301-328`
**Issue:** `compare_graph_direct_results()` compares the full normalized relation lists, while the FTS/vector/hybrid comparators all trim to `case.top_k`. Extra low-rank related sections can therefore fail graph parity even when the requested top-K matches, which makes the retrieval recommendation noisier than intended.
**Fix:**
```python
baseline_rows = _normalize_graph_related_sections(current_results)[: case.top_k]
candidate_rows = _normalize_surreal_relation_rows(... )[: case.top_k]
```
Trim before computing overlap and equality so graph parity uses the same contract as the other comparators.

### WR-03 WARNING: The Phase 38 evidence is hardcoded to one strategy/model pair

**File:** `backend/src/dotmd/ingestion/migrate_surreal.py:138-199`, `backend/src/dotmd/storage/surreal_inventory.py:237-300`
**Issue:** The importer only reads `contextual_512_50` / `multilingual_e5_large` table families, and the inventory mapper does not classify tables such as `meta_fingerprints_*` or `vec_chunks_*` as first-class mapped surfaces. dotMD’s storage architecture explicitly supports multiple chunk strategies and embedding models simultaneously, so the Phase 38 evidence becomes incomplete as soon as more than the single hardcoded pair exists in `index.db`.
**Fix:** Discover strategy/model table families from SQLite metadata and iterate them dynamically, or fail closed when the snapshot contains more than the single supported pair.

---

_Reviewed: 2026-06-12T16:44:59Z_
_Reviewer: the agent (gsd-code-reviewer)_
_Depth: deep_
