---
phase: "33"
plan: "02"
type: tdd
wave: 2
depends_on:
  - "33-01"
files_modified:
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/src/dotmd/ingestion/source_lifecycle.py
  - backend/tests/ingestion/test_source_lifecycle.py
  - backend/tests/ingestion/test_source_filesystem.py
autonomous: true
requirements: ["LIFE-01", "LIFE-04"]
requirements_addressed: ["LIFE-01", "LIFE-04"]
must_haves:
  truths:
    - "D-13: Filesystem does not pretend to have provider-owned cursor commits."
    - "D-14: Filesystem construction path must route through lifecycle/factory, not stop at a dead architecture layer."
    - "D-16: Filesystem paths remain internal holder mechanics for discovery, reads, delete detection, parser routing, and content-addressed reuse."
    - "Phase 26 guardrail: public source identity remains source-ref-first; filesystem paths do not return as public identity."
    - "Phase 27 guardrail: retained artifacts and active bindings remain the public visibility gate."
---

# Phase 33 Plan 02: Filesystem Lifecycle Migration

<objective>
Route the real filesystem discovery and source-document construction path in
`IndexingPipeline` through the lifecycle runtime factory while preserving
existing filesystem refs, internal holder paths, and retained-artifact behavior.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Lifecycle remains unused by filesystem runtime | HIGH | Tests monkeypatch/fake lifecycle construction and assert pipeline discovery uses the lifecycle bundle. |
| Public filesystem identity regresses to path-first | HIGH | Existing source-ref tests continue to assert `SourceDocument.ref == filesystem:<resolved_path>` and public read/search uses refs. |
| Filesystem starts claiming provider cursor semantics | HIGH | Runtime metadata can expose fingerprint state, but tests assert filesystem bundle has no application provider and no provider checkpoint cursor commit path. |
| Direct adapter construction remains in pipeline | MEDIUM | Static acceptance criterion rejects `FilesystemMarkdownSourceAdapter()` in `pipeline.py`. |
| Discovery config drifts from settings | MEDIUM | Factory builder uses the live `Settings` API: `FilesystemSourceConfig(paths=settings.indexing_paths, exclude=settings.effective_indexing_exclude)`. Runtime validation already requires `indexing_paths` to be non-empty absolute path specs. |
| Retained artifact behavior is disturbed | HIGH | Run existing source filesystem tests that cover active bindings, missing files, and holder mechanics. |
</threat_model>

<tasks>
<task id="1" type="tdd">
<name>Add filesystem lifecycle regression tests</name>
<title>Add filesystem lifecycle regression tests</title>
<read_first>
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-RESEARCH.md`
- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-PATTERNS.md`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Add failing tests proving the filesystem path uses lifecycle.

Concrete tests:
- In `backend/tests/ingestion/test_source_lifecycle.py`, add
  `test_source_runtime_factory_from_settings_seeds_filesystem_config`:
  construct `Settings(data_dir=tmp_path / "data", index_dir=tmp_path / "index",
  embedding_url="http://localhost:18088", indexing_paths=[str(tmp_path / "data")],
  indexing_extra_exclude=["ignored"])`, then call the new settings helper
  planned in task 2. Assert the returned filesystem config contains the data
  path and an exclude list containing `"ignored"`.
- In `backend/tests/ingestion/test_source_filesystem.py`, add
  `test_pipeline_discovers_filesystem_documents_through_lifecycle`:
  create an `IndexingPipeline`, replace its lifecycle/factory dependency with
  a fake whose `build("filesystem")` returns a bundle with a recording adapter,
  call `_discover_documents_multi([str(tmp_path)], exclude=["skip"])`, and
  assert the fake received namespace `filesystem` and the recording adapter
  received the exact paths/exclude values.
- Add `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter`:
  create a `FileInfo`, route `_source_document_for_file_info(file_info)`, and
  assert the resulting document still has `namespace == "filesystem"`,
  `document_ref == str(file_info.path.resolve())`, and
  `ref == f"filesystem:{file_info.path.resolve()}"`.
- Add a static-style test or assertion that filesystem lifecycle runtime has
  `provider is None` and does not expose a provider checkpoint commit.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_filesystem.py` contains `test_pipeline_discovers_filesystem_documents_through_lifecycle`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter`.
