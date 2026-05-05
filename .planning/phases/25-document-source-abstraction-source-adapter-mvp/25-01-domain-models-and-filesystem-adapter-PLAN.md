---
phase: "25"
plan: "01"
type: execute
wave: 1
depends_on: []
files_modified:
  - backend/src/dotmd/core/models.py
  - backend/src/dotmd/ingestion/source.py
  - backend/src/dotmd/ingestion/reader.py
  - backend/tests/ingestion/test_source_filesystem.py
  - .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md
autonomous: true
requirements: []
must_haves:
  truths:
    - "D-01: Phase 25 reproduces current filesystem Markdown indexing through an adapter-backed path before adding any new source"
    - "D-02: The new model includes namespace, document_ref, canonical ref, source-unit provenance, parser/media metadata, and chunk provenance"
    - "D-03: Filesystem is the only source namespace implemented and Markdown is the only parser implemented in this plan"
    - "D-04/D-05/D-06: The Phase 25 architecture panel contract is the planning source of truth"
    - "D-07/D-08: Telegram read-only and mcp-telegram export work are not implemented"
    - "D-09/D-10/D-11: filesystem Markdown behavior, frontmatter semantics, and split fingerprints remain compatible"
    - "No SourceAsset, SourceEntity, out-of-process adapter transport, TTL policy, or second-source validation implementation is added"
---

# Phase 25 Plan 01: Source Models and Filesystem Markdown Adapter

<objective>
Introduce the minimal source-aware internal model and filesystem Markdown
adapter contract needed for the compatibility shim.

This plan defines source documents, source units, and chunk provenance as
domain concepts, then maps current `.md` discovery into:

- `namespace = "filesystem"`
- `document_ref = <stable normalized path/ref>`
- `ref = "filesystem:<document_ref>"`
- `media_type = "text/markdown"`
- `parser_name = "markdown"`
- `document_type = <frontmatter kind>`

The plan does not change search behavior, does not add Telegram, and does not
add source assets or entity catalogs.
</objective>

<threat_model>
## Threat Model

| Threat | Severity | Mitigation |
|---|---:|---|
| New source model accidentally replaces file path compatibility before the rest of the stack is ready | HIGH | Keep compatibility path fields on filesystem documents and keep `FileInfo` compatibility wrappers in this plan. |
| Raw source-unit storage expands private data retention | MEDIUM | Define source-unit models, but do not require durable raw source-unit storage in this plan. |
| Fingerprint formulas drift while moving into source models | HIGH | Tests assert existing `chunk_checksum()` and `meta_checksum()` formulas still hold for adapter documents. |
| Future-source terms pull runtime scope into Phase 25 | MEDIUM | Tests and acceptance criteria reject Telegram/assets/entities/transports/TTL implementation in this plan. |
</threat_model>

