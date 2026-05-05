---
phase: 25-document-source-abstraction-source-adapter-mvp
verified: 2026-05-05T21:44:39Z
status: passed
score: 8/8 must-haves verified
overrides_applied: 0
gaps: []
human_verification: []
---

# Phase 25: Document Source Abstraction Source Adapter MVP Verification Report

**Phase Goal:** Implement the Document Source Abstraction source adapter MVP as a filesystem Markdown compatibility shim through source-aware internal models. Telegram/read-only adapters are deferred.
**Verified:** 2026-05-05T21:44:39Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | SourceDocument, SourceUnit, ChunkProvenance models exist with filesystem identity invariants and no future-source runtime scope. | VERIFIED | `backend/src/dotmd/core/models.py` defines all three models with `extra="forbid"` and validates `ref == f"{namespace}:{document_ref}"`; filesystem documents validate `document_ref == str(file_path.resolve())`. `backend/tests/ingestion/test_source_filesystem.py` covers canonical refs, mismatch rejection, fingerprints, and deferred runtime terms. |
| 2 | Filesystem Markdown discovery is adapter-backed and converts through FileInfo for path compatibility. | VERIFIED | `backend/src/dotmd/ingestion/source.py` implements `FilesystemMarkdownSourceAdapter`, `filesystem_document_ref()`, and `source_document_to_file_info()`. `IndexingPipeline.index()` discovers source documents then bridges to `FileInfo` before tracker diffing. Tests assert tracker inputs are `FileInfo`, not `SourceDocument`. |
| 3 | Chunking remains path-compatible while carrying caller-owned source provenance for adapter-routed ingestion. | VERIFIED | `chunk_file()` accepts optional `ChunkProvenance`, leaves direct callers at `provenance is None`, and preserves `file_paths=[file_path]`. Pipeline passes filesystem provenance with `namespace=filesystem`, `document_ref=str(path.resolve())`, `ref=filesystem:<document_ref>`, `parser_name=markdown`, and `source_unit_refs=[]`. Tests compare adapter-routed chunk payloads to direct chunking. |
| 4 | `source_documents` and `chunk_source_provenance_<strategy>` persist additively without replacing `chunk_file_paths_<strategy>`. | VERIFIED | `SQLiteMetadataStore` creates global `source_documents` keyed by `(namespace, document_ref)` and strategy-scoped `chunk_source_provenance_<strategy>` with chunk index. Storage tests round-trip source documents, empty filesystem source-unit refs, batch provenance hydration, and prove file path hydration still uses `chunk_file_paths`. |
| 5 | Search, API read, and MCP compatibility remain path-based. | VERIFIED | `SearchResult.file_paths` remains the public result shape; fusion hydrates paths from metadata M2M. `DotMDService.read(file_path, start, end)` uses file path and chunk ranges. MCP `SearchHit` exposes `file_paths`, and MCP `read` calls `service.read(file_path, start, end)`. Tests cover API result shape, MCP search output schema/output, and MCP read compatibility. |
| 6 | Metadata-only vector replacement and search/graph metadata refresh are correct. | VERIFIED | `_index_file_embed()` deletes current vector rows for changed chunks before adding recomputed fused vectors; metadata-only bulk and `index_file()` tests prove vector rows are replaced without wiping siblings. FTS metadata and graph frontmatter refresh are explicitly tested for updated title/tags and removed tag edges. |
| 7 | `drop_chunks()`, purge cleanup, and source provenance cleanup are holder-aware. | VERIFIED | `drop_chunks()` drops current strategy chunk/M2M/provenance tables and deletes `source_documents` only for paths no longer referenced by other strategies. `_holder_aware_chunk_cleanup()` deletes the filesystem source document, document-specific provenance, and orphan chunk provenance while preserving shared chunks. Tests cover single-holder purge, shared-holder preservation, mixed strategies, drop cleanup, and source provenance cleanup. |
| 8 | LadybugDB/FalkorDB graph purge uses holder-aware chunk deletion and preserves shared graph state. | VERIFIED | Graph protocols and both backends expose `delete_chunks_from_graph(chunk_ids)` and `delete_file_node(file_path)`. Pipeline purge calls `delete_chunks_from_graph()` only for orphan chunk IDs, then deletes only the file node. Tests include the post-review holder-aware graph path check and LadybugDB delete behavior. |

