---
phase: 25
slug: document-source-abstraction-source-adapter-mvp
status: complete
nyquist_compliant: true
wave_0_complete: true
created: 2026-05-06
updated: 2026-05-06T13:11:55+05:00
validation_state: reconstructed-from-summaries
gaps_found: 0
gaps_resolved: 0
manual_only_count: 0
---

# Phase 25 - Validation Strategy

Retroactive Nyquist validation for the completed Document Source Abstraction
source adapter MVP. No pre-existing `25-VALIDATION.md` was present, so this
file reconstructs the validation contract from the Phase 25 plans, summaries,
verification report, security report, and current test suite.

## Test Infrastructure

| Property | Value |
|----------|-------|
| Framework | pytest via `uv run pytest`; pyright via repo ratchet |
| Config file | `backend/pyproject.toml` |
| Quick run command | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` |
| Focused full command | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/test_graph_delete.py -q` |
| Type command | `just typecheck` |
| Estimated runtime | ~20 seconds for focused pytest plus ratchet typecheck |

## Sampling Rate

- After every task commit: run the quick ingestion/source adapter test command.
- After every plan wave: run the focused full command for touched surfaces.
- Before `$gsd-verify-work`: focused full command plus `just typecheck`.
- Max feedback latency: focused pytest is under 15 seconds in the current checkout.

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Threat Ref | Secure Behavior | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|------------|-----------------|-----------|-------------------|-------------|--------|
| 25-01-01 | 01 | 1 | Source models | P25-01 T1/T2/T3/T4 | Filesystem refs are deterministic; future-source scope is forbidden | unit | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-01-02 | 01 | 1 | Filesystem Markdown adapter | P25-01 T1/T3/T4 | Adapter reuses reader checksums and emits only filesystem/Markdown docs | unit | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_meta_checksum.py -q` | yes | green |
| 25-01-03 | 01 | 1 | FileInfo compatibility bridge | P25-01 T1/T3 | `SourceDocument` converts back to compatible `FileInfo` only after ref validation | unit | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-01-04 | 01 | 1 | Deferred scope guards | P25-01 T4 | Telegram/assets/entities/transports are not introduced in runtime code | unit/static | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-02-01 | 02 | 2 | Caller-owned chunk provenance | P25-02 T1 | Direct chunker callers keep `provenance is None`; adapter callers pass explicit provenance | unit | `cd backend && uv run pytest tests/ingestion/test_chunker.py -q` | yes | green |
| 25-02-02 | 02 | 2 | Adapter-backed bulk indexing | P25-02 T2/T5 | Tracker diff still receives `FileInfo`; chunk text and file_paths remain stable | integration | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py -q` | yes | green |
| 25-02-03 | 02 | 2 | Metadata-only fast path | P25-02 T3/T4 | Title/tag-only changes avoid full re-chunking and keep TEI call count bounded | integration | `cd backend && uv run pytest tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-02-04 | 02 | 2 | `index_file()` adapter bridge | P25-02 T4 | Single-file indexing uses the same source document/provenance path as bulk indexing | integration | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-03-01 | 03 | 3 | Additive source schema | P25-03 T1/T6/T7 | `source_documents` and `chunk_source_provenance_*` are additive and migration-safe | unit/storage | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py -q` | yes | green |
| 25-03-02 | 03 | 3 | Provenance writes on save paths | P25-03 T2/T4/T5 | Bulk and trickle writes persist filesystem provenance with `source_unit_refs=[]` | integration/storage | `cd backend && uv run pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_source_filesystem.py -q` | yes | green |
| 25-03-03 | 03 | 3 | Path-compatible search and MCP read | P25-03 T3 | `file_paths` and MCP `read(file_path)` remain public compatibility contracts | api/mcp | `cd backend && uv run pytest tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py -q` | yes | green |
| 25-03-04 | 03 | 3 | Holder-aware cleanup | P25-03 T1/T4/T7 | Purge/drop cleanup removes only orphan provenance and preserves shared holders | integration/storage/graph | `cd backend && uv run pytest tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/test_graph_delete.py -q` | yes | green |
| 25-04-01 | 04 | 4 | Cross-surface regression suite | P25-04 T1 | Ingestion, storage, API, MCP, and graph cleanup behavior are covered together | integration | focused full command | yes | green |
| 25-04-02 | 04 | 4 | Documentation boundary | P25-04 T2 | Docs name shipped filesystem shim and defer future source scopes | docs/static | `rg "filesystem:<document_ref>|source_documents|read\\(file_path" docs/source-adapter-architecture.md docs/architecture.md` | yes | green |
| 25-04-03 | 04 | 4 | Type ratchet gate | P25-04 T3 | Project-wide raw pyright debt remains ratcheted; Phase 25 does not regress it | typecheck | `just typecheck` | yes | green |
| 25-04-04 | 04 | 4 | Deferred scope audit | P25-04 T4 | Telegram read-only, mcp-telegram export, assets, entities, transports, TTL, and second-source validation remain out of scope | docs/static | `rg "Telegram read-only adapter not implemented|Source assets not implemented|TTL policy not implemented" .planning/phases/25-document-source-abstraction-source-adapter-mvp/25-04-SUMMARY.md` | yes | green |

