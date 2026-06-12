---
phase: "25"
plan: "04"
type: execute
wave: 4
depends_on:
  - "25-01"
  - "25-02"
  - "25-03"
files_modified:
  - backend/tests/ingestion/test_source_filesystem.py
  - backend/tests/ingestion/test_metadata_only_reindex.py
  - backend/tests/ingestion/test_pipeline_purge.py
  - backend/tests/api/test_search_result_shape.py
  - backend/tests/mcp/test_search_tool.py
  - docs/source-adapter-architecture.md
  - docs/architecture.md
  - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-03: PDF/DOCX/HTML parser support is not part of Phase 25"
    - "D-07/D-08: Telegram read-only and mcp-telegram export implementation remain follow-up work"
    - "D-09: User-visible filesystem Markdown search/read behavior is regression-tested"
    - "D-10: Frontmatter title, kind, tags, and participants are documented as document metadata in the shim"
    - "D-11: Incremental fingerprint behavior is regression-tested"
    - "Documentation keeps SourceAsset, entity catalogs, transports, TTL policy, and second-source validation as future slices"
---

# Phase 25 Plan 04: Regression Suite, Documentation, and Phase Verification

<objective>
Close Phase 25 by adding end-to-end regression coverage and documentation for
the filesystem Markdown compatibility shim. This plan proves that the source
model is real internally while current users and MCP agents keep the same
filesystem search/read workflow.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| Tests only prove object construction and miss behavior drift | HIGH | Run ingestion, storage, API, and MCP tests together and include compatibility assertions. |
| Docs imply Telegram or assets shipped in Phase 25 | MEDIUM | Docs must name filesystem shim as shipped and keep Telegram/assets/entities/transports/TTL as future scope. |
| Live-container assumptions make the local regression suite brittle | MEDIUM | Verification uses mocked TEI and local SQLite/LadybugDB style tests; live smoke is optional only. |
| New public read contract is implied without implementation | MEDIUM | Docs state `read(file_path)` remains the Phase 25 public contract; ref-aware read is future/additive. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Add cross-surface filesystem compatibility regression tests</title>
<name>Add cross-surface filesystem compatibility regression tests</name>
<read_first>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-RESEARCH.md`
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
</read_first>
<files>
- `backend/tests/ingestion/test_source_filesystem.py`
- `backend/tests/ingestion/test_metadata_only_reindex.py`
- `backend/tests/ingestion/test_pipeline_purge.py`
- `backend/tests/api/test_search_result_shape.py`
- `backend/tests/mcp/test_search_tool.py`
</files>
<action>
Ensure the final test coverage proves the compatibility shim at every surface.

Required coverage:
- adapter discovery and fingerprint tests from Plan 01;
- adapter-routed chunk compatibility tests from Plan 02;
- source provenance persistence and delete cleanup tests from Plan 03;
- `SearchResult.file_paths` shape remains stable;
- MCP `search` returns `file_paths`;
- MCP `read(file_path, start, end)` remains path-based and returns
  frontmatter plus chunk ranges;
- at least one test asserts no runtime Telegram adapter or source asset/entity
  implementation exists in Phase 25 files.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_filesystem.py` contains `filesystem`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `content_fingerprint`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `metadata_fingerprint`.
- `backend/tests/ingestion/test_pipeline_purge.py` contains `source_documents` or the chosen source document table name.
- `backend/tests/api/test_search_result_shape.py` contains `file_paths`.
- `backend/tests/mcp/test_search_tool.py` contains `file_paths`.
- `backend/tests/mcp/test_search_tool.py` contains `read` or an existing read-tool compatibility test is added.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Document the shipped filesystem shim and future-source boundary</title>
<name>Document the shipped filesystem shim and future-source boundary</name>
<read_first>
- `docs/source-adapter-architecture.md`
- `docs/source-adapter-architecture-panel-review.md`
- `docs/architecture.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-ARCHITECTURE-PANEL.md`
</read_first>
<files>
- `docs/source-adapter-architecture.md`
- `docs/architecture.md`
</files>
<action>
Update docs to describe the Phase 25 delivered state and the future-source
boundary.

Required doc content:
- Phase 25 ships a filesystem Markdown compatibility shim through a
  source-aware internal model.
