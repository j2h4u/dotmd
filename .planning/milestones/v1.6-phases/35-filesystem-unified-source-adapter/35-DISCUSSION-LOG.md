# Phase 35: Filesystem unified source adapter - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-05-10
**Phase:** 35-filesystem-unified-source-adapter
**Areas discussed:** Refactoring depth, Private method bridge, In-flight trickle paths, Regression test scope

---

## Refactoring depth

### Q1 — Pipeline internals placement

| Option | Description | Selected |
|--------|-------------|----------|
| Stay in pipeline | Orchestration concerns; adapter produces SourceDocument, pipeline decides what to do with it | ✓ |
| Move to adapter or lifecycle bundle | Richer adapter, but inverts dependency direction (adapter gets SQLiteMetadataStore dependency) | |

**User's choice:** Stay in pipeline
**Notes:** Clean dependency direction preserved. `_filesystem_chunk_provenance`, `_upsert_active_filesystem_binding`, `_rebind_retained_filesystem_document(s)`, `_deactivate_filesystem_binding` all stay in `IndexingPipeline`.

---

### Q2 — Interpretation of "no bypass" (FS-03)

| Option | Description | Selected |
|--------|-------------|----------|
| Narrow — no direct instantiation | If adapter object obtained through lifecycle bundle, all access is acceptable | |
| Broad — any access through public interface | Private method names (underscore prefix) are also a form of bypass; rename to public | ✓ |

**User's choice:** Broad interpretation
**Notes:** The `_` removal is what satisfies "public interface." The construction boundary (lifecycle) is what matters for bypass; but private naming on methods called externally is also addressed.

---

### Q3 — `document_for_file_info` in protocol or on concrete class

| Option | Description | Selected |
|--------|-------------|----------|
| Add to SourceAdapterProtocol | Formal contract; all future adapters must implement | |
| Public method on concrete class only | ISP + LSP: Telegram has no FileInfo concept | ✓ |

**User's choice:** Expert panel invoked (user couldn't decide alone)
**Expert panel verdict (Architect + Kaizen + QA, unanimous):** Public method on `FilesystemMarkdownSourceAdapter` only. Filesystem-specific method must not pollute generic discovery protocol. `SourceAdapterProtocol` stays at `discover()` + `discover_multi()`. The `_` removal satisfies the "public interface" requirement; protocol membership is a separate concern.

---

## Private method bridge

### Q1 — `source_document_to_file_info()` fate

| Option | Description | Selected |
|--------|-------------|----------|
| Keep — paths needed inside | FS-02 explicitly allows paths where required; function is already public | ✓ |
| Remove — use `document.file_path` directly | Pipeline can read `.file_path` without round-trip conversion | |

**User's choice:** Expert panel invoked (mini-panel, 2 voices)
**Mini-panel verdict:** Keep. The function carries a validation invariant beyond conversion: `document_ref` must match resolved `file_path`. This prevents silent drift bugs. Use `document.file_path` directly only where the full `FileInfo` round-trip is unnecessary.

---

## In-flight trickle paths

### Q1 — Is `index_file(Path)` from trickle a bypass?

| Option | Description | Selected |
|--------|-------------|----------|
| No — Path is an OS trigger | Inside `index_file` processing goes through lifecycle; raw path is inotify API | ✓ |
| Yes — trickle should call `bundle.source.discover([path])` | Explicit adapter-protocol call from trickle | |

**User's choice:** Initially attracted to option 2; expert panel invoked
**Mini-panel verdict (Architect + Kaizen):** Option 1. `discover_multi()` is a batch/directory API; calling it with a single event path is semantically awkward. Adding `discover_one()` to the protocol would violate ISP (Telegram can't implement it meaningfully). The lifecycle boundary is respected internally inside `index_file`. inotify path = OS event, not source identity.

---

## Regression test scope

### Q1 — What should regression coverage cover?

| Option | Description | Selected |
|--------|-------------|----------|
| Existing tests are sufficient | If pipeline tests pass after refactoring, FS-01 is proven | |
| Targeted tests on new boundary | `document_for_file_info` public method + lifecycle construction path | ✓ |
| E2E through lifecycle factory | Full SourceRuntimeFactory → discovery → index → search round-trip | |

**User's choice:** Targeted tests on new boundary

---

### Q2 — How to verify absence of direct instantiation?

| Option | Description | Selected |
|--------|-------------|----------|
| Behavioral test through lifecycle | `SourceRuntimeFactory.build("filesystem")` → `document_for_file_info()` works | ✓ |
| Grep guard test | Test greps codebase for `FilesystemMarkdownSourceAdapter()` outside lifecycle | |

**User's choice:** Behavioral test through lifecycle
**Notes:** Grep guard tests are fragile (break on rename, can't handle string contexts). Behavioral test proves the path works; that's sufficient.

---

## Claude's Discretion

- Whether existing tests that directly instantiate `FilesystemMarkdownSourceAdapter()` (if any exist) should be updated to go through `SourceRuntimeFactory` — agent should grep and decide.
- Which callers of `source_document_to_file_info()` can be simplified to `document.file_path` direct access vs. which need the full `FileInfo` validation.
- Test file placement (existing module vs. new file in `backend/tests/ingestion/`).

## Deferred Ideas

- `discover_one(path: Path) -> SourceDocument | None` — single-file discovery API on `SourceAdapterProtocol`. Would require protocol changes; out of scope for Phase 35.
- Grep guard tests — reviewed and explicitly rejected as fragile; behavioral tests preferred.