## Gap Analysis

| Area | Status | Evidence |
|------|--------|----------|
| Source domain models and filesystem identity | COVERED | `backend/tests/ingestion/test_source_filesystem.py` covers canonical refs, mismatch rejection, frontmatter, fingerprints, and deferrals. |
| Filesystem adapter and FileInfo bridge | COVERED | Source adapter tests cover discovery, exclusions, checksum reuse, and `source_document_to_file_info()`. |
| Chunk provenance and payload compatibility | COVERED | `backend/tests/ingestion/test_chunker.py` proves default `None` provenance, explicit provenance attachment, and unchanged chunk text. |
| Bulk and trickle ingestion routing | COVERED | `backend/tests/ingestion/test_source_filesystem.py` covers adapter-routed bulk and `index_file()` provenance behavior. |
| Metadata-only fast path | COVERED | `backend/tests/ingestion/test_metadata_only_reindex.py` covers TEI call count, vector replacement, FTS metadata, and graph frontmatter refresh. |
| Additive provenance persistence | COVERED | `backend/tests/storage/test_metadata_m2m.py` covers source documents, chunk provenance hydration, empty filesystem `source_unit_refs`, and file path compatibility. |
| Purge/drop cleanup | COVERED | `backend/tests/ingestion/test_pipeline_purge.py`, `backend/tests/storage/test_metadata_m2m.py`, and `backend/tests/test_graph_delete.py` cover holder-aware source and graph cleanup. |
| API/MCP compatibility | COVERED | `backend/tests/api/test_search_result_shape.py` and `backend/tests/mcp/test_search_tool.py` cover `file_paths` and path-based MCP read. |
| Docs and deferred boundaries | COVERED | `docs/source-adapter-architecture.md`, `docs/architecture.md`, and `25-04-SUMMARY.md` document shipped vs deferred scope. |
| Type checking | COVERED | `just typecheck` passes the repo-standard pyright ratchet. |

## Wave 0 Requirements

Existing infrastructure covers all Phase 25 requirements. No Wave 0 test
scaffolding is missing.

## Manual-Only Verifications

All phase behaviors have automated verification.

## Validation Audit 2026-05-06

| Metric | Count |
|--------|-------|
| Plans audited | 4 |
| Task rows mapped | 16 |
| Gaps found | 0 |
| Resolved | 0 |
| Escalated | 0 |
| Manual-only | 0 |

## Commands Run

| Command | Result |
|---------|--------|
| `gsd-sdk query config-get workflow.nyquist_validation --raw` | `true` |
| `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/test_graph_delete.py -q` | 71 passed, 24 warnings |
| `just typecheck` | passed; pyright ratchet: 70 errors, baseline 76, improvement -6 across 2 files |

## Validation Sign-Off

- [x] All tasks have automated verification or existing infrastructure coverage.
- [x] Sampling continuity: no 3 consecutive tasks without automated verification.
- [x] Wave 0 covers all missing references.
- [x] No watch-mode flags.
- [x] Feedback latency is under the focused-test budget.
- [x] `nyquist_compliant: true` set in frontmatter.

**Approval:** approved 2026-05-06
