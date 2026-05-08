---
phase: 32
phase_name: source-capability-registry
status: passed
verified_at: 2026-05-08T13:46:00Z
requirements:
  SRC-01: passed
  SRC-02: passed
  SRC-03: passed
  SRC-04: passed
must_haves_verified: 15
must_haves_total: 15
human_verification: []
gaps: []
---

# Phase 32 Verification: Source Capability Registry

## Verdict

Passed. Phase 32 delivers the planned declarative source capability registry:
typed descriptor models, closed capability vocabulary, filesystem and Telegram
registry seeds, provider-description compatibility, and Airweave mapping docs.

## Requirement Traceability

| Requirement | Status | Evidence |
|---|---|---|
| SRC-01 | Passed | `SourceDescriptor`, display/config/auth/cursor schema models, and `ApplicationSourceDescription.from_descriptor()` are implemented in `backend/src/dotmd/core/models.py`. |
| SRC-02 | Passed | `default_source_registry()` registers filesystem and Telegram descriptors in `backend/src/dotmd/ingestion/source_registry.py`. |
| SRC-03 | Passed | `SourceCapability` is a closed enum with exact assertions in `backend/tests/ingestion/test_source_registry.py`. |
| SRC-04 | Passed | `docs/source-registry-airweave-mapping.md` maps Airweave source metadata into copied/adapted/rejected/deferred dotMD concepts. |

## Must-Haves

- D-01 passed: Airweave is principles-first reference material, not a copied schema.
- D-02 passed: Phase 32 uses source catalog entries, schemas, capability flags, browse-tree, federated-search, ACL, and incremental-sync markers.
- D-03 passed: Airweave runtime/product subsystems are rejected or deferred in docs.
- D-04 passed: descriptors are declarative only; no provider factories, credential access, or cursor persistence were added.
- D-05 passed: lifecycle construction and cursor commit behavior remain Phase 33 scope.
- D-06 passed: descriptor schemas are structural Pydantic models.
- D-07 passed: capability flags are a closed enum.
- D-08 passed: capability vocabulary covers local sync, federated search, read-unit windows, materialization, browse trees, ACL, and incremental cursors.
- D-09 passed: new capabilities require model changes.
- D-10 passed: filesystem and Telegram have detailed seed entries.
- D-11 passed: filesystem paths remain internal holder mechanics.
- D-12 passed: Telegram remains behind `mcp-telegram`.
- D-13 passed: Airweave mapping table exists.
- D-14 passed: mapping table classifies concepts as copied, adapted, rejected, or deferred.
- D-15 passed: mapping explains local refs, retained artifacts, typed Pydantic contracts, and no runtime Airweave dependency.

## Automated Checks

- `cd backend && uv run pytest tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py -q` - passed.
- `cd backend && uv run pyright src/dotmd/core/models.py src/dotmd/core/source_registry.py src/dotmd/ingestion/source_registry.py src/dotmd/ingestion/source_provider.py src/dotmd/ingestion/telegram_provider.py tests/ingestion/test_source_registry.py tests/ingestion/test_source_filesystem.py tests/ingestion/test_application_source_provider.py tests/ingestion/test_telegram_provider.py` - passed.
- `rg -n "dotMD has no runtime Airweave dependency|copied|adapted|rejected|deferred" docs/source-registry-airweave-mapping.md` - passed.
- `rg -n "Phase 32|source registry|Phase 33|mcp-telegram" docs/source-adapter-architecture.md` - passed.
- `rg -n "from airweave|import airweave" backend/src backend/tests` - passed with no matches.
- `rg -n "supports_browse_tree|output_entity_definitions|class_name|feature_flag" backend/src backend/tests` - passed with no matches.

## TDD Gate

| Plan | RED | GREEN | Status |
|---|---|---|---|
| 32-01 | `2e09fed` | `ea272a6` | Pass |
| 32-02 | `9059cf7` | `797aeea` | Pass |
| 32-03 | `0fc446b` | `d053e97` | Pass |

## Notes

- Repo-wide `cd backend && uv run pyright` still reports pre-existing unrelated
  type errors outside Phase 32's changed files. Scoped pyright for all Phase 32
  code and tests passes.
- Security enforcement is enabled and no `32-SECURITY.md` exists yet; run
  `$gsd-secure-phase 32` before advancing beyond execution gates that require
  security verification.

