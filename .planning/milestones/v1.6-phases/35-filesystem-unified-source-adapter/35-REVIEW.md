---
phase: 35-filesystem-unified-source-adapter
reviewed: 2026-05-10T09:06:46Z
depth: standard
files_reviewed: 3
files_reviewed_list:
  - backend/src/dotmd/ingestion/source.py
  - backend/src/dotmd/ingestion/pipeline.py
  - backend/tests/ingestion/test_source_filesystem.py
findings:
  critical: 0
  warning: 3
  info: 2
  total: 5
status: issues_found
---

# Phase 35: Code Review Report

**Reviewed:** 2026-05-10T09:06:46Z
**Depth:** standard
**Files Reviewed:** 3
**Status:** issues_found

## Summary

This phase renames `_from_file_info` to `document_for_file_info`, making it public API on `FilesystemMarkdownSourceAdapter`, and adds behavioral tests covering the public lifecycle boundary. The rename itself is complete and consistent — no stale `_from_file_info` call sites exist anywhere in source or test code, and all six call paths in pipeline.py correctly use the new name via the `bundle.source.document_for_file_info(file_info)` delegation in `_source_document_for_file_info`.

The public name `document_for_file_info` communicates intent well: it is the constructor that maps a reader `FileInfo` to the source-layer `SourceDocument`. The name follows the established pattern (`source_document_to_file_info` for the inverse), and the direction is clear.

Three issues are worth fixing before this ships: the Protocol contract gap is the most structural — `SourceAdapterProtocol` doesn't include the newly public method, which means future non-filesystem adapters won't be bound to implement it even though the pipeline calls it. Two test issues are also flagged, one being a fragile relative path that will silently break outside of `backend/`.

## Warnings

### WR-01: `SourceAdapterProtocol` does not declare `document_for_file_info`

**File:** `backend/src/dotmd/ingestion/source.py:22-35`
**Issue:** The Protocol defines only `discover` and `discover_multi`. The newly public `document_for_file_info` is not part of the contract. The pipeline (`pipeline.py:1371`) reaches this method via `bundle.source`, which is typed as `FilesystemMarkdownSourceAdapter | None` — a concrete type — so it works today. However, any future adapter that satisfies `SourceAdapterProtocol` but doesn't implement `document_for_file_info` will pass type-checking and fail at runtime when `_source_document_for_file_info` calls it. Making the method part of the Protocol closes this gap structurally.

**Fix:**
```python
class SourceAdapterProtocol(Protocol):
    """Discovery boundary for source-backed documents."""

    def discover(self, directory: Path) -> list[SourceDocument]:
        """Discover source documents under a directory."""
        ...

    def discover_multi(
        self,
        paths: list[str],
        exclude: list[str] | None = None,
    ) -> list[SourceDocument]:
        """Discover source documents from multiple path specs."""
        ...

    def document_for_file_info(self, file_info: FileInfo) -> SourceDocument:
        """Build a SourceDocument from a pre-resolved FileInfo."""
        ...
```

---

### WR-02: `test_source_module_keeps_future_runtime_concepts_deferred` uses a relative path

**File:** `backend/tests/ingestion/test_source_filesystem.py:992`
**Issue:** `Path("src/dotmd/ingestion/source.py").read_text(...)` resolves relative to the process working directory. This works when pytest is invoked from `backend/` (which is the convention), but it will silently raise `FileNotFoundError` if run from the project root, a CI matrix with a different cwd, or via `python -m pytest` from another directory. The failure mode is a test crash, not a useful assertion message.

**Fix:**
```python
def test_source_module_keeps_future_runtime_concepts_deferred() -> None:
    source_path = Path(__file__).parents[3] / "src" / "dotmd" / "ingestion" / "source.py"
    source_text = source_path.read_text(encoding="utf-8")
    ...
```

---

### WR-03: `_source_document_for_file_info` bridge guard omits `last_modified` / `updated_at` from its equality check

**File:** `backend/src/dotmd/ingestion/pipeline.py:1373-1378`
**Issue:** The bridge validation compares `path`, `title`, `kind`, and `frontmatter` between the original `FileInfo` and the round-tripped `bridged_file_info`, but does not include `last_modified`. `document_for_file_info` sets `updated_at=file_info.last_modified` and `source_document_to_file_info` maps it back to `last_modified` — so the round-trip is currently faithful. However, the guard's purpose is to catch future drift in the adapter implementation; omitting `last_modified` from the check means a future adapter that re-reads `st_mtime` (introducing a small timestamp delta) would pass the guard silently and insert a stale timestamp into provenance. This gap is pre-existing but is now more visible because the path through `document_for_file_info` is public and the guard is the only safety net.

**Fix:**
```python
if (
    bridged_file_info.path != file_info.path
    or bridged_file_info.title != file_info.title
    or bridged_file_info.kind != file_info.kind
    or bridged_file_info.frontmatter != file_info.frontmatter
    or bridged_file_info.last_modified != file_info.last_modified
):
    raise ValueError("filesystem SourceDocument bridge changed FileInfo")
```

## Info

### IN-01: `document_for_file_info` is missing a docstring

**File:** `backend/src/dotmd/ingestion/source.py:63`
**Issue:** Every other public method in the file has a docstring (`discover`, `discover_multi`, `filesystem_document_ref`, `source_document_to_file_info`). The newly public `document_for_file_info` has none. For a public API boundary method this is a minor omission but inconsistent with the surrounding style.

**Fix:**
```python
def document_for_file_info(self, file_info: FileInfo) -> SourceDocument:
    """Build a filesystem SourceDocument from a pre-resolved FileInfo."""
    document_ref = filesystem_document_ref(file_info.path)
    ...
```

---

### IN-02: `test_filesystem_source_document_rejects_mismatched_file_path` is misattributed

**File:** `backend/tests/ingestion/test_source_filesystem.py:78-85`
**Issue:** The test name implies it is testing the adapter's rejection of a mismatched path, but it directly constructs a `SourceDocument` and exercises the Pydantic `_validate_refs` model validator in `core/models.py`. Neither `FilesystemMarkdownSourceAdapter` nor `document_for_file_info` is involved. The test belongs in a model-level test file, and its name should reflect that it tests `SourceDocument` construction, not the adapter. As written it provides no coverage of the adapter's own validation logic.

**Fix:** Move the test to `tests/core/test_models.py` (or equivalent model test file) and rename it to `test_source_document_rejects_mismatched_filesystem_document_ref`. No code change needed.

---

_Reviewed: 2026-05-10T09:06:46Z_
_Reviewer: Claude (gsd-code-reviewer)_
_Depth: standard_
