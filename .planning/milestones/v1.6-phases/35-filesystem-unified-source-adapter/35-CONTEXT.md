# Phase 35: Filesystem unified source adapter - Context

**Gathered:** 2026-05-10
**Status:** Ready for planning

<domain>
## Phase Boundary

Route all filesystem indexing, reads, delete detection, and content-addressed
reuse through the Phase 33 lifecycle/registry boundary without breaking current
trickle, search, read, parser routing, or rebind behavior.

Concretely: no `FilesystemMarkdownSourceAdapter` is instantiated outside
`source_lifecycle.py`; all adapter methods accessed from pipeline are public
(no `_` prefix); pipeline orchestration methods stay in pipeline.

This phase is NOT a deep restructuring of pipeline internals, NOT a refactor of
trickle's event model, NOT a new discovery API shape, and NOT the Telegram or
Airweave work (Phases 36–37).

</domain>

<decisions>
## Implementation Decisions

### Refactoring Depth

- **D-01:** `_filesystem_chunk_provenance`, `_upsert_active_filesystem_binding`,
  `_rebind_retained_filesystem_document(s)`, and `_deactivate_filesystem_binding`
  stay in `IndexingPipeline`. These are orchestration concerns — the adapter
  produces `SourceDocument`, the pipeline decides what to do with it.
  Moving them into the adapter would invert the dependency direction
  (`FilesystemMarkdownSourceAdapter` would need `SQLiteMetadataStore`).

- **D-02:** FS-03 "no bypass" is interpreted **broadly**: any access to adapter
  behavior must be through a public interface (naming: no `_` prefix). The
  relevant boundary is the lifecycle construction boundary — if an object is
  obtained through `SourceRuntimeFactory.build("filesystem")`, calling its
  public methods is not a bypass. Protocol membership is a separate concern
  from public naming.

- **D-03:** `_from_file_info` on `FilesystemMarkdownSourceAdapter` is renamed to
  `document_for_file_info` (public). It is **not** added to `SourceAdapterProtocol`.
  Rationale (expert panel, ISP + LSP): `FileInfo` is a filesystem concept;
  Telegram (Phase 36) has no `FileInfo`. Adding a filesystem-specific method to
  the generic discovery protocol would require all future adapters to implement
  a method with no meaning in their domain. `SourceAdapterProtocol` stays at
  `discover()` + `discover_multi()` only.

### Adapter Bridge

- **D-04:** `source_document_to_file_info(document: SourceDocument) -> FileInfo`
  stays in `source.py`. It carries a validation invariant beyond conversion:
  `document_ref` must match the resolved `file_path`. This prevents silent bugs
  if the two drift. Use `document.file_path` directly only in places where only
  the path is needed and the invariant check is redundant.

### In-Flight Trickle Paths

- **D-05:** `index_file(Path)` called from the trickle watcher is **not a bypass**.
  inotify delivers a raw OS path as the event — there is no alternative. The
  lifecycle boundary is respected inside `index_file` (discovery goes through
  the `SourceRuntimeFactory` bundle). Requiring trickle to call
  `bundle.source.discover([path])` first would demand a `discover_one()` method
  on the protocol (not scoped to this phase, would violate ISP for Telegram),
  with no behavioral benefit.

### Regression Test Scope

- **D-06:** Existing pipeline integration tests are the primary proof of FS-01
  (behavior preserved after refactoring). No new E2E trickle tests are required
  unless a behavioral gap is found during implementation.

- **D-07:** Add targeted tests on the new public boundary:
  1. `FilesystemMarkdownSourceAdapter.document_for_file_info(file_info)` is
     accessible and produces a correct `SourceDocument` (replaces the former
     private method test surface).
  2. `SourceRuntimeFactory.build("filesystem") → bundle.source.document_for_file_info()`
     works end-to-end through the lifecycle construction path.