<tasks>
<task id="1" type="execute">
<title>Add source-aware domain models</title>
<read_first>
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-CONTEXT.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-ARCHITECTURE-PANEL.md`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-RESEARCH.md`
- `backend/src/dotmd/core/models.py`
</read_first>
<files>
- `backend/src/dotmd/core/models.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Add minimal Pydantic models to `backend/src/dotmd/core/models.py`:

- `SourceDocument` with fields:
  - `namespace: str`
  - `document_ref: str`
  - `ref: str`
  - `title: str`
  - `source_uri: str`
  - `media_type: str`
  - `parser_name: str`
  - `document_type: str = DocKind.DOCUMENT`
  - `updated_at: datetime`
  - `content_fingerprint: str`
  - `metadata_fingerprint: str`
  - `metadata_json: dict = Field(default_factory=dict)`
  - `file_path: Path | None = None`
- `SourceUnit` with fields:
  - `namespace: str`
  - `document_ref: str`
  - `unit_ref: str`
  - `unit_type: str`
  - `text: str`
  - `order_key: str`
  - `fingerprint: str`
  - `metadata_json: dict = Field(default_factory=dict)`
  - `chunking_hints: dict = Field(default_factory=dict)`
- `ChunkProvenance` with fields:
  - `namespace: str`
  - `document_ref: str`
  - `source_unit_refs: list[str] = Field(default_factory=list)`
  - `chunk_strategy: str`
  - `parser_name: str | None = None`

Use `ConfigDict(extra="forbid")` on the new models. Do not add
`SourceAsset`, `SourceEntity`, `Mention`, or `CanonicalEntity`.
</action>
<acceptance_criteria>
- `backend/src/dotmd/core/models.py` contains `class SourceDocument`.
- `backend/src/dotmd/core/models.py` contains `namespace: str`.
- `backend/src/dotmd/core/models.py` contains `document_ref: str`.
- `backend/src/dotmd/core/models.py` contains `ref: str`.
- `backend/src/dotmd/core/models.py` contains `media_type: str`.
- `backend/src/dotmd/core/models.py` contains `parser_name: str`.
- `backend/src/dotmd/core/models.py` contains `content_fingerprint: str`.
- `backend/src/dotmd/core/models.py` contains `metadata_fingerprint: str`.
- `backend/src/dotmd/core/models.py` contains `class SourceUnit`.
- `backend/src/dotmd/core/models.py` contains `class ChunkProvenance`.
- `backend/src/dotmd/core/models.py` does not contain `class SourceAsset`.
- `backend/src/dotmd/core/models.py` does not contain `class SourceEntity`.
</acceptance_criteria>
</task>

<task id="2" type="execute">
<title>Implement filesystem Markdown source adapter</title>
<read_first>
- `backend/src/dotmd/ingestion/reader.py`
- `backend/src/dotmd/core/models.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-PATTERNS.md`
</read_first>
<files>
- `backend/src/dotmd/ingestion/source.py`
- `backend/src/dotmd/ingestion/reader.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Create `backend/src/dotmd/ingestion/source.py` with a Protocol-style source
adapter boundary and an in-process filesystem Markdown adapter.

Concrete target state:
- Define `SourceAdapterProtocol` with a method that can discover or export
  `SourceDocument` objects for the filesystem Markdown source.
- Define `FilesystemMarkdownSourceAdapter` that accepts the same path inputs
  used by current discovery.
- For every discovered Markdown file, emit a `SourceDocument` with:
  - `namespace="filesystem"`
  - `document_ref` set to a stable normalized path string using the same path
    normalization convention everywhere in this adapter
  - `ref=f"filesystem:{document_ref}"`
  - `media_type="text/markdown"`
  - `parser_name="markdown"`
  - `document_type` from frontmatter `kind` with `DocKind.DOCUMENT` default
  - `title` using the existing title extraction semantics
  - `file_path` set to the compatibility `Path`
  - `content_fingerprint` equal to the current `chunk_checksum(path)`
  - `metadata_fingerprint` equal to the current `meta_checksum(path)`
  - `metadata_json` containing current frontmatter