- `backend/tests/ingestion/test_source_lifecycle.py` contains `test_source_runtime_factory_from_settings_seeds_filesystem_config`.
- The tests fail before task 2 and exit 0 after task 2 with `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q`.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q` fails before task 2 because pipeline construction still bypasses lifecycle.
</verify>
<done>
Filesystem lifecycle regression tests are present and fail only on missing lifecycle integration.
</done>
</task>

<task id="2" type="tdd">
<name>Route IndexingPipeline filesystem construction through lifecycle</name>
<title>Route IndexingPipeline filesystem construction through lifecycle</title>
<read_first>
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/source_registry.py`
- `backend/src/dotmd/core/config.py`
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source_lifecycle.py`
- `backend/src/dotmd/ingestion/pipeline.py`
- `backend/tests/ingestion/test_source_lifecycle.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Integrate the lifecycle factory into filesystem construction.

Concrete target state:
- Add a helper in `source_lifecycle.py`, for example
  `source_runtime_factory_from_settings(settings: Settings, metadata_store: SQLiteMetadataStore) -> SourceRuntimeFactory`.
- The helper builds:
  - `default_source_registry()`
  - `InMemorySourceConfigStore`
  - filesystem `SourceConfigRecord(namespace="filesystem", config=FilesystemSourceConfig(paths=settings.indexing_paths, exclude=settings.effective_indexing_exclude), credential_ref=SourceCredentialRef(namespace="filesystem"))`
  - Do not add or reference a resolved-indexing-paths alias; live `Settings` exposes `indexing_paths`, and `validate_for_runtime()` already enforces absolute non-empty indexing path specs for runtime startup.
  - Telegram config only if settings has `telegram_daemon_socket`; Plan 03 may complete/extend this.
  - `DefaultSourceCredentialProvider`
  - `SQLiteSourceCursorStore(metadata_store)`
- In `IndexingPipeline.__init__`, create and store the lifecycle factory after
  metadata store initialization, for example `self._source_runtime_factory`.
- Replace direct calls in `pipeline.py`:
  - `_discover_documents(directory)` obtains `bundle = self._source_runtime_factory.build("filesystem")`, asserts/guards `bundle.source is not None`, and calls `bundle.source.discover(directory)`.
  - `_discover_documents_multi(paths, exclude)` obtains the same bundle and calls `bundle.source.discover_multi(paths, exclude)`.
  - `_source_document_for_file_info(file_info)` uses the filesystem source from the lifecycle bundle to build or bridge the source document. If the exact adapter method remains `_from_file_info`, keep it private to the adapter but obtain the adapter from lifecycle first.
- Do not change `filesystem_document_ref()` semantics.
- Do not change public search/read result shapes.
- Do not add filesystem checkpoint commits.
- Do not run or require a full reindex.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/pipeline.py` contains `_source_runtime_factory`.
- `backend/src/dotmd/ingestion/pipeline.py` contains `.build("filesystem")`.
- `backend/src/dotmd/ingestion/pipeline.py` does not contain `FilesystemMarkdownSourceAdapter()`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `source_runtime_factory_from_settings`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `settings.indexing_paths`.
- `backend/src/dotmd/ingestion/source_lifecycle.py` contains `settings.effective_indexing_exclude`.
- `rg -n "resolved[_]indexing[_]paths" backend/src/dotmd/ingestion/source_lifecycle.py` returns no matches.
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q` exits 0.
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py` exits 0.
</acceptance_criteria>
<verify>
`cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q`
`cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py`
`rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` returns no matches.
`rg -n "resolved[_]indexing[_]paths" backend/src/dotmd/ingestion/source_lifecycle.py` returns no matches.
</verify>
<done>
Filesystem discovery and source-document bridge paths obtain their adapter through lifecycle and preserve source-ref-first behavior.
</done>
</task>
</tasks>

<verification>
- `cd backend && uv run pytest tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py -q`
- `cd backend && uv run pyright src/dotmd/ingestion/source_lifecycle.py src/dotmd/ingestion/pipeline.py tests/ingestion/test_source_lifecycle.py tests/ingestion/test_source_filesystem.py`
- `rg -n "FilesystemMarkdownSourceAdapter\\(\\)" backend/src/dotmd/ingestion/pipeline.py` returns no matches.
</verification>

<success_criteria>
- LIFE-01 applies to the filesystem runtime bundle.
- LIFE-04 is partially satisfied: filesystem construction path uses lifecycle.
- Filesystem public refs and internal holder path mechanics remain unchanged.
- Filesystem does not claim provider-owned cursor commits.
</success_criteria>