- **D-08:** No grep-based guard tests. Behavioral tests through the lifecycle
  factory are the appropriate proof. If a direct instantiation reappears, the
  failing behavioral test (not a grep) will catch it.

### Claude's Discretion

- Whether any existing tests that currently instantiate `FilesystemMarkdownSourceAdapter()`
  directly (bypassing lifecycle) should be updated to go through
  `SourceRuntimeFactory` — agent should grep for this and decide.
- Exact scope of callers to migrate from `source_document_to_file_info()` to
  direct `document.file_path` access — apply only where the full `FileInfo`
  round-trip is unnecessary.
- Naming of the new test file or existing test module where targeted tests land.

### Reviewed Todos (not folded)

- `soft-delete-with-ttl-for-removed-source-files.md` — not folded. FS-01 requires
  delete detection to *continue to work*; it does not require adding TTL semantics.
  Soft-delete with TTL is a separate feature.
- `background-trickle-indexer.md` — not folded; trickle behavior is unchanged.
- `evaluate-pplx-embed-context-as-e5-large-replacement.md` — not folded; unrelated.

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Milestone and Phase Definition

- `.planning/ROADMAP.md` — Phase 35 goal, dependency on Phase 33, requirement
  mapping (FS-01, FS-02, FS-03), and success criteria.
- `.planning/REQUIREMENTS.md` — FS-01 through FS-03 v1.6 filesystem unification
  requirements. Read the exact requirement text before planning — particularly
  FS-02 ("paths only where still required") and FS-03 ("no bypass").
- `.planning/STATE.md` — Current workflow state and milestone progress.

### Prior Source Architecture Decisions

- `.planning/phases/33-source-lifecycle-config-auth-cursor-boundary/33-CONTEXT.md`
  — Lifecycle bundle shape, `SourceRuntimeFactory`, `FilesystemSourceConfig`,
  `source_runtime_factory_from_settings`. Phase 35 routes through this boundary.
  Specifically: D-13 (filesystem does not own provider cursor commits), D-16
  (paths remain internal holder mechanics).
- `.planning/phases/32-source-capability-registry/32-CONTEXT.md` — Descriptor
  stays declarative; registry owns namespace lookup. Phase 35 must not change
  the filesystem descriptor.
- `.planning/phases/34-federated-searchcandidate-contract/34-CONTEXT.md` —
  `SearchCandidate` contract; confirms filesystem source participates as a
  local-backed source, not a federated one.

### Current Code Surfaces

- `backend/src/dotmd/ingestion/source.py` — `FilesystemMarkdownSourceAdapter`
  (has `_from_file_info` to be renamed), `SourceAdapterProtocol` (stays
  minimal: `discover` + `discover_multi`), `source_document_to_file_info`
  (stays with validation invariant).
- `backend/src/dotmd/ingestion/source_lifecycle.py` — `SourceRuntimeFactory`,
  `SourceRuntimeBundle`, `source_runtime_factory_from_settings`. The only place
  `FilesystemMarkdownSourceAdapter()` should be instantiated.
- `backend/src/dotmd/ingestion/source_registry.py` — `filesystem_source_descriptor()`
  and `default_source_registry()`. Read-only in this phase; no descriptor changes.
- `backend/src/dotmd/ingestion/pipeline.py` — `IndexingPipeline`: contains all
  `_filesystem_*` methods that stay here; already calls
  `_source_runtime_factory.build("filesystem")` in `_discover_filesystem_documents`,
  `_discover_filesystem_documents_multi`, and `_source_document_for_file_info`.
  The `_source_document_for_file_info` method currently calls
  `bundle.source._from_file_info()` — this is the primary call site to update.
- `backend/src/dotmd/ingestion/trickle.py` — File watcher; calls `index_file(Path)`.
  No change required; raw path input from inotify is an OS event, not a bypass.

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets

- `SourceRuntimeFactory.build("filesystem")` already exists and already produces
  a `SourceRuntimeBundle` with a live `FilesystemMarkdownSourceAdapter` inside
  `bundle.source`. Phase 35 expands what's callable on that object, it does not
  replace the factory.
