---
phase: 27-resource-bindings-retained-artifacts-foundation
verified: 2026-05-07T15:57:45Z
status: passed
score: 9/9 must-haves verified
overrides_applied: 0
deferred:
  - truth: "Telegram provider contract, ingestion, and fixture adapter behavior"
    addressed_in: "Phase 28 and Phase 29"
    evidence: "Phase 28 goal defines the application source provider contract; Phase 29 goal ingests selected synced Telegram dialogs/messages."
  - truth: "Live Telegram smoke and public Telegram search/read/drill round-trip"
    addressed_in: "Phase 31"
    evidence: "Phase 31 goal hardens and verifies search(query) -> ref -> drill(ref) / read(ref, start, end), including live smoke against deployed mcp-telegram."
---

# Phase 27: Resource Bindings and Retained Artifacts Foundation Verification Report

**Phase Goal:** Add the generic storage and service foundation that separates active source-resource visibility from retained content and derived artifacts, so resource churn does not force recomputation of already processed content.
**Verified:** 2026-05-07T15:57:45Z
**Status:** passed
**Re-verification:** No - initial verification

## Goal Achievement

### Observable Truths

| # | Truth | Status | Evidence |
|---|---|---|---|
| 1 | Generic resource binding state exists for active/inactive visibility. | VERIFIED | `ResourceBinding` has `namespace`, `resource_ref`, `document_ref`, `active`, timestamps, fingerprints, source-unit refs, and lifecycle metadata in `backend/src/dotmd/core/models.py:116`. SQLite creates `resource_bindings` plus active and fingerprint indexes in `backend/src/dotmd/storage/metadata.py:125`. |
| 2 | Existing source documents are backfilled into active bindings without recomputation. | VERIFIED | Store initialization ensures `resource_bindings` and calls `backfill_resource_bindings_from_source_documents` in `backend/src/dotmd/storage/metadata.py:328`; the backfill copies persisted SQLite metadata only and documents no source-file reads or derived-artifact rebuilds in `backend/src/dotmd/storage/metadata.py:590`. |
| 3 | Active bindings are the public search/read/drill visibility gate. | VERIFIED | Public search filters fused candidates through `get_active_chunk_provenance_for_chunk_ids` before rerank/hydration in `backend/src/dotmd/api/service.py:539`; `read` and `drill` both call `_require_active_source_document` before filesystem fallback or file reads in `backend/src/dotmd/api/service.py:847`, `backend/src/dotmd/api/service.py:879`, and `backend/src/dotmd/api/service.py:917`. |
| 4 | Normal filesystem unbind hides public output without deleting retained artifacts. | VERIFIED | Deleted paths route to `_deactivate_filesystem_binding`, while modified paths still use `_purge_file`, in `backend/src/dotmd/ingestion/pipeline.py:1538`. `_deactivate_filesystem_binding` only upserts an inactive binding and does not call holder cleanup or graph delete helpers in `backend/src/dotmd/ingestion/pipeline.py:2321`. Tests assert retained source/provenance/chunk/FTS/vector rows and no graph delete calls in `backend/tests/ingestion/test_pipeline_purge.py`. |
| 5 | Same-path equivalent filesystem rebind reuses retained artifacts with zero TEI recomputation. | VERIFIED | `_rebind_retained_filesystem_document` matches inactive binding fingerprints, reuses retained chunk refs, records reused chunks/embeddings, restores provenance, activates the binding, and saves fingerprints in `backend/src/dotmd/ingestion/pipeline.py:910`. Tests assert unchanged rebind keeps chunk IDs and `encode_calls == []` in `backend/tests/ingestion/test_source_filesystem.py:363`. |
| 6 | Cross-path equivalent filesystem rebind reuses retained artifacts with zero TEI recomputation. | VERIFIED | If no binding exists for the new path, rebind looks up inactive bindings by content and metadata fingerprints, reads chunk refs from the retained resource path, and writes active provenance for the new path in `backend/src/dotmd/ingestion/pipeline.py:924`. The cross-path regression asserts new path provenance points to the new ref, chunk refs match the retained refs, and `encode_calls == []` in `backend/tests/ingestion/test_source_filesystem.py:423`. |
| 7 | Shared retained content remains visible through another active binding. | VERIFIED | Active provenance joins `chunk_source_provenance_<strategy>` to `resource_bindings` with `rb.active = 1` in `backend/src/dotmd/storage/metadata.py:698`. The shared-chunk test proves inactive-only chunks are hidden while a shared chunk resolves to the active file in `backend/tests/storage/test_metadata_m2m.py:337`. |
| 8 | Diagnostics are count-only and no inactive browsing/recycle-bin surface ships. | VERIFIED | `binding_diagnostics` returns only `active`, `inactive`, `retained`, and `reused` counts in `backend/src/dotmd/api/service.py:936`. Grep found no `include_inactive`, `list_inactive`, inactive browsing, or recycle-bin runtime surface in `backend/src/dotmd`; docs mention those terms only as deferred/out-of-scope. |
| 9 | Phase 27 does not require full reindex and does not implement Telegram ingestion/deleted-message semantics. | VERIFIED | Schema changes are idempotent `CREATE TABLE IF NOT EXISTS`/backfill paths; service filtering is read-side; rebind uses retained rows instead of TEI. Docs explicitly state Phase 27 is filesystem foundation only and defer Telegram ingestion/export/deletion policy/live smoke in `docs/source-adapter-architecture.md:73` and `docs/architecture.md:230`. |

