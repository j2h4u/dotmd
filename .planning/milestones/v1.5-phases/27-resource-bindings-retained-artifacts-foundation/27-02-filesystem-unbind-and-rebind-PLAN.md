---
phase: "27"
plan: "02"
type: tdd
wave: 2
depends_on:
  - "27-01"
files_modified:
  - backend/src/dotmd/storage/metadata.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/tests/ingestion/test_pipeline_purge.py
  - backend/tests/ingestion/test_pipeline_orphan_sweep.py
  - backend/tests/ingestion/test_source_filesystem.py
  - backend/tests/ingestion/test_metadata_only_reindex.py
autonomous: true
requirements: ["R1", "R2", "R8"]
requirements_addressed: ["R1", "R2", "R8"]
must_haves:
  truths:
    - "D-04: Normal unbind retains chunks, embeddings, FTS rows, graph artifacts, source/chunk provenance, and metadata needed for reuse."
    - "D-07: Reuse is content/source-unit fingerprint based."
    - "D-08: Equivalent content can rebind to retained artifacts without recomputing unchanged work."
    - "D-09: Missing filesystem paths deactivate active binding and hide the resource instead of hard purging."
    - "D-10: Filesystem missing/rebind behavior is the main Phase 27 validation slice."
    - "D-12: Graph nodes/edges are not deleted on normal unbind in Phase 27."
    - "D-13: No graph inactive-state schema is added unless proven necessary."
    - "Review feedback: every successful filesystem index upserts an active binding with current fingerprints."
    - "Review feedback: modified files keep replacement reindex semantics and update fingerprints after successful reindex; only missing/deleted paths deactivate."
    - "Review feedback: trickle index_file and restored-file paths are covered, not only batch incremental indexing."
    - "Full-reindex answer: this plan must not run dotmd index --force or rebuild unchanged TEI/FTS/vector/graph stores."
---

# Phase 27 Plan 02: Filesystem Unbind and Rebind