- `_discover_filesystem_documents` and `_discover_filesystem_documents_multi`
  in `pipeline.py` already go through lifecycle — they are correct examples of
  the pattern to apply to `_source_document_for_file_info`.
- `source_document_to_file_info()` already validates the `document_ref` ↔
  `file_path` invariant — no new validation logic needed.

### Established Patterns

- dotMD prefers small Protocol/Pydantic boundaries over broad plugin frameworks.
  `SourceAdapterProtocol` stays minimal; concrete class carries filesystem-specific
  public methods.
- Public behavior flows through `DotMDService`, CLI, MCP, FastAPI; internals
  do not become public integration APIs.
- Filesystem paths are internal holder mechanics — they stay in `SourceDocument.file_path`
  and in pipeline orchestration, not in the public source identity.
- Invariant by construction: structural impossibility preferred over runtime
  monitors. The lifecycle factory is the single construction point; expanding
  the public API of the adapter (D-03) makes the invariant structurally visible.

### Integration Points

- `pipeline._source_document_for_file_info()` is the primary call site to
  migrate from `bundle.source._from_file_info()` to
  `bundle.source.document_for_file_info()`.
- Targeted tests land in `backend/tests/ingestion/` alongside existing source
  and lifecycle tests.
- No changes required to `mcp_server.py`, `api/service.py`, `search/`, or
  `storage/` — Phase 35 is entirely within `ingestion/`.

### Anti-Patterns To Avoid

- Do not add `document_for_file_info` to `SourceAdapterProtocol` — ISP + LSP
  violation for future non-filesystem adapters (Telegram has no `FileInfo`).
- Do not move `_filesystem_*` pipeline methods into the adapter or lifecycle
  bundle — dependency direction inversion.
- Do not require trickle to call `bundle.source.discover([path])` for
  single-file events — no `discover_one()` exists; scope creep.
- Do not remove `source_document_to_file_info()` — it carries the document_ref
  ↔ file_path validation invariant, not just conversion.

</code_context>

<specifics>
## Specific Ideas

- The user explicitly chose the broad interpretation of FS-03: "any access must
  be through a public interface." This means removing all `_` prefixes from
  adapter methods that are called externally — the rename is the deliverable,
  not adding to the protocol.
- Expert panel (ISP + LSP) drove D-03: filesystem-specific methods must not
  pollute the generic discovery protocol. The protocol is a discovery contract;
  the lifecycle bundle is the construction contract.
- The user confirmed that `source_document_to_file_info()` carries validation
  beyond conversion — the mini-panel recommendation to retain it was accepted.

</specifics>

<deferred>
## Deferred Ideas

- **`discover_one(path: Path) -> SourceDocument | None`** — a single-file
  discovery method on `SourceAdapterProtocol`. Would make trickle's call site
  cleaner but requires protocol changes and doesn't exist yet. Out of scope for
  Phase 35; revisit when trickle's event model is reviewed.
- **Grep guard tests** — test that asserts no direct `FilesystemMarkdownSourceAdapter()`
  instantiation outside `source_lifecycle.py`. Fragile (breaks on rename,
  can't handle string contexts). Out of scope; behavioral tests are sufficient.

### Reviewed Todos (not folded)

- `2026-03-28-soft-delete-with-ttl-for-removed-source-files.md` — not folded.
  FS-01 requires delete detection to continue working, not to add TTL semantics.
  Separate feature; reviewed and explicitly left out of Phase 35.
- `2026-03-27-background-trickle-indexer.md` — not folded; trickle behavior
  is unchanged by this phase.
- `2026-03-30-evaluate-pplx-embed-context-as-e5-large-replacement.md` — not
  folded; embedding model evaluation is unrelated to filesystem unification.

</deferred>

---

*Phase: 35-Filesystem unified source adapter*
*Context gathered: 2026-05-10*