**Score:** 9/9 truths verified

### Deferred Items

Items not yet met but explicitly addressed in later milestone phases.

| # | Item | Addressed In | Evidence |
|---|---|---|---|
| 1 | Telegram provider contract and ingestion | Phase 28 / Phase 29 | Phase 28 defines the application source provider contract; Phase 29 ingests selected synced Telegram dialogs/messages from `mcp-telegram`. |
| 2 | Live Telegram smoke and public Telegram round-trip | Phase 31 | Phase 31 verifies `search(query) -> ref -> drill(ref) / read(ref, start, end)` and live `mcp-telegram` smoke. |

### Required Artifacts

| Artifact | Expected | Status | Details |
|---|---|---|---|
| `backend/src/dotmd/core/models.py` | Resource binding domain model | VERIFIED | `ResourceBinding` is substantive and validates refs. |
| `backend/src/dotmd/storage/metadata.py` | Binding schema, backfill, active provenance, diagnostics | VERIFIED | Table/indexes/backfill/helper methods are present and used by service/pipeline. |
| `backend/src/dotmd/ingestion/pipeline.py` | Active upsert, inactive unbind, retained rebind | VERIFIED | Successful indexing upserts active bindings; missing paths deactivate; retained rebind handles same-path and cross-path equivalent content. |
| `backend/src/dotmd/api/service.py` | Public active filtering and active read/drill resolver | VERIFIED | Search filters before rerank/hydration; read/drill reject inactive refs before filesystem fallback. |
| `backend/src/dotmd/search/fusion.py` | Hydrates public results from active provenance map | VERIFIED | `build_search_results` accepts `provenance_map` and raises on missing provenance. |
| Phase 27 test files | Regression coverage for storage, pipeline, search/API/MCP | VERIFIED | Focused suite passed: `133 passed, 75 warnings in 6.72s`. |
| `docs/source-adapter-architecture.md` / `docs/architecture.md` | Document shipped boundary and deferred Telegram/GC scope | VERIFIED | Docs state active bindings, retained artifacts, no full reindex, and Telegram deferral. |

### Key Link Verification

| From | To | Via | Status | Details |
|---|---|---|---|---|
| `SQLiteMetadataStore.__init__` | Existing `source_documents` | `backfill_resource_bindings_from_source_documents` | WIRED | Existing documents get active bindings before active filtering can hide them. |
| `IndexingPipeline` successful filesystem indexing | `resource_bindings` | `_upsert_active_filesystem_binding` / `upsert_resource_binding` | WIRED | Binding fingerprints come from the same `SourceDocument` persisted for provenance. |
| Missing filesystem path handling | Inactive binding state | `_incremental_index` and `purge_orphaned_files` call `_deactivate_filesystem_binding` | WIRED | Normal missing-resource handling avoids hard purge. |
| Equivalent restored filesystem content | Retained chunks/embeddings | `_rebind_retained_filesystem_document` | WIRED | Fingerprint match reactivates and rewires provenance before normal recomputation. |
| Search candidates | Active public results | `_filter_active_fused_candidates` before rerank/build | WIRED | Inactive provenance is skipped; missing provenance remains an invariant error. |
| `read(ref)` / `drill(ref)` | Active binding resolver | `_require_active_source_document` | WIRED | Inactive/missing bindings raise `Unknown source ref` before filesystem fallback. |

