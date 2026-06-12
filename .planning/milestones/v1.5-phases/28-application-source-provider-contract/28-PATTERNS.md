# Phase 28 Pattern Map: Application Source Provider Contract

**Generated:** 2026-05-07
**Purpose:** Give executors exact local analogs before implementing Phase 28 plans.

## Files To Create Or Modify

| Target | Role | Closest Existing Analog | Notes |
|--------|------|-------------------------|-------|
| `backend/src/dotmd/core/models.py` | Add provider payload models and `SourceUnit.updated_at` | `SourceDocument`, `ResourceBinding`, `ChunkProvenance` | Use `ConfigDict(extra="forbid")` and `@model_validator(mode="after")` for ref invariants. |
| `backend/src/dotmd/ingestion/source_provider.py` | New application provider protocol and fixture provider | `backend/src/dotmd/ingestion/source.py` | Keep application sync separate from filesystem discovery. Use `Protocol` and deterministic fixture classes. |
| `backend/src/dotmd/storage/metadata.py` | Add source checkpoint and source-unit fingerprint tables/helpers | Resource binding helpers and source document helpers | Additive `CREATE TABLE IF NOT EXISTS`, caller-owned transaction helpers, JSON via `json.dumps(..., sort_keys=True)`. |
| `backend/tests/ingestion/test_application_source_provider.py` | Contract and fixture tests | `backend/tests/ingestion/test_source_filesystem.py`, `backend/tests/storage/test_metadata_m2m.py` | Tests should import public models/protocols and use fixture data only. |
| `backend/tests/storage/test_metadata_m2m.py` | Storage regression tests | Existing `TestResourceBindings` and provenance tests | Add tests near resource binding/source document sections. |
| `docs/mcp-telegram-source-contract.md` | mcp-telegram payload note | `docs/source-adapter-architecture.md` | Concrete examples only; no mcp-telegram implementation plan. |
| `docs/source-adapter-architecture.md` | Update Phase 28 delivered/planned contract | Phase 26/27 delivered sections | Record the minimal method set and cursor semantics. |
| `docs/architecture.md` | High-level source adapter update | Future Source Adapters section | Short summary of the provider contract boundary. |

## Pattern Details

### Pydantic Ref Validation

`SourceDocument` and `ResourceBinding` validate `ref == f"{namespace}:{document_ref}"`. New provider payloads should reuse that convention and avoid source-specific Telegram fields in generic models.

### Transaction-Owned Storage Helpers

Current helpers such as `upsert_source_document(document, *, conn)` and `upsert_resource_binding(binding, *, conn)` require the caller to own transaction boundaries. Phase 28 checkpoint helpers should follow that pattern so `checkpoint_cursor` is saved only after the matching local persistence succeeds.

### Active Fixture Testing

The storage tests use small helper constructors such as `_source_document`, `_resource_binding`, and `_build_m2m_store`. Phase 28 should add analogous constructors for application source units and avoid live daemons, containers, or `mcp-telegram` runtime dependencies.

### Documentation Verification

Phase 27 docs plans used grep-style checks for forbidden scope. Phase 28 docs should similarly assert:

- `docs/mcp-telegram-source-contract.md` contains `checkpoint_cursor`.
- It contains `read_unit_window`.
- It maps Telegram dialog to `SourceDocument` and Telegram message to `SourceUnit`.
- It says dotMD does not read private `mcp-telegram` SQLite tables.
- It does not claim Telegram ingestion shipped in Phase 28.

## Risk Notes

- `SourceUnit` currently lacks `updated_at`, which D-14 requires. Add it with focused tests.
- `DotMDService.read()` is currently filesystem-only after active binding resolution. Do not wire Telegram reads in Phase 28; the provider contract and fixture `read_unit_window()` are enough.
- `mcp-telegram` already has useful raw message fields, but existing tools are rendered for humans. Do not plan dotMD indexing against formatted text responses.