- Canonical filesystem mapping:
  - `namespace = filesystem`
  - `document_ref = str(Path(file_path).resolve())`
  - `ref = filesystem:<document_ref>`
  - `media_type = text/markdown`
  - `parser_name = markdown`
- `SourceDocument.file_path` is a compatibility field for filesystem sources;
  when present with `namespace = filesystem`, it must resolve to
  `document_ref`.
- Frontmatter `title`, `kind`, `tags`, and `participants` remain document
  metadata.
- `source_documents` is a single strategy-independent table keyed by
  `(namespace, document_ref)`; `chunk_source_provenance_<strategy>` is
  strategy-scoped.
- `file_paths` and MCP `read(file_path, start, end)` remain the public
  compatibility contract for filesystem hits.
- Telegram read-only, source assets, entity catalogs, adapter transports, TTL
  retention policy, and second-source validation remain later slices.
</action>
<acceptance_criteria>
- `docs/source-adapter-architecture.md` contains `filesystem:<document_ref>`.
- `docs/source-adapter-architecture.md` contains `str(Path(file_path).resolve())`.
- `docs/source-adapter-architecture.md` contains `source_documents`.
- `docs/source-adapter-architecture.md` contains `chunk_source_provenance`.
- `docs/source-adapter-architecture.md` contains `media_type = text/markdown`.
- `docs/source-adapter-architecture.md` contains `parser_name = markdown`.
- `docs/source-adapter-architecture.md` contains `read(file_path`.
- `docs/source-adapter-architecture.md` contains `Telegram read-only`.
- `docs/architecture.md` links or references the Phase 25 filesystem shim.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Run full focused verification gate</title>
<name>Run full focused verification gate</name>
<read_first>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md`
- `backend/pyproject.toml`
- `justfile`
</read_first>
<files>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md`
</files>
<action>
Run the final focused verification gate for Phase 25.

Preferred command if available:

```bash
just typecheck
```

Required focused tests:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q
cd backend && uv run pyright
```

If `just typecheck` is the repo-standard wrapper and runs pyright, record its
output instead of duplicating pyright manually.

Do not run `dotmd index --force` while the production container is running.
Do not restart production for Phase 25 tests unless the user explicitly asks
for a live smoke.
</action>
<acceptance_criteria>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `tests/ingestion/test_source_filesystem.py`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `tests/mcp/test_search_tool.py`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `pyright` or `just typecheck`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Self-Check: PASSED` if all required commands pass.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Write final phase summary with deferred scope audit</title>
<name>Write final phase summary with deferred scope audit</name>
<read_first>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-RESEARCH.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-02-SUMMARY.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-03-SUMMARY.md`
</read_first>
<files>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md`
</files>
<action>
Complete `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md`
with:

- the shipped internal model fields;
- the canonical filesystem ref rule: `document_ref = str(Path(file_path).resolve())`;
- where `file_path` is intentionally preserved;
- the `SourceDocument.file_path` and `document_ref` invariant;
- which object owns frontmatter metadata;
- how source-unit refs are attached to chunks;
- schema/storage changes made, including global `source_documents` and
  strategy-scoped `chunk_source_provenance_<strategy>`;
- how bulk `index(directory)` and trickle `index_file(path)` share the adapter
  and provenance path;
- how metadata-only change detection still avoids full re-chunking;
- commands run and outcomes;
- explicit deferred scope audit:
  - Telegram read-only adapter not implemented;
  - `mcp-telegram` export API not implemented;
  - source assets not implemented;
  - entity catalogs/canonical identity not implemented;
  - out-of-process transports not implemented;
  - TTL policy not implemented;
  - second-source validation not implemented.
</action>
<acceptance_criteria>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Canonical filesystem ref`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `str(Path(file_path).resolve())`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `file_path is preserved`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `index_file(path)`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `source_documents`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Frontmatter metadata owner`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Source-unit refs`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Telegram read-only adapter not implemented`.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` contains `Self-Check: PASSED`.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run focused verification:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q
cd backend && uv run pyright
```
</verification>

<success_criteria>
- Phase 25 has local regression coverage across ingestion, storage, API, and
  MCP surfaces.
- Docs describe the filesystem shim and future-source boundary accurately.
- Final summary answers every architecture panel acceptance-gate question.
- Production restart and `dotmd index --force` are not part of planning or
  normal verification.
- Deferred source work remains out of Phase 25.
</success_criteria>