### Data-Flow Trace (Level 4)

| Artifact | Data Variable | Source | Produces Real Data | Status |
|---|---|---|---|---|
| `ResourceBinding` storage | `active`, fingerprints, lifecycle metadata | `SourceDocument` rows and pipeline lifecycle events | Yes | FLOWING |
| Active search filtering | `active_provenance_map` | SQL join from chunk provenance to active `resource_bindings` | Yes | FLOWING |
| Retained rebind | `chunk_refs`, reused counts | Existing `chunk_file_paths`, vector metadata, inactive binding fingerprints | Yes | FLOWING |
| Public diagnostics | `active`, `inactive`, `retained`, `reused` | Store count queries and retained binding metadata | Yes | FLOWING |

### Behavioral Spot-Checks

| Behavior | Command | Result | Status |
|---|---|---|---|
| Focused Phase 27 lifecycle/search/storage/MCP tests | `uv run --directory backend pytest tests/storage/test_metadata_m2m.py tests/ingestion/test_pipeline_purge.py tests/ingestion/test_pipeline_orphan_sweep.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_metadata_only_reindex.py tests/api/test_service_search.py tests/test_fusion.py tests/mcp/test_search_tool.py -q` | `133 passed, 75 warnings in 6.72s`; warnings are existing pydantic-settings `toml_file` warnings | PASS |
| Typecheck ratchet | `just typecheck` | `pyright ratchet: 66 errors (baseline 69); improvements: -3 across 2 files` | PASS |
| Lint | `just lint` | `All checks passed!` | PASS |
| Public inactive browsing grep | `rg "include_inactive|list_inactive|inactive browsing|recycle-bin|recycle bin" backend/src/dotmd docs/...` | No runtime public browsing flags; docs hits are deferred/out-of-scope wording | PASS |

### Requirements Coverage

| Requirement | Source Plan | Description | Status | Evidence |
|---|---|---|---|---|
| R1 | Plans 27-01 through 27-04 | Resource binding foundation | SATISFIED | Generic `ResourceBinding` and `resource_bindings` support arbitrary namespaces, filesystem is wired end-to-end, active bindings gate search/read, unbind retains artifacts, equivalent rebind reuses retained chunks/embeddings, and filesystem behavior remains covered by regression tests. Telegram runtime behavior is intentionally deferred to Phases 28-31. |
| R2 | Plans 27-01 through 27-04 | Retained derived artifacts | SATISFIED | Inactive retained content is excluded from public output, retained identity uses content/metadata fingerprints, GC is not part of normal missing-resource handling, and unchanged rebind avoids TEI recomputation. |
| R8 | Plans 27-01 through 27-04 | Validation and smoke | SATISFIED FOR PHASE 27 | Unit/integration coverage for binding lifecycle, reuse, active filtering, read/drill rejection, shared chunks, and no-TEI rebind passed. Typecheck/lint passed. Live Telegram smoke is explicitly Phase 31, not Phase 27. |

### Anti-Patterns Found

| File | Line | Pattern | Severity | Impact |
|---|---:|---|---|---|
| `backend/src/dotmd/ingestion/pipeline.py` | 698 | `embeddings.append([])  # placeholder; filled below` | INFO | Local allocation placeholder overwritten in the same embedding path; not user-visible and not a stub. |
| Multiple storage/service helpers | various | Empty `return {}` / `return []` for empty inputs | INFO | Guard clauses for empty query/input sets; not hardcoded public data. |

No blocker anti-patterns found.

### Human Verification Required

None. Phase 27 is backend/storage/API behavior with focused fixture coverage. Runtime Telegram smoke is deferred to Phase 31 by roadmap scope.

### Gaps Summary

No blocking gaps found. The phase goal is achieved in the codebase: active bindings are the public visibility gate, retained inactive artifacts remain available for reuse but hidden from public search/read/drill, equivalent same-path and cross-path filesystem rebinds avoid TEI recomputation, and Telegram ingestion/inactive browsing are not shipped in Phase 27.

---

_Verified: 2026-05-07T15:57:45Z_
_Verifier: the agent (gsd-verifier)_