**Score:** 8/8 truths verified

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/core/models.py` | Source-aware models and chunk provenance field | VERIFIED | Defines `SourceDocument`, `SourceUnit`, `ChunkProvenance`, and `Chunk.provenance`; filesystem ref validation is enforced. |
| `backend/src/dotmd/ingestion/source.py` | Filesystem Markdown source adapter and compatibility conversion | VERIFIED | Adapter wraps current Markdown discovery, computes canonical filesystem refs, copies frontmatter metadata, and converts back to `FileInfo`. No Telegram/assets/entities/transports implementation found. |
| `backend/src/dotmd/ingestion/chunker.py` | Optional caller-owned provenance with unchanged chunk payload semantics | VERIFIED | Direct `chunk_file(path)` returns chunks with `provenance is None`; explicit provenance attaches without changing text/headings/file_paths. |
| `backend/src/dotmd/ingestion/pipeline.py` | Source-document routing, provenance writes, metadata-only refresh, holder-aware cleanup | VERIFIED | Bulk and single-file ingestion route through filesystem source documents; provenance is persisted on save paths; metadata-only refresh updates vectors/FTS/graph; purge/drop cleanup handles source tables. |
| `backend/src/dotmd/storage/metadata.py` | Additive SQLite provenance schema and helpers | VERIFIED | Adds `source_documents` and `chunk_source_provenance_<strategy>` DDL/helpers; `delete_all()` clears source-aware tables. |
| `backend/src/dotmd/mcp_server.py` and `backend/src/dotmd/api/service.py` | Path-compatible MCP/search/read surfaces | VERIFIED | MCP search returns `file_paths`; MCP read remains `file_path` based; API read uses path-based metadata range calls. |
| `docs/source-adapter-architecture.md` and `docs/architecture.md` | Shipped filesystem shim and deferred-source boundary documented | VERIFIED | Docs describe Phase 25 filesystem mapping, storage split, path-compatible public contract, and defer Telegram/source assets/entities/transports/TTL/second-source plus PDF/DOCX/HTML parser support. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `IndexingPipeline.index()` | `FilesystemMarkdownSourceAdapter.discover()` | `_discover_documents()` | WIRED | Bulk discovery returns `SourceDocument` objects, then bridges to `FileInfo` for trackers. |
| `IndexingPipeline.index_file()` | filesystem source bridge | `_file_info_and_source_document()` | WIRED | Path and `FileInfo` inputs normalize through the same SourceDocument path before chunking. |
| Pipeline chunks | source provenance persistence | `_persist_chunk_source_provenance()` / `_persist_one_chunk_source_provenance()` | WIRED | Bulk and single-file save paths write source documents and chunk provenance. |
| Search fusion | path compatibility | `get_file_paths_for_chunk_ids()` | WIRED | Search results remain hydrated from M2M file paths, not source refs. |
| MCP `read` | API `read` | `service.read(file_path, start, end)` | WIRED | Public read contract remains path-based. |
| Purge | graph cleanup | `delete_chunks_from_graph()` + `delete_file_node()` | WIRED | Only orphan chunk IDs are passed to graph chunk deletion; file node deletion is separate. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `FilesystemMarkdownSourceAdapter` | `SourceDocument` | Existing `discover_files()` / `discover_files_multi()` and reader checksums | Yes | FLOWING |
| `chunk_file()` / pipeline `_chunk_files()` | `Chunk.provenance` | Pipeline-built filesystem `SourceDocument` | Yes | FLOWING |
| `SQLiteMetadataStore` provenance helpers | `source_documents`, `chunk_source_provenance_<strategy>` rows | Pipeline save paths and storage helpers | Yes | FLOWING |
| Fusion/search results | `SearchResult.file_paths` | `chunk_file_paths_<strategy>` batch hydration | Yes | FLOWING |
| MCP read result | `frontmatter`, `chunks` | Filesystem read plus metadata store chunk range lookup | Yes | FLOWING |
| Metadata-only refresh | vector rows, FTS metadata, graph frontmatter edges | Existing chunks and `FileInfo` frontmatter | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused Phase 25 regression suite | `cd backend && uv run pytest tests/ingestion/test_source_filesystem.py tests/ingestion/test_chunker.py tests/ingestion/test_metadata_only_reindex.py tests/ingestion/test_pipeline_purge.py tests/storage/test_metadata_m2m.py tests/api/test_search_result_shape.py tests/mcp/test_search_tool.py tests/test_graph_delete.py -q` | `71 passed, 24 warnings in 7.02s` | PASS |
| Repo-standard type gate | `just typecheck` | `pyright ratchet: 70 errors (baseline 76); improvements: -6 across 2 files` | PASS |
| Artifact/key-link helper | `gsd-sdk query verify.artifacts/key-links ...` | Plans have no `must_haves.artifacts` or `must_haves.key_links` frontmatter; manual artifact/link verification performed from plan truths. | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| None declared | All Phase 25 plans | Plan frontmatter `requirements: []`; ROADMAP phase says `Requirements: TBD`; `.planning/REQUIREMENTS.md` has no Phase 25 mappings. | N/A | No requirement IDs to verify. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `backend/src/dotmd/ingestion/pipeline.py` | 680 | `embeddings.append([])  # placeholder; filled below` | INFO | Existing local batching placeholder, populated before use; not a Phase 25 stub. |
| Multiple tests/code paths | various | `source_unit_refs=[]` | INFO | Intentional Phase 25 filesystem shim semantics; tests assert empty refs until durable source-unit emission is added later. |
| `backend/src/dotmd/storage/metadata.py` | 966 | `file_paths=[]  # hydrated separately...` | INFO | Existing storage hydration pattern; not user-visible empty data. |

