# Phase 35: Filesystem Unified Source Adapter — Research

**Researched:** 2026-05-10
**Status:** Complete

---

## Summary

Phase 35 is a narrow refactoring: one private method rename, one call-site update,
and targeted tests proving the public boundary works. The CONTEXT.md decisions are
authoritative — this research surfaces the exact code locations and confirms no
surprises exist.

---

## What Needs to Change

### Change 1: Rename `_from_file_info` → `document_for_file_info` (D-03)

**File:** `backend/src/dotmd/ingestion/source.py`

Current code:
```python
def _from_file_info(self, file_info: FileInfo) -> SourceDocument:
```

Becomes:
```python
def document_for_file_info(self, file_info: FileInfo) -> SourceDocument:
```

Internal callers within the same class (`discover`, `discover_multi`) also call
`self._from_file_info(file_info)` — these must be updated to
`self.document_for_file_info(file_info)`.

### Change 2: Update `_source_document_for_file_info` in pipeline.py (D-02, D-05)

**File:** `backend/src/dotmd/ingestion/pipeline.py`, line ~1371

Current:
```python
source_document = bundle.source._from_file_info(file_info)
```

Becomes:
```python
source_document = bundle.source.document_for_file_info(file_info)
```

This is the **only** call site in `pipeline.py` that hits the private method.
All other pipeline filesystem methods (`_discover_filesystem_documents`,
`_discover_filesystem_documents_multi`) already go through public protocol
(`bundle.source.discover()`, `bundle.source.discover_multi()`).

### Change 3: Update test double in test_source_filesystem.py (D-07)

**File:** `backend/tests/ingestion/test_source_filesystem.py`, lines 250–270

`_RecordingLifecycleAdapter` currently overrides `_from_file_info`:
```python
def _from_file_info(self, file_info: FileInfo) -> SourceDocument:
    self.file_infos.append(file_info)
    return super()._from_file_info(file_info)
```

Must be updated to override `document_for_file_info`:
```python
def document_for_file_info(self, file_info: FileInfo) -> SourceDocument:
    self.file_infos.append(file_info)
    return super().document_for_file_info(file_info)
```

---

## What Does NOT Change

Per CONTEXT.md decisions D-01, D-04, D-05, D-06:

- `SourceAdapterProtocol` stays at `discover()` + `discover_multi()` — no new methods.
- `source_document_to_file_info()` in `source.py` stays unchanged (carries validation invariant).
- `_filesystem_chunk_provenance`, `_upsert_active_filesystem_binding`,
  `_rebind_retained_filesystem_document(s)`, `_deactivate_filesystem_binding` stay in
  `IndexingPipeline` — they are orchestration concerns, not adapter concerns.
- `trickle.py` stays unchanged — inotify delivers raw paths; `index_file(Path)` is not a bypass.
- No changes to `source_registry.py`, `source_lifecycle.py`, `mcp_server.py`,
  `api/service.py`, `search/`, or `storage/`.

---

## New Tests Required (D-07)

Two targeted behavioral tests in `backend/tests/ingestion/`:

1. **`test_filesystem_adapter_document_for_file_info_is_public_and_correct`**
   - Creates a tmp markdown file
   - Calls `FilesystemMarkdownSourceAdapter().document_for_file_info(file_info)` directly
   - Verifies returned `SourceDocument` has correct `namespace`, `document_ref`, `file_path`,
     `ref`, `media_type`, `parser_name`
   - Proves the renamed method is accessible and produces correct output

2. **`test_lifecycle_factory_exposes_document_for_file_info_through_bundle`**
   - Builds a `SourceRuntimeBundle` through `SourceRuntimeFactory.build("filesystem")`
   - Calls `bundle.source.document_for_file_info(file_info)` via the lifecycle path
   - Verifies `SourceDocument` shape and that `bundle.source` is not `None`
   - Proves end-to-end lifecycle construction → public method call chain works

Both tests land in `test_source_filesystem.py` or a new
`test_source_filesystem_boundary.py` — agent's discretion per CONTEXT.md.

The existing test
`test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` already covers
that `_source_document_for_file_info` in pipeline goes through lifecycle. After the
rename, that test's `_RecordingLifecycleAdapter` will also need updating.

---

## Existing Test Exposure

`_RecordingLifecycleAdapter.file_infos` capture currently goes via `_from_file_info`.
After rename, the test double's override must match the new method name or the
recorder won't fire. The existing test for lifecycle routing
(`test_pipeline_source_document_for_file_info_uses_lifecycle_adapter`) will fail
until the double is updated — this is expected and confirms the rename propagated.

---

## Validation Architecture

### Test Infrastructure

- Framework: pytest
- Config: `backend/pyproject.toml`
- Quick run: `cd backend && python -m pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_source_lifecycle.py -q`
- Full suite: `cd backend && python -m pytest -q`
- Estimated runtime: ~30 seconds

### Per-Task Verification Map

| Task | Requirement | Test | Command |
|------|-------------|------|---------|
| Rename `_from_file_info` in source.py | FS-03 | Existing test suite passes; no `_from_file_info` in source.py | `python -m pytest tests/ingestion/test_source_filesystem.py -q` |
| Update `_source_document_for_file_info` in pipeline.py | FS-03 | `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter` passes | `python -m pytest tests/ingestion/test_source_filesystem.py::test_pipeline_source_document_for_file_info_uses_lifecycle_adapter -q` |
| Update `_RecordingLifecycleAdapter` test double | FS-01 | Existing lifecycle routing test passes after rename | `python -m pytest tests/ingestion/test_source_filesystem.py -q` |
| Add targeted public-boundary tests | FS-01, FS-03 | Two new tests green | `python -m pytest tests/ingestion/ -q` |

### Max Feedback Latency

< 30 seconds (full ingestion suite)

---

## Risk Assessment

**Very low risk.** The change is:
- 1 method rename (3 occurrences: definition + 2 internal callers)
- 1 call-site update in pipeline.py (line ~1371)
- 1 test double update
- 2 new tests

No behavioral change — only naming and access visibility. All existing behavior is
preserved; the rename is the only observable delta from the public interface
perspective.

The existing test `test_pipeline_source_document_for_file_info_uses_lifecycle_adapter`
already verifies lifecycle routing end-to-end. The full integration test suite
(`test_source_filesystem.py`, `test_source_lifecycle.py`) covers FS-01 behaviorally.

---

## Conclusion

This phase has a minimal change surface with high existing test coverage.
Two plans suffice:
1. **Rename + call-site fix** (source.py + pipeline.py): the structural refactor
2. **Targeted tests**: two new behavioral tests for the public boundary

Wave 1 = rename+fix, Wave 2 = tests (depends on Wave 1).