- Keep the adapter in-process. Do not add HTTP, MCP, Unix socket, command, or
  daemon transports.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/source.py` contains `class SourceAdapterProtocol`.
- `backend/src/dotmd/ingestion/source.py` contains `class FilesystemMarkdownSourceAdapter`.
- `backend/src/dotmd/ingestion/source.py` contains `namespace = "filesystem"` or `namespace="filesystem"`.
- `backend/src/dotmd/ingestion/source.py` contains `media_type = "text/markdown"` or `media_type="text/markdown"`.
- `backend/src/dotmd/ingestion/source.py` contains `parser_name = "markdown"` or `parser_name="markdown"`.
- `backend/src/dotmd/ingestion/source.py` contains `chunk_checksum`.
- `backend/src/dotmd/ingestion/source.py` contains `meta_checksum`.
- `backend/src/dotmd/ingestion/source.py` does not contain `telegram`.
- `backend/src/dotmd/ingestion/source.py` does not contain `socket`.
- `backend/src/dotmd/ingestion/source.py` does not contain `requests`.
</acceptance_criteria>
</task>

<task id="3" type="execute">
<title>Preserve reader compatibility wrappers</title>
<read_first>
- `backend/src/dotmd/ingestion/reader.py`
- `backend/src/dotmd/ingestion/source.py`
- `backend/tests/ingestion/test_chunker.py`
- `backend/tests/ingestion/test_meta_checksum.py`
</read_first>
<files>
- `backend/src/dotmd/ingestion/reader.py`
- `backend/tests/ingestion/test_source_filesystem.py`
</files>
<action>
Keep existing reader functions available for current call sites while allowing
the new adapter to share their logic.

Concrete rules:
- `discover_files(directory)` still returns `list[FileInfo]`.
- `discover_files_multi(paths, exclude)` still returns `list[FileInfo]`.
- `parse_frontmatter(content)`, `chunk_checksum(path)`, and
  `meta_checksum(path)` keep their current public behavior.
- Add a focused compatibility helper only if needed, for example converting a
  `SourceDocument` back to `FileInfo` for old pipeline code.
- Do not change `.md`-only discovery in this plan.
</action>
<acceptance_criteria>
- `backend/src/dotmd/ingestion/reader.py` still contains `def discover_files(`.
- `backend/src/dotmd/ingestion/reader.py` still contains `def discover_files_multi(`.
- `backend/src/dotmd/ingestion/reader.py` still contains `def chunk_checksum(`.
- `backend/src/dotmd/ingestion/reader.py` still contains `def meta_checksum(`.
- `backend/tests/ingestion/test_source_filesystem.py` has a test proving adapter output can be converted to or compared with `FileInfo` for title, kind, frontmatter, and path.
</acceptance_criteria>
</task>

<task id="4" type="execute">
<title>Test filesystem adapter contract and explicit deferrals</title>
<read_first>
- `backend/tests/ingestion/test_meta_checksum.py`
- `backend/tests/ingestion/test_chunker.py`
- `backend/src/dotmd/ingestion/source.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-ARCHITECTURE-PANEL.md`
</read_first>
<files>
- `backend/tests/ingestion/test_source_filesystem.py`
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md`
</files>
<action>
Add `backend/tests/ingestion/test_source_filesystem.py` with local tmp_path
tests.

Required test cases:
- A Markdown file with frontmatter produces one `SourceDocument` with
  `namespace=="filesystem"`, `ref.startswith("filesystem:")`,
  `media_type=="text/markdown"`, `parser_name=="markdown"`, frontmatter title,
  `document_type` equal to frontmatter `kind`, and non-empty
  `content_fingerprint` plus `metadata_fingerprint`.
- A body-only change changes `content_fingerprint` and does not change
  `metadata_fingerprint`.
- A title/tag-only change changes `metadata_fingerprint` and does not change
  `content_fingerprint`.
- Empty files and non-`.md` files remain excluded if the adapter wraps
  multi-path discovery.
- The test module or source module contains no runtime Telegram adapter,
  `SourceAsset`, `SourceEntity`, out-of-process transport, TTL, or
  second-source validation implementation.

Run:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_meta_checksum.py -q
```

Write `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md`
with commands run and any deviations.
</action>
<acceptance_criteria>
- `backend/tests/ingestion/test_source_filesystem.py` contains `FilesystemMarkdownSourceAdapter`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `namespace == "filesystem"`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `media_type == "text/markdown"`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `parser_name == "markdown"`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `content_fingerprint`.
- `backend/tests/ingestion/test_source_filesystem.py` contains `metadata_fingerprint`.
- `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_meta_checksum.py -q` exits 0.
- `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-01-SUMMARY.md` contains `FilesystemMarkdownSourceAdapter`.
</acceptance_criteria>
</task>
</tasks>

<verification>
Run focused verification:

```bash
cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_meta_checksum.py -q
cd backend && uv run pyright
```
</verification>

<success_criteria>
- Source-aware domain models exist and forbid accidental unknown fields.
- Filesystem Markdown adapter emits stable `filesystem:<document_ref>` refs.
- Current reader functions remain available for existing callers.
- Content and metadata fingerprints preserve current semantics.
- No Telegram, source asset, entity catalog, adapter transport, TTL, or
  second-source validation implementation enters the codebase.
</success_criteria>
