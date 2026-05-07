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
    - "Full-reindex answer: this plan must not run dotmd index --force or rebuild TEI/FTS/vector/graph stores."
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
| Existing purge path destroys reusable rows before service can hide them | HIGH | Add a separate deactivation path and route normal missing-file handling through it. |
| Hard-purge tests are blindly rewritten and GC/drop behavior becomes unsafe | MEDIUM | Keep `_purge_file` or a renamed hard-purge primitive only for explicit hard-delete/strategy-drop contexts. |
| Graph cleanup deletes retained graph work during unbind | HIGH | Normal unbind must not call `delete_chunks_from_graph`, `delete_file_node`, or `delete_file_subgraph`. |
| Restored unchanged files still call TEI despite retained chunk/vector rows | HIGH | Add fixture tests using encode-call counts or retained row counts to prove reuse/no full recomputation. |
| Modified files are incorrectly treated like missing files | HIGH | Preserve existing modified-file reindex semantics unless the plan implements an explicit replace/rebind path with tests. |
</threat_model>

<tasks>
<task id="1" type="tdd">
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
- Add a pipeline method such as `_deactivate_filesystem_binding(file_path: str) -> None`.
- It must:
  - derive `document_ref = self._meta_entity_id(file_path)`;
  - set the filesystem resource binding inactive using Plan 01 storage helpers;
  - preserve `source_documents`;
  - preserve `chunk_source_provenance_<strategy>`;
  - preserve `chunk_file_paths_<strategy>` rows unless a replacement holder
    mapping exists in the same task and tests prove rebind still works;
  - preserve `chunks_*`, `chunks_fts_*`, `vec_meta_*`, and graph artifacts;
  - remove or mark only source activity state, not retained artifacts.
- Keep `_purge_file()` as an explicit hard purge only if existing drop/GC
  behavior still needs it. Add docstring language:
  `Hard purge is not normal missing-resource handling; Phase 27 normal unbind uses _deactivate_filesystem_binding`.
- Change `_incremental_index()` so `diff.deleted` uses `_deactivate_filesystem_binding(path_str)`, not `_purge_file(path_str)`.
- Change `purge_orphaned_files(discovered_paths=...)` so missing paths use
  `_deactivate_filesystem_binding(file_path)`, not `_purge_file(file_path)`.
- Do not change modified-file handling unless tests cover the replacement path.
- Add/adjust tests:
  - normal missing path deactivates binding;
  - retained rows remain present in `source_documents`, provenance, chunks, FTS, and vector metadata;
  - graph delete helpers are not called on normal unbind;
  - explicit hard purge still removes rows only when invoked directly or from a clearly named GC/drop path.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `_deactivate_filesystem_binding`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `Hard purge is not normal missing-resource handling` or equivalent docstring wording.
- `_incremental_index` deleted-file branch calls `_deactivate_filesystem_binding`.
- `purge_orphaned_files` calls `_deactivate_filesystem_binding` for missing paths.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `source_documents`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `chunk_source_provenance_`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts normal unbind preserves `chunks_fts_` and `vec_meta_`.
- `backend/tests/ingestion/test_pipeline_purge.py` asserts graph delete helpers are not called on normal unbind.
- `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py -q` exits 0.
</acceptance_criteria>
</task>

<task id="2" type="tdd">
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
Add the minimal concrete rebind behavior for equivalent filesystem content.

Concrete target state:
- When a filesystem document is discovered with a `content_fingerprint` and
  `metadata_fingerprint` matching retained inactive binding/source rows:
  - reactivate/upsert the resource binding;
  - keep existing retained chunk IDs where the chunk/body strategy is unchanged;
  - avoid TEI re-embedding for unchanged chunk text when existing vector rows
    or text-hash cache rows are present;
  - preserve FTS rows and graph artifacts rather than rebuilding them if they
    are still present;
  - update file trackers/fingerprints so subsequent runs treat the file as
    unchanged.
- Add a small diagnostic return/log path with counts containing exact keys:
  `rebound`, `reused_chunks`, `reused_embeddings`, `retained_hidden`.
  It may be a log line, metadata helper return, or pipeline stats extension,
  but tests must be able to assert the values.
- If full no-TEI rebind is too risky in one step, implement a count/dry-run
  helper first, but the plan is not complete until filesystem restore either
  reuses retained artifacts or explicitly records why one recomputation remains.
- Do not add Telegram, attachment/media, or generic plugin API behavior.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `rebound`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `reused_chunks`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `reused_embeddings`.
- `backend/tests/ingestion/test_source_filesystem.py` or `backend/tests/ingestion/test_metadata_only_reindex.py` deactivates a filesystem binding, restores equivalent content, and asserts active binding is restored.
- The rebind test asserts retained chunk IDs or retained row counts are reused.
- The rebind test asserts TEI encoding is not called for unchanged retained chunk text, or documents a single remaining recomputation in a summary/gap with a focused follow-up.
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
- Normal filesystem disappearance deactivates visibility instead of hard-purging retained artifacts.
- Equivalent restored filesystem content can reactivate/rebind retained work.
- Graph artifacts are not deleted on normal unbind.
- Existing hard-purge behavior remains explicit and not confused with normal missing-resource handling.
</success_criteria>