<objective>
Convert normal filesystem missing-path handling from hard purge to inactive
binding semantics, and prove equivalent restored content can reuse retained
derived artifacts instead of recomputing from scratch.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Active bindings are deactivated but never created during normal indexing | HIGH | Upsert a filesystem resource binding in the successful index path that persists each `SourceDocument`. |
| Existing purge path destroys reusable rows before service can hide them | HIGH | Add a separate deactivation path that never calls `_holder_aware_chunk_cleanup`. |
| `_holder_aware_chunk_cleanup` deletes provenance on normal unbind | HIGH | Keep `_holder_aware_chunk_cleanup` as hard-purge/replacement cleanup only; normal unbind uses `_deactivate_filesystem_binding`. |
| Restored unchanged files still call TEI despite retained chunk/vector rows | HIGH | Add fixture tests with TEI encode call count exactly `0` on unchanged retained-content rebind. |
| Modified files are incorrectly treated like missing files | HIGH | Preserve modified-file replacement semantics and update active binding fingerprints only after successful reindex. |
| Trickle path diverges from batch incremental path | HIGH | Cover both `purge_orphaned_files()` and `index_file()` restored/modified interactions. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<title>Upsert active filesystem bindings during successful indexing</title>
<name>Upsert active filesystem bindings during successful indexing</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-REVIEWS.md`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
</files>
<action>
Add the missing active-binding writer paired with Plan 01 storage helpers.

Concrete target state:
- In the code path that persists each filesystem `SourceDocument` and
  chunk-source provenance, upsert an active `ResourceBinding` in the same SQLite
  transaction.
- The binding fields come from the `SourceDocument` already being persisted:
  - `namespace = "filesystem"` or the document namespace;
  - `resource_ref = document_ref`;
  - `document_ref = source_document.document_ref`;
  - `ref = source_document.ref`;
  - `active = True`;
  - `bound_at = source_document.updated_at` or current UTC timestamp;
  - `unbound_at = None`;
  - `content_fingerprint = source_document.content_fingerprint`;
  - `metadata_fingerprint = source_document.metadata_fingerprint`;
  - `source_unit_refs = []` for filesystem Markdown in Phase 27;
  - `metadata_json = {}` unless binding lifecycle metadata is present.
- Normal successful indexing, metadata-only refresh, and trickle `index_file()`
  must all pass through this binding upsert, either directly or through the
  shared source-document persistence helper.
- Modified-file lifecycle rule:
  - `_incremental_index()` modified files keep the existing replacement path
    that removes stale chunks/vectors/FTS for changed content;
  - after the modified file is successfully reindexed, upsert the active
    binding with the new `content_fingerprint` and `metadata_fingerprint`;
  - do not deactivate modified files merely because content changed.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `upsert_resource_binding`.
- `backend/src/dotmd/ingestion/pipeline.py` passes `content_fingerprint` from `SourceDocument` or the equivalent source-document object into the binding upsert.
- `backend/tests/ingestion/test_source_filesystem.py` or `backend/tests/ingestion/test_metadata_only_reindex.py` asserts a newly indexed filesystem file has an active binding.
- A modified-file test asserts the active binding remains active and its fingerprints change after successful reindex.
- A metadata-only refresh test asserts binding fingerprints are updated without deactivating the binding.
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
<title>Split normal unbind from hard purge</title>
<name>Split normal unbind from hard purge</name>
<read_first>
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-CONTEXT.md`
- `.planning/phases/27-resource-bindings-retained-artifacts-foundation/27-RESEARCH.md`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/ingestion/test_pipeline_orphan_sweep.py`
</files>
<action>
Add a normal filesystem unbind path and route missing-path handling through it.

Concrete target state:
- Add `_deactivate_filesystem_binding(file_path: str, *, reason: str = "file_missing") -> None`.
- It must:
  - derive `document_ref = self._meta_entity_id(file_path)`;
  - ensure a binding exists by using the current `SourceDocument` row when available, then set it inactive;
  - set binding lifecycle metadata such as `{"deactivation_reason": reason}`;
  - preserve `source_documents`;
  - preserve `chunk_source_provenance_<strategy>`;
  - preserve `chunk_file_paths_<strategy>` rows in Phase 27;
  - preserve `chunks_*`, `chunks_fts_*`, `vec_meta_*`, and graph artifacts;
  - not call `_holder_aware_chunk_cleanup`;
  - not call `delete_chunk_provenance_for_document`;
  - not call `delete_chunks_from_graph`, `delete_file_node`, or `delete_file_subgraph`.
- Keep `_purge_file()` as explicit hard purge/replacement cleanup only. Add docstring language:
  `Hard purge is not normal missing-resource handling; Phase 27 normal unbind uses _deactivate_filesystem_binding`.
- Change `_incremental_index()` so `diff.deleted` uses `_deactivate_filesystem_binding(path_str)`, not `_purge_file(path_str)`.
- Leave `_incremental_index()` `diff.modified` on the hard replacement path, with tests proving it does not route through `_deactivate_filesystem_binding`.
- Change `purge_orphaned_files(discovered_paths=...)` so missing paths use `_deactivate_filesystem_binding(file_path)`, not `_purge_file(file_path)`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `_deactivate_filesystem_binding`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `Hard purge is not normal missing-resource handling` or equivalent docstring wording.
- `_deactivate_filesystem_binding` does not contain `_holder_aware_chunk_cleanup`.
- `_incremental_index` deleted-file branch calls `_deactivate_filesystem_binding`.
- `_incremental_index` modified-file branch still calls `_purge_file` or an explicitly named replacement cleanup path.
- `purge_orphaned_files` calls `_deactivate_filesystem_binding` for missing paths.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `source_documents`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `chunk_source_provenance_`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `chunks_fts_` and `vec_meta_`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts graph delete helpers are not called on normal unbind.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts modified files do not call `_deactivate_filesystem_binding`.
- `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="3" type="tdd">
<title>Rebind equivalent filesystem content to retained artifacts</title>
<name>Rebind equivalent filesystem content to retained artifacts</name>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/src/dotmd/storage/sqlite_vec.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/storage/metadata.py`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
</files>
<action>
Add concrete rebind behavior for equivalent filesystem content.

Concrete target state:
- When a filesystem document is discovered and an inactive binding exists with
  the same `namespace`, `content_fingerprint`, and `metadata_fingerprint`:
  1. upsert/reactivate the resource binding;
  2. persist or re-confirm the `SourceDocument`;
  3. preserve existing retained chunk IDs where the chunk/body strategy is unchanged;
  4. preserve or re-add M2M `chunk_file_paths_<strategy>` holder rows for the restored filesystem path;
  5. preserve or re-add `chunk_source_provenance_<strategy>` rows for the active ref;
  6. skip TEI encoding when existing vector rows or embedding-cache rows exist for all unchanged chunk text hashes;
  7. preserve FTS rows and graph artifacts when they are still present;
  8. update file trackers and binding fingerprints so the next run treats the file as unchanged.
- Add a countable diagnostic path with exact keys:
  `rebound`, `reused_chunks`, `reused_embeddings`, `retained_hidden`.
- The plan is not complete if rebind only writes a summary explaining why reuse remains missing. The unchanged-content rebind fixture must prove `TEI encode call count == 0`.
- Trickle coverage:
  - `index_file()` on a restored equivalent file reactivates the inactive binding;
  - `index_file()` on a modified present file updates fingerprints through the normal replacement path;
  - if a file disappears before `index_file()` can read it, the method returns the existing no-op/missing-file result and missing-path deactivation is covered by `purge_orphaned_files`.
- Do not add Telegram, attachment/media, TTL/GC policy, or generic plugin API behavior.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `rebound`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `reused_chunks`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `reused_embeddings`.
- `backend/tests/ingestion/test_source_filesystem.py` or `backend/tests/ingestion/test_metadata_only_reindex.py` deactivates a filesystem binding, restores equivalent content, and asserts active binding is restored.
- The rebind test asserts retained chunk IDs or retained row counts are reused.
- The rebind test asserts TEI encoding call count equals `0` for unchanged retained chunk text.
- The rebind test asserts `chunk_file_paths_` and `chunk_source_provenance_` rows exist after restore.
- A trickle `index_file()` restored-file test asserts active binding is restored.
- A trickle `index_file()` modified-file test asserts fingerprints update and no inactive binding is left behind.
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q` exits 0.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run:

```bash
cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py -q
```
</verification>

<success_criteria>
- Successful filesystem indexing creates or updates active bindings with current fingerprints.
- Normal filesystem disappearance deactivates visibility instead of hard-purging retained artifacts.
- Equivalent restored filesystem content reactivates/rebinds retained work with TEI encode call count `0`.
- Modified files still follow replacement reindex semantics and update fingerprints.
- Trickle `index_file()` and restored-file paths are covered.
- Graph artifacts are not deleted on normal unbind.
</success_criteria>
