---
phase: 25-document-source-abstraction-source-adapter-mvp
secured: 2026-05-06
status: secured
asvs_level: 1
threats_total: 21
threats_closed: 21
threats_open: 0
block_on: high,critical
---

# Phase 25 Security Verification

## Summary

All Phase 25 registered threat mitigations were verified against current code,
tests, docs, summaries, review, and verification artifacts. No implementation
files were modified during this audit.

## Threat Verification

| Threat ID | Category | Disposition | Status | Evidence |
|-----------|----------|-------------|--------|----------|
| T25-01 | source model compatibility | mitigate | CLOSED | `SourceDocument.file_path` and ref invariant in `backend/src/dotmd/core/models.py:81`; `source_document_to_file_info()` compatibility bridge in `backend/src/dotmd/ingestion/source.py:82`; test coverage in `backend/tests/ingestion/test_source_filesystem.py:120`. |
| T25-02 | source-unit storage | mitigate | CLOSED | `SourceUnit` exists as a model in `backend/src/dotmd/core/models.py:116`; persistence stores source document/provenance metadata only in `backend/src/dotmd/storage/metadata.py:97` and `backend/src/dotmd/storage/metadata.py:116`. |
| T25-03 | fingerprints | mitigate | CLOSED | Adapter sets `content_fingerprint=chunk_checksum(...)` and `metadata_fingerprint=meta_checksum(...)` in `backend/src/dotmd/ingestion/source.py:75`; tests assert formulas and split behavior in `backend/tests/ingestion/test_source_filesystem.py:107` and `backend/tests/ingestion/test_source_filesystem.py:147`. |
| T25-04 | phase scope | mitigate | CLOSED | Future runtime concepts are rejected by test scan in `backend/tests/ingestion/test_source_filesystem.py:513`; final summary records deferred scope in `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md:106`. |
| T25-05 | adapter routing/chunker | mitigate | CLOSED | Pipeline chunking passes adapter provenance through `_chunk_files()` in `backend/src/dotmd/ingestion/pipeline.py:1470`; tests compare adapter-routed payloads to direct `chunk_file()` in `backend/tests/ingestion/test_source_filesystem.py:368`. |
| T25-06 | metadata-only flow | mitigate | CLOSED | Split chunk/meta tracker flow remains in `backend/src/dotmd/ingestion/pipeline.py:409` and `backend/src/dotmd/ingestion/pipeline.py:419`; encode-call invariant test is `backend/tests/ingestion/test_metadata_only_reindex.py:117`. |
| T25-07 | filesystem chunk compatibility | mitigate | CLOSED | `Chunk.file_paths` remains in `backend/src/dotmd/core/models.py:157`; both normal and split chunk branches populate `file_paths=[file_path]` in `backend/src/dotmd/ingestion/chunker.py:223` and `backend/src/dotmd/ingestion/chunker.py:244`. |
| T25-08 | index_file trickle path | mitigate | CLOSED | Bulk `index()` discovers documents and bridges to `FileInfo` in `backend/src/dotmd/ingestion/pipeline.py:393`; `index_file()` normalizes through `_file_info_and_source_document()` in `backend/src/dotmd/ingestion/pipeline.py:1684`; parity tests in `backend/tests/ingestion/test_source_filesystem.py:246` and `backend/tests/ingestion/test_source_filesystem.py:275`. |
| T25-09 | FileTracker diff | mitigate | CLOSED | `SourceDocument` is converted to `FileInfo` before diffing in `backend/src/dotmd/ingestion/pipeline.py:743`; tracker calls use `files`/`[file_info]` in `backend/src/dotmd/ingestion/pipeline.py:409` and `backend/src/dotmd/ingestion/pipeline.py:1722`; test spy asserts `FileInfo` in `backend/tests/ingestion/test_source_filesystem.py:474`. |
| T25-10 | chunk provenance | mitigate | CLOSED | `ChunkProvenance.source_unit_refs` exists in `backend/src/dotmd/core/models.py:132`; filesystem provenance sets `source_unit_refs=[]` in `backend/src/dotmd/ingestion/pipeline.py:854`; tests assert the empty refs in `backend/tests/ingestion/test_source_filesystem.py:295`. |
| T25-11 | provenance cleanup | mitigate | CLOSED | Holder-aware cleanup deletes source documents, document provenance, and orphan chunk provenance in `backend/src/dotmd/ingestion/pipeline.py:1983`; cascade tests in `backend/tests/ingestion/test_pipeline_purge.py:196` and shared-holder tests in `backend/tests/ingestion/test_pipeline_purge.py:328`. |
| T25-12 | public search/MCP contract | mitigate | CLOSED | `SearchResult.file_paths` remains in `backend/src/dotmd/core/models.py:213`; MCP `SearchHit.file_paths` remains in `backend/src/dotmd/mcp_server.py:75`; tests cover API and MCP shapes in `backend/tests/api/test_search_result_shape.py:26` and `backend/tests/mcp/test_search_tool.py:34`. |
| T25-13 | source_documents schema | mitigate | CLOSED | One global `source_documents` table is keyed by `PRIMARY KEY (namespace, document_ref)` in `backend/src/dotmd/storage/metadata.py:97`; strategy-scoped chunk provenance table is separate in `backend/src/dotmd/storage/metadata.py:116`. |
| T25-14 | trickle single-file persistence | mitigate | CLOSED | Bulk save persists source documents/provenance in `backend/src/dotmd/ingestion/pipeline.py:1489`; `index_file()` persists source document and per-chunk provenance in `backend/src/dotmd/ingestion/pipeline.py:1793`; common persistence helper is `backend/src/dotmd/ingestion/pipeline.py:1931`. |
| T25-15 | source-unit refs schema | mitigate | CLOSED | Storage rejects non-empty filesystem `source_unit_refs` in `backend/src/dotmd/storage/metadata.py:389` and serializes refs as JSON in `backend/src/dotmd/storage/metadata.py:403`; round-trip tests assert `[]` in `backend/tests/storage/test_metadata_m2m.py:241`. |
| T25-16 | private data retention | mitigate | CLOSED | Provenance schema stores refs/metadata fields, not raw unit text, in `backend/src/dotmd/storage/metadata.py:97` and `backend/src/dotmd/storage/metadata.py:116`; docs state no durable parser-emitted units in `docs/source-adapter-architecture.md:48`. |
| T25-17 | schema migration | mitigate | CLOSED | Additive/idempotent DDL uses `CREATE TABLE IF NOT EXISTS` for `source_documents` and `chunk_source_provenance` in `backend/src/dotmd/storage/metadata.py:97` and `backend/src/dotmd/storage/metadata.py:116`; index creation is idempotent in `backend/src/dotmd/storage/metadata.py:272`. |
| T25-18 | regression coverage | mitigate | CLOSED | Final focused test gate passed `50 passed` in `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md:102`; verification artifact records expanded suite `71 passed` in `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-VERIFICATION.md:73`. |
| T25-19 | docs/scope | mitigate | CLOSED | Docs name the shipped filesystem shim and future-source boundary in `docs/source-adapter-architecture.md:13`; top-level architecture references the Phase 25 shim in `docs/architecture.md:187`; deferred scope is explicit in `docs/source-adapter-architecture.md:53`. |
| T25-20 | local regression brittleness | mitigate | CLOSED | Tests mock TEI in `backend/tests/ingestion/test_metadata_only_reindex.py:147` and use local settings; verification records local/mocked-service coverage and optional live smoke only in `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-VERIFICATION.md:95` and `.planning/phases/25-document-source-abstraction-source-adapter-mvp/25-VERIFICATION.md:110`. |
| T25-21 | public read contract | mitigate | CLOSED | `DotMDService.read(file_path, ...)` remains path-based in `backend/src/dotmd/api/service.py:638`; MCP read parameter is `file_path` in `backend/src/dotmd/mcp_server.py:630`; docs state `read(file_path)` remains public contract in `docs/source-adapter-architecture.md:15`. |

## Threat Flags

All four plan summaries report `Threat Flags: None`. No unregistered summary
flags were present to map.

## Accepted Risks

None.

## Audit Trail

| Date | Auditor | Result | Notes |
|------|---------|--------|-------|
| 2026-05-06 | Codex gsd-security-auditor | SECURED | Verified 21/21 registered mitigations. |