No blocker or warning anti-patterns were found in the Phase 25 implementation surface.

### Human Verification Required

None. This phase is an internal compatibility shim with local, mocked-service regression coverage. No visual, interactive, or external-service behavior is required for goal achievement.

### Deferred Items

No failed must-have was deferred to a later roadmap phase. The following are explicitly out of Phase 25 scope and documented as future slices, not gaps:

| Item | Status | Evidence |
|---|---|---|
| Telegram read-only adapter and `mcp-telegram` export | Deferred by contract | Docs and tests state not implemented in Phase 25. |
| SourceAsset, SourceEntity, canonical identity, transports, TTL, second-source validation | Deferred by contract | Runtime scan found no implementation in Phase 25 source adapter; docs mark as future. |
| PDF/DOCX/HTML parser support | Deferred by contract | Docs mark parser support as future; Phase 25 adapter is Markdown-only. |

### Residual Risks

- Raw `cd backend && uv run pyright` still has project-wide historical debt, but the repo-standard ratchet gate passed and improved from baseline 76 to 70 errors.
- Live production container MCP smoke was not run because the phase contract and tests use local mocked runtime; production restart/smoke remains a deployment concern.
- Current public compatibility remains path-based. Future non-filesystem sources will still need an additive `read(ref)` or equivalent compatibility design.
- Source-unit persistence is deliberately minimal: filesystem chunks persist `source_unit_refs=[]`, so later non-filesystem/source-unit phases must define real unit emission and context-read semantics.

### Gaps Summary

No blocking gaps found. The Phase 25 goal is achieved: current filesystem Markdown indexing now flows through source-aware internal models and persistence while search/read/MCP remain path-compatible, and future-source scope remains deferred rather than partially implemented.

---

_Verified: 2026-05-05T21:44:39Z_
_Verifier: the agent (gsd-verifier)_
